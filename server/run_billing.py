"""Server/agent glue for run-level billing (see server/run_budget.py and docs/BILLING.md).

Client payload rules, enforced here and by tests/test_run_billing.py:
* integer cents, fee-inclusive, one price per step;
* no fee amounts or percentages, no provider/vendor/model names in billing data, no tool vendor fields;
* line labels describe the work.
Voice consent notices name the upload destination as required for recorded consent.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from typing import Any

from server import run_budget as rb

logger = logging.getLogger(__name__)
_MEDIA_WORK: ContextVar[tuple[str, str] | None] = ContextVar("run_billing_media_work", default=None)


def billing_applies(repo: Any, user_id: str | None) -> bool:
    """Same gate as media billing: Stripe on, or a beta-credit account."""
    if not user_id:
        return False
    from server.beta_credits import beta_billing_enabled
    from server.billing import stripe_enabled

    return bool(stripe_enabled() or beta_billing_enabled(repo, user_id))


# --------------------------------------------------------------------------- run lifecycle (server side)


def start_run(
    repo: Any, user_id: str | None, run_id: str, conversation_id: str | None, *, autonomous_media_cents: int = 0,
) -> dict[str, Any] | None:
    """Hold credit for a run before it starts.  Idempotent; a resumed job adopts the held run.

    Raises InsufficientCreditError when the default cap cannot be held.
    """
    if not billing_applies(repo, user_id):
        return None
    assert user_id
    existing = repo.get_run_hold(run_id)
    if existing and existing["state"] == "held":
        repo.touch_run_hold(run_id)
        return existing
    if conversation_id and repo.adopt_conversation_hold(user_id, conversation_id, run_id):
        return repo.get_run_hold(run_id)
    estimate = autonomous_media_cents + (rb.orchestration_estimate_cents() if rb.orchestration_billing_enabled() else 0)
    return repo.hold_run(user_id, run_id, rb.default_cap_cents(estimate) if estimate else 0,
                         estimate_cents=estimate, conversation_id=conversation_id)


def end_run(repo: Any, run_id: str, *, execution_status: str, error_type: str | None = None) -> dict[str, Any] | None:
    """Release what the run did not spend and store its receipt, unless it is only paused."""
    hold = repo.get_run_hold(run_id)
    if hold is None or hold["state"] != "held":
        return None
    if execution_status == "awaiting_approval" or hold["status"] == "paused_cap":
        repo.touch_run_hold(run_id)
        return None
    if execution_status == "completed":
        status = "done"
    elif error_type == "UserStopped":
        status = "stopped"
    else:
        status = "failed"
    return repo.release_run(run_id, status=status)


# --------------------------------------------------------------------------- pricing of pending approvals

# Worst-case holds for steps the price tables cannot quote (fee-inclusive integer cents).
# With a hard $10 beta credit an unpriced step must never be approvable, so when a quote fails the
# step is held at a conservative ceiling for its type instead.  That hold is the step's cap and the
# runner cuts the step off there.  Derived from server/billing_rates.py (all fee-inclusive):
# * video: the dearest per-second 1080p rate in the tables is 28 c/s (aleph2); 10 s plus the fee is
#   about $3.64, rounded up to $4.00.  Lip-sync, avatar, upscale and edit jobs are video-sized too.
# * image: dearest still is about 26 c with fee (high-quality edits); held at $0.50.
# * audio (speech, voice, music, sound effects): dearest quoted track is under $0.40; held at $0.50.
# Anything that matches none of these has no hold, so it cannot be approved at all.
WORST_CASE_HOLD_CENTS = {"video": 400, "image": 50, "audio": 50}
_VIDEO_WORDS = ("video", "lipsync", "lip_sync", "avatar", "dialogue", "upscale", "extend", "motion", "act_two", "aleph", "reframe", "v2a")
_IMAGE_WORDS = ("image", "still", "vector", "rmbg", "background", "logo")
_AUDIO_WORDS = ("speech", "tts", "voice", "music", "sfx", "sound", "audio", "song")
UNPRICEABLE_MESSAGE = "This step can’t be priced, so it can’t be approved. Nothing was charged."


def step_kind(tool_name: str) -> str | None:
    name = (tool_name or "").lower()
    if any(word in name for word in _VIDEO_WORDS):
        return "video"
    if any(word in name for word in _IMAGE_WORDS):
        return "image"
    if any(word in name for word in _AUDIO_WORDS):
        return "audio"
    return None


def worst_case_hold_cents(tool_name: str) -> int | None:
    kind = step_kind(tool_name)
    return WORST_CASE_HOLD_CENTS.get(kind) if kind else None


def step_quote(item: dict[str, Any]) -> tuple[int | None, str]:
    """(cents, basis): "fixed" for a real price, "up_to" for a worst-case hold, "none" when neither exists."""
    price = _step_price(item)
    if price is not None:
        return price, "fixed"
    hold = worst_case_hold_cents(str(item.get("tool_name") or ""))
    return (hold, "up_to") if hold is not None else (None, "none")


def unpriceable(raw_approvals: list[dict[str, Any]], call_id: str | None = None) -> bool:
    """True when a live paid step has neither a price nor a worst-case hold."""
    for item in raw_approvals:
        if item.get("kind") == "question" or item.get("decision") == "reject" or item.get("tool_name") == "review_finishing_preview":
            continue
        if call_id is not None and item.get("call_id") != call_id:
            continue
        if step_quote(item)[1] == "none":
            return True
    return False


def _step_price(item: dict[str, Any]) -> int | None:
    from agent.deep_agent.routing import estimate_cost

    if item.get("tool_name") == "review_finishing_preview":
        return 0
    try:
        return estimate_cost(str(item.get("tool_name") or ""), item.get("arguments") or {}).total_cents
    except Exception:  # noqa: BLE001 - an unpriceable step is reported as unknown, never guessed
        logger.warning("Could not price approval %s", item.get("call_id"))
        return None


def _hold_numbers(repo: Any, user_id: str | None, run_id: str) -> dict[str, int]:
    hold = repo.get_run_hold(run_id)
    held = hold["held_cents"] if hold and hold["state"] == "held" else 0
    charged = hold["charged_cents"] if hold and hold["state"] == "held" else 0
    if not user_id:
        return {"held": held, "charged": charged, "beyond": 0, "spendable": 0}
    beyond = max(0, repo.available_credit(user_id, exclude_run=run_id) - max(0, held - charged))
    return {"held": held, "charged": charged, "beyond": beyond, "spendable": repo.spendable_credit(user_id)}


def plan_for_pending(repo: Any, run_id: str, raw_approvals: list[dict[str, Any]]) -> rb.RunPlan | None:
    pending = [a for a in raw_approvals if a.get("kind") != "question" and a.get("decision") != "reject"
               and a.get("tool_name") != "review_finishing_preview"]
    if not pending:
        return None
    media_lines = []
    for item in pending:
        cents, basis = step_quote(item)
        label, detail = rb.work_label(str(item.get("tool_name") or ""), item.get("arguments"))
        # A worst-case hold enters the plan at its full amount, so the run cap always covers it.
        media_lines.append(rb._line(label, cents or 0, "media", "fixed" if basis == "fixed" else "estimate", detail))
    hold = repo.get_run_hold(run_id)
    spent_rows = repo.run_lines(run_id) if hold else []
    plan = rb.plan_run(media_lines=media_lines, spent_rows=spent_rows,
                       existing_held_cents=hold["held_cents"] if hold and hold["state"] == "held" else 0)
    if any(step_quote(item)[1] == "up_to" for item in pending):
        # One number: an up-to step is already its worst case, so the cap IS the "Up to" total.
        # (Before: "Up to $4.50" cap vs a "$4.32" estimate in the warning.)
        plan = replace(plan, cap_cents=max(plan.estimate_cents, plan.spent_cents))
    return plan


def up_to_floor_cents(repo: Any, run_id: str, raw_approvals: list[dict[str, Any]]) -> int | None:
    """Lowest cap an up-to plan accepts: the fixed-priced part plus 1 cent of the up-to work.

    The runner stops at the cap, so "Up to $X · we'll stop there" stays true at a lower cap.
    """
    pending = [a for a in raw_approvals if a.get("kind") != "question" and a.get("decision") != "reject"
               and a.get("tool_name") != "review_finishing_preview"]
    holds = [step_quote(item)[0] or 0 for item in pending if step_quote(item)[1] == "up_to"]
    if not holds:
        return None
    plan = plan_for_pending(repo, run_id, raw_approvals)
    return max(1, plan.estimate_cents - sum(holds) + 1) if plan else None


def public_approvals(
    repo: Any, *, run_id: str, user_id: str | None, execution_status: str, error_type: str | None,
    raw_approvals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Client approval cards with neutral billing data and required voice consent notices."""
    if not raw_approvals:
        return []
    questions = []
    for item in raw_approvals:
        if item.get("kind") == "question":
            from agent.deep_agent.questions import StudioQuestionRequest
            safe = {**item, 'question': rb.neutral_error(item.get('question'), 'Which outcome do you prefer?'),
                    'options': [{**option,
                        'label': rb.neutral_error(option.get('label'), f'Option {index + 1}'),
                        'description': rb.neutral_error(option.get('description'), '')}
                        for index, option in enumerate(item.get('options') or [])]}
            question = StudioQuestionRequest.model_validate(safe).model_dump()
            question["decision"] = item.get("decision")
            question["status"] = "answered" if item.get("decision") == "answer" else (
                "pending" if execution_status == "awaiting_approval" else "closed")
            if item.get("answer") is not None:
                question["answer"] = StudioQuestionRequest.model_validate(safe).validate_answer(item["answer"]).model_dump()
            questions.append(question)
    raw_approvals = [item for item in raw_approvals if item.get("kind") != "question"]
    if not raw_approvals:
        return questions
    plan = plan_for_pending(repo, run_id, raw_approvals)
    numbers = _hold_numbers(repo, user_id, run_id)
    hold = repo.get_run_hold(run_id)
    paused = bool(hold and hold["status"] == "paused_cap")
    remaining_estimate = max(0, plan.estimate_cents - plan.spent_cents) if plan else 0
    remaining_cap = max(0, plan.cap_cents - plan.spent_cents) if plan else 0
    extra_needed = max(0, (plan.cap_cents if plan else 0) - numbers["held"])
    applies = billing_applies(repo, user_id)
    can_afford = (not applies) or extra_needed <= numbers["beyond"]
    insufficient = None
    if plan and not can_afford:
        insufficient = rb.insufficient_credit_payload(
            estimate_cents=plan.estimate_cents, cap_cents=plan.cap_cents,
            available_cents=numbers["beyond"], held_cents=numbers["held"],
            floor_cents=up_to_floor_cents(repo, run_id, raw_approvals),
        )
    live = [a for a in raw_approvals if a.get("decision") != "reject"
            and a.get("tool_name") != "review_finishing_preview"]
    output = []
    for item in raw_approvals:
        label, detail = rb.work_label(str(item.get("tool_name") or ""), item.get("arguments"))
        decision = item.get("decision")
        if decision == "reject":
            status = "rejected"
        elif decision == "approve":
            status = {"completed": "done", "error": "paused_cap" if paused else "failed"}.get(
                execution_status, "running" if execution_status in {"running", "queued"} else "approved")
        else:
            status = "pending" if execution_status == "awaiting_approval" else "failed"
        if item.get("tool_name") == "review_finishing_preview":
            comparison = rb.scrub_arguments(item.get("arguments")).get("comparison")
            fields = {
                "before_version_id", "after_version_id", "duration_seconds", "source_start_seconds",
                "full_estimated_cost_cents", "source_width", "source_height", "output_width",
                "output_height", "source_fps", "output_fps",
                "covers_full_source",
            }
            output.append({
                "call_id": item.get("call_id"), "tool_name": "review_finishing_preview",
                "label": "Review finishing preview", "status": status, "decision": decision,
                "arguments": {"comparison": {key: value for key, value in comparison.items() if key in fields}
                              if isinstance(comparison, dict) else None},
                "step_price_cents": 0, "approve_enabled": status == "pending",
            })
            continue
        price, price_basis = step_quote(item)
        entry: dict[str, Any] = {
            "call_id": item.get("call_id"),
            "label": label,
            "status": status,
            "decision": decision,
            "arguments": rb.scrub_arguments(item.get("arguments")),
            "step_price_cents": price,
            "price_basis": price_basis,
            "step_index": (live.index(item) + 1) if item in live else None,
            "step_count": len(live),
        }
        if detail:
            entry["detail"] = detail
        if price_basis == "none" and status == "pending":
            entry.update({"approve_enabled": False, "unpriceable": True, "unpriceable_message": UNPRICEABLE_MESSAGE})
        if isinstance(item.get("message"), str):
            entry["message"] = rb.scrub_client_text(item["message"], "Review this step before it runs.")
        if item.get("tool_name") in {"HeyGen___voice_clone", "HeyGen___voice_tts"}:
            _, marker, notice = str(item.get("description") or "").partition("Voice owner:")
            if marker:
                estimate = item.get("estimated_cost") or {}
                cents = estimate.get("total_cents")
                cost = f"Estimated cost ${cents / 100:.2f} USD." if isinstance(cents, (int, float)) else "Estimated cost unknown."
                entry["message"] = f"Voice owner:{notice} {cost}"
        if plan and status in {"pending", "approved", "running"}:
            entry.update({
                "estimate_cents": plan.estimate_cents,
                "cap_cents": plan.cap_cents,
                "lines": rb.public_lines(plan.lines),
                "held_cents": numbers["held"],
                "spent_so_far_cents": plan.spent_cents,
                "balance_cents": numbers["beyond"],
                "balance_after_estimate_cents": max(0, numbers["spendable"] - remaining_estimate),
                "balance_after_cap_cents": max(0, numbers["spendable"] - remaining_cap),
                "approve_enabled": status == "pending" and insufficient is None and price_basis != "none",
                "insufficient_credit": insufficient if status == "pending" else None,
                "raise_options_cents": [],
                "estimate_incomplete": price_basis == "none",
                "up_to": price_basis == "up_to",
                "hold_only": price_basis == "up_to",
            })
        output.append(entry)
    return output + questions


