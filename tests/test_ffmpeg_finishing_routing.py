from __future__ import annotations

import unittest

from agent.deep_agent.routing import estimate_cost, filter_request_tools, route_intent
from agent.gateway_executor import tool_needs_approval


class FinishingRoutingTests(unittest.TestCase):
    def test_local_finishing_requests_choose_the_existing_free_editor(self):
        cases = [
            ("burn these subtitles into the video", "remotion-delivery-render", "burn_subtitles"),
            ("export an SRT from these timed cues", "remotion-delivery-render", "export_srt"),
            ("match the colour of clip B to clip A with this LUT", "remotion-delivery-render", "color_match_lut"),
            ("Apply this .cube LUT to the clip.", "remotion-delivery-render", "color_match_lut"),
            ("clean up the noisy dialogue before loudness QC", "remotion-loudness-qc", "audio_cleanup"),
            ("make a small preview proxy to review", "remotion-delivery-render", "make_proxy"),
            ("make_proxy of the local master", "remotion-delivery-render", "make_proxy"),
        ]
        for prompt, skill, op in cases:
            for confidential in (False, True):
                with self.subTest(prompt=prompt, confidential=confidential):
                    route = route_intent(prompt, confidential=confidential)
                    self.assertEqual((route.skill, route.tool, route.status),
                                     (skill, "Ffmpeg___ffmpeg_tool", "ready"))
                    self.assertEqual(route.dispatch_tool, "call_editor_tool")
                    self.assertEqual(route.required["op"], op)
                    self.assertEqual(estimate_cost(route.tool, {}).total_cents, 0)
                    for autonomous in (False, True):
                        self.assertFalse(tool_needs_approval(route.tool, autonomous, {"op": op}))

    def test_missing_local_tool_blocks_finishing_without_paid_fallback(self):
        for prompt in ("burn these subtitles into the video", "apply this .cube LUT to the clip",
                       "clean up the noisy dialogue before loudness QC", "make a small preview proxy to review"):
            with self.subTest(prompt=prompt):
                route = route_intent(prompt, available_tools={"Remotion___render_timeline"})
                self.assertEqual(route.status, "blocked")
                self.assertIsNone(route.tool)

    def test_unsafe_and_resolve_requests_keep_their_refusals(self):
        for prompt in ("Run ffmpeg -i a.mp4 -vf subtitles=a.srt b.mp4",
                       "Use Resolve's Voice Isolation on this dialogue",
                       "Open my .drp project and apply this LUT",
                       "Use a free-form filtergraph to clean up the audio"):
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.status, "blocked")
                self.assertIsNone(route.tool)
                self.assertEqual(filter_request_tools(prompt, {"Ffmpeg___ffmpeg_tool"}), set())

    def test_generation_and_existing_delivery_routes_keep_their_tools(self):
        cases = [
            ("Generate a video ad with subtitles", "wan3_t2v"),
            ("Use Kling to generate a video with subtitles", "kling_t2v"),
            ("Export a review proxy of the cut for the client, small.", "delivery_render"),
            ("Make a 540p proxy of all clips.", "delivery_render"),
        ]
        for prompt, alias in cases:
            with self.subTest(prompt=prompt):
                self.assertEqual(route_intent(prompt).alias, alias)
