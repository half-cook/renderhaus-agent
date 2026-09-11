from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from agents.mcp import MCPServerStreamableHttp
from mcp import Tool
from mcp.types import CallToolResult, TextContent

from agent.fal_mcp import FAL_MCP_URL, FalMCPServer, fal_mcp_server
from agent.studio_agent_next import (
    StudioAgentContext,
    StudioAgentRequest,
    _append_harvested_event,
    _gateway_requires_approval,
    run_studio_agent,
)


class FalConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.loader = patch("agent.fal_mcp.load_local_env")
        self.loader.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.loader.stop)

    def test_optional_until_key_is_provided(self) -> None:
        self.assertIsNone(fal_mcp_server())
        os.environ["FAL_MCP_ENABLED"] = "true"
        with self.assertRaisesRegex(ValueError, "FAL_KEY is required"):
            fal_mcp_server()

    def test_explicit_disable_takes_precedence_over_key(self) -> None:
        os.environ.update(FAL_KEY="test-key", FAL_MCP_ENABLED="false")
        self.assertIsNone(fal_mcp_server())

    def test_key_connects_only_to_official_endpoint_with_existing_approval_policy(self) -> None:
        os.environ["FAL_KEY"] = " test-key "
        server = fal_mcp_server(require_approval=_gateway_requires_approval)
        self.assertIsInstance(server, FalMCPServer)
        self.assertEqual(server.params["url"], FAL_MCP_URL)
        self.assertEqual(server.params["headers"], {"Authorization": "Bearer test-key"})
        self.assertEqual(server._needs_approval_policy, _gateway_requires_approval)
        self.assertEqual(server.max_retry_attempts, 0)


class FalRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_tools_are_namespaced_without_mutating_the_sdk_cache(self) -> None:
        tool = Tool(name="search_models", inputSchema={"type": "object"})
        server = FalMCPServer({"url": FAL_MCP_URL})
        with patch.object(MCPServerStreamableHttp, "list_tools", AsyncMock(return_value=[tool])):
            first = await server.list_tools()
            second = await server.list_tools()
        self.assertEqual(first[0].name, "Fal___search_models")
        self.assertEqual(second[0].name, first[0].name)
        self.assertEqual(tool.name, "search_models")

    async def test_nested_canvas_handles_are_resolved_before_remote_call(self) -> None:
        studio = StudioAgentContext(
            source_publisher=lambda version: f"https://media.test/{version}"
        )
        server = FalMCPServer(
            {"url": FAL_MCP_URL}, argument_transformer=studio.prepare_gateway_arguments
        )
        arguments = {
            "endpoint_id": "test/model",
            "input": {"image_urls": ["renderhaus-asset://version-1"], "prompt": "Animate"},
        }
        with (
            patch("agent.fal_mcp.stripe_enabled", return_value=False),
            patch.object(MCPServerStreamableHttp, "call_tool", AsyncMock()) as remote,
        ):
            await server.call_tool("Fal___submit_job", arguments)
        remote.assert_awaited_once_with(
            "submit_job",
            {
                "endpoint_id": "test/model",
                "input": {"image_urls": ["https://media.test/version-1"], "prompt": "Animate"},
            },
            meta=None,
        )
        self.assertEqual(arguments["input"]["image_urls"], ["renderhaus-asset://version-1"])

    async def test_billing_cannot_be_bypassed_by_hidden_tool_dispatch(self) -> None:
        server = FalMCPServer({"url": FAL_MCP_URL})
        tools = [
            Tool(name=name, inputSchema={}) for name in ["search_models", "run_model", "submit_job"]
        ]
        with (
            patch.dict(os.environ, {"FAL_MCP_ALLOW_UNBILLED_GENERATION": "false"}),
            patch("agent.fal_mcp.stripe_enabled", return_value=True),
            patch.object(MCPServerStreamableHttp, "list_tools", AsyncMock(return_value=tools)),
            patch.object(MCPServerStreamableHttp, "call_tool", AsyncMock()) as remote,
        ):
            self.assertEqual([t.name for t in await server.list_tools()], ["Fal___search_models"])
            with self.assertRaisesRegex(ValueError, "customer billing"):
                await server.call_tool("Fal___submit_job", {"endpoint_id": "test/model"})
            remote.assert_not_awaited()
            os.environ["FAL_MCP_ALLOW_UNBILLED_GENERATION"] = "true"
            self.assertEqual(len(await server.list_tools()), 3)
            await server.call_tool("Fal___submit_job", {"endpoint_id": "test/model"})
            remote.assert_awaited_once()

    async def test_runtime_connects_and_closes_both_servers(self) -> None:
        gateway, fal = object(), object()
        manager = AsyncMock()
        manager.__aenter__.return_value = SimpleNamespace(active_servers=[gateway, fal])
        request = StudioAgentRequest(prompt="Find a fal image model")
        with (
            patch("agent.studio_agent_next.gateway_mcp_server", return_value=gateway),
            patch("agent.studio_agent_next.fal_mcp_server", return_value=fal) as factory,
            patch("agent.studio_agent_next.MCPServerManager", return_value=manager) as constructor,
            patch("agent.studio_agent_next._run_with_servers", AsyncMock()) as run,
        ):
            await run_studio_agent(request)
        self.assertEqual(constructor.call_args.args[0], [gateway, fal])
        self.assertEqual(run.call_args.args[3], [gateway, fal])
        self.assertIs(factory.call_args.kwargs["require_approval"], _gateway_requires_approval)
        manager.__aexit__.assert_awaited_once()

    async def test_missing_key_keeps_the_existing_gateway_available(self) -> None:
        gateway = object()
        manager = AsyncMock()
        manager.__aenter__.return_value = SimpleNamespace(active_servers=[gateway])
        with (
            patch("agent.studio_agent_next.gateway_mcp_server", return_value=gateway),
            patch("agent.studio_agent_next.fal_mcp_server", return_value=None),
            patch("agent.studio_agent_next.MCPServerManager", return_value=manager) as constructor,
            patch("agent.studio_agent_next._run_with_servers", AsyncMock()),
        ):
            await run_studio_agent(StudioAgentRequest(prompt="Make an outline"))
        self.assertEqual(constructor.call_args.args[0], [gateway])