def paused_cap_view(repo: Any, run_id: str) -> dict[str, Any] | None:
    hold = repo.get_run_hold(run_id)
    if not hold or hold["status"] != "paused_cap" or hold["state"] != "held":
        return None
    return build_paused_payload(repo, hold)


def build_paused_payload(repo: Any, hold: dict[str, Any]) -> dict[str, Any]:
    run_id = hold["run_id"]
    lines = rb.lines_from_rows(repo.run_lines(run_id))
    beyond = max(0, repo.available_credit(hold["user_id"], exclude_run=run_id)
                 - max(0, hold["held_cents"] - hold["charged_cents"]))
    payload = rb.paused_cap_payload(
        run_id=run_id, cap_cents=hold["held_cents"], charged_cents=hold["charged_cents"], lines=lines,
        balance_cents=beyond, held_cents=hold["held_cents"],
    )
    payload["add_credit"] = not payload["raise_options_cents"]
    return payload


def approval_gate(
    repo: Any, *, run_id: str, user_id: str, conversation_id: str | None,
    raw_approvals: list[dict[str, Any]], requested_cap_cents: int | None,
) -> dict[str, Any] | None:
    """Hold the cap when the user approves.  Returns the hold, or raises InsufficientCreditError/ValueError."""
    if unpriceable(raw_approvals):
        raise ValueError(UNPRICEABLE_MESSAGE)
    if not billing_applies(repo, user_id):
        return None
    plan = plan_for_pending(repo, run_id, raw_approvals)
    if plan is None:
        return None
    cap = plan.cap_cents if requested_cap_cents is None else requested_cap_cents
    floor = up_to_floor_cents(repo, run_id, raw_approvals)
    if cap < (plan.estimate_cents if floor is None else floor):
        raise ValueError("The cap cannot be lower than the estimated total.")
    if repo.get_run_hold(run_id) is None and conversation_id:
        repo.adopt_conversation_hold(user_id, conversation_id, run_id)
    return repo.hold_run(user_id, run_id, cap, estimate_cents=plan.estimate_cents, conversation_id=conversation_id)


