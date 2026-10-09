from __future__ import annotations

import importlib
import io
import os
import tempfile
import unittest
import warnings
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from agent import backend_config


class AgentModelConfigTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_default_is_opus_with_high_adaptive_thinking(self):
        fake = object()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-only"}), patch(
            "langchain.chat_models.init_chat_model", return_value=fake,
        ) as initialize:
            self.assertEqual(backend_config.deep_agent_model(), "anthropic:claude-opus-5-5")
            self.assertIs(backend_config.configured_deep_agent_model(), fake)
        initialize.assert_called_once_with(
            "anthropic:claude-opus-5-5", thinking={"type": "adaptive"},
            output_config={"effort": "high"},
        )

    def test_previous_openai_model_aliases_remain_selectable(self):
        for value in ["openai:gpt-5.6-luna", "openai/gpt-5.6-luna", "gpt-5.6-luna"]:
            with self.subTest(model=value), patch.dict(os.environ, {"RENDERHAUS_AGENT_MODEL": value}):
                self.assertEqual(backend_config.deep_agent_model(), "openai:gpt-5.6-luna")

    def test_legacy_model_fallback_and_explicit_model_precedence(self):
        with patch.dict(os.environ, {"AGENT_MODEL": "gpt-5.6-luna"}):
            self.assertEqual(backend_config.deep_agent_model(), "openai:gpt-5.6-luna")
            with patch.dict(os.environ, {"RENDERHAUS_AGENT_MODEL": "anthropic:claude-opus-5-5"}):
                self.assertEqual(backend_config.deep_agent_model(), "anthropic:claude-opus-5-5")

    def test_blank_model_values_fall_back_to_legacy_or_opus(self):
        for empty in ["", "  "]:
            with self.subTest(value=empty), patch.dict(os.environ, {
                "RENDERHAUS_AGENT_MODEL": empty, "AGENT_MODEL": empty,
            }):
                self.assertEqual(backend_config.deep_agent_model(), "anthropic:claude-opus-5-5")
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

    def test_blank_effort_uses_high(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-only", "RENDERHAUS_AGENT_EFFORT": " "}), patch(
            "langchain.chat_models.init_chat_model", return_value=object(),
        ) as initialize:
            backend_config.configured_deep_agent_model()
        self.assertEqual(initialize.call_args.kwargs["output_config"], {"effort": "high"})

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
        self.assertEqual(backend_config.deep_agent_model(), "anthropic:claude-opus-5-5")
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

    def test_studio_env_loading_keeps_opus_default_and_explicit_legacy_selection(self):
        from server import config

        for env, expected in [({}, "anthropic:claude-opus-5-5"), ({"AGENT_MODEL": "gpt-5.6-luna"}, "openai:gpt-5.6-luna")]:
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

        values = {"ANTHROPIC_API_KEY": "test-only", "RENDERHAUS_AGENT_MODEL": "anthropic:claude-opus-5-5",
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
            "RENDERHAUS_AGENT_BACKEND": "deepagents", "RENDERHAUS_AGENT_MODEL": "anthropic:claude-opus-5-5",
            "RENDERHAUS_AGENT_EFFORT": "high", "ANTHROPIC_API_KEY": "test-only", "OPENAI_API_KEY": "test-only",
        }), patch("server.config.load_local_env"):
            env = deploy_agentcore.load_bootstrap_env(secret_name="test-config")
        self.assertEqual(env["RENDERHAUS_AGENT_BACKEND"], "deepagents")
        self.assertEqual(env["RENDERHAUS_AGENT_MODEL"], "anthropic:claude-opus-5-5")
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

    def test_installed_anthropic_adapter_keeps_effort_and_allows_toolstrategy_with_thinking(self):
        from langchain_anthropic import ChatAnthropic
        from langchain_core.messages import HumanMessage

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-only"}):
            model = ChatAnthropic(model="claude-opus-5-5", thinking={"type": "adaptive"}, output_config={"effort": "high"})
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always")
            bound = model.bind_tools([{"name": "finish", "description": "Finish", "input_schema": {"type": "object"}}], tool_choice="any")
        self.assertNotIn("tool_choice", bound.kwargs)
        self.assertTrue(any("thinking" in str(warning.message) for warning in observed))
        payload = model._get_request_payload([HumanMessage(content="Plan a storyboard")])
        self.assertEqual(payload["thinking"], {"type": "adaptive"})
        self.assertEqual(payload["output_config"], {"effort": "high"})


class AgentModelGraphTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        env = patch.dict(os.environ, {"RENDERHAUS_OUTCOME_DIR": str(Path(directory.name) / "outcomes")}, clear=True)
        env.start()
        self.addCleanup(env.stop)

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
        factory.assert_called_once_with()
        self.assertEqual(len(model._seen), 3)

    async def test_anthropic_toolstrategy_sends_verified_settings_over_mock_http(self):
        import json

        import anthropic
        import httpx

        from agent.deep_agent.runner import run_with_servers
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request
        from test_deep_agent import FINAL, Gateway

        payloads = []

        def response(request):
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json={
                "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                "content": [{"type": "tool_use", "id": "finish", "name": "StudioAgentOutput", "input": FINAL}],
                "stop_reason": "tool_use", "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 10},
            })

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-only"}):
            model = backend_config.configured_deep_agent_model()
        model.disable_streaming = True
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
            model.__dict__["_async_client"] = anthropic.AsyncClient(
                api_key="test-only", http_client=http, max_retries=0,
            )
            request = StudioAgentRequest(prompt="Make an outline")
            with patch("agent.deep_agent.runner.configured_deep_agent_model", return_value=model), warnings.catch_warnings():
                warnings.filterwarnings("ignore", message="tool_choice is forced but thinking is enabled")
                result = await run_with_servers(request, _context_from_request(request), [Gateway()])
        self.assertEqual(result.title, FINAL["title"])
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["thinking"], {"type": "adaptive"})
        self.assertEqual(payloads[0]["output_config"], {"effort": "high"})
        self.assertEqual(payloads[0]["model"], "claude-opus-5-5")
        self.assertGreater(payloads[0]["max_tokens"], 0)
        self.assertNotIn("tool_choice", payloads[0])
        self.assertIn("StudioAgentOutput", {tool["name"] for tool in payloads[0]["tools"]})
