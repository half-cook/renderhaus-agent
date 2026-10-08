from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.deep_agent import routing
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, _context_from_request,
)
from test_deep_agent import Gateway, ScriptedModel, call, final


class LadderTests(unittest.TestCase):
    def select(self, job="t2v", **kwargs):
        return routing.select_provider(job, **kwargs)

    def test_finished_shots_default_to_standard_cheapest_known(self):
        route = self.select(arguments={"duration_seconds": 5, "resolution": "720p"})
        self.assertEqual((route.tier, route.tool), ("standard", "Seedance___text_to_video"))

    def test_capabilities_filter_before_tier_and_cost(self):
        self.assertEqual(self.select(required={"native_audio": True}).tool, "Seedance___text_to_video")
        self.assertEqual(self.select(required={"multi_shot": True}).tool, "Kling___text_to_video")
        self.assertEqual(self.select("i2v", required={"start_end_frame": True}).tool, "Kling___image_to_video")
        self.assertEqual(self.select(required={"max_resolution": 2160}).tool, "Kling___text_to_video")
        blocked = self.select(tier="draft", required={"native_audio": True})
        self.assertEqual(blocked.status, "blocked")
        self.assertIsNone(blocked.tool)
        self.assertEqual(self.select(provider="luma", arguments={"duration_seconds": 7}).status, "blocked")
        self.assertEqual(self.select(tier="draft", required={"duration_seconds": 60}).status, "blocked")

    def test_tiers_and_pending_premium(self):
        self.assertEqual(self.select(tier="draft").tool, "Fal___text_to_video")
        self.assertEqual(self.select(tier="premium").tool, "Kling___text_to_video")
        self.assertEqual(self.select(provider="veo").status, "blocked")

    def test_explicit_provider_wins_only_when_capable_and_allowed(self):
        self.assertEqual(self.select(provider="runway").tool, "Runway___text_to_video")
        self.assertEqual(self.select(provider="seedance", required={"start_end_frame": True}).status, "blocked")
        self.assertEqual(self.select(provider="runway", required={"max_resolution": 1080}).status, "blocked")
        with patch.dict(routing.POLICY["providers"]["kling"], {"allowed_regions": ["CA"]}):
            self.assertEqual(self.select(provider="kling", region="US").status, "blocked")

    def test_unknown_sorts_after_known_without_changing_dry_run_flags(self):
        with patch.dict(os.environ, {"KLING_DRY_RUN": "true"}):
            route = self.select(provider="kling")
            self.assertEqual(route.model, "kling-3.0")
            self.assertEqual(os.environ["KLING_DRY_RUN"], "true")
        route = self.select(provider="kling", model="kling-3.0-turbo")
        self.assertIsNone(route.estimated_cost["total_cents"])
        self.assertIn("unknown", route.disclosure.lower())

    def test_list_quotes_keep_billing_validation(self):
        for name, args in [
            ("Runway___video_to_video", {}),
            ("Luma___modify_video", {}),
            ("Kling___text_to_video", {"duration_seconds": 2}),
            ("Runway___text_to_video", {"duration_seconds": 99}),
        ]:
            with self.subTest(name=name, args=args):
                self.assertIsNone(routing.estimate_cost(name, args).total_cents)
                self.assertIsNone(routing.estimate_cost(name, args, list_price=True).total_cents)

    def test_resolution_domain_and_minimum_are_priced_at_supported_presets(self):
        self.assertEqual(self.select(provider="seedance", arguments={"resolution": "580p"}).status, "blocked")
        route = self.select(provider="seedance", required={"max_resolution": 580})
        self.assertEqual(route.estimated_cost["total_cents"],
                         routing.estimate_cost(route.tool, {"resolution": "720p"}, list_price=True).total_cents)
        image = self.select("image", provider="runway", required={"max_resolution": 1024})
        self.assertEqual(image.provider, "runway")
        self.assertEqual(image.estimated_cost["total_cents"],
                         routing.estimate_cost(image.tool, {"ratio": "1920:1080"}, list_price=True).total_cents)
        self.assertIsNone(self.select("image", provider="seedream", required={"max_resolution": 720}).estimated_cost["total_cents"])

    def test_published_quotes_match_pure_billing_calculations(self):
        from server.billing_rates import cost_for
        examples = [
            ("Kling___text_to_video", {"duration_seconds": 5, "generate_audio": True, "resolution": "1080p"}),
            ("Runway___text_to_video", {"duration_seconds": 5}),
            ("Runway___video_to_video", {"video_duration_seconds": 5}),
            ("Runway___text_to_image", {"ratio": "1920:1080"}),
            ("Luma___modify_video", {"source_duration_seconds": 5}),
            ("Fal___text_to_video", {"prompt": "Forest", "num_frames": 81}),
            ("Seedance___text_to_video", {"duration_seconds": 5}),
            ("Seedream___text_to_image", {"size": "1K"}),
        ]
        with patch.dict(os.environ, {key: "false" for key in ["KLING_DRY_RUN", "RUNWAY_DRY_RUN", "LUMA_DRY_RUN", "FAL_DRY_RUN"]}):
            for name, args in examples:
                with self.subTest(name=name):
                    provider, tool = routing.tool_parts(name)
                    args = {**args, "model": routing.effective_model(provider, tool, args)}
                    self.assertEqual(routing.estimate_cost(name, args, list_price=True).total_cents,
                                     cost_for(provider, tool, args).total_cents)

    def test_v2v_ladder_and_plate_preference(self):
        for tier, tool in [("draft", "Fal___video_to_video"), ("standard", "Luma___modify_video"),
                           ("premium", "Runway___video_to_video")]:
            self.assertEqual(self.select("v2v_edit", tier=tier).tool, tool)
        self.assertEqual(self.select("v2v_edit", faithful=True).tool, "Runway___video_to_video")
        self.assertEqual(routing.route_intent("edit multi-shot footage faithfully").tool, "Runway___video_to_video")

    def test_confidential_is_wan_only_and_never_escalates(self):
        for tier in ["draft", "standard", "premium"]:
            self.assertEqual(self.select(tier=tier, confidential=True).tool, "Fal___text_to_video")
        self.assertEqual(self.select(confidential=True, provider="runway").status, "blocked")
        self.assertEqual(self.select(confidential=True, required={"max_resolution": 1080}).status, "blocked")
        self.assertEqual(self.select(confidential=True, retry=True).tool, "Fal___text_to_video")
        self.assertEqual(self.select("image", confidential=True).status, "blocked")

    def test_reject_retry_keeps_features_and_uses_wan(self):
        self.assertEqual(self.select(tier="premium", retry=True).tool, "Fal___text_to_video")
        self.assertEqual(self.select(retry=True, required={"native_audio": True}).status, "blocked")

    def test_prompt_constraints_and_preview_tier(self):
        self.assertEqual(routing.route_intent("generate a video of a forest").tier, "standard")
        self.assertEqual(routing.route_intent("draft video of a forest").tool, "Fal___text_to_video")
        self.assertEqual(routing.route_intent("animate image with end frame at 1080p").tool, "Kling___image_to_video")
        self.assertEqual(routing.route_intent("Seedance video needs end frame").status, "blocked")
        self.assertEqual(routing.route_intent("confidential video with native audio").status, "blocked")

    def test_disclosure_contains_choice_tier_filters_cost_and_typical_speed(self):
        route = self.select(required={"multi_shot": True})
        for part in ["Kling", "kling-3.0", "standard", "multi_shot", "Estimated cost", "typical"]:
            self.assertIn(part, route.disclosure)

    def test_unpublished_settings_remain_unknown(self):
        for job, kwargs in [
            ("image", {"provider": "seedream", "arguments": {"size": "2K"}}),
            ("v2v_edit", {"provider": "runway", "arguments": {"video_duration_seconds": 5.5}}),
            ("t2v", {"provider": "fal", "arguments": {"resolution": "360p"}}),
            ("t2v", {"provider": "fal", "model": "fal-ai/wan-22-vace-fun-a14b"}),
            ("v2v_edit", {"provider": "luma", "arguments": {"source_duration_seconds": 7}}),
        ]:
            with self.subTest(kwargs=kwargs):
                route = self.select(job, **kwargs)
                self.assertIn("unknown", route.disclosure)
                self.assertIsNone(route.estimated_cost["total_cents"])

    def test_table_is_built_schema_and_inherits_restrictive_policy(self):
        from test_skill_routing import gateway_names
        rows = routing.capability_table()
        known = gateway_names()
        schemas = {path.stem.removesuffix(".tools"): {tool["name"]: tool["inputSchema"] for tool in json.loads(path.read_text())}
                   for path in Path("configs/gateway").glob("*.tools.json")}
        for row in rows:
            policy = routing.POLICY["providers"][row["provider"]]
            self.assertEqual(row["license"], policy["license"])
            self.assertEqual(row["allowed_regions"], policy["allowed_regions"])
            self.assertEqual(row["blocked_regions"], policy.get("blocked_regions", []))
            self.assertEqual(row["training_eligible"], policy["training_eligible"])
            self.assertTrue(set(row["tools"].values()) <= known)
            for variant, name in row["tools"].items():
                provider, tool = routing.tool_parts(name)
                self.assertTrue(set(row["controls"][variant]) <= set(schemas[provider][tool]["properties"]))
            self.assertFalse(row["jobs"]["lipsync"])
            self.assertFalse(row["jobs"]["upscale"])
        self.assertEqual(len(rows), 15)
        self.assertFalse(next(r for r in rows if r["provider"] == "seedance")["jobs"]["start_end_frame"])
