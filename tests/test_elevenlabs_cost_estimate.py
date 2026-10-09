import os
import unittest
from datetime import date
from unittest.mock import patch

from agent.deep_agent.routing import estimate_cost
from server import billing_rates as rates


class ElevenLabsCostEstimateTests(unittest.TestCase):
    def test_offline_tts_approvals_quote_characters_and_expiring_promo(self):
        with patch.dict(os.environ, {'STRIPE_SECRET_KEY': '', 'ELEVENLABS_TOOL_COST_CENTS_JSON': '{}'}, clear=True):
            for today, cents in ((date(2026, 10, 9), 11), (date(2026, 10, 13), 40)):
                with self.subTest(today=today), patch.object(rates, 'date') as clock:
                    clock.today.return_value = today
                    args = {'text': 'a' * 10000, 'model_id': 'eleven_v4_turbo'}
                    cost = rates.cost_for('elevenlabs', 'text_to_speech_convert', args)
                    self.assertEqual(cost.provider_cents, cents)
                    quote = estimate_cost('ElevenLabs___text_to_speech_convert', args)
                    self.assertEqual(quote.total_cents, cost.total_cents)
                    self.assertIn('$', quote.description)
            with patch.object(rates, 'date') as clock:
                clock.today.return_value = date(2026, 10, 13)
                full = rates.cost_for('elevenlabs', 'text_to_speech_convert', {'text': 'a' * 10000, 'model_id': 'eleven_v4'})
                self.assertEqual(full.provider_cents, 80)
            with self.assertRaisesRegex(ValueError, 'Allowed model_ids:'):
                estimate_cost('ElevenLabs___text_to_speech_convert', {'text': 'Hi', 'model_id': 'unknown'})
            self.assertIsNone(estimate_cost('ElevenLabs___music_compose', {'prompt': 'Piano'}).total_cents)
        with patch.dict(os.environ, {'STRIPE_SECRET_KEY': 'test-only', 'ELEVENLABS_TOOL_COST_CENTS_JSON': '{}'}, clear=True):
            self.assertIsNone(estimate_cost('ElevenLabs___text_to_speech_convert', {'text': 'Hi'}).total_cents)
            with self.assertRaises(ValueError):
                rates.cost_for('elevenlabs', 'text_to_speech_convert', {'text': 'Hi'})
