from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from collections import defaultdict, deque
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, NotRequired

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from deepagents.backends.utils import create_file_data
from deepagents.middleware.filesystem import FilesystemMiddleware, FilesystemPermission
from deepagents.middleware.skills import SkillsMiddleware
from langchain.agents.middleware import TodoListMiddleware, wrap_tool_call
from langchain.agents.middleware.types import AgentState, PrivateStateAttr
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command
from langgraph.errors import GraphRecursionError
from pydantic import ValidationError

from agent.backend_config import configured_deep_agent_model
from agent.deep_agent.checkpoints import StudioCheckpointer
from agent.deep_agent.costs import append_media_costs
from agent.deep_agent.files import subagent_file_updates
from agent.deep_agent.memory import ProjectMemory, append_only_middleware
from agent.deep_agent.usage import ModelUsage
from agent.deep_agent.routing import route_intent, capability_table
from agent.gateway_executor import GatewayExecutor, tool_needs_approval
from agent.errors import AgentRunLimitExceeded
from agent.studio_agent_next import (
    STUDIO_MANAGER_INSTRUCTIONS,
    StudioAgentApprovalRequired,
    StudioAgentOutput,
    _GATEWAY_SEARCH_TOOL,
    _approval_request,
    _input_for,
    _progress,
    _record_approval_requests,
    _validate_video_delivery,
    _media_input_arguments,
    normalize_markdown_filename,
    report_progress,
)
from agent.session_scope import conversation_scope as _conversation_scope, execution_scope as _scope

logger = logging.getLogger(__name__)


class StudioAgentState(AgentState):
    structured_response: NotRequired[Annotated[dict | None, PrivateStateAttr]]


SESSION_TYPE = "renderhaus_deepagents_session"
SKILLS_ROOT = Path(__file__).parent / "skills"
DISPATCH_TARGETS = {
    "call_media_tool": {"Gemini", "OpenAI", "Seedance", "Seedream", "Kling", "Runway", "Fal", "Luma", "ModelStudio", "Sync", "HeyGen", "Topaz"},
    "call_audio_tool": {"ElevenLabs", "FishAudio", "FishAudioProvider", "Fish_Audio", "Mureka"},
    "call_editor_tool": {"Remotion", "HyperFrames", "Ffmpeg"},
}
FS_TOOLS = ["ls", "read_file", "write_file", "edit_file", "glob", "grep"]
PERMISSIONS = [FilesystemPermission(operations=["write"], paths=["/skills/**"], mode="deny")]

