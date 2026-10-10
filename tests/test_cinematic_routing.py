from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from agent.deep_agent.routing import POLICY, is_free_tool, route_intent, tool_parts

ROOT = Path(__file__).resolve().parents[1]
SEARCH = "ShotRecipes___shot_recipe_search"
LAUNCH = "Make a 30-second cinematic Apple-style launch film for my note-taking app, with punchy beat-synced cuts"
NAMED = "Use the 'ink press' style shot card for the product reveal in my promo video"
WALKTHROUGH = "Record a quick walkthrough of my dashboard with captions, nothing fancy"


class CinematicRoutingTests(unittest.TestCase):
    def test_launch_searches_before_assembly_without_video_generation(self):
        route = route_intent(LAUNCH)
        self.assertEqual(route.skill, "cinematic-product-promo")
        self.assertEqual(route.status, "ready")
        self.assertEqual([step.alias for step in route.steps], ["shot_recipe_search", "remotion_render"])
        self.assertEqual(route.execution_groups, (("shot_recipe_search",), ("remotion_render",)))
        self.assertEqual(route.expected_output, "assembled MP4")
        self.assertEqual(route.required["target_duration_s"], 30)
        self.assertFalse({"wan3_t2v", "seedance25_t2v"} & {step.alias for step in route.steps})

    def test_user_named_card_is_required_for_the_reveal(self):
        route = route_intent(NAMED)
        self.assertEqual(route.skill, "cinematic-product-promo")
        self.assertEqual(route.alias, "shot_recipe_search")
        self.assertEqual(route.tool, SEARCH)
        self.assertEqual(route.required["card_id"], "brand-ink-open")
        self.assertEqual(route.required["beat"], "reveal")
        self.assertEqual(route.basis, "explicit named card")
        self.assertEqual(route.steps, ())

    def test_plain_walkthrough_stays_pending_on_capture_and_never_searches_cards(self):
        route = route_intent(WALKTHROUGH)
        self.assertEqual(route.skill, "product-demo-video")
        self.assertEqual(route.alias, "cutaway_record")
        self.assertEqual(route.status, "pending")
        self.assertIsNone(route.tool)
        self.assertNotIn("shot_recipe_search", {step.alias for step in route.steps} | {route.alias})

    def test_exact_named_card_without_generic_cinematic_words_still_wins(self):
        route = route_intent("Use brand-ink-open for the reveal")
        self.assertEqual(route.alias, "shot_recipe_search")
        self.assertEqual(route.required["card_id"], "brand-ink-open")
        self.assertEqual(route.required["beat"], "reveal")
        self.assertEqual(route.steps, ())

    def test_explicit_video_model_request_keeps_existing_generation_route(self):
        route = route_intent("Use Wan 3 for a cinematic product promo video")
        self.assertEqual(route.alias, "wan3_t2v")
        self.assertEqual(route.skill, "t2v")

    def test_other_authoring_workflows_keep_their_skill(self):
        cases = [
            ("Add a lower third to my product promo", "motion-graphics"),
            ("use an HTML template for the title card", "motion-graphics"),
            ("Make a HyperFrames cinematic product promo", "hyperframes"),
            ("Make a silent knowledge explainer about gravity", "knowledge-explainer"),
            ("Make a cinematic product promo video in Bauhaus style", "art-style-motion"),
            ("Render ad variants for a cinematic product promo", "remotion-ad-variant-matrix"),
        ]
        for prompt, skill in cases:
            with self.subTest(prompt=prompt), patch.dict("os.environ", {"HYPERFRAMES_ENABLED": "true"}):
                route = route_intent(prompt)
                self.assertEqual(route.skill, skill)
                self.assertNotIn("shot_recipe_search", {step.alias for step in route.steps} | {route.alias})

    def test_quoted_card_selection_survives_instruction_copy_masking(self):
        cases = [("Use 'crane reveal' for the opening beat in my promo video", 'crane-rise-reveal'),
                 ("Use 'brand-ink-open' for the intro beat", 'brand-ink-open'),
                 ("Use the 'ink press' shot card for the closing logo beat", 'brand-ink-open')]
        for prompt, card_id in cases:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.skill, 'cinematic-product-promo')
                self.assertEqual(route.required['card_id'], card_id)

    def test_launch_video_and_named_style_film_follow_the_skill_spec(self):
        for prompt in ('Make a cinematic launch video for my product', 'Apple-style product film'):
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.skill, 'cinematic-product-promo')
                self.assertEqual([step.alias for step in route.steps], ['shot_recipe_search', 'remotion_render'])

    def test_quoted_copy_is_not_a_named_card_instruction(self):
        route = route_intent("Make a cinematic launch film; use the headline 'ink press' as approved copy")
        self.assertEqual(route.skill, 'cinematic-product-promo')
        self.assertNotIn('card_id', route.required)
        self.assertEqual(len(route.steps), 2)

    def test_generic_search_terms_do_not_claim_a_user_named_card(self):
        for prompt in ('Make a cinematic launch film. Use a product card to show the dashboard',
                       'Make a cinematic product promo; use a chart reveal to show growth'):
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.skill, 'cinematic-product-promo')
                self.assertNotIn('card_id', route.required)
                self.assertEqual(len(route.steps), 2)

    def test_search_is_a_free_editor_utility_with_no_training_grant(self):
        from agent.deep_agent.runner import DISPATCH_TARGETS

        self.assertEqual(tool_parts(SEARCH), ("shot_recipes", "shot_recipe_search"))
        self.assertTrue(is_free_tool(SEARCH))
        self.assertIn("ShotRecipes", DISPATCH_TARGETS["call_editor_tool"])
        self.assertFalse(POLICY["model_policies"]["shot_recipe_search"]["training_eligible"])
        self.assertEqual(POLICY["capability_map"]["shot_recipes"]["default"], "shot_recipe_search")

    def test_missing_search_tool_blocks_the_assembled_route(self):
        route = route_intent(LAUNCH, available_tools={"Remotion___render_timeline"})
        self.assertEqual(route.alias, "shot_recipe_search")
        self.assertEqual(route.status, "blocked")
        self.assertIsNone(route.tool)
        self.assertIn("unavailable", route.reason)

    def test_cinematic_render_requires_motion_qc(self):
        from agent.deep_agent.motion_carry_gate import requires_motion_qc

        self.assertTrue(requires_motion_qc(LAUNCH, []))

    def test_skill_loads_with_neutral_description_and_real_editor_dispatch(self):
        from deepagents.middleware.skills import _parse_skill_metadata

        path = ROOT / "agent/deep_agent/skills/cinematic-product-promo/SKILL.md"
        body = path.read_text()
        self.assertIsNotNone(_parse_skill_metadata(body, str(path), path.parent.name))
        front = yaml.safe_load(body.split("---", 2)[1])
        self.assertEqual(front["name"], "cinematic-product-promo")
        for name in ("Apple", "Remotion", "Mixkit", "Mureka", "ElevenLabs", "$", "free", "cost", "fee"):
            self.assertNotIn(name.casefold(), front["description"].casefold())
        self.assertIn(SEARCH, front["metadata"]["gateway_tools"].split())
        self.assertIn("call_editor_tool", front["metadata"]["include_tools"].split())
        self.assertIn("validate_storyboard", body)
        self.assertIn("user-supplied", body)
        self.assertIn("empty", body)
        self.assertIn("-14 LUFS", body)
        self.assertIn("checksum", body)

    def test_workbook_rows_are_retained_and_capture_is_explicitly_pending(self):
        cases = json.loads((ROOT / "tests/fixtures/skill_routing.json").read_text())
        rows = {case["test_id"]: case for case in cases if case.get("test_id") in {"RT-174", "RT-175", "RT-176"}}
        self.assertEqual(set(rows), {"RT-174", "RT-175", "RT-176"})
        self.assertEqual(rows["RT-174"]["prompt"], LAUNCH)
        self.assertEqual(rows["RT-175"]["prompt"], NAMED)
        self.assertEqual(rows["RT-176"]["prompt"], WALKTHROUGH)
        self.assertEqual(rows["RT-174"]["skip_reason"], "")
        self.assertEqual(rows["RT-175"]["skip_reason"], "")
        self.assertEqual(rows["RT-176"]["skip_reason"], "provider pending: cutaway_record (feat/product-demo-capture)")


if __name__ == "__main__":
    unittest.main()
