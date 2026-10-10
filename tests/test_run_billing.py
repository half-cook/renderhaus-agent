from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage

from server import run_billing, run_budget as rb
from server.studio_state import InsufficientBalanceError, StudioRepository

USER = "user:billing"
# Independent of server.run_budget.CLIENT_DENY_LIST so a weakened list cannot hide a leak.
VENDOR_RE = re.compile(
    r"wan|seedance|seedream|kling|runway|luma|vidu|openai|gpt|eleven|fish|\bfal\b|anthropic|claude|sonnet|opus|"
    r"remotion|heygen|mureka|mirelo|topaz|\bsync\b|gemini|ideogram|recraft|byteplus|dashscope|alibaba|modelstudio|"
    r"hyperframes|30%|\bfees?\b|markup|platform|provider|upstream",
    re.IGNORECASE,
)


def approval(call_id, tool, arguments=None, decision=None):
    return {"call_id": call_id, "tool_name": tool, "label": f"{tool} · Estimated cost $9.99 USD", "provider": "seedance",
            "arguments": {"prompt": "A matte-black travel mug on a desk", "duration_seconds": 5, "resolution": "720p",
                          "model": "dreamina-seedance-2-5", "provider": "fal", **(arguments or {})},
            "estimated_cost": {"provider_cents": 50, "fee_cents": 15, "total_cents": 65},
            "description": "Seedance list price plus 30% fee", "decision": decision}


PRICES = {"Seedance___image_to_video": 65, "Seedream___text_to_image": 26, "ElevenLabs___text_to_speech_convert": 2}


class Fixture:
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        path = Path(self.directory.name)
        self.repo = StudioRepository(path / "state.sqlite3", path / "media")
        self.repo.adjust_balance(USER, 1000, "test_credit")
        env = patch.dict(os.environ, {"ORCHESTRATION_BILLING_ENABLED": "true", "ORCHESTRATION_ESTIMATE_CENTS": "75"})
        env.start()
        self.addCleanup(env.stop)
        applies = patch.object(run_billing, "billing_applies", return_value=True)
        applies.start()
        self.addCleanup(applies.stop)
        price = patch.object(run_billing, "_step_price", side_effect=lambda item: PRICES.get(item["tool_name"]))
        price.start()
        self.addCleanup(price.stop)

    def ledger_sum(self, user=USER):
        with self.repo._connect() as connection:
            return connection.execute("SELECT COALESCE(SUM(delta), 0) FROM credit_ledger WHERE user_id = ?", (user,)).fetchone()[0]


class ConfigTests(Fixture, unittest.TestCase):
    def test_default_cap_is_1_4x_rounded_up_to_25_cents(self):
        self.assertEqual(rb.default_cap_cents(105), 150)
        self.assertEqual(rb.default_cap_cents(100), 150)
        self.assertEqual(rb.default_cap_cents(75), 125)
        self.assertEqual(rb.default_cap_cents(258), 375)
        self.assertEqual(rb.default_cap_cents(0), 0)

    def test_cap_is_configurable_and_never_below_estimate(self):
        with patch.dict(os.environ, {"ORCHESTRATION_CAP_FACTOR": "2", "ORCHESTRATION_CAP_ROUND_CENTS": "10"}):
            self.assertEqual(rb.default_cap_cents(105), 210)
        with patch.dict(os.environ, {"ORCHESTRATION_HARD_CAP_CENTS": "50"}):
            self.assertEqual(rb.default_cap_cents(105), 105)

    def test_invalid_values_fail_loudly(self):
        for name, value in (("ORCHESTRATION_ESTIMATE_CENTS", "abc"), ("ORCHESTRATION_ESTIMATE_CENTS", "-1"),
                            ("ORCHESTRATION_CAP_FACTOR", "0.5"), ("ORCHESTRATION_CAP_ROUND_CENTS", "0")):
            with patch.dict(os.environ, {name: value}), self.assertRaises(ValueError):
                rb.orchestration_estimate_cents()
                rb.cap_factor()
                rb.cap_round_cents()

    def test_flag(self):
        with patch.dict(os.environ, {"ORCHESTRATION_BILLING_ENABLED": "false"}):
            self.assertFalse(rb.orchestration_billing_enabled())
        with patch.dict(os.environ, {"ORCHESTRATION_BILLING_ENABLED": "true"}):
            self.assertTrue(rb.orchestration_billing_enabled())

    def test_orchestration_price_uses_the_single_fee_rate(self):
        from server import billing_rates

        self.assertEqual(rb.orchestration_total_cents(0), 0)
        self.assertEqual(rb.orchestration_total_cents(0.50), 65)
        with patch.object(billing_rates, "PLATFORM_FEE_RATE", 0.50):
            self.assertEqual(rb.orchestration_total_cents(0.50), 75)
        self.assertEqual(rb.orchestration_total_cents(0.001), 2)  # minimum fee, rounded up


