from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp import Tool

from agent.codex_harness import ToolApprovalPending
from agent.deep_agent.outcomes import OutcomeStore
from agent.deep_agent.runner import run_with_servers
from agent.gateway_executor import GatewayExecutor, tool_needs_approval
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, _context_from_request,
)
from test_deep_agent import Gateway, ScriptedModel, call, final


class CapabilityApprovalTests(unittest.TestCase):
    def test_all_paid_video_requires_approval_in_autonomous_runs(self):
        for name in (
            "Seedance___text_to_video", "Seedance___image_to_video",
            "Fal___text_to_video", "Fal___video_to_video", "Fal___vidu_q4_i2v",
            "Fal___vidu_q4_r2v", "Kling___text_to_video", "Runway___video_to_video",
            "Luma___extend_video", "Remotion___render_timeline",
            "wan3_t2v", "wan3_edit", "sync3_lipsync", "heygen_avatar_v",
            "runway_act_two", "kling_motion_control", "topaz_upscale", "topaz_interpolate",
        ):
            with self.subTest(name=name):
                self.assertTrue(tool_needs_approval(name, autonomous=True))
        with patch.dict(os.environ, {"RENDERHAUS_PREMIUM_VIDEO_APPROVAL": "false"}):
            self.assertFalse(tool_needs_approval("Seedance___text_to_video", autonomous=True))
            self.assertTrue(tool_needs_approval("Seedance___text_to_video", autonomous=False))

    def test_nonvideo_and_exempt_behavior_is_preserved(self):
        self.assertFalse(tool_needs_approval("ElevenLabs___text_to_speech_convert", True))
        self.assertTrue(tool_needs_approval("ElevenLabs___text_to_speech_convert", False))
        self.assertTrue(tool_needs_approval("ElevenLabs___voices_ivc_create", True))
        for autonomous in (False, True):
            self.assertFalse(tool_needs_approval("Remotion___export_nle_timeline", autonomous))
        self.assertFalse(tool_needs_approval("Fal___get_video_task", True))


class CapabilityExecutorTests(unittest.IsolatedAsyncioTestCase):
    def executor(self, name, prompt, *, confidential=False):
        studio = _context_from_request(StudioAgentRequest(
            prompt=prompt, confidential=confidential, autonomous=True, job_id="policy-test",
        ))
        gateway = Gateway([Tool(name=name, inputSchema={"type": "object"})])
        return GatewayExecutor(studio, [gateway]), gateway

    async def test_autonomous_seedance_pauses_before_provider_work(self):
        name = "Seedance___text_to_video"
        executor, gateway = self.executor(name, "make a 5 second video with Seedance")
        with self.assertRaises(ToolApprovalPending):
            await executor.execute({"tool_name": name, "arguments": {"prompt": "forest"}, "call_id": "video"})
        gateway.call_tool.assert_not_awaited()
        event = executor.studio.progress_events[-1]
        self.assertEqual(event.type, "MODEL_UPDATE")
        self.assertIn("seedance", event.message.lower())
        self.assertIn("Estimated cost", event.message)
        self.assertIn("explicit request", event.message)

    async def test_paid_editor_dispatch_publishes_provider_model_and_cost(self):
        name = "Remotion___render_timeline"
        executor, _ = self.executor(name, "assemble a motion graphic")
        executor.disclose_selection(None, "render", name, {})
        event = executor.studio.progress_events[-1]
        self.assertEqual(event.type, "MODEL_UPDATE")
        self.assertIn("remotion", event.message.lower())
        self.assertIn("Estimated cost", event.message)
        self.assertIn("unknown", event.message.lower())
        self.assertIn("default", event.message)

    async def test_approved_confidential_calls_cannot_bypass_project_policy(self):
        refused = (
            ("Runway___text_to_video", "use Runway for a video"),
            ("Seedream___image_to_image", "edit this confidential image"),
            ("ElevenLabs___text_to_speech_convert", "make a voiceover"),
            ("ElevenLabs___music_compose", "compose music"),
            ("ElevenLabs___text_to_sound_effects_convert", "make sound effects"),
            ("UnknownProvider___generate_audio", "make audio"),
        )
        for name, prompt in refused:
            with self.subTest(name=name):
                executor, gateway = self.executor(name, prompt, confidential=True)
                result = await executor.execute({"tool_name": name, "arguments": {}, "call_id": "forbidden"}, approved=True)
                self.assertEqual(result["status"], "not_run")
                self.assertIn("confidential", result["reason"].lower())
                self.assertIn("flag", result["reason"].lower())
                gateway.call_tool.assert_not_awaited()

    async def test_confidential_still_is_pending_and_never_uses_image_provider(self):
        name = "Seedream___text_to_image"
        executor, gateway = self.executor(name, "generate a confidential still image", confidential=True)
        result = await executor.execute({"tool_name": name, "arguments": {}, "call_id": "still"}, approved=True)
        self.assertEqual(result["status"], "not_run")
        self.assertIn("provider pending: flux2_klein4b_t2i", result["reason"])
        gateway.call_tool.assert_not_awaited()


class CapabilityNativeInterruptTests(unittest.IsolatedAsyncioTestCase):
    async def test_autonomous_seedance_approval_resumes_once_in_fresh_worker(self):
        name = "Seedance___text_to_video"
        arguments = {"prompt": "forest"}
        request = StudioAgentRequest(prompt="make a 5 second video with Seedance", autonomous=True,
                                     workspace_id="workspace", project_id="project", job_id="native-approval",
                                     conversation_id="conversation")
        gateway = Gateway([Tool(name=name, inputSchema={"type": "object"})])
        studio = _context_from_request(request)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"RENDERHAUS_OUTCOME_DIR": directory}):
            with self.assertRaises(StudioAgentApprovalRequired) as paused:
                await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                    call("read_file", {"file_path": "/skills/t2v/SKILL.md"}, "skill"),
                    call("call_media_tool", {"tool_name": name, "arguments": arguments}, "video"),
                ]))
            gateway.call_tool.assert_not_awaited()
            approval = paused.exception.approvals[0]
            self.assertIn("Estimated cost", approval.description)
            self.assertIn("explicit request", approval.description)
            resumed = request.model_copy(update={
                "session_items": json.loads(json.dumps(studio.session_items)),
                "resume_state": paused.exception.state,
                "approval_decisions": [StudioApprovalDecision(call_id=approval.call_id, decision="approve")],
            })
            await run_with_servers(resumed, _context_from_request(resumed), [gateway], model=ScriptedModel([final()]))
            gateway.call_tool.assert_awaited_once_with(name, arguments)


class CapabilityOutcomeTests(unittest.TestCase):
    def test_optional_ab_arm_survives_record_and_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OutcomeStore(Path(directory))
            common = dict(event_id="trial", provider="seedance", model="seedance-1-5-pro-251215",
                          job_type="t2v", stage="review", outcome="accepted")
            row = store.record(**common, ab_arm="dialogue-exception")
            replayed = store.record(**common, ab_arm="different")
            self.assertEqual(row["ab_arm"], "dialogue-exception")
            self.assertEqual(replayed, row)
            self.assertFalse(row["training_eligible"])
            rows = [json.loads(line) for line in store.path.read_text().splitlines()]
            self.assertEqual(rows, [row])
            self.assertIsNone(store.record(**{**common, "event_id": "normal"})["ab_arm"])
