from __future__ import annotations

import copy
import importlib
import json
import os
import io
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import httpx


CLIENT = httpx.Client
ROOT = "https://api.sync.so/v2"
SOURCE = "https://assets.sync.so/source.mp4"
PREVIEW = "https://assets.sync.so/preview.wav?signature=private-preview"
OUTPUT = "https://assets.sync.so/output.mp4"
TRANSCRIPT = {
    "segments": [{"id": "s1", "words": [
        {"id": "w1", "text": "Hello", "startMs": 0, "endMs": 500},
        {"id": "w2", "text": "world", "startMs": 600, "endMs": 1000},
        {"id": "w3", "text": "today", "startMs": 1100, "endMs": 1600},
    ]}], "speakerCount": 1, "language": "en",
}
BASE = {"source_video_url": SOURCE, "source_duration_seconds": 2.0,
        "speaker_count": 1, "subjects": "Consented presenter and source voice",
        "consent_confirmed": True}
EDITS = [{"kind": "change", "wordId": "w2", "replacement": "Renderhaus"}]
MP4 = (Path(__file__).parent / "fixtures" / "sync-video.mp4").read_bytes()


class DialogueEditTests(unittest.TestCase):
    def setUp(self):
        self.dialogue = importlib.import_module("providers.sync.dialogue")
        self.api = importlib.import_module("providers.sync.api")
        self.contracts = importlib.import_module("providers.sync.dialogue_contracts")
        self.directory = tempfile.TemporaryDirectory(prefix="dialogue-offline-")
        self.addCleanup(self.directory.cleanup)
        environment = patch.dict(os.environ, {
            "SYNC_DRY_RUN": "false", "SYNC_TRANSPORT": "fal", "SYNC_MODEL": "sync-3",
            "SYNC_API_KEY": "offline-key", "SYNC_DIRECT_AUTHORIZED": "true",
            "SYNC_BILLING_PLAN": "legacy_base", "FAL_DRY_RUN": "true",
            "RENDERHAUS_MEDIA_DIR": self.directory.name,
            "SYNC_DIALOGUE_PREVIEW_COST_CENTS": "100",
        }, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.requests = []
        self.routes = []
        self.transport = httpx.MockTransport(self.handle_request)
        client_patch = patch.object(httpx, "Client", self.mock_client)
        client_patch.start()
        self.addCleanup(client_patch.stop)
        stream_patch = patch.object(httpx, "stream", self.mock_stream)
        stream_patch.start()
        self.addCleanup(stream_patch.stop)

    def mock_client(self, *args, **kwargs):
        return CLIENT(*args, transport=self.transport, **kwargs)

    @contextmanager
    def mock_stream(self, method, url, **kwargs):
        with CLIENT(transport=self.transport) as client:
            with client.stream(method, url, **kwargs) as response:
                yield response

    def handle_request(self, request):
        self.requests.append(request)
        self.assertTrue(self.routes, f"Unexpected request {request.method} {request.url.path}")
        method, url, response = self.routes.pop(0)
        self.assertEqual((request.method, str(request.url)), (method, url))
        if isinstance(response, Exception):
            raise response
        return response

    def route(self, method, suffix, payload, status=200):
        self.routes.append((method, ROOT + suffix, httpx.Response(status, json=payload)))

    def transcription(self, **overrides):
        return {"id": "transcript_1", "status": "COMPLETED", "sourceVideoUrl": SOURCE,
                "sourceStartMs": 0, "sourceEndMs": 2000, "transcript": copy.deepcopy(TRANSCRIPT),
                "speakerCount": 1, **overrides}

    def preview(self, **overrides):
        return {"id": "edit_1", "status": "COMPLETED", "sourceVideoUrl": SOURCE,
                "sourceStartMs": 0, "sourceEndMs": 2000, "edits": EDITS,
                "segmentLipsyncEnabled": True, "sectionExpansionEnabled": True,
                "previewAudioUrl": PREVIEW, "previewDurationMs": 2100, "voiceId": "voice_1",
                "sourceTranscript": TRANSCRIPT, "resultTranscript": TRANSCRIPT,
                "resultSlots": [{"kind": "change", "outputStartMs": 0, "outputDurationMs": 2100}],
                **overrides}

    def create(self, **overrides):
        return self.dialogue.create_dialogue_edit(**{
            **BASE, "transcription_id": "transcript_1", "edits": copy.deepcopy(EDITS),
            "action_id": "action_1", **overrides,
        })

    def video(self, **overrides):
        return self.dialogue.create_dialogue_video(**{
            **BASE, "dialogue_edit_id": "edit_1", "source_fps": 25.0,
            "preview_reviewed": True, "preview_duration_seconds": 2.1, "idempotency_key": "video-action_1", **overrides,
        })

    def create_routes(self, payload=None):
        self.route("GET", "/transcriptions/transcript_1", self.transcription())
        self.route("POST", "/dialogue-edits", payload or self.preview(status="PENDING"), 201)

    def test_five_tools_integrate_with_existing_sync_poll(self):
        names = {"transcribe_video", "get_transcription", "create_dialogue_edit",
                 "get_dialogue_edit", "create_dialogue_video"}
        self.assertTrue(names <= set(self.api.TOOL_HANDLERS))
        self.assertIs(self.api.TOOL_HANDLERS["get_video_task"], self.api.get_video_task)

    def test_transcribe_sends_whole_video_and_preserves_vendor_id(self):
        self.route("POST", "/transcriptions", {"id": "transcript_1", "status": "PENDING"}, 201)
        result = self.dialogue.transcribe_video(**BASE)
        self.assertEqual(result["transcription_id"], "transcript_1")
        self.assertEqual(result["status"], "queued")
        self.assertEqual(json.loads(self.requests[0].content), {"sourceVideoUrl": SOURCE, "maxSourceSeconds": 600})
        self.assertEqual(self.requests[0].headers["x-api-key"], "offline-key")

    def test_get_preserves_raw_transcript_and_optional_fields(self):
        self.route("GET", "/transcriptions/transcript_1", self.transcription(difficulty="hard"))
        result = self.dialogue.get_transcription("transcript_1")
        self.assertEqual(result["transcript"], TRANSCRIPT)
        self.assertEqual(result["difficulty"], "hard")

    def test_contract_rejects_invalid_source_consent_speaker_duration_before_io(self):
        changes = [
            {"consent_confirmed": x} for x in (False, "true", 1, None)
        ] + [{"speaker_count": x} for x in (0, 2, True, "1")]
        changes += [{"source_duration_seconds": x} for x in (0, -1, 601, float("inf"), True, "2")]
        changes += [{"source_video_url": x} for x in (
            "https://other.test/source.mp4", "https://assets.sync.so.evil.test/a",
            "http://assets.sync.so/a", "https://user:secret@assets.sync.so/a",
            "https://assets.sync.so:444/a", "https://assets.sync.so/a#fragment",
        )]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.dialogue.transcribe_video(**{**BASE, **change})
        self.assertEqual(self.requests, [])
        self.assertEqual(list(Path(self.directory.name).rglob("*.json")), [])

    def test_direct_authorization_applies_to_every_endpoint(self):
        os.environ["SYNC_DIRECT_AUTHORIZED"] = "false"
        for call in (lambda: self.dialogue.transcribe_video(**BASE), self.create,
                     lambda: self.dialogue.get_transcription("transcript_1"),
                     lambda: self.dialogue.get_dialogue_edit("edit_1"), self.video):
            with self.assertRaisesRegex(ValueError, "permission"):
                call()
        self.assertEqual(self.requests, [])

    def test_dry_default_ignores_fal_flag_and_has_no_http(self):
        del os.environ["SYNC_DRY_RUN"]
        for call in (lambda: self.dialogue.transcribe_video(**BASE), self.create,
                     lambda: self.dialogue.get_transcription("transcript_1"),
                     lambda: self.dialogue.get_dialogue_edit("edit_1"), self.video):
            self.assertEqual(call()["status"], "dry_run")
        self.assertEqual(self.requests, [])

    def test_preview_forwards_unchanged_transcript_and_nested_edits(self):
        self.create_routes()
        result = self.create()
        body = json.loads(self.requests[1].content)
        self.assertEqual(body, {"sourceVideoUrl": SOURCE, "transcript": TRANSCRIPT, "edits": EDITS})
        self.assertEqual(result["dialogue_edit_id"], "edit_1")
        self.assertEqual(result["status"], "queued")

    def test_preview_requires_known_completed_whole_single_speaker_transcript(self):
        variants = [self.transcription(status="PROCESSING"), self.transcription(sourceVideoUrl=SOURCE + "?changed=1"),
                    self.transcription(sourceStartMs=10), self.transcription(sourceEndMs=1500),
                    self.transcription(speakerCount=2), self.transcription(transcript={**TRANSCRIPT, "speakerCount": 2})]
        for index, payload in enumerate(variants):
            self.route("GET", "/transcriptions/transcript_1", payload)
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.create(action_id=f"invalid_{index}")
        self.assertTrue(all(request.method == "GET" for request in self.requests))

    def test_edits_validate_ids_contiguous_removal_conflicts_and_window_fields(self):
        invalid = [[], [{"kind": "change", "wordId": "missing", "replacement": "x"}],
                   [{"kind": "change", "wordId": "w1", "replacement": " "}],
                   [{"kind": "remove", "wordIds": ["w1", "w3"]}],
                   [{"kind": "remove", "wordIds": ["w1", "w1"]}],
                   EDITS * 2, EDITS + [{"kind": "remove", "wordIds": ["w2"]}],
                   [{"kind": "change", "wordId": "w1", "replacement": "x", "sourceStartMs": 10}],
                   EDITS * 101]
        for index, edits in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.contracts.validate_edits(TRANSCRIPT, edits, 2.0)
        self.assertEqual(self.requests, [])

    def test_valid_remove_and_pronunciation_pass_through(self):
        edits = [{"kind": "change", "wordId": "w1", "replacement": "Hi", "pronunciation": "hai"},
                 {"kind": "remove", "wordIds": ["w2", "w3"]}]
        self.create_routes()
        self.create(edits=edits)
        self.assertEqual(json.loads(self.requests[1].content)["edits"], edits)

    def test_transcript_word_timings_and_duplicate_ids_refuse_before_post(self):
        for index, change in enumerate(({"endMs": 0}, {"startMs": -1}, {"endMs": 3000}, {"id": "w2"}, {"startMs": True})):
            transcript = copy.deepcopy(TRANSCRIPT)
            transcript["segments"][0]["words"][0].update(change)
            self.route("GET", "/transcriptions/transcript_1", self.transcription(transcript=transcript))
            with self.assertRaises(ValueError):
                self.create(action_id=f"timing_{index}")
        self.assertTrue(all(request.method == "GET" for request in self.requests))

    def test_preview_timeout_is_unknown_and_never_retried_after_restart(self):
        self.route("GET", "/transcriptions/transcript_1", self.transcription())
        self.routes.append(("POST", ROOT + "/dialogue-edits", httpx.ReadTimeout("lost after send")))
        first = self.create()
        self.assertEqual(first["status"], "submission_unknown")
        self.assertEqual(first["next_action"], "check_status_or_ask_user")
        self.assertIn("check status", first["note"].lower())
        self.dialogue = importlib.reload(self.dialogue)
        self.assertEqual(self.create()["status"], "submission_unknown")
        self.assertEqual(sum(r.method == "POST" for r in self.requests), 1)

    def test_connection_drop_and_write_timeout_do_not_retry(self):
        for index, error in enumerate((httpx.WriteTimeout("lost"), httpx.RemoteProtocolError("dropped"), httpx.ReadError("dropped"))):
            self.route("GET", "/transcriptions/transcript_1", self.transcription())
            self.routes.append(("POST", ROOT + "/dialogue-edits", error))
            result = self.create(action_id=f"unknown_{index}")
            self.assertEqual(result["status"], "submission_unknown")
            self.assertEqual(self.create(action_id=f"unknown_{index}")["status"], "submission_unknown")
        self.assertEqual(sum(r.method == "POST" for r in self.requests), 3)

    def test_malformed_success_never_retries(self):
        for index, response in enumerate((httpx.Response(201, content=b"broken"), httpx.Response(201, json={"status": "PENDING"}))):
            self.route("GET", "/transcriptions/transcript_1", self.transcription())
            self.routes.append(("POST", ROOT + "/dialogue-edits", response))
            self.assertEqual(self.create(action_id=f"malformed_{index}")["status"], "submission_unknown")
            self.assertEqual(self.create(action_id=f"malformed_{index}")["status"], "submission_unknown")
        self.assertEqual(sum(r.method == "POST" for r in self.requests), 2)

    def test_same_action_reuses_id_and_changed_payload_refuses(self):
        self.create_routes()
        first = self.create()
        self.assertEqual(self.create()["dialogue_edit_id"], first["dialogue_edit_id"])
        with self.assertRaisesRegex(ValueError, "different"):
            self.create(edits=[{"kind": "remove", "wordIds": ["w1"]}])
        self.assertEqual(sum(r.method == "POST" for r in self.requests), 1)

    def test_persistence_failure_before_post_prevents_paid_io(self):
        self.route("GET", "/transcriptions/transcript_1", self.transcription())
        with patch.object(self.api, "_write", side_effect=self.api.SyncStoreError("offline failure")):
            with self.assertRaises(self.api.SyncStoreError):
                self.create()
        self.assertTrue(all(r.method == "GET" for r in self.requests))

    def test_lambda_requires_durable_store_before_paid_call(self):
        os.environ["AWS_LAMBDA_FUNCTION_NAME"] = "offline"
        with self.assertRaisesRegex(ValueError, "AWS_S3_BUCKET"):
            self.create()
        self.assertEqual(self.requests, [])

    def test_unknown_preview_cost_blocks_live_but_dry_can_preview(self):
        with patch.object(self.contracts, "preview_quote_cents", side_effect=ValueError("unknown preview cost")):
            with self.assertRaisesRegex(ValueError, "cost|price|quote"):
                self.create()
            os.environ["SYNC_DRY_RUN"] = "true"
            self.assertEqual(self.create()["status"], "dry_run")
        self.assertEqual(self.requests, [])

    def test_signed_urls_never_persist(self):
        source = SOURCE + "?signature=private-source"
        self.route("GET", "/transcriptions/transcript_1", self.transcription(sourceVideoUrl=source))
        self.route("POST", "/dialogue-edits", self.preview(sourceVideoUrl=source), 201)
        self.create(source_video_url=source)
        for path in Path(self.directory.name).rglob("*.json"):
            value = path.read_text()
            self.assertNotIn("private-source", value)
            self.assertNotIn("private-preview", value)
            self.assertNotIn("offline-key", value)

    def test_partial_completion_remains_visible_and_requires_acceptance(self):
        self.route("GET", "/dialogue-edits/edit_1", self.preview(status="COMPLETED_PARTIAL"))
        result = self.dialogue.get_dialogue_edit("edit_1")
        self.assertEqual(result["status"], "completed_partial")
        self.assertTrue(result["partial_completion"])
        self.assertIn("warning", result)
        self.assertEqual(result["previewAudioUrl"], PREVIEW)
        self.route("GET", "/dialogue-edits/edit_1", self.preview(status="COMPLETED_PARTIAL"))
        with self.assertRaisesRegex(ValueError, "partial"):
            self.video()
        self.assertTrue(all(r.method == "GET" for r in self.requests))

    def test_generation_requires_review_rollouts_and_same_source(self):
        with self.assertRaises(ValueError):
            self.video(preview_reviewed=False)
        self.assertEqual(self.requests, [])
        for payload in (self.preview(sourceVideoUrl=SOURCE + "?changed=1"), self.preview(status="PROCESSING")):
            self.route("GET", "/dialogue-edits/edit_1", payload)
            with self.assertRaises(ValueError):
                self.video()
        self.assertTrue(all(r.method == "GET" for r in self.requests))

    def test_missing_rollout_falls_back_without_paid_submission(self):
        for changes in ({"segmentLipsyncEnabled": False}, {"sectionExpansionEnabled": False}):
            self.route("GET", "/dialogue-edits/edit_1", self.preview(**changes))
            result = self.video()
            self.assertEqual(result["status"], "requires_audio_fallback")
            self.assertEqual(result["next_tool"], "Sync___lipsync_video")
            self.assertIn("independently", result["note"])
        self.assertTrue(all(r.method == "GET" for r in self.requests))

    def test_saved_video_quote_matches_current_official_frame_rate(self):
        from server.billing_rates import cost_for

        self.route("GET", "/dialogue-edits/edit_1", self.preview())
        self.route("POST", "/generate", {"id": "generation_1", "status": "PENDING"}, 201)
        result = self.video()
        quote = cost_for("sync", "create_dialogue_video", {**BASE, "dialogue_edit_id": "edit_1",
            "source_fps": 25.0, "preview_duration_seconds": 2.1, "preview_reviewed": True,
            "idempotency_key": "video-action_1"})
        self.assertEqual(result["estimated_cost_usd"], quote.provider_cents / 100)

    def test_video_body_idempotency_and_existing_download_poll(self):
        self.route("GET", "/dialogue-edits/edit_1", self.preview())
        self.route("POST", "/generate", {"id": "generation_1", "status": "PENDING"}, 201)
        result = self.video(source_width=1280, source_height=720)
        body = json.loads(self.requests[1].content)
        self.assertEqual(body, {"model": "sync-3", "input": [{"type": "video", "url": SOURCE}], "dialogueEdit": {"id": "edit_1"}})
        self.assertEqual(self.requests[1].headers["Idempotency-Key"], "video-action_1")
        self.route("GET", "/generate/generation_1", {"id": "generation_1", "status": "COMPLETED", "outputUrl": OUTPUT})
        self.routes.append(("GET", OUTPUT, httpx.Response(200, content=MP4)))
        completed = self.api.get_video_task(result["job_id"], download=True)
        self.assertEqual(completed["status"], "succeeded")
        self.assertTrue(Path(completed["output_path"]).is_file())
        self.assertTrue(completed["downloaded"])

    def test_generation_partial_explicit_acceptance(self):
        self.route("GET", "/dialogue-edits/edit_1", self.preview(status="COMPLETED_PARTIAL"))
        self.route("POST", "/generate", {"id": "generation_1", "status": "PENDING"}, 201)
        self.assertEqual(self.video(accept_partial=True)["status"], "queued")

    def test_generation_lost_response_reuses_unknown_saved_job(self):
        self.route("GET", "/dialogue-edits/edit_1", self.preview())
        self.routes.append(("POST", ROOT + "/generate", httpx.ReadTimeout("lost")))
        result = self.video()
        self.assertEqual(result["status"], "submission_unknown")
        self.assertEqual(self.video()["job_id"], result["job_id"])
        self.assertEqual(sum(r.method == "POST" for r in self.requests), 1)

    def test_422_retime_requests_fallback_without_submitting_it(self):
        for operation in ("preview", "video"):
            if operation == "preview":
                self.route("GET", "/transcriptions/transcript_1", self.transcription())
                self.route("POST", "/dialogue-edits", {"errorCode": "dialogue_edit_retime_required"}, 422)
                result = self.create()
            else:
                self.route("GET", "/dialogue-edits/edit_1", self.preview())
                self.route("POST", "/generate", {"errorCode": "dialogue_edit_retime_required"}, 422)
                result = self.video()
            self.assertEqual(result["status"], "requires_audio_fallback")
            self.assertEqual(result["next_tool"], "Sync___lipsync_video")
            self.assertIn("approval", result["note"].lower())
        self.assertEqual(sum(r.method == "POST" for r in self.requests), 2)

    def test_422_removal_refuses_with_safe_section_and_no_vendor_message(self):
        self.route("GET", "/transcriptions/transcript_1", self.transcription())
        self.route("POST", "/dialogue-edits", {
            "errorCode": "dialogue_edit_removal_too_large", "message": "secret=private",
            "dialogueEditSection": {"slotIndex": 1, "sourceStartMs": 0, "sourceDurationMs": 1000, "url": PREVIEW},
        }, 422)
        result = self.create()
        self.assertEqual(result["status"], "refused")
        self.assertEqual(result["errorCode"], "dialogue_edit_removal_too_large")
        self.assertEqual(result["dialogueEditSection"], {"slotIndex": 1, "sourceStartMs": 0, "sourceDurationMs": 1000})
        self.assertNotIn("private", json.dumps(result))

    def test_foreign_voice_hint_is_ignored(self):
        self.create_routes()
        result = self.create(voice_id="other_voice")
        self.assertNotIn("voiceId", json.loads(self.requests[1].content))
        self.assertIn("warning", result)

    def test_voice_reuse_requires_prior_same_source_and_matching_voice(self):
        self.route("GET", "/transcriptions/transcript_1", self.transcription())
        self.route("GET", "/dialogue-edits/earlier_1", self.preview(id="earlier_1"))
        self.route("POST", "/dialogue-edits", self.preview(status="PENDING"), 201)
        self.create(voice_id="voice_1", rerun_of_job_id="earlier_1")
        body = json.loads(self.requests[2].content)
        self.assertEqual(body["voiceId"], "voice_1")
        self.assertEqual(body["rerunOfJobId"], "earlier_1")

    def test_video_idempotency_contract(self):
        for value in ("", "spaces forbidden", "x" * 129, "unicodeé", True):
            with self.assertRaises(ValueError):
                self.video(idempotency_key=value)
        with self.assertRaises(ValueError):
            self.video(source_width=1280)
        self.assertEqual(self.requests, [])


    def test_full_transcribe_preview_generate_flow_uses_only_direct_endpoints(self):
        self.route("POST", "/transcriptions", {"id": "transcript_1", "status": "PENDING"}, 201)
        transcription_id = self.dialogue.transcribe_video(**BASE)["transcription_id"]
        self.route("GET", "/transcriptions/transcript_1", self.transcription())
        self.assertEqual(self.dialogue.get_transcription(transcription_id)["transcript"], TRANSCRIPT)
        self.create_routes()
        dialogue_id = self.create(transcription_id=transcription_id)["dialogue_edit_id"]
        self.route("GET", "/dialogue-edits/edit_1", self.preview())
        self.assertEqual(self.dialogue.get_dialogue_edit(dialogue_id)["previewAudioUrl"], PREVIEW)
        self.route("GET", "/dialogue-edits/edit_1", self.preview())
        self.route("POST", "/generate", {"id": "generation_1", "status": "PENDING"}, 201)
        job_id = self.video(dialogue_edit_id=dialogue_id)["job_id"]
        self.route("GET", "/generate/generation_1", {"id": "generation_1", "status": "COMPLETED", "outputUrl": OUTPUT})
        self.routes.append(("GET", OUTPUT, httpx.Response(200, content=MP4)))
        self.assertTrue(self.api.get_video_task(job_id, download=True)["downloaded"])
        self.assertTrue(all(request.url.host in {"api.sync.so", "assets.sync.so"} for request in self.requests))
        self.assertFalse(self.routes)

    def test_dry_handles_refuse_before_live_provider_io(self):
        os.environ["SYNC_DRY_RUN"] = "true"
        transcription = self.dialogue.transcribe_video(**BASE)
        dialogue = self.create(transcription_id=transcription["transcription_id"])
        self.assertTrue(transcription["transcription_id"].startswith("dry_transcription_"))
        self.assertTrue(dialogue["dialogue_edit_id"].startswith("dry_dialogue_"))
        self.assertEqual(self.dialogue.get_transcription(transcription["transcription_id"])["status"], "dry_run")
        self.assertEqual(self.dialogue.get_dialogue_edit(dialogue["dialogue_edit_id"])["status"], "dry_run")
        self.assertNotIn("previewAudioUrl", dialogue)
        os.environ["SYNC_DRY_RUN"] = "false"
        calls = [lambda: self.dialogue.get_transcription(transcription["transcription_id"]),
                 lambda: self.dialogue.get_dialogue_edit(dialogue["dialogue_edit_id"]),
                 lambda: self.create(transcription_id=transcription["transcription_id"]),
                 lambda: self.video(dialogue_edit_id=dialogue["dialogue_edit_id"])]
        for call in calls:
            with self.assertRaisesRegex(ValueError, "dry-run|Dry-run"):
                call()
        self.assertEqual(self.requests, [])

    def test_preview_duration_quote_and_actual_duration_must_agree(self):
        self.route("GET", "/dialogue-edits/edit_1", self.preview())
        with self.assertRaisesRegex(ValueError, "preview_duration_seconds"):
            self.video(preview_duration_seconds=2.0)
        self.assertTrue(all(request.method == "GET" for request in self.requests))

    def test_generation_source_transcript_must_be_single_speaker(self):
        self.route("GET", "/dialogue-edits/edit_1", self.preview(sourceTranscript={**TRANSCRIPT, "speakerCount": 2}))
        with self.assertRaisesRegex(ValueError, "speaker"):
            self.video()
        self.assertTrue(all(request.method == "GET" for request in self.requests))

    def test_lost_generation_poll_remains_unknown_without_http(self):
        self.route("GET", "/dialogue-edits/edit_1", self.preview())
        self.routes.append(("POST", ROOT + "/generate", httpx.ReadTimeout("lost")))
        job = self.video()
        self.assertEqual(self.api.get_video_task(job["job_id"])["status"], "submission_unknown")
        self.assertEqual(sum(request.method == "POST" for request in self.requests), 1)

    def test_accepted_preview_is_preserved_after_metadata_write_failure(self):
        self.create_routes()
        original = self.api._write
        calls = 0

        def interrupted_write(record, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise self.api.SyncStoreError("offline interrupted save")
            return original(record, **kwargs)

        with patch.object(self.api, "_write", side_effect=interrupted_write):
            result = self.create()
        self.assertEqual(result["dialogue_edit_id"], "edit_1")
        self.assertTrue(result["persistence_error"])
        self.assertEqual(self.create()["dialogue_edit_id"], "edit_1")
        self.assertEqual(sum(request.method == "POST" for request in self.requests), 1)

    def test_accepted_preview_reuses_saved_id_without_new_quote(self):
        self.create_routes()
        self.create()
        del os.environ["SYNC_DIALOGUE_PREVIEW_COST_CENTS"]
        self.assertEqual(self.create()["dialogue_edit_id"], "edit_1")
        self.assertEqual(sum(request.method == "POST" for request in self.requests), 1)

    def test_preview_quote_is_operator_supplied_and_rejects_invalid_values(self):
        for value in ("", "0", "-1", "1.5", "NaN", "Infinity", "unknown"):
            os.environ["SYNC_DIALOGUE_PREVIEW_COST_CENTS"] = value
            with self.assertRaisesRegex(ValueError, "unknown"):
                self.contracts.preview_quote_cents()
        self.assertEqual(self.requests, [])

    def test_durable_store_claims_once_and_survives_local_loss(self):
        from botocore.exceptions import ClientError

        objects = {}
        claims = []

        class Store:
            def get_object(inner, *, Bucket, Key):
                if Key not in objects:
                    raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
                return {"Body": io.BytesIO(objects[Key])}

            def put_object(inner, *, Bucket, Key, Body, ContentType, IfNoneMatch=None):
                if IfNoneMatch:
                    claims.append(IfNoneMatch)
                    if Key in objects:
                        raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "PutObject")
                objects[Key] = Body

        os.environ["AWS_S3_BUCKET"] = "offline-bucket"
        self.create_routes()
        with patch.object(self.api, "_store_client", return_value=Store()):
            first = self.create()
            for path in Path(self.directory.name).rglob("*.json"):
                path.unlink()
            self.dialogue = importlib.reload(self.dialogue)
            self.assertEqual(self.create()["dialogue_edit_id"], first["dialogue_edit_id"])
        self.assertEqual(claims, ["*"])
        self.assertEqual(sum(request.method == "POST" for request in self.requests), 1)

    def test_idempotency_unknown_generation_id_is_recovered_for_polling(self):
        self.route("GET", "/dialogue-edits/edit_1", self.preview())
        self.route("POST", "/generate", {"errorCode": "IDEMPOTENCY_OUTCOME_UNKNOWN", "generationId": "generation_1"}, 409)
        result = self.video()
        self.assertEqual(result["status"], "submission_unknown")
        self.assertEqual(result["accepted_provider_handle"], "generation_1")
        self.route("GET", "/generate/generation_1", {"id": "generation_1", "status": "PROCESSING"})
        self.assertEqual(self.api.get_video_task(result["job_id"])["status"], "running")

    def test_gateway_nested_edits_are_typed_and_cannot_carry_audio_or_windows(self):
        from providers.contracts import enrich_tool_schema, validate_tool_arguments

        schema = {"type": "object", "properties": {
            key: {"type": "array" if key == "edits" else "boolean" if isinstance(value, bool) else "number" if isinstance(value, float) else "integer" if isinstance(value, int) else "string"}
            for key, value in {**BASE, "transcription_id": "transcript_1", "edits": EDITS, "action_id": "a"}.items()
        }}
        tool = enrich_tool_schema("sync", {"name": "create_dialogue_edit", "inputSchema": schema})
        arguments = {**BASE, "transcription_id": "transcript_1", "edits": EDITS, "action_id": "a"}
        self.assertEqual(validate_tool_arguments("sync", "create_dialogue_edit", arguments, tool["inputSchema"])["edits"], EDITS)
        for change in ({"audio_url": PREVIEW}, {"sourceStartMs": 10}, {"edits": [{"kind": "remove", "wordIds": [7]}]}):
            with self.assertRaises(ValueError):
                validate_tool_arguments("sync", "create_dialogue_edit", {**arguments, **change}, tool["inputSchema"])
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
