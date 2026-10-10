"""Project-scoped HeyGen Voice candidate. Live activation is deliberately blocked."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
import wave
import time

import httpx
from pathlib import Path

from providers.heygen import voice_contracts as contracts
from providers.heygen.contracts import reference_for_metadata


def dry_run() -> bool:
    return os.getenv("HEYGEN_VOICE_DRY_RUN", "true").lower() != "false"


def _guard_live(arguments: dict | None = None) -> None:
    if not dry_run() and (blocker := contracts.live_blocker(arguments)):
        raise ValueError(blocker)


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _scope(request: contracts.Scope) -> str:
    return _digest(request.model_dump(include={"account_id", "workspace_id", "project_id"}))


def _record_path(request: contracts.PollRequest) -> Path:
    return Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")) / "audio" / ".voices" / _scope(request) / (request.voice_id + ".json")


def _store_key(request: contracts.PollRequest) -> str:
    return f"renderhaus-heygen-voices/{_scope(request)}/{request.voice_id}.json"


def _write(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(content, indent=2) + "\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _save(request: contracts.PollRequest, record: dict) -> None:
    from providers.heygen.api import _bucket, _store_client

    try:
        _write(_record_path(request), record)
        if _bucket():
            _store_client().put_object(Bucket=_bucket(), Key=_store_key(request),
                                     Body=json.dumps(record).encode(), ContentType="application/json")
    except Exception:
        raise RuntimeError(f"HeyGen Voice clone storage failed; preserve voice_id {request.voice_id} and do not resubmit.") from None


def _read(request: contracts.PollRequest) -> dict:
    from providers.heygen.api import _bucket, _store_client

    content = None
    if _bucket():
        from botocore.exceptions import ClientError

        try:
            body = _store_client().get_object(Bucket=_bucket(), Key=_store_key(request))["Body"]
            try:
                content = body.read().decode()
            finally:
                body.close()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}:
                raise ValueError("Voice is not saved in this account and project scope.") from None
            raise RuntimeError("HeyGen Voice clone storage could not be read.") from None
        except Exception:
            raise RuntimeError("HeyGen Voice clone storage could not be read.") from None
    try:
        record = json.loads(content if content is not None else _record_path(request).read_text())
        if any(record[key] != getattr(request, key) for key in ("voice_id", "account_id", "workspace_id", "project_id")):
            raise ValueError
        contracts.CloneRequest.model_validate({key: record[key] for key in contracts.CloneRequest.model_fields})
        if record.get("status") not in {"dry_run", "queued", "running", "succeeded", "failed"}:
            raise ValueError
        return record
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("Voice is not an authorized saved instant clone in this account and project scope.") from None


def voice_clone(reference_audio_url: str, reference_duration_seconds: float, reference_size_bytes: int,
                reference_format: str, name: str, subjects: str, consent_confirmed: bool,
                consent_record_id: str, account_id: str, workspace_id: str, project_id: str,
                mode: str = "instant", language: str | None = None, similarity: str = "extra_high",
                remove_background_noise: bool = True, model: str | None = None) -> dict:
    """Preview one consented instant voice clone; save its handle only in the current account/project."""
    request = contracts.CloneRequest.model_validate(locals())
    _guard_live({"model": request.model})
    saved = request.model_dump()
    saved["reference_audio_url"] = reference_for_metadata(request.reference_audio_url)
    is_dry = dry_run()
    voice_id = "heygen_voice_dry_" + _digest(saved)[:32]
    if not is_dry:
        response = _request("POST", "/models/audio/voices", body=contracts.clone_body(request),
                            idempotency_key="renderhaus-voice-" + _digest(saved))
        voice_id = _data(response).get("voice_id")
        contracts.PollRequest.model_validate({**request.model_dump(include={"account_id", "workspace_id", "project_id"}), "voice_id": voice_id})
    record = {**saved, "voice_id": voice_id, "status": "dry_run" if is_dry else "queued", "used_reference_seconds": request.used_reference_seconds,
              "cost_usd": 0 if is_dry else None, "placeholder": is_dry, **contracts.PROVENANCE, "model": request.model}
    scope = contracts.PollRequest.model_validate({key: record[key] for key in ("voice_id", "account_id", "workspace_id", "project_id")})
    _save(scope, record)
    return {**record, "request_preview": {**contracts.clone_body(request),
            "audio": [{"type": "url", "url": saved["reference_audio_url"]}]},
            "note": (_note(request.model) if is_dry else "Accepted once; preserve this voice_id and poll without resubmitting.") + " Clone creation would return 202; poll get_voice_status until ACTIVE after activation."}


def _note(model: str) -> str:
    unknown = "UNVERIFIED model. " if model != contracts.DEFAULT_MODEL else ""
    return unknown + "Dry-run only. No reference upload, provider call or key read occurred. Prices unknown."


def get_voice_status(voice_id: str, account_id: str, workspace_id: str, project_id: str) -> dict:
    """Read one saved project clone preview; future live poll is GET /v3/models/audio/voices/{voice_id}."""
    request = contracts.PollRequest.model_validate(locals())
    record = _read(request)
    if record["status"] == "dry_run" or dry_run():
        return {**record, "status": "dry_run", "note": _note(record["model"])}
    _guard_live({"model": record["model"]})
    data = _data(_request("GET", f"/models/audio/voices/{request.voice_id}"))
    states = {"PENDING": "running", "ACTIVE": "succeeded", "FAILED": "failed"}
    if data.get("voice_id") != request.voice_id or data.get("mode") != "instant" or data.get("status") not in states:
        raise RuntimeError("HeyGen Voice poll returned a mismatched voice, mode or unknown status.")
    record["status"] = states[data["status"]]
    if record["status"] == "failed":
        record["error"] = "HeyGen instant clone failed; inspect the provider account before requesting a new clone."
    _save(request, record)
    return record


def voice_tts(voice_id: str, text: str, language: str, account_id: str, workspace_id: str,
              project_id: str, model: str | None = None, expressiveness_boost: float = 1.0) -> dict:
    """Save a deterministic silent WAV placeholder for project-owned instant-clone speech, never generated audio."""
    request = contracts.TTSRequest.model_validate(locals())
    record = _read(request)
    _guard_live({"model": request.model})
    output = _record_path(request).parents[2] / ("heygen_voice_" + _digest(request.model_dump())[:32] + ".wav")
    output.parent.mkdir(parents=True, exist_ok=True)
    if record["status"] != "dry_run" and not dry_run():
        if record["status"] != "succeeded":
            raise ValueError("Project voice is not ACTIVE; poll the saved clone before speech.")
        data = _data(_request("POST", "/models/audio/tts", body=contracts.tts_body(request)))
        url = data.get("audio_url")
        contracts.validate_media_reference(url, allow_asset=False)
        _download_wav(url, output)
        duration = _validate_wav(output)
        from providers.heygen.api import _bucket, _store_client

        artifact = {}
        if _bucket():
            key = f"renderhaus-heygen-voice-outputs/{_scope(request)}/{output.name}"
            try:
                store = _store_client()
                store.upload_file(Filename=str(output), Bucket=_bucket(), Key=key,
                                  ExtraArgs={"ContentType": "audio/wav"})
                artifact["audio_url"] = store.generate_presigned_url(
                    "get_object", Params={"Bucket": _bucket(), "Key": key}, ExpiresIn=3600)
                contracts.validate_media_reference(artifact["audio_url"], allow_asset=False)
            except Exception:
                raise RuntimeError("HeyGen Voice WAV storage failed; do not repeat synthesis.") from None
        return {**contracts.PROVENANCE, **artifact, "model": request.model, "provider": "heygen", "status": "succeeded",
                "voice_id": voice_id, "output_path": str(output), "duration_seconds": duration,
                "placeholder": False, "subjects": record["subjects"], "consent_record_id": record["consent_record_id"]}
    temporary = output.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        with wave.open(str(temporary), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(44100)
            audio.writeframes(b"\0\0" * 44100)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return {**contracts.PROVENANCE, "model": request.model, "provider": "heygen", "status": "dry_run",
            "voice_id": voice_id, "output_path": str(output), "duration_seconds": 1.0, "cost_usd": 0,
            "placeholder": True, "subjects": record["subjects"], "consent_record_id": record["consent_record_id"],
            "note": _note(request.model) + " Silent mock WAV, not synthesized speech. Do not deliver as completed media."}


def _request(method: str, path: str, **kwargs) -> dict:
    from providers.heygen.api import _request as heygen_request

    return heygen_request(method, path, **kwargs)


def _data(response: dict) -> dict:
    data = response.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("HeyGen Voice returned invalid resource data.")
    return data


def _validate_wav(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as audio:
            if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth(), audio.getcomptype()) != (44100, 1, 2, "NONE"):
                raise ValueError
            frames = audio.getnframes()
            if frames <= 0 or len(audio.readframes(frames)) != frames * 2:
                raise ValueError
            return frames / 44100
    except (OSError, EOFError, wave.Error, ValueError):
        raise RuntimeError("HeyGen Voice did not return a complete 44.1 kHz mono PCM16 WAV.") from None


def _download_wav(url: str, output: Path) -> None:
    from providers.heygen.api import _public_output

    contracts.validate_media_reference(url, allow_asset=False)
    temporary = output.with_suffix(f".{uuid.uuid4().hex}.part")
    deadline = time.monotonic() + 120
    try:
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False,
                          event_hooks={"request": [_public_output]}) as client:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise RuntimeError("HeyGen Voice WAV download failed; redirects are not followed.")
                size = 0
                with temporary.open("wb") as target:
                    for chunk in response.iter_bytes(1024 * 1024):
                        size += len(chunk)
                        if size > 256 * 1024 * 1024 or time.monotonic() > deadline:
                            raise RuntimeError("HeyGen Voice WAV exceeded size or time limits.")
                        target.write(chunk)
        _validate_wav(temporary)
        temporary.replace(output)
    except httpx.HTTPError:
        raise RuntimeError("HeyGen Voice WAV download failed.") from None
    finally:
        temporary.unlink(missing_ok=True)
