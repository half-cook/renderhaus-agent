from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from agent.gateway_executor import tool_needs_approval


class PolicyTests(unittest.TestCase):
    def test_premium_video_approval_is_required_in_autonomous_runs(self):
        for name in ["Kling___text_to_video", "Runway___image_to_video", "Runway___video_to_video"]:
            self.assertTrue(tool_needs_approval(name, True), name)
        self.assertFalse(tool_needs_approval("Fal___text_to_video", True))
        with patch.dict(os.environ, {"RENDERHAUS_PREMIUM_VIDEO_APPROVAL": "false"}):
            self.assertFalse(tool_needs_approval("Kling___text_to_video", True))
            self.assertTrue(tool_needs_approval("Kling___text_to_video", False))

    def test_reads_never_trigger_premium_approval_and_keep_non_autonomous_behavior(self):
        for name in [
            "Kling___get_video_task",
            "Runway___list_runway_models",
            "Fal___get_video_task",
            "Remotion___export_nle_timeline",
        ]:
            self.assertEqual(
                tool_needs_approval(name, False), name != "Remotion___export_nle_timeline"
            )
            self.assertFalse(tool_needs_approval(name, True))

    def test_unknown_price_is_not_a_dry_run_zero(self):
        from agent.deep_agent.routing import estimate_cost

        for name, args in [
            ("Kling___text_to_video", {"model": "kling-3.0-turbo"}),
            ("Remotion___render_timeline", {}),
            ("Seedream___text_to_image", {"size": "2K"}),
            ("Fal___text_to_video", {"prompt": "forest", "model": "fal-ai/wan-22-vace-fun-a14b"}),
        ]:
            quote = estimate_cost(name, args)
            self.assertIsNone(quote.total_cents, name)
            self.assertIn("unknown", quote.description.lower())
        self.assertEqual(estimate_cost("Fal___get_video_task", {}).total_cents, 0)

    def test_quotes_use_billing_rates(self):
        from agent.deep_agent.routing import estimate_cost
        from server.billing_rates import cost_for

        with patch.dict(os.environ, {"KLING_DRY_RUN": "false", "RUNWAY_DRY_RUN": "false"}):
            for name, provider, args in [
                ("Kling___text_to_video", "kling", {"duration_seconds": 5}),
                ("Runway___text_to_video", "runway", {"duration_seconds": 5}),
            ]:
                quote = estimate_cost(name, args)
                self.assertEqual(
                    quote.total_cents, cost_for(provider, "text_to_video", args).total_cents
                )
                self.assertIn(f"${quote.total_cents / 100:.2f}", quote.description)

    def test_training_requires_wan_apache_provenance(self):
        from agent.deep_agent.routing import training_eligible

        asset = {
            "provider": "fal",
            "model": "fal-ai/wan-vace-14b",
            "weights_license": "Apache-2.0",
            "training_eligible": True,
            "status": "succeeded",
        }
        self.assertTrue(training_eligible(asset))
        for provider in [
            "kling",
            "runway",
            "luma",
            "seedance",
            "seedream",
            "veo",
            "minimax_h3",
            "hunyuan",
        ]:
            self.assertFalse(training_eligible({**asset, "provider": provider}))
        for changed in [
            {"weights_license": "MIT"},
            {"model": "not-wan"},
            {"model": []},
            {"model": {}},
            {"training_eligible": False},
            {"dry_run": True},
            {"status": "queued"},
            {"status": "failed"},
        ]:
            self.assertFalse(training_eligible({**asset, **changed}))
        self.assertFalse(
            training_eligible({"training_eligible": True, "weights_license": "Apache-2.0"})
        )

    def test_region_and_model_gates(self):
        from agent.deep_agent.routing import policy_blocker, POLICY

        self.assertIsNotNone(policy_blocker("MiniMaxH3___text_to_video", {}, region="US"))
        self.assertIsNotNone(policy_blocker("Hunyuan___text_to_video", {}, region="CA"))
        self.assertIsNotNone(policy_blocker("Fal___text_to_video", {"model": "minimax-h3"}))
        with patch.dict(POLICY["providers"]["kling"], {"allowed_regions": ["CA"]}):
            self.assertIsNone(policy_blocker("Kling___text_to_video", {}, region="CA"))
            self.assertIsNotNone(policy_blocker("Kling___text_to_video", {}, region="US"))
            self.assertIsNotNone(policy_blocker("Kling___text_to_video", {}, region=None))

    def test_env_models_and_unknown_models_cannot_bypass_gates(self):
        from agent.deep_agent.routing import policy_blocker

        for target, key in [
            ("Kling", "KLING_MODEL"),
            ("Seedance", "SEEDANCE_MODEL"),
            ("Seedream", "SEEDREAM_MODEL"),
            ("FishAudio", "FISH_AUDIO_MODEL"),
        ]:
            name = (
                f"{target}___text_to_video"
                if target != "FishAudio"
                else f"{target}___generate_speech"
            )
            with self.subTest(target=target), patch.dict(os.environ, {key: "hunyuan"}):
                self.assertIsNotNone(policy_blocker(name, {}))
                self.assertIsNotNone(policy_blocker(name, {"model": "minimax-h3"}))

    def test_model_specific_licence_and_region_gates(self):
        from agent.deep_agent.routing import policy_blocker, training_eligible, POLICY

        model = POLICY["providers"]["fal"]["model_policies"]["fal-ai/wan-vace-14b"]
        with patch.dict(model, {"license": "non-commercial"}):
            self.assertIsNotNone(policy_blocker("Fal___text_to_video", {}))
            self.assertFalse(
                training_eligible(
                    {
                        "provider": "fal",
                        "model": "fal-ai/wan-vace-14b",
                        "status": "succeeded",
                        "weights_license": "Apache-2.0",
                        "training_eligible": True,
                    }
                )
            )
        with patch.dict(model, {"allowed_regions": ["CA"]}):
            self.assertIsNone(policy_blocker("Fal___text_to_video", {}, region="CA"))
            self.assertIsNotNone(policy_blocker("Fal___text_to_video", {}, region="US"))

    def test_fish_env_model_quote_matches_effective_provider_model(self):
        from agent.deep_agent.routing import estimate_cost
        from server.billing_rates import cost_for

        with patch.dict(os.environ, {"FISH_AUDIO_MODEL": "s2.1-pro"}):
            args = {"text": "a" * 10000}
            self.assertEqual(
                estimate_cost("FishAudio___generate_speech", args).total_cents,
                cost_for(
                    "fish_audio", "generate_speech", {**args, "model": "s2.1-pro"}
                ).total_cents,
            )

    def test_invalid_operator_quotes_remain_unknown_without_stripe(self):
        from agent.deep_agent.routing import estimate_cost

        for quote in ["unconfirmed", True, -1, None]:
            import json

            with (
                self.subTest(quote=quote),
                patch.dict(
                    os.environ,
                    {
                        "STRIPE_SECRET_KEY": "",
                        "ELEVENLABS_TOOL_COST_CENTS_JSON": json.dumps(
                            {"text_to_speech_convert": quote}
                        ),
                    },
                ),
            ):
                self.assertIsNone(
                    estimate_cost("ElevenLabs___text_to_speech_convert", {}).total_cents
                )


