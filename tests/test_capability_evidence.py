import unittest

from agent.deep_agent.routing import POLICY, resolve_alias


class CapabilityEvidenceTests(unittest.TestCase):
    def test_future_seedance_uses_us_fal_without_enabling_an_adapter(self):
        for alias, endpoint in [
            ('seedance25_t2v', 'text-to-video'),
            ('seedance25_i2v', 'image-to-video'),
            ('seedance25_r2v', 'reference-to-video'),
        ]:
            entry = POLICY['tools'][alias]
            self.assertEqual(entry['model'], f'bytedance/seedance-2.5/us/{endpoint}')
            self.assertEqual(entry['host'], 'fal US default')
            self.assertEqual(entry['us_available'], 'yes')
            self.assertEqual(entry['status'], 'pending')
            self.assertIsNone(entry['gateway_tool'])
            self.assertFalse(entry['training_eligible'])
        self.assertEqual(resolve_alias('seedance25_t2v'), 'Seedance___text_to_video')

    def test_official_evidence_never_enables_pending_tools(self):
        for alias in ['mureka_v95', 'mirelo_v2a', 'sync3_lipsync',
                      'heygen_avatar_v', 'recraft_v41_vector', 'ideogram45_edit', 'topaz_upscale']:
            with self.subTest(alias=alias):
                entry = POLICY['tools'][alias]
                self.assertEqual(entry['status'], 'pending')
                self.assertIsNone(entry['gateway_tool'])
                self.assertFalse(entry['training_eligible'])
                self.assertEqual(entry['read_date'], '2026-10-08')
                self.assertTrue(entry['license_source'].startswith('https://'))
                self.assertIn('adapter pending', entry['verification'])
        self.assertEqual(POLICY['tools']['sync3_lipsync']['us_available'], 'unclear')
        self.assertEqual(POLICY['tools']['heygen_avatar_v']['us_available'], 'unclear')
