from __future__ import annotations

import os
import unittest
from typing import Literal
from unittest.mock import patch

from agents.mcp import MCPServerStreamableHttp

from agent.studio_agent_next import gateway_mcp_server
from providers.registry import _json_schema_for_hint, sanitize_gateway_json_schema
from server.config import GATEWAY_MCP_SERVER_NAME, require_agentcore_gateway_url


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


if __name__ == "__main__":
    unittest.main()