class LumaPolicyTests(unittest.TestCase):
    def test_luma_routes_to_real_gateway_tools(self):
        from agent.deep_agent.routing import route_intent

        modify = route_intent("change look keep performance Luma")
        self.assertEqual((modify.skill, modify.tool, modify.status), ("edit-v2v", "Luma___modify_video", "ready"))
        t2v = route_intent("Luma Ray text to video of a beach at dawn")
        self.assertEqual((t2v.skill, t2v.tool, t2v.status), ("t2v", "Luma___text_to_video", "ready"))
        i2v = route_intent("luma image to video from this start frame")
        self.assertEqual((i2v.skill, i2v.tool), ("i2v", "Luma___image_to_video"))

    def test_luma_is_enabled_premium_and_never_training_eligible(self):
        from agent.deep_agent.routing import is_free_tool, policy_blocker, premium_video, training_eligible

        for tool in ("text_to_video", "image_to_video", "extend_video", "modify_video"):
            name = f"Luma___{tool}"
            self.assertIsNone(policy_blocker(name, {}))
            self.assertTrue(premium_video(name))
            self.assertTrue(tool_needs_approval(name, autonomous=True))
            self.assertTrue(tool_needs_approval(name, autonomous=False))
        self.assertTrue(is_free_tool("Luma___list_luma_models"))
        self.assertTrue(is_free_tool("Luma___get_video_task"))
        self.assertFalse(tool_needs_approval("Luma___list_luma_models", autonomous=True))
        self.assertFalse(training_eligible({
            "provider": "luma", "model": "ray-3.2", "weights_license": "Apache-2.0",
            "training_eligible": True, "status": "succeeded",
        }))
        self.assertIsNotNone(policy_blocker("Luma___text_to_video", {"model": "ray-9"}))

    def test_luma_cost_estimate_uses_billing_rates_or_unknown(self):
        from agent.deep_agent.routing import estimate_cost

        with patch.dict(os.environ, {"LUMA_DRY_RUN": "false"}):
            quote = estimate_cost("Luma___modify_video", {"source_duration_seconds": 5, "resolution": "720p"})
            self.assertEqual(quote.total_cents, 108 + 32)
            self.assertIn("$1.40", quote.description)
            unknown = estimate_cost("Luma___extend_video", {"resolution": "360p", "generation_id": "x"})
            self.assertIsNone(unknown.total_cents)
            self.assertIn("unknown", unknown.description)
