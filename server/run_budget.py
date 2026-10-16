"""Run-level billing: orchestration metering, wallet holds, caps and receipts.

Everything a customer can see about money for an agent run is produced here, as
integer cents that are already fee-inclusive.  The platform fee, the upstream
vendor and the model that did the work are backend-only: they are used to
compute a price and are never copied into a client payload.  See docs/BILLING.md.

Hold model
----------
* ``run_holds`` has one row per agent run (the execution/job id).  ``held_cents``
  is the run's hard cap; ``charged_cents`` is what has actually been debited.
* While a hold is active, ``held_cents - charged_cents`` is *reserved*: other runs
  and other charges cannot spend it, so the wallet can never go negative and two
  concurrent runs can never spend the same credit.
* Charges for the run go through ``charge_usage(..., run_id=...)`` which refuses
  to exceed the cap.  At the end of the run the unused part is released.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any

ORCHESTRATION_LABEL = "Planning and checks"
NEUTRAL_ERROR = "This step could not be completed."
PAUSED_MESSAGE = "The next step needs more than the remaining cap. No further work has started."

# Words that must never reach a client.  Vendor / model / infrastructure names,
# plus fee wording.  Matched case-insensitively on word boundaries.
CLIENT_DENY_LIST = (
    "wan", "wan2", "wan3", "seedance", "kling", "runway", "luma", "vidu", "seedream", "gpt", "gpt-image",
    "openai", "elevenlabs", "eleven", "eleven labs", "fish audio", "fish_audio", "fal", "fal.ai",
    "anthropic", "claude", "sonnet", "opus", "haiku", "remotion", "heygen", "mureka", "mirelo",
    "topaz", "sync", "sync labs", "gemini", "ideogram", "recraft", "byteplus", "dashscope",
    "alibaba", "modelstudio", "hyperframes", "bedrock", "agentcore", "lambda", "stripe",
    "provider", "upstream", "third party", "third-party", "vendor",
    "platform fee", "service fee", "fee", "fees", "markup", "margin", "30%",
)
_DENY_RE = re.compile(
    r"(?<![\w])(?:" + "|".join(re.escape(word) for word in sorted(CLIENT_DENY_LIST, key=len, reverse=True)) + r")(?![\w])"
    r"|\b\d{1,3}\s?%\s*(?:fee|platform|markup)",
    re.IGNORECASE,
)
# Argument keys that identify a vendor/model; dropped from client-visible argument echoes.
_VENDOR_KEYS = frozenset({
    "provider", "provider_id", "model", "model_id", "model_name", "endpoint", "endpoint_id", "vendor",
    "voice_model", "tts_model", "engine", "backend", "api", "host", "route",
})


class RunBudgetError(RuntimeError):
    """Base class; messages are client-safe."""


class InsufficientCreditError(RunBudgetError):
    def __init__(self, available_cents: int, needed_cents: int) -> None:
        super().__init__("Not enough credit for this cap.")
        self.available_cents = available_cents
        self.needed_cents = needed_cents


class RunCapExceededError(RunBudgetError):
    def __init__(self, charged_cents: int, cap_cents: int, cost_cents: int) -> None:
        super().__init__("This step would go over the hard cap.")
        self.charged_cents = charged_cents
        self.cap_cents = cap_cents
        self.cost_cents = cost_cents


class RunPausedAtCap(RunBudgetError):
    """Raised inside a run when a hard stop fires; carries the client payload."""

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(PAUSED_MESSAGE)
        self.payload = payload


# --------------------------------------------------------------------------- config


def _env_int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        raise ValueError(f"{name} must be an integer number of cents.") from None
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    return value


def orchestration_billing_enabled() -> bool:
    """ORCHESTRATION_BILLING_ENABLED (default true)."""
    return os.getenv("ORCHESTRATION_BILLING_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def orchestration_estimate_cents() -> int:
    """Planning estimate, not a measurement or authorization to exceed the hard cap."""
    return _env_int("ORCHESTRATION_ESTIMATE_CENTS", orchestration_estimate_assumptions()["total_cents"])


def local_compute_usd_per_second() -> float:
    """Optional configured compute estimate. Zero records usage without assigning a price."""
    value = float(os.getenv("ORCHESTRATION_LOCAL_USD_PER_SECOND", "0"))
    if not math.isfinite(value) or value < 0:
        raise ValueError("ORCHESTRATION_LOCAL_USD_PER_SECOND must be finite and non-negative.")
    return value


def orchestration_estimate_assumptions() -> dict[str, Any]:
    from agent.deep_agent.usage import MODEL_RATES

    rates = MODEL_RATES["claude-sonnet-5-5"]
    calls, rubric_calls, summary_calls, local_actions = 16, 3, 2, 12
    input_tokens, output_tokens = 6_000, 4_000
    model_usd = (calls + rubric_calls + summary_calls) * (input_tokens * rates.input + output_tokens * rates.output) / 1_000_000
    local_seconds = local_actions * 10
    compute_usd = local_seconds * local_compute_usd_per_second()
    return {
        "basis": "planning_assumptions_not_measurements", "manager_and_subagent_calls": calls,
        "rubric_calls": rubric_calls, "summary_calls": summary_calls, "input_tokens_per_call": input_tokens,
        "output_tokens_per_call_including_thinking": output_tokens, "effort": "high",
        "local_actions": local_actions, "local_seconds": local_seconds,
        "local_compute_usd_per_second": local_compute_usd_per_second(),
        "local_compute_basis": "configured_estimate" if compute_usd else "unpriced_usage_units_only",
        "total_cents": orchestration_total_cents(model_usd + compute_usd),
    }


def cap_factor() -> float:
    raw = os.getenv("ORCHESTRATION_CAP_FACTOR", "1.4").strip()
    try:
        value = float(raw)
    except ValueError:
        raise ValueError("ORCHESTRATION_CAP_FACTOR must be a number.") from None
    if not 1.0 <= value <= 10.0:
        raise ValueError("ORCHESTRATION_CAP_FACTOR must be between 1.0 and 10.")
    return value


def cap_round_cents() -> int:
    return _env_int("ORCHESTRATION_CAP_ROUND_CENTS", 25, minimum=1)


def start_cap_floor_cents() -> int:
    """Lowest hold a new run starts with. Each planner call reserves its worst case (often $1-2) before
    it starts and is refunded to the actual (a few cents), so a smaller start cap pauses real first turns."""
    return _env_int("ORCHESTRATION_START_CAP_FLOOR_CENTS", 0)


def raise_step_cents() -> int:
    return _env_int("ORCHESTRATION_RAISE_STEP_CENTS", 50, minimum=1)


def hold_ttl_seconds() -> int:
    return _env_int("ORCHESTRATION_HOLD_TTL_SECONDS", 6 * 3600, minimum=60)


def autonomous_media_cents() -> int:
    """Media allowance held for an autonomous run (no approval card sets its cap).

    RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS (the existing autonomous spend cap) wins; otherwise
    ORCHESTRATION_AUTONOMOUS_MEDIA_CENTS (default 300).
    """
    raw = os.getenv("RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS", "").strip()
    if raw:
        if not raw.isdigit():
            raise ValueError("RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS must be a non-negative integer.")
        return int(raw)
    return _env_int("ORCHESTRATION_AUTONOMOUS_MEDIA_CENTS", 300)


def default_cap_cents(estimate_cents: int) -> int:
    """Estimate x ORCHESTRATION_CAP_FACTOR rounded up to the next ORCHESTRATION_CAP_ROUND_CENTS.

    $1.05 estimate -> 147 -> $1.50.  ORCHESTRATION_HARD_CAP_CENTS (> 0) overrides it, but never
    below the estimate.
    """
    override = _env_int("ORCHESTRATION_HARD_CAP_CENTS", 0)
    step = cap_round_cents()
    cap = math.ceil(round(estimate_cents * cap_factor(), 6) / step) * step
    if override:
        cap = override
    return max(cap, estimate_cents)


def orchestration_total_cents(cumulative_model_usd: float) -> int:
    """Fee-inclusive cents for the cumulative planner model cost of a run (one backend fee rate)."""
    from server.billing_rates import MIN_FEE_CENTS, PLATFORM_FEE_RATE

    if cumulative_model_usd <= 0:
        return 0
    provider_cents = round(cumulative_model_usd * 100, 6)
    total = provider_cents + max(MIN_FEE_CENTS, provider_cents * PLATFORM_FEE_RATE)
    return max(1, math.ceil(round(total, 6)))


# --------------------------------------------------------------------------- scrubbing


def is_client_safe(text: object) -> bool:
    return not isinstance(text, str) or _DENY_RE.search(text) is None


def neutral_error(text: object, fallback: str = NEUTRAL_ERROR) -> str:
    """Pass a message through only if it contains no vendor/model/fee wording."""
    if isinstance(text, str) and text.strip() and is_client_safe(text):
        return text
    return fallback


_TOOL_ID_RE = re.compile(r"`?\b[A-Za-z][A-Za-z0-9]*___[A-Za-z0-9_]+\b`?")
_PATH_RE = re.compile(r"`?(?:file://)?(?:~|\.{1,2})?/(?:[\w.@+-]+/)+[\w.@+-]*`?")
_MODEL_ID_RE = re.compile(r"`?\b(?:" + "|".join(re.escape(word) for word in sorted(
    (w for w in CLIENT_DENY_LIST if re.fullmatch(r"[a-z0-9]+", w)), key=len, reverse=True)) + r")[_.-][\w.-]+`?", re.I)
_INTERNAL_TERMS_RE = re.compile(
    r"\b(?:inspect_media|stage_media|report_progress|read_file|write_file|not_run|job directory|native arguments|"
    r"capability map|routing policy|gateway|mcp|sandbox|checkpoint)\b", re.I)
_TOKEN_COST_RE = re.compile(r"\b(?:model|token|llm)s?\b[^.\n]{0,40}\bcosts?\b|\bestimates? include\b", re.I)
_SENTENCE_SPLIT_RE = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"”')\]]))\s+(?=[\"“(*`]*[A-Z0-9])")
_MARK = "\u2063internal\u2063"


def scrub_client_text(text: object, fallback: str = "") -> str:
    """Remove vendor/model names, internal tool ids, file paths and fee wording from agent text.

    Tool ids and paths are replaced with neutral words first; any sentence (or table row, list
    item, heading) that still names a vendor, model, fee or model-token cost is dropped whole, so
    the customer never sees half a sentence. Returns ``fallback`` if nothing safe is left.
    """
    if not isinstance(text, str) or not text.strip():
        return fallback if not isinstance(text, str) else text
    # Sentences that cite an internal tool id or a model id are dropped whole; a path is reworded.
    text = _TOOL_ID_RE.sub(_MARK, text)
    text = _MODEL_ID_RE.sub(_MARK, text)
    text = _PATH_RE.sub("your project", text)
    text = _INTERNAL_TERMS_RE.sub(_MARK, text)
    kept_lines = []
    for line in text.split("\n"):
        if not line.strip():
            kept_lines.append(line)
            continue
        if line.lstrip().startswith("|") or line.lstrip().startswith("#"):
            if _MARK not in line and _DENY_RE.search(line) is None and _TOKEN_COST_RE.search(line) is None:
                kept_lines.append(line)
            continue
        sentences = _SENTENCE_SPLIT_RE.split(line)
        safe = [part for part in sentences if _MARK not in part and _DENY_RE.search(part) is None
                and _TOKEN_COST_RE.search(part) is None]
        joined = " ".join(part.strip() for part in safe).strip()
        if joined and re.search(r"\w", joined.strip("-*• ")):
            indent = line[: len(line) - len(line.lstrip())]
            prefix = re.match(r"\s*(?:[-*•]|\d+[.)])\s+", line)
            if prefix and not joined.startswith(prefix.group(0).strip()):
                joined = prefix.group(0).strip() + " " + joined
            kept_lines.append(indent + joined)
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines)).strip()
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned if cleaned and _MARK not in cleaned and is_client_safe(cleaned) else fallback


def scrub_arguments(arguments: Any) -> dict[str, Any]:
    """Client-visible copy of tool arguments: vendor/model keys dropped, recursively."""
    if not isinstance(arguments, dict):
        return {}
    cleaned: dict[str, Any] = {}
    for key, value in arguments.items():
        if str(key).lower() in _VENDOR_KEYS:
            continue
        cleaned[key] = scrub_arguments(value) if isinstance(value, dict) else value
    return cleaned


def work_label(tool_name: str, arguments: dict[str, Any] | None = None) -> tuple[str, str | None]:
    """(label, detail) describing the work of a tool call, never the vendor."""
    arguments = arguments if isinstance(arguments, dict) else {}
    name = str(tool_name or "").lower().replace("-", "_")
    verb = name.rsplit("___", 1)[-1]
    if verb == "review_drama_outline":
        return "Series outline", "Review the cast, story beats and episode synopses. No production spending."
    if verb == "validate_drama_episode":
        return "Episode plan", "Check cut timing, continuity locks and production arguments."
    seconds = next((arguments[k] for k in ("duration_seconds", "duration", "seconds", "source_duration_seconds")
                    if isinstance(arguments.get(k), (int, float)) and not isinstance(arguments.get(k), bool)), None)
    resolution = arguments.get("resolution") if isinstance(arguments.get("resolution"), str) else None
    detail_parts = []
    if seconds:
        detail_parts.append(f"{seconds:g} s")
    if resolution and is_client_safe(resolution):
        detail_parts.append(resolution)
    detail = " · ".join(detail_parts) or None
    if any(word in name for word in ("speech", "tts", "voice", "narrat")):
        return "Voiceover", detail
    if any(word in name for word in ("lyrics", "music", "song")):
        return "Music", detail
    if any(word in name for word in ("sfx", "sound", "v2a", "foley")):
        return "Sound effects", detail
    if any(word in name for word in ("lipsync", "lip_sync")):
        return "Dialogue lip match", detail
    if any(word in name for word in ("upscale", "interpolate", "enhance")):
        return "Video enhancement", detail
    if any(word in name for word in ("render", "assemble", "timeline", "ad_variants", "export", "ffmpeg")):
        return "Final render", detail
    if any(word in name for word in ("avatar", "act_two", "motion_control", "performance")):
        return "Performance video", detail
    if any(word in verb for word in ("video", "t2v", "i2v", "r2v", "extend", "clip")) or "video" in name:
        return "Video clip", detail
    if any(word in name for word in ("image", "t2i", "vector", "edit", "seedream", "ideogram")):
        return "Image", None
    return "Media step", detail


# --------------------------------------------------------------------------- schema + transactional helpers


def init_run_budget_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS run_holds (
            run_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            conversation_id TEXT,
            held_cents INTEGER NOT NULL CHECK (held_cents >= 0),
            charged_cents INTEGER NOT NULL DEFAULT 0,
            estimate_cents INTEGER NOT NULL DEFAULT 0,
            model_usd REAL NOT NULL DEFAULT 0,
            state TEXT NOT NULL DEFAULT 'held',
            status TEXT NOT NULL DEFAULT 'running',
            balance_before_cents INTEGER NOT NULL DEFAULT 0,
            balance_after_cents INTEGER,
            pause_json TEXT,
            receipt_json TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            released_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS run_holds_user_state ON run_holds(user_id, state);
        CREATE TABLE IF NOT EXISTS run_lines (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            label TEXT NOT NULL,
            detail TEXT,
            cents INTEGER NOT NULL,
            call_id TEXT,
            charge_id TEXT,
            refunded_at INTEGER,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS run_lines_run ON run_lines(run_id);
        CREATE INDEX IF NOT EXISTS run_lines_charge ON run_lines(charge_id);
        CREATE TABLE IF NOT EXISTS run_work (
            run_id TEXT NOT NULL,
            work_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('model', 'local', 'media')),
            role TEXT NOT NULL,
            reserved_cents INTEGER NOT NULL CHECK(reserved_cents >= 0),
            state TEXT NOT NULL DEFAULT 'reserved' CHECK(state IN ('reserved', 'ambiguous', 'settled')),
            model_usd REAL NOT NULL DEFAULT 0,
            compute_usd REAL NOT NULL DEFAULT 0,
            usage_json TEXT,
            charge_id TEXT,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY(run_id, work_id)
        );
        CREATE INDEX IF NOT EXISTS run_work_state ON run_work(run_id, state);
        """
    )
    present = {str(row[1]) for row in connection.execute("PRAGMA table_info(usage_events)")}
    if "run_id" not in present:
        connection.execute("ALTER TABLE usage_events ADD COLUMN run_id TEXT")
    if "compute_usd" not in {str(row[1]) for row in connection.execute("PRAGMA table_info(run_holds)")}:
        connection.execute("ALTER TABLE run_holds ADD COLUMN compute_usd REAL NOT NULL DEFAULT 0")


