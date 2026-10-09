from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage
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
RENDER = Tool(name="Remotion___render_timeline", description="Assemble", inputSchema={"type": "object"})
VIDEO_ARGS = {"prompt": "A lighthouse", "duration": 5, "resolution": "1080p", "audio": False}
TTS_ARGS = {"voice_id": "authorized-voice", "text": "Every night, someone has to keep the light.",
            "model_id": "eleven_v4_turbo"}
FINAL = {"title": "Lighthouse", "summary": "The lighthouse shot is ready.",
         "markdown": "# Lighthouse\n\n## Costs\n\nVideo $1.00. Voiceover cost unknown. Total $1.00.",
         "filename": "lighthouse.md"}


def dispatch(tool, arguments, call_id):
    wrapper = "call_audio_tool" if tool == TTS else "call_editor_tool" if tool == RENDER else "call_media_tool"
    return call(wrapper, {"tool_name": tool.name, "arguments": arguments}, call_id)


class DeepAgentExecutionTests(unittest.IsolatedAsyncioTestCase):
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
