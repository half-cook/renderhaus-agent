from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from mcp import Tool
from pydantic import PrivateAttr

from agent.deep_agent.runner import SESSION_TYPE, run_with_servers
from agent.studio_agent_next import (
    StudioAgentApprovalRequired,
    StudioAgentRequest,
    StudioApprovalDecision,
    _context_from_request,
)

FINAL = {"title": "Product still", "summary": "A product still is ready.",
         "markdown": "# Product still", "filename": "../Product still"}
IMAGE = Tool(name="Seedream___text_to_image", description="Generate a still",
             inputSchema={"type": "object", "properties": {"prompt": {"type": "string"}},
                          "required": ["prompt"], "additionalProperties": False})


class ScriptedModel(BaseChatModel):
    _steps: list = PrivateAttr()
    _seen: list = PrivateAttr(default_factory=list)

    def __init__(self, steps):
        super().__init__()
        self._steps = list(steps)

    @property
    def _llm_type(self):
        return "renderhaus-scripted-test"

    def bind_tools(self, tools, **kwargs):
        names = {t.name if hasattr(t, "name") else t["function"]["name"] for t in tools}
        return self.bind(available_tools=names)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._seen.append((messages, kwargs.get("available_tools", set())))
        if not self._steps:
            raise AssertionError("Unexpected model call")
        step = self._steps.pop(0)
        if callable(step):
            step = step(messages, kwargs.get("available_tools", set()))
        return ChatResult(generations=[ChatGeneration(message=step)])


class StreamingModel(ScriptedModel):
    _partial_received: asyncio.Event | None = PrivateAttr(default=None)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        message = self._generate(messages, stop=stop, **kwargs).generations[0].message
        if message.text:
            midpoint = len(message.text) // 2
            yield ChatGenerationChunk(message=AIMessageChunk(
                content=message.text[:midpoint], id=message.id,
            ))
            if self._partial_received is not None:
                await asyncio.wait_for(self._partial_received.wait(), timeout=1)
            yield ChatGenerationChunk(message=AIMessageChunk(
                content=message.text[midpoint:], id=message.id,
            ))
        yield ChatGenerationChunk(message=AIMessageChunk(
            content="", id=message.id, tool_call_chunks=[
                {"name": tool["name"], "args": json.dumps(tool["args"]),
                 "id": tool["id"], "index": index}
                for index, tool in enumerate(message.tool_calls)
            ],
        ))


