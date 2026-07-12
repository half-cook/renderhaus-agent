from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

from agent.config import DEFAULT_MCP_CONFIG, load_local_env, load_mcp_servers, mask_secret_status


SYSTEM_PROMPT = """You are the Renderhaus generation coordinator.
Use MCP tools for image, video, audio, and music work. Prefer dry-run planning for expensive
generation unless the user explicitly asks to generate real media. Summarize tool outputs with
asset paths, job IDs, provider names, and estimated costs when available.
"""

GEN_SECRET_KEYS = [
    "OPENAI_API_KEY",
    "MUREKA_API_KEY",
    "ELEVENLABS_API_KEY",
    "BYTEPLUS_API_KEY",
    "GOOGLE_API_KEY",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the basic Renderhaus LangChain MCP agent.")
    parser.add_argument("prompt", nargs="*", help="Prompt to send to the agent.")
    parser.add_argument("--config", default=str(DEFAULT_MCP_CONFIG), help="MCP config JSON path.")
    parser.add_argument("--list-tools", action="store_true", help="Load MCP tools and print them.")
    parser.add_argument("--check-env", action="store_true", help="Print required secret status.")
    return parser.parse_args()


def print_env_status() -> None:
    for key in GEN_SECRET_KEYS:
        print(f"{key}={mask_secret_status(key)}")


def print_tool(tool: Any) -> None:
    description = getattr(tool, "description", "") or ""
    description = " ".join(description.split())
    if len(description) > 180:
        description = f"{description[:177]}..."
    print(f"- {tool.name}: {description}")


def dedupe_tool_names(tools: list[Any]) -> list[Any]:
    counts: dict[str, int] = {}
    for tool in tools:
        original_name = tool.name
        count = counts.get(original_name, 0)
        counts[original_name] = count + 1
        if count == 0:
            continue
        new_name = f"{original_name}_{count + 1}"
        tool.name = new_name
        tool.description = (
            f"{tool.description}\n\nOriginal MCP tool name was `{original_name}`; renamed to "
            f"`{new_name}` because another server exposed the same tool name."
        )
    return tools


async def load_tools(config_path: Path) -> list[Any]:
    client = MultiServerMCPClient(load_mcp_servers(config_path))
    return dedupe_tool_names(await client.get_tools())


async def run_agent(config_path: Path, prompt: str) -> None:
    from agent.service import invoke_agent

    result = await invoke_agent(prompt, config_path=config_path)
    print(result.get("message") or result)


async def main() -> None:
    args = parse_args()
    load_local_env()
    config_path = Path(args.config).expanduser().resolve()

    if args.check_env:
        print_env_status()
        return

    if args.list_tools:
        tools = await load_tools(config_path)
        print(f"Loaded {len(tools)} MCP tools")
        for tool in tools:
            print_tool(tool)
        return

    prompt = " ".join(args.prompt).strip()
    if not prompt:
        raise SystemExit("Provide a prompt, or use --list-tools / --check-env.")
    await run_agent(config_path, prompt)


if __name__ == "__main__":
    asyncio.run(main())
