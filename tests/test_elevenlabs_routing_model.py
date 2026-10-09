from unittest import TestCase
from unittest.mock import patch
import os

from providers.elevenlabs import api
from agent.deep_agent.routing import effective_model


class TTSModelTests(TestCase):
    def test_model_config_defaults_to_map_id(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(effective_model('elevenlabs', 'text_to_speech_convert', {}), 'eleven_v4_turbo')
            self.assertTrue(api.dry_run())

    def test_unverified_http_model_cannot_make_a_paid_request(self):
        with patch.dict(os.environ, {'ELEVENLABS_DRY_RUN': 'false'}, clear=True), patch.object(api, 'api_key') as key, patch.object(api.httpx, 'Client') as client:
            result = api.dispatch_tool('text_to_speech_convert', {'voice_id': 'test', 'text': 'Hello'})
        self.assertEqual(result['status'], 'dry_run')
        self.assertIn('UNVERIFIED', result['note'])
        key.assert_not_called()
        client.assert_not_called()

    def test_verified_model_override_is_configurable(self):
        with patch.dict(os.environ, {'ELEVENLABS_TTS_MODEL': 'eleven_multilingual_v2'}):
            self.assertEqual(effective_model('elevenlabs', 'text_to_speech_convert', {}), 'eleven_multilingual_v2')