def precheck_start(repo: Any, user_id: str | None, conversation_id: str | None) -> dict[str, Any] | None:
    """insufficient_credit payload when a new run's default cap cannot be held, else None."""
    if not billing_applies(repo, user_id):
        return None
    assert user_id
    if conversation_id and repo.conversation_has_hold(user_id, conversation_id):
        return None
    estimate = rb.orchestration_estimate_cents() if rb.orchestration_billing_enabled() else 0
    cap = rb.default_cap_cents(estimate) if estimate else 0
    available = repo.available_credit(user_id)
    if cap > available:
        return rb.insufficient_credit_payload(estimate_cents=estimate, cap_cents=cap, available_cents=available)
    return None


def insufficient_for(
    repo: Any, run_id: str, exc: rb.InsufficientCreditError, raw_approvals: list[dict[str, Any]],
    requested_cap_cents: int | None,
) -> dict[str, Any]:
    plan = plan_for_pending(repo, run_id, raw_approvals)
    estimate = plan.estimate_cents if plan else 0
    cap = requested_cap_cents if requested_cap_cents is not None else (plan.cap_cents if plan else exc.needed_cents)
    hold = repo.get_run_hold(run_id)
    held = hold["held_cents"] if hold and hold["state"] == "held" else 0
    return rb.insufficient_credit_payload(
        estimate_cents=estimate, cap_cents=cap, available_cents=exc.available_cents, held_cents=held)


