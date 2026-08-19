"""AgentCore Gateway Lambda entrypoint for a single provider.

Set RENDERHAUS_PROVIDER to a catalog id (seedance, seedream, mureka, fish_audio).

Event = flat tool arguments. Tool name comes from
context.client_context.custom['bedrockAgentCoreToolName'] as TargetName___tool_name.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import Any


_HERE = Path(__file__).resolve().parent
_ROOT = _HERE if (_HERE / "providers").is_dir() else _HERE.parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from providers.registry import dispatch  # noqa: E402


TOOL_DELIMITER = "___"


def _tool_name_from_context(context: Any) -> str:
    custom = {}
    client_context = getattr(context, "client_context", None)
    if client_context is not None:
        custom = getattr(client_context, "custom", None) or {}
    if not isinstance(custom, dict):
        custom = {}
    raw = str(custom.get("bedrockAgentCoreToolName") or "")
    if TOOL_DELIMITER in raw:
        return raw.split(TOOL_DELIMITER, 1)[1]
    return raw


def handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    event = dict(event or {})
    provider_id = os.getenv("RENDERHAUS_PROVIDER", "").strip()
    try:
        if not provider_id:
            raise ValueError("RENDERHAUS_PROVIDER is required on the Lambda.")
        tool_name = _tool_name_from_context(context)
        if not tool_name:
            tool_name = str(event.pop("_tool_name", "") or "")
        if not tool_name:
            raise ValueError("Missing bedrockAgentCoreToolName in Lambda context.")
        args = {key: value for key, value in event.items() if not str(key).startswith("_")}
        result = dispatch(provider_id, tool_name, args)
        if not isinstance(result, dict):
            return {"result": result}
        return result
    except Exception as exc:  # noqa: BLE001 - surface as MCP tool error payload
        return {
            "error": str(exc),
            "error_type": type(exc).__name__,
            "traceback": traceback.format_exc()[-2000:],
            "provider": provider_id,
        }


lambda_handler = handler
