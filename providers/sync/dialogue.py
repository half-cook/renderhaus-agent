from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import uuid
from contextlib import contextmanager
from typing import Any, Literal

import httpx
from botocore.exceptions import ClientError

from providers.sync import contracts, dialogue_contracts as dc


API_ROOT = "https://api.sync.so/v2"
STATES = {
    "PENDING": "queued", "PROCESSING": "running", "COMPLETED": "succeeded",
    "COMPLETED_PARTIAL": "completed_partial", "FAILED": "failed",
}
FALLBACK_NOTE = (
    "This organization lacks the Dialogue Edits retiming rollout. Use regular Sync___lipsync_video "
    "with independently generated, consented replacement speech audio and a new cost approval. "
    "The dialogue preview audio is not forwarded as ordinary lip-sync audio."
)
UNKNOWN_NOTE = "Submission outcome is unknown. Check status or ask the user to reconcile the accepted job; never resubmit this action automatically."


class ActionRecord(dc.StrictModel):
    job_id: str
    mode: Literal["dialogue_edit_preview", "dialogue_edit_video"]
    fingerprint: str
    status: Literal["submitting", "submission_unknown", "queued", "running", "succeeded", "completed_partial", "failed", "refused", "requires_audio_fallback"] = "submitting"
    provider_id: str | None = None
    generation_job_id: str | None = None
    error_code: str | None = None
    section: dict[str, int] | None = None
    warning: str | None = None
    persistence_error: bool = False
    estimated_cost_usd: float | None = None
    partial_completion: bool = False


def _fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _action_id(kind: str, value: str) -> str:
    return f"sync:dialogue-{kind}:" + hashlib.sha256(value.encode()).hexdigest()


