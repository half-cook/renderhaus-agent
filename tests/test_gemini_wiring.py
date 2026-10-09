from __future__ import annotations

import os
import json
import tempfile
import unittest
from pathlib import Path
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from agent.deep_agent import routing
from agent.gateway_executor import tool_needs_approval
from providers.catalog import get_provider
from providers.registry import dispatch, generate_schemas
from server.billing_rates import cost_for, gemini_rates, gemini_usage_usd
from test_gemini import image_b64


class GeminiApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_approval_discloses_unknown_cost_and_honors_rejection(self):
        from mcp import Tool
        from agent.deep_agent.runner import run_with_servers
        from agent.studio_agent_next import (StudioAgentApprovalRequired, StudioAgentRequest,
                                            StudioApprovalDecision, _context_from_request)
        from test_deep_agent import Gateway, ScriptedModel, call, final

        for decision in ("approve", "reject"):
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as directory, patch.dict(
                os.environ, {"GEMINI_DRY_RUN": "true", "GEMINI_TOOL_COST_CENTS_JSON": "{}",
                             "RENDERHAUS_OUTCOME_DIR": directory}
            ):
                frame = image_b64()
                args = {"before_image_b64": frame, "after_image_b64": frame}
                request = StudioAgentRequest(prompt="VLM judge these keyframes for continuity",
                                             autonomous=False, job_id="gemini-" + decision)
                studio = _context_from_request(request)
                schemas = generate_schemas(get_provider("gemini"))
                gateway = Gateway([Tool(name="Gemini___" + t["name"], description=t["description"],
                                        inputSchema=t["inputSchema"]) for t in schemas],
                                  result={"status": "skipped", "dry_run": True, "provider": "gemini",
                                          "reason": "Gemini dry-run enabled.", "training_eligible": False})
                with self.assertRaises(StudioAgentApprovalRequired) as paused:
                    await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                        call("read_file", {"file_path": "/skills/continuity-qc/SKILL.md"}, "skill"),
                        call("call_media_tool", {"tool_name": "Gemini___judge_continuity", "arguments": args}, "judge")]))
                approval = paused.exception.approvals[0]
                self.assertIn("unknown", approval.description.lower())
                request = request.model_copy(update={"session_items": studio.session_items,
                    "resume_state": paused.exception.state, "approval_decisions": [
                    StudioApprovalDecision(call_id=approval.call_id, decision=decision)]})
                studio = _context_from_request(request)
                await run_with_servers(request, studio, [gateway], model=ScriptedModel([final()]))
                if decision == "approve":
                    gateway.call_tool.assert_awaited_once_with("Gemini___judge_continuity", args)
                    self.assertEqual(studio.tool_events[-1].status, "skipped")
                else:
                    gateway.call_tool.assert_not_awaited()
                rows = [json.loads(line) for line in (Path(directory) / "outcomes.jsonl").read_text().splitlines()]
                self.assertEqual(rows[-1]["ab_arm"], "gemini_vlm_judge")

    async def test_autonomous_cap_blocks_unknown_quote_before_submission(self):
        from mcp import Tool
        from agent.gateway_executor import GatewayExecutor
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request
        from test_deep_agent import Gateway

        with patch.dict(os.environ, {"GEMINI_DRY_RUN": "true", "GEMINI_TOOL_COST_CENTS_JSON": "{}",
                                     "RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": "5"}):
            schema = generate_schemas(get_provider("gemini"))[0]
            gateway = Gateway([Tool(name="Gemini___judge_continuity", description=schema["description"],
                                    inputSchema=schema["inputSchema"])])
            studio = _context_from_request(StudioAgentRequest(prompt="VLM judge continuity", autonomous=True,
                                                             job_id="cap-gemini"))
            frame = image_b64()
            result = await GatewayExecutor(studio, [gateway]).execute({
                "tool_name": "Gemini___judge_continuity", "arguments": {"before_image_b64": frame,
                "after_image_b64": frame}, "call_id": "judge"}, approved=True)
            self.assertEqual(result["status"], "not_run")
            gateway.call_tool.assert_not_awaited()


class GeminiWiringTests(unittest.TestCase):
    def test_registry_contract_blocks_invalid_images_before_paid_dispatch(self):
        with patch("providers.gemini.api.httpx.Client") as client:
            with self.assertRaises(ValueError):
                dispatch("gemini", "judge_continuity", {"before_image_b64": "bad", "after_image_b64": "bad"})
            client.assert_not_called()

    def test_schema_contract_and_dry_run_dispatch(self):
        schemas = generate_schemas(get_provider("gemini"))
        self.assertEqual([row["name"] for row in schemas], ["judge_continuity", "get_task"])
        with patch.dict(os.environ, {"GEMINI_DRY_RUN": "true"}):
            frame = image_b64()
            result = dispatch("gemini", "judge_continuity", {"before_image_b64": frame, "after_image_b64": frame})
            self.assertEqual(result["status"], "skipped")
            self.assertTrue(result["dry_run"])
            self.assertFalse(result["training_eligible"])
            self.assertEqual(dispatch("gemini", "get_task", {"job_id": result["job_id"]})["status"], "skipped")

    def test_approval_and_spend_policy_remain_intact(self):
        name = "Gemini___judge_continuity"
        self.assertTrue(tool_needs_approval(name, False))
        self.assertFalse(tool_needs_approval(name, True))
        self.assertFalse(tool_needs_approval("Gemini___get_task", True))
        with patch.dict(os.environ, {"GEMINI_TOOL_COST_CENTS_JSON": "{}"}):
            self.assertIsNone(routing.estimate_cost(name, {}).total_cents)
            self.assertIn("unknown", routing.estimate_cost(name, {}).description.lower())
        with patch.dict(os.environ, {"GEMINI_DRY_RUN": "false", "GEMINI_TOOL_COST_CENTS_JSON": '{"judge_continuity":10}'}):
            self.assertEqual(routing.estimate_cost(name, {}).total_cents, 13)
            self.assertEqual(cost_for("gemini", "judge_continuity", {}).total_cents, 13)

    def test_unverified_model_never_gets_a_live_quote(self):
        with patch.dict(os.environ, {"GEMINI_DRY_RUN": "false", "GEMINI_VLM_MODEL": "future-model"}):
            self.assertIn("UNVERIFIED", routing.policy_blocker("Gemini___judge_continuity", {}))
            self.assertIsNone(routing.estimate_cost("Gemini___judge_continuity", {}).total_cents)

    def test_official_pricing_expires_and_counts_thinking(self):
        self.assertEqual(gemini_rates(as_of=date(2026, 12, 31)), (Decimal(".75"), Decimal("3.75")))
        self.assertEqual(gemini_rates(as_of=date(2027, 1, 1)), (Decimal("1.50"), Decimal("7.50")))
        self.assertAlmostEqual(gemini_usage_usd({"total_input_tokens": 1000, "total_output_tokens": 100,
                                               "total_thought_tokens": 100}, as_of=date(2026, 10, 9)), .0015)
        with self.assertRaises(ValueError):
            gemini_usage_usd({"total_input_tokens": True})
