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

    def test_bootstrap_and_provider_defaults_stay_dry_run(self):
        from providers.catalog import PROVIDERS
        from providers.remotion import api as remotion
        from server.config import DEFAULT_ENV
        from server.secrets import secret_payload_from_mapping
        from scripts.deploy_agentcore import RUNTIME_BOOTSTRAP_KEYS

        self.assertEqual(DEFAULT_ENV['ELEVENLABS_DRY_RUN'], 'true')
        self.assertEqual(DEFAULT_ENV['REMOTION_DRY_RUN'], 'true')
        self.assertEqual(DEFAULT_ENV['ELEVENLABS_TTS_MODEL'], 'eleven_v4_turbo')
        self.assertIn('ELEVENLABS_TTS_MODEL', RUNTIME_BOOTSTRAP_KEYS)
        config = {'ELEVENLABS_TTS_MODEL': 'eleven_multilingual_v2'}
        self.assertEqual(secret_payload_from_mapping(config), config)
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(api.dry_run())
            self.assertTrue(remotion.dry_run())
        for spec in PROVIDERS:
            for key, value in spec.default_env.items():
                if key.endswith('_DRY_RUN'):
                    self.assertEqual(value, 'true', key)

    def test_every_http_speech_variant_blocks_unverified_transport(self):
        for tool in api.CATALOG:
            if not tool.startswith(('text_to_speech_', 'text_to_dialogue_')):
                continue
            args = {'voice_id': 'test', 'text': 'Hello'} if tool.startswith('text_to_speech_') else {'inputs_json': '[{"voice_id": "test", "text": "Hello"}]'}
            with self.subTest(tool=tool), patch.dict(os.environ, {'ELEVENLABS_DRY_RUN': 'false'}, clear=True), patch.object(api, 'api_key') as key, patch.object(api.httpx, 'Client') as client:
                result = api.dispatch_tool(tool, args)
                self.assertEqual(result['status'], 'dry_run')
                self.assertIn('UNVERIFIED', result['note'])
                key.assert_not_called()
                client.assert_not_called()
