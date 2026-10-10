from __future__ import annotations

import ipaddress
import math
import os
import re
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import boto3
import httpx
from botocore.exceptions import ClientError
from pydantic import BaseModel, ConfigDict, Field

from providers.heygen import contracts
from providers.heygen.voice import voice_clone, voice_tts, get_voice_status
from providers.sync.media import validate_mp4


BASE_URL = "https://api.heygen.com/v3"
STATES = {"pending": "queued", "waiting": "queued", "processing": "running",
          "completed": "succeeded", "failed": "failed"}
MAX_VIDEO_BYTES = 512 * 1024 * 1024


class JobManifest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False, hide_input_in_errors=True)

    version: Literal[1] = 1
    provider: Literal["heygen"] = "heygen"
    job_id: str
    model: str
    status: Literal["dry_run", "submitting", "submission_unknown", "queued", "running", "succeeded", "failed"]
    avatar_id: str
    group_id: str | None = None
    provider_video_id: str | None = None
    duration_seconds: float = Field(gt=0, le=1800)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    actual_duration_seconds: float | None = Field(default=None, gt=0)
    subjects: str = Field(min_length=1)
    consent_confirmed: Literal[True]
    consent_record_id: str
    voice_id: str | None = None
    audio_reference: str | None = None
    artifact_key: str | None = None
    persistence_error: bool = False
    training_eligible: Literal[False] = False


def dry_run(arguments: dict[str, Any] | None = None) -> bool:
    return os.getenv("HEYGEN_DRY_RUN", "true").lower() != "false" or contracts.configured_model(arguments) != contracts.DEFAULT_MODEL


def _paths(job_id: str) -> tuple[Path, Path]:
    if not contracts.JOB_PATTERN.fullmatch(job_id):
        raise ValueError("Use the saved job_id returned by create_avatar_video.")
    video = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")) / "video"
    name = "heygen_" + job_id.rsplit(":", 1)[1]
    return video / ".tasks" / "heygen" / f"{name}.json", video / f"{name}.mp4"


def _bucket() -> str:
    return os.getenv("AWS_S3_BUCKET", "").strip()


