from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.deep_agent.routing import filter_request_tools, route_intent


class KnowledgeExplainerRoutingTests(unittest.TestCase):
    def test_silent_explainer_selects_renderer_before_audio_or_generated_video(self):
        for prompt in [
            "make a silent explainer video about probability",
            "make an explainer video with no narration and sound effects synced to events",
            "no voiceover graphic science explainer with event foley",
            "graphic explainer with sound effects synced to on-screen events",
            "export a silent knowledge explainer as an MP4",
            "make a knowledge-explainer about the control illusion",
            "make a narration-free knowledge short",
            "make a silent graphic explainer with on-screen text \"Narration is optional\"",
            "make an explainer about probability with sound effects synced, no narration",
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual((route.skill, route.alias, route.tool, route.status),
                                 ("knowledge-explainer", "remotion_render", "Remotion___render_timeline", "ready"))
                self.assertFalse(route.steps)

    def test_explicit_hyperframes_keeps_knowledge_skill_and_feature_gate(self):
        prompt = "HyperFrames silent science explainer with event foley only"
        with patch.dict(os.environ, {"HYPERFRAMES_ENABLED": "true", "HYPERFRAMES_DRY_RUN": "true"}):
            route = route_intent(prompt)
            self.assertEqual((route.skill, route.alias, route.tool),
                             ("knowledge-explainer", "hyperframes_render", "HyperFrames___render_composition"))
            self.assertIn("explicit HyperFrames request", route.disclosure)
        with patch.dict(os.environ, {"HYPERFRAMES_ENABLED": "false"}):
            route = route_intent(prompt)
            self.assertEqual((route.skill, route.status, route.tool), ("knowledge-explainer", "blocked", None))
            self.assertIn("disabled", route.reason)

    def test_missing_requested_renderer_is_blocked_without_substitution(self):
        with patch.dict(os.environ, {"HYPERFRAMES_ENABLED": "true"}):
            route = route_intent("HyperFrames silent science explainer", available_tools={"Remotion___render_timeline"})
        self.assertEqual((route.skill, route.status, route.tool), ("knowledge-explainer", "blocked", None))

    def test_whiteboard_voiceover_remains_a_narrated_whiteboard_workflow(self):
        for prompt in ["whiteboard explainer with voiceover narration",
                       "whiteboard explainer with voiceover and sound effects synced to drawing",
                       "whiteboard explainer with voice-over and event foley",
                       "whiteboard explainer with voice over"]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual((route.skill, route.alias, route.tool),
                                 ("whiteboard-explainer", "eleven_v4_turbo", "ElevenLabs___text_to_speech_convert"))

    def test_silent_whiteboard_is_knowledge_and_plain_whiteboard_is_preserved(self):
        self.assertEqual(route_intent("whiteboard explainer with no narration and event foley only").skill,
                         "knowledge-explainer")
        self.assertEqual(route_intent("draw and explain this concept as whiteboard video").skill,
                         "whiteboard-explainer")

    def test_narrated_explainers_are_not_silent_workflows(self):
        for prompt in [
            "whiteboard explainer with voiceover and event foley",
            "make a science explainer video about silent neurons with narration",
            'whiteboard explainer titled "No narration" with voiceover',
            "make a knowledge-explainer with voiceover narration",
        ]:
            with self.subTest(prompt=prompt):
                self.assertNotEqual(route_intent(prompt).skill, "knowledge-explainer")
                self.assertIn("ElevenLabs___text_to_speech_convert", filter_request_tools(
                    prompt, {"ElevenLabs___text_to_speech_convert"}))

    def test_audio_postprocessing_keeps_the_sfx_route(self):
        route = route_intent("add foley to this existing silent knowledge explainer",
                             arguments={"video_url": "https://example.invalid/silent.mp4"})
        self.assertEqual((route.skill, route.alias, route.tool),
                         ("audio-bed", "mirelo_v2a", "Fal___mirelo_v2a"))

    def test_no_narration_blocks_tts_but_allows_graphic_assets_and_sfx(self):
        allowed = {"OpenAI___generate_image", "Fal___mirelo_v2a", "ElevenLabs___text_to_sound_effects_convert"}
        speech = {"ElevenLabs___text_to_speech_convert", "ElevenLabs___text_to_speech_convert_with_timestamps",
                  "ElevenLabs___text_to_dialogue_convert", "FishAudio___generate_speech"}
        prompt = "make a silent graphic explainer video with no narration and synced sound effects"
        self.assertEqual(filter_request_tools(prompt, allowed | speech), allowed)
        self.assertEqual(filter_request_tools("whiteboard explainer with voiceover narration", speech), speech)

    def test_sfx_requests_remain_on_audio_bed_and_choose_by_input(self):
        for prompt, arguments, alias, tool in [
            ("add foley from this silent clip", {"video_url": "https://example.invalid/silent.mp4"},
             "mirelo_v2a", "Fal___mirelo_v2a"),
            ("a whoosh sound effect, 2 seconds", None, "elevenlabs_sfx_v2", "ElevenLabs___text_to_sound_effects_convert"),
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt, arguments=arguments)
                self.assertEqual((route.skill, route.alias, route.tool), ("audio-bed", alias, tool))

    def test_confidential_metadata_and_price_words_do_not_change_renderer(self):
        for tier in [None, "draft", "premium"]:
            for confidential in [False, True]:
                route = route_intent("cheapest silent knowledge explainer", tier=tier, confidential=confidential)
                self.assertEqual((route.skill, route.alias), ("knowledge-explainer", "remotion_render"))


class KnowledgeExplainerTemplateTests(unittest.TestCase):
    def test_planned_cues_attach_to_the_same_events_in_the_native_timeline(self):
        from providers.remotion.api import build_timeline_props

        path = Path(__file__).resolve().parents[1] / "agent/deep_agent/skills/knowledge-explainer/templates/silent-graphic.json"
        self.assertTrue(path.is_file(), "The silent graphic template must ship with its skill.")
        template = json.loads(path.read_text())
        arguments = template["arguments"]
        self.assertEqual(arguments["audio_tracks"], [])
        events = template["events"]
        tracks = [{"url": f"renderhaus-asset://offline-{event['event_id']}",
                   "start_seconds": event["start_seconds"], "duration_seconds": event["sfx"]["duration_seconds"],
                   "source_in_seconds": 0, "volume": 0.5} for event in events]
        props = build_timeline_props(**{**arguments, "audio_tracks": tracks}, measure_local=False)
        document = props["document"]
        audio = [track["items"][0] for track in document["tracks"] if track["kind"] == "audio"]
        self.assertEqual([(cue["start"], cue["duration"]) for cue in audio], [(1.25, 0.5), (3, 1)])
        labels = next(track["items"] for track in document["tracks"] if track["id"] == "titles-1")
        self.assertEqual([label["start"] for label in labels], [1.25, 3])
        self.assertEqual(props["renderConfig"]["durationInFrames"], 192)


class KnowledgeExplainerApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_speech_dispatch_is_blocked_before_approval_or_provider_access(self):
        from mcp import Tool

        from agent.gateway_executor import GatewayExecutor
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request
        from test_deep_agent import Gateway

        request = StudioAgentRequest(prompt="make a silent graphic explainer video with no narration", job_id="silent")
        gateway = Gateway([Tool(name="ElevenLabs___text_to_speech_convert", inputSchema={"type": "object"})])
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"RENDERHAUS_OUTCOME_DIR": directory}):
            executor = GatewayExecutor(_context_from_request(request), [gateway])
            self.assertNotIn("ElevenLabs___text_to_speech_convert", await executor.available())
            result = await executor.execute({"tool_name": "ElevenLabs___text_to_speech_convert",
                "arguments": {"text": "Forbidden narration", "voice_id": "offline-voice"}, "call_id": "tts"})
        self.assertEqual(result["status"], "not_run")
        self.assertIn("narration/TTS is excluded", result["reason"])
        self.assertEqual(executor.cost_ledger, {})
        gateway.call_tool.assert_not_awaited()

    async def test_silent_skill_loads_and_mirelo_rejection_resumes_without_paid_submission(self):
        from langchain_core.messages import ToolMessage
        from mcp import Tool

        from agent.deep_agent.runner import run_with_servers
        from agent.studio_agent_next import (
            StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, _context_from_request,
        )
        from test_deep_agent import Gateway, ScriptedModel, call, final

        root = Path(__file__).resolve().parents[1]
        schema = next(row for row in json.loads((root / "configs/gateway/fal.tools.json").read_text())
                      if row["name"] == "mirelo_v2a")
        gateway = Gateway([Tool(name="Fal___mirelo_v2a", description=schema["description"], inputSchema=schema["inputSchema"])])
        request = StudioAgentRequest(prompt="make a silent graphic explainer video with synced sound effects",
                                     autonomous=True, job_id="knowledge-sfx", workspace_id="workspace", project_id="project")
        studio = _context_from_request(request)
        model = ScriptedModel([
            call("read_file", {"file_path": "/skills/knowledge-explainer/SKILL.md", "limit": 1000}, "skill"),
            call("read_studio_context", {}, "context"),
            call("call_media_tool", {"tool_name": "Fal___mirelo_v2a", "arguments": {
                "video_url": "https://media.example.com/silent.mp4", "duration": 8, "num_samples": 1}}, "sfx"),
        ])
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "RENDERHAUS_OUTCOME_DIR": directory, "FAL_DRY_RUN": "true", "RENDERHAUS_PREMIUM_VIDEO_APPROVAL": "true",
        }):
            with self.assertRaises(StudioAgentApprovalRequired) as paused:
                await run_with_servers(request, studio, [gateway], model=model)
            messages = model._seen[-1][0]
            skill = next(message for message in messages if isinstance(message, ToolMessage) and message.tool_call_id == "skill")
            self.assertIn("Plan the event timeline", skill.content)
            context = next(json.loads(message.content) for message in messages
                           if isinstance(message, ToolMessage) and message.name == "read_studio_context")
            self.assertEqual(context["intent_route"]["skill"], "knowledge-explainer")
            self.assertEqual(context["intent_route"]["tool"], "Remotion___render_timeline")
            approval = paused.exception.approvals[0]
            self.assertIn("Estimated cost $", approval.description)
            self.assertIn("mirelo-ai/sfx1.6/video-to-video", approval.description)
            gateway.call_tool.assert_not_awaited()
            resumed = request.model_copy(update={"session_items": studio.session_items,
                "resume_state": paused.exception.state, "approval_decisions": [
                    StudioApprovalDecision(call_id=approval.call_id, decision="reject")]})
            await run_with_servers(resumed, _context_from_request(resumed), [gateway], model=ScriptedModel([final()]))
            gateway.call_tool.assert_not_awaited()
            row = json.loads((Path(directory) / "outcomes.jsonl").read_text().splitlines()[-1])
            self.assertEqual((row["provider"], row["outcome"], row["stage"]), ("fal", "rejected", "approval"))
