#!/usr/bin/env python3
"""Verify Renderhaus's fal MCP connection without generating paid media."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.fal_mcp import fal_mcp_server, mcp_result_is_error  # noqa: E402


async def smoke() -> int:
    server = fal_mcp_server()
    if server is None:
        print("fal MCP is not enabled. Add FAL_KEY to .env.local or the Renderhaus AWS secret.")
        return 1
    async with server:
        tools = await server.list_tools()
        names = sorted(tool.name for tool in tools)
        if "Fal___search_models" not in names:
            print("fal MCP connected but did not expose search_models.")
            return 1
        result = await server.call_tool("Fal___search_models", {"query": "flux", "limit": 1})
        if mcp_result_is_error(result):
            print(
                "fal MCP connected but the model search failed. Check FAL_KEY and account access."
            )
            return 1
        print(f"fal MCP connected: {len(names)} tools; live model search succeeded.")
        print("\n".join(names))
    return 0


def main() -> int:
    try:
        return asyncio.run(smoke())
    except Exception as exc:
        # Do not echo transport payloads or request headers containing the API key.
        print(f"fal MCP check failed ({type(exc).__name__}). Check credentials and connectivity.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
