from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from langchain_core.messages import ToolMessage
from mcp import Tool

from agent.deep_agent.routing import effective_model, estimate_cost
from agent.deep_agent.runner import run_with_servers
from agent.gateway_executor import GatewayExecutor
from agent.studio_agent_next import StudioAgentApprovalRequired, StudioAgentRequest, _context_from_request
from providers.elevenlabs import api
from providers.elevenlabs.catalog import build_catalog
from server import billing_rates as rates
from test_deep_agent import Gateway, ScriptedModel, call, final


TTS_TOOLS = (
    "text_to_speech_convert", "text_to_speech_convert_with_timestamps",
    "text_to_speech_stream", "text_to_speech_stream_with_timestamps",
)
ALLOWED = r"Allowed model_ids:.*eleven_v4.*eleven_v4_turbo"
ROOT = Path(__file__).resolve().parents[1]


class TTSModelPinTests(unittest.TestCase):
    def test_stored_and_generated_tts_choices_are_priced(self):
        stored = json.loads((ROOT / "configs/gateway/elevenlabs.tools.json").read_text())
        generated = [entry["tool"] for entry in build_catalog().values()]
        for schemas in (stored, generated):
            for tool in schemas:
                if tool["name"] not in TTS_TOOLS:
                    continue
                with self.subTest(tool=tool["name"], stored=schemas is stored):
                    model = tool["inputSchema"]["properties"]["model_id"]
                    match = re.search(r"enum: (\[[^\]]+\])", model["description"])
                    offered = model.get("enum") or (json.loads(match[1]) if match else [])
                    self.assertTrue(offered, "TTS discovery must enumerate priced model_ids")
                    self.assertLessEqual(set(offered), rates.ELEVENLABS_CHARACTER_MULTIPLIERS.keys())
                    advertised = set(re.findall(r"\beleven_[a-z0-9_]+\b", model["description"]))
                    self.assertLessEqual(advertised, rates.ELEVENLABS_CHARACTER_MULTIPLIERS.keys())
                    self.assertIn("ELEVENLABS_TTS_MODEL", model["description"])
                    self.assertIn('default: "eleven_v4_turbo"', model["description"])

    def test_unpriced_models_are_rejected_at_estimate_time_even_with_operator_quote(self):
        for verb in TTS_TOOLS:
            for quotes in ("{}", json.dumps({verb: 1})):
                with self.subTest(verb=verb, quotes=quotes), patch.dict(os.environ, {
                    "ELEVENLABS_TOOL_COST_CENTS_JSON": quotes,
                }, clear=True):
                    with self.assertRaisesRegex(ValueError, ALLOWED):
                        estimate_cost("ElevenLabs___" + verb, {"text": "Hello", "model_id": "eleven_multilingual_v2"})
                    with self.assertRaisesRegex(ValueError, ALLOWED):
                        rates.elevenlabs_quote(verb, {"text": "Hello", "model_id": "eleven_multilingual_v2"})

    def test_default_and_explicit_priced_models_quote_all_variants(self):
        for verb in TTS_TOOLS:
            for configured, explicit, expected_model, cents in (
                (None, None, "eleven_v4_turbo", 40),
                ("eleven_v4", None, "eleven_v4", 80),
                ("eleven_v4", "eleven_v4_turbo", "eleven_v4_turbo", 40),
                (None, "eleven_v4", "eleven_v4", 80),
            ):
                env = {} if configured is None else {"ELEVENLABS_TTS_MODEL": configured}
                args = {"text": "a" * 10000}
                if explicit is not None:
                    args["model_id"] = explicit
                with self.subTest(verb=verb, configured=configured, explicit=explicit), \
                        patch.dict(os.environ, env, clear=True), patch.object(rates, "date") as clock:
                    clock.today.return_value = date(2026, 10, 13)
                    self.assertEqual(effective_model("elevenlabs", verb, args), expected_model)
                    cost = rates.elevenlabs_quote(verb, args)
                    self.assertEqual(cost.provider_cents, cents)
                    self.assertEqual(estimate_cost("ElevenLabs___" + verb, args).total_cents, cost.total_cents)

    def test_bad_configured_default_fails_clearly(self):
        for configured in ("eleven_multilingual_v2", ""):
            with self.subTest(configured=configured), patch.dict(os.environ, {
                "ELEVENLABS_TTS_MODEL": configured,
            }, clear=True):
                with self.assertRaisesRegex(ValueError, "ELEVENLABS_TTS_MODEL.*" + ALLOWED):
                    estimate_cost("ElevenLabs___text_to_speech_convert", {"text": "Hello"})

    def test_provider_boundary_rejects_unpriced_models_without_io(self):
        for verb in TTS_TOOLS:
            for dry_run in ("true", "false"):
                with self.subTest(verb=verb, dry_run=dry_run), patch.dict(os.environ, {
                    "ELEVENLABS_DRY_RUN": dry_run,
                }, clear=True), patch.object(api, "api_key", side_effect=AssertionError("Credentials read before model validation")) as key, \
                        patch.object(api.httpx, "Client", side_effect=AssertionError("Provider I/O before model validation")) as client:
                    args = {"voice_id": "authorized", "text": "Hello", "model_id": "eleven_multilingual_v2"}
                    with self.assertRaisesRegex(ValueError, ALLOWED):
                        api.dispatch_tool(verb, args)
                    key.assert_not_called()
                    client.assert_not_called()

    def test_prepare_request_uses_the_same_configured_default_as_the_quote(self):
        for verb in TTS_TOOLS:
            with self.subTest(verb=verb), patch.dict(os.environ, {"ELEVENLABS_TTS_MODEL": "eleven_v4"}, clear=True):
                body = api.prepare_request(verb, {"voice_id": "authorized", "text": "Hello"})[3]
                self.assertEqual(body.get("model_id"), "eleven_v4")


class TTSApprovalGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_schema_unpriced_tts_is_failed_before_approval_or_dispatch(self):
        for verb in TTS_TOOLS:
            tool = Tool(name="ElevenLabs___" + verb, description="Stale TTS schema", inputSchema={"type": "object"})
            for autonomous in (False, True):
                with self.subTest(verb=verb, autonomous=autonomous), tempfile.TemporaryDirectory() as directory, \
                        patch.dict(os.environ, {"RENDERHAUS_OUTCOME_DIR": directory}, clear=True):
                    gateway = Gateway([tool])
                    request = StudioAgentRequest(prompt="Narrate hello", autonomous=autonomous)
                    studio = _context_from_request(request)
                    executor = GatewayExecutor(studio, [gateway])
                    args = {"voice_id": "authorized", "text": "Hello", "model_id": "eleven_multilingual_v2"}
                    try:
                        result = await executor.execute({"tool_name": tool.name, "arguments": args, "call_id": "bad-model"})
                    except Exception as exc:
                        self.fail(f"Invalid TTS must be a failed tool result before approval: {type(exc).__name__}: {exc}")
                    self.assertEqual(result["status"], "failed")
                    self.assertRegex(result["error"], ALLOWED)
                    gateway.call_tool.assert_not_awaited()
                    self.assertEqual(executor.reservations, {})

    async def test_native_deep_agent_returns_correctable_error_without_interrupt(self):
        for verb in TTS_TOOLS:
            tool = Tool(name="ElevenLabs___" + verb, description="Stale TTS schema", inputSchema={"type": "object"})
            gateway = Gateway([tool])

            def inspect_error(messages, tools):
                self.assertIsInstance(messages[-1], ToolMessage)
                result = json.loads(messages[-1].text)
                self.assertEqual(result["status"], "failed")
                self.assertRegex(result["error"], ALLOWED)
                return final()

            model = ScriptedModel([
                call("call_audio_tool", {"tool_name": tool.name, "arguments": {
                    "voice_id": "authorized", "text": "Hello", "model_id": "eleven_multilingual_v2",
                }}, "bad-model"), inspect_error,
            ])
            request = StudioAgentRequest(prompt="Narrate hello", autonomous=False)
            with self.subTest(verb=verb), tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                "RENDERHAUS_OUTCOME_DIR": directory, "STRIPE_SECRET_KEY": "", "ELEVENLABS_TOOL_COST_CENTS_JSON": "{}",
            }, clear=True):
                studio = _context_from_request(request)
                try:
                    await run_with_servers(request, studio, [gateway], model=model)
                except StudioAgentApprovalRequired:
                    self.fail("Unpriced TTS requested approval instead of returning a correctable error")
            gateway.call_tool.assert_not_awaited()
            self.assertFalse(model._steps)

    async def test_missing_stripe_quote_fails_before_approval(self):
        from test_deep_agent_execution import TTS, TTS_ARGS

        gateway = Gateway([TTS])
        request = StudioAgentRequest(prompt="Narrate hello", autonomous=False)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "RENDERHAUS_OUTCOME_DIR": directory, "STRIPE_SECRET_KEY": "test-only",
            "ELEVENLABS_TOOL_COST_CENTS_JSON": "{}",
        }, clear=True):
            executor = GatewayExecutor(_context_from_request(request), [gateway])
            try:
                result = await executor.execute({"tool_name": TTS.name, "arguments": TTS_ARGS, "call_id": "no-quote"})
            except Exception as exc:
                self.fail(f"Missing quote must fail before approval: {type(exc).__name__}: {exc}")
        self.assertEqual(result["status"], "failed")
        self.assertIn("ELEVENLABS_TOOL_COST_CENTS_JSON", result["error"])
        gateway.call_tool.assert_not_awaited()
