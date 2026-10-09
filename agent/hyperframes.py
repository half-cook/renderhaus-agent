"""Optional local HyperFrames composition preview, without executing authored code."""

from __future__ import annotations

import os

from jsonschema import ValidationError, validate
from mcp import Tool


HYPERFRAMES_TOOL = Tool(
    name="HyperFrames___render_composition",
    description=(
        "Preview a bounded HTML motion composition locally when HYPERFRAMES_ENABLED=true. "
        "Returns dry_run metadata only. Live rendering requires a future isolated renderer. "
        "Never executes HTML, downloads a runtime, or calls hosted HeyGen APIs."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "html": {"type": "string", "minLength": 1, "maxLength": 200000},
            "duration_seconds": {"type": "number", "minimum": 0.1, "maximum": 300},
            "width": {"type": "integer", "minimum": 16, "maximum": 3840},
            "height": {"type": "integer", "minimum": 16, "maximum": 2160},
            "fps": {"type": "integer", "minimum": 1, "maximum": 60},
        },
        "required": ["html", "duration_seconds", "width", "height", "fps"],
        "additionalProperties": False,
    },
)


def enabled() -> bool:
    return os.getenv("HYPERFRAMES_ENABLED", "false").lower() == "true"


def dry_run() -> bool:
    return os.getenv("HYPERFRAMES_DRY_RUN", "true").lower() != "false"


class HyperFramesServer:
    """Local tool registry consumed by the existing Gateway executor."""

    def __init__(self):
        self._tools_list: list[Tool] = []

    async def list_tools(self) -> list[Tool]:
        self._tools_list = [HYPERFRAMES_TOOL] if enabled() else []
        return self._tools_list

    async def call_tool(self, name: str, arguments: dict) -> dict:
        if not enabled():
            return {"status": "not_run", "reason": "HyperFrames is disabled. Enable HYPERFRAMES_ENABLED for composition previews."}
        if name != HYPERFRAMES_TOOL.name:
            return {"status": "not_run", "reason": "Unknown local HyperFrames tool."}
        try:
            validate(arguments, HYPERFRAMES_TOOL.input_schema)
        except ValidationError as exc:
            return {"status": "not_run", "reason": "Composition arguments do not match the schema.",
                    "path": list(exc.absolute_path)}
        if not dry_run():
            return {"status": "not_run", "reason": "HyperFrames isolated renderer not configured. Live HTML execution is unavailable."}
        return {
            "status": "dry_run",
            "dry_run": True,
            "composition": {key: value for key, value in arguments.items() if key != "html"},
            "summary": "HyperFrames composition preview only. No HTML was executed and no media file was rendered.",
        }
