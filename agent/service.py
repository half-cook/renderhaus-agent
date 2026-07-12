from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from langchain.agents import create_agent

from agent.config import DEFAULT_MCP_CONFIG
from agent.main import SYSTEM_PROMPT, load_tools


WEB_SYSTEM_PROMPT = """You are the private Renderhaus video-generation coordinator.
The user has explicitly authorized exactly one video generation for this request.
Call exactly one immediate-return generation tool: text_to_video for a text prompt, or
image_to_video when a local reference image path is supplied. Never call wait, polling, model
listing, audio, voice, music, playback, phone, or outbound communication tools. Do not reveal
provider, model, tool, credential, or internal path details in your prose. Keep the final response
to one short sentence; the application reads the generation result structurally.
"""


_runtime_lock = asyncio.Lock()
_cached_tools: dict[str, Any] | None = None
_cached_web_agent: Any | None = None


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    return str(value)


def _parse_content(value: Any) -> Any:
    if not isinstance(value, str):
        return _jsonable(value)
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def normalize_tool_output(value: Any) -> Any:
    normalized = _jsonable(value)
    if (
        isinstance(normalized, list)
        and len(normalized) == 1
        and isinstance(normalized[0], dict)
        and isinstance(normalized[0].get("text"), str)
    ):
        return _parse_content(normalized[0]["text"])
    return _parse_content(normalized)


def _content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(part for part in parts if part)
    return str(value) if value is not None else ""


def _walk_artifacts(value: Any, artifacts: list[dict[str, Any]]) -> None:
    value = _parse_content(value)
    if isinstance(value, dict):
        path = value.get("output_path")
        url = value.get("video_url")
        if isinstance(path, str) or isinstance(url, str):
            artifact: dict[str, Any] = {}
            if isinstance(path, str):
                artifact["output_path"] = path
            if isinstance(url, str):
                artifact["video_url"] = url
            status = value.get("status")
            if isinstance(status, str):
                artifact["status"] = status
            job_id = value.get("job_id")
            if isinstance(job_id, str):
                artifact["job_id"] = job_id
            artifacts.append(artifact)
        for item in value.values():
            _walk_artifacts(item, artifacts)
    elif isinstance(value, list):
        for item in value:
            _walk_artifacts(item, artifacts)


def summarize_agent_result(result: dict[str, Any]) -> dict[str, Any]:
    messages = result.get("messages", [])
    final_text = ""
    tool_events: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []

    for message in messages:
        data = _jsonable(message)
        content = data.get("content") if isinstance(data, dict) else data
        message_type = data.get("type") if isinstance(data, dict) else None
        if message_type == "tool" or (isinstance(data, dict) and data.get("tool_call_id")):
            event = {
                "name": data.get("name") or "tool",
                "content": _parse_content(content),
            }
            tool_events.append(event)
            _walk_artifacts(event["content"], artifacts)
        else:
            text = _content_text(content)
            if text:
                final_text = text

    unique_artifacts: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None]] = set()
    for artifact in artifacts:
        key = (artifact.get("output_path"), artifact.get("video_url"))
        if key in seen:
            continue
        seen.add(key)
        unique_artifacts.append(artifact)

    return {
        "message": final_text,
        "tool_events": tool_events,
        "artifacts": unique_artifacts,
    }


async def invoke_agent(
    prompt: str,
    *,
    config_path: Path = DEFAULT_MCP_CONFIG,
    system_prompt: str = SYSTEM_PROMPT,
) -> dict[str, Any]:
    tools = await load_tools(config_path)
    model = os.getenv("AGENT_MODEL", "openai:gpt-4.1-mini")
    agent = create_agent(model=model, tools=tools, system_prompt=system_prompt)
    result = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
    return summarize_agent_result(result)


async def _generation_runtime() -> tuple[Any, dict[str, Any]]:
    global _cached_tools, _cached_web_agent
    if _cached_tools is not None and _cached_web_agent is not None:
        return _cached_web_agent, _cached_tools

    async with _runtime_lock:
        if _cached_tools is not None and _cached_web_agent is not None:
            return _cached_web_agent, _cached_tools
        tools = await load_tools(DEFAULT_MCP_CONFIG)
        by_name = {tool.name: tool for tool in tools}
        required = {"text_to_video", "image_to_video", "get_video_task"}
        missing = sorted(required - by_name.keys())
        if missing:
            raise RuntimeError(
                f"Required video generation tools are unavailable: {', '.join(missing)}"
            )
        generation_tools = [by_name["text_to_video"], by_name["image_to_video"]]
        model = os.getenv("AGENT_MODEL", "openai:gpt-4.1-mini")
        _cached_web_agent = create_agent(
            model=model,
            tools=generation_tools,
            system_prompt=WEB_SYSTEM_PROMPT,
        )
        _cached_tools = {name: by_name[name] for name in required}
        return _cached_web_agent, _cached_tools


async def start_video_generation(prompt: str) -> dict[str, Any]:
    agent, _ = await _generation_runtime()
    result = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
    return summarize_agent_result(result)


async def poll_video_generation(job_id: str) -> dict[str, Any]:
    _, tools = await _generation_runtime()
    output = await tools["get_video_task"].ainvoke({"job_id": job_id, "download": True})
    normalized = normalize_tool_output(output)
    if not isinstance(normalized, dict):
        raise RuntimeError("Video generation returned an invalid status payload.")
    return normalized
