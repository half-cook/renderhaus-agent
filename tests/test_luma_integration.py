from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from lambdas.handler import handler
from providers.catalog import get_provider
from providers.registry import dispatch, generate_schemas, load_committed_schemas
from server.billing_rates import cost_for
from server.secrets import secret_payload_from_mapping
from server.studio_options import static_field_options


class LumaGatewayTests(unittest.TestCase):
    def test_committed_schemas_match_generated_six_tools(self):
        spec = get_provider("luma")
        schemas = generate_schemas(spec)
        self.assertEqual(schemas, load_committed_schemas(spec))
        self.assertEqual({tool["name"] for tool in schemas}, {
            "text_to_video", "image_to_video", "extend_video", "modify_video",
            "get_video_task", "list_luma_models",
        })
        self.assertEqual(spec.default_env, {"LUMA_DRY_RUN": "true"})
        self.assertIn("LUMA_API_KEY", spec.env_keys)
        image_schema = next(tool for tool in schemas if tool["name"] == "image_to_video")
        self.assertEqual(image_schema["inputSchema"]["properties"]["duration_seconds"]["description"], "Allowed values: 5.")

    def test_invalid_gateway_arguments_never_open_http_client(self):
        cases = [
            ("text_to_video", {"prompt": "Clip", "model": "ray-3.2-flash"}),
            ("text_to_video", {"prompt": "Clip", "resolution": "4k"}),
            ("text_to_video", {"prompt": "Clip", "duration_seconds": True}),
            ("text_to_video", {"prompt": "Clip", "duration_seconds": 6}),
            ("text_to_video", {"prompt": "Clip", "aspect_ratio": "adaptive"}),
            ("text_to_video", {"prompt": "a" * 6001}),
            ("text_to_video", {"prompt": "Clip", "callback_url": "https://example.test"}),
            ("image_to_video", {"prompt": "Clip"}),
            ("image_to_video", {"prompt": "Clip", "image_path_or_url": "https://example.test/a.png", "duration_seconds": 10}),
            ("extend_video", {"prompt": "Clip", "generation_id": "../escape"}),
            ("extend_video", {"prompt": "Clip", "generation_id": "d290f1ee-6c54-4b01-90e6-d701748f0851", "resolution": "360p"}),
            ("modify_video", {"prompt": "Edit", "source_duration_seconds": 5}),
            ("modify_video", {"prompt": "Edit", "source_duration_seconds": 8, "video_path_or_url": "https://example.test/a.mp4"}),
            ("modify_video", {"prompt": "Edit", "source_duration_seconds": 5, "video_path_or_url": "https://example.test/a.mp4", "source_generation_id": "d290f1ee-6c54-4b01-90e6-d701748f0851"}),
            ("get_video_task", {"job_id": "../../outside"}),
        ]
        with patch.dict(os.environ, {"LUMA_DRY_RUN": "false"}), patch("providers.luma.api.httpx.Client") as client:
            for tool, arguments in cases:
                with self.subTest(tool=tool, arguments=arguments), self.assertRaises(ValueError):
                    dispatch("luma", tool, arguments)
            client.assert_not_called()

    def test_lambda_exposes_luma_and_returns_validation_error(self):
        with patch.dict(os.environ, {"RENDERHAUS_PROVIDER": "luma", "LUMA_DRY_RUN": "true"}):
            result = handler({"_tool_name": "text_to_video", "prompt": "Clip"}, SimpleNamespace())
            error = handler({"_tool_name": "text_to_video", "prompt": "Clip", "resolution": "bogus"}, SimpleNamespace())
        self.assertEqual(result["status"], "dry_run")
        self.assertIs(result["training_eligible"], False)
        self.assertEqual(error["error_type"], "ValueError")

    def test_studio_choices_and_secrets_use_documented_configuration(self):
        options = static_field_options()["luma"]
        self.assertEqual(options["model"], ["ray-3.2"])
        self.assertEqual(options["duration_seconds"], [5, 10])
        self.assertEqual(options["resolution"], ["360p", "540p", "720p", "1080p"])
        self.assertNotIn("adaptive", options["aspect_ratio"])
        self.assertEqual(secret_payload_from_mapping({"LUMA_API_KEY": "fixture", "LUMA_DRY_RUN": "true"}), {
            "LUMA_API_KEY": "fixture", "LUMA_DRY_RUN": "true",
        })

    def test_ci_forces_luma_dry_run_even_when_environment_is_live(self):
        from scripts.ci_check import _force_dry_run
        with patch.dict(os.environ, {"LUMA_DRY_RUN": "false"}):
            _force_dry_run()
            self.assertEqual(os.environ["LUMA_DRY_RUN"], "true")