def insufficient_for_raise(repo: Any, run_id: str, exc: rb.InsufficientCreditError, new_cap_cents: int) -> dict[str, Any]:
    hold = repo.get_run_hold(run_id) or {}
    return rb.insufficient_credit_payload(
        estimate_cents=int(hold.get("estimate_cents") or 0), cap_cents=new_cap_cents,
        available_cents=exc.available_cents, held_cents=int(hold.get("held_cents") or 0))


def raise_cap(repo: Any, run_id: str, user_id: str, new_cap_cents: int) -> dict[str, Any]:
    """Explicit user action: raise the run's cap to a new TOTAL, bounded by available credit."""
    hold = repo.get_run_hold(run_id)
    if hold is None or hold["user_id"] != user_id or hold["state"] != "held":
        raise KeyError("Run not found")
    if new_cap_cents <= hold["held_cents"]:
        raise ValueError("The new cap must be higher than the current cap.")
    return repo.hold_run(user_id, run_id, new_cap_cents, estimate_cents=hold["estimate_cents"])


# --------------------------------------------------------------------------- agent side


class RunMeter:
    """Meters planner cost and gates paid steps against the run's hard cap and held credit."""

    def __init__(self, repo: Any, user_id: str, run_id: str) -> None:
        self.repo = repo
        self.user_id = user_id
        self.run_id = run_id
        self.pause: dict[str, Any] | None = None

    @classmethod
    def for_run(cls, repo: Any, user_id: str | None, run_id: str | None) -> RunMeter | None:
        if not user_id or not run_id:
            return None
        hold = repo.get_run_hold(run_id)
        if hold is None or hold["state"] != "held" or hold["user_id"] != user_id:
            return None
        return cls(repo, user_id, run_id)

    def _hold(self) -> dict[str, Any]:
        hold = self.repo.get_run_hold(self.run_id)
        if hold is None or hold["state"] != "held":
            raise rb.RunBudgetError("This run has no active credit hold.")
        return hold

    def remaining_cap_cents(self) -> int:
        return self.snapshot()["remaining_cents"]

    def snapshot(self) -> dict[str, int]:
        return self.repo.run_budget_snapshot(self.run_id)

    def reserve_work(
        self, work_id: str, cost_cents: int, *, kind: str, role: str, allow_existing: bool = True,
    ) -> dict[str, Any]:
        try:
            return self.repo.reserve_run_work(self.user_id, self.run_id, work_id, cost_cents, kind=kind,
                                              role=role, allow_existing=allow_existing)
        except rb.RunCapExceededError:
            raise rb.RunPausedAtCap(self._pause()) from None

    def settle_work(
        self, work_id: str, *, model_cost_usd: float = 0, compute_cost_usd: float = 0,
        usage: dict[str, Any] | None = None,
    ) -> Any:
        return self.repo.settle_run_work(self.user_id, self.run_id, work_id, model_cost_usd=model_cost_usd,
                                         compute_cost_usd=compute_cost_usd, usage=usage)

    def fail_work(self, work_id: str, usage: dict[str, Any] | None = None) -> None:
        """A transport error cannot prove that the model did no billable work."""
        self.repo.mark_run_work_ambiguous(self.run_id, work_id, usage)

    def reserve_media(self, call_id: str, price_cents: int | None, tool_name: str | None = None) -> dict[str, Any]:
        if price_cents is None and tool_name:
            price_cents = worst_case_hold_cents(tool_name)  # the hold is the step's cap
        if price_cents is None:
            raise rb.RunPausedAtCap(self._pause())
        return self.reserve_work("media:" + call_id, price_cents, kind="media", role="paid_dispatch", allow_existing=False)

    def complete_media(self, call_id: str, *, definitely_not_started: bool = False) -> None:
        work_id = "media:" + call_id
        if definitely_not_started:
            self.repo.charge_usage(self.user_id, 0, "generation", run_id=self.run_id, _work_id=work_id,
                                   _work_usage={"status": "not_started"})
        else:
            self.fail_work(work_id)

    @contextmanager
    def media_dispatch(self, call_id: str, price_cents: int | None, tool_name: str | None = None):
        """Bridge the preflight quote (or worst-case hold) to the charge in the host's async dispatch stack."""
        self.reserve_media(call_id, price_cents, tool_name)
        token = _MEDIA_WORK.set((self.run_id, "media:" + call_id))
        try:
            yield
        finally:
            _MEDIA_WORK.reset(token)
            self.complete_media(call_id)

    def _pause(self) -> dict[str, Any]:
        hold = self._hold()
        self.repo.set_run_pause(self.run_id, None)
        payload = build_paused_payload(self.repo, hold)
        self.repo.set_run_pause(self.run_id, payload)
        self.pause = payload
        return payload

    def check_step(self, price_cents: int | None) -> dict[str, Any] | None:
        """Before a paid step: run spend + step must fit the cap.  Returns a paused_cap payload if not."""
        if price_cents is None:
            return self._pause()
        if price_cents > self.remaining_cap_cents():
            return self._pause()
        return None

    def check_turn(self) -> dict[str, Any] | None:
        """Before an agent turn: nothing left under the cap means stop (the next turn would be unbillable)."""
        if rb.orchestration_billing_enabled() and self.remaining_cap_cents() <= 0:
            return self._pause()
        return None

    def meter_turn(self, model_cost_usd: float | None) -> dict[str, Any] | None:
        """Charge the planner turn (fee-inclusive, clipped to the cap).  Returns a paused_cap payload at the cap."""
        if not rb.orchestration_billing_enabled() or not model_cost_usd or model_cost_usd <= 0:
            return None
        cumulative = self.repo.add_run_model_cost(self.run_id, float(model_cost_usd))
        target = rb.orchestration_total_cents(cumulative)
        already = sum(int(line["cents"]) for line in self.repo.run_lines(self.run_id)
                      if line["kind"] == "orchestration" and not line["refunded_at"])
        delta = target - already
        if delta <= 0:
            return None
        remaining = self.remaining_cap_cents()
        charge = min(delta, remaining)
        if charge > 0:
            self.repo.charge_usage(
                self.user_id, charge, "orchestration", run_id=self.run_id,
                line_kind="orchestration", line_label=rb.ORCHESTRATION_LABEL,
            )
        if delta > remaining:
            return self._pause()
        return None

    def raise_if_paused(self) -> None:
        if self.pause is not None:
            raise rb.RunPausedAtCap(self.pause)