def work_reserved_cents(connection: sqlite3.Connection, run_id: str) -> int:
    row = connection.execute(
        "SELECT COALESCE(SUM(reserved_cents), 0) FROM run_work WHERE run_id = ? AND state != 'settled'", (run_id,),
    ).fetchone()
    return int(row[0])


def spendable_cents(connection: sqlite3.Connection, user_id: str, today: str) -> int:
    """Daily allowance remaining plus wallet balance (what charge_usage can draw on)."""
    sub = connection.execute("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)).fetchone()
    daily = 0
    if sub and sub["status"] == "active":
        used = sub["daily_allowance_used_cents"] if sub["daily_allowance_reset_date"] == today else 0
        daily = max(0, sub["daily_allowance_cents"] - used)
    row = connection.execute("SELECT balance_cents FROM accounts WHERE user_id = ?", (user_id,)).fetchone()
    return daily + (int(row[0]) if row else 0)


def reserved_cents(connection: sqlite3.Connection, user_id: str, *, exclude_run: str | None = None) -> int:
    row = connection.execute(
        "SELECT COALESCE(SUM(held_cents - charged_cents), 0) FROM run_holds "
        "WHERE user_id = ? AND state = 'held' AND run_id != ?",
        (user_id, exclude_run or ""),
    ).fetchone()
    return max(0, int(row[0]))


def sweep_stale_holds(connection: sqlite3.Connection, user_id: str | None = None, *, now: int | None = None) -> int:
    """Release holds nobody has touched for ORCHESTRATION_HOLD_TTL_SECONDS (crashed runs)."""
    now = int(time.time()) if now is None else now
    cutoff = now - hold_ttl_seconds()
    where = ("state = 'held' AND updated_at < ? AND NOT EXISTS "
             "(SELECT 1 FROM run_work WHERE run_work.run_id = run_holds.run_id AND run_work.state != 'settled')"
             + (" AND user_id = ?" if user_id else ""))
    args: tuple[Any, ...] = (cutoff, user_id) if user_id else (cutoff,)
    rows = connection.execute(f"SELECT run_id FROM run_holds WHERE {where}", args).fetchall()
    for row in rows:
        connection.execute(
            "UPDATE run_holds SET state = 'released', status = CASE WHEN status IN ('running','paused_cap') "
            "THEN 'failed' ELSE status END, released_at = ?, updated_at = ? WHERE run_id = ? AND state = 'held'",
            (now, now, row["run_id"]),
        )
    return len(rows)


def apply_run_charge(
    connection: sqlite3.Connection, run_id: str, user_id: str, cost_cents: int, charge_id: str, now: int,
    *, kind: str | None, label: str | None, detail: str | None, call_id: str | None,
) -> None:
    """Called inside charge_usage's transaction: enforce the cap and record the line."""
    hold = connection.execute(
        "SELECT user_id, held_cents, charged_cents, state FROM run_holds WHERE run_id = ?", (run_id,)
    ).fetchone()
    if hold is None or hold["state"] != "held" or hold["user_id"] != user_id:
        raise RunBudgetError("This run has no active credit hold.")
    if hold["charged_cents"] + work_reserved_cents(connection, run_id) + cost_cents > hold["held_cents"]:
        raise RunCapExceededError(hold["charged_cents"], hold["held_cents"], cost_cents)
    connection.execute(
        "UPDATE run_holds SET charged_cents = charged_cents + ?, updated_at = ? WHERE run_id = ?",
        (cost_cents, now, run_id),
    )
    connection.execute("UPDATE usage_events SET run_id = ? WHERE id = ?", (run_id, charge_id))
    if kind:
        connection.execute(
            "INSERT INTO run_lines(id, run_id, kind, label, detail, cents, call_id, charge_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, run_id, kind, label or "Media step", detail, cost_cents, call_id, charge_id, now),
        )


def reverse_run_charge(connection: sqlite3.Connection, charge_id: str | None, now: int) -> None:
    """A refunded charge no longer counts against the run's cap or appears on its receipt."""
    if not charge_id:
        return
    line = connection.execute(
        "SELECT id, run_id, cents FROM run_lines WHERE charge_id = ? AND refunded_at IS NULL", (charge_id,)
    ).fetchone()
    event = connection.execute("SELECT run_id, wallet_cents + daily_cents AS total FROM usage_events WHERE id = ?",
                               (charge_id,)).fetchone()
    if line:
        connection.execute("UPDATE run_lines SET refunded_at = ? WHERE id = ?", (now, line["id"]))
    if event and event["run_id"]:
        connection.execute(
            "UPDATE run_holds SET charged_cents = MAX(0, charged_cents - ?), updated_at = ? WHERE run_id = ?",
            (int(event["total"]), now, event["run_id"]),
        )


# --------------------------------------------------------------------------- client payloads


def _line(label: str, price_cents: int, kind: str, basis: str, detail: str | None = None) -> dict[str, Any]:
    line: dict[str, Any] = {"label": label, "price_cents": int(price_cents), "kind": kind, "basis": basis}
    if detail:
        line["detail"] = detail
    return line


def lines_from_rows(rows: list[sqlite3.Row] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fee-inclusive run lines; orchestration turns are folded into one 'Planning and checks' line."""
    media = [_line(r["label"], r["cents"], "media", "fixed", r["detail"]) for r in rows
             if r["kind"] == "media" and not r["refunded_at"]]
    orchestration = sum(int(r["cents"]) for r in rows if r["kind"] == "orchestration" and not r["refunded_at"])
    if orchestration:
        media.append(_line(ORCHESTRATION_LABEL, orchestration, "orchestration", "fixed"))
    return media


def public_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in line.items() if k in {"label", "detail", "price_cents", "kind", "basis"}}
            for line in lines]


def raise_options(cap_cents: int, held_cents: int, available_cents: int) -> list[int]:
    """New TOTAL caps the user can afford: each extra over the current hold must fit in available credit."""
    step = raise_step_cents()
    options = [cap_cents + step * n for n in (1, 2)]
    return [value for value in options if value - held_cents <= available_cents]


def paused_cap_payload(
    *, run_id: str, cap_cents: int, charged_cents: int, lines: list[dict[str, Any]],
    balance_cents: int, held_cents: int,
) -> dict[str, Any]:
    return {
        "type": "paused_cap",
        "status": "paused_cap",
        "run_id": run_id,
        "message": PAUSED_MESSAGE,
        "charged_cents": charged_cents,
        "cap_cents": cap_cents,
        "held_cents": held_cents,
        "lines": public_lines(lines),
        "raise_options_cents": raise_options(cap_cents, held_cents, balance_cents),
        "balance_cents": balance_cents,
        "choices": ["raise_cap", "stop"],
    }


def insufficient_credit_payload(
    *, estimate_cents: int, cap_cents: int, available_cents: int, held_cents: int = 0,
    floor_cents: int | None = None,
) -> dict[str, Any]:
    """floor_cents: lowest acceptable cap when it is below the estimate (an up-to step stops at its cap)."""
    from server.launch_flags import topups_enabled

    extra_needed = max(0, estimate_cents - held_cents)
    can_lower = available_cents + held_cents
    topups = topups_enabled()
    return {
        "type": "insufficient_credit",
        "reason": "insufficient_credit",
        "approve_enabled": False,
        "message": "Not enough credit for this cap." if topups else "You've used your beta credit. Top-ups are coming soon.",
        "balance_cents": available_cents,
        "estimate_cents": estimate_cents,
        "cap_cents": cap_cents,
        "lower_cap_option_cents": can_lower if can_lower >= (estimate_cents if floor_cents is None else floor_cents)
                                  and can_lower < cap_cents else None,
        "add_credit": topups,
        "topups_available": topups,
        "shortfall_cents": max(0, cap_cents - held_cents - available_cents),
        "minimum_needed_cents": extra_needed,
    }


def receipt_payload(
    *, run_id: str, status: str, lines: list[dict[str, Any]], estimate_cents: int, cap_cents: int,
    balance_before_cents: int, balance_after_cents: int,
) -> dict[str, Any]:
    actual = sum(int(line["price_cents"]) for line in lines)
    return {
        "type": "receipt",
        "run_id": run_id,
        "status": "done" if status in {"done", "running"} else "failed",
        "lines": public_lines(lines),
        "actual_cents": actual,
        "estimate_cents": estimate_cents,
        "cap_cents": cap_cents,
        "under_estimate": actual <= estimate_cents,
        "balance_before_cents": balance_before_cents,
        "balance_after_cents": balance_after_cents,
    }


@dataclass(frozen=True)
class RunPlan:
    estimate_cents: int
    cap_cents: int
    lines: list[dict[str, Any]]
    pending_media_cents: int
    spent_cents: int


def plan_run(
    *, media_lines: list[dict[str, Any]], spent_rows: list[Any], existing_held_cents: int = 0,
) -> RunPlan:
    """Run-level estimate and default cap.

    estimate = what was already charged + the media still pending + the orchestration estimate (less
    what orchestration already cost, never below a quarter of it).  The lines shown add up to it.
    """
    spent_lines = lines_from_rows(spent_rows)
    orchestration_spent = sum(l["price_cents"] for l in spent_lines if l["kind"] == "orchestration")
    media_spent = [l for l in spent_lines if l["kind"] == "media"]
    estimate_orchestration = 0
    if orchestration_billing_enabled():
        base = orchestration_estimate_cents()
        estimate_orchestration = max(base - orchestration_spent, base // 4) + orchestration_spent
    lines = [*media_spent, *media_lines]
    if estimate_orchestration:
        lines.append(_line(ORCHESTRATION_LABEL, estimate_orchestration, "orchestration", "estimate"))
    estimate = sum(l["price_cents"] for l in lines)
    spent = sum(l["price_cents"] for l in spent_lines)
    cap = max(default_cap_cents(estimate), existing_held_cents)
    return RunPlan(estimate, cap, lines, sum(l["price_cents"] for l in media_lines), spent)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
