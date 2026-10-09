from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from server import billing_rates as rates


class Wan3BillingTests(unittest.TestCase):
    def test_official_resolution_rates_and_native_audio_no_surcharge(self):
        for resolution, cents in [('480p', 25), ('720p', 50), ('1080p', 100)]:
            for audio in [False, True]:
                with self.subTest(resolution=resolution, audio=audio):
                    self.assertEqual(rates.wan3_price_cents({'duration': 5, 'resolution': resolution, 'audio': audio}), cents)

    def test_defaults_match_official_1080p_five_seconds(self):
        self.assertEqual(rates.wan3_price_cents({}), 100)

    def test_reference_video_input_seconds_are_billed(self):
        self.assertEqual(rates.wan3_price_cents({
            'resolution': '720p', 'duration': 10,
            'reference_video_urls': ['https://example.test/a.mp4', 'https://example.test/b.mp4'],
            'reference_video_durations': [3, 4.5],
        }), 175)

    def test_images_and_audio_have_no_unpublished_input_surcharge(self):
        self.assertEqual(rates.wan3_price_cents({
            'duration': 5, 'resolution': '480p',
            'reference_image_urls': ['https://example.test/image.png'],
            'reference_audio_urls': ['https://example.test/voice.mp3'],
            'reference_audio_durations': [10],
        }), 25)

    def test_smart_duration_quote_is_unknown(self):
        with self.assertRaisesRegex(ValueError, 'smart|Smart'):
            rates.wan3_price_cents({'duration': None})

    def test_missing_or_invalid_input_measurements_do_not_underquote(self):
        for extra in [{}, {'reference_video_durations': []},
                      {'reference_video_durations': [-1]}, {'reference_video_durations': [16]},
                      {'reference_video_durations': [float('nan')]}, {'reference_video_durations': [True]},
                      {'reference_video_durations': [1, 2]}]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                rates.wan3_price_cents({'reference_video_urls': ['https://example.test/a.mp4'], **extra})

    def test_invalid_native_settings_do_not_get_fallback_prices(self):
        for args in [{'duration': 1}, {'duration': 31}, {'duration': True}, {'duration': 3.5},
                     {'resolution': '4K'}, {'audio': 'true'}, {'model': 'fal-ai/wan-vace-14b'},
                     {'reference_video_durations': [3]}]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                rates.wan3_price_cents(args)

    def test_live_cost_includes_existing_platform_fee(self):
        with patch.dict(os.environ, {'FAL_DRY_RUN': 'false'}):
            cost = rates.cost_for('fal', 'generate_wan3_t2v', {'prompt': 'A forest', 'duration': 10, 'resolution': '720p'})
        self.assertEqual(cost.public(), {'provider_cents': 100, 'fee_cents': 30, 'total_cents': 130})

    def test_reference_live_cost_uses_total_input_and_output_seconds(self):
        with patch.dict(os.environ, {'FAL_DRY_RUN': 'false'}):
            cost = rates.cost_for('fal', 'generate_wan3_r2v', {
                'prompt': 'Keep the subject', 'duration': 10, 'resolution': '1080p',
                'reference_video_urls': ['https://example.test/a.mp4'],
                'reference_video_durations': [5], 'reference_video_fps': [24],
            })
        self.assertEqual(cost.public(), {'provider_cents': 300, 'fee_cents': 90, 'total_cents': 390})

    def test_dryrun_cost_is_zero_but_arguments_still_validated(self):
        with patch.dict(os.environ, {'FAL_DRY_RUN': 'true'}):
            self.assertEqual(rates.cost_for('fal', 'generate_wan3_t2v', {'prompt': 'A forest'}).total_cents, 0)
            with self.assertRaises(ValueError):
                rates.cost_for('fal', 'generate_wan3_t2v', {'prompt': 'A forest', 'duration': 31})

    def test_billing_fixed_endpoint_identity_does_not_accept_other_model(self):
        with patch.dict(os.environ, {'FAL_DRY_RUN': 'false'}):
            with self.assertRaisesRegex(ValueError, 'model|endpoint'):
                rates.cost_for('fal', 'generate_wan3_i2v', {
                    'start_image_url': 'https://example.test/start.png',
                    'model': 'alibaba/wan-3.0/text-to-video',
                })
