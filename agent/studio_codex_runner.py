"""Studio policy and tool boundary around the Codex app-server harness."""

from __future__ import annotations

import hashlib
import json
import asyncio
import os
import time
from types import SimpleNamespace

from jsonschema import validate, ValidationError as SchemaValidationError
from mcp import Tool

from agent.codex_harness import CodexHarness, SESSION_TYPE, ToolApprovalPending
from agent.studio_agent_next import (
    STUDIO_MANAGER_INSTRUCTIONS,
    StudioAgentApprovalRequired,
    StudioAgentOutput,
    StudioAgentRequest,
    _GATEWAY_SEARCH_TOOL,
    _agent_model,
    _approval_request,
    _append_harvested_event,
    _compact_tool_arguments,
    _input_for,
    _progress,
    _record_approval_requests,
    _record_stream_event,
    _unwrap_tool_output,
    _validate_video_delivery,
    normalize_markdown_filename,
    report_progress,
)


def _scope(request: StudioAgentRequest) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                request.workspace_id,
                request.project_id,
                request.conversation_id,
                request.job_id,
            ]
        ).encode()
    ).hexdigest()


def _conversation_scope(request: StudioAgentRequest) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                request.workspace_id,
                request.project_id,
                request.conversation_id or request.job_id,
            ]
        ).encode()
    ).hexdigest()


def _function(name, description, schema):
    return {"type": "function", "name": name, "description": description, "inputSchema": schema}