def _store_client():
    return boto3.client("s3", region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1")


def _store_key(job_id: str) -> str:
    return "renderhaus-heygen-jobs/" + job_id.rsplit(":", 1)[1] + ".json"


def _artifact_key(job_id: str) -> str:
    return "renderhaus-heygen-outputs/" + job_id.rsplit(":", 1)[1] + ".mp4"


def _write_local(manifest: JobManifest) -> None:
    path, _ = _paths(manifest.job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(manifest.model_dump_json(indent=2))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _save(manifest: JobManifest) -> None:
    try:
        _write_local(manifest)
        if _bucket():
            _store_client().put_object(Bucket=_bucket(), Key=_store_key(manifest.job_id),
                                     Body=manifest.model_dump_json().encode(), ContentType="application/json")
    except Exception:
        raise RuntimeError("HeyGen job storage failed; preserve the saved job and do not resubmit.") from None


def _read(job_id: str) -> JobManifest:
    path, _ = _paths(job_id)
    content = None
    if _bucket():
        try:
            body = _store_client().get_object(Bucket=_bucket(), Key=_store_key(job_id))["Body"]
            try:
                content = body.read().decode()
            finally:
                body.close()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {"NoSuchKey", "404", "NotFound"}:
                raise RuntimeError("HeyGen durable job storage could not be read.") from None
        except Exception:
            raise RuntimeError("HeyGen durable job storage could not be read.") from None
    try:
        if content is None:
            content = path.read_text()
        manifest = JobManifest.model_validate_json(content)
        if path.is_file() and manifest.provider_video_id is None:
            local = JobManifest.model_validate_json(path.read_text())
            fields = ("job_id", "model", "avatar_id", "group_id", "duration_seconds", "subjects",
                      "consent_confirmed", "consent_record_id", "voice_id", "audio_reference")
            if any(getattr(local, field) != getattr(manifest, field) for field in fields):
                raise ValueError("Conflicting HeyGen job identities.")
            if local.provider_video_id:
                manifest = local
        if manifest.job_id != job_id or not manifest.subjects.strip():
            raise ValueError("Invalid saved HeyGen identity.")
        if job_id.startswith("heygen:live:"):
            if manifest.model != contracts.DEFAULT_MODEL or manifest.status == "dry_run":
                raise ValueError("Invalid saved HeyGen engine.")
        elif manifest.status != "dry_run":
            raise ValueError("Invalid saved dry-run job.")
        contracts.validate_id(manifest.avatar_id, "avatar_id")
        if manifest.provider_video_id:
            contracts.validate_id(manifest.provider_video_id, "provider_video_id")
        if not re.fullmatch(r"[A-Za-z0-9_:.-]{1,255}", manifest.consent_record_id):
            raise ValueError("Invalid saved consent record.")
        if manifest.artifact_key is not None and manifest.artifact_key != _artifact_key(job_id):
            raise ValueError("Invalid saved HeyGen artifact.")
    except (OSError, ValueError):
        raise ValueError("Saved HeyGen metadata is missing or invalid; no provider request was made.") from None
    return manifest


def _summary(manifest: JobManifest) -> dict[str, Any]:
    return {**manifest.model_dump(exclude={"artifact_key", "audio_reference"}),
            **contracts.TRAINING_METADATA, "downloaded": False}


def _request(method: str, path: str, *, body: dict[str, Any] | None = None,
             params: dict[str, Any] | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
    key = os.getenv("HEYGEN_API_KEY", "").strip()
    if not key:
        raise ValueError("HEYGEN_API_KEY must be configured for a live HeyGen request.")
    headers = {"x-api-key": key, "Accept": "application/json"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    try:
        with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = client.request(method, BASE_URL + path, headers=headers, json=body, params=params)
    except httpx.HTTPError:
        raise RuntimeError("HeyGen request failed at the HTTP boundary; no automatic retry was made.") from None
    if not response.is_success:
        raise RuntimeError(f"HeyGen request returned HTTP {response.status_code}; no automatic retry was made.")
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError("HeyGen returned invalid JSON.") from None
    if not isinstance(payload, dict) or payload.get("error"):
        raise RuntimeError("HeyGen returned an invalid or unsuccessful response.")
    return payload


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError("HeyGen returned invalid resource data.")
    return data


def _preflight(request: contracts.AvatarRequest) -> str:
    look = _data(_request("GET", f"/avatars/looks/{request.avatar_id}"))
    engines = look.get("supported_api_engines")
    if (look.get("id") != request.avatar_id or look.get("avatar_type") != "digital_twin"
            or look.get("status") != "completed" or not isinstance(engines, list)
            or contracts.DEFAULT_MODEL not in engines):
        raise ValueError("Live Avatar V requires a completed, eligible digital-twin look; no generation was submitted.")
    group_id = contracts.validate_id(look.get("group_id"), "avatar group_id")
    group = _data(_request("GET", f"/avatars/{group_id}"))
    if (group.get("id") != group_id or group.get("status") != "completed"
            or group.get("consent_status") != "accepted"):
        raise ValueError("HeyGen digital-twin group consent must be accepted and training completed; no generation was submitted.")
    return group_id


def _cost_estimate(request: contracts.AvatarRequest) -> float | None:
    from server.billing_rates import _with_fee, heygen_price_cents

    try:
        return _with_fee(math.ceil(heygen_price_cents(request.model_dump()))).total_cents / 100
    except ValueError:
        return None


def create_avatar_video(
    avatar_id: str, duration_seconds: float, subjects: str, consent_confirmed: bool,
    consent_record_id: str, script: str | None = None, voice_id: str | None = None,
    audio_url: str | None = None, language: str | None = None, resolution: str = "720p",
    aspect_ratio: str = "16:9", motion_prompt: str | None = None, model: str | None = None,
) -> dict[str, Any]:
    """Submit an authorized Avatar V presenter once; explicit consent and cost approval are required."""
    request = contracts.request_for(locals())
    preview = contracts.request_body(request)
    is_dry = dry_run({"model": request.model})
    job_id = f"heygen:{'dry' if is_dry else 'live'}:{uuid.uuid4().hex}"
    manifest = JobManifest(job_id=job_id, model=request.model, status="dry_run" if is_dry else "submitting",
                           avatar_id=request.avatar_id, duration_seconds=request.duration_seconds,
                           estimated_cost_usd=_cost_estimate(request),
                           subjects=request.subjects, consent_confirmed=request.consent_confirmed,
                           consent_record_id=request.consent_record_id, voice_id=request.voice_id,
                           audio_reference=contracts.reference_for_metadata(request.audio_url) if request.audio_url else None)
    if is_dry:
        _write_local(manifest)
        reason = "UNVERIFIED engine, dry-run only. " if request.model != contracts.DEFAULT_MODEL else ""
        return {**_summary(manifest), "request_preview": preview,
                "note": reason + "No HeyGen request was made. This input preview is not generated media."}
    if blocker := contracts.live_blocker({"model": request.model}):
        raise ValueError(blocker)
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME") and not _bucket():
        raise ValueError("Hosted live HeyGen requires AWS_S3_BUCKET for durable job storage before submission.")
    if request.audio_url and request.audio_url.startswith("renderhaus-asset://"):
        raise ValueError("Live HeyGen audio asset handles require the authorized Studio asset resolver before provider I/O.")
    manifest.group_id = _preflight(request)
    _save(manifest)
    try:
        data = _data(_request("POST", "/videos", body=preview, idempotency_key=job_id))
        manifest.provider_video_id = contracts.validate_id(data.get("video_id"), "provider_video_id")
        manifest.status = "queued"
    except (RuntimeError, ValueError):
        manifest.status = "submission_unknown"
        try:
            _save(manifest)
        except RuntimeError:
            manifest.persistence_error = True
        return {**_summary(manifest), "submission_unknown": True,
                "note": "Do not resubmit. Submission outcome is unknown; reconcile this saved handle with the HeyGen account."}
    try:
        _save(manifest)
    except RuntimeError:
        manifest.persistence_error = True
        try:
            _write_local(manifest)
        except OSError:
            pass
    return {**_summary(manifest), "poll_interval_seconds": 5,
            "note": ("Preserve both saved ids and do not resubmit; job storage needs reconciliation."
                     if manifest.persistence_error else "Poll get_video_status with this saved job_id; download=true saves the completed MP4.")}


def _validate_video(path: Path) -> None:
    try:
        validate_mp4(path)
    except (OSError, RuntimeError, ValueError):
        raise RuntimeError("HeyGen returned an invalid or truncated MP4 video.") from None


def _public_output(request: httpx.Request) -> None:
    contracts.validate_media_reference(str(request.url), allow_asset=False)
    try:
        addresses = socket.getaddrinfo(request.url.host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError
    except (OSError, ValueError):
        raise RuntimeError("HeyGen output host must resolve to public addresses.") from None


def _download(url: str, output: Path) -> None:
    contracts.validate_media_reference(url, allow_asset=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f".{uuid.uuid4().hex}.part")
    deadline = time.monotonic() + 120
    try:
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False,
                          event_hooks={"request": [_public_output]}) as client:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise RuntimeError("HeyGen MP4 download was unavailable; redirects are not followed.")
                content_type = response.headers.get("content-type", "").split(";", 1)[0]
                if content_type and content_type not in {"video/mp4", "application/octet-stream"}:
                    raise RuntimeError("HeyGen download did not return MP4 video content.")
                size = 0
                with temporary.open("wb") as target:
                    for chunk in response.iter_bytes(1024 * 1024):
                        size += len(chunk)
                        if size > MAX_VIDEO_BYTES or time.monotonic() > deadline:
                            raise RuntimeError("HeyGen MP4 download exceeded the size or time limit.")
                        target.write(chunk)
        _validate_video(temporary)
        temporary.replace(output)
    except httpx.HTTPError:
        raise RuntimeError("HeyGen video download failed; poll the saved job again without resubmitting.") from None
    finally:
        temporary.unlink(missing_ok=True)


def _completed(manifest: JobManifest, output: Path) -> dict[str, Any]:
    result = {**_summary(manifest), "downloaded": True, "output_path": str(output)}
    if manifest.artifact_key and _bucket():
        try:
            url = _store_client().generate_presigned_url(
                "get_object", Params={"Bucket": _bucket(), "Key": manifest.artifact_key}, ExpiresIn=3600,
            )
            contracts.validate_media_reference(url, allow_asset=False)
        except Exception:
            raise RuntimeError("Saved HeyGen artifact URL could not be issued; reuse the accepted job.") from None
        result["video_url"] = url
    return result


def get_video_status(job_id: str, download: bool = False) -> dict[str, Any]:
    """Poll one saved HeyGen job without resubmission; download=true validates and saves completed MP4."""
    request = contracts.PollRequest.model_validate(locals())
    manifest = _read(request.job_id)
    _, output = _paths(request.job_id)
    if job_id.startswith("heygen:dry:") or dry_run():
        return {**_summary(manifest), "status": "dry_run", "downloaded": False,
                "note": "Dry-run handle or polling configuration; no HeyGen request was made."}
    if manifest.status == "submission_unknown" or not manifest.provider_video_id:
        return {**_summary(manifest), "status": "submission_unknown", "submission_unknown": True,
                "note": "Do not resubmit. Reconcile the unknown submission with the HeyGen account."}
    if manifest.status == "succeeded" and download:
        if not output.is_file() and manifest.artifact_key and _bucket():
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_suffix(f".{uuid.uuid4().hex}.part")
            try:
                _store_client().download_file(Bucket=_bucket(), Key=manifest.artifact_key, Filename=str(temporary))
                _validate_video(temporary)
                temporary.replace(output)
            except Exception:
                raise RuntimeError("Saved HeyGen MP4 could not be restored; no generation was resubmitted.") from None
            finally:
                temporary.unlink(missing_ok=True)
        if output.is_file():
            _validate_video(output)
            return _completed(manifest, output)
    data = _data(_request("GET", f"/videos/{manifest.provider_video_id}"))
    provider_status = data.get("status")
    if data.get("id") != manifest.provider_video_id or provider_status not in STATES:
        raise RuntimeError("HeyGen polling returned a mismatched id or unknown status.")
    manifest.status = STATES[provider_status]
    result = {"provider_status": provider_status}
    if manifest.status == "succeeded":
        url = data.get("video_url")
        try:
            contracts.validate_media_reference(url, allow_asset=False)
        except ValueError:
            raise RuntimeError("Completed HeyGen result did not contain a valid HTTPS video URL.") from None
        duration = data.get("duration")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and 0 < duration < float("inf"):
            manifest.actual_duration_seconds = float(duration)
        result["video_url"] = url
        if download:
            _download(url, output)
            if _bucket():
                try:
                    _store_client().upload_file(Filename=str(output), Bucket=_bucket(), Key=_artifact_key(job_id),
                                                ExtraArgs={"ContentType": "video/mp4"})
                except Exception:
                    raise RuntimeError("HeyGen MP4 was saved locally but durable artifact storage failed; do not resubmit.") from None
                manifest.artifact_key = _artifact_key(job_id)
            result.update(downloaded=True, output_path=str(output))
    elif manifest.status == "failed":
        result["error"] = "HeyGen video generation failed. Inspect the provider account before requesting another job."
        code = data.get("failure_code")
        if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", code):
            result["failure_code"] = code
    _save(manifest)
    if result.get("downloaded"):
        return {**result, **_completed(manifest, output)}
    return {**_summary(manifest), **result}


def _list_resources(tool: str, limit: int, next_token: str | None) -> dict[str, Any]:
    arguments = {"limit": limit, "next_token": next_token}
    contracts.validate_arguments(tool, arguments)
    if dry_run():
        return {"provider": "heygen", "status": "dry_run", "data": [], "has_more": False,
                "next_token": None, "note": "No HeyGen account request was made; no resources were invented."}
    params = {"avatar_type": "digital_twin", "limit": limit} if tool == "list_avatars" else {"limit": limit}
    if next_token is not None:
        params["token"] = next_token
    payload = _request("GET", "/avatars/looks" if tool == "list_avatars" else "/voices", params=params)
    data = payload.get("data")
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise RuntimeError("HeyGen list returned invalid resource data.")
    fields = {"id", "group_id", "name", "avatar_type", "supported_api_engines", "status", "default_voice_id"} if tool == "list_avatars" else {"voice_id", "name", "language", "gender", "type", "support_locale", "available_engines"}
    return {"provider": "heygen", "status": "succeeded",
            "data": [{key: value for key, value in item.items() if key in fields} for item in data],
            "has_more": payload.get("has_more", False), "next_token": payload.get("next_token")}


def list_avatars(limit: int = 20, next_token: str | None = None) -> dict[str, Any]:
    """List existing digital-twin looks once; look ids are required for Avatar V generation."""
    return _list_resources("list_avatars", limit, next_token)


def list_voices(limit: int = 20, next_token: str | None = None) -> dict[str, Any]:
    """List existing authorized HeyGen voices once; never creates or clones a voice."""
    return _list_resources("list_voices", limit, next_token)


TOOL_HANDLERS = {"voice_clone": voice_clone, "voice_tts": voice_tts, "get_voice_status": get_voice_status,
                 "create_avatar_video": create_avatar_video, "get_video_status": get_video_status,
                 "list_avatars": list_avatars, "list_voices": list_voices}
GATEWAY_TOOLS = tuple(TOOL_HANDLERS)
