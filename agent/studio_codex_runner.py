"""Studio policy and tool boundary around the Codex app-server harness."""

from __future__ import annotations

import json
from types import SimpleNamespace


from agent.codex_harness import CodexHarness, SESSION_TYPE, ToolApprovalPending
from agent.gateway_executor import GatewayExecutor
from agent.session_scope import conversation_scope as _conversation_scope, execution_scope as _scope
from agent.studio_agent_next import (
    STUDIO_MANAGER_INSTRUCTIONS,
    StudioAgentApprovalRequired,
    StudioAgentOutput,
    _GATEWAY_SEARCH_TOOL,
    _agent_model,
    _approval_request,
    _input_for,
    _progress,
    _record_approval_requests,
    _validate_video_delivery,
    normalize_markdown_filename,
    report_progress,
)



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
    executor = GatewayExecutor(studio, servers, session)
    render_jobs = executor.render_jobs
    execute = executor.execute
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

    await executor.connect_tools(session)
    available = executor.available

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