def charge_media(
    repo: Any, user_id: str, run_id: str | None, cost_cents: int, tool_name: str,
    arguments: dict[str, Any] | None, call_id: str | None = None,
) -> Any:
    """Charge one paid media step inside the run's hold; hard-stops at the cap (RunPausedAtCap)."""
    meter = RunMeter.for_run(repo, user_id, run_id)
    if meter is None:
        return repo.charge_usage(user_id, cost_cents, "generation")
    scope = _MEDIA_WORK.get()
    work_id = scope[1] if scope is not None and scope[0] == run_id else None
    if work_id is None and call_id is not None:
        existing = next((row for row in repo.run_work(run_id) if row["work_id"] == "media:" + call_id), None)
        if existing:
            work_id = existing["work_id"]
    if work_id is None:
        paused = meter.check_step(cost_cents)
        if paused:
            raise rb.RunPausedAtCap(paused)
    if work_id is not None:
        # Never charge a step more than what was reserved for it (its price or worst-case hold).
        reserved = next((int(row["reserved_cents"]) for row in repo.run_work(run_id)
                         if row["work_id"] == work_id and row["reserved_cents"] is not None), None)
        if reserved is not None and cost_cents > reserved:
            logger.warning("Clipped charge for %s to its %s c hold", work_id, reserved)
            cost_cents = reserved
    label, detail = rb.work_label(tool_name, arguments)
    try:
        return repo.charge_usage(
            user_id, cost_cents, "generation", run_id=run_id, line_kind="media", line_label=label,
            line_detail=detail, call_id=call_id,
            _work_id=work_id,
        )
    except rb.RunCapExceededError:
        raise rb.RunPausedAtCap(meter._pause()) from None