class HoldTests(Fixture, unittest.TestCase):
    def test_hold_reserves_credit_and_release_returns_the_unused_part(self):
        self.repo.hold_run(USER, "run-1", 600)
        self.assertEqual(self.repo.available_credit(USER), 400)
        self.assertEqual(self.repo.get_balance(USER), 1000)
        self.repo.charge_usage(USER, 150, "generation", run_id="run-1", line_kind="media", line_label="Video clip")
        self.assertEqual(self.repo.available_credit(USER), 400)  # 850 wallet - 450 still reserved
        receipt = self.repo.release_run("run-1")
        self.assertEqual(self.repo.available_credit(USER), 850)
        self.assertEqual(receipt["actual_cents"], 150)
        self.assertEqual(self.repo.release_run("run-1"), receipt)  # idempotent

    def test_a_second_run_cannot_hold_the_same_credit(self):
        self.repo.hold_run(USER, "run-1", 700)
        with self.assertRaises(rb.InsufficientCreditError) as caught:
            self.repo.hold_run(USER, "run-2", 400)
        self.assertEqual(caught.exception.available_cents, 300)
        self.repo.hold_run(USER, "run-2", 300)

    def test_other_charges_cannot_spend_held_credit_and_wallet_never_goes_negative(self):
        self.repo.hold_run(USER, "run-1", 900)
        with self.assertRaises(InsufficientBalanceError):
            self.repo.charge_usage(USER, 150, "generation")
        self.repo.charge_usage(USER, 100, "generation")
        self.assertEqual(self.repo.get_balance(USER), 900)

    def test_hold_cannot_exceed_balance(self):
        with self.assertRaises(rb.InsufficientCreditError):
            self.repo.hold_run(USER, "run-1", 1001)
        self.assertEqual(self.repo.available_credit(USER), 1000)

    def test_raise_hold_is_bounded_by_available_credit(self):
        self.repo.hold_run(USER, "run-1", 500)
        self.repo.hold_run(USER, "run-1", 1000)
        with self.assertRaises(rb.InsufficientCreditError):
            self.repo.hold_run(USER, "run-1", 1001)
        self.assertEqual(self.repo.get_run_hold("run-1")["held_cents"], 1000)

    def test_charge_never_exceeds_the_cap(self):
        self.repo.hold_run(USER, "run-1", 100)
        self.repo.charge_usage(USER, 60, "generation", run_id="run-1", line_kind="media", line_label="Video clip")
        with self.assertRaises(rb.RunCapExceededError):
            self.repo.charge_usage(USER, 41, "generation", run_id="run-1")
        self.assertEqual(self.repo.get_balance(USER), 940)
        self.assertEqual(self.repo.get_run_hold("run-1")["charged_cents"], 60)

    def test_stale_hold_is_swept(self):
        self.repo.hold_run(USER, "run-1", 500)
        with self.repo._connect() as connection:
            connection.execute("UPDATE run_holds SET updated_at = updated_at - 100000")
        self.assertEqual(self.repo.available_credit(USER), 1000)
        self.assertEqual(self.repo.get_run_hold("run-1")["state"], "released")

    def test_concurrent_charges_in_one_run_stop_exactly_at_the_cap(self):
        self.repo.hold_run(USER, "run-1", 100)

        def charge(_):
            try:
                self.repo.charge_usage(USER, 10, "generation", run_id="run-1", line_kind="media", line_label="Image")
                return True
            except rb.RunCapExceededError:
                return False

        with ThreadPoolExecutor(20) as pool:
            results = list(pool.map(charge, range(20)))
        self.assertEqual(sum(results), 10)
        self.assertEqual(self.repo.get_balance(USER), 900)

    def test_concurrent_runs_cannot_double_spend_credit(self):
        def hold(index):
            try:
                self.repo.hold_run(USER, f"run-{index}", 400)
                return True
            except rb.InsufficientCreditError:
                return False

        with ThreadPoolExecutor(8) as pool:
            results = list(pool.map(hold, range(8)))
        self.assertEqual(sum(results), 2)
        self.assertGreaterEqual(self.repo.available_credit(USER), 0)

    def test_ledger_matches_balance_after_run(self):
        self.repo.hold_run(USER, "run-1", 300)
        self.repo.charge_usage(USER, 120, "generation", run_id="run-1", line_kind="media", line_label="Image")
        self.repo.charge_usage(USER, 33, "orchestration", run_id="run-1", line_kind="orchestration",
                               line_label=rb.ORCHESTRATION_LABEL)
        self.repo.release_run("run-1")
        self.assertEqual(self.ledger_sum(), self.repo.get_balance(USER))
        self.assertEqual(self.repo.get_balance(USER), 1000 - 153)

    def test_refund_removes_the_line_and_frees_cap(self):
        self.repo.hold_run(USER, "run-1", 200)
        charge = self.repo.charge_usage(USER, 150, "generation", run_id="run-1", line_kind="media", line_label="Video clip")
        self.repo.refund_usage(USER, charge, "refund: step failed")
        self.assertEqual(self.repo.get_run_hold("run-1")["charged_cents"], 0)
        receipt = self.repo.release_run("run-1")
        self.assertEqual(receipt["actual_cents"], 0)
        self.assertEqual(receipt["lines"], [])
        self.assertEqual(self.repo.get_balance(USER), 1000)

    def test_usage_event_rows_record_orchestration_reason(self):
        self.repo.hold_run(USER, "run-1", 200)
        self.repo.charge_usage(USER, 40, "orchestration", run_id="run-1", line_kind="orchestration",
                               line_label=rb.ORCHESTRATION_LABEL)
        with self.repo._connect() as connection:
            row = connection.execute("SELECT reason, run_id, wallet_cents FROM usage_events WHERE reason = 'orchestration'").fetchone()
        self.assertEqual((row["reason"], row["run_id"], row["wallet_cents"]), ("orchestration", "run-1", 40))

    def test_daily_allowance_is_spent_before_wallet_inside_a_run(self):
        with self.repo._connect() as connection:
            connection.execute(
                "INSERT INTO subscriptions(user_id, plan_id, status, monthly_budget_cents, daily_allowance_cents, "
                "daily_allowance_used_cents, daily_allowance_reset_date, current_period_end, created_at, updated_at) "
                "VALUES (?, 'p', 'active', 0, 50, 0, ?, 0, 0, 0)", (USER, rb.time.strftime("%Y-%m-%d", rb.time.gmtime())))
        self.repo.hold_run(USER, "run-1", 200)
        charge = self.repo.charge_usage(USER, 80, "generation", run_id="run-1", line_kind="media", line_label="Image")
        self.assertEqual((charge.daily_cents, charge.wallet_cents), (50, 30))