async def run_with_servers(request, studio, harness: CodexHarness, servers):
    snapshots = [item for item in request.session_items if item.get("type") == SESSION_TYPE]
    session = snapshots[-1] if snapshots else None
    if session and session.get("scope") != _conversation_scope(request):
        raise ValueError(
            "This Codex conversation belongs to a different workspace or conversation."
        )
    legacy = [] if session else request.session_items
    render_jobs = dict((session or {}).get("render_jobs") or {})
    for event in studio.tool_events:
        if event.name.endswith("render_timeline") and event.result.get("render_id"):
            render_jobs.setdefault(event.result["render_id"], dict(event.result))
        if event.name.endswith("get_render_progress") and event.status == "succeeded":
            render_id = event.result.get("render_id") or event.arguments.get("render_id")
            if render_id in render_jobs:
                render_jobs[render_id].update(event.result)
    if session:
        studio.source_versions.update(session.get("source_versions") or {})
        studio.add_assets(list((session.get("working_assets") or {}).values()))
    pending_call = None
    if request.resume_state:
        try:
            state = json.loads(request.resume_state)
            if (
                state["harness"] != "codex"
                or state["version"] != 1
                or state["scope"] != _scope(request)
            ):
                raise ValueError
            pending_call = state["call"]
            if not session:
                raise ValueError
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(
                "This approval checkpoint cannot be resumed by Codex. Start a new request."
            ) from exc

    for server in servers:
        await server.list_tools()
        if session and hasattr(server, "_discovered_tool_names"):
            restored = session.get("gateway_tools", [])
            cached = {tool.name: tool for tool in (server._tools_list or [])}
            for item in restored:
                tool = Tool.model_validate(item)
                cached.setdefault(tool.name, tool)
                server._discovered_tool_names.add(tool.name)
            server._tools_list = list(cached.values())

    async def available():
        return {
            tool.name: (server, tool) for server in servers for tool in await server.list_tools()
        }

    initial = await available()
    def save_checkpoint(snapshot):
        snapshot["scope"] = _conversation_scope(request)
        snapshot["source_versions"] = studio.source_versions
        snapshot["working_assets"] = studio.working_assets
        snapshot["render_jobs"] = render_jobs
        snapshot["gateway_tools"] = [
            tool.model_dump(by_alias=True, exclude_none=True)
            for server in servers for tool in (getattr(server, "_tools_list", None) or [])
            if tool.name != _GATEWAY_SEARCH_TOOL
        ]
        studio.session_items = [snapshot]
        if studio.session_sink:
            studio.session_sink(studio.session_items)
    tools = [
        _function(
            "report_progress",
            "Show a concise progress update to the customer.",
            {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
                "additionalProperties": False,
            },
        ),
        _function(
            "call_gateway_tool",
            "Call a tool returned by Gateway search. Use its exact name "
            "and encode the arguments as JSON matching its returned inputSchema.",
            {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string"},
                    "arguments_json": {"type": "string"},
                },
                "required": ["tool_name", "arguments_json"],
                "additionalProperties": False,
            },
        ),
    ]
    if _GATEWAY_SEARCH_TOOL in initial:
        search = initial[_GATEWAY_SEARCH_TOOL][1]
        tools.append(
            _function(
                search.name,
                search.description or "Search available media tools.",
                search.input_schema,
            )
        )

    async def execute(call, *, approved=False, rejection=None):
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
        # Restored completed calls must never be charged or dispatched again.
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
        registry = await available()
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
        from providers.elevenlabs.catalog import requires_approval
        if (not studio.autonomous or requires_approval(name)) and not approved and rejection is None:
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
                # One approved status check follows the same job to completion.
                # Waiting belongs to the host, not a model loop that can give up
                # after several immediate polls (or require approval for each one).
                if name.rsplit("___", 1)[-1] in {
                    "query_music_task", "get_music_task", "get_video_task", "get_runway_task", "get_render_progress"
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
                # Preserve a visible failure and allow Codex to correct tool input.
                payload = getattr(exc, "payload", {})
                output = {**payload, "status": "failed", "error": str(exc)[:400],
                          "transport_error": not bool(payload.get("render_id") and payload.get("status") == "failed")}
        saving_media = bool(studio.asset_registrar and _unwrap_tool_output(output).get("status") == "succeeded")
        if saving_media:
            _progress(studio, event_id=f"save-{call_id}", event_type="MEDIA_WAIT", title="Saving media",
                      message="Saving completed media to your project…", status="running")
        # Media downloads can take seconds or minutes. Keep the event loop free
        # so the Studio can poll progress, stop, and serve existing artifacts.
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
                    for _, tool in (await available()).values()
                    if tool.name != _GATEWAY_SEARCH_TOOL
                ],
            }
        return completed.result

    async def call_tool(payload):
        tool = payload.get("tool")
        arguments = payload.get("arguments", {})
        if not isinstance(arguments, dict):
            return {"status": "failed", "error": "Expected an argument object."}
        if tool == "report_progress":
            message = arguments.get("message")
            if not isinstance(message, str):
                return {"status": "failed", "error": "message must be text."}
            return await report_progress(studio, message)
        if tool == "call_gateway_tool":
            try:
                name = arguments["tool_name"]
                arguments = json.loads(arguments["arguments_json"])
                if not isinstance(name, str) or not isinstance(arguments, dict):
                    raise ValueError
            except (KeyError, ValueError, TypeError):
                return {
                    "status": "failed",
                    "error": "Provide tool_name and a JSON argument object.",
                }
        elif tool == _GATEWAY_SEARCH_TOOL:
            name = tool
        else:
            return {"status": "failed", "error": "Unknown Studio tool."}
        return await execute(
            {"call_id": payload["callId"], "tool_name": name, "arguments": arguments}
        )

    def on_event(method, payload):
        item = payload.get("item", {})
        if item.get("type") == "contextCompaction" and method in {"item/started", "item/completed"}:
            _progress(studio, event_id=f"compact-{item['id']}", event_type="CONTEXT_COMPACTION",
                      title="Conversation memory", message="Condensing earlier context while preserving the conversation.",
                      status="completed" if method == "item/completed" else "running")
        if (
            method == "item/completed"
            and item.get("type") == "agentMessage"
            and item.get("phase") == "commentary"
        ):
            _progress(
                studio,
                event_id=f"codex-{item['id']}",
                event_type="MODEL_UPDATE",
                title="Agent update",
                message=str(item.get("text", ""))[:1000],
                status="completed",
            )

    prompt = _input_for(request.prompt, list(studio.nodes))
    if render_jobs:
        prompt += "\nAuthoritative saved render jobs (reference data):\n" + json.dumps([
            {key: job[key] for key in ("render_id", "bucket_name", "output_key", "status") if key in job}
            for job in render_jobs.values()
        ])
    prompt += ("\nCurrent execution state: no tool approval is pending in this new turn. "
               "Historical approval messages are past events. If a tool is needed, call it; "
               "the host will pause this execution and display an approval card if required. "
               "Never finish by claiming to await approval without making the tool call.")
    if _GATEWAY_SEARCH_TOOL not in initial:
        prompt += "\nAvailable Gateway tools (data):\n" + json.dumps(
            [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.input_schema,
                }
                for _, tool in initial.values()
            ]
        )
    if pending_call:
        decision = next(
            (
                item
                for item in request.approval_decisions
                if item.call_id == pending_call["call_id"]
            ),
            None,
        )
        approval = _approval_request(
            SimpleNamespace(
                name=pending_call["tool_name"],
                call_id=pending_call["call_id"],
                arguments=json.dumps(pending_call["arguments"]),
            )
        )
        if decision is None:
            raise StudioAgentApprovalRequired(
                request.resume_state, [approval], request.session_items
            )
        result = await execute(
            pending_call,
            approved=decision.decision == "approve",
            rejection=(decision.message or "The customer rejected this tool call.")
            if decision.decision == "reject"
            else None,
        )
        prompt = (
            prompt + "\n\n"
            +
            "Continue the customer's request after the Studio approval pause. "
            "The previous tool callback was stopped before execution. Studio has now "
            "applied the decision below. Use this result; do not repeat that call.\n"
            + json.dumps({"call": pending_call, "decision": decision.decision, "result": result})
        )
    try:
        try:
            raw = await harness.run(
                prompt=prompt,
                model=_agent_model(),
                instructions=STUDIO_MANAGER_INSTRUCTIONS,
                tools=tools,
                output_schema={
                    **StudioAgentOutput.model_json_schema(),
                    "additionalProperties": False,
                },
                session=session,
                legacy_items=legacy,
                call_tool=call_tool,
                on_event=on_event,
                on_checkpoint=save_checkpoint,
            )
        finally:
            if harness.session:
                harness.session["scope"] = _conversation_scope(request)
                harness.session["source_versions"] = studio.source_versions
                harness.session["working_assets"] = studio.working_assets
                harness.session["render_jobs"] = render_jobs
                harness.session["gateway_tools"] = [
                    tool.model_dump(by_alias=True, exclude_none=True)
                    for _, tool in (await available()).values()
                    if tool.name != _GATEWAY_SEARCH_TOOL
                ]
                studio.session_items = [harness.session]
                if studio.session_sink:
                    studio.session_sink(studio.session_items)
    except ToolApprovalPending as exc:
        approval = _approval_request(
            SimpleNamespace(
                name=exc.call["tool_name"],
                call_id=exc.call["call_id"],
                arguments=json.dumps(exc.call["arguments"]),
            )
        )
        _record_approval_requests(studio, [approval])
        state = json.dumps(
            {"harness": "codex", "version": 1, "scope": _scope(request), "call": exc.call}
        )
        raise StudioAgentApprovalRequired(
            state, [approval], studio.session_items, studio.tool_events
        ) from exc
    except Exception as exc:
        _progress(
            studio,
            event_id="run",
            event_type="RUN_ERROR",
            title="Agent stopped",
            message=f"The run stopped ({type(exc).__name__}).",
            status="failed",
        )
        raise
    final = StudioAgentOutput.model_validate_json(raw)
    final.filename = normalize_markdown_filename(final.filename, final.title)
    delivered = _validate_video_delivery(request, studio, final)
    _progress(
        studio,
        event_id="run",
        event_type="RUN_FINISHED" if delivered else "RUN_ERROR",
        title="Agent finished" if delivered else "Export incomplete",
        message=f"Completed {final.title}." if delivered else final.summary,
        status="completed" if delivered else "failed",
    )
    return final


def completed_label(name: str) -> str:
    if name.endswith("get_render_progress"):
        return "Remotion is assembling the MP4"
    if name.endswith(("query_music_task", "get_music_task")):
        return "The audio provider is preparing the soundtrack"
    return "The video provider is processing the clip"
