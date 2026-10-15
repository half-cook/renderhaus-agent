from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field

from agent.deep_agent.budget import BudgetContextMiddleware, guard_model, model_envelope, record_local_work
from server import run_budget as rb
from server.run_billing import RunMeter
from server.run_billing import charge_media
from server.studio_state import StudioRepository


class RecordingModel(BaseChatModel):
    model_name: str = "claude-sonnet-5-5"
    max_tokens: int = 200
    max_retries: int = 2
    calls: list = Field(default_factory=list)
    fail: bool = False
    omit_usage: bool = False
    profile: dict = Field(default_factory=lambda: {"max_input_tokens": 1_000_000, "max_output_tokens": 128_000})

    @property
    def _llm_type(self):
        return "budget-test"

    @property
    def _identifying_params(self):
        return {"model_name": self.model_name, "max_tokens": self.max_tokens}

    def bind_tools(self, tools, **kwargs):
        return self.bind(tools=tools, **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        if self.fail:
            raise TimeoutError("Ambiguous request timeout")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content="done", usage_metadata=None if self.omit_usage else {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            response_metadata={"model_name": self.model_name},
        ))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        yield ChatGenerationChunk(message=AIMessageChunk(content="do"))
        yield ChatGenerationChunk(message=AIMessageChunk(
            content="ne", usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            response_metadata={"model_name": self.model_name},
        ))


class HarnessBudgetTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.repo = StudioRepository(root / "state.sqlite3", root / "media")
        self.repo.adjust_balance("u", 10_000, "test_credit")
        self.repo.hold_run("u", "r", 100)
        self.meter = RunMeter(self.repo, "u", "r")

    def test_parallel_reservations_share_the_actual_cap(self):
        def reserve(index):
            try:
                self.meter.reserve_work(str(index), 30, kind="model", role="planner")
                return True
            except rb.RunPausedAtCap:
                return False
        with ThreadPoolExecutor(12) as pool:
            accepted = list(pool.map(reserve, range(12)))
        self.assertEqual(sum(accepted), 3)
        self.assertEqual(self.meter.remaining_cap_cents(), 10)
        self.assertEqual(self.repo.get_balance("u"), 10_000)
        with self.assertRaises(rb.RunCapExceededError):
            self.repo.charge_usage("u", 11, "generation", run_id="r")

    def test_settlement_is_atomic_idempotent_and_uses_actual_cost(self):
        self.meter.reserve_work("m", 70, kind="model", role="summary")
        self.meter.settle_work("m", model_cost_usd=0.10, usage={"input_tokens": 50})
        self.meter.settle_work("m", model_cost_usd=0.10, usage={"input_tokens": 50})
        self.assertEqual(self.repo.get_balance("u"), 9_987)
        self.assertEqual(self.meter.remaining_cap_cents(), 87)
        self.assertAlmostEqual(self.repo.get_run_hold("r")["model_usd"], 0.10)
        self.assertEqual(self.repo.run_work("r")[0]["state"], "settled")

    def test_concurrent_settlement_cannot_charge_a_call_twice(self):
        self.meter.reserve_work("m", 70, kind="model", role="rubric")
        with ThreadPoolExecutor(8) as pool:
            list(pool.map(lambda _: self.meter.settle_work("m", model_cost_usd=0.20), range(8)))
        self.assertEqual(self.repo.get_balance("u"), 9_974)
        self.assertAlmostEqual(self.repo.get_run_hold("r")["model_usd"], 0.20)

    def test_out_of_envelope_settlement_is_not_clipped_or_charged(self):
        self.meter.reserve_work("m", 5, kind="model", role="manager")
        with self.assertRaises(rb.RunBudgetError):
            self.meter.settle_work("m", model_cost_usd=1)
        self.assertEqual(self.repo.get_balance("u"), 10_000)
        self.assertEqual(self.repo.run_work("r")[0]["state"], "reserved")

    def test_unresolved_work_survives_end_and_stale_sweep(self):
        self.meter.reserve_work("m", 40, kind="model", role="manager")
        self.meter.fail_work("m")
        self.assertIsNone(self.repo.release_run("r"))
        with self.repo._connect() as connection:
            connection.execute("UPDATE run_holds SET updated_at = 0 WHERE run_id = 'r'")
        self.assertEqual(self.repo.available_credit("u"), 9_900)
        self.assertEqual(self.repo.get_run_hold("r")["state"], "held")
        self.assertEqual(self.repo.run_work("r")[0]["state"], "ambiguous")
        self.meter.settle_work("m", model_cost_usd=0.10)
        self.assertEqual(self.repo.release_run("r")["actual_cents"], 13)

    def test_reservation_rekeys_with_resume(self):
        self.meter.reserve_work("m", 40, kind="model", role="planner")
        self.repo.rekey_run("r", "resumed")
        resumed = RunMeter(self.repo, "u", "resumed")
        self.assertEqual(resumed.remaining_cap_cents(), 60)
        resumed.settle_work("m", model_cost_usd=0.10)
        self.assertEqual(self.repo.get_balance("u"), 9_987)

    def test_unknown_model_and_missing_output_envelope_block_before_dispatch(self):
        for model in (RecordingModel(model_name="unknown"), RecordingModel(max_tokens=0)):
            guarded = guard_model(model, self.meter, role="planner")
            with self.assertRaises(rb.RunBudgetError):
                guarded.invoke("Hello")
            self.assertEqual(model.calls, [])

    def test_bound_includes_tool_schemas_unicode_and_full_output_budget(self):
        model = RecordingModel()
        plain = model_envelope(model, [[HumanMessage(content="héllo")]], {})
        tools = model_envelope(model, [[HumanMessage(content="héllo")]], {
            "tools": [{"name": "test", "description": "x" * 10_000}], "max_tokens": 20_000,
        })
        self.assertGreater(tools.input_tokens, plain.input_tokens + 9_000)
        self.assertEqual(tools.output_tokens, 20_000)
        multimedia = model_envelope(model, [[HumanMessage(content=[{"type": "image_url", "image_url": {"url": "https://example.test/p.png"}}])]], {})
        self.assertLess(multimedia.input_tokens, 1_000_000)
        self.assertIn('bounded_images', multimedia.input_basis)

    def test_guard_is_on_the_model_and_preserves_binding_and_existing_callbacks(self):
        events = []
        class Existing(BaseCallbackHandler):
            def on_llm_end(self, response, **kwargs):
                events.append("finished")
        original = RecordingModel(callbacks=[Existing()])
        guarded = guard_model(original, self.meter, role="planner")
        self.assertIsInstance(guarded, RecordingModel)
        self.assertEqual(guarded.profile, original.profile)
        self.assertEqual(original.max_retries, 2)
        self.assertEqual(guarded.max_retries, 0)
        guarded.bind_tools([{"name": "test"}]).invoke("hello")
        self.assertEqual(events, ["finished"])
        self.assertEqual(len(self.repo.run_work("r")), 1)
        self.assertEqual(self.repo.run_work("r")[0]["state"], "settled")
        self.assertEqual(self.repo.get_balance("u"), 9_998)

    def test_guard_stops_the_provider_before_insufficient_envelope(self):
        original = RecordingModel(max_tokens=128_000)
        guarded = guard_model(original, self.meter, role="rubric")
        with self.assertRaises(rb.RunPausedAtCap):
            guarded.invoke("hello")
        self.assertEqual(original.calls, [])
        self.assertEqual(self.repo.get_balance("u"), 10_000)
        self.assertEqual(self.repo.get_run_hold("r")["status"], "paused_cap")

    def test_guarded_timeout_retains_unsettled_reservation(self):
        model = guard_model(RecordingModel(fail=True), self.meter, role="summary")
        with self.assertRaises(TimeoutError):
            model.invoke("hello")
        self.assertEqual(self.repo.run_work("r")[0]["state"], "ambiguous")
        self.assertLess(self.meter.remaining_cap_cents(), 100)

    def test_async_and_stream_usage_are_settled_once(self):
        model = guard_model(RecordingModel(), self.meter, role="manager")
        asyncio.run(model.ainvoke("first"))
        self.assertEqual("".join(chunk.content for chunk in model.stream("second")), "done")
        self.assertEqual([work["state"] for work in self.repo.run_work("r")], ["settled", "settled"])
        self.assertEqual(self.repo.get_balance("u"), 9_998)

    def test_actual_anthropic_clone_rebuilds_warmed_clients_with_no_retries(self):
        model = ChatAnthropic(model="claude-sonnet-5-5", max_tokens=200, api_key="test-only")
        _ = model._client
        guarded = guard_model(model, self.meter, role="summary")
        self.assertEqual(guarded._client.max_retries, 0)
        self.assertEqual(model._client.max_retries, 2)

    def test_budget_context_snapshot_is_fresh_for_every_decision_turn(self):
        middleware = BudgetContextMiddleware(self.meter)
        first = middleware.before_model({'messages': []}, None)
        self.assertIn("remaining_cents=100", first['messages'][0].content)
        self.meter.reserve_work("sibling", 20, kind="model", role="planner")
        second = middleware.before_model({'messages': first['messages']}, None)
        self.assertIn("reserved_cents=20", second['messages'][0].content)
        self.assertIn("remaining_cents=100", first['messages'][0].content)

    def test_local_execution_records_units_without_inventing_a_rate(self):
        with patch.dict("os.environ", {"ORCHESTRATION_LOCAL_USD_PER_SECOND": "0"}):
            result = record_local_work(self.meter, "inspect", lambda: "ok", max_seconds=3)
        self.assertEqual(result, "ok")
        record = self.repo.run_work("r")[0]
        self.assertEqual(record["kind"], "local")
        self.assertIn('"actions": 1', record["usage_json"])
        self.assertEqual(self.repo.get_balance("u"), 10_000)

    def test_local_configured_estimate_is_reserved_before_action(self):
        ran = []
        with patch.dict("os.environ", {"ORCHESTRATION_LOCAL_USD_PER_SECOND": "1"}):
            with self.assertRaises(rb.RunPausedAtCap):
                record_local_work(self.meter, "execute", lambda: ran.append(True), max_seconds=3)
        self.assertEqual(ran, [])

    def test_estimate_includes_labeled_high_effort_rubric_and_local_assumptions(self):
        with patch.dict("os.environ", {}, clear=True):
            assumptions = rb.orchestration_estimate_assumptions()
            self.assertGreater(rb.orchestration_estimate_cents(), 75)
        self.assertEqual(assumptions["basis"], "planning_assumptions_not_measurements")
        self.assertGreater(assumptions["rubric_calls"], 0)
        self.assertGreater(assumptions["local_actions"], 0)

    def test_media_reservation_is_consumed_once_by_the_actual_charge(self):
        with self.meter.media_dispatch("media-1", 60):
            self.assertEqual(self.meter.remaining_cap_cents(), 40)
            charged = charge_media(self.repo, "u", "r", 60, "Seedream___text_to_image", {})
            self.assertEqual(charged.total_cents, 60)
            self.assertEqual(self.meter.remaining_cap_cents(), 40)
        self.assertEqual(self.repo.get_balance("u"), 9_940)
        self.assertEqual(self.repo.run_work("r")[0]["state"], "settled")
        with self.assertRaises(rb.RunBudgetError):
            with self.meter.media_dispatch("media-1", 60):
                self.fail("Already dispatched call must not run twice")

    def test_media_scope_reaches_async_thread_charge_and_definite_no_start_can_cancel(self):
        async def dispatch():
            with self.meter.media_dispatch("media-1", 60):
                return await asyncio.to_thread(charge_media, self.repo, "u", "r", 60, "Seedream___text_to_image", {})
        self.assertEqual(asyncio.run(dispatch()).total_cents, 60)
        self.meter.reserve_media("never-started", 40)
        self.meter.complete_media("never-started", definitely_not_started=True)
        self.assertEqual(self.meter.remaining_cap_cents(), 40)

    def test_unknown_media_quote_stops_and_missing_charge_keeps_reservation(self):
        with self.assertRaises(rb.RunPausedAtCap):
            self.meter.reserve_media("unknown", None)
        self.repo.set_run_pause('r', None)
        self.meter.pause = None
        with self.meter.media_dispatch("unconfirmed", 60):
            pass
        work = self.repo.run_work("r")[0]
        self.assertEqual(work["state"], "ambiguous")
        self.assertEqual(self.meter.remaining_cap_cents(), 40)

    def test_model_kwargs_cannot_hide_a_larger_output_budget(self):
        model = ChatAnthropic(model="claude-sonnet-5-5", max_tokens=200, api_key="test-only")
        model = model.model_copy(update={"model_kwargs": {"max_tokens": 20_000}})
        envelope = model_envelope(model, [[HumanMessage(content="hello")]], model._get_invocation_params())
        self.assertEqual(envelope.output_tokens, 20_000)

    def test_pinned_anthropic_real_payload_and_usage_path_are_guarded_without_http(self):
        from anthropic.types import Message
        response = Message.model_validate({
            "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
            "content": [{"type": "text", "text": "done"}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 20, "output_tokens": 10},
        })
        model = guard_model(ChatAnthropic(model="claude-sonnet-5-5", max_tokens=200, api_key="test-only"),
                            self.meter, role="summary")
        with patch.object(ChatAnthropic, "_create", return_value=SimpleNamespace(parse=lambda: response)) as create:
            self.assertEqual(model.invoke("Summarize").content, "done")
        create.assert_called_once()
        self.assertEqual(self.repo.run_work("r")[0]["state"], "settled")
        self.assertEqual(self.repo.get_balance("u"), 9_998)

    def test_missing_usage_blocks_further_work_and_retains_reservation(self):
        model = guard_model(RecordingModel(omit_usage=True), self.meter, role="rubric")
        with self.assertRaises(rb.RunBudgetError):
            model.invoke("hello")
        self.assertEqual(self.repo.run_work("r")[0]["state"], "ambiguous")
        self.assertEqual(self.repo.get_balance("u"), 10_000)

    def test_concurrent_duplicate_media_ids_cannot_dispatch_twice(self):
        def reserve(_):
            try:
                self.meter.reserve_media("same-id", 20)
                return True
            except rb.RunBudgetError:
                return False
        with ThreadPoolExecutor(8) as pool:
            self.assertEqual(sum(pool.map(reserve, range(8))), 1)


if __name__ == "__main__":
    unittest.main()
