from __future__ import annotations

import json
import os
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent.deep_agent.runner import run_with_servers
from agent.gateway_executor import GatewayExecutor
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, _context_from_request,
    _append_harvested_event,
)
from providers import registry
from test_deep_agent import Gateway, ScriptedModel, call, final
from test_heygen import MemoryS3
from test_heygen_voice import CLONE, GATE


class HeyGenVoiceStorageBoundaries(unittest.TestCase):
    def test_ci_dry_run_does_not_use_a_deployment_storage_bucket(self):
        with patch.dict(os.environ, {"AWS_S3_BUCKET": "deployment-bucket"}):
            from scripts.ci_check import _force_dry_run

            _force_dry_run()
            self.assertEqual(os.environ["AWS_S3_BUCKET"], "")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = MemoryS3()
        self.environment = patch.dict(os.environ, {
            **GATE, "RENDERHAUS_MEDIA_DIR": str(Path(self.directory.name) / "lambda"),
            "AWS_S3_BUCKET": "offline-voice-bucket", "HEYGEN_VOICE_MODEL": "heygen-voice-1",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        storage = patch("providers.heygen.api._store_client", return_value=self.store)
        storage.start()
        self.addCleanup(storage.stop)

    def scope(self, voice_id):
        return {"voice_id": voice_id, **{key: CLONE[key] for key in
                                       ("account_id", "workspace_id", "project_id")}}

    def test_personal_and_organization_workspace_ids_survive_scoped_reuse(self):
        from server.auth import current_workspace_id

        for payload in ({"sub": "alice"}, {"sub": "alice", "org_id": "org_team"}):
            workspace_id = current_workspace_id(SimpleNamespace(payload=payload))
            with self.subTest(workspace_id=workspace_id):
                clone = registry.dispatch("heygen", "voice_clone", {**CLONE, "workspace_id": workspace_id})
                args = {**self.scope(clone["voice_id"]), "workspace_id": workspace_id,
                        "text": "Hello Alice.", "language": "en"}
                executor = object.__new__(GatewayExecutor)
                executor.studio = SimpleNamespace(prompt="Use HeyGen Voice to read in my cloned voice",
                    user_id="alice", workspace_id=workspace_id, project_id="project")
                self.assertIsNone(executor.selection_blocker("HeyGen___voice_tts", args, None))
                self.assertEqual(registry.dispatch("heygen", "voice_tts", args)["cost_usd"], 0)

    def test_clone_survives_different_host_and_cold_provider_roots(self):
        clone = registry.dispatch("heygen", "voice_clone", CLONE)
        with patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": str(Path(self.directory.name) / "host")}):
            executor = object.__new__(GatewayExecutor)
            executor.studio = SimpleNamespace(prompt="Use HeyGen Voice to read in my cloned voice",
                user_id="alice", workspace_id="workspace", project_id="project")
            args = {**self.scope(clone["voice_id"]), "text": "Hello Alice.", "language": "en"}
            self.assertIsNone(executor.selection_blocker("HeyGen___voice_tts", args, None))
            disclosure = executor.dispatch_disclosure("HeyGen___voice_tts", args, None)
            self.assertIn("Alice Lee", disclosure)
        with patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": str(Path(self.directory.name) / "cold-lambda")}):
            poll = registry.dispatch("heygen", "get_voice_status", self.scope(clone["voice_id"]))
            self.assertEqual(poll["status"], "dry_run")
            speech = registry.dispatch("heygen", "voice_tts", args)
            self.assertTrue(speech["placeholder"])
            self.assertEqual(speech["cost_usd"], 0)

    def test_durable_scope_and_consent_cannot_be_forged(self):
        clone = registry.dispatch("heygen", "voice_clone", CLONE)
        self.assertEqual(len(self.store.objects), 1)
        key = next(iter(self.store.objects))
        original = json.loads(self.store.objects[key])
        for change in ({"account_id": "bob"}, {"consent_confirmed": False}, {"subjects": " "},
                       {"consent_record_id": ""}, {"mode": "professional"}, {"subjects": 123},
                       {"consent_confirmed": "true"}):
            with self.subTest(change=change):
                self.store.objects[key] = json.dumps({**original, **change}).encode()
                with self.assertRaises(ValueError):
                    registry.dispatch("heygen", "get_voice_status", self.scope(clone["voice_id"]))

    def test_storage_failure_cannot_fall_back_to_stale_local_consent(self):
        clone = registry.dispatch("heygen", "voice_clone", CLONE)
        with patch.object(self.store, "get_object", side_effect=OSError("offline interrupted read")):
            with self.assertRaisesRegex(RuntimeError, "storage"):
                registry.dispatch("heygen", "get_voice_status", self.scope(clone["voice_id"]))
            executor = object.__new__(GatewayExecutor)
            executor.studio = SimpleNamespace(prompt="Use HeyGen Voice to read in my cloned voice",
                user_id="alice", workspace_id="workspace", project_id="project")
            args = {**self.scope(clone["voice_id"]), "text": "Hello Alice.", "language": "en"}
            self.assertIn("storage", executor.selection_blocker("HeyGen___voice_tts", args, None))
        with patch.object(self.store, "put_object", side_effect=OSError("offline interrupted write")):
            with self.assertRaisesRegex(RuntimeError, "storage"):
                registry.dispatch("heygen", "voice_clone", CLONE)

    def test_mock_completed_wav_has_remote_audio_url_for_asset_registration(self):
        def download(url, output):
            with wave.open(str(output), "wb") as audio:
                audio.setparams((1, 2, 44100, 0, "NONE", "not compressed"))
                audio.writeframes(b"\0\0" * 44100)

        with patch.dict(os.environ, {"HEYGEN_VOICE_DRY_RUN": "false"}), \
             patch("providers.heygen.voice_contracts.live_blocker", return_value=None), \
             patch("providers.heygen.voice._request", return_value={"data": {"voice_id": "alice-voice"}}) as transport, \
             patch("providers.heygen.voice._download_wav", side_effect=download):
            registry.dispatch("heygen", "voice_clone", CLONE)
            transport.return_value = {"data": {"voice_id": "alice-voice", "mode": "instant", "status": "ACTIVE"}}
            registry.dispatch("heygen", "get_voice_status", self.scope("alice-voice"))
            transport.return_value = {"data": {"audio_url": "https://example.com/voice.wav", "duration": 1.0}}
            speech = registry.dispatch("heygen", "voice_tts", {
                **self.scope("alice-voice"), "text": "Hello Alice.", "language": "en",
            })
            self.assertEqual(speech["status"], "succeeded")
            self.assertIn("audio_url", speech)
            self.assertTrue(speech["audio_url"].startswith("https://offline-bucket.s3.amazonaws.com/"))
            self.assertTrue(any(key.endswith(".wav") for key in self.store.objects))
            self.assertFalse(speech["training_eligible"])
            request = StudioAgentRequest(prompt="Use HeyGen Voice to read in my cloned voice", user_id="alice",
                                        workspace_id="workspace", project_id="project")
            studio = _context_from_request(request)
            asset = {"kind": "audio", "version_id": "saved-audio", "provider": "heygen", "training_eligible": False}
            studio.asset_registrar = Mock(return_value=[asset])
            _append_harvested_event(studio, call_id="speech", name="HeyGen___voice_tts",
                                    arguments={}, output=speech)
            self.assertEqual(studio.working_assets["saved-audio"], asset)
            registered = studio.asset_registrar.call_args.kwargs["result"]
            self.assertEqual(registered["audio_url"], speech["audio_url"])
            for key, contents in self.store.objects.items():
                if key.endswith(".json"):
                    self.assertNotIn("signature=", contents.decode())

    def test_placeholder_never_registers_as_completed_studio_audio(self):
        clone = registry.dispatch("heygen", "voice_clone", CLONE)
        speech = registry.dispatch("heygen", "voice_tts", {
            **self.scope(clone["voice_id"]), "text": "Hello Alice.", "language": "en",
        })
        studio = _context_from_request(StudioAgentRequest(prompt="Use HeyGen Voice"))
        studio.asset_registrar = Mock()
        _append_harvested_event(studio, call_id="preview", name="HeyGen___voice_tts",
                                arguments={}, output=speech)
        studio.asset_registrar.assert_not_called()


class HeyGenVoiceNativeBoundaries(unittest.IsolatedAsyncioTestCase):
    async def test_studio_context_exposes_authenticated_voice_scope(self):
        request = StudioAgentRequest(prompt="Clone my voice and read this script", user_id="alice",
                                    workspace_id="workspace", project_id="project")

        def inspect_context(messages, tools):
            context = json.loads(messages[-1].text)
            self.assertEqual({key: context[key] for key in ("user_id", "workspace_id", "project_id")},
                             {"user_id": "alice", "workspace_id": "workspace", "project_id": "project"})
            self.assertEqual(context["capabilities"][0]["model"], "heygen-voice-1")
            self.assertIn("UNVERIFIED", context["capabilities"][0]["price"]["verification"])
            self.assertEqual(context["capabilities"][0]["price"]["rates"], {
                "list_usd_per_million_characters": "unknown", "instant_clone_list_usd": "unknown",
            })
            self.assertEqual(context["capabilities"][0]["price"]["currency_unit"], "USD")
            return final()

        with patch.dict(os.environ, {**GATE, "AWS_S3_BUCKET": ""}):
            await run_with_servers(request, _context_from_request(request), [Gateway(tools=[])],
                model=ScriptedModel([call("read_studio_context", {}, "context"), inspect_context]))

    async def test_clone_native_approval_and_fresh_resume_dispatch_or_reject(self):
        from mcp import Tool

        for decision in ("approve", "reject"):
            with self.subTest(decision=decision), tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
                **GATE, "AWS_S3_BUCKET": "", "RENDERHAUS_OUTCOME_DIR": directory,
            }):
                request = StudioAgentRequest(prompt="Use HeyGen Voice to clone my voice", user_id="alice",
                    workspace_id="workspace", project_id="project", conversation_id=f"voice-{decision}",
                    job_id=f"voice-{decision}")
                gateway = Gateway([Tool(name="HeyGen___voice_clone", inputSchema={"type": "object"})],
                                  result={"status": "dry_run", "voice_id": "offline-voice", "cost_usd": 0})
                studio = _context_from_request(request)
                with self.assertRaises(StudioAgentApprovalRequired) as paused:
                    await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                        call("read_file", {"file_path": "/skills/audio-bed/SKILL.md"}, "skill"),
                        call("call_audio_tool", {"tool_name": "HeyGen___voice_clone", "arguments": CLONE}, "clone"),
                    ]))
                gateway.call_tool.assert_not_awaited()
                approval = paused.exception.approvals[0]
                for phrase in ("Alice Lee", "uploaded to HeyGen", "training", "unknown", "$0.00"):
                    self.assertIn(phrase.lower(), approval.description.lower())
                from server import run_billing
                from server.studio_state import StudioRepository

                repository = StudioRepository(Path(directory) / "studio.sqlite3", Path(directory) / "media")
                with patch.object(run_billing, "billing_applies", return_value=False):
                    card = run_billing.public_approvals(repository, run_id=request.job_id, user_id="alice",
                        execution_status="awaiting_approval", error_type=None,
                        raw_approvals=[approval.model_dump()])[0]
                for phrase in ("Alice Lee", "uploaded to HeyGen", "training", "unknown", "$0.00"):
                    self.assertIn(phrase.lower(), card["message"].lower())
                self.assertNotIn("model", card)
                self.assertNotIn("provider", card)
                resumed = request.model_copy(update={
                    "session_items": json.loads(json.dumps(studio.session_items)), "resume_state": paused.exception.state,
                    "approval_decisions": [StudioApprovalDecision(call_id=approval.call_id, decision=decision)],
                })
                await run_with_servers(resumed, _context_from_request(resumed), [gateway], model=ScriptedModel([final()]))
                if decision == "approve":
                    gateway.call_tool.assert_awaited_once_with("HeyGen___voice_clone", CLONE)
                else:
                    gateway.call_tool.assert_not_awaited()