class MeterTests(Fixture, unittest.TestCase):
    def meter(self, cap=125):
        self.repo.hold_run(USER, "run-1", cap, estimate_cents=75)
        return run_billing.RunMeter(self.repo, USER, "run-1")

    def test_turn_is_billed_with_the_markup_and_recorded_as_orchestration(self):
        meter = self.meter()
        self.assertIsNone(meter.meter_turn(0.10))
        self.assertEqual(self.repo.get_balance(USER), 1000 - 13)
        self.assertIsNone(meter.meter_turn(0.10))
        self.assertEqual(self.repo.get_balance(USER), 1000 - 26)  # cumulative rounding, not per-turn
        lines = self.repo.run_lines("run-1")
        self.assertEqual({line["kind"] for line in lines}, {"orchestration"})
        self.assertEqual(sum(line["cents"] for line in lines), 26)

    def test_flag_off_charges_nothing(self):
        meter = self.meter()
        with patch.dict(os.environ, {"ORCHESTRATION_BILLING_ENABLED": "false"}):
            self.assertIsNone(meter.meter_turn(0.50))
        self.assertEqual(self.repo.get_balance(USER), 1000)

    def test_turn_is_clipped_at_the_cap_and_pauses(self):
        meter = self.meter(cap=100)
        self.assertIsNone(meter.meter_turn(0.50))  # 65
        paused = meter.meter_turn(0.60)  # would be 143 cumulative
        self.assertEqual(paused["type"], "paused_cap")
        self.assertEqual(paused["charged_cents"], 100)
        self.assertEqual(self.repo.get_balance(USER), 900)  # never above the cap
        self.assertEqual(self.repo.get_run_hold("run-1")["status"], "paused_cap")
        self.assertEqual(run_billing.stored_pause(self.repo, "run-1")["cap_cents"], 100)
        with self.assertRaises(rb.RunPausedAtCap):
            meter.raise_if_paused()

    def test_step_over_the_cap_is_not_run(self):
        meter = self.meter(cap=100)
        self.assertIsNone(meter.check_step(100))
        self.repo.charge_usage(USER, 40, "generation", run_id="run-1", line_kind="media", line_label="Image")
        paused = meter.check_step(65)
        self.assertEqual(paused["status"], "paused_cap")
        self.assertEqual(self.repo.get_balance(USER), 960)
        self.assertEqual(paused["raise_options_cents"], [150, 200])
        self.assertEqual(paused["choices"], ["raise_cap", "stop"])

    def test_check_turn_stops_when_nothing_is_left(self):
        meter = self.meter(cap=65)
        meter.meter_turn(0.50)
        self.assertEqual(meter.remaining_cap_cents(), 0)
        self.assertEqual(meter.check_turn()["type"], "paused_cap")

    def test_raising_the_cap_resumes_and_bills_the_catch_up(self):
        meter = self.meter(cap=100)
        meter.meter_turn(0.50)
        meter.meter_turn(0.60)
        run_billing.raise_cap(self.repo, "run-1", USER, 200)
        self.assertEqual(self.repo.get_run_hold("run-1")["status"], "running")
        resumed = run_billing.RunMeter(self.repo, USER, "run-1")
        self.assertIsNone(resumed.meter_turn(0.01))
        self.assertLessEqual(self.repo.get_run_hold("run-1")["charged_cents"], 200)

    def test_raise_is_rejected_when_credit_is_short(self):
        self.repo.adjust_balance(USER, -800, "test_spend")
        meter = self.meter(cap=100)
        with self.assertRaises(rb.InsufficientCreditError):
            run_billing.raise_cap(self.repo, "run-1", USER, 500)
        paused = meter.check_step(500)
        self.assertEqual(paused["raise_options_cents"], [150, 200])
        self.assertEqual(self.repo.get_balance(USER), 200)

    def test_media_charge_goes_through_the_hold_and_hard_stops(self):
        self.repo.hold_run(USER, "run-1", 100)
        run_billing.charge_media(self.repo, USER, "run-1", 65, "Seedance___image_to_video", {"duration_seconds": 5}, "c1")
        with self.assertRaises(rb.RunPausedAtCap) as caught:
            run_billing.charge_media(self.repo, USER, "run-1", 65, "Seedance___image_to_video", {}, "c2")
        self.assertEqual(self.repo.get_balance(USER), 935)
        self.assertEqual(caught.exception.payload["type"], "paused_cap")
        lines = self.repo.run_lines("run-1")
        self.assertEqual([(l["kind"], l["label"], l["detail"]) for l in lines], [("media", "Video clip", "5 s")])

    def test_charge_without_a_hold_keeps_the_old_path(self):
        charge = run_billing.charge_media(self.repo, USER, "no-such-run", 26, "Seedream___text_to_image", {})
        self.assertEqual(charge.total_cents, 26)

    def test_model_usage_returns_the_turn_cost(self):
        from agent.deep_agent.usage import ModelUsage

        usage = ModelUsage("scope")
        message = AIMessage(content="x", id="m1", usage_metadata={"input_tokens": 1_000_000, "output_tokens": 100_000,
                                                                  "total_tokens": 1_100_000},
                            response_metadata={"model_name": "claude-sonnet-5-5"})
        self.assertAlmostEqual(usage.record(message), 3.0)
        self.assertIsNone(usage.record(message))  # same message id is never counted twice
        unknown = AIMessage(content="x", id="m2", usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                            response_metadata={"model_name": "mystery"})
        self.assertIsNone(usage.record(unknown))


