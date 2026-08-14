"""Local stdio MCP adapter over the Gemini TTS provider API."""

from __future__ import annotations

from fastmcp import FastMCP

from mcps.bind import bind_tools
from providers.gemini_tts.api import TOOL_HANDLERS


mcp = FastMCP("renderhaus-gemini-tts")
bind_tools(mcp, TOOL_HANDLERS)

if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