@contextmanager
def _action_lock(job_id: str):
    with api._lock(job_id):
        path, _ = api._paths(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.with_suffix(".lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _read_action(job_id: str) -> ActionRecord | None:
    path, _ = api._paths(job_id)
    remote = None
    if api._store_bucket():
        try:
            response = api._store_client().get_object(Bucket=api._store_bucket(), Key=api._store_key(job_id))
            body = response["Body"]
            try:
                remote = ActionRecord.model_validate_json(body.read())
            finally:
                body.close()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {"NoSuchKey", "404", "NotFound"}:
                raise api.SyncStoreError("Sync dialogue action store could not be read.") from None
        except Exception:
            raise api.SyncStoreError("Sync dialogue action store could not be read.") from None
    local = ActionRecord.model_validate_json(path.read_text()) if path.is_file() else None
    if remote and local:
        if remote.job_id != local.job_id or remote.fingerprint != local.fingerprint:
            raise api.SyncStoreError("Saved Sync dialogue action identities conflict.")
        if remote.provider_id and local.provider_id and remote.provider_id != local.provider_id:
            raise api.SyncStoreError("Saved Sync dialogue provider identities conflict.")
        if local.provider_id and not remote.provider_id:
            return local
    record = remote or local
    if record and record.job_id != job_id:
        raise api.SyncStoreError("Saved Sync dialogue action identity is invalid.")
    return record


def _save_result(record: ActionRecord) -> None:
    try:
        api._write(record)
    except api.SyncStoreError:
        record.persistence_error = True
        try:
            api._write_local(record)
        except OSError:
            pass


def _saved_summary(record: ActionRecord) -> dict[str, Any]:
    result = {
        "provider": "sync", "transport": "direct", "mode": record.mode,
        "status": "submission_unknown" if record.status == "submitting" else record.status,
        "action_handle": record.job_id, "estimated_cost_usd": record.estimated_cost_usd,
        **contracts.training_metadata("direct"),
    }
    if record.provider_id:
        result["dialogue_edit_id" if record.mode == "dialogue_edit_preview" else "accepted_provider_handle"] = record.provider_id
    if record.generation_job_id:
        result["job_id"] = record.generation_job_id
    if result["status"] == "submission_unknown":
        result["note"] = UNKNOWN_NOTE
    if record.error_code:
        result["errorCode"] = record.error_code
    if record.section:
        result["dialogueEditSection"] = record.section
    if result["status"] == "requires_audio_fallback":
        result.update(next_tool="Sync___lipsync_video", note=FALLBACK_NOTE)
    if record.warning:
        result["warning"] = record.warning
    if record.partial_completion:
        result["partial_completion"] = True
    if record.persistence_error:
        result.update(persistence_error=True, persistence_note="The provider accepted work but metadata storage failed. Retain this accepted handle and never blindly resubmit.")
    return result


def _gate() -> None:
    blocker = contracts.live_blocker({}, transport="direct")
    if blocker:
        raise ValueError(blocker)


def _dry(mode: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {
        "provider": "sync", "transport": "direct", "mode": mode, "status": "dry_run",
        "live_blocker": contracts.live_blocker({}, transport="direct"),
        "verification_status": "verified", **contracts.training_metadata("direct"),
        "note": "Preview only. No transcription, voice cloning, media fetching or generation was requested.",
    }
    if body is not None:
        result["request_preview"] = body
    return result


def _exchange(method: str, endpoint: str, body: dict[str, Any] | None = None, *, headers: dict[str, str] | None = None) -> httpx.Response:
    key = os.getenv("SYNC_API_KEY")
    if not key:
        raise RuntimeError("SYNC_API_KEY is required for live direct Sync calls.")
    with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
        return client.request(method, API_ROOT + endpoint, json=body, headers={
            "x-api-key": key, "Content-Type": "application/json", **(headers or {}),
        })


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError("Sync dialogue returned a non-JSON response.") from None
    if not isinstance(payload, dict):
        raise RuntimeError("Sync dialogue returned a non-object response.")
    return payload


def _refusal(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = _json(response)
    except RuntimeError:
        payload = {}
    code = payload.get("errorCode")
    if not isinstance(code, str):
        code = None
    allowed = {
        "dialogue_edit_retime_required", "dialogue_edit_unsupported", "dialogue_edit_removal_too_large",
        "dialogue_edit_source_mismatch", "dialogue_edit_audio_conflict", "IDEMPOTENCY_OUTCOME_UNKNOWN",
    }
    result: dict[str, Any] = {"status": "refused", "error": f"Sync Dialogue API refused the request (HTTP {response.status_code})."}
    if code in allowed or isinstance(code, str) and re.fullmatch(r"dialogue_edit_[a-z0-9_]{1,96}", code):
        result["errorCode"] = code
    section = payload.get("dialogueEditSection")
    if isinstance(section, dict):
        result["dialogueEditSection"] = {
            name: value for name, value in section.items()
            if name in {"slotIndex", "sourceStartMs", "sourceDurationMs"} and type(value) is int and value >= 0
        }
    if code == "dialogue_edit_retime_required":
        result.update(status="requires_audio_fallback", next_tool="Sync___lipsync_video", note=FALLBACK_NOTE)
    if code == "IDEMPOTENCY_OUTCOME_UNKNOWN":
        result.update(status="submission_unknown", note=UNKNOWN_NOTE)
        try:
            result["generation_id"] = api._request_id(payload.get("generationId"))
        except RuntimeError:
            pass
    return result


def _view(payload: dict[str, Any], id_field: str, expected_id: str | None = None) -> dict[str, Any]:
    provider_id = api._request_id(payload.get("id"))
    provider_status = payload.get("status")
    status = STATES.get(provider_status) if isinstance(provider_status, str) else None
    if status is None or expected_id is not None and provider_id != expected_id:
        raise RuntimeError("Sync dialogue returned an invalid task state or identifier.")
    result = {key: value for key, value in payload.items() if key != "error"}
    result.update({id_field: provider_id, "provider_status": payload["status"], "status": status,
                   "provider": "sync", "transport": "direct", **contracts.training_metadata("direct")})
    if payload.get("error"):
        result["error"] = "Sync reported a dialogue processing error; review the provider job before any new paid action."
    if status == "completed_partial":
        result.update(partial_completion=True, warning="Dialogue preview completed partially. Review the preview and reported failed edits before accepting it.")
    return result


def _get(endpoint: str, provider_id: str, field: str) -> dict[str, Any]:
    _gate()
    try:
        response = _exchange("GET", f"/{endpoint}/{provider_id}")
    except httpx.HTTPError:
        raise RuntimeError("Sync dialogue status could not be read. GET polling may be retried; no submission was made.") from None
    if response.is_error:
        return _refusal(response)
    return _view(_json(response), field, provider_id)


def transcribe_video(source_video_url: str, source_duration_seconds: float, speaker_count: int, subjects: str, consent_confirmed: bool) -> dict:
    """Transcribe one consented whole source up to ten minutes; poll get_transcription for original word IDs."""
    request = dc.SourceRequest.model_validate(locals())
    body = {"sourceVideoUrl": request.source_video_url, "maxSourceSeconds": 600}
    if api._is_dry("direct"):
        return {**_dry("dialogue_transcription", {**body, "sourceVideoUrl": contracts.reference_for_metadata(request.source_video_url)}), "transcription_id": "dry_transcription_" + uuid.uuid4().hex}
    _gate()
    try:
        response = _exchange("POST", "/transcriptions", body)
    except httpx.HTTPError:
        raise RuntimeError("Sync transcription submission outcome is unknown. Check status before submitting again.") from None
    return _refusal(response) if response.is_error else _view(_json(response), "transcription_id")


def get_transcription(transcription_id: str) -> dict:
    """Read an existing Sync transcription without submitting or changing its upstream transcript."""
    request = dc.TranscriptionPoll.model_validate(locals())
    if api._is_dry("direct"):
        return {**_dry("dialogue_transcription"), "transcription_id": request.transcription_id}
    if request.transcription_id.startswith("dry_"):
        raise ValueError("A dry-run transcription ID cannot be used for live provider calls.")
    return _get("transcriptions", request.transcription_id, "transcription_id")


def get_dialogue_edit(dialogue_edit_id: str) -> dict:
    """Poll an existing dialogue preview; surface partial results and the cloned-voice WAV preview."""
    request = dc.DialoguePoll.model_validate(locals())
    if api._is_dry("direct"):
        return {**_dry("dialogue_edit_preview"), "dialogue_edit_id": request.dialogue_edit_id}
    if request.dialogue_edit_id.startswith("dry_"):
        raise ValueError("A dry-run dialogue edit ID cannot be used for live provider calls.")
    return _get("dialogue-edits", request.dialogue_edit_id, "dialogue_edit_id")


def create_dialogue_edit(
    source_video_url: str, transcription_id: str, edits: list[dict], source_duration_seconds: float,
    speaker_count: int, subjects: str, consent_confirmed: bool, action_id: str,
    voice_id: str | None = None, rerun_of_job_id: str | None = None,
) -> dict:
    """Preview only edited words in the consented source-cloned voice; never retry a lost paid submission."""
    request = dc.PreviewRequest.model_validate(locals())
    if api._is_dry("direct"):
        return {**_dry("dialogue_edit_preview", {"sourceVideoUrl": contracts.reference_for_metadata(source_video_url), "edits": edits}),
                "action_id": action_id, "transcription_id": transcription_id,
                "dialogue_edit_id": "dry_dialogue_" + uuid.uuid4().hex,
                "estimated_cost_usd": None, "pricing_note": "Official preview rate TODO; operator-confirmed quote required for live submission."}
    _gate()
    api._storage_gate()
    if request.transcription_id.startswith("dry_") or (request.rerun_of_job_id or "").startswith("dry_"):
        raise ValueError("Dry-run transcription and dialogue IDs cannot be used for live provider calls.")
    saved_id = _action_id("preview", request.action_id)
    fingerprint = _fingerprint(request.model_dump())
    with _action_lock(saved_id):
        record = _read_action(saved_id)
        if record:
            if record.fingerprint != fingerprint:
                raise ValueError("This action_id already refers to a different preview payload.")
            return _saved_summary(record)
        quote = dc.preview_quote_cents()
        transcription = get_transcription(request.transcription_id)
        if transcription.get("status") != "succeeded":
            raise ValueError("The source transcription must be COMPLETED before a dialogue preview.")
        dc.validate_whole_source(transcription, request)
        if "speakerCount" in transcription and (type(transcription["speakerCount"]) is not int or transcription["speakerCount"] != 1):
            raise ValueError("The upstream transcription contains multiple speakers.")
        raw_transcript = transcription.get("transcript")
        dc.validate_edits(raw_transcript, edits, request.source_duration_seconds)
        body = {"sourceVideoUrl": request.source_video_url, "sourceTranscript": raw_transcript, "edits": edits}
        warning = None
        if request.voice_id:
            if request.rerun_of_job_id:
                earlier = get_dialogue_edit(request.rerun_of_job_id)
                if earlier.get("sourceVideoUrl") == request.source_video_url and earlier.get("voiceId") == request.voice_id:
                    body.update(voiceId=request.voice_id, rerunOfJobId=request.rerun_of_job_id)
                else:
                    warning = "Foreign voice hint ignored. The preview uses the cloned voice from this source."
            else:
                warning = "Unverified voice hint ignored. The preview uses the cloned voice from this source."
        record = ActionRecord(job_id=saved_id, mode="dialogue_edit_preview", fingerprint=fingerprint,
                              warning=warning, estimated_cost_usd=quote / 100)
        api._write(record, create_only=True)
        try:
            response = _exchange("POST", "/dialogue-edits", body)
            if response.is_error:
                result = _refusal(response)
            else:
                result = _view(_json(response), "dialogue_edit_id")
                record.provider_id = result["dialogue_edit_id"]
        except (httpx.HTTPError, RuntimeError):
            result = {"status": "submission_unknown", "note": UNKNOWN_NOTE}
        record.status = result["status"]
        record.error_code, record.section = result.get("errorCode"), result.get("dialogueEditSection")
        record.partial_completion = result.get("partial_completion", False)
        _save_result(record)
        return {**result, **_saved_summary(record)}


def create_dialogue_video(
    source_video_url: str, dialogue_edit_id: str, source_duration_seconds: float, source_fps: float,
    speaker_count: int, subjects: str, consent_confirmed: bool, preview_reviewed: bool,
    preview_duration_seconds: float, idempotency_key: str, accept_partial: bool = False,
    source_width: int | None = None, source_height: int | None = None,
) -> dict:
    """Generate sync-3 video from an approved whole-source dialogue preview; poll the saved Sync video task."""
    request = dc.VideoRequest.model_validate(locals())
    body = {"model": "sync-3", "input": [{"type": "video", "url": request.source_video_url}], "dialogueEdit": {"id": request.dialogue_edit_id}}
    if api._is_dry("direct"):
        body["input"][0]["url"] = contracts.reference_for_metadata(request.source_video_url)
        return {**_dry("dialogue_edit_video", body), "job_id": f"sync:dry:{uuid.uuid4().hex}", "output_duration_seconds": request.preview_duration_seconds}
    _gate()
    api._storage_gate()
    if request.dialogue_edit_id.startswith("dry_"):
        raise ValueError("A dry-run dialogue edit ID cannot be used for live provider calls.")
    saved_id = _action_id("video", request.idempotency_key)
    fingerprint = _fingerprint(request.model_dump())
    with _action_lock(saved_id):
        record = _read_action(saved_id)
        if record:
            if record.fingerprint != fingerprint:
                raise ValueError("This idempotency_key already refers to a different generation payload.")
            return _saved_summary(record)
        preview = get_dialogue_edit(request.dialogue_edit_id)
        if preview.get("status") == "completed_partial" and not request.accept_partial:
            raise ValueError("The dialogue preview completed partially. Obtain explicit partial acceptance before generation.")
        if preview.get("status") not in {"succeeded", "completed_partial"}:
            raise ValueError("The dialogue preview must be completed and reviewed before video generation.")
        dc.validate_whole_source(preview, request)
        dc.validate_edits(preview.get("sourceTranscript"), preview.get("edits"), request.source_duration_seconds)
        if "speakerCount" in preview and (type(preview["speakerCount"]) is not int or preview["speakerCount"] != 1):
            raise ValueError("The upstream dialogue preview contains multiple speakers.")
        if preview.get("segmentLipsyncEnabled") is not True or preview.get("sectionExpansionEnabled") is not True:
            raise ValueError("Dialogue video requires segment lipsync and section expansion rollout. Use consented regular lip-sync with a new cost approval.")
        duration_ms = preview.get("previewDurationMs")
        if type(duration_ms) is not int or duration_ms <= 0 or abs(duration_ms / 1000 - request.preview_duration_seconds) > 1e-6:
            raise ValueError("preview_duration_seconds must match the completed previewDurationMs before quoting generation.")
        sync_request = contracts.SyncRequest.model_validate({
            "video_url": request.source_video_url, "audio_url": request.source_video_url,
            "source_duration_seconds": request.source_duration_seconds,
            "audio_duration_seconds": request.preview_duration_seconds, "source_fps": request.source_fps,
            "subjects": request.subjects, "consent_confirmed": True, "model": "sync-3",
            "sync_mode": "remap", "source_width": request.source_width, "source_height": request.source_height,
        })
        manifest = api._manifest(f"sync:direct:{uuid.uuid4().hex}", sync_request, "direct")
        manifest.mode = "dialogue_edit_video"
        manifest.dialogue_edit_id = request.dialogue_edit_id
        manifest.idempotency_key = request.idempotency_key
        manifest.partial_completion = preview.get("status") == "completed_partial"
        record = ActionRecord(job_id=saved_id, mode="dialogue_edit_video", fingerprint=fingerprint,
                              generation_job_id=manifest.job_id, estimated_cost_usd=manifest.estimated_cost_usd,
                              partial_completion=manifest.partial_completion)
        api._write(record, create_only=True)
        api._write(manifest)
        try:
            response = _exchange("POST", "/generate", body, headers={"Idempotency-Key": request.idempotency_key})
            if response.is_error:
                result = _refusal(response)
                provider_id = result.get("generation_id")
            else:
                payload = _json(response)
                provider_id = api._request_id(payload.get("id"))
                result = {"status": "failed" if payload.get("status") in ("FAILED", "REJECTED") else "queued"}
            if provider_id:
                manifest.request_id = provider_id
                manifest.status = "failed" if result["status"] == "failed" else "queued"
                manifest.error = "Sync dialogue generation failed." if manifest.status == "failed" else None
                manifest.submission_complete = True
                record.provider_id = provider_id
        except (httpx.HTTPError, RuntimeError):
            result = {"status": "submission_unknown", "note": UNKNOWN_NOTE}
        if not manifest.request_id:
            manifest.submission_unknown = result["status"] == "submission_unknown"
            manifest.status = "failed"
            manifest.error = UNKNOWN_NOTE if result["status"] == "submission_unknown" else "Dialogue generation was refused; retain the saved approval action."
        try:
            api._write(manifest)
        except api.SyncStoreError:
            api._preserve_accepted(manifest)
            record.persistence_error = True
        record.status = result["status"]
        record.error_code, record.section = result.get("errorCode"), result.get("dialogueEditSection")
        _save_result(record)
        return {**result, **api._summary(manifest), **_saved_summary(record)}


TOOL_HANDLERS = {name: globals()[name] for name in dc.TOOLS}

from providers.sync import api