class PayloadTests(Fixture, unittest.TestCase):
    def view(self, approvals, **overrides):
        options = dict(run_id="run-1", user_id=USER, execution_status="awaiting_approval", error_type=None)
        options.update(overrides)
        return run_billing.public_approvals(self.repo, raw_approvals=approvals, **options)

    def sample(self):
        return [approval("a", "Seedream___text_to_image"), approval("b", "Seedance___image_to_video"),
                approval("c", "Seedance___image_to_video"), approval("d", "ElevenLabs___text_to_speech_convert", {"text": "Hi"})]

    def test_approval_shape_prices_estimate_cap_and_lines(self):
        cards = self.view(self.sample())
        card = cards[1]
        self.assertEqual(card["step_price_cents"], 65)
        self.assertEqual(card["estimate_cents"], 26 + 65 + 65 + 2 + 75)
        self.assertEqual(card["cap_cents"], rb.default_cap_cents(card["estimate_cents"]))
        self.assertEqual(sum(line["price_cents"] for line in card["lines"]), card["estimate_cents"])
        self.assertEqual([line["label"] for line in card["lines"]],
                         ["Image", "Video clip", "Video clip", "Voiceover", "Agent orchestration"])
        self.assertEqual(card["lines"][-1], {"label": "Agent orchestration", "price_cents": 75, "kind": "orchestration",
                                             "basis": "estimate"})
        self.assertEqual(card["status"], "pending")
        self.assertTrue(card["approve_enabled"])
        self.assertIsNone(card["insufficient_credit"])
        self.assertEqual((card["step_index"], card["step_count"]), (2, 4))
        self.assertEqual(card["balance_cents"], 1000)
        self.assertEqual(card["balance_after_estimate_cents"], 1000 - card["estimate_cents"])
        self.assertEqual(card["balance_after_cap_cents"], 1000 - card["cap_cents"])
        for key in ("tool_name", "provider", "estimated_cost", "description"):
            self.assertNotIn(key, card)
        self.assertEqual(set(card["arguments"]), {"prompt", "duration_seconds", "resolution"})

    def test_insufficient_credit_disables_approve(self):
        self.repo.adjust_balance(USER, -850, "test_spend")  # 150 left; estimate 233, cap 350
        card = self.view(self.sample())[0]
        self.assertFalse(card["approve_enabled"])
        info = card["insufficient_credit"]
        self.assertEqual(info["type"], "insufficient_credit")
        self.assertEqual(info["balance_cents"], 150)
        self.assertTrue(info["add_credit"])
        self.assertIsNone(info["lower_cap_option_cents"])  # below the estimate: only add credit

    def test_lowering_the_cap_is_offered_when_balance_covers_the_estimate(self):
        self.repo.adjust_balance(USER, -700, "test_spend")  # 300 left; estimate 233, cap 350
        info = self.view(self.sample())[0]["insufficient_credit"]
        self.assertEqual(info["lower_cap_option_cents"], 300)

    def test_other_runs_holds_count_against_available_credit(self):
        self.repo.hold_run(USER, "other", 800)
        card = self.view(self.sample())[0]
        self.assertEqual(card["balance_cents"], 200)
        self.assertFalse(card["approve_enabled"])

    def test_approval_gate_holds_the_cap_and_rejects_low_caps(self):
        raw = self.sample()
        hold = run_billing.approval_gate(self.repo, run_id="run-1", user_id=USER, conversation_id="conv",
                                         raw_approvals=raw, requested_cap_cents=None)
        self.assertEqual(hold["held_cents"], 350)
        self.assertEqual(self.repo.available_credit(USER), 650)
        with self.assertRaises(ValueError):
            run_billing.approval_gate(self.repo, run_id="run-2", user_id=USER, conversation_id=None,
                                      raw_approvals=raw, requested_cap_cents=100)

    def test_approval_gate_with_a_lowered_cap(self):
        self.repo.adjust_balance(USER, -700, "test_spend")
        hold = run_billing.approval_gate(self.repo, run_id="run-1", user_id=USER, conversation_id=None,
                                         raw_approvals=self.sample(), requested_cap_cents=300)
        self.assertEqual(hold["held_cents"], 300)
        with self.assertRaises(rb.InsufficientCreditError):
            run_billing.approval_gate(self.repo, run_id="run-2", user_id=USER, conversation_id=None,
                                      raw_approvals=self.sample(), requested_cap_cents=300)

    def test_rejected_cards_are_not_priced(self):
        raw = self.sample()
        raw[1]["decision"] = "reject"
        cards = self.view(raw)
        self.assertEqual(cards[1]["status"], "rejected")
        self.assertNotIn("estimate_cents", cards[1])
        self.assertEqual(cards[0]["estimate_cents"], 26 + 65 + 2 + 75)

    def test_orchestration_line_is_absent_when_the_flag_is_off(self):
        with patch.dict(os.environ, {"ORCHESTRATION_BILLING_ENABLED": "false"}):
            card = self.view(self.sample())[0]
        self.assertNotIn("orchestration", {line["kind"] for line in card["lines"]})
        self.assertEqual(card["estimate_cents"], 26 + 65 + 65 + 2)

    def test_second_pause_in_the_same_run_counts_what_was_spent(self):
        self.repo.hold_run(USER, "run-1", 325)
        self.repo.charge_usage(USER, 65, "generation", run_id="run-1", line_kind="media", line_label="Video clip",
                               line_detail="5 s")
        self.repo.charge_usage(USER, 40, "orchestration", run_id="run-1", line_kind="orchestration",
                               line_label=rb.ORCHESTRATION_LABEL)
        card = self.view([approval("e", "Seedream___text_to_image")])[0]
        self.assertEqual(card["spent_so_far_cents"], 105)
        self.assertEqual(card["estimate_cents"], 105 + 26 + 35)  # orchestration estimate 75, 40 already billed
        self.assertEqual(sum(l["price_cents"] for l in card["lines"]), card["estimate_cents"])
        self.assertGreaterEqual(card["cap_cents"], 325)

    def test_status_follows_the_execution(self):
        raw = [approval("a", "Seedream___text_to_image", decision="approve")]
        self.assertEqual(self.view(raw, execution_status="running")[0]["status"], "running")
        self.assertEqual(self.view(raw, execution_status="completed")[0]["status"], "done")
        self.assertEqual(self.view(raw, execution_status="error")[0]["status"], "failed")
        self.repo.hold_run(USER, "run-1", 100)
        self.repo.set_run_pause("run-1", {"type": "paused_cap"})
        self.assertEqual(self.view(raw, execution_status="error")[0]["status"], "paused_cap")

    def test_receipt_totals_balance_and_shape(self):
        self.repo.hold_run(USER, "run-1", 325, estimate_cents=233)
        self.repo.charge_usage(USER, 26, "generation", run_id="run-1", line_kind="media", line_label="Image")
        self.repo.charge_usage(USER, 65, "generation", run_id="run-1", line_kind="media", line_label="Video clip", line_detail="5 s")
        self.repo.charge_usage(USER, 40, "orchestration", run_id="run-1", line_kind="orchestration", line_label=rb.ORCHESTRATION_LABEL)
        self.repo.charge_usage(USER, 31, "orchestration", run_id="run-1", line_kind="orchestration", line_label=rb.ORCHESTRATION_LABEL)
        receipt = self.repo.release_run("run-1")
        self.assertEqual(receipt, {
            "type": "receipt", "run_id": "run-1", "status": "done",
            "lines": [
                {"label": "Image", "price_cents": 26, "kind": "media", "basis": "fixed"},
                {"label": "Video clip", "detail": "5 s", "price_cents": 65, "kind": "media", "basis": "fixed"},
                {"label": "Agent orchestration", "price_cents": 71, "kind": "orchestration", "basis": "fixed"},
            ],
            "actual_cents": 162, "estimate_cents": 233, "cap_cents": 325, "under_estimate": True,
            "balance_before_cents": 1000, "balance_after_cents": 838,
        })
        self.assertEqual(sum(line["price_cents"] for line in receipt["lines"]), receipt["actual_cents"])
        self.assertEqual(self.repo.get_run_receipt("run-1", USER), receipt)
        self.assertIsNone(self.repo.get_run_receipt("run-1", "someone-else"))

    def test_failed_run_receipt_lists_only_what_was_charged(self):
        self.repo.hold_run(USER, "run-1", 200, estimate_cents=100)
        receipt = self.repo.release_run("run-1", status="failed")
        self.assertEqual((receipt["status"], receipt["actual_cents"], receipt["lines"]), ("failed", 0, []))
        self.assertEqual(receipt["balance_after_cents"], 1000)

    def test_end_run_keeps_paused_and_awaiting_holds(self):
        self.repo.hold_run(USER, "run-1", 200)
        self.assertIsNone(run_billing.end_run(self.repo, "run-1", execution_status="awaiting_approval"))
        self.assertEqual(self.repo.get_run_hold("run-1")["state"], "held")
        self.repo.set_run_pause("run-1", {"type": "paused_cap"})
        self.assertIsNone(run_billing.end_run(self.repo, "run-1", execution_status="error", error_type="PausedAtCap"))
        self.assertEqual(self.repo.get_run_hold("run-1")["state"], "held")
        self.repo.set_run_pause("run-1", None)
        self.assertEqual(run_billing.end_run(self.repo, "run-1", execution_status="completed")["status"], "done")
        self.assertEqual(self.repo.available_credit(USER), 1000)

    def test_start_run_holds_the_default_cap_and_resume_adopts_it(self):
        hold = run_billing.start_run(self.repo, USER, "job-1", "conv-1")
        self.assertEqual(hold["held_cents"], 125)
        again = run_billing.start_run(self.repo, USER, "job-1", "conv-1")
        self.assertEqual(again["run_id"], "job-1")
        self.repo.set_run_pause("job-1", {"type": "paused_cap"})
        adopted = run_billing.start_run(self.repo, USER, "job-2", "conv-1")
        self.assertEqual(adopted["run_id"], "job-2")
        self.assertIsNone(self.repo.get_run_hold("job-1"))
        self.assertEqual(self.repo.available_credit(USER), 875)

    def test_autonomous_run_holds_a_media_allowance_too(self):
        hold = run_billing.start_run(self.repo, USER, "auto-1", None, autonomous_media_cents=rb.autonomous_media_cents())
        self.assertEqual(hold["held_cents"], rb.default_cap_cents(75 + 300))
        with patch.dict(os.environ, {"RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": "100"}):
            self.assertEqual(rb.autonomous_media_cents(), 100)
        with patch.dict(os.environ, {"RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": "x"}), self.assertRaises(ValueError):
            rb.autonomous_media_cents()

    def test_start_run_fails_when_credit_cannot_cover_the_default_cap(self):
        self.repo.adjust_balance(USER, -950, "test_spend")
        short = run_billing.precheck_start(self.repo, USER, "conv-9")
        self.assertEqual(short["type"], "insufficient_credit")
        with self.assertRaises(rb.InsufficientCreditError):
            run_billing.start_run(self.repo, USER, "job-9", "conv-9")

    def test_paused_payload_shape(self):
        self.repo.hold_run(USER, "run-1", 150)
        self.repo.charge_usage(USER, 120, "generation", run_id="run-1", line_kind="media", line_label="Video clip")
        meter = run_billing.RunMeter(self.repo, USER, "run-1")
        paused = meter.check_step(65)
        self.assertEqual(set(paused), {"type", "status", "run_id", "message", "charged_cents", "cap_cents", "held_cents",
                                       "lines", "raise_options_cents", "balance_cents", "choices", "add_credit"})
        self.assertEqual(paused["raise_options_cents"], [200, 250])
        self.assertFalse(paused["add_credit"])
        self.assertEqual(run_billing.paused_cap_view(self.repo, "run-1")["cap_cents"], 150)


