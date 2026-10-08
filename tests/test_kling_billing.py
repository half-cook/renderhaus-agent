from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from server.billing_rates import cost_for


class KlingBillingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_read_tools_are_free_with_live_billing(self) -> None:
        with patch.dict(os.environ, {"STRIPE_SECRET_KEY": "test-stripe", "KLING_DRY_RUN": "false"}):
            for tool in ("get_video_task", "list_kling_models"):
                with self.subTest(tool=tool):
                    self.assertEqual(cost_for("kling", tool, {}).public(), {
                        "provider_cents": 0, "fee_cents": 0, "total_cents": 0,
                    })

    def test_generation_is_free_in_dry_run(self) -> None:
        for environment in ({},
                            {"STRIPE_SECRET_KEY": "test-stripe"},
                            {"STRIPE_SECRET_KEY": "test-stripe", "KLING_DRY_RUN": "true"}):
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True):
                for tool in ("text_to_video", "image_to_video", "omni_video"):
                    self.assertEqual(cost_for("kling", tool, {}).total_cents, 0)

    def test_published_rates_and_disclosed_thirty_percent_fee(self) -> None:
        cases = [
            ("text_to_video", "720p", False, 42, 13),
            ("image_to_video", "1080p", False, 56, 17),
            ("text_to_video", "720p", True, 63, 19),
            ("image_to_video", "1080p", True, 84, 25),
            ("omni_video", "720p", False, 42, 13),
            ("omni_video", "720p", True, 56, 17),
            ("omni_video", "1080p", True, 70, 21),
            ("omni_video", "4k", True, 210, 63),
            ("text_to_video", "4k", False, 210, 63),
        ]
        with patch.dict(os.environ, {"KLING_DRY_RUN": "false"}):
            for tool, resolution, audio, provider_cents, fee_cents in cases:
                with self.subTest(tool=tool, resolution=resolution, audio=audio):
                    self.assertEqual(cost_for("kling", tool, {
                        "duration_seconds": 5, "resolution": resolution, "generate_audio": audio,
                    }).public(), {
                        "provider_cents": provider_cents, "fee_cents": fee_cents,
                        "total_cents": provider_cents + fee_cents,
                    })

    def test_provider_total_rounds_once_after_multiplying_duration(self) -> None:
        with patch.dict(os.environ, {"KLING_DRY_RUN": "false"}):
            self.assertEqual(cost_for("kling", "text_to_video", {
                "duration_seconds": 3, "resolution": "720p",
            }).provider_cents, 25)
            self.assertEqual(cost_for("kling", "text_to_video", {
                "duration_seconds": 15, "resolution": "1080p", "generate_audio": True,
            }).provider_cents, 252)

    def test_turbo_unconfirmed_default_audio_semantics_have_no_guessed_price(self) -> None:
        with patch.dict(os.environ, {"KLING_DRY_RUN": "false"}):
            with self.assertRaises(ValueError):
                cost_for("kling", "text_to_video", {"model": "kling-3.0-turbo"})

    def test_invalid_arguments_cannot_receive_a_misleading_price(self) -> None:
        invalid = [{"duration_seconds": True}, {"duration_seconds": "5"},
                   {"duration_seconds": 2}, {"duration_seconds": 16},
                   {"duration_seconds": 5.5}, {"resolution": "480p"},
                   {"generate_audio": "false"}, {"model": "invented-model"},
                   {"model": []}, {"model": ["kling-3.0"]}, {"model": {"id": "kling-3.0"}},
                   {"resolution": []}, {"resolution": {"id": "720p"}}]
        with patch.dict(os.environ, {"KLING_DRY_RUN": "false"}):
            for arguments in invalid:
                with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                    cost_for("kling", "text_to_video", arguments)

    def test_unknown_kling_tool_has_no_fallback_price(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown Kling tool"):
            cost_for("kling", "unknown_tool", {})


if __name__ == "__main__":
    unittest.main()
