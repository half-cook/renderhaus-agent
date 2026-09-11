"""Connect Renderhaus to fal's hosted Run MCP server."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from typing import Any

from agents.mcp import MCPServerStreamableHttp

from server.billing import stripe_enabled
from server.config import load_local_env


FAL_MCP_URL = "https://mcp.fal.ai/mcp"
FAL_TOOL_PREFIX = "Fal___"
FAL_GENERATION_TOOLS = frozenset({"run_model", "submit_job"})
FAL_RESULT_TOOLS = frozenset({"run_model", "get_job_result"})


def mcp_result_is_error(result: Any) -> bool:
    """Support both MCP SDK v1 camelCase and v2 snake_case result fields."""
    if isinstance(result, dict):
        return bool(result.get("isError") or result.get("is_error"))
    return bool(getattr(result, "is_error", False) or getattr(result, "isError", False))


def _unbilled_generation_allowed() -> bool:
    return not stripe_enabled() or os.getenv(
        "FAL_MCP_ALLOW_UNBILLED_GENERATION", ""
    ).strip().lower() in {"1", "true", "yes"}


class FalMCPServer(MCPServerStreamableHttp):
    """Namespace fal tools and resolve canvas media at the provider boundary."""

    def __init__(self, *args: Any, argument_transformer: Callable | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._argument_transformer = argument_transformer

    async def list_tools(self, run_context: Any = None, agent: Any = None) -> list[Any]:
        tools = await super().list_tools(run_context, agent)
        return [
            tool.model_copy(update={"name": FAL_TOOL_PREFIX + tool.name})
            for tool in tools
            if tool.name not in FAL_GENERATION_TOOLS or _unbilled_generation_allowed()
        ]

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
        meta: dict[str, Any] | None = None,
    ) -> Any:
        if not tool_name.startswith(FAL_TOOL_PREFIX):
            raise ValueError("Expected a Fal___ tool name.")
        raw_name = tool_name.removeprefix(FAL_TOOL_PREFIX)
        if raw_name in FAL_GENERATION_TOOLS and not _unbilled_generation_allowed():
            raise ValueError(
                "fal generation is not integrated with Renderhaus customer billing. "
                "Set FAL_MCP_ALLOW_UNBILLED_GENERATION=true only for operator-funded runs."
            )
        resolved = dict(arguments or {})
        if self._argument_transformer:
            resolved = await asyncio.to_thread(self._argument_transformer, tool_name, resolved)
        # Do not automatically retry paid submissions: a lost response can still mean a job ran.
        return await super().call_tool(raw_name, resolved, meta=meta)


def fal_mcp_server(
    *,
    argument_transformer: Callable | None = None,
    require_approval: Any = "always",
) -> FalMCPServer | None:
    """Enable automatically when FAL_KEY exists, or explicitly via FAL_MCP_ENABLED."""
    load_local_env()
    enabled = os.getenv("FAL_MCP_ENABLED", "").strip().lower()
    if enabled in {"0", "false", "no"}:
        return None
    if enabled not in {"", "1", "true", "yes"}:
        raise ValueError("FAL_MCP_ENABLED must be true or false.")
    key = os.getenv("FAL_KEY", "").strip()
    if not key:
        if enabled:
            raise ValueError("FAL_KEY is required when FAL_MCP_ENABLED=true.")
        return None
    return FalMCPServer(
        {"url": FAL_MCP_URL, "headers": {"Authorization": f"Bearer {key}"}, "timeout": 30},
        name="fal-ai",
        cache_tools_list=True,
        client_session_timeout_seconds=180,
        max_retry_attempts=0,
        argument_transformer=argument_transformer,
        require_approval=require_approval,
    )


def normalize_fal_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Add typed media URLs to fal file objects for canvas ingestion and reuse."""
    kinds = {
        "image": "image",
        "images": "image",
        "video": "video",
        "videos": "video",
        "audio": "audio",
        "audios": "audio",
    }

    def visit(value: Any, kind: str | None = None) -> Any:
        if isinstance(value, list):
            return [visit(item, kind) for item in value]
        if not isinstance(value, dict):
            return value
        mime_kind = str(value.get("content_type", "")).split("/", 1)[0]
        kind = mime_kind if mime_kind in {"image", "video", "audio"} else kind
        result = {key: visit(item, kinds.get(key)) for key, item in value.items()}
        url = value.get("url")
        if kind and isinstance(url, str) and url.startswith("https://"):
            result[f"{kind}_url"] = url
        return result

    return visit(payload)
