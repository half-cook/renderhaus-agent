"""AgentCore Gateway Lambda target for all Mureka music tools.

Event = flat tool arguments. Tool name comes from
context.client_context.custom['bedrockAgentCoreToolName'] as TargetName___tool_name.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any


# Allow importing mcps.mureka.api whether packaged as a Lambda zip or run from repo.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mcps.mureka.api import dispatch_tool  # noqa: E402


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
    # Local/test fallback: event may include _tool_name.
    return raw


def handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    event = event or {}
    try:
        tool_name = _tool_name_from_context(context)
        if not tool_name:
            tool_name = str(event.pop("_tool_name", "") or "")
        if not tool_name:
            raise ValueError("Missing bedrockAgentCoreToolName in Lambda context.")
        # Strip gateway-injected bookkeeping keys if any.
        args = {k: v for k, v in event.items() if not str(k).startswith("_")}
        result = dispatch_tool(tool_name, args)
        if not isinstance(result, dict):
            return {"result": result}
        return result
    except Exception as exc:  # noqa: BLE001 - surface as MCP tool error payload
        return {
            "error": str(exc),
            "error_type": type(exc).__name__,
            "traceback": traceback.format_exc()[-2000:],
            "dry_run": os.getenv("MUREKA_DRY_RUN", "true"),
        }


# AWS Lambda entrypoint alias
lambda_handler = handler
