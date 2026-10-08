"""Offline quote checks for the fal provider."""

from __future__ import annotations

import os
import unittest
from decimal import Decimal
from unittest.mock import patch

from providers.fal import wan
from server.billing_rates import cost_for

MODEL_21, MODEL_22 = wan.MODELS
SOURCE_URL = "https://media.example.test/video.mp4"
IMAGE_URL = "https://media.example.test/image.png"


class FalBillingTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"FAL_DRY_RUN": "false"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_quotes_use_confirmed_21_resolution_rates_and_fixed_16_fps_unit(self):
        for resolution, rate in (
            ("480p", Decimal("4")),
            ("580p", Decimal("6")),
            ("720p", Decimal("8")),
        ):
            for fps in (5, 16, 30):
                with self.subTest(resolution=resolution, fps=fps):
                    quote = cost_for(
                        "fal",
                        "text_to_video",
                        {
                            "prompt": "p",
                            "resolution": resolution,
                            "num_frames": 81,
                            "frames_per_second": fps,
                        },
                    )
                    self.assertEqual(quote.provider_cents, round(rate * Decimal(81) / Decimal(16)))
                    self.assertEqual(quote.fee_cents, max(1, round(quote.provider_cents * 0.3)))

    def test_quotes_use_confirmed_22_edit_rates(self):
        for mode in ("inpainting", "outpainting", "reframe", "depth"):
            for resolution, rate in (
                ("480p", Decimal("5")),
                ("580p", Decimal("7.5")),
                ("720p", Decimal("10")),
            ):
                with self.subTest(mode=mode, resolution=resolution):
                    quote = cost_for(
                        "fal",
                        "video_to_video",
                        {
                            "prompt": "p",
                            "video_url": SOURCE_URL,
                            "model": MODEL_22,
                            "edit_mode": mode,
                            "resolution": resolution,
                            "num_frames": 81,
                            **(
                                {"mask_image_url": IMAGE_URL}
                                if mode == "inpainting"
                                else {"expand_left": True}
                                if mode == "outpainting"
                                else {}
                            ),
                        },
                    )
                    self.assertEqual(quote.provider_cents, round(rate * Decimal(81) / Decimal(16)))

    def test_unknown_pricing_is_rejected_in_quotes(self):
        for mode in ("freeform", "pose"):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "pricing"):
                cost_for(
                    "fal",
                    "video_to_video",
                    {
                        "prompt": "p",
                        "video_url": SOURCE_URL,
                        "model": MODEL_22,
                        "edit_mode": mode,
                        "task": "depth" if mode == "freeform" else None,
                    },
                )
        for resolution in ("auto", "240p", "360p"):
            with self.subTest(resolution=resolution), self.assertRaisesRegex(ValueError, "pricing"):
                cost_for("fal", "text_to_video", {"prompt": "p", "resolution": resolution})

    def test_poll_and_catalog_quotes_are_zero(self):
        for tool in ("get_video_task", "list_fal_models"):
            with self.subTest(tool=tool):
                self.assertEqual(
                    cost_for("fal", tool, {}).public(),
                    {"provider_cents": 0, "fee_cents": 0, "total_cents": 0},
                )

    def test_dry_run_quotes_are_zero_even_with_unconfirmed_pricing(self):
        with patch.dict(os.environ, {"FAL_DRY_RUN": "true"}):
            for arguments in (
                {"prompt": "p"},
                {"prompt": "p", "model": MODEL_22},
                {"prompt": "p", "resolution": "240p"},
            ):
                with self.subTest(arguments=arguments):
                    self.assertEqual(cost_for("fal", "text_to_video", arguments).total_cents, 0)

    def test_quote_validates_types_bounds_and_mode_requirements(self):
        for arguments in (
            {"prompt": "p", "num_frames": True},
            {"prompt": "p", "num_frames": 80},
            {"prompt": "p", "model": "unknown"},
            {"prompt": "p", "resolution": "1080p"},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                cost_for("fal", "text_to_video", arguments)
        with self.assertRaisesRegex(ValueError, "mask"):
            cost_for(
                "fal",
                "video_to_video",
                {"prompt": "p", "video_url": SOURCE_URL, "edit_mode": "inpainting"},
            )

    def test_default_quote_matches_submission_estimate(self):
        quote = cost_for("fal", "text_to_video", {"prompt": "p"})
        self.assertEqual(quote.provider_cents, 40)
        self.assertEqual(quote.fee_cents, 12)
        self.assertEqual(quote.total_cents, 52)


if __name__ == "__main__":
    unittest.main()
