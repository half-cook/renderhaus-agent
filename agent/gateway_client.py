"""Small MCP transport independent of the model orchestration framework."""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client


class GatewayClient:
    def __init__(
        self,
        params: dict[str, Any],
        *,
        name: str,
        cache_tools_list: bool = True,
        client_session_timeout_seconds: float = 180,
    ) -> None:
        self.params = params
        self.name = name
        self.cache_tools_list = cache_tools_list
        self.timeout = client_session_timeout_seconds
        self._tools_list: list[Any] | None = None
        self._session: ClientSession | None = None
        self._stack: AsyncExitStack | None = None

    async def __aenter__(self):
        stack = AsyncExitStack()
        try:
            client = await stack.enter_async_context(
                create_mcp_http_client(headers=self.params.get("headers"))
            )
            read, write = await stack.enter_async_context(
                streamable_http_client(self.params["url"], http_client=client)
            )
            self._session = await stack.enter_async_context(
                ClientSession(read, write, read_timeout_seconds=self.timeout)
            )
            await self._session.initialize()
        except BaseException:
            await stack.aclose()
            raise
        self._stack = stack
        return self

    async def __aexit__(self, *_args):
        self._session = None
        stack, self._stack = self._stack, None
        if stack:
            # MCP task groups wrap injected body exceptions in ExceptionGroup.
            # Close our resources normally so Studio's approval pause reaches
            # its caller intact; genuine cleanup errors still propagate.
            await stack.aclose()
        return False

    async def list_tools(self, *_args) -> list[Any]:
        if self._tools_list is not None and self.cache_tools_list:
            return list(self._tools_list)
        if self._session is None:
            raise RuntimeError("Gateway is not connected.")
        tools = []
        cursor = None
        while True:
            result = await self._session.list_tools(
                params=types.PaginatedRequestParams(cursor=cursor)
            )
            tools.extend(result.tools)
            cursor = result.next_cursor
            if not cursor:
                break
        self._tools_list = tools
        return list(tools)

    async def call_tool(self, tool_name, arguments, meta=None):
        if self._session is None:
            raise RuntimeError("Gateway is not connected.")
        return await self._session.call_tool(tool_name, arguments, meta=meta)
