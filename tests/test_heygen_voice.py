from __future__ import annotations

import json
import os
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.deep_agent import routing
from agent.gateway_executor import GatewayExecutor, tool_needs_approval
from providers import registry
from providers.catalog import get_provider
from server.billing_rates import cost_for

CLONE = {
    "reference_audio_url": "https://example.com/reference.wav",
    "reference_duration_seconds": 120.0, "reference_size_bytes": 1024,
    "reference_format": "wav", "name": "Alice narrator", "subjects": "Alice Lee",
    "consent_confirmed": True, "consent_record_id": "consent-alice",
    "account_id": "alice", "workspace_id": "workspace", "project_id": "project",
}
GATE = {"HEYGEN_VOICE_AB_GATE": "internal", "HEYGEN_VOICE_AB_USERS": "alice",
        "HEYGEN_VOICE_DRY_RUN": "true"}
PROMPT = "Clone my voice from this 2-minute recording and read this script in it"


class HeyGenVoiceContracts(unittest.TestCase):
    def setUp(self):
        from providers.heygen import voice_contracts
        self.contracts = voice_contracts

    def test_valid_instant_body_excludes_consent_and_account_fields(self):
        body = self.contracts.clone_body(self.contracts.CloneRequest.model_validate(CLONE))
        self.assertEqual(body, {"mode": "instant", "name": "Alice narrator", "audio": [
            {"type": "url", "url": "https://example.com/reference.wav"}], "similarity": "extra_high",
            "remove_background_noise": True})

    def test_refuses_missing_false_consent_and_unnamed_owner(self):
        for change in ({"consent_confirmed": False}, {"consent_confirmed": "true"},
                       {"subjects": " "}, {"consent_record_id": ""}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.contracts.CloneRequest.model_validate({**CLONE, **change})
        for field in ("consent_confirmed", "subjects", "consent_record_id"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.contracts.CloneRequest.model_validate({k: v for k, v in CLONE.items() if k != field})

    def test_professional_rejected_with_clear_message(self):
        with self.assertRaisesRegex(ValueError, "[Ii]nstant.*professional|[Pp]rofessional.*scope"):
            self.contracts.CloneRequest.model_validate({**CLONE, "mode": "professional"})

    def test_reference_limits_and_public_https(self):
        for change in ({"reference_size_bytes": 104857601}, {"reference_size_bytes": 0},
                       {"reference_duration_seconds": 0.0}, {"reference_duration_seconds": float("nan")},
                       {"reference_format": "flac"}, {"reference_audio_url": "https://127.0.0.1/audio.wav"},
                       {"reference_audio_url": "http://example.com/a.wav"}, {"name": "n" * 65}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.contracts.CloneRequest.model_validate({**CLONE, **change})
        request = self.contracts.CloneRequest.model_validate({**CLONE, "reference_duration_seconds": 240.0})
        self.assertEqual(request.used_reference_seconds, 180.0)

    def test_tts_text_limits_and_instant_only_controls(self):
        base = {"voice_id": "voice", "text": "Hello", "language": "en", **{
            k: CLONE[k] for k in ("account_id", "workspace_id", "project_id")}}
        for change in ({"text": " "}, {"text": "x" * 5001}, {"seed": 1},
                       {"text": '<break time="1s"/>'}, {"expressiveness_boost": 1.1}, {"language": "xx"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.contracts.TTSRequest.model_validate({**base, **change})
        self.contracts.TTSRequest.model_validate({**base, "text": "x" * 5000})


class HeyGenVoicePreview(unittest.TestCase):
    def setUp(self):
        from providers.heygen import voice
        self.voice = voice
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = patch.dict(os.environ, {**GATE, "RENDERHAUS_MEDIA_DIR": self.directory.name,
                                          "HEYGEN_DRY_RUN": "false", "HEYGEN_VOICE_MODEL": "heygen-voice-1"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def clone(self):
        return registry.dispatch("heygen", "voice_clone", CLONE)

    def speech(self, voice_id, **changes):
        return registry.dispatch("heygen", "voice_tts", {"voice_id": voice_id, "text": "Hello Alice.",
            "language": "en", "account_id": "alice", "workspace_id": "workspace", "project_id": "project", **changes})

    def test_preview_clone_then_wav_is_zero_cost_and_deterministic(self):
        with patch("httpx.Client", side_effect=AssertionError("Provider network forbidden")), \
             patch("boto3.client", side_effect=AssertionError("Secrets/network forbidden")):
            first = self.clone()
            self.assertEqual(first["status"], "dry_run")
            self.assertEqual(first["voice_id"], self.clone()["voice_id"])
            poll = registry.dispatch("heygen", "get_voice_status", {"voice_id": first["voice_id"],
                "account_id": "alice", "workspace_id": "workspace", "project_id": "project"})
            self.assertEqual(poll["status"], "dry_run")
            speech = self.speech(first["voice_id"])
            self.assertEqual(speech["status"], "dry_run")
            self.assertTrue(speech["placeholder"])
            self.assertFalse(speech["training_eligible"])
            self.assertEqual(speech["cost_usd"], 0)
            contents = Path(speech["output_path"]).read_bytes()
            self.assertEqual(contents, Path(self.speech(first["voice_id"])["output_path"]).read_bytes())
            with wave.open(speech["output_path"], "rb") as wav:
                self.assertEqual((wav.getframerate(), wav.getnchannels(), wav.getsampwidth()), (44100, 1, 2))
                self.assertEqual(wav.getnframes(), 44100)
            self.assertEqual(cost_for("heygen", "voice_tts", {}).total_cents, 0)
            self.assertEqual(cost_for("heygen", "voice_clone", {}).total_cents, 0)

    def test_project_and_account_bound_voice_cannot_be_reused(self):
        clone = self.clone()
        for change in ({"project_id": "other"}, {"account_id": "bob"}, {"workspace_id": "other"}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "project|account|scope"):
                self.speech(clone["voice_id"], **change)
        with self.assertRaises(ValueError):
            self.speech("arbitrary-global-voice")

    def test_dry_flag_false_blocks_before_key_or_transport_access(self):
        with patch.dict(os.environ, {"HEYGEN_VOICE_DRY_RUN": "false"}), \
             patch("httpx.Client", side_effect=AssertionError("Network forbidden")):
            with self.assertRaisesRegex(ValueError, "UNVERIFIED|dry.run.only"):
                self.clone()

    def test_unknown_model_preview_is_marked_unverified_and_quote_unknown(self):
        from providers.heygen import voice_contracts
        with patch.dict(os.environ, {"HEYGEN_VOICE_MODEL": "future-voice"}):
            clone = self.clone()
            self.assertIn("UNVERIFIED", clone["note"])
            self.assertIsNone(routing.estimate_cost("HeyGen___voice_tts", {"text": "Hello"}).total_cents)
            self.assertIn("UNVERIFIED", voice_contracts.live_blocker())

    def test_no_key_reads_or_saved_signed_query(self):
        original = os.getenv
        def getenv(name, default=None):
            if name == "HEYGEN_API_KEY":
                raise AssertionError("Dry voice must not read a key")
            return original(name, default)
        with patch("os.getenv", side_effect=getenv):
            self.clone()
        registry.dispatch("heygen", "voice_clone", {**CLONE,
            "reference_audio_url": "https://example.com/a.wav?signature=private-value"})
        for file in Path(self.directory.name).rglob("*.json"):
            self.assertNotIn("private-value", file.read_text())


class HeyGenVoiceRouting(unittest.TestCase):
    def route(self, prompt=PROMPT, **kwargs):
        return routing.route_intent(prompt, user_id="alice", **kwargs)

    def test_gate_off_clone_sequence_is_elevenlabs(self):
        with patch.dict(os.environ, {"HEYGEN_VOICE_AB_GATE": "off"}):
            route = self.route()
        self.assertEqual([r.alias for r in route.steps], ["voices_ivc_create", "eleven_v4_turbo"])

    def test_gate_on_internal_clone_then_speech(self):
        with patch.dict(os.environ, GATE):
            route = self.route()
        self.assertEqual([r.alias for r in route.steps], ["heygen_voice_clone", "heygen_voice_tts"])
        self.assertTrue(all(r.dispatch_tool == "call_audio_tool" for r in route.steps))

    def test_allowlist_is_required_and_cannot_be_enabled_by_arguments(self):
        with patch.dict(os.environ, GATE):
            route = routing.route_intent(PROMPT, user_id="bob", arguments={"heygen_voice_ab": True})
        self.assertEqual(route.steps[0].alias, "voices_ivc_create")
        with patch.dict(os.environ, {**GATE, "HEYGEN_VOICE_AB_USERS": ""}):
            self.assertEqual(self.route().steps[0].alias, "voices_ivc_create")

    def test_abbreviation_and_numbers_exception(self):
        with patch.dict(os.environ, GATE):
            route = self.route('Read this script in my cloned voice: "Call 1-800-555-0199 by Oct 31, ASAP, Dr. Lee, 3.5 GB"')
        self.assertEqual(route.alias, "eleven_v4_turbo")
        self.assertIn("normal", route.basis.lower())

    def test_named_elevenlabs_wins_even_when_gate_on(self):
        with patch.dict(os.environ, GATE):
            route = self.route("Use ElevenLabs to clone my voice and narrate this")
        self.assertEqual([r.alias for r in route.steps], ["voices_ivc_create", "eleven_v4_turbo"])
        self.assertTrue(all(r.skill == "named-provider" for r in route.steps))

    def test_stock_voice_tts_default_unchanged(self):
        with patch.dict(os.environ, GATE):
            self.assertEqual(self.route("Read this narration in a stock voice").alias, "eleven_v4_turbo")
        self.assertEqual(routing.POLICY["capability_map"]["tts"]["default"], "eleven_v4_turbo")
        self.assertEqual(routing.POLICY["capability_map"]["tts"]["exceptions"], [])
        self.assertEqual(routing.POLICY["capability_map"]["voice_clone"]["default"], "voices_ivc_create")

    def test_named_heygen_stays_available_as_dry_preview_with_gate_off(self):
        with patch.dict(os.environ, {"HEYGEN_VOICE_AB_GATE": "off", "HEYGEN_VOICE_DRY_RUN": "true"}):
            route = self.route("Use HeyGen Voice to clone my voice and read this script")
        self.assertEqual([r.alias for r in route.steps], ["heygen_voice_clone", "heygen_voice_tts"])

    def test_deterministic_normalisation_predicate(self):
        from providers.heygen.voice_contracts import needs_text_normalisation
        for text in ("Call 1-800-555-0199", "Meet on 2026-10-31", "Oct 31", "3.5 GB", "Dr. Lee", "ASAP", "15 kg", "10/31/2026"):
            with self.subTest(text=text):
                self.assertTrue(needs_text_normalisation(text))
        for text in ("The birds sing in the garden.", "We will call tomorrow."):
            self.assertFalse(needs_text_normalisation(text))

    def test_normalised_script_uses_candidate_without_llm_prepass(self):
        with patch.dict(os.environ, GATE):
            route = self.route("Read in my cloned voice: Call the doctor as soon as possible.",
                               arguments={"text": "Call the doctor as soon as possible.", "text_normalised": True})
        self.assertEqual(route.alias, "heygen_voice_tts")

    def test_gate_off_gateway_blocks_unnamed_candidate(self):
        executor = object.__new__(GatewayExecutor)
        executor.studio = SimpleNamespace(prompt=PROMPT, user_id="alice", account_id="alice",
            workspace_id="workspace", project_id="project", confidential=False, working_assets={}, source_versions={})
        executor.rejected_reviews = {}; executor.media_jobs = {}
        with patch.dict(os.environ, {**GATE, "HEYGEN_VOICE_AB_GATE": "off"}):
            route = executor.media_selection("HeyGen___voice_clone", CLONE)
            self.assertIn("ElevenLabs", executor.selection_blocker("HeyGen___voice_clone", CLONE, route))

    def test_approval_card_names_owner_upload_training_and_unknown_cost(self):
        executor = object.__new__(GatewayExecutor)
        executor.studio = SimpleNamespace(prompt="Use HeyGen Voice to clone my voice", user_id="alice",
            workspace_id="workspace", project_id="project")
        message = executor.dispatch_disclosure("HeyGen___voice_clone", CLONE, None)
        for phrase in ("Alice Lee", "uploaded to HeyGen", "training", "unknown", "consent-alice"):
            self.assertIn(phrase.lower(), message.lower())
        self.assertTrue(tool_needs_approval("HeyGen___voice_clone", False))
        self.assertTrue(tool_needs_approval("HeyGen___voice_tts", False))
        for change in ({"subjects": ""}, {"consent_confirmed": False}, {"account_id": "bob"}):
            self.assertIsNotNone(executor.selection_blocker("HeyGen___voice_clone", {**CLONE, **change}, None))

    def test_gateway_schema_dispatch_and_separate_dry_flag(self):
        from agent.deep_agent.runner import DISPATCH_TARGETS
        tools = registry.generate_schemas(get_provider("heygen"))
        by_name = {t["name"]: t for t in tools}
        self.assertTrue({"voice_clone", "voice_tts", "get_voice_status"} <= by_name.keys())
        self.assertTrue({"consent_confirmed", "subjects", "consent_record_id", "account_id", "project_id"} <= set(by_name["voice_clone"]["inputSchema"]["required"]))
        self.assertIn("HeyGen", DISPATCH_TARGETS["call_audio_tool"])
        self.assertEqual(get_provider("heygen").default_env["HEYGEN_VOICE_DRY_RUN"], "true")
        self.assertIn("HEYGEN_VOICE_AB_USERS", get_provider("heygen").env_keys)

    def test_unverified_price_stays_unknown_not_proposal_rate(self):
        from server.billing_rates import heygen_voice_price_cents
        with self.assertRaisesRegex(ValueError, "unknown|UNVERIFIED"):
            heygen_voice_price_cents("voice_tts", {"text": "x" * 1000})


class HeyGenVoiceMockTransport(unittest.TestCase):
    setUp = HeyGenVoicePreview.setUp
    clone = HeyGenVoicePreview.clone
    speech = HeyGenVoicePreview.speech

    def test_mocked_async_submit_and_single_poll(self):
        with patch.dict(os.environ, {"HEYGEN_VOICE_DRY_RUN": "false"}), \
             patch("providers.heygen.voice_contracts.live_blocker", return_value=None), \
             patch("providers.heygen.voice._request", return_value={"data": {"voice_id": "voice_alice"}}) as transport:
            clone = self.clone()
            self.assertEqual(clone["status"], "queued")
            args = transport.call_args
            self.assertEqual(args.args, ("POST", "/models/audio/voices"))
            self.assertEqual(args.kwargs["body"]["mode"], "instant")
            self.assertTrue(args.kwargs["idempotency_key"])
            transport.return_value = {"data": {"voice_id": "voice_alice", "mode": "instant", "status": "ACTIVE"}}
            poll = registry.dispatch("heygen", "get_voice_status", {"voice_id": "voice_alice",
                "account_id": "alice", "workspace_id": "workspace", "project_id": "project"})
            self.assertEqual(poll["status"], "succeeded")
            self.assertEqual(transport.call_args.args, ("GET", "/models/audio/voices/voice_alice"))
            self.assertEqual(transport.call_count, 2)

    def test_mocked_speech_saves_valid_wav_as_normal_output(self):
        def download(url, output):
            with wave.open(str(output), "wb") as wav:
                wav.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
                wav.writeframes(b"\0\0" * 44100)
        with patch.dict(os.environ, {"HEYGEN_VOICE_DRY_RUN": "false"}), \
             patch("providers.heygen.voice_contracts.live_blocker", return_value=None), \
             patch("providers.heygen.voice._request", return_value={"data": {"voice_id": "voice_alice"}}) as transport, \
             patch("providers.heygen.voice._download_wav", side_effect=download):
            self.clone()
            transport.return_value = {"data": {"voice_id": "voice_alice", "mode": "instant", "status": "ACTIVE"}}
            registry.dispatch("heygen", "get_voice_status", {"voice_id": "voice_alice",
                "account_id": "alice", "workspace_id": "workspace", "project_id": "project"})
            transport.return_value = {"data": {"audio_url": "https://example.com/generated.wav", "duration": 1.0}}
            speech = self.speech("voice_alice")
            self.assertEqual(speech["status"], "succeeded")
            self.assertFalse(speech["placeholder"])
            self.assertTrue(Path(speech["output_path"]).is_file())
            self.assertFalse(speech["training_eligible"])
            self.assertEqual(transport.call_args.args, ("POST", "/models/audio/tts"))

    def test_list_price_math_ignores_promotion(self):
        from decimal import Decimal
        from server import billing_rates
        with patch.object(billing_rates, "HEYGEN_VOICE_LIST_USD_PER_MILLION", Decimal("30")):
            self.assertEqual(billing_rates.heygen_voice_price_cents("voice_tts", {"text": "x" * 5000}), Decimal("15"))
        with patch.object(billing_rates, "HEYGEN_VOICE_CLONE_LIST_USD", Decimal("2")):
            self.assertEqual(billing_rates.heygen_voice_price_cents("voice_clone", {}), Decimal("200"))
