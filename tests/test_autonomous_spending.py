from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from mcp import Tool
from agent.deep_agent.routing import CostEstimate
from agent.gateway_executor import GatewayExecutor
from agent.studio_agent_next import StudioAgentRequest, _context_from_request
from test_deep_agent import Gateway
from server.billing_rates import cost_for

CAP = str(cost_for("seedance", "text_to_video", {"prompt": "forest"}).total_cents)

PAID = Tool(
    name="Seedance___text_to_video",
    inputSchema={
        "type": "object",
        "properties": {"prompt": {"type": "string"}},
        "required": ["prompt"],
    },
)
FREE = Tool(name="Seedance___get_video_task", inputSchema={"type": "object"})


class SpendingTests(unittest.IsolatedAsyncioTestCase):
    def context(self, autonomous=True):
        return _context_from_request(
            StudioAgentRequest(prompt="Seedance video", autonomous=autonomous, job_id="job")
        )

    def executor(self, studio=None, session=None, scope="run-one", gateway=None):
        gateway = gateway or Gateway([PAID, FREE], {"status": "succeeded"})
        return GatewayExecutor(
            studio or self.context(), [gateway], session, run_scope=scope
        ), gateway

    async def paid(self, executor, call_id="one", **kwargs):
        return await executor.execute(
            {"tool_name": PAID.name, "arguments": {"prompt": "forest"}, "call_id": call_id},
            **kwargs,
        )

    async def test_unset_cap_does_not_restrict_dispatch_and_only_quotes_telemetry(self):
        with (
            patch.dict(os.environ, {"RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": ""}),
            patch("agent.gateway_executor.estimate_cost", return_value=CostEstimate(None, "unknown")) as estimate,
        ):
            executor, gateway = self.executor()
            await self.paid(executor, approved=True)
            gateway.call_tool.assert_awaited_once()
            self.assertEqual(executor.reservations, {})
            estimate.assert_called_once_with(PAID.name, {"prompt": "forest"}, list_price=True)

    async def test_cap_allows_exact_limit_and_then_stops_paid_tools(self):
        with patch.dict(os.environ, {"RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": CAP}):
            executor, gateway = self.executor()
            first = await self.paid(executor, approved=True)
            self.assertEqual(first["status"], "succeeded")
            blocked = await self.paid(executor, "two", approved=True)
            self.assertEqual(blocked["status"], "not_run")
            self.assertIn("cap", blocked["reason"])
            gateway.call_tool.assert_awaited_once()
            free = await executor.execute(
                {"tool_name": FREE.name, "arguments": {}, "call_id": "poll"}
            )
            self.assertEqual(free["status"], "succeeded")
            gateway.call_tool.assert_awaited_with(FREE.name, {})

    async def test_cap_survives_approved_calls_and_restarts(self):
        with patch.dict(os.environ, {"RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": CAP}):
            executor, gateway = self.executor()
            await self.paid(executor, approved=True)
            restarted, _ = self.executor(session=executor.snapshot(), gateway=gateway)
            blocked = await self.paid(restarted, "two", approved=True)
            self.assertEqual(blocked["status"], "not_run")
            gateway.call_tool.assert_awaited_once()
            new_run, _ = self.executor(
                session=executor.snapshot(), scope="run-two", gateway=gateway
            )
            await self.paid(new_run, "two", approved=True)
            self.assertEqual(gateway.call_tool.await_count, 2)

    async def test_concurrent_dispatch_cannot_overspend(self):
        with patch.dict(os.environ, {"RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": CAP}):
            executor, gateway = self.executor()
            outputs = await asyncio.gather(self.paid(executor, "one", approved=True), self.paid(executor, "two", approved=True))
            self.assertEqual(sum(x["status"] == "succeeded" for x in outputs), 1)
            gateway.call_tool.assert_awaited_once()

    async def test_unknown_paid_quote_stops_dispatch_and_remains_stopped(self):
        unknown = Tool(name="Remotion___render_timeline", inputSchema={"type": "object"})
        with patch.dict(os.environ, {"RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": "10000"}):
            gateway = Gateway([PAID, unknown], {"status": "succeeded"})
            executor, _ = self.executor(gateway=gateway)
            output = await executor.execute(
                {"tool_name": unknown.name, "arguments": {}, "call_id": "render"}, approved=True
            )
            self.assertIn("unknown", output["reason"])
            self.assertEqual(output["status"], "not_run")
            await self.paid(executor, "later", approved=True)
            gateway.call_tool.assert_not_awaited()

    async def test_non_autonomous_runs_ignore_cap_and_keep_approval(self):
        from agent.codex_harness import ToolApprovalPending

        with patch.dict(os.environ, {"RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": "0"}):
            executor, gateway = self.executor(studio=self.context(False))
            with self.assertRaises(ToolApprovalPending):
                await self.paid(executor)
            await self.paid(executor, approved=True)
            gateway.call_tool.assert_awaited_once()

    async def test_rejections_and_schema_failures_consume_no_spend(self):
        with patch.dict(os.environ, {"RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": CAP}):
            executor, gateway = self.executor()
            await self.paid(executor, rejection="skip")
            await executor.execute({"tool_name": PAID.name, "arguments": {}, "call_id": "invalid"})
            self.assertEqual(executor.reservations, {})
            gateway.call_tool.assert_not_awaited()

    async def test_transport_failure_keeps_conservative_reservation(self):
        with patch.dict(os.environ, {"RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": CAP}):
            executor, gateway = self.executor()
            gateway.call_tool.side_effect = RuntimeError("timeout after submission")
            await self.paid(executor, approved=True)
            await self.paid(executor, "two", approved=True)
            gateway.call_tool.assert_awaited_once()
            self.assertTrue(executor.reservations)

    async def test_gate_cannot_be_bypassed_by_approval(self):
        gated = Tool(name="Fal___text_to_video", inputSchema={"type": "object"})
        executor, gateway = self.executor(gateway=Gateway([gated]))
        result = await executor.execute(
            {"tool_name": gated.name, "arguments": {"model": "hunyuan"}, "call_id": "blocked"},
            approved=True,
        )
        self.assertEqual(result["status"], "not_run")
        gateway.call_tool.assert_not_awaited()

    async def test_reservation_is_persisted_before_submission_and_survives_cancellation(self):
        import copy

        with patch.dict(os.environ, {"RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": CAP}):
            studio = self.context()
            saved = []
            studio.session_sink = lambda items: saved.append(copy.deepcopy(items))
            executor, gateway = self.executor(studio=studio)

            async def cancel_after_submission(*args):
                self.assertTrue(saved[-1][-1]["spending"]["reservations"])
                raise asyncio.CancelledError

            gateway.call_tool.side_effect = cancel_after_submission
            with self.assertRaises(asyncio.CancelledError):
                await self.paid(executor, approved=True)
            restored = self.context()
            restored.session_items = saved[-1]
            stale = {"spending": {"scope": "run-one", "reservations": {}}}
            restarted, _ = self.executor(studio=restored, session=stale, gateway=gateway)
            blocked = await self.paid(restarted, "second", approved=True)
            self.assertEqual(blocked["status"], "not_run")
            gateway.call_tool.assert_awaited_once()

    async def test_cap_requires_durable_run_identity(self):
        with patch.dict(os.environ, {"RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": "1"}):
            studio = self.context()
            studio.job_id = None
            with self.assertRaisesRegex(ValueError, "stable job_id"):
                self.executor(studio=studio)
