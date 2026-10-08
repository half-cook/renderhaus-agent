from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from mcp import Tool

from providers.catalog import get_provider
from providers.registry import dispatch, generate_schemas, load_committed_schemas
from server.billing_rates import cost_for
from server.secrets import secret_payload_from_mapping
from server.studio import _register_payload_assets, collect_asset_sources
from server.studio_state import StudioRepository


class RunwayGatewayTests(unittest.TestCase):
    def test_committed_schemas_match_generated_tools(self):
        spec = get_provider("runway")
        self.assertEqual(load_committed_schemas(spec), generate_schemas(spec))
        self.assertEqual(spec.target_name, "Runway")
        self.assertEqual(spec.function_name, "renderhaus-runway-tools")
        self.assertIn("RUNWAYML_API_SECRET", spec.env_keys)
        self.assertEqual(spec.default_env["RUNWAY_DRY_RUN"], "true")

    def test_contract_rejects_bad_arguments_before_handler(self):
        from providers.runway import api

        cases = [
            ("text_to_video", {"prompt": "Move", "duration_seconds": 11}),
            ("text_to_video", {"prompt": "Move", "duration_seconds": True}),
            ("text_to_video", {"prompt": "Move", "ratio": "960:960"}),
            ("text_to_video", {"prompt": "Move", "model": "gen4_aleph"}),
            ("text_to_video", {"prompt": " ", "seed": 1}),
            ("image_to_video", {"prompt": "Move", "image_path_or_url": "http://example.test/a.png"}),
            ("text_to_image", {"prompt": "Still", "model": "gen4_image_turbo"}),
            ("video_to_video", {"prompt": "Snow", "video_path_or_url": "https://example.com/a.mp4", "video_duration_seconds": 31}),
            ("video_to_video", {"prompt": "Snow", "video_path_or_url": "https://example.com/a.mp4", "video_duration_seconds": float("nan")}),
            ("get_runway_task", {"job_id": "../../etc/passwd"}),
        ]
        with patch.dict(os.environ, {"RUNWAY_DRY_RUN": "false", "RUNWAYML_API_SECRET": "test-key"}), patch.object(api.httpx, "Client") as client:
            for name, arguments in cases:
                with self.subTest(tool=name, arguments=arguments), self.assertRaises(ValueError):
                    dispatch("runway", name, arguments)
                client.assert_not_called()

    def test_lambda_routes_runway_context(self):
        from lambdas.handler import handler

        context = SimpleNamespace(client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": "Runway___text_to_video"}))
        with patch.dict(os.environ, {"RUNWAY_DRY_RUN": "true", "RENDERHAUS_PROVIDER": "runway"}):
            result = handler({"prompt": "Clouds drift"}, context)
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["provider"], "runway")

    def test_secret_sync_keeps_runway_and_excludes_aws_credentials(self):
        values = secret_payload_from_mapping({"RUNWAYML_API_SECRET": "test-value", "RUNWAY_DRY_RUN": "true", "AWS_SECRET_ACCESS_KEY": "excluded"})
        self.assertEqual(values, {"RUNWAYML_API_SECRET": "test-value", "RUNWAY_DRY_RUN": "true"})