def stored_pause(repo: Any, run_id: str | None) -> dict[str, Any] | None:
    """The paused_cap payload recorded for a run (set by any process sharing the database)."""
    hold = repo.get_run_hold(run_id) if run_id else None
    if hold and hold["state"] == "held" and hold["status"] == "paused_cap" and hold["pause_json"]:
        import json

        return json.loads(hold["pause_json"])
    return None


_TEXT_KEYS = frozenset({"error", "reason", "message", "note", "detail", "summary", "status_message", "warning"})
# Agent-written prose shown to the customer: scrubbed sentence-by-sentence instead of replaced.
_PROSE_KEYS = frozenset({"title", "summary", "markdown", "text", "content", "response", "final_response", "message", "body"})
_PATH_KEYS = frozenset({"output_path", "local_path", "path", "file_path", "video_path", "audio_path", "image_path"})


def _clean_result(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in _PATH_KEYS and isinstance(item, str):
                continue
            if isinstance(item, str) and item and key in _PROSE_KEYS:
                out[key] = rb.scrub_client_text(item, rb.NEUTRAL_ERROR if key in _TEXT_KEYS else "")
            elif isinstance(item, str) and item and key in _TEXT_KEYS:
                out[key] = rb.neutral_error(rb.scrub_client_text(item, rb.NEUTRAL_ERROR))
            elif key in {"provider", "model", "model_id", "voice_id", "endpoint_id"}:
                continue
            else:
                out[key] = _clean_result(item)
        return out
    if isinstance(value, list):
        return [_clean_result(item) for item in value]
    return value


def public_execution(execution: dict[str, Any] | None) -> dict[str, Any] | None:
    """Client view of an execution: tool labels describe the work, vendor fields and vendor/fee text are removed.

    The machine ``name`` of a tool call is kept because Studio uses it for canvas logic; clients must not display it.
    """
    if execution is None:
        return None
    cleaned = dict(execution)
    calls = []
    for call in execution.get("tool_calls") or []:
        label, detail = rb.work_label(str(call.get("name") or ""), call.get("arguments"))
        shown = f"{label} · {detail}" if detail else label
        calls.append({**call, "label": shown, "provider": None,
                      "summary": rb.neutral_error(call.get("summary"), f"{label} finished."),
                      "result": _clean_result(call.get("result") or {})})
    if "tool_calls" in cleaned:
        cleaned["tool_calls"] = calls
    if "events" in cleaned:
        events = []
        for event in execution.get("events") or []:
            title = event.get("title")
            if event.get("tool_call_name"):
                label, _ = rb.work_label(str(event["tool_call_name"]), None)
                title = rb.scrub_client_text(title) or label
            events.append({**event, "title": rb.scrub_client_text(title, "Update"),
                           "message": rb.scrub_client_text(event.get("message"), "Working on it."),
                           **({"tool_call_name": event.get("tool_call_name")} if "tool_call_name" in event else {})})
        cleaned["events"] = events
    if isinstance(cleaned.get("message"), str):
        cleaned["message"] = rb.scrub_client_text(cleaned["message"], "Update")
    if isinstance(cleaned.get("result"), dict):
        cleaned["result"] = _clean_result(cleaned["result"])
    if isinstance(cleaned.get("result"), str):
        cleaned["result"] = rb.scrub_client_text(cleaned["result"])
    return cleaned