class FalMediaTests(unittest.TestCase):
    def test_completed_media_is_registered_and_can_be_reused(self) -> None:
        from server.studio import collect_asset_sources

        registrar = Mock(return_value=[{"kind": "image", "version_id": "image-1"}])
        studio = StudioAgentContext(asset_registrar=registrar)
        _append_harvested_event(
            studio,
            call_id="fal-job",
            name="Fal___get_job_result",
            arguments={},
            output={
                "request_id": "request-1",
                "data": {
                    "images": [
                        {"url": "https://media.test/no-extension", "content_type": "image/png"}
                    ]
                },
            },
        )
        result = studio.tool_events[0].result
        self.assertEqual(
            collect_asset_sources(result),
            [{"kind": "image", "source": "https://media.test/no-extension"}],
        )
        self.assertEqual(studio.source_versions["https://media.test/no-extension"], "image-1")
        self.assertEqual(studio.tool_events[0].provider, "fal")
        self.assertEqual(studio.tool_events[0].provider_job_id, "request-1")

    def test_discovery_previews_are_not_ingested_as_generated_assets(self) -> None:
        from server.studio import _hydrate_tool_event_assets

        registrar = Mock()
        studio = StudioAgentContext(asset_registrar=registrar)
        _append_harvested_event(
            studio,
            call_id="search-1",
            name="Fal___search_models",
            arguments={},
            output={"models": [{"image_url": "https://media.test/preview.png"}]},
        )
        registrar.assert_not_called()
        with patch("server.studio._register_payload_assets") as register:
            _hydrate_tool_event_assets(
                studio.tool_events, workspace_id="w", project_id="p", user_id="u", execution_id="e"
            )
        register.assert_not_called()

    def test_failed_and_processing_jobs_do_not_register_media(self) -> None:
        for output in [
            {"status": "processing", "request_id": "request-1"},
            CallToolResult(isError=True, content=[TextContent(type="text", text="Failed")]),
        ]:
            registrar = Mock()
            studio = StudioAgentContext(asset_registrar=registrar)
            _append_harvested_event(
                studio, call_id="fal-job", name="Fal___run_model", arguments={}, output=output
            )
            registrar.assert_not_called()
        self.assertEqual(studio.tool_events[0].status, "failed")
