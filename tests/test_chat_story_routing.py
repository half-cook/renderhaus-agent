from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.deep_agent.routing import (
    filter_request_tools,
    request_tool_blocker,
    route_intent,
)
from agent.gateway_executor import tool_needs_approval


ROOT = Path(__file__).resolve().parents[1]
SINGLE = "Turn this 12-line breakup script into a fake text message video for TikTok"
BATCH = "Here's a CSV of 20 chat scripts, render one WhatsApp-style conversation video per row"
GENERATION = {
    "Fal___generate_wan3_t2v",
    "Fal___generate_wan3_i2v",
    "Fal___generate_wan3_r2v",
    "Seedance___text_to_video",
    "Seedance___image_to_video",
    "Seedance___reference_to_video",
    "Seedance___edit_video",
    "Seedance___extend_video",
    "Kling___text_to_video",
    "Runway___video_to_video",
    "Luma___modify_video",
    "Runway___act_two",
    "Fal___kling_motion_control",
    "Sync___lipsync_video",
    "HeyGen___create_avatar_video",
    "Mureka___generate_lyrics_video",
}


class ChatStoryRoutingTests(unittest.TestCase):
    def test_workbook_requests_use_chat_composition_without_generation(self):
        for prompt in (SINGLE, BATCH):
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.skill, "chat-story-video")
                self.assertEqual(route.alias, "remotion_render")
                self.assertEqual(route.tool, "Remotion___render_timeline")
                self.assertEqual(route.dispatch_tool, "call_editor_tool")
                self.assertEqual(route.status, "ready")
                self.assertFalse(GENERATION & {route.tool, *(step.tool for step in route.steps)})

    def test_explicit_thread_animation_wording_routes_to_chat(self):
        for prompt in (
            "Make a fake text message video from this script",
            "Animate this SMS conversation into a 9:16 short",
            "Render a chat thread to a video",
            "Create a text-story video from my messages table",
            "Make a chat story short with typing indicator reveals",
            "Animate this WhatsApp conversation from these messages",
        ):
            with self.subTest(prompt=prompt):
                self.assertEqual(route_intent(prompt).skill, "chat-story-video")

    def test_thread_with_voiceover_still_uses_chat_composition(self):
        route = route_intent("Make a fake text message video with a voiceover reading the thread")
        self.assertEqual(route.skill, "chat-story-video")
        self.assertEqual(route.tool, "Remotion___render_timeline")
        self.assertFalse(GENERATION & {route.tool, *(step.tool for step in route.steps)})

    def test_disabled_lookalike_request_discloses_generic_theme(self):
        with patch.dict("os.environ", {"CHAT_STORY_LOOKALIKE_THEMES": "off"}):
            route = route_intent(BATCH)
        self.assertEqual(route.required["theme"], "generic")
        self.assertIn("lookalike themes are not enabled", route.disclosure)
        self.assertIn("generic", route.disclosure)
        self.assertNotIn("WhatsApp", route.disclosure)
        self.assertNotIn("iMessage", route.disclosure)

    def test_unrelated_requests_retain_their_routes(self):
        cases = (
            ("Cut filler words from this real talking-head clip; it mentions a text message.", "conversational-edit"),
            ("Render ad-variant matrix per-market copy swaps from this finished ad; its headline mentions text message.", "remotion-ad-variant-matrix"),
            ("Add a generic lower third to this interview; its caption mentions text message.", "motion-graphics"),
            ("Make a video of a mountain sunrise; the brief mentions text message.", "t2v"),
            ("Create a still image poster about a text message conversation.", "image-gen"),
            ('Animate this product image; its caption says "create a chat story video".', "motion-graphics"),
        )
        for prompt, skill in cases:
            with self.subTest(prompt=prompt):
                self.assertEqual(route_intent(prompt).skill, skill)
                self.assertIsNone(request_tool_blocker(prompt, "Fal___generate_wan3_t2v"))

    def test_enabled_neutral_preset_still_requires_an_explicit_request(self):
        with patch.dict("os.environ", {"CHAT_STORY_LOOKALIKE_THEMES": "on"}):
            self.assertEqual(route_intent(SINGLE).required["theme"], "generic")
            self.assertEqual(route_intent(BATCH).required["theme"], "moss")
            self.assertEqual(route_intent("Animate this iMessage conversation from these messages").required["theme"], "slate")

    def test_negated_chat_instruction_does_not_select_chat(self):
        prompt = "Create a still image of a mountain. Do not render a chat story video."
        self.assertEqual(route_intent(prompt).skill, "image-gen")
        self.assertIsNone(request_tool_blocker(prompt, "Fal___generate_wan3_t2v"))

    def test_generation_is_refused_at_discovery_and_dispatch_boundaries(self):
        allowed = {"Remotion___render_timeline", "Remotion___render_ad_variants", "Ffmpeg___ffmpeg_tool",
                   "Fal___get_video_task", "ElevenLabs___text_to_speech_convert",
                   "ElevenLabs___text_to_sound_effects_convert"}
        self.assertEqual(filter_request_tools(SINGLE, GENERATION | allowed), allowed)
        for name in GENERATION:
            with self.subTest(tool=name):
                self.assertIn("chat thread", request_tool_blocker(SINGLE, name))
                self.assertIn("chat thread", request_tool_blocker(BATCH, name))

    def test_batch_uses_existing_host_approval_in_autonomous_runs(self):
        for autonomous in (False, True):
            self.assertTrue(tool_needs_approval("Remotion___render_timeline", autonomous))
            for stage, expected in (("plan", False), ("render_first", True), ("render_batch", True)):
                with self.subTest(autonomous=autonomous, stage=stage):
                    self.assertEqual(tool_needs_approval("Remotion___render_ad_variants", autonomous,
                                                         {"stage": stage, "brief": {"mode": "chat_story"}}), expected)

    def test_workbook_rows_are_active_and_forbid_video_generation(self):
        rows = json.loads((ROOT / "tests/fixtures/skill_routing.json").read_text())
        for row_id, prompt in (("RT-180", SINGLE), ("RT-181", BATCH)):
            with self.subTest(row=row_id):
                matches = [row for row in rows if row.get("test_id") == row_id]
                self.assertEqual(len(matches), 1)
                row = matches[0]
                self.assertEqual(row["prompt"], prompt)
                self.assertEqual(row["skip_reason"], "")
                self.assertEqual(row["expected_skill"], "chat-story-video")
                self.assertEqual(row["expected_tool"], "remotion_render")
                self.assertIn("wan3_t2v", row["forbidden_tools"])


if __name__ == "__main__":
    unittest.main()