INSTRUCTIONS = STUDIO_MANAGER_INSTRUCTIONS.replace("`call_gateway_tool`", "the matching role dispatch tool").replace(
    "JSON-encoded arguments", "an arguments object",
) + """
You use LangChain Deep Agents. Read the relevant /skills/<name>/SKILL.md before media work.
Read skills before using call_media_tool, call_audio_tool, or call_editor_tool. Each dispatch tool takes
an exact discovered Gateway tool_name and an arguments object matching its inputSchema.
Search before dispatch. Delegate focused work to planner, media, audio, or editor when useful.
Start independent steps in intent_route.execution_groups in parallel. For an off-screen
voiceover, discover the video and speech schemas and any authorized voice lookup first.
Launch media and audio task calls together in one assistant message, or batch the video
submission and TTS dispatch together. Dispatch TTS before starting a blocking video poll.
Only assembly waits for both completed assets. Honor explicit dependencies in the brief,
such as narration that requires a generated clip's transcript or a picture-synchronized Foley.
Omit timeline fps and bitrate unless the customer sets them. The renderer preserves the primary
visual's measured frame rate and quality; a cinematic brief does not request 24 fps.
Remotion remains the default renderer. Explicit HyperFrames requests use the optional local
tool schema in read_studio_context, through call_editor_tool. If disabled, report the blocker.
HyperFrames only previews composition inputs, never executes HTML or produces a video here.
Do not silently replace a requested HyperFrames workflow with Remotion or a hosted HeyGen API.
Use write_todos to track multi-shot or multi-step work and update the plan as steps finish.
Pass current asset handles, the plan, and saved job IDs in the task description. Project files
are virtual and private to this workspace/project/conversation. There is no shell or direct
provider access. read_studio_context supplies optional canvas references and current assets.
Use report_progress for customer updates. Never claim to be awaiting approval without calling
a tool; the host displays native interrupts as approval cards.
Follow the host intent_route and capability map. Selection is an explicit customer request,
then a named exception, then the capability default. Pending defaults use only their configured
interim tool. Never select by tier or cheapest price. Every project follows the same map.
Project confidentiality is stored metadata and has no effect on routing or approvals.
If dispatch returns not_run with a route, discover that route's schema and dispatch its exact
tool/model with all requested controls intact. Do not weaken required features to find a route.
The host discloses provider/model, selection reason and estimated list cost before approval or
dispatch. Unknown means unknown, not free. All paid video requires approval even in autonomous
runs when premium_video_approval is enabled. Sync and HeyGen always require consent and cost approval
independently of that switch. Keep all existing approval and spending gates.
Act-Two and Kling Motion Control also always require consent and cost approval, including autonomous
runs. Use /skills/act-two/SKILL.md for sequential shot/silence chunks and Remotion concatenation.
Mirelo picture-synced SFX returns a video. Dispatch Fal___mirelo_v2a and Fal___get_video_task
through call_media_tool in the media role. The audio role handles text-only ElevenLabs SFX.
Mirelo paid video needs cost approval even autonomous when premium_video_approval is enabled.
Record explicit customer acceptance/rejection of completed media with record_media_outcome,
using the saved generation call ID from media_jobs. Provider success is not customer acceptance.
Artifact rejection proposes one capability-map retry through the normal approval/spending gates.
Ad matrices use Remotion___render_ad_variants plan -> render_first -> render_batch. Planning is
free. Both render stages always pause for human approval, including autonomous runs. Bind every
render to the returned plan_hash. Inspect first-aspect frames against expected verbatim strings
before requesting batch approval. Never assert OCR matched without a vision comparison. Ffmpeg
inspection runs on this worker with its job directory. Resolve editing stays parked. Delivery and
loudness QC are pending feat/remotion-delivery-qc; a matrix render is not a delivery QC pass.
Spending-approval rejection does not authorize a retry. Poll pending jobs before review.
"""


MANAGER_OUTPUT_INSTRUCTIONS = """
Finish by calling StudioAgentOutput with title, summary, markdown, and filename.
Do not finish the manager turn with plain text. Use this tool only after all required work
finishes or after documenting a real blocker. Subagents return their task results to you.
The host appends the recorded media cost line items and total. Keep costs out of your narrative.
"""


def _signature(name, arguments):
    return json.dumps([name, arguments], sort_keys=True)


def _gateway_action(action):
    name, arguments = action["name"], action["args"]
    if name in DISPATCH_TARGETS:
        return arguments["tool_name"], arguments["arguments"]
    return name, arguments


