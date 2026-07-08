from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.config import ROOT, load_local_env
from agent.main import load_tools


JOBS_DIR = ROOT / ".renderhaus" / "jobs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run generation MCP tools without the test UI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("models", help="List visible Seedance/video models.")

    video = subparsers.add_parser("video", help="Generate a Seedance text-to-video asset.")
    video.add_argument("prompt")
    video.add_argument("--duration", type=int, default=4)
    video.add_argument("--aspect-ratio", default="16:9")
    video.add_argument("--resolution", default="720p")
    video.add_argument("--model", default=None)
    video.add_argument("--audio", action="store_true")
    video.add_argument("--watermark", action="store_true")
    video.add_argument("--no-wait", action="store_true")
    video.add_argument("--timeout-seconds", type=int, default=600)
    video.add_argument("--poll-interval-seconds", type=int, default=5)

    tool = subparsers.add_parser("tool", help="Invoke an MCP tool by name.")
    tool.add_argument("name")
    tool.add_argument("--args-json", default="{}")

    return parser.parse_args()


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    return str(value)


def normalize_tool_output(output: Any) -> Any:
    normalized = jsonable(output)
    if (
        isinstance(normalized, list)
        and len(normalized) == 1
        and isinstance(normalized[0], dict)
        and isinstance(normalized[0].get("text"), str)
    ):
        text = normalized[0]["text"]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}
    return normalized


def write_job_record(tool_name: str, args: dict[str, Any], output: Any) -> Path:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = JOBS_DIR / f"{timestamp}-{tool_name}.json"
    record = {
        "tool": tool_name,
        "args": args,
        "output": output,
        "created_at": timestamp,
    }
    path.write_text(json.dumps(record, indent=2, sort_keys=True))
    return path


async def get_tool(name: str):
    tools = await load_tools(ROOT / "configs" / "mcp.local.json")
    for tool in tools:
        if tool.name == name:
            return tool
    available = ", ".join(sorted(tool.name for tool in tools))
    raise SystemExit(f"Unknown tool {name!r}. Available tools: {available}")


async def invoke_tool(tool_name: str, args: dict[str, Any]) -> Any:
    tool = await get_tool(tool_name)
    output = await tool.ainvoke(args)
    return normalize_tool_output(output)


async def run_models() -> None:
    output = await invoke_tool("list_seedance_models", {})
    path = write_job_record("list_seedance_models", {}, output)
    print(json.dumps({"record_path": str(path), "output": output}, indent=2, sort_keys=True))


async def run_video(args: argparse.Namespace) -> None:
    tool_name = "text_to_video" if args.no_wait else "text_to_video_and_wait"
    tool_args: dict[str, Any] = {
        "prompt": args.prompt,
        "duration_seconds": args.duration,
        "aspect_ratio": args.aspect_ratio,
        "resolution": args.resolution,
        "generate_audio": args.audio,
        "watermark": args.watermark,
    }
    if args.model:
        tool_args["model"] = args.model
    if not args.no_wait:
        tool_args["timeout_seconds"] = args.timeout_seconds
        tool_args["poll_interval_seconds"] = args.poll_interval_seconds

    output = await invoke_tool(tool_name, tool_args)
    path = write_job_record(tool_name, tool_args, output)
    print(json.dumps({"record_path": str(path), "output": output}, indent=2, sort_keys=True))


async def run_named_tool(args: argparse.Namespace) -> None:
    tool_args = json.loads(args.args_json)
    output = await invoke_tool(args.name, tool_args)
    path = write_job_record(args.name, tool_args, output)
    print(json.dumps({"record_path": str(path), "output": output}, indent=2, sort_keys=True))


async def main() -> None:
    load_local_env()
    args = parse_args()
    if args.command == "models":
        await run_models()
    elif args.command == "video":
        await run_video(args)
    elif args.command == "tool":
        await run_named_tool(args)


if __name__ == "__main__":
    asyncio.run(main())
