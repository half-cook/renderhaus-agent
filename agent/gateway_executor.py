from __future__ import annotations

import asyncio
import json
import os
import time
from types import SimpleNamespace

from jsonschema import validate, ValidationError as SchemaValidationError
from mcp import Tool

from agent.codex_harness import ToolApprovalPending
from agent.studio_agent_next import (
    _GATEWAY_SEARCH_TOOL,
    _append_harvested_event,
    _compact_tool_arguments,
    _progress,
    _record_stream_event,
    _unwrap_tool_output,
)


# Free, non-generative tools that only package existing project media. They
# create no paid provider work, so they never pause for customer approval.
APPROVAL_EXEMPT_TOOLS = frozenset({"Remotion___export_nle_timeline"})


def tool_needs_approval(name: str, autonomous: bool) -> bool:
    from providers.elevenlabs.catalog import requires_approval

    if name in APPROVAL_EXEMPT_TOOLS:
        return False
    return not autonomous or requires_approval(name)


class GatewayExecutor:
    def __init__(self, studio, servers, session=None):
        self.studio = studio
        self.servers = servers
        self.render_jobs = dict((session or {}).get("render_jobs") or {})
        for event in studio.tool_events:
            if event.name.endswith("render_timeline") and event.result.get("render_id"):
                self.render_jobs.setdefault(event.result["render_id"], dict(event.result))
            if event.name.endswith("get_render_progress") and event.status == "succeeded":
                render_id = event.result.get("render_id") or event.arguments.get("render_id")
                if render_id in self.render_jobs:
                    self.render_jobs[render_id].update(event.result)
        if session:
            studio.source_versions.update(session.get("source_versions") or {})
            studio.add_assets(list((session.get("working_assets") or {}).values()))

    async def connect_tools(self, session=None):
        for server in self.servers:
            await server.list_tools()
            if session and hasattr(server, "_discovered_tool_names"):
                cached = {tool.name: tool for tool in (server._tools_list or [])}
                for item in session.get("gateway_tools", []):
                    tool = Tool.model_validate(item)
                    cached.setdefault(tool.name, tool)
                    server._discovered_tool_names.add(tool.name)
                server._tools_list = list(cached.values())

    async def available(self):
        return {
            tool.name: (server, tool)
            for server in self.servers for tool in await server.list_tools()
        }

    def snapshot(self):
        return {
            "source_versions": self.studio.source_versions,
            "working_assets": self.studio.working_assets,
            "render_jobs": self.render_jobs,
            "gateway_tools": [
                tool.model_dump(by_alias=True, exclude_none=True)
                for server in self.servers
                for tool in (getattr(server, "_tools_list", None) or [])
                if tool.name != _GATEWAY_SEARCH_TOOL
            ],
        }

    async def execute(self, call, *, approved=False, rejection=None):
        studio, render_jobs = self.studio, self.render_jobs
        name, arguments, call_id = call["tool_name"], call["arguments"], call["call_id"]
        if name.endswith("___render_timeline"):
            unfinished = [job for job in render_jobs.values()
                          if job.get("status") in {"queued", "running", "preparing"}]
            if unfinished:
                return {"status": "not_run", "reason": "Check the existing render before starting any replacement. A polling error does not mean rendering failed.",
                        "next_tool": "Remotion___get_render_progress",
                        "arguments": {key: unfinished[-1][key] for key in ("render_id", "bucket_name", "output_key") if key in unfinished[-1]}}
            reused = next((event for event in studio.tool_events
                           if event.name == name and event.arguments == arguments
                           and event.result.get("render_id") and event.status not in {"failed", "error"}), None)
            if reused:
                return {**reused.result, "note": "This exact edit already has a render. Check its progress; no duplicate was started."}
        if name.endswith("___get_render_progress"):
            render = render_jobs.get(arguments.get("render_id"))
            if render:
                # These opaque provider identifiers must not be retyped by the
                # model. A one-character bucket change made valid renders look failed.
                arguments = {**arguments, "bucket_name": render["bucket_name"],
                             "output_key": render.get("output_key", "")}
                call = {**call, "arguments": arguments}
            completed_poll = next((event for event in studio.tool_events
                                   if event.name == name and event.status == "succeeded"
                                   and event.arguments.get("render_id") == arguments.get("render_id")), None)
            if completed_poll:
                return {**completed_poll.result, "note": "Already completed and saved in this execution. Deliver this MP4; no additional status check is needed."}
        previous = next(
            (
                event
                for event in studio.tool_events
                if event.id == call_id and event.status not in {"running", "awaiting_approval"}
            ),
            None,
        )
        if previous:
            return previous.result
        registry = await self.available()
        if name not in registry:
            return {"status": "failed", "error": "Search for this Gateway tool before invoking it."}
        server, tool = registry[name]
        try:
            validate(arguments, tool.input_schema)
        except SchemaValidationError as exc:
            return {
                "status": "failed",
                "error": "Arguments do not match the discovered tool schema.",
                "path": list(exc.absolute_path),
            }
        if tool_needs_approval(name, studio.autonomous) and not approved and rejection is None:
            raise ToolApprovalPending(call)
        if rejection is not None:
            output = {"status": "rejected", "message": rejection}
        else:
            _record_stream_event(
                SimpleNamespace(
                    type="run_item_stream_event",
                    name="tool_called",
                    item=SimpleNamespace(
                        call_id=call_id, tool_name=name, arguments=json.dumps(arguments)
                    ),
                ),
                studio,
                {},
                {},
            )
            try:
                output = await server.call_tool(name, arguments)
                if name.rsplit("___", 1)[-1] in {
                    "query_music_task", "get_music_task", "get_video_task", "get_runway_task",
                    "get_render_progress",
                }:
                    started = time.monotonic()
                    deadline = started + float(os.getenv("STUDIO_MEDIA_WAIT_SECONDS", "600"))
                    while _unwrap_tool_output(output).get("status") in {
                        "preparing", "queued", "running", "streaming", "pending", "processing"
                    }:
                        payload = _unwrap_tool_output(output)
                        elapsed = int(time.monotonic() - started)
                        percent = payload.get("progress")
                        detail = f" · {float(percent):.0%}" if isinstance(percent, (float, int)) else ""
                        _progress(
                            studio, event_id=f"wait-{call_id}", event_type="MEDIA_WAIT",
                            title="Rendering video" if "render_progress" in name else "Waiting for media",
                            message=f"{completed_label(name)}{detail} · {elapsed}s elapsed. Checking automatically.",
                            status="running", tool_call_id=call_id, tool_call_name=name,
                        )
                        if time.monotonic() >= deadline:
                            output = {**payload, "wait_timed_out": True,
                                      "note": "The existing job is still running. Its id is saved; resume to check it without generating again."}
                            break
                        await asyncio.sleep(min(8, max(0, deadline - time.monotonic())))
                        output = await server.call_tool(name, arguments)
                    _progress(
                        studio, event_id=f"wait-{call_id}", event_type="MEDIA_WAIT",
                        title="Media status", message="Status check finished.",
                        status="completed", tool_call_id=call_id, tool_call_name=name,
                    )
            except Exception as exc:
                payload = getattr(exc, "payload", {})
                output = {**payload, "status": "failed", "error": str(exc)[:400],
                          "transport_error": not bool(payload.get("render_id") and payload.get("status") == "failed")}
        saving_media = bool(studio.asset_registrar and _unwrap_tool_output(output).get("status") == "succeeded")
        if saving_media:
            _progress(studio, event_id=f"save-{call_id}", event_type="MEDIA_WAIT", title="Saving media",
                      message="Saving completed media to your project…", status="running")
        await asyncio.to_thread(
            _append_harvested_event,
            studio,
            call_id=call_id,
            name=name,
            arguments=_compact_tool_arguments(arguments),
            output=output,
        )
        if saving_media:
            _progress(studio, event_id=f"save-{call_id}", event_type="MEDIA_WAIT", title="Media saved",
                      message="Completed media saved to your project.", status="completed")
        completed = next(event for event in studio.tool_events if event.id == call_id)
        if name.endswith("render_timeline") and completed.result.get("render_id"):
            render_jobs[completed.result["render_id"]] = completed.result
        if name.endswith("get_render_progress") and arguments.get("render_id") in render_jobs:
            result = completed.result
            if result.get("status") == "succeeded" or (result.get("status") == "failed" and not result.get("transport_error")):
                render_jobs[arguments["render_id"]].update(result)
        _progress(
            studio,
            event_id=f"tool-{call_id}",
            event_type="TOOL_CALL_RESULT",
            title=completed.label,
            message=completed.summary,
            status=completed.status,
            tool_call_id=call_id,
            tool_call_name=name,
        )
        if name == _GATEWAY_SEARCH_TOOL:
            return {
                "result": _unwrap_tool_output(output),
                "tools": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": tool.input_schema,
                    }
                    for _, tool in (await self.available()).values()
                    if tool.name != _GATEWAY_SEARCH_TOOL
                ],
            }
        return completed.result


def completed_label(name: str) -> str:
    if name.endswith("get_render_progress"):
        return "Remotion is assembling the MP4"
    if name.endswith(("query_music_task", "get_music_task")):
        return "The audio provider is preparing the soundtrack"
    return "The video provider is processing the clip"
