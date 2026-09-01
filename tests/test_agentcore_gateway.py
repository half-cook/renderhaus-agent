from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from typing import Literal
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.mcp import MCPServerStreamableHttp

from agent.studio_agent_next import gateway_mcp_server
from providers.catalog import get_provider
from providers.registry import (
    _json_schema_for_hint,
    dispatch,
    generate_schemas,
    sanitize_gateway_json_schema,
)
from server.config import GATEWAY_MCP_SERVER_NAME, require_agentcore_gateway_url
from scripts.deploy_gateway import GATEWAY_INSTRUCTIONS, _upsert_gateway


class AgentCoreGatewayConfigTests(unittest.TestCase):
    def test_require_gateway_url_fails_when_unset(self) -> None:
        with patch.dict(os.environ, {"AGENTCORE_GATEWAY_URL": ""}, clear=False):
            os.environ.pop("AGENTCORE_GATEWAY_URL", None)
            with self.assertRaises(ValueError):
                require_agentcore_gateway_url()

    def test_gateway_mcp_server_is_the_only_client(self) -> None:
        with (
            patch("agent.studio_agent_next.load_local_env"),
            patch.dict(
                os.environ,
                {
                    "AGENTCORE_GATEWAY_URL": "https://gateway.example/mcp",
                    "AGENTCORE_GATEWAY_AUTH_TOKEN": "token-1",
                },
            ),
        ):
            server = gateway_mcp_server()
        self.assertIsInstance(server, MCPServerStreamableHttp)
        self.assertEqual(server.name, GATEWAY_MCP_SERVER_NAME)

    def test_existing_gateway_receives_updated_instructions_without_resetting_search(self) -> None:
        control = MagicMock()
        with (
            patch(
                "scripts.deploy_gateway._find_gateway",
                return_value={"gatewayId": "gateway-1", "name": "renderhaus-mureka-gateway"},
            ),
            patch(
                "scripts.deploy_gateway._wait_gateway_ready",
                return_value={"gatewayId": "gateway-1", "gatewayUrl": "https://gateway.example/mcp"},
            ),
        ):
            gateway_id, url = _upsert_gateway(control, role_arn="arn:aws:iam::123:role/gateway")

        self.assertEqual(gateway_id, "gateway-1")
        self.assertEqual(url, "https://gateway.example/mcp")
        kwargs = control.update_gateway.call_args.kwargs
        self.assertEqual(
            kwargs["protocolConfiguration"],
            {"mcp": {"instructions": GATEWAY_INSTRUCTIONS}},
        )
        self.assertNotIn("protocolType", kwargs)
        self.assertNotIn("searchType", kwargs["protocolConfiguration"]["mcp"])


class GatewayToolSchemaTests(unittest.TestCase):
    def test_literal_uses_description_not_enum(self) -> None:
        schema = _json_schema_for_hint(Literal["default", "flex"])
        self.assertEqual(schema["type"], "string")
        self.assertNotIn("enum", schema)
        self.assertIn("default", schema["description"])
        self.assertIn("flex", schema["description"])

    def test_sanitize_keeps_property_names(self) -> None:
        tool = {
            "name": "text_to_video",
            "description": "Create a video task.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "service_tier": {"enum": ["default", "flex"], "type": "string"},
                },
                "required": ["prompt"],
            },
        }
        cleaned = sanitize_gateway_json_schema(tool)
        properties = cleaned["inputSchema"]["properties"]
        self.assertEqual(properties["prompt"], {"type": "string"})
        self.assertEqual(properties["service_tier"]["type"], "string")
        self.assertNotIn("enum", properties["service_tier"])
        self.assertIn("default", properties["service_tier"]["description"])
        self.assertEqual(cleaned["inputSchema"]["required"], ["prompt"])

    def test_contracts_are_visible_in_gateway_schemas(self) -> None:
        seedance = {tool["name"]: tool for tool in generate_schemas(get_provider("seedance"))}
        resolution = seedance["image_to_video"]["inputSchema"]["properties"]["resolution"]
        self.assertIn("480p, 720p, 1080p", resolution["description"])

        remotion = {tool["name"]: tool for tool in generate_schemas(get_provider("remotion"))}
        visual = remotion["render_timeline"]["inputSchema"]["properties"]["visuals"]["items"]
        self.assertEqual(visual["required"], ["kind", "url", "duration_seconds"])
        self.assertIn("kind", visual["properties"])

    def test_dispatch_rejects_unsupported_seedance_arguments_before_provider_call(self) -> None:
        with patch.dict(os.environ, {"SEEDANCE_DRY_RUN": "true"}):
            with self.assertRaisesRegex(ValueError, "480p, 720p, 1080p"):
                dispatch("seedance", "text_to_video", {"prompt": "Launch", "resolution": "2K"})
            with self.assertRaisesRegex(ValueError, "adaptive, 16:9"):
                dispatch(
                    "seedance",
                    "image_to_video",
                    {
                        "image_path_or_url": "https://example.test/frame.png",
                        "prompt": "Move slowly",
                        "aspect_ratio": "2.39:1",
                    },
                )
            accepted = dispatch(
                "seedance",
                "text_to_video",
                {"prompt": "Launch", "resolution": "720p", "aspect_ratio": "adaptive"},
            )
        self.assertEqual(accepted["status"], "dry_run")

    def test_dispatch_enforces_cross_field_contracts(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires one of"):
            dispatch(
                "mureka",
                "region_edit_song",
                {"lyrics": "Verse", "edit_start_ms": 1, "edit_end_ms": 2},
            )
        with self.assertRaisesRegex(ValueError, "greater than"):
            dispatch(
                "mureka",
                "region_edit_song",
                {
                    "lyrics": "Verse",
                    "edit_start_ms": 20,
                    "edit_end_ms": 10,
                    "song_id": "song-1",
                },
            )


if __name__ == "__main__":
    unittest.main()