class RunwayBillingTests(unittest.TestCase):
    def setUp(self):
        self.live = patch.dict(os.environ, {"RUNWAY_DRY_RUN": "false"})
        self.live.start()
        self.addCleanup(self.live.stop)

    def test_gen45_price_and_platform_fee(self):
        price = cost_for("runway", "text_to_video", {"duration_seconds": 5})
        self.assertEqual(price.public(), {"provider_cents": 60, "fee_cents": 18, "total_cents": 78})
        self.assertEqual(cost_for("runway", "image_to_video", {"duration_seconds": 10}).provider_cents, 120)

    def test_aleph_price_uses_input_duration(self):
        self.assertEqual(cost_for("runway", "video_to_video", {"video_duration_seconds": 2}).provider_cents, 56)
        self.assertEqual(cost_for("runway", "video_to_video", {"video_duration_seconds": 30}).provider_cents, 840)
        self.assertEqual(cost_for("runway", "video_to_video", {"video_duration_seconds": 3.5}).provider_cents, 98)

    def test_image_prices_by_resolution(self):
        self.assertEqual(cost_for("runway", "text_to_image", {"ratio": "1280:720"}).provider_cents, 5)
        self.assertEqual(cost_for("runway", "text_to_image", {"ratio": "1080:1080"}).provider_cents, 8)
        self.assertEqual(cost_for("runway", "image_to_image", {"ratio": "1920:1080", "model": "gen4_image_turbo"}).provider_cents, 2)

    def test_poll_and_model_catalog_are_free(self):
        for name in ("get_runway_task", "list_runway_models"):
            self.assertEqual(cost_for("runway", name, {}).public(), {"provider_cents": 0, "fee_cents": 0, "total_cents": 0})

    def test_dry_run_is_free_by_default_and_explicit_flag(self):
        with patch.dict(os.environ, {"RUNWAY_DRY_RUN": "true"}):
            self.assertEqual(cost_for("runway", "text_to_video", {}).total_cents, 0)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cost_for("runway", "text_to_image", {}).total_cents, 0)

    def test_unknown_or_unpriced_calls_do_not_get_fallback(self):
        for tool, args in [
            ("unknown", {}),
            ("text_to_image", {"ratio": "1360:768"}),
            ("text_to_image", {"model": "gen4_image_turbo"}),
            ("text_to_video", {"model": "aleph2"}),
            ("video_to_video", {}),
            ("video_to_video", {"video_duration_seconds": float("inf")}),
        ]:
            with self.subTest(tool=tool, args=args), self.assertRaises(ValueError):
                cost_for("runway", tool, args)


class RunwayPersistenceTests(unittest.TestCase):
    def test_remote_poll_output_becomes_durable_owned_media(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = StudioRepository(Path(temp) / "state.sqlite3", Path(temp) / "media")
            project = repo.create_project("workspace", "user", "Runway result")
            for kind, mime, filename in [("image", "image/png", "still.png"), ("video", "video/mp4", "clip.mp4")]:
                url = f"https://cdn.example.test/{filename}"
                content = b"offline media fixture"
                payload = {"status": "succeeded", "provider": "runway", f"{kind}_url": url}
                self.assertEqual(collect_asset_sources(payload)[0]["source"], url)

                @contextmanager
                def stream(*args, **kwargs):
                    yield httpx.Response(200, request=httpx.Request("GET", url), content=content, headers={"Content-Type": mime})

                with patch("server.studio.repository", repo), patch("server.studio_state.httpx.stream", stream):
                    assets = _register_payload_assets(payload=payload, workspace_id="workspace", project_id=project["id"], user_id="user")
                self.assertEqual(len(assets), 1)
                asset = assets[0]
                self.assertEqual(asset["kind"], kind)
                self.assertEqual(repo.version_path("workspace", asset["version_id"]).read_bytes(), content)
                self.assertIsNone(repo.get_version("other-workspace", asset["version_id"]))


class RunwayAgentPollingTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_gateway_host_waits_on_runway_poll(self):
        from agent.studio_agent_next import StudioAgentContext, StudioAgentRequest, run_studio_agent
        from test_codex_harness import FakeGateway, FakeHarness

        tool = Tool(name="Runway___get_runway_task", description="Poll", inputSchema={"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]})
        gateway = FakeGateway()
        gateway.list_tools = AsyncMock(return_value=[tool])
        gateway.call_tool = AsyncMock(side_effect=[{"status": "queued", "job_id": "job"}, {"status": "succeeded", "job_id": "job", "image_url": "https://cdn.example.test/still.png"}])
        harness = FakeHarness([{"callId": "runway-poll", "tool": "call_gateway_tool", "arguments": {"tool_name": tool.name, "arguments_json": '{"job_id":"job"}'}}])
        studio = StudioAgentContext(autonomous=True)
        with patch("agent.gateway_executor.asyncio.sleep", new=AsyncMock()) as sleep:
            await run_studio_agent(StudioAgentRequest(prompt="Check the image", autonomous=True), studio=studio, harness=harness, mcp_servers=[gateway])
        self.assertEqual(gateway.call_tool.await_count, 2)
        self.assertGreaterEqual(sleep.await_args.args[0], 5)
        self.assertEqual(len(studio.tool_events), 1)
        self.assertEqual(studio.tool_events[0].status, "succeeded")