async def run_with_servers(request, studio, servers, *, model=None):
    injected_model = model
    model = model if model is not None else configured_deep_agent_model()
    usage = ModelUsage(_scope(request))
    output_repair = False
    snapshots = [item for item in request.session_items if item.get("type") == SESSION_TYPE]
    session = snapshots[-1] if snapshots else None
    thread_id = _conversation_scope(request)
    if session and (session.get("version") != 1 or session.get("scope") != thread_id):
        raise ValueError("This Deep Agents conversation belongs to a different workspace or conversation.")
    executor = GatewayExecutor(studio, servers, session, run_scope=_scope(request))
    await executor.connect_tools(session)
    initial = await executor.available()
    aliases = defaultdict(deque)

    def save_checkpoint(checkpoint):
        studio.session_items = [{
            "type": SESSION_TYPE, "version": 1, "scope": thread_id, "thread_id": thread_id,
            "checkpoint": checkpoint, **executor.snapshot(),
        }]
        if studio.session_sink:
            studio.session_sink(studio.session_items)

    saver = StudioCheckpointer(thread_id, (session or {}).get("checkpoint"), save_checkpoint)
    backend = CompositeBackend(
        default=StateBackend(),
        routes={"/skills/": FilesystemBackend(root_dir=SKILLS_ROOT, virtual_mode=True)},
    )

    @tool("report_progress")
    async def progress(message: str) -> str:
        """Show a concise customer-facing progress update."""
        return await report_progress(studio, message)

    @tool
    async def read_studio_context(tool_name: str | None = None) -> dict:
        """Read routed capabilities, assets and discovered names; request one named tool for its schema."""
        route = route_intent(request.prompt, arguments=_media_input_arguments(studio.nodes)).public()
        available = await executor.available()
        steps = route.get("steps") or [route]
        selected = {step.get("tool") for step in steps}
        rows = capability_table()
        result = {
            "intent_route": route,
            "capabilities": [
                {key: row[key] for key in ("provider", "model", "label", "tools", "jobs", "price",
                                          "license", "training_eligible") if key in row}
                for row in rows if selected.intersection(row.get("tools", {}).values())
                and any(step.get("model") in {None, row.get("model")} for step in steps)
            ],
            "media_jobs": executor.media_jobs,
            "references": _input_for("", list(studio.nodes)),
            "assets": list(studio.working_assets.values()),
            "render_jobs": executor.render_jobs,
            "tools": sorted(available),
        }
        if tool_name:
            found = available.get(tool_name)
            if found:
                schema = found[1]
                result["tool_schema"] = {"name": schema.name, "description": schema.description,
                                         "inputSchema": schema.input_schema}
            else:
                result["error"] = "Search for this tool before requesting its schema."
        return result

    def dispatcher(tool_name):
        @tool(tool_name)
        async def dispatch(tool_name: str, arguments: dict, runtime: ToolRuntime) -> dict:
            """Call a discovered media tool with its exact name and schema-checked arguments."""
            if output_repair:
                return {"status": "not_run", "error": "Provider dispatch is disabled during completion repair."}
            wrapper = dispatch.name
            if tool_name.split("___", 1)[0] not in DISPATCH_TARGETS[wrapper]:
                return {"status": "failed", "error": "This role cannot call that provider."}
            key = _signature(tool_name, arguments)
            call_id = aliases[key].popleft() if aliases[key] else "tool-" + hashlib.sha256(
                json.dumps([
                    _scope(request), runtime.config["configurable"].get("checkpoint_ns", ""),
                    runtime.tool_call_id,
                ]).encode()
            ).hexdigest()
            return await executor.execute(
                {"tool_name": tool_name, "arguments": arguments, "call_id": call_id}, approved=True,
            )
        return dispatch

    dispatch_tools = [dispatcher(name) for name in DISPATCH_TARGETS]
    dispatch_schemas = {dispatch.name: dispatch.tool_call_schema for dispatch in dispatch_tools}
    @tool
    async def record_media_outcome(call_id: str, outcome: str) -> dict:
        """Record explicit customer review of a completed saved media job as accepted or rejected."""
        return executor.record_outcome(call_id, outcome)

    @tool("StudioAgentOutput", args_schema=StudioAgentOutput, return_direct=True)
    async def finish(title: str, summary: str, markdown: str, filename: str,
                     runtime: ToolRuntime) -> Command:
        """Finish the manager turn with the validated downloadable Studio artifact."""
        output = StudioAgentOutput(title=title, summary=summary, markdown=markdown, filename=filename)
        return Command(update={"structured_response": output.model_dump(), "messages": [
            ToolMessage(content="Studio artifact recorded.", tool_call_id=runtime.tool_call_id),
        ]})

    common_tools = [progress, read_studio_context, record_media_outcome]
    if _GATEWAY_SEARCH_TOOL in initial:
        schema = initial[_GATEWAY_SEARCH_TOOL][1]

        async def search(**arguments):
            return await executor.execute({
                "tool_name": _GATEWAY_SEARCH_TOOL, "arguments": arguments,
                "call_id": "search-" + hashlib.sha256((_scope(request) + json.dumps(arguments, sort_keys=True)).encode()).hexdigest(),
            }, approved=True)

        from langchain_core.tools import StructuredTool
        common_tools.append(StructuredTool.from_function(
            coroutine=search, name=schema.name, description=schema.description or "Search Gateway tools",
            args_schema=schema.input_schema,
        ))

    def needs_approval(call):
        try:
            arguments = dispatch_schemas[call.tool_call["name"]].model_validate(call.tool_call["args"])
        except ValidationError:
            return False
        if output_repair:
            return False
        if executor.tts_argument_error(arguments.tool_name, arguments.arguments):
            return False
        route = executor.media_selection(arguments.tool_name, arguments.arguments)
        if executor.selection_blocker(arguments.tool_name, arguments.arguments, route):
            return False
        executor.disclose_selection(route, call.tool_call["id"], arguments.tool_name, arguments.arguments)
        return tool_needs_approval(arguments.tool_name, studio.autonomous, arguments.arguments)

    def approval_description(tool_call, state, runtime):
        name, arguments = _gateway_action({"name": tool_call["name"], "args": tool_call["args"]})
        route = executor.media_selection(name, arguments)
        plan = arguments.get("plan_summary", "") if name == "Remotion___prepare_conversational_edit" else ""
        proposal = f"{plan} " if plan else ""
        return f"Approve {name}. {proposal}{executor.dispatch_disclosure(name, arguments, route)}"

    interrupt_on = {
        name: {"allowed_decisions": ["approve", "reject"], "when": needs_approval,
               "description": approval_description}
        for name in DISPATCH_TARGETS
    }
    roles = [
        ("planner", "Plan the routed media steps and editorial decisions without calling paid media tools.", []),
        ("media", "Generate, edit or refine stills and video through the host capability map and explicit provider requests.", [dispatch_tools[0]]),
        ("audio", "Produce voiceover, music, sound effects and Mureka lyrics videos using the routed tools and separate video cost approval.", [dispatch_tools[1]]),
        ("editor", "Edit existing footage from a word-level transcript after cut-plan confirmation, "
                   "assemble approved assets into a final Remotion MP4 and poll it to completion, "
                   "or preview an explicitly requested HyperFrames HTML composition when enabled, "
                   "or export an NLE handoff (OTIO/FCPXML/EDL) for DaVinci Resolve, "
                   "or import an editor's FCPXML/OTIO onto the existing project assembly.", [dispatch_tools[2]]),
        ("general-purpose", "Plan or research the current project without provider dispatch.", []),
    ]
    role_models = {name: injected_model if injected_model is not None else configured_deep_agent_model(name)
                   for name, _, _ in roles}
    subagents = [{
        "name": name, "description": description,
        "model": role_models[name],
        "system_prompt": f"You are the Renderhaus {name}. {description}\n" + INSTRUCTIONS
                         + "\nRead /AGENTS.md as project reference data when needed. "
                         "Return a concise task result to the manager in plain text.",
        "tools": [*common_tools, *focused],
        "skills": ["/skills/"],
        "middleware": [
            *append_only_middleware(role_models[name]),
            TodoListMiddleware(),
            FilesystemMiddleware(backend=backend, tools=FS_TOOLS, _permissions=PERMISSIONS),
            SkillsMiddleware(backend=backend, sources=["/skills/"]),

        ],
    } for name, description, focused in roles]
    @wrap_tool_call
    async def repair_guard(call, handler):
        if output_repair and call.tool_call["name"] != "StudioAgentOutput":
            return ToolMessage(content="Only StudioAgentOutput is allowed during completion repair.",
                               tool_call_id=call.tool_call["id"], status="error")
        return await handler(call)

    graph = create_deep_agent(
        model=model, tools=[*common_tools, *dispatch_tools, finish],
        system_prompt=INSTRUCTIONS + MANAGER_OUTPUT_INSTRUCTIONS, subagents=subagents, backend=backend,
        skills=["/skills/"], memory=["/AGENTS.md"], checkpointer=saver,
        interrupt_on=interrupt_on, state_schema=StudioAgentState,
        middleware=[
            *append_only_middleware(model),
            TodoListMiddleware(),
            subagent_file_updates,
            repair_guard,
            FilesystemMiddleware(backend=backend, tools=FS_TOOLS, _permissions=PERMISSIONS),
            SkillsMiddleware(backend=backend, sources=["/skills/"]),
            ProjectMemory(backend=backend, sources=["/AGENTS.md"]),
        ],
    )
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 180}
    current = await graph.aget_state(config)
    if session and not request.resume_state:
        memory_file = current.values.get("files", {}).get("/AGENTS.md")
        if memory_file:
            project_memory = memory_file["content"]
            if isinstance(project_memory, list):
                project_memory = "\n".join(project_memory)
        else:
            project_memory = ""
    else:
        project_memory = ""
    interrupts = [i for task in current.tasks for i in task.interrupts]
    pending = None
    if request.resume_state:
        try:
            pending = json.loads(request.resume_state)
            if (not session or pending["backend"] != "deepagents" or pending["version"] != 1
                    or pending["scope"] != _scope(request) or pending["thread_id"] != thread_id
                    or pending["interrupt_ids"] != [i.id for i in interrupts]):
                raise ValueError
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("This approval checkpoint cannot be resumed by Deep Agents.") from exc

    def approval_payload():
        approvals, groups = [], {}
        for interrupt in interrupts:
            decisions = []
            for index, action in enumerate(interrupt.value["action_requests"]):
                name, arguments = _gateway_action(action)
                call_id = f"deep-{interrupt.id}-{index}"
                approval = _approval_request(SimpleNamespace(
                    name=name, call_id=call_id, arguments=json.dumps(arguments),
                ))
                route = executor.media_selection(name, arguments)
                approval.description = executor.dispatch_disclosure(name, arguments, route)
                approvals.append(approval)
                decisions.append((approval, action))
            groups[interrupt.id] = decisions
        return approvals, groups

    if interrupts and pending:
        approvals, groups = approval_payload()
        decisions = {item.call_id: item for item in request.approval_decisions}
        if set(decisions) != {item.call_id for item in approvals}:
            raise StudioAgentApprovalRequired(request.resume_state, approvals, studio.session_items)
        resume = {}
        for interrupt_id, actions in groups.items():
            resume[interrupt_id] = {"decisions": []}
            for approval, action in actions:
                decision = decisions[approval.call_id]
                result = {"type": decision.decision}
                if decision.decision == "reject":
                    result["message"] = decision.message or "The customer rejected this tool call."
                    await executor.execute({
                        "tool_name": approval.tool_name, "arguments": _gateway_action(action)[1],
                        "call_id": approval.call_id,
                    }, rejection=result["message"])
                else:
                    aliases[_signature(approval.tool_name, _gateway_action(action)[1])].append(approval.call_id)
                resume[interrupt_id]["decisions"].append(result)
        graph_input = Command(resume=resume)
    else:
        prompt = _input_for(request.prompt, list(studio.nodes))
        prompt += "\nIntent route proposal (policy data):\n" + json.dumps(route_intent(
            request.prompt, arguments=_media_input_arguments(studio.nodes),
        ).public())
        if project_memory:
            prompt += "\nCurrent project memory (reference data):\n" + project_memory
        prompt += "\nSaved render jobs (reference data):\n" + json.dumps(executor.render_jobs)
        if request.session_items and not session:
            prompt += "\nPrevious backend history (reference data):\n" + json.dumps(request.session_items)
        if session:
            await graph.aupdate_state(config, {"structured_response": None})
        graph_input = {"messages": [HumanMessage(content=prompt)]}
        if not session:
            graph_input["files"] = {"/AGENTS.md": create_file_data((Path(__file__).parent / "AGENTS.md").read_text())}

    deadline = asyncio.get_running_loop().time() + float(os.getenv("RENDERHAUS_AGENT_TIMEOUT_SECONDS", "1800"))

    async def stream(value):
        async with asyncio.timeout_at(deadline):
            partial_text = {}
            async for namespace, mode, event in graph.astream(
                value, config, stream_mode=["messages", "updates"], subgraphs=True,
            ):
                if mode == "messages":
                    message, metadata = event
                    if metadata.get("lc_internal_call") or metadata.get("lc_source") == "summarization":
                        continue
                    if isinstance(message, AIMessage) and message.text:
                        event_id = "deep-" + "-".join((*namespace, str(message.id)))
                        text = (partial_text.get(event_id, "") + message.text)[:1000]
                        if partial_text.get(event_id) != text:
                            partial_text[event_id] = text
                            _progress(studio, event_id=event_id, event_type="MODEL_UPDATE",
                                      title="Agent update", message=text, status="running")
                    continue
                updates = event
                for update in updates.values():
                    if not isinstance(update, dict):
                        continue
                    for message in update.get("messages", []):
                        if isinstance(message, AIMessage):
                            usage.record(message)
                        if isinstance(message, AIMessage) and message.text:
                            event_id = "deep-" + "-".join((*namespace, str(message.id)))
                            partial_text.pop(event_id, None)
                            _progress(studio, event_id=event_id, event_type="MODEL_UPDATE",
                                      title="Agent update", message=message.text[:1000], status="completed")
    try:
        await stream(graph_input)
        current = await graph.aget_state(config)
        interrupts = [i for task in current.tasks for i in task.interrupts]
        if interrupts:
            approvals, _ = approval_payload()
            _record_approval_requests(studio, approvals)
            state = json.dumps({
                "backend": "deepagents", "version": 1, "scope": _scope(request),
                "thread_id": thread_id, "interrupt_ids": [i.id for i in interrupts],
            })
            raise StudioAgentApprovalRequired(state, approvals, studio.session_items, studio.tool_events)
        for attempt in range(3):
            try:
                final = StudioAgentOutput.model_validate(current.values.get("structured_response"))
                break
            except ValidationError:
                if attempt == 2:
                    raise ValueError("The manager did not return a valid StudioAgentOutput after two repairs.")
                output_repair = True
                await stream({"messages": [HumanMessage(content=
                    "Finish by calling StudioAgentOutput with title, summary, markdown and filename. "
                    "Summarize existing results and blockers only. Do not repeat media generation or rendering.")],
                    "structured_response": None})
                current = await graph.aget_state(config)
                interrupts = [i for task in current.tasks for i in task.interrupts]
                if interrupts:
                    approvals, _ = approval_payload()
                    _record_approval_requests(studio, approvals)
                    state = json.dumps({"backend": "deepagents", "version": 1, "scope": _scope(request),
                                        "thread_id": thread_id, "interrupt_ids": [i.id for i in interrupts]})
                    raise StudioAgentApprovalRequired(state, approvals, studio.session_items, studio.tool_events)
        final.filename = normalize_markdown_filename(final.filename, final.title)
        delivered = _validate_video_delivery(request, studio, final)
        append_media_costs(final, executor.cost_ledger, executor.run_scope)
        _progress(studio, event_id="run", event_type="RUN_FINISHED" if delivered else "RUN_ERROR",
                  title="Agent finished" if delivered else "Export incomplete",
                  message=f"Completed {final.title}." if delivered else final.summary,
                  status="completed" if delivered else "failed")
        return final
    except StudioAgentApprovalRequired:
        raise
    except (GraphRecursionError, TimeoutError) as exc:
        raise AgentRunLimitExceeded("The manager reached its execution limit.") from exc
    except Exception as exc:
        _progress(studio, event_id="run", event_type="RUN_ERROR", title="Agent stopped",
                  message=f"The run stopped ({type(exc).__name__}).", status="failed")
        raise
    finally:
        usage.publish(logger)
        saver.publish()
