"""Local stdio MCP adapter over the Mureka provider API."""

from __future__ import annotations

from fastmcp import FastMCP

from mcps.bind import bind_tools
from providers.mureka.api import TOOL_HANDLERS


mcp = FastMCP("renderhaus-mureka")
bind_tools(mcp, TOOL_HANDLERS)

if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