class LumaBillingTests(unittest.TestCase):
    def test_generation_and_modify_match_official_sdr_tiers(self):
        generation = {"360p": (6, 18), "540p": (15, 45), "720p": (30, 90), "1080p": (120, 360)}
        modify = {"360p": (54, 108), "540p": (72, 144), "720p": (108, 216), "1080p": (216, 432)}
        with patch.dict(os.environ, {"LUMA_DRY_RUN": "false"}):
            for tool, rates, duration_key in (
                ("text_to_video", generation, "duration_seconds"),
                ("modify_video", modify, "source_duration_seconds"),
            ):
                for resolution, amounts in rates.items():
                    for duration, cents in zip((5, 10), amounts):
                        with self.subTest(tool=tool, resolution=resolution, duration=duration):
                            cost = cost_for("luma", tool, {"resolution": resolution, duration_key: duration})
                            self.assertEqual(cost.provider_cents, cents)
                            self.assertEqual(cost.fee_cents, max(1, round(cents * 0.30)))

    def test_image_and_extend_have_fixed_five_second_pricing(self):
        with patch.dict(os.environ, {"LUMA_DRY_RUN": "false"}):
            self.assertEqual(cost_for("luma", "image_to_video", {}).provider_cents, 30)
            for resolution, cents in (("540p", 15), ("720p", 30), ("1080p", 120)):
                self.assertEqual(cost_for("luma", "extend_video", {"resolution": resolution}).provider_cents, cents)

    def test_dry_run_defaults_to_zero_cost_and_poll_and_list_are_free(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cost_for("luma", "text_to_video", {}).total_cents, 0)
        with patch.dict(os.environ, {"LUMA_DRY_RUN": "false"}):
            for tool in ("get_video_task", "list_luma_models"):
                self.assertEqual(cost_for("luma", tool, {}).total_cents, 0)
        with patch.dict(os.environ, {"LUMA_DRY_RUN": "TRUE"}):
            self.assertEqual(cost_for("luma", "text_to_video", {}).total_cents, 0)
        with patch.dict(os.environ, {"LUMA_DRY_RUN": "FALSE"}):
            self.assertEqual(cost_for("luma", "text_to_video", {}).total_cents, 39)

    def test_unknown_prices_and_models_fail_closed(self):
        cases = [
            ("text_to_video", {"model": "ray-2-flash"}),
            ("text_to_video", {"resolution": "4k"}),
            ("text_to_video", {"duration_seconds": True}),
            ("text_to_video", {"duration_seconds": 8}),
            ("image_to_video", {"duration_seconds": 10}),
            ("extend_video", {"resolution": "360p"}),
            ("modify_video", {}),
            ("modify_video", {"source_duration_seconds": 18}),
            ("unknown_tool", {}),
        ]
        with patch.dict(os.environ, {"LUMA_DRY_RUN": "false"}):
            for tool, arguments in cases:
                with self.subTest(tool=tool, arguments=arguments), self.assertRaises(ValueError):
                    cost_for("luma", tool, arguments)




if __name__ == "__main__":
    unittest.main()