def call(name, args, call_id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def final():
    return call("StudioAgentOutput", FINAL, "final")


def read_skill():
    return call("read_file", {"file_path": "/skills/product-images/SKILL.md"}, "skill")


def image(call_id="image"):
    return call("call_media_tool", {"tool_name": IMAGE.name, "arguments": {"prompt": "Product hero"}}, call_id)


class Gateway:
    def __init__(self, tools=None, result=None):
        self.tools = tools if tools is not None else [IMAGE]
        self.call_tool = AsyncMock(return_value=result or {
            "status": "succeeded", "image_url": "https://cdn.example/hero.png",
        })

    async def list_tools(self):
        return self.tools


class DeepAgentTests(unittest.IsolatedAsyncioTestCase):
    def request(self, **kwargs):
        return StudioAgentRequest(prompt="Make a product still", workspace_id="workspace",
                                  project_id="project", conversation_id="conversation",
                                  job_id="job", **kwargs)

    async def run_graph(self, request, steps, gateway=None, studio=None):
        studio = studio or _context_from_request(request)
        model = ScriptedModel(steps)
        result = await run_with_servers(request, studio, [gateway or Gateway()], model=model)
        self.assertFalse(model._steps)
        return result, studio, model

    async def test_todos_persist_across_fresh_workers(self):
        from agent.deep_agent.checkpoints import StudioCheckpointer

        todos = [{"content": "Preview the first shot", "status": "in_progress"},
                 {"content": "Assemble the approved shots", "status": "pending"}]

        def plan(messages, tools):
            self.assertIn("write_todos", tools)
            return call("write_todos", {"todos": todos}, "plan")

        _, studio, _ = await self.run_graph(self.request(), [plan, final()])
        _, restored, _ = await self.run_graph(
            self.request(session_items=json.loads(json.dumps(studio.session_items))), [final()],
        )
        session = restored.session_items[0]
        saver = StudioCheckpointer(session["thread_id"], session["checkpoint"])
        state = saver.get_tuple({"configurable": {"thread_id": session["thread_id"]}})
        self.assertEqual(state.checkpoint["channel_values"]["todos"], todos)

    async def test_planner_todos_do_not_replace_manager_plan(self):
        from agent.deep_agent.checkpoints import StudioCheckpointer

        todos = [{"content": "Deliver the edit", "status": "pending"}]

        def planner(messages, tools):
            self.assertIn("write_todos", tools)
            self.assertNotIn("call_media_tool", tools)
            return call("write_todos", {"todos": [
                {"content": "Plan shot durations", "status": "completed"},
            ]}, "child-plan")

        _, studio, _ = await self.run_graph(self.request(), [
            call("write_todos", {"todos": todos}, "manager-plan"),
            call("task", {"subagent_type": "planner", "description": "Plan two shots"}, "planner"),
            planner, AIMessage(content="Two shots planned."), final(),
        ])
        session = studio.session_items[0]
        state = StudioCheckpointer(session["thread_id"], session["checkpoint"]).get_tuple(
            {"configurable": {"thread_id": session["thread_id"]}},
        )
        self.assertEqual(state.checkpoint["channel_values"]["todos"], todos)

    async def test_skills_disclose_tools_only_after_relevant_read(self):
        def before(messages, tools):
            self.assertNotIn("call_media_tool", tools)
            self.assertNotIn("call_audio_tool", tools)
            self.assertNotIn("execute", tools)
            prompt = messages[0].text
            self.assertIn("product-images", prompt)
            self.assertNotIn("Start with one inexpensive still", prompt)
            return read_skill()

        def after(messages, tools):
            self.assertIn("call_media_tool", tools)
            self.assertNotIn("call_audio_tool", tools)
            self.assertIn("Start with one inexpensive still", "\n".join(m.text for m in messages))
            return image()

        gateway = Gateway()
        result, studio, _ = await self.run_graph(self.request(autonomous=True), [before, after, final()], gateway)
        self.assertEqual(result.filename, "Product-still.md")
        gateway.call_tool.assert_awaited_once_with(IMAGE.name, {"prompt": "Product hero"})
        self.assertEqual(studio.tool_events[0].status, "succeeded")
        self.assertEqual(studio.session_items[0]["type"], SESSION_TYPE)
        self.assertEqual(studio.progress_events[-1].type, "RUN_FINISHED")

    async def test_new_turn_reloads_changed_skill_metadata_and_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "product-images" / "SKILL.md"
            skill.parent.mkdir()
            skill.write_text("---\nname: product-images\ndescription: Old image workflow\n"
                             "metadata:\n  include_tools: call_media_tool\n---\nCreate an image.\n")
            with patch("agent.deep_agent.runner.SKILLS_ROOT", root):
                _, studio, _ = await self.run_graph(self.request(), [final()])
                skill.write_text("---\nname: product-images\ndescription: Updated assembly workflow\n"
                                 "metadata:\n  include_tools: call_editor_tool\n---\nAssemble an edit.\n")

                def updated_index(messages, tools):
                    self.assertIn("Updated assembly workflow", messages[0].text)
                    self.assertNotIn("Old image workflow", messages[0].text)
                    self.assertNotIn("call_editor_tool", tools)
                    return read_skill()

                def updated_tools(messages, tools):
                    self.assertIn("call_editor_tool", tools)
                    self.assertNotIn("call_media_tool", tools)
                    self.assertIn("Assemble an edit.", messages[-1].text)
                    return final()

                await self.run_graph(self.request(session_items=studio.session_items),
                                     [updated_index, updated_tools])

    async def test_approval_restores_in_fresh_worker_and_uses_exact_call(self):
        request = self.request()
        studio = _context_from_request(request)
        gateway = Gateway()
        with self.assertRaises(StudioAgentApprovalRequired) as paused:
            await run_with_servers(request, studio, [gateway], model=ScriptedModel([read_skill(), image()]))
        approval = paused.exception.approvals[0]
        self.assertEqual(approval.tool_name, IMAGE.name)
        gateway.call_tool.assert_not_awaited()
        serialized = json.loads(json.dumps(studio.session_items))
        resumed = self.request(session_items=serialized, resume_state=paused.exception.state,
                               approval_decisions=[StudioApprovalDecision(call_id=approval.call_id, decision="approve")])
        result, restored, _ = await self.run_graph(resumed, [final()], gateway)
        gateway.call_tool.assert_awaited_once()
        self.assertEqual(restored.tool_events[0].id, approval.call_id)
        self.assertEqual(result.title, FINAL["title"])

    async def test_rejection_never_dispatches_and_is_recorded(self):
        request = self.request()
        studio = _context_from_request(request)
        gateway = Gateway()
        with self.assertRaises(StudioAgentApprovalRequired) as paused:
            await run_with_servers(request, studio, [gateway], model=ScriptedModel([read_skill(), image()]))
        approval = paused.exception.approvals[0]
        resumed = self.request(session_items=studio.session_items, resume_state=paused.exception.state,
                               approval_decisions=[StudioApprovalDecision(call_id=approval.call_id, decision="reject", message="Skip this")])
        _, restored, _ = await self.run_graph(resumed, [final()], gateway)
        gateway.call_tool.assert_not_awaited()
        self.assertEqual(restored.tool_events[0].status, "rejected")

    async def test_thread_and_memory_resume_across_turns(self):
        request = self.request(autonomous=True)
        _, studio, _ = await self.run_graph(request, [
            call("write_file", {"file_path": "/AGENTS.md", "content": "Use a blue background."}, "memory"),
            call("write_file", {"file_path": "/brief.md", "content": "Quiet product reveal"}, "brief"), final(),
        ])
        def verify(messages, tools):
            self.assertIn("Use a blue background.", messages[0].text)
            self.assertGreater(len(messages), 3)
            return call("read_file", {"file_path": "/brief.md"}, "read-brief")

        def verify_file(messages, tools):
            self.assertIn("Quiet product reveal", messages[-1].text)
            return final()

        _, restored, _ = await self.run_graph(self.request(autonomous=True, session_items=studio.session_items), [verify, verify_file])
        self.assertEqual(studio.session_items[0]["thread_id"], restored.session_items[0]["thread_id"])
        foreign = self.request(session_items=studio.session_items).model_copy(update={"project_id": "other"})
        with self.assertRaisesRegex(ValueError, "different workspace"):
            await self.run_graph(foreign, [final()])

    async def test_subagent_delegation_has_focused_tools(self):
        def audio_read(messages, tools):
            self.assertIn("Renderhaus audio", messages[0].text)
            self.assertNotIn("call_media_tool", tools)
            return call("read_file", {"file_path": "/skills/product-images/SKILL.md"}, "audio-skill")

        def audio_result(messages, tools):
            self.assertNotIn("call_media_tool", tools)
            return AIMessage(content="Audio plan complete. No generation needed.")

        result, _, _ = await self.run_graph(self.request(autonomous=True), [
            call("task", {"subagent_type": "audio", "description": "Plan a quiet soundtrack"}, "delegate"),
            audio_read, audio_result, final(),
        ])
        self.assertEqual(result.title, FINAL["title"])

    async def test_parallel_subagents_preserve_edits_and_independent_files(self):
        def verify_brief(messages, tools):
            self.assertIn("Updated brief", messages[-1].text)
            return call("read_file", {"file_path": "/audio.md"}, "read-audio")

        def verify_audio(messages, tools):
            self.assertIn("Quiet soundtrack", messages[-1].text)
            return final()

        tasks = AIMessage(content="", tool_calls=[
            call("task", {"subagent_type": "planner", "description": "Update the brief"}, "planner").tool_calls[0],
            call("task", {"subagent_type": "audio", "description": "Write the audio plan"}, "audio").tool_calls[0],
        ])

        def write_plan(messages, tools):
            if "Renderhaus planner" in messages[0].text:
                return call("edit_file", {"file_path": "/brief.md", "old_string": "Old brief",
                                          "new_string": "Updated brief"}, "edit-brief")
            self.assertIn("Renderhaus audio", messages[0].text)
            return call("write_file", {"file_path": "/audio.md", "content": "Quiet soundtrack"}, "audio-plan")

        _, studio, _ = await self.run_graph(self.request(), [
            call("write_file", {"file_path": "/brief.md", "content": "Old brief"}, "brief"),
            tasks, write_plan, write_plan, AIMessage(content="Plan ready."), AIMessage(content="Audio ready."),
            call("read_file", {"file_path": "/brief.md"}, "read-brief"), verify_brief, verify_audio,
        ])
        await self.run_graph(self.request(session_items=json.loads(json.dumps(studio.session_items))), [
            call("read_file", {"file_path": "/brief.md"}, "restored-brief"), verify_brief, verify_audio,
        ])

    async def test_interrupt_inside_subagent_resumes_nested_task(self):
        request = self.request()
        studio = _context_from_request(request)
        gateway = Gateway()
        with self.assertRaises(StudioAgentApprovalRequired) as paused:
            await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                call("task", {"subagent_type": "media", "description": "Generate the product hero"}, "delegate"),
                read_skill(), image(),
            ]))
        approval = paused.exception.approvals[0]
        resumed = self.request(session_items=studio.session_items, resume_state=paused.exception.state,
                               approval_decisions=[StudioApprovalDecision(call_id=approval.call_id, decision="approve")])
        await self.run_graph(resumed, [AIMessage(content="The still is generated."), final()], gateway)
        gateway.call_tool.assert_awaited_once()

    async def test_invalid_gateway_arguments_fail_before_dispatch(self):
        gateway = Gateway()
        bad = call("call_media_tool", {"tool_name": IMAGE.name, "arguments": {"missing": "prompt"}}, "bad")
        _, studio, _ = await self.run_graph(self.request(autonomous=True), [read_skill(), bad, final()], gateway)
        gateway.call_tool.assert_not_awaited()
        self.assertFalse(any(e.status == "succeeded" for e in studio.tool_events))

    async def test_malformed_dispatch_wrappers_return_tool_errors_without_dispatch(self):
        invalid = [
            {"arguments": {"prompt": "Hero"}},
            {"tool_name": 42, "arguments": {"prompt": "Hero"}},
            {"tool_name": IMAGE.name},
            {"tool_name": IMAGE.name, "arguments": "not an object"},
        ]

        def recover(messages, tools):
            self.assertEqual(messages[-1].status, "error")
            return final()

        for arguments in invalid:
            with self.subTest(arguments=arguments):
                gateway = Gateway()
                await self.run_graph(self.request(), [
                    read_skill(), call("call_media_tool", arguments, "bad-wrapper"), recover,
                ], gateway)
                gateway.call_tool.assert_not_awaited()

    async def test_project_files_cannot_write_into_shipped_skills(self):
        def check(messages, tools):
            self.assertIn("denied", messages[-1].text.lower())
            return final()

        await self.run_graph(self.request(autonomous=True), [
            call("write_file", {"file_path": "/skills/product-images/SKILL.md", "content": "corrupt"}, "write-skill"), check,
        ])

    async def test_no_completed_remotion_means_incomplete_video(self):
        request = self.request(autonomous=True).model_copy(update={"prompt": "Create a video ad"})
        result, studio, _ = await self.run_graph(request, [final()])
        self.assertIn("incomplete", result.summary)
        self.assertEqual(studio.progress_events[-1].status, "failed")

    async def test_new_turn_does_not_resume_an_unapproved_tool(self):
        request = self.request()
        studio = _context_from_request(request)
        gateway = Gateway()
        with self.assertRaises(StudioAgentApprovalRequired):
            await run_with_servers(request, studio, [gateway], model=ScriptedModel([read_skill(), image()]))
        new_request = self.request(session_items=studio.session_items).model_copy(update={"job_id": "next-job"})
        await self.run_graph(new_request, [final()], gateway)
        gateway.call_tool.assert_not_awaited()

    async def test_missing_or_wrong_scope_approval_does_not_dispatch(self):
        request = self.request()
        studio = _context_from_request(request)
        gateway = Gateway()
        with self.assertRaises(StudioAgentApprovalRequired) as paused:
            await run_with_servers(request, studio, [gateway], model=ScriptedModel([read_skill(), image()]))
        resumed = self.request(session_items=studio.session_items, resume_state=paused.exception.state)
        with self.assertRaises(StudioAgentApprovalRequired):
            await self.run_graph(resumed, [], gateway)
        wrong = resumed.model_copy(update={"job_id": "wrong-job"})
        with self.assertRaisesRegex(ValueError, "cannot be resumed"):
            await self.run_graph(wrong, [], gateway)
        gateway.call_tool.assert_not_awaited()

    async def test_autonomous_admin_still_interrupts(self):
        admin = Tool(name="ElevenLabs___workspace_groups_list", description="List groups",
                     inputSchema={"type": "object", "properties": {}})
        request = self.request(autonomous=True)
        gateway = Gateway([admin])
        with self.assertRaises(StudioAgentApprovalRequired):
            await self.run_graph(request, [
                call("read_file", {"file_path": "/skills/audio/SKILL.md"}, "audio"),
                call("call_audio_tool", {"tool_name": admin.name, "arguments": {}}, "admin"),
            ], gateway)
        gateway.call_tool.assert_not_awaited()

    async def test_batched_approvals_resume_all_decisions(self):
        request = self.request()
        studio = _context_from_request(request)
        gateway = Gateway()
        calls = [image("image-1").tool_calls[0], image("image-2").tool_calls[0]]
        calls[1]["args"]["arguments"]["prompt"] = "Second angle"
        with self.assertRaises(StudioAgentApprovalRequired) as paused:
            await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                read_skill(), AIMessage(content="", tool_calls=calls),
            ]))
        self.assertEqual(len(paused.exception.approvals), 2)
        resumed = self.request(session_items=studio.session_items, resume_state=paused.exception.state,
                               approval_decisions=[
                                   StudioApprovalDecision(call_id=a.call_id, decision="approve")
                                   for a in paused.exception.approvals
                               ])
        _, restored, _ = await self.run_graph(resumed, [final()], gateway)
        self.assertEqual(gateway.call_tool.await_count, 2)
        self.assertEqual({e.id for e in restored.tool_events}, {a.call_id for a in paused.exception.approvals})

    async def test_dry_run_keeps_video_incomplete(self):
        request = self.request(autonomous=True).model_copy(update={"prompt": "Render a video"})
        render = Tool(name="Remotion___render_timeline", description="Render timeline",
                      inputSchema={"type": "object", "properties": {}})
        gateway = Gateway([render], {"status": "dry_run", "timeline": {}})
        result, _, _ = await self.run_graph(request, [
            call("read_file", {"file_path": "/skills/final-assembly/SKILL.md"}, "assembly"),
            call("call_editor_tool", {"tool_name": render.name, "arguments": {}}, "render"), final(),
        ], gateway)
        self.assertIn("incomplete", result.summary)

    async def test_gateway_search_discovers_a_schema_for_dispatch(self):
        from agent.studio_agent_next import _GATEWAY_SEARCH_TOOL
        search = Tool(name=_GATEWAY_SEARCH_TOOL, description="Search Gateway tools",
                      inputSchema={"type": "object", "properties": {"query": {"type": "string"}},
                                   "required": ["query"]})
        gateway = Gateway([search])

        async def respond(name, arguments):
            if name == search.name:
                gateway.tools.append(IMAGE)
                return {"tools": [IMAGE.model_dump(by_alias=True)]}
            return {"status": "succeeded", "image_url": "https://cdn.example/hero.png"}

        gateway.call_tool.side_effect = respond
        await self.run_graph(self.request(autonomous=True), [
            call(search.name, {"query": "product image"}, "search"), read_skill(), image(), final(),
        ], gateway)
        self.assertEqual([item.args[0] for item in gateway.call_tool.await_args_list], [search.name, IMAGE.name])

    async def test_model_text_streams_before_the_response_finishes(self):
        request = self.request()
        studio = _context_from_request(request)
        received = []
        partial = asyncio.Event()
        text = "Planning the product shot."

        def progress(event):
            received.append(event)
            if event.type == "MODEL_UPDATE" and event.message == text[:len(text) // 2]:
                partial.set()

        studio.progress_sink = progress
        model = StreamingModel([
            AIMessage(content=text, id="plan", tool_calls=read_skill().tool_calls), final(),
        ])
        model._partial_received = partial
        await run_with_servers(request, studio, [Gateway()], model=model)
        self.assertTrue(partial.is_set())
        updates = [event for event in received if event.type == "MODEL_UPDATE"]
        self.assertEqual(updates[0].status, "running")
        self.assertEqual(updates[-1].message, text)
        self.assertEqual(updates[-1].status, "completed")
        self.assertEqual(len({event.id for event in updates}), 1)
        self.assertEqual(len([event for event in studio.progress_events if event.type == "MODEL_UPDATE"]), 1)
        self.assertFalse(model._steps)

    async def test_nested_model_streams_keep_namespace_and_hide_tool_arguments(self):
        request = self.request()
        studio = _context_from_request(request)
        received = []
        studio.progress_sink = received.append
        secret = "ARGUMENTS_MUST_NOT_BE_PROGRESS"
        child_text = "The audio plan is ready."
        model = StreamingModel([
            AIMessage(content="Delegating the audio plan.", id="same", tool_calls=call("task", {
                "subagent_type": "audio", "description": secret,
            }, "delegate").tool_calls),
            AIMessage(content=child_text, id="same"), final(),
        ])
        await run_with_servers(request, studio, [Gateway()], model=model)
        updates = [event for event in received if event.type == "MODEL_UPDATE"]
        self.assertTrue(any(event.status == "running" and event.message == child_text[:len(child_text) // 2]
                            for event in updates))
        completed = [event for event in updates if event.status == "completed"]
        self.assertEqual({event.message for event in completed},
                         {"Delegating the audio plan.", "The audio plan is ready."})
        self.assertEqual(len({event.id for event in completed}), 2)
        self.assertNotIn(secret, "\n".join(event.message for event in updates))

    async def test_internal_summaries_are_not_customer_progress(self):
        from deepagents import create_deep_agent
        from deepagents.middleware.summarization import SummarizationMiddleware

        _, previous, _ = await self.run_graph(self.request(), [final()])
        request = self.request(session_items=previous.session_items)
        studio = _context_from_request(request)
        received = []
        studio.progress_sink = received.append
        summary = ScriptedModel([AIMessage(content="INTERNAL SUMMARY MUST STAY PRIVATE")])

        def compact(**kwargs):
            kwargs["middleware"].append(SummarizationMiddleware(
                model=summary, backend=kwargs["backend"], trigger=("messages", 2), keep=("messages", 1),
            ))
            return create_deep_agent(**kwargs)

        with patch("agent.deep_agent.runner.create_deep_agent", side_effect=compact):
            await self.run_graph(request, [final()], studio=studio)
        self.assertFalse(summary._steps)
        self.assertNotIn("INTERNAL SUMMARY", "\n".join(event.message for event in received))

    async def test_existing_render_survives_fresh_worker_and_poll_uses_canonical_ids(self):
        render = Tool(name="Remotion___render_timeline", description="Start render",
                      inputSchema={"type": "object", "properties": {}})
        poll = Tool(name="Remotion___get_render_progress", description="Poll render",
                    inputSchema={"type": "object", "properties": {
                        key: {"type": "string"} for key in ("render_id", "bucket_name", "output_key")},
                                 "required": ["render_id", "bucket_name"]})
        gateway = Gateway([render, poll], {"status": "queued", "render_id": "render-1",
                                          "bucket_name": "bucket-1", "output_key": "out.mp4"})
        _, studio, _ = await self.run_graph(self.request(autonomous=True), [
            call("read_file", {"file_path": "/skills/final-assembly/SKILL.md"}, "skill"),
            call("call_editor_tool", {"tool_name": render.name, "arguments": {}}, "render"), final(),
        ], gateway)
        gateway.call_tool.reset_mock()
        gateway.call_tool.return_value = {"status": "succeeded", "render_id": "render-1", "url": "https://cdn.example/out.mp4"}
        await self.run_graph(self.request(autonomous=True, session_items=studio.session_items), [
            call("call_editor_tool", {"tool_name": render.name, "arguments": {}}, "replacement"),
            call("call_editor_tool", {"tool_name": poll.name, "arguments": {
                "render_id": "render-1", "bucket_name": "mistyped", "output_key": "mistyped"}}, "poll"), final(),
        ], gateway)
        gateway.call_tool.assert_awaited_once_with(poll.name, {
            "render_id": "render-1", "bucket_name": "bucket-1", "output_key": "out.mp4"})

    async def test_backend_and_provider_configuration(self):
        from agent.backend_config import agent_backend, agent_configured, deep_agent_model
        with patch.dict(os.environ, {"RENDERHAUS_AGENT_BACKEND": "deepagents", "RENDERHAUS_AGENT_MODEL": "anthropic:test",
                                     "ANTHROPIC_API_KEY": "test-only"}):
            self.assertEqual(agent_backend(), "deepagents")
            self.assertEqual(deep_agent_model(), "anthropic:test")
            self.assertTrue(agent_configured())
        with patch.dict(os.environ, {"RENDERHAUS_AGENT_MODEL": "  ", "AGENT_MODEL": "  "}):
            self.assertEqual(deep_agent_model(), "openai:gpt-5.6-luna")
        with patch.dict(os.environ, {"RENDERHAUS_AGENT_BACKEND": "invalid"}):
            with self.assertRaises(ValueError):
                agent_backend()

    async def test_new_paid_providers_dispatch_through_media_role_with_approval(self):
        for name in ("Kling___text_to_video", "Runway___video_to_video", "Fal___text_to_video", "Luma___modify_video"):
            with self.subTest(tool=name):
                tool = Tool(name=name, description="Paid video", inputSchema=IMAGE.input_schema)
                request = self.request().model_copy(update={"prompt": name.split("___")[0] + " video"})
                studio = _context_from_request(request)
                gateway = Gateway(tools=[tool], result={"status": "queued", "job_id": "job-1"})
                media = call("call_media_tool", {"tool_name": name, "arguments": {"prompt": "Hero"}}, "paid")
                with self.assertRaises(StudioAgentApprovalRequired) as paused:
                    await run_with_servers(request, studio, [gateway], model=ScriptedModel([read_skill(), media]))
                self.assertEqual(paused.exception.approvals[0].tool_name, name)
                gateway.call_tool.assert_not_awaited()
                approval = paused.exception.approvals[0]
                resumed = request.model_copy(update={"session_items": studio.session_items, "resume_state": paused.exception.state,
                                       "approval_decisions": [StudioApprovalDecision(call_id=approval.call_id, decision="approve")]})
                await self.run_graph(resumed, [final()], gateway)
                gateway.call_tool.assert_awaited_once_with(name, {"prompt": "Hero"})

    async def test_nle_export_is_free_editor_dispatch_without_approval(self):
        tool = Tool(name="Remotion___export_nle_timeline", description="Export NLE handoff",
                    inputSchema={"type": "object", "properties": {"timeline_json": {"type": "string"}},
                                 "required": ["timeline_json"], "additionalProperties": False})
        gateway = Gateway(tools=[tool], result={"status": "succeeded", "filename": "handoff.zip"})
        export = call("call_editor_tool", {"tool_name": tool.name, "arguments": {"timeline_json": "{}"}}, "export")
        read = call("read_file", {"file_path": "/skills/final-assembly/SKILL.md"}, "skill")
        await self.run_graph(self.request(), [read, export, final()], gateway)
        gateway.call_tool.assert_awaited_once_with(tool.name, {"timeline_json": "{}"})
