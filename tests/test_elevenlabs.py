"""Run: .venv/bin/python -m unittest discover -s tests -p test_elevenlabs.py (no paid requests)."""
import base64
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
import httpx2
from botocore.credentials import Credentials

from agent.gateway_client import GatewayIAMAuth
from agent.studio_agent_next import StudioAgentContext
from providers.catalog import PROVIDERS, get_provider
from providers.elevenlabs import api
from providers.elevenlabs.catalog import CATALOG, FEATURE_TOOLS, SPEC, build_catalog, requires_approval
from providers.registry import dispatch, generate_schemas, load_committed_schemas


class ElevenLabsTests(unittest.TestCase):
    def test_live_voices_work_without_static_provider_options(self):
        from server.studio import studio_options
        with patch("server.studio.dispatch", return_value={"result": {"voices": [{"voice_id": "voice-1"}]}}), \
             patch("server.studio.LIVE_CHOICE_TOOLS", (("elevenlabs", "voices_search", "voice_id"),)):
            result = asyncio.run(studio_options())
        self.assertEqual(result["providers"]["elevenlabs"]["voice_id"], ["voice-1"])

    def test_only_media_features_are_discoverable_and_executable(self):
        self.assertEqual(set(CATALOG), FEATURE_TOOLS)
        self.assertEqual(len(CATALOG), 41)
        self.assertTrue({"text_to_dialogue_convert", "music_compose", "dubbing_get", "voices_search"} <= CATALOG.keys())
        for name in ("voices_delete", "voices_update", "workspace_groups_list",
                     "service_accounts_api_keys_create", "user_get", "music_finetunes_create"):
            with self.subTest(name=name), patch.object(api, "api_key") as key:
                self.assertNotIn(name, CATALOG)
                with self.assertRaisesRegex(ValueError, "Unknown elevenlabs Gateway tool"):
                    dispatch("elevenlabs", name, {})
                with self.assertRaises(KeyError):
                    api.dispatch_tool(name, {})
                key.assert_not_called()
        # An upstream addition stays unavailable until explicitly selected.
        with patch.dict(SPEC["paths"], {"/v1/music/admin": {"post": {
            "x-fern-sdk-group-name": "music", "x-fern-sdk-method-name": "admin",
        }}}):
            self.assertEqual(set(build_catalog()), FEATURE_TOOLS)
        with patch.dict(SPEC, {"paths": {}}), self.assertRaisesRegex(ValueError, "Missing ElevenLabs feature"):
            build_catalog()
        self.assertNotIn("mureka", [p.id for p in PROVIDERS])
        self.assertEqual(load_committed_schemas(get_provider("elevenlabs")), generate_schemas(get_provider("elevenlabs")))
        for entry in CATALOG.values():
            self.assertNotEqual(entry["effect"], "administration")
            self.assertNotIn(entry["method"], {"DELETE", "PATCH", "PUT"})
            tool = entry["tool"]
            self.assertIn("Required inputs:", tool["description"])
            self.assertIn("Returns:", tool["description"])
            self.assertNotIn("xi-api-key", tool["inputSchema"]["properties"])
            self.assertTrue(all(name in tool["inputSchema"]["properties"] for name in tool["inputSchema"]["required"]))

    def test_music_validation_and_json_inputs(self):
        for args in ({}, {"prompt": "music", "music_length_ms": 30},
                     {"prompt": "music", "seed": 5}, {"prompt": "music", "composition_plan_json": "{}"}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                api.prepare_request("music_compose", args)
        with patch.dict(os.environ, {"ELEVENLABS_DRY_RUN": "true"}):
            self.assertEqual(dispatch("elevenlabs", "music_compose", {"prompt": "Warm piano", "music_length_ms": 3000})["status"], "dry_run")
        path, query, _, body = api.prepare_request("text_to_speech_convert", {
            "voice_id": "voice/id", "text": "Hello", "output_format": "mp3_44100_128",
            "voice_settings_json": '{"stability":0.5,"similarity_boost":0.7}',
        })
        self.assertEqual(path, "/v1/text-to-speech/voice%2Fid")
        self.assertEqual(query, {"output_format": "mp3_44100_128"})
        self.assertEqual(body["voice_settings"]["stability"], 0.5)
        for bad in ("..", "."):
            with self.assertRaises(ValueError):
                api.prepare_request("voices_get", {"voice_id": bad})

    def test_http_serialization_media_and_errors(self):
        requests = []
        def handle(request):
            requests.append(request)
            self.assertEqual(request.headers["xi-api-key"], "test-only-key")
            if request.url.path == "/v1/music":
                self.assertEqual(json.loads(request.content)["music_length_ms"], 3000)
                return httpx.Response(200, content=b"ID3audio", headers={"content-type": "audio/mpeg", "song-id": "song-1"})
            return httpx.Response(403, json={"detail": "test-only-key"})
        client = httpx.Client(transport=httpx.MockTransport(handle))
        with patch.object(api, "api_key", return_value="test-only-key"), \
             patch.object(api.httpx, "Client", return_value=client), \
             patch.dict(os.environ, {"ELEVENLABS_DRY_RUN": "false"}), \
             patch.object(api, "_save_media", return_value={"audio_url": "https://storage.test/audio.mp3"}) as save:
            result = dispatch("elevenlabs", "music_compose", {"prompt": "Piano", "music_length_ms": 3000})
        self.assertEqual(result["song_id"], "song-1")
        self.assertEqual(result["status"], "succeeded")
        save.assert_called_once_with(b"ID3audio", "audio/mpeg", output_format="")
        with patch.object(api, "api_key", return_value="test-only-key"), \
             patch.object(api.httpx, "Client", return_value=httpx.Client(transport=httpx.MockTransport(handle))), \
             patch.dict(os.environ, {"ELEVENLABS_DRY_RUN": "false"}):
            with self.assertRaises(RuntimeError) as failure:
                dispatch("elevenlabs", "models_list", {})
        self.assertIn("HTTP 403", str(failure.exception))
        self.assertNotIn("test-only-key", str(failure.exception))

    def test_multipart_upload_and_private_source_boundary(self):
        def handle(request):
            self.assertEqual(request.url.path, "/v1/audio-isolation")
            self.assertIn('name="audio"; filename="sample.wav"', request.content.decode())
            return httpx.Response(200, content=b"clean-audio", headers={"content-type": "audio/mpeg"})
        with patch.object(api, "api_key", return_value="test-key"), \
             patch.object(api.httpx, "Client", return_value=httpx.Client(transport=httpx.MockTransport(handle))), \
             patch.object(api, "_file_input", return_value=("sample.wav", b"sample", "audio/wav")), \
             patch.object(api, "_save_media", return_value={"audio_url": "https://storage.test/clean.mp3"}), \
             patch.dict(os.environ, {"ELEVENLABS_DRY_RUN": "false"}):
            self.assertEqual(api.dispatch_tool("audio_isolation_convert", {"audio": "https://owned.test/sample.wav"})["status"], "succeeded")
        with httpx.Client() as client:
            for url in ("http://169.254.169.254/latest/meta-data/", "https://example.com/file", "/etc/passwd"):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    api._file_input(client, url)

    def test_binary_storage_and_timestamp_stream(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "AWS_S3_BUCKET": "", "REMOTION_APP_BUCKET_NAME": "", "AWS_LAMBDA_FUNCTION_NAME": "", "RENDERHAUS_MEDIA_DIR": directory,
        }):
            result = api._response_payload(b"ID3audio", "audio/mpeg", "")
            self.assertEqual(Path(result["output_path"]).read_bytes(), b"ID3audio")
            chunks = b"\n".join(json.dumps({"audio_base64": base64.b64encode(c).decode(), "alignment": {}}).encode() for c in [b"one", b"two"])
            result = api._response_payload(chunks, "application/json", "")
            self.assertEqual(Path(result["audio_asset"]["output_path"]).read_bytes(), b"onetwo")
        self.assertEqual(api._json_result({"api_key": "secret"})["api_key"], "[credential redacted; manage in ElevenLabs dashboard]")

    def test_administration_approval_and_nested_asset_handles(self):
        self.assertTrue(requires_approval("ElevenLabs___voices_delete"))
        self.assertTrue(requires_approval("ElevenLabs___service_accounts_api_keys_create"))
        self.assertFalse(requires_approval("ElevenLabs___music_compose"))
        context = StudioAgentContext(source_publisher=lambda version: "https://storage.test/" + version)
        result = context.prepare_gateway_arguments("ElevenLabs___example", {"inputs_json": '[{"audio":"renderhaus-asset://version"}]'})
        self.assertEqual(json.loads(result["inputs_json"])[0]["audio"], "https://storage.test/version")

    def test_gateway_iam_signs_body_and_session_token(self):
        auth = GatewayIAMAuth("us-east-1")
        with patch.object(auth.session, "get_credentials", return_value=Credentials("test-id", "test-secret", "session-token")):
            request = httpx2.Request("POST", "https://example.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp", content=b'{"method":"tools/list"}')
            signed = next(auth.auth_flow(request))
        self.assertIn("AWS4-HMAC-SHA256", signed.headers["authorization"])
        self.assertEqual(signed.headers["x-amz-security-token"], "session-token")

    def test_billing_never_reuses_a_blanket_generation_price(self):
        from server.billing_rates import cost_for
        with patch.dict(os.environ, {"STRIPE_SECRET_KEY": "test-only", "ELEVENLABS_TOOL_COST_CENTS_JSON": "{}"}):
            self.assertEqual(cost_for("elevenlabs", "models_list", {}).total_cents, 0)
            with self.assertRaisesRegex(ValueError, "Configure an ElevenLabs"):
                cost_for("elevenlabs", "music_compose", {"prompt": "Piano"})
        with patch.dict(os.environ, {"STRIPE_SECRET_KEY": ""}):
            self.assertEqual(cost_for("elevenlabs", "music_compose", {"prompt": "Piano"}).total_cents, 0)


if __name__ == "__main__":
    unittest.main()
