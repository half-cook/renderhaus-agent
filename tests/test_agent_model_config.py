from __future__ import annotations

import importlib
import io
import os
import tempfile
import unittest
import warnings
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agent import backend_config


class AgentModelConfigTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_default_is_sonnet_with_medium_adaptive_thinking(self):
        fake = object()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-only"}), patch(
            "langchain.chat_models.init_chat_model", return_value=fake,
        ) as initialize:
            self.assertEqual(backend_config.deep_agent_model(), "anthropic:claude-sonnet-5-5")
            self.assertIs(backend_config.configured_deep_agent_model(), fake)
        initialize.assert_called_once_with(
            "anthropic:claude-sonnet-5-5", thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
        )

    def test_role_overrides_and_dispatch_effort_defaults(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-only"}), patch(
            "langchain.chat_models.init_chat_model", return_value=object(),
        ) as initialize:
            for role in ["planner", "media", "audio", "editor", "general-purpose"]:
                with self.subTest(role=role):
                    backend_config.configured_deep_agent_model(role)
                    self.assertEqual(initialize.call_args.args, ("anthropic:claude-sonnet-5-5",))
                    expected = "medium" if role in {"planner", "general-purpose"} else "low"
                    self.assertEqual(initialize.call_args.kwargs["output_config"], {"effort": expected})
            with patch.dict(os.environ, {
                "RENDERHAUS_AGENT_MODEL_PLANNER": "anthropic:claude-opus-5-5",
                "RENDERHAUS_AGENT_EFFORT_PLANNER": "high", "RENDERHAUS_AGENT_EFFORT": "medium",
            }):
                backend_config.configured_deep_agent_model("planner")
                self.assertEqual(initialize.call_args.args, ("anthropic:claude-opus-5-5",))
                self.assertEqual(initialize.call_args.kwargs["output_config"], {"effort": "high"})
            with patch.dict(os.environ, {"RENDERHAUS_AGENT_MODEL": "anthropic:claude-haiku-4-5"}):
                backend_config.configured_deep_agent_model()
                self.assertEqual(initialize.call_args.kwargs, {})

    def test_previous_openai_model_aliases_remain_selectable(self):
        for value in ["openai:gpt-5.6-luna", "openai/gpt-5.6-luna", "gpt-5.6-luna"]:
            with self.subTest(model=value), patch.dict(os.environ, {"RENDERHAUS_AGENT_MODEL": value}):
                self.assertEqual(backend_config.deep_agent_model(), "openai:gpt-5.6-luna")

    def test_legacy_model_fallback_and_explicit_model_precedence(self):
        with patch.dict(os.environ, {"AGENT_MODEL": "gpt-5.6-luna"}):
            self.assertEqual(backend_config.deep_agent_model(), "openai:gpt-5.6-luna")
            with patch.dict(os.environ, {"RENDERHAUS_AGENT_MODEL": "anthropic:claude-sonnet-5-5"}):
                self.assertEqual(backend_config.deep_agent_model(), "anthropic:claude-sonnet-5-5")

    def test_blank_model_values_fall_back_to_legacy_or_sonnet(self):
        for empty in ["", "  "]:
            with self.subTest(value=empty), patch.dict(os.environ, {
                "RENDERHAUS_AGENT_MODEL": empty, "AGENT_MODEL": empty,
            }):
                self.assertEqual(backend_config.deep_agent_model(), "anthropic:claude-sonnet-5-5")
            with patch.dict(os.environ, {"RENDERHAUS_AGENT_MODEL": empty, "AGENT_MODEL": "gpt-5.6-luna"}):
                self.assertEqual(backend_config.deep_agent_model(), "openai:gpt-5.6-luna")

    def test_provider_prefix_allowlist_accepts_supported_providers(self):
        for provider in ["openai", "anthropic", "bedrock", "bedrock_converse"]:
            with self.subTest(provider=provider), patch.dict(os.environ, {
                "RENDERHAUS_AGENT_MODEL": provider + ":test-model",
            }):
                self.assertEqual(backend_config.deep_agent_model(), provider + ":test-model")

    def test_unknown_provider_prefix_fails_with_supported_choices(self):
        for model in ["unknown:test", "unknown/test", ":test"]:
            with self.subTest(model=model), patch.dict(os.environ, {"RENDERHAUS_AGENT_MODEL": model}):
                with self.assertRaisesRegex(ValueError, "Supported.*openai.*anthropic.*bedrock"):
                    backend_config.deep_agent_model()

    def test_missing_provider_model_id_is_rejected(self):
        for model in ["anthropic:", "openai/", "bedrock_converse:  "]:
            with self.subTest(model=model), patch.dict(os.environ, {"RENDERHAUS_AGENT_MODEL": model}):
                with self.assertRaisesRegex(ValueError, "model ID"):
                    backend_config.deep_agent_model()

    def test_effort_override_uses_only_anthropic_output_config(self):
        for effort in ["low", "medium", "high", "xhigh", "max"]:
            with self.subTest(effort=effort), patch.dict(os.environ, {
                "ANTHROPIC_API_KEY": "test-only", "RENDERHAUS_AGENT_EFFORT": effort,
            }), patch("langchain.chat_models.init_chat_model", return_value=object()) as initialize:
                backend_config.configured_deep_agent_model()
                self.assertEqual(initialize.call_args.kwargs["output_config"], {"effort": effort})

    def test_blank_effort_uses_medium(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-only", "RENDERHAUS_AGENT_EFFORT": " "}), patch(
            "langchain.chat_models.init_chat_model", return_value=object(),
        ) as initialize:
            backend_config.configured_deep_agent_model()
        self.assertEqual(initialize.call_args.kwargs["output_config"], {"effort": "medium"})

    def test_invalid_effort_fails_before_model_construction(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-only", "RENDERHAUS_AGENT_EFFORT": "extreme"}), patch(
            "langchain.chat_models.init_chat_model",
        ) as initialize:
            with self.assertRaisesRegex(ValueError, "RENDERHAUS_AGENT_EFFORT"):
                backend_config.configured_deep_agent_model()
        initialize.assert_not_called()

    def test_missing_anthropic_key_is_a_clear_construction_error(self):
        for value in ["", " "]:
            with self.subTest(value=value), patch.dict(os.environ, {"ANTHROPIC_API_KEY": value}), patch(
                "langchain.chat_models.init_chat_model",
            ) as initialize:
                with self.assertRaisesRegex(RuntimeError, "ANTHROPIC_API_KEY.*Anthropic"):
                    backend_config.configured_deep_agent_model()
                initialize.assert_not_called()

    def test_configuration_and_import_do_not_require_anthropic_credentials(self):
        importlib.reload(backend_config)
        self.assertEqual(backend_config.deep_agent_model(), "anthropic:claude-sonnet-5-5")
        self.assertFalse(backend_config.agent_configured())

    def test_other_providers_preserve_deepagents_model_initialization(self):
        for model in ["openai:gpt-5.6-luna", "bedrock:anthropic.test", "bedrock_converse:anthropic.test"]:
            with self.subTest(model=model), patch.dict(os.environ, {
                "RENDERHAUS_AGENT_MODEL": model, "RENDERHAUS_AGENT_EFFORT": "irrelevant",
            }), patch("langchain.chat_models.init_chat_model") as initialize:
                self.assertEqual(backend_config.configured_deep_agent_model(), model)
                initialize.assert_not_called()

    def test_selected_provider_credentials_and_codex_fallback(self):
        cases = [
            ({"RENDERHAUS_AGENT_MODEL": "anthropic:test", "ANTHROPIC_API_KEY": "test-only"}, True),
            ({"RENDERHAUS_AGENT_MODEL": "anthropic:test", "OPENAI_API_KEY": "test-only"}, False),
            ({"RENDERHAUS_AGENT_MODEL": "openai:test", "OPENAI_API_KEY": "test-only"}, True),
            ({"RENDERHAUS_AGENT_MODEL": "openai:test", "ANTHROPIC_API_KEY": "test-only"}, False),
            ({"RENDERHAUS_AGENT_MODEL": "bedrock:test"}, True),
            ({"RENDERHAUS_AGENT_MODEL": "bedrock_converse:test"}, True),
            ({"RENDERHAUS_AGENT_BACKEND": "codex", "OPENAI_API_KEY": "test-only"}, True),
            ({"RENDERHAUS_AGENT_BACKEND": "codex", "ANTHROPIC_API_KEY": "test-only"}, False),
            ({"RENDERHAUS_AGENT_MODEL": "anthropic:test", "ANTHROPIC_API_KEY": " "}, False),
        ]
        for env, expected in cases:
            with self.subTest(env=list(env)), patch.dict(os.environ, env, clear=True):
                self.assertEqual(backend_config.agent_configured(), expected)

    def test_studio_env_loading_keeps_sonnet_default_and_explicit_legacy_selection(self):
        from server import config

        for env, expected in [({}, "anthropic:claude-sonnet-5-5"), ({"AGENT_MODEL": "gpt-5.6-luna"}, "openai:gpt-5.6-luna")]:
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True), patch.object(
                config, "load_dotenv",
            ), patch.object(config, "secrets_locator", return_value=None), patch.object(
                config, "load_secrets_from_manager",
            ) as secrets:
                config.load_local_env()
                self.assertEqual(backend_config.deep_agent_model(), expected)
                secrets.assert_not_called()

    def test_secret_payload_and_application_preserve_anthropic_config_without_output(self):
        from server.secrets import apply_secret_map, secret_payload_from_mapping

        values = {"ANTHROPIC_API_KEY": "test-only", "RENDERHAUS_AGENT_MODEL": "anthropic:claude-sonnet-5-5",
                  "RENDERHAUS_AGENT_EFFORT": "high", "AWS_SECRET_ACCESS_KEY": "excluded-test-only"}
        payload = secret_payload_from_mapping(values)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", payload)
        self.assertEqual(set(payload), {"ANTHROPIC_API_KEY", "RENDERHAUS_AGENT_MODEL", "RENDERHAUS_AGENT_EFFORT"})
        with patch("builtins.print") as output:
            apply_secret_map(payload)
        output.assert_not_called()
        self.assertTrue(backend_config.agent_configured())

    def test_runtime_bootstrap_carries_model_settings_without_credentials(self):
        from scripts import deploy_agentcore

        with patch.dict(os.environ, {
            "RENDERHAUS_AGENT_BACKEND": "deepagents", "RENDERHAUS_AGENT_MODEL": "anthropic:claude-sonnet-5-5",
            "RENDERHAUS_AGENT_EFFORT": "high", "ANTHROPIC_API_KEY": "test-only", "OPENAI_API_KEY": "test-only",
        }), patch("server.config.load_local_env"):
            env = deploy_agentcore.load_bootstrap_env(secret_name="test-config")
        self.assertEqual(env["RENDERHAUS_AGENT_BACKEND"], "deepagents")
        self.assertEqual(env["RENDERHAUS_AGENT_MODEL"], "anthropic:claude-sonnet-5-5")
        self.assertEqual(env["RENDERHAUS_AGENT_EFFORT"], "high")
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("OPENAI_API_KEY", env)

    def test_deployment_validates_the_selected_provider_before_aws_calls(self):
        from scripts import deploy_agentcore

        cases = [
            ({"RENDERHAUS_AGENT_MODEL": "anthropic:test", "ANTHROPIC_API_KEY": "test-only"}, True),
            ({"RENDERHAUS_AGENT_MODEL": "anthropic:test", "OPENAI_API_KEY": "test-only"}, False),
            ({"RENDERHAUS_AGENT_MODEL": "openai:test", "OPENAI_API_KEY": "test-only"}, True),
            ({"RENDERHAUS_AGENT_MODEL": "bedrock_converse:test"}, True),
            ({"RENDERHAUS_AGENT_BACKEND": "codex", "ANTHROPIC_API_KEY": "test-only"}, False),
        ]
        for env, configured in cases:
            with self.subTest(env=list(env)), patch.dict(os.environ, env, clear=True), patch(
                "sys.argv", ["deploy_agentcore.py"],
            ), patch.object(deploy_agentcore, "load_bootstrap_env", return_value={"AWS_S3_BUCKET": "test-bucket"}), patch.object(
                deploy_agentcore.boto3.session, "Session", side_effect=RuntimeError("AWS boundary stopped"),
            ) as aws, redirect_stderr(io.StringIO()) as stderr:
                if configured:
                    with self.assertRaisesRegex(RuntimeError, "AWS boundary stopped"):
                        deploy_agentcore.main()
                    aws.assert_called_once()
                else:
                    self.assertEqual(deploy_agentcore.main(), 1)
                    aws.assert_not_called()
                    self.assertIn("selected agent", stderr.getvalue().lower())
                self.assertNotIn("test-only", stderr.getvalue())

    def test_installed_anthropic_adapter_keeps_effort_and_auto_tools_without_warning(self):
        from langchain_anthropic import ChatAnthropic
        from langchain_core.messages import HumanMessage

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-only"}):
            model = ChatAnthropic(model="claude-sonnet-5-5", thinking={"type": "adaptive"}, output_config={"effort": "medium"})
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always")
            bound = model.bind_tools([{"name": "finish", "description": "Finish", "input_schema": {"type": "object"}}], tool_choice="auto")
        self.assertEqual(bound.kwargs["tool_choice"], {"type": "auto"})
        self.assertFalse(observed)
        payload = model._get_request_payload([HumanMessage(content="Plan a storyboard")])
        self.assertEqual(payload["thinking"], {"type": "adaptive"})
        self.assertEqual(payload["output_config"], {"effort": "medium"})


class AgentModelGraphTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = patch.dict(os.environ, {"RENDERHAUS_OUTCOME_DIR": str(Path(directory.name) / "outcomes")}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    async def test_missing_anthropic_credentials_fail_before_gateway_discovery(self):
        from agent.deep_agent.runner import run_with_servers
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request
        from test_deep_agent import IMAGE, Gateway

        request = StudioAgentRequest(prompt="Make an outline")
        gateway = Gateway()
        with patch.object(gateway, "list_tools", new=AsyncMock(return_value=[IMAGE])) as discover:
            with self.assertRaisesRegex(RuntimeError, "ANTHROPIC_API_KEY"):
                await run_with_servers(request, _context_from_request(request), [gateway])
        discover.assert_not_awaited()

    async def test_explicit_fake_bypasses_model_factory_and_credentials(self):
        from agent.deep_agent.runner import run_with_servers
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request
        from test_deep_agent import FINAL, Gateway, ScriptedModel, final

        request = StudioAgentRequest(prompt="Make an outline")
        model = ScriptedModel([final()])
        with patch("agent.deep_agent.runner.configured_deep_agent_model", create=True, side_effect=AssertionError("Factory must be bypassed")):
            result = await run_with_servers(request, _context_from_request(request), [Gateway()], model=model)
        self.assertEqual(result.title, FINAL["title"])

    async def test_configured_fake_is_shared_with_delegated_roles(self):
        from agent.deep_agent.runner import run_with_servers
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request
        from langchain_core.messages import AIMessage
        from test_deep_agent import FINAL, Gateway, ScriptedModel, call, final

        request = StudioAgentRequest(prompt="Make an outline")
        model = ScriptedModel([
            call("task", {"subagent_type": "planner", "description": "Plan two shots"}, "delegate"),
            AIMessage(content="Two shots planned."), final(),
        ])
        with patch("agent.deep_agent.runner.configured_deep_agent_model", create=True, return_value=model) as factory, patch(
            "agent.deep_agent.runner.deep_agent_model", create=True, side_effect=AssertionError("Configured factory required"),
        ):
            result = await run_with_servers(request, _context_from_request(request), [Gateway()])
        self.assertEqual(result.title, FINAL["title"])
        self.assertEqual(factory.call_count, 6)
        self.assertEqual(len(model._seen), 3)

    async def test_studio_context_returns_routed_rows_and_only_requested_schema(self):
        import json
        from agent.deep_agent.runner import run_with_servers
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request
        from test_deep_agent import Gateway, ScriptedModel, call, final
        from mcp import Tool

        video = Tool(name="Fal___wan3_text_to_video", description="Generate Wan", inputSchema={"type": "object"})
        huge = Tool(name="ElevenLabs___models_list", description="x" * 30_000, inputSchema={"type": "object"})
        request = StudioAgentRequest(prompt="Make a 5-second cinematic shot")

        def compact(messages, tools):
            context = json.loads(messages[-1].text)
            self.assertLess(len(messages[-1].text), 10_000)
            self.assertTrue(all(isinstance(name, str) for name in context["tools"]))
            self.assertLessEqual(len(context["capabilities"]), 3)
            return call("read_studio_context", {"tool_name": video.name}, "named-context")

        def named(messages, tools):
            context = json.loads(messages[-1].text)
            self.assertEqual(context["tool_schema"]["name"], video.name)
            self.assertNotIn(huge.description, messages[-1].text)
            return final()

        await run_with_servers(request, _context_from_request(request), [Gateway(tools=[video, huge])],
                               model=ScriptedModel([call("read_studio_context", {}, "context"), compact, named]))

    async def test_missing_completion_is_repaired_without_paid_dispatch(self):
        from agent.deep_agent.runner import run_with_servers
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request
        from langchain_core.messages import AIMessage
        from test_deep_agent import Gateway, ScriptedModel, image, final

        request = StudioAgentRequest(prompt="Make an outline", autonomous=True)
        gateway = Gateway()
        model = ScriptedModel([AIMessage(content="Finished"), image(), final()])
        result = await run_with_servers(request, _context_from_request(request), [gateway], model=model)
        self.assertTrue(result.markdown)
        gateway.call_tool.assert_not_awaited()
        self.assertIn("Do not repeat media", model._seen[1][0][-1].text)
        self.assertIn("completion repair", model._seen[2][0][-1].text)

    async def test_completion_repair_uses_the_run_deadline(self):
        import asyncio
        from agent.deep_agent.runner import run_with_servers
        from agent.errors import AgentRunLimitExceeded
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request
        from langchain_core.messages import AIMessage
        from test_deep_agent import Gateway, ScriptedModel

        class StalledRepair(ScriptedModel):
            async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
                if not self._steps:
                    await asyncio.Event().wait()
                return self._generate(messages, stop=stop, **kwargs)

        request = StudioAgentRequest(prompt="Make an outline")
        with patch.dict(os.environ, {"RENDERHAUS_AGENT_TIMEOUT_SECONDS": "0.5"}):
            with self.assertRaises(AgentRunLimitExceeded):
                await asyncio.wait_for(run_with_servers(request, _context_from_request(request), [Gateway()],
                    model=StalledRepair([AIMessage(content="Done")])), timeout=2)

    async def test_approval_resume_preserves_system_tools_and_history(self):
        import json
        from agent.deep_agent.runner import run_with_servers
        from agent.studio_agent_next import StudioAgentRequest, StudioAgentApprovalRequired, StudioApprovalDecision, _context_from_request
        from test_deep_agent import Gateway, ScriptedModel, image, read_skill, final
        from langchain_core.utils.function_calling import convert_to_openai_tool
        from pydantic import PrivateAttr

        class CaptureModel(ScriptedModel):
            _schemas: list = PrivateAttr(default_factory=list)

            def bind_tools(self, tools, **kwargs):
                self._schemas.append(json.dumps([convert_to_openai_tool(t) for t in tools], sort_keys=True))
                return super().bind_tools(tools, **kwargs)

        request = StudioAgentRequest(prompt="Make this still with Seedream")
        studio = _context_from_request(request)
        gateway = Gateway()
        first = CaptureModel([read_skill(), image()])
        with self.assertRaises(StudioAgentApprovalRequired) as paused:
            await run_with_servers(request, studio, [gateway], model=first)
        decision = StudioApprovalDecision(call_id=paused.exception.approvals[0].call_id, decision="approve")
        resumed = request.model_copy(update={"session_items": studio.session_items,
                                           "resume_state": paused.exception.state, "approval_decisions": [decision]})
        second = CaptureModel([final()])
        await run_with_servers(resumed, _context_from_request(resumed), [gateway], model=second)
        self.assertTrue(all(schema == second._schemas[0] for schema in first._schemas))
        for messages, tools in first._seen:
            self.assertEqual(messages[0].model_dump(), second._seen[0][0][0].model_dump())
            self.assertEqual(tools, second._seen[0][1])
            self.assertEqual([m.model_dump() for m in messages[1:]],
                             [m.model_dump() for m in second._seen[0][0][1:len(messages)]])

    async def test_anthropic_completion_tool_sends_verified_settings_without_warning_over_mock_http(self):
        import json

        import anthropic
        import httpx2 as httpx

        from agent.deep_agent.runner import run_with_servers
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request
        from test_deep_agent import FINAL, Gateway

        payloads = []

        def response(request):
            payloads.append(json.loads(request.content))
            events = [
                {"type": "message_start", "message": {
                    "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
                    "content": [], "stop_reason": None, "stop_sequence": None,
                    "usage": {"input_tokens": 10, "output_tokens": 0},
                }},
                {"type": "content_block_start", "index": 0, "content_block": {
                    "type": "tool_use", "id": "finish", "name": "StudioAgentOutput", "input": {},
                }},
                {"type": "content_block_delta", "index": 0, "delta": {
                    "type": "input_json_delta", "partial_json": json.dumps(FINAL),
                }},
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                 "usage": {"output_tokens": 10}},
                {"type": "message_stop"},
            ]
            stream = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
            return httpx.Response(200, content=stream, headers={"content-type": "text/event-stream"})

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-only"}):
            model = backend_config.configured_deep_agent_model()
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
            model.__dict__["_async_client"] = anthropic.AsyncClient(
                api_key="test-only", http_client=http, max_retries=0,
            )
            request = StudioAgentRequest(prompt="Make an outline")
            with patch("agent.deep_agent.runner.configured_deep_agent_model", return_value=model), warnings.catch_warnings():
                warnings.filterwarnings("error", message="tool_choice is forced but thinking is enabled")
                result = await run_with_servers(request, _context_from_request(request), [Gateway()])
        self.assertEqual(result.title, FINAL["title"])
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["thinking"], {"type": "adaptive"})
        self.assertEqual(payloads[0]["output_config"], {"effort": "medium"})
        self.assertEqual(payloads[0]["model"], "claude-sonnet-5-5")
        self.assertGreater(payloads[0]["max_tokens"], 0)
        for parameter in ("temperature", "top_p", "top_k"):
            self.assertNotIn(parameter, payloads[0])
        self.assertEqual(payloads[0]["messages"][-1]["role"], "user")
        self.assertNotIn("tool_choice", payloads[0])
        self.assertIn("StudioAgentOutput", {tool["name"] for tool in payloads[0]["tools"]})
