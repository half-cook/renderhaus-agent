import os
import unittest
from unittest.mock import patch

from agent.deep_agent.routing import POLICY, effective_model, resolve_alias


class CapabilityEvidenceTests(unittest.TestCase):
    def test_seedance25_ready_adapter_uses_us_fal_by_default(self):
        with patch.dict(os.environ, {
            "SEEDANCE_TRANSPORT": "fal", "SEEDANCE_FAL_REGION": "us",
            "SEEDANCE_MODEL": "dreamina-seedance-2-5-260628",
        }):
            for alias, endpoint, verb in [
                ('seedance25_t2v', 'text-to-video', 'text_to_video'),
                ('seedance25_i2v', 'image-to-video', 'image_to_video'),
                ('seedance25_r2v', 'reference-to-video', 'reference_to_video'),
                ('seedance25_edit', 'reference-to-video', 'edit_video'),
                ('seedance25_extend', 'reference-to-video', 'extend_video'),
            ]:
                with self.subTest(alias=alias):
                    entry = POLICY['tools'][alias]
                    self.assertEqual(entry['model'], 'dreamina-seedance-2-5-260628')
                    self.assertIn('fal US default', entry['host'])
                    self.assertIn('/us/', entry['availability_source'])
                    self.assertIn('yes via fal', POLICY['providers']['seedance']['us_available'])
                    self.assertEqual(entry['status'], 'ready')
                    self.assertEqual(entry['gateway_tool'], 'Seedance___' + verb)
                    self.assertFalse(entry['training_eligible'])
                    self.assertEqual(resolve_alias(alias), entry['gateway_tool'])
                    self.assertEqual(effective_model('seedance', verb, {}),
                                     f'bytedance/seedance-2.5/us/{endpoint}')

    def test_image_specialists_bind_verified_built_tools(self):
        for alias in ['recraft_v41_vector', 'ideogram45_edit']:
            with self.subTest(alias=alias):
                entry = POLICY['tools'][alias]
                self.assertEqual(entry['status'], 'ready')
                self.assertEqual(entry['gateway_tool'], {'recraft_v41_vector': 'Fal___recraft_text_to_vector',
                                                        'ideogram45_edit': 'Fal___ideogram_edit'}[alias])
                self.assertFalse(entry['training_eligible'])
                self.assertEqual(entry['read_date'], '2026-10-09')
                self.assertTrue(entry['license_source'].startswith('https://'))
                self.assertEqual(resolve_alias(alias), entry['gateway_tool'])
        entry = POLICY['tools']['heygen_avatar_v']
        self.assertEqual(entry['status'], 'ready')
        self.assertEqual(entry['gateway_tool'], 'HeyGen___create_avatar_video')
        self.assertEqual(entry['model'], 'avatar_v')
        self.assertEqual(entry['read_date'], '2026-10-09')
        self.assertEqual(entry['us_available'], 'yes')
        self.assertFalse(entry['training_eligible'])
        self.assertEqual(resolve_alias('heygen_avatar_v'), entry['gateway_tool'])

    def test_sync_verified_adapter_binds_the_canonical_alias(self):
        entry = POLICY['tools']['sync3_lipsync']
        self.assertEqual(entry['status'], 'ready')
        self.assertEqual(entry['gateway_tool'], 'Sync___lipsync_video')
        self.assertEqual(entry['read_date'], '2026-10-09')
        self.assertEqual(entry['us_available'], 'yes')
        self.assertFalse(entry['training_eligible'])
        self.assertEqual(resolve_alias('sync3_lipsync'), entry['gateway_tool'])