class ScrubbingTests(Fixture, unittest.TestCase):
    def test_client_payloads_have_no_vendor_model_or_fee_wording(self):
        raw = [approval("a", "Seedream___text_to_image"), approval("b", "Seedance___image_to_video"),
               approval("c", "ElevenLabs___text_to_speech_convert", {"text": "Hello"})]
        payloads = [run_billing.public_approvals(self.repo, run_id="run-1", user_id=USER,
                                                 execution_status="awaiting_approval", error_type=None, raw_approvals=raw)]
        self.repo.adjust_balance(USER, -900, "test_spend")
        payloads.append(run_billing.public_approvals(self.repo, run_id="run-1", user_id=USER,
                                                     execution_status="awaiting_approval", error_type=None, raw_approvals=raw))
        self.repo.adjust_balance(USER, 900, "test_credit")
        self.repo.hold_run(USER, "run-2", 150)
        self.repo.charge_usage(USER, 100, "generation", run_id="run-2", line_kind="media", line_label="Video clip")
        meter = run_billing.RunMeter(self.repo, USER, "run-2")
        payloads.append(meter.check_step(65))
        payloads.append(rb.insufficient_credit_payload(estimate_cents=233, cap_cents=325, available_cents=150))
        payloads.append(run_billing.insufficient_for_raise(self.repo, "run-2", rb.InsufficientCreditError(10, 50), 400))
        payloads.append(run_billing.start_run(self.repo, USER, "run-3", None) and run_billing.precheck_start(self.repo, USER, "c"))
        payloads.append(self.repo.release_run("run-2", status="failed"))
        payloads.append(rb.NEUTRAL_ERROR)
        payloads.append(rb.PAUSED_MESSAGE)
        text = json.dumps(payloads)
        self.assertIsNone(VENDOR_RE.search(text), VENDOR_RE.search(text))
        self.assertNotIn("fee_cents", text)
        self.assertNotIn("provider_cents", text)

    def test_every_gateway_tool_id_gets_a_vendor_free_label(self):
        names = set()
        for path in Path("configs/gateway").glob("*.tools.json"):
            data = json.loads(path.read_text())
            tools = data if isinstance(data, list) else data.get("tools", data)
            prefix = path.name.split(".")[0]
            for tool in tools:
                if isinstance(tool, dict) and tool.get("name"):
                    names.add(f"{prefix}___{tool['name']}")
        self.assertGreater(len(names), 50)
        for name in names:
            for arguments in ({}, {"duration_seconds": 8, "resolution": "1080p"}):
                label, detail = rb.work_label(name, arguments)
                self.assertIsNone(VENDOR_RE.search(f"{label} {detail}"), (name, label, detail))

    def test_unsafe_error_text_is_replaced(self):
        for text in ("Seedance API returned 500", "fal queue timeout", "Upstream provider failed", "A 30% fee applies",
                     "Claude Sonnet overloaded", "ElevenLabs quota", "platform fee"):
            self.assertEqual(rb.neutral_error(text), rb.NEUTRAL_ERROR, text)
        self.assertEqual(rb.neutral_error("This step timed out after 120 s."), "This step timed out after 120 s.")
        self.assertEqual(rb.neutral_error(""), rb.NEUTRAL_ERROR)

    def test_vendor_argument_keys_are_dropped_recursively(self):
        cleaned = rb.scrub_arguments({"prompt": "p", "model": "m", "provider": "x", "nested": {"model_id": "q", "ok": 1}})
        self.assertEqual(cleaned, {"prompt": "p", "nested": {"ok": 1}})

    def test_public_execution_scrubs_tool_calls_events_and_results(self):
        execution = {
            "status": "error", "message": "x", "result": {"summary": "Seedance returned 502"},
            "tool_calls": [{"id": "1", "name": "Seedance___image_to_video", "label": "Seedance image to video",
                            "provider": "seedance", "summary": "Seedance failed after 30% fee", "status": "failed",
                            "arguments": {"duration_seconds": 5},
                            "result": {"error": "fal queue timeout", "job_id": "abc", "nested": {"reason": "Kling busy"}}}],
            "events": [{"title": "Seedance render", "message": "fal 40 s elapsed", "status": "running"}],
        }
        public = run_billing.public_execution(execution)
        self.assertIsNone(VENDOR_RE.search(json.dumps({k: v for k, v in public.items()
                                                       if k != "tool_calls"} | {"calls": [
            {k: v for k, v in call.items() if k not in {"name", "provider"}} for call in public["tool_calls"]]})))
        call = public["tool_calls"][0]
        self.assertEqual((call["label"], call["provider"]), ("Video clip · 5 s", None))
        self.assertEqual(call["result"]["job_id"], "abc")  # ids are kept
        self.assertEqual(call["result"]["error"], rb.NEUTRAL_ERROR)
        self.assertIsNone(run_billing.public_execution(None))


if __name__ == "__main__":
    unittest.main()
