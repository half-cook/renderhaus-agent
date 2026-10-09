from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage
from mcp import Tool

from agent.deep_agent.runner import SESSION_TYPE, run_with_servers
from agent.studio_agent_next import (
    StudioAgentApprovalRequired,
    StudioAgentRequest,
    StudioApprovalDecision,
    _context_from_request,
)
from test_deep_agent import Gateway, ScriptedModel, call

VIDEO = Tool(name="Fal___generate_wan3_t2v", description="Generate video", inputSchema={"type": "object"})
POLL = Tool(name="Fal___get_video_task", description="Poll video", inputSchema={"type": "object"})
TTS = Tool(name="ElevenLabs___text_to_speech_convert", description="Narrate", inputSchema={"type": "object"})
VOICES = Tool(name="ElevenLabs___voices_search", description="Find a voice", inputSchema={"type": "object"})
RENDER = Tool(name="Remotion___render_timeline", description="Assemble", inputSchema={"type": "object"})
VIDEO_ARGS = {"prompt": "A lighthouse", "duration": 5, "resolution": "1080p", "audio": False}
TTS_ARGS = {"voice_id": "authorized-voice", "text": "Every night, someone has to keep the light.",
            "model_id": "eleven_v4_turbo"}
FINAL = {"title": "Lighthouse", "summary": "The lighthouse shot is ready.",
         "markdown": "# Lighthouse\n\n## Costs\n\nVideo $1.00. Voiceover cost unknown. Total $1.00.",
         "filename": "lighthouse.md"}


def dispatch(tool, arguments, call_id):
    wrapper = "call_audio_tool" if tool in (TTS, VOICES) else "call_editor_tool" if tool == RENDER else "call_media_tool"
    return call(wrapper, {"tool_name": tool.name, "arguments": arguments}, call_id)


class DeepAgentExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_subagent_approvals_dispatch_once_without_model_replay(self):
        await self.parallel_subagent_approvals()

    async def test_rejected_parallel_call_does_not_dispatch_approved_sibling_does(self):
        for rejected_tool in (VIDEO, VOICES):
            with self.subTest(rejected_tool=rejected_tool.name):
                await self.parallel_subagent_approvals(rejected_tool)

    async def parallel_subagent_approvals(self, rejected_tool=None):
        gateway = Gateway([VIDEO, VOICES])
        voice_args = {"search": "narrator"}
        tasks = AIMessage(content="", tool_calls=[
            call("task", {"subagent_type": "media", "description": "Generate the lighthouse"}, "media-task").tool_calls[0],
            call("task", {"subagent_type": "audio", "description": "Find a narrator"}, "audio-task").tool_calls[0],
        ])

        def propose(messages, tools):
            if "call_media_tool" in tools:
                return dispatch(VIDEO, VIDEO_ARGS, "wan-call")
            return dispatch(VOICES, voice_args, "voices-call")

        def completed(messages, tools):
            self.assertIsInstance(messages[-1], ToolMessage, "Approval resume re-invoked the subagent model before dispatch")
            expected_tool = VIDEO if "call_media_tool" in tools else VOICES
            expected_id = "wan-call" if expected_tool == VIDEO else "voices-call"
            self.assertEqual(messages[-1].tool_call_id, expected_id)
            if expected_tool == rejected_tool:
                self.assertEqual(messages[-1].status, "error")
                self.assertIn("Skip this call", messages[-1].text)
            return AIMessage(content="Task completed.")

        request = self.request()
        studio = _context_from_request(request)
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"RENDERHAUS_OUTCOME_DIR": directory}):
            with self.assertRaises(StudioAgentApprovalRequired) as paused:
                await run_with_servers(request, studio, [gateway], model=ScriptedModel([tasks, propose, propose]))
            approvals = paused.exception.approvals
            self.assertCountEqual([item.tool_name for item in approvals], [VIDEO.name, VOICES.name])
            gateway.call_tool.assert_not_awaited()
            resumed = request.model_copy(update={
                "session_items": json.loads(json.dumps(paused.exception.session_items)),
                "resume_state": paused.exception.state,
                "prior_tool_events": [event.public() for event in studio.tool_events],
                "approval_decisions": [StudioApprovalDecision(call_id=item.call_id,
                                       decision="reject" if item.tool_name == getattr(rejected_tool, "name", None) else "approve",
                                       message="Skip this call")
                                       for item in reversed(approvals)],
            })
            restored = _context_from_request(resumed)
            model = ScriptedModel([completed, completed, call("StudioAgentOutput", FINAL, "finish")])
            output = await run_with_servers(
                resumed, restored, [gateway], model=model,
            )
            self.assertEqual(output.title, FINAL["title"])
            self.assertFalse(model._steps)
            self.assertCountEqual([event.id for event in restored.tool_events], [item.call_id for item in approvals])
        self.assertCountEqual([(item.args[0], item.args[1]) for item in gateway.call_tool.await_args_list],
                              [(tool.name, args) for tool, args in ((VIDEO, VIDEO_ARGS), (VOICES, voice_args))
                               if tool != rejected_tool])

    async def test_serial_subagent_approvals_dispatch_once_or_report_rejection(self):
        for decision in ("approve", "reject"):
            with self.subTest(decision=decision):
                gateway = Gateway([VIDEO, VOICES])
                voice_args = {"search": "narrator"}

                def completed(messages, tools):
                    self.assertIsInstance(messages[-1], ToolMessage, "Serial resume replayed the proposed call")
                    self.assertEqual(messages[-1].tool_call_id,
                                     "wan-call" if "call_media_tool" in tools else "voices-call")
                    if decision == "reject":
                        self.assertEqual(messages[-1].status, "error")
                        self.assertIn("Skip this call", messages[-1].text)
                    return AIMessage(content="Task completed.")

                model = ScriptedModel([
                    call("task", {"subagent_type": "media", "description": "Generate the lighthouse"}, "media-task"),
                    dispatch(VIDEO, VIDEO_ARGS, "wan-call"), completed,
                    call("task", {"subagent_type": "audio", "description": "Find a narrator"}, "audio-task"),
                    dispatch(VOICES, voice_args, "voices-call"), completed,
                    call("StudioAgentOutput", FINAL, "finish"),
                ])
                request = self.request()
                batches = []
                with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"RENDERHAUS_OUTCOME_DIR": directory}):
                    for _ in range(3):
                        studio = _context_from_request(request)
                        try:
                            output = await run_with_servers(request, studio, [gateway], model=model)
                            break
                        except StudioAgentApprovalRequired as exc:
                            self.assertEqual(len(exc.approvals), 1)
                            approval = exc.approvals[0]
                            batches.append(approval.tool_name)
                            self.assertEqual(gateway.call_tool.await_count, len(batches) - 1 if decision == "approve" else 0)
                            request = request.model_copy(update={
                                "session_items": json.loads(json.dumps(exc.session_items)),
                                "resume_state": exc.state,
                                "prior_tool_events": [event.public() for event in exc.tool_events],
                                "approval_decisions": [StudioApprovalDecision(call_id=approval.call_id,
                                                       decision=decision, message="Skip this call")],
                            })
                    else:
                        self.fail("Serial approval calls were reissued instead of completing")
                self.assertEqual(output.title, FINAL["title"])
                self.assertEqual(batches, [VIDEO.name, VOICES.name])
                self.assertFalse(model._steps)
                self.assertCountEqual([(item.args[0], item.args[1]) for item in gateway.call_tool.await_args_list],
                                      [(VIDEO.name, VIDEO_ARGS), (VOICES.name, voice_args)] if decision == "approve" else [])

    async def drive(self, request, model, gateway):
        for _ in range(10):
            studio = _context_from_request(request)
            try:
                return await run_with_servers(request, studio, [gateway], model=model), studio
            except StudioAgentApprovalRequired as exc:
                request = request.model_copy(update={
                    "session_items": json.loads(json.dumps(studio.session_items)),
                    "resume_state": exc.state,
                    "prior_tool_events": [event.public() for event in studio.tool_events],
                    "approval_decisions": [StudioApprovalDecision(call_id=approval.call_id, decision="approve")
                                           for approval in exc.approvals],
                })
        self.fail("The scripted run did not finish after approval resumes.")

    def request(self):
        return StudioAgentRequest(prompt="Make a 5-second lighthouse shot with a one-line voiceover.",
                                  workspace_id="workspace", project_id="project", conversation_id="conversation",
                                  job_id="lighthouse", autonomous=False)

    async def test_independent_voiceover_dispatches_before_video_poll_completes(self):
        order = []
        gateway = Gateway([VIDEO, POLL, TTS])

        async def provider(name, arguments):
            if name == VIDEO.name:
                order.append("video_submitted")
                return {"status": "queued", "job_id": "alibaba/wan-3.0/text-to-video:job"}
            if name == TTS.name:
                order.append("voiceover_dispatched")
                return {"status": "succeeded", "audio_url": "https://example.test/voice.mp3"}
            self.assertEqual(name, POLL.name)
            await asyncio.sleep(0)
            order.append("video_poll_completed")
            return {"status": "succeeded", "job_id": arguments["job_id"],
                    "video_url": "https://example.test/video.mp4"}

        gateway.call_tool.side_effect = provider

        def plan(messages, tools):
            context = json.loads(messages[-1].text)
            groups = context["intent_route"].get("execution_groups", [])
            media = dispatch(VIDEO, VIDEO_ARGS, "video")
            audio = dispatch(TTS, TTS_ARGS, "audio")
            poll = dispatch(POLL, {"job_id": "alibaba/wan-3.0/text-to-video:job", "download": True}, "poll")
            together = any({"wan3_t2v", "eleven_v4_turbo"} <= set(group) for group in groups)
            if together and "parallel" in messages[0].text.lower():
                model._steps[:0] = [poll, call("StudioAgentOutput", FINAL, "finish")]
                return AIMessage(content="", tool_calls=[*media.tool_calls, *audio.tool_calls])
            model._steps[:0] = [poll, audio, call("StudioAgentOutput", FINAL, "finish")]
            return media

        model = ScriptedModel([call("read_studio_context", {}, "context"), plan])
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"RENDERHAUS_OUTCOME_DIR": directory}):
            await self.drive(self.request(), model, gateway)
        self.assertIn("video_submitted", order)
        self.assertLess(order.index("voiceover_dispatched"), order.index("video_poll_completed"), order)

    async def test_cost_summary_preserves_every_paid_step_across_approval_resumes(self):
        gateway = Gateway([VIDEO, TTS, RENDER])

        async def provider(name, arguments):
            if name == VIDEO.name:
                return {"status": "queued", "job_id": "alibaba/wan-3.0/text-to-video:job"}
            if name == TTS.name:
                return {"status": "succeeded", "audio_url": "https://example.test/voice.mp3"}
            self.assertEqual(name, RENDER.name)
            return {"status": "queued", "render_id": "render", "bucket_name": "local"}

        gateway.call_tool.side_effect = provider
        model = ScriptedModel([
            dispatch(VIDEO, VIDEO_ARGS, "video"), dispatch(TTS, TTS_ARGS, "audio"),
            dispatch(RENDER, {"visuals": []}, "render"), call("StudioAgentOutput", FINAL, "finish"),
        ])
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {
            "RENDERHAUS_OUTCOME_DIR": directory, "STRIPE_SECRET_KEY": "",
            "ELEVENLABS_TOOL_COST_CENTS_JSON": '{"text_to_speech_convert": 1}',
        }):
            output, studio = await self.drive(self.request(), model, gateway)
            persisted = next(item for item in studio.session_items if item["type"] == SESSION_TYPE)
            ledger = persisted.get("cost_ledger", {})
            self.assertEqual(len(ledger), 3)
            self.assertEqual(sorted(row["total_estimate_cents"] for row in ledger.values()
                                    if row["total_estimate_cents"] is not None), [2, 130])
            self.assertIn("$0.02", output.markdown)
            self.assertIn(TTS.name, output.markdown)
            self.assertIn(VIDEO.name, output.markdown)
            self.assertIn(RENDER.name, output.markdown)
            self.assertIn("$1.32", output.summary)
            self.assertIn("Voiceover $0.02", output.summary)
            self.assertIn("Video $1.30", output.summary)
            self.assertIn("Assembly unknown", output.summary)
            self.assertIn("unknown", output.summary.lower())
            self.assertNotIn("Voiceover cost unknown", output.markdown)
            self.assertEqual(output.markdown.count("## Estimated media costs"), 1)
            resumed = self.request().model_copy(update={
                "session_items": json.loads(json.dumps(studio.session_items)),
                "prior_tool_events": [event.public() for event in studio.tool_events],
            })
            repeated, repeated_studio = await self.drive(
                resumed, ScriptedModel([call("StudioAgentOutput", FINAL, "finish-again")]), gateway,
            )
            self.assertIn("$1.32", repeated.summary)
            self.assertEqual(repeated.markdown.count("## Estimated media costs"), 1)
            self.assertEqual(len(next(item for item in repeated_studio.session_items
                                      if item["type"] == SESSION_TYPE)["cost_ledger"]), 3)
        self.assertEqual(gateway.call_tool.await_count, 3)
