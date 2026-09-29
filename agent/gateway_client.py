"""Small MCP transport independent of the model orchestration framework."""

from __future__ import annotations

from contextlib import AsyncExitStack
import re
from typing import Any
from urllib.parse import urlsplit

import httpx2
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import MCP_DEFAULT_SSE_READ_TIMEOUT, MCP_DEFAULT_TIMEOUT, create_mcp_http_client


class GatewayIAMAuth(httpx2.Auth):
    """Sign each request with refreshable AWS credentials, as in smoke_gateway.py."""
    requires_request_body = True

    def __init__(self, region: str):
        self.region = region
        self.session = boto3.Session(region_name=region)

    def auth_flow(self, request):
        credentials = self.session.get_credentials()
        if credentials is None:
            raise RuntimeError("AWS credentials are required to invoke the AgentCore Gateway.")
        signed = AWSRequest(method=request.method, url=str(request.url),
                            data=request.content, headers=dict(request.headers))
        SigV4Auth(credentials.get_frozen_credentials(), "bedrock-agentcore", self.region).add_auth(signed)
        request.headers.update(dict(signed.headers))
        yield request


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
        url = self.params["url"]
        headers = dict(self.params.get("headers") or {})
        if not isinstance(url, str) or any(ord(char) <= 32 or ord(char) == 127 or char == "\\" for char in url):
            raise ValueError("Gateway URL must be an absolute HTTPS URL.")
        parsed = urlsplit(url)
        if not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.fragment:
            raise ValueError("Gateway URL must have a host and no embedded credentials or fragment.")
        # Accessing port rejects malformed/out-of-range ports before creating a client.
        _ = parsed.port
        if parsed.scheme != "https":
            if not (
                parsed.scheme == "http"
                and self.params.get("allow_loopback_http") is True
                and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                and not headers and not parsed.query
            ):
                raise ValueError("Gateway requires HTTPS; HTTP is only allowed for explicit credential-free loopback development.")
        stack = AsyncExitStack()
        try:
            client = (
                httpx2.AsyncClient(trust_env=False, timeout=httpx2.Timeout(MCP_DEFAULT_TIMEOUT, read=MCP_DEFAULT_SSE_READ_TIMEOUT))
                if parsed.scheme == "http" else create_mcp_http_client(headers=headers)
            )
            # MCP defaults to following redirects, which could downgrade or escape loopback.
            client.follow_redirects = False
            aws_host = re.fullmatch(r"[a-z0-9-]+\.gateway\.bedrock-agentcore\.([a-z0-9-]+)\.amazonaws\.com", parsed.hostname)
            if aws_host and not any(key.lower() == "authorization" for key in headers):
                client.auth = GatewayIAMAuth(aws_host.group(1))
            await stack.enter_async_context(client)
            read, write = await stack.enter_async_context(
                streamable_http_client(url, http_client=client)
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
