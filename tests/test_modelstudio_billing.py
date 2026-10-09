from __future__ import annotations

import os
import unittest
from decimal import Decimal
from unittest.mock import patch

from server import billing_rates as rates


BASE = {
    "video_url": "https://media.example.test/source.mp4", "prompt": "Keep the subject",
    "source_duration_seconds": 5, "source_fps": 24, "duration": 7,
}


class ModelStudioBillingTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_region_resolution_rates_use_input_plus_output_seconds(self):
        tables = {
            "us-east-1": {"480p": "49.5072", "720p": "99.0156", "1080p": "198.0300"},
            "ap-southeast-1": {"480p": "60", "720p": "120", "1080p": "240"},
        }
        for region, values in tables.items():
            for resolution, cents in values.items():
                for tool in ("edit_wan3_video", "extend_wan3_video"):
                    with self.subTest(region=region, resolution=resolution, tool=tool):
                        result = rates.modelstudio_price_cents(tool, {**BASE, "resolution": resolution}, region=region)
                        self.assertEqual(result, Decimal(cents))
                        self.assertIsInstance(result, Decimal)

    def test_source_fractional_seconds_are_priced_without_early_rounding(self):
        self.assertEqual(rates.modelstudio_price_cents("edit_wan3_video", {
            **BASE, "source_duration_seconds": 3.25, "duration": 5, "resolution": "480p",
        }), Decimal("34.0362"))

    def test_configured_region_matches_the_submit_configuration(self):
        with patch.dict(os.environ, {"DASHSCOPE_REGION": "ap-southeast-1"}):
            self.assertEqual(rates.modelstudio_price_cents("extend_wan3_video", BASE), Decimal("240"))

    def test_smart_duration_unknown_and_invalid_native_values_do_not_underquote(self):
        cases = [{"duration": -1}, {"duration": True}, {"duration": 1}, {"duration": 31},
                 {"duration": 7.0}, {"resolution": "4k"}, {"source_duration_seconds": 16},
                 {"source_duration_seconds": float("nan")}, {"source_duration_seconds": True},
                 {"source_duration_seconds": 15, "duration": 16}, {"source_fps": 15}, {"audio": "true"}]
        for extra in cases:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                rates.modelstudio_price_cents("edit_wan3_video", {**BASE, **extra})
        with self.assertRaises(ValueError):
            rates.modelstudio_price_cents("extend_wan3_video", {**BASE, "duration": 5})

    def test_unverified_model_has_no_known_price(self):
        with patch.dict(os.environ, {"DASHSCOPE_MODEL": "wan-unverified"}), self.assertRaisesRegex(ValueError, "UNVERIFIED"):
            rates.modelstudio_price_cents("edit_wan3_video", BASE)

    def test_polls_are_free_and_unknown_tools_do_not_fall_through(self):
        self.assertEqual(rates.cost_for("alibaba_modelstudio", "get_task", {"job_id": "a-task"}).total_cents, 0)
        with self.assertRaises(ValueError):
            rates.modelstudio_price_cents("other", BASE)

    def test_dry_run_is_free_after_argument_validation(self):
        self.assertEqual(rates.cost_for("alibaba_modelstudio", "edit_wan3_video", BASE).total_cents, 0)
        with self.assertRaises(ValueError):
            rates.cost_for("alibaba_modelstudio", "edit_wan3_video", {**BASE, "duration": 31})

    def test_live_bill_adds_existing_platform_fee_once(self):
        with patch.dict(os.environ, {
            "MODELSTUDIO_DRY_RUN": "false", "DASHSCOPE_WORKSPACE_ID": "testworkspace",
        }):
            self.assertEqual(rates.cost_for("alibaba_modelstudio", "extend_wan3_video", BASE).public(), {
                "provider_cents": 198, "fee_cents": 59, "total_cents": 257,
            })

    def test_unknown_region_never_gets_a_fallback_price(self):
        with self.assertRaises(ValueError):
            rates.modelstudio_price_cents("edit_wan3_video", BASE, region="elsewhere")

