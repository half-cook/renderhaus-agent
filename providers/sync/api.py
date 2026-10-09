from __future__ import annotations

import hashlib
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import httpx
from botocore.exceptions import ClientError
from pydantic import BaseModel, ConfigDict, Field

from providers.fal import queue
from providers.sync import chunks, contracts, media


DIRECT_URL = "https://api.sync.so/v2/generate"
DIRECT_STATES = {
    "PENDING": "queued", "PROCESSING": "running", "COMPLETED": "succeeded",
    "FAILED": "failed", "REJECTED": "failed",
}
JOB_PATTERN = re.compile(r"sync:(?:(fal|direct|dry):[a-f0-9]{32}|chunks:(fal|direct):[a-f0-9]{32})")
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_LOCK = threading.Lock()


class ChunkRecord(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False, hide_input_in_errors=True)

    index: int = Field(ge=0)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    duration_seconds: float = Field(gt=0)
    job_id: str | None = None
    provider_handle: str | None = None
    status: Literal["pending_submit", "queued", "running", "succeeded", "failed"] = "pending_submit"


class JobManifest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False, hide_input_in_errors=True)

    version: Literal[1] = 1
    provider: Literal["sync"] = "sync"
    job_id: str
    transport: Literal["fal", "direct"]
    model: str
    endpoint_id: str | None = None
    endpoint_handle: str | None = None
    request_id: str | None = None
    status: Literal["submitting", "queued", "running", "succeeded", "failed"] = "submitting"
    subjects: str = Field(min_length=1)
    consent_confirmed: bool
    source_duration_seconds: float = Field(gt=0)
    audio_duration_seconds: float = Field(gt=0)
    source_fps: float = Field(gt=0)
    source_width: int | None = Field(default=None, gt=0)
    source_height: int | None = Field(default=None, gt=0)
    output_duration_seconds: float = Field(gt=0)
    sync_mode: Literal["cut_off", "loop", "bounce", "silence", "remap"]
    video_reference: str
    audio_reference: str
    output_reference: str | None = None
    artifact_key: str | None = None
    chunks: list[ChunkRecord] = Field(default_factory=list)
    submission_complete: bool = False
    output_path: str | None = None
    downloaded: bool = False
    error: str | None = None
    persistence_error: bool = False
    estimated_cost_usd: float | None = None
    created_at: float = Field(default_factory=time.time)
    training_eligible: Literal[False] = False
    weights_license: Literal["closed-weights"] = "closed-weights"
    license: Literal["service-terms"] = "service-terms"
    license_source: str
    hosted_terms_url: str


class SyncStoreError(RuntimeError):
    pass


def _is_dry(transport: str) -> bool:
    return os.getenv("SYNC_DRY_RUN", "true").lower() != "false" or (transport == "fal" and queue.dry_run())


def dry_run() -> bool:
    return _is_dry(contracts.configured_transport())


def _paths(job_id: str) -> tuple[Path, Path]:
    digest = hashlib.sha256(job_id.encode()).hexdigest()
    video = chunks.media_root() / "video"
    return video / ".tasks" / "sync" / f"{digest}.json", video / f"sync_{digest}.mp4"


def _store_bucket() -> str:
    return os.getenv("AWS_S3_BUCKET", "").strip()


def _store_client():
    return chunks.boto3.client("s3", region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1")


def _store_key(job_id: str) -> str:
    return "renderhaus-sync-jobs/" + hashlib.sha256(job_id.encode()).hexdigest() + ".json"


def _artifact_key(job_id: str) -> str:
    return "renderhaus-sync-outputs/" + hashlib.sha256(job_id.encode()).hexdigest() + ".mp4"


def _write_local(manifest: JobManifest) -> None:
    path, _ = _paths(manifest.job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(manifest.model_dump_json(indent=2))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _write(manifest: JobManifest) -> None:
    local_error = False
    try:
        _write_local(manifest)
    except OSError:
        local_error = True
    if _store_bucket():
        try:
            _store_client().put_object(
                Bucket=_store_bucket(), Key=_store_key(manifest.job_id),
                Body=manifest.model_dump_json(indent=2).encode(), ContentType="application/json",
            )
        except Exception:
            raise SyncStoreError("Durable Sync job store is unavailable; no automatic retry was made.") from None
    if local_error:
        raise SyncStoreError("Sync local job store is unavailable; no automatic retry was made.")


def _preserve_accepted(manifest: JobManifest) -> None:
    manifest.persistence_error = True
    try:
        _write_local(manifest)
    except OSError:
        pass


def _storage_gate() -> None:
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME") and not _store_bucket():
        raise ValueError("Hosted live Sync requires AWS_S3_BUCKET for durable job manifests before any paid submission.")


def _kind(job_id: str) -> str:
    match = JOB_PATTERN.fullmatch(job_id)
    if not match:
        raise ValueError("job_id must be the saved handle returned by lipsync_video.")
    return match.group(1) or "chunks"


def _saved_transport(job_id: str, kind: str) -> str:
    return job_id.split(":")[2] if kind == "chunks" else kind


def _read(job_id: str, kind: str) -> JobManifest:
    path, output = _paths(job_id)
    content = None
    if _store_bucket():
        try:
            response = _store_client().get_object(Bucket=_store_bucket(), Key=_store_key(job_id))
            body = response["Body"]
            try:
                content = body.read().decode()
            finally:
                body.close()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in {"NoSuchKey", "404", "NotFound"}:
                raise SyncStoreError("Durable Sync job store could not be read.") from None
        except Exception:
            raise SyncStoreError("Durable Sync job store could not be read.") from None
    if content is None and path.is_file():
        content = path.read_text()
    if content is None:
        raise ValueError("Saved Sync job metadata was not found; no provider request was made.")
    try:
        manifest = JobManifest.model_validate_json(content)
        if not manifest.request_id and kind != "chunks" and path.is_file():
            local_manifest = JobManifest.model_validate_json(path.read_text())
            if local_manifest.request_id and local_manifest.job_id == manifest.job_id:
                manifest = local_manifest
    except (ValueError, OSError):
        raise ValueError("Saved Sync job metadata is invalid.") from None
    if (
        manifest.job_id != job_id or manifest.consent_confirmed is not True
        or manifest.transport != _saved_transport(job_id, kind)
        or manifest.model != contracts.DEFAULT_MODEL
        or manifest.endpoint_id != (contracts.FAL_ENDPOINT if manifest.transport == "fal" else None)
        or (manifest.output_path is not None and manifest.output_path != str(output))
        or (manifest.artifact_key is not None and manifest.artifact_key != _artifact_key(job_id))
    ):
        raise ValueError("Saved Sync job transport, model, consent or output path is invalid.")
    if kind == "chunks":
        if len(manifest.chunks) < 2 or manifest.request_id or manifest.endpoint_handle:
            raise ValueError("Saved Sync aggregate metadata is invalid.")
        previous = 0.0
        for index, child in enumerate(manifest.chunks):
            if (
                child.index != index or child.start_seconds != previous
                or not child.end_seconds > child.start_seconds
                or not abs(child.duration_seconds - (child.end_seconds - child.start_seconds)) < 1e-6
                or (child.job_id is not None and _kind(child.job_id) != manifest.transport)
            ):
                raise ValueError("Saved Sync chunk order or transport is invalid.")
            previous = child.end_seconds
        if abs(previous - manifest.output_duration_seconds) > 1e-6:
            raise ValueError("Saved Sync chunks do not cover the declared output duration.")
    elif manifest.chunks:
        raise ValueError("Saved Sync single-job metadata cannot contain chunk jobs.")
    elif manifest.request_id:
        _request_id(manifest.request_id)
        expected = f"{contracts.FAL_ENDPOINT}:{manifest.request_id}" if manifest.transport == "fal" else None
        if manifest.endpoint_handle != expected:
            raise ValueError("Saved Sync endpoint handle is invalid.")
    elif manifest.status != "failed":
        raise ValueError("Saved Sync task has no accepted provider handle; do not blindly resubmit.")
    return manifest


def _lock(job_id: str) -> threading.RLock:
    with _LOCKS_LOCK:
        return _LOCKS.setdefault(job_id, threading.RLock())


def _estimate(request: contracts.SyncRequest) -> float | None:
    from server.billing_rates import sync_price_cents

    try:
        return float(sync_price_cents(request.model_dump()) / 100)
    except ValueError:
        return None


def _manifest(job_id: str, request: contracts.SyncRequest, transport: str) -> JobManifest:
    return JobManifest(
        job_id=job_id, transport=transport, model=request.model,
        endpoint_id=contracts.FAL_ENDPOINT if transport == "fal" else None,
        subjects=request.subjects, consent_confirmed=request.consent_confirmed,
        source_duration_seconds=request.source_duration_seconds,
        audio_duration_seconds=request.audio_duration_seconds, source_fps=request.source_fps,
        source_width=request.source_width, source_height=request.source_height,
        output_duration_seconds=request.output_duration, sync_mode=request.sync_mode,
        video_reference=contracts.reference_for_metadata(request.video_url),
        audio_reference=contracts.reference_for_metadata(request.audio_url),
        estimated_cost_usd=_estimate(request), **contracts.training_metadata(transport),
    )


def _summary(manifest: JobManifest) -> dict[str, Any]:
    result = {
        "job_id": manifest.job_id, "provider": "sync", "transport": manifest.transport,
        "mode": "lipsync_video", "model": manifest.model, "endpoint_id": manifest.endpoint_id,
        "status": manifest.status, "output_duration_seconds": manifest.output_duration_seconds,
        "estimated_cost_usd": manifest.estimated_cost_usd,
        "verification_status": "verified", **contracts.training_metadata(manifest.transport),
    }
    if manifest.error:
        result["error"] = manifest.error
    if manifest.request_id:
        result["accepted_provider_handle"] = manifest.endpoint_handle or manifest.request_id
    if manifest.persistence_error:
        result["persistence_error"] = True
        result["note"] = "The provider accepted work but job metadata could not be updated. Retain accepted handles and never blindly resubmit."
    if manifest.chunks:
        result["chunks"] = [child.model_dump() for child in manifest.chunks]
        result["accepted_job_ids"] = [child.job_id for child in manifest.chunks if child.job_id]
        result["accepted_provider_handles"] = [child.provider_handle for child in manifest.chunks if child.provider_handle]
        result["submission_complete"] = manifest.submission_complete
    if manifest.downloaded and manifest.output_path and Path(manifest.output_path).is_file():
        result.update(output_path=manifest.output_path, downloaded=True)
    return result


def _published_url(manifest: JobManifest) -> str:
    try:
        url = _store_client().generate_presigned_url(
            "get_object", Params={"Bucket": _store_bucket(), "Key": manifest.artifact_key},
            ExpiresIn=chunks.INPUT_URL_TTL_SECONDS,
        )
        contracts.validate_media_reference(url, allow_asset=False)
    except Exception:
        raise RuntimeError("Sync saved artifact URL could not be issued; reuse the accepted job.") from None
    return url


def _completed_summary(manifest: JobManifest) -> dict[str, Any]:
    result = _summary(manifest)
    if manifest.artifact_key and _store_bucket():
        result["video_url"] = _published_url(manifest)
        result["downloaded"] = True
    return result


def _publish_artifact(manifest: JobManifest, path: Path) -> None:
    if not _store_bucket() or manifest.artifact_key:
        return
    key = _artifact_key(manifest.job_id)
    try:
        _store_client().upload_file(
            Filename=str(path), Bucket=_store_bucket(), Key=key,
            ExtraArgs={"ContentType": "video/mp4"},
        )
    except Exception:
        raise RuntimeError("Sync artifact could not be saved to durable storage; poll the accepted job again.") from None
    manifest.artifact_key = key


def _restore_artifact(manifest: JobManifest, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f".{uuid.uuid4().hex}.part")
    try:
        _store_client().download_file(Bucket=_store_bucket(), Key=manifest.artifact_key, Filename=str(temporary))
        media.validate_mp4(temporary)
        temporary.replace(output)
    except Exception:
        raise RuntimeError("Sync saved child artifact could not be restored; reuse the accepted jobs.") from None
    finally:
        temporary.unlink(missing_ok=True)


def _request_id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
        raise RuntimeError("Sync submission did not return a valid task identifier.")
    return value


def _direct_request(method: str, request_id: str | None = None, body: dict[str, Any] | None = None) -> dict[str, Any]:
    key = os.getenv("SYNC_API_KEY")
    if not key:
        raise RuntimeError("SYNC_API_KEY is required for live direct Sync calls.")
    url = DIRECT_URL if request_id is None else f"{DIRECT_URL}/{_request_id(request_id)}"
    try:
        with httpx.Client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = client.request(method, url, headers={"x-api-key": key, "Content-Type": "application/json"}, json=body)
    except httpx.HTTPError:
        raise RuntimeError("Direct Sync request failed; no automatic retry was made.") from None
    if response.is_error:
        raise RuntimeError(f"Direct Sync API error HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError("Direct Sync returned a non-JSON response.") from None
    if not isinstance(payload, dict):
        raise RuntimeError("Direct Sync returned a non-object response.")
    return payload


def _fal_submit(body: dict[str, Any]) -> dict[str, Any]:
    try:
        return queue.submit(contracts.FAL_ENDPOINT, body)
    except queue.FalAPIError as exc:
        raise RuntimeError(f"Sync fal API error HTTP {exc.status_code}.") from None
    except (httpx.HTTPError, RuntimeError):
        raise RuntimeError("Sync fal request failed; no automatic retry was made.") from None


def _submit_single(request: contracts.SyncRequest, transport: str) -> JobManifest:
    job_id = f"sync:{transport}:{uuid.uuid4().hex}"
    manifest = _manifest(job_id, request, transport)
    _write(manifest)
    try:
        body = contracts.request_body(request, transport)
        payload = _fal_submit(body) if transport == "fal" else _direct_request("POST", body=body)
        manifest.request_id = _request_id(payload.get("request_id" if transport == "fal" else "id"))
        if transport == "fal":
            manifest.endpoint_handle = f"{contracts.FAL_ENDPOINT}:{manifest.request_id}"
            failed = bool(payload.get("error") or payload.get("error_type"))
        else:
            failed = payload.get("status") in {"FAILED", "REJECTED"}
        manifest.status = "failed" if failed else "queued"
        manifest.error = "Sync generation failed." if failed else None
        manifest.submission_complete = True
    except (RuntimeError, ValueError):
        manifest.status = "failed"
        manifest.error = "Sync submission failed or its outcome is unknown. Do not blindly resubmit."
        _write(manifest)
        raise
    try:
        _write(manifest)
    except SyncStoreError:
        _preserve_accepted(manifest)
    return manifest


def _submit_chunks(request: contracts.SyncRequest, transport: str, plan: tuple[chunks.ChunkSpan, ...]) -> dict[str, Any]:
    prepared = chunks.prepare(request, plan)
    if len(prepared) != len(plan) or any(
        (part.index, part.start_seconds, part.end_seconds) != (span.index, span.start_seconds, span.end_seconds)
        for part, span in zip(prepared, plan)
    ):
        raise ValueError("Sync preprocessing did not preserve the ordered chunk plan.")
    manifest = _manifest(f"sync:chunks:{transport}:{uuid.uuid4().hex}", request, transport)
    manifest.chunks = [ChunkRecord(**span.preview()) for span in plan]
    _write(manifest)
    for part, record in zip(prepared, manifest.chunks):
        child_request = request.model_copy(update={
            "video_url": part.video_url, "audio_url": part.audio_url,
            "source_duration_seconds": record.duration_seconds,
            "audio_duration_seconds": record.duration_seconds, "chunk_boundaries_seconds": None,
        })
        try:
            child = _submit_single(child_request, transport)
        except (RuntimeError, ValueError):
            record.status = "failed"
            break
        record.job_id, record.status = child.job_id, child.status
        record.provider_handle = child.endpoint_handle or child.request_id
        try:
            _write(manifest)
        except SyncStoreError:
            manifest.persistence_error = True
            break
        if child.status == "failed" or child.persistence_error:
            manifest.persistence_error = child.persistence_error
            break
    manifest.submission_complete = all(record.job_id is not None for record in manifest.chunks)
    if not manifest.submission_complete or manifest.persistence_error or any(record.status == "failed" for record in manifest.chunks):
        manifest.status = "failed"
        manifest.error = "Partial chunk submission stopped. Saved accepted jobs remain recoverable; no chunks were retried."
    else:
        manifest.status = "queued"
    try:
        _write(manifest)
    except SyncStoreError:
        _preserve_accepted(manifest)
    return _summary(manifest)


def lipsync_video(
    video_url: str,
    audio_url: str,
    source_duration_seconds: float,
    audio_duration_seconds: float,
    source_fps: float,
    subjects: str,
    consent_confirmed: bool,
    sync_mode: Literal["cut_off", "loop", "bounce", "silence", "remap"] = "cut_off",
    chunk_boundaries_seconds: list[float] | None = None,
    model: str | None = None,
    source_width: int | None = None,
    source_height: int | None = None,
) -> dict:
    """Synchronize an existing video's lips to consented speech; poll get_video_task for the MP4."""
    request = contracts.request_for(locals())
    transport = contracts.configured_transport()
    plan = chunks.plan_for(request)
    blocker = contracts.live_blocker(request.model_dump(), transport=transport)
    if _is_dry(transport):
        preview_request = request.model_copy(update={
            "video_url": contracts.reference_for_metadata(request.video_url),
            "audio_url": contracts.reference_for_metadata(request.audio_url),
        })
        return {
            "job_id": f"sync:dry:{uuid.uuid4().hex}", "status": "dry_run", "provider": "sync",
            "transport": transport, "mode": "lipsync_video", "model": request.model,
            "endpoint_id": contracts.FAL_ENDPOINT if transport == "fal" else None,
            "request_preview": contracts.request_body(preview_request, transport),
            "output_duration_seconds": request.output_duration,
            "chunk_plan": [span.preview() for span in plan],
            "chunk_limit_seconds": contracts.max_chunk_seconds(),
            "chunk_limit_verification": "UNVERIFIED" if transport == "fal" else "operational_cap",
            "verification_status": "verified" if request.model == contracts.DEFAULT_MODEL else "UNVERIFIED",
            "live_blocker": blocker, "estimated_cost_usd": _estimate(request),
            **contracts.training_metadata(transport),
            "note": "Preview only. No media was fetched, clipped, uploaded or generated. No provider request was made.",
        }
    if blocker:
        raise ValueError(blocker)
    if request.video_url.startswith("renderhaus-asset:") or request.audio_url.startswith("renderhaus-asset:"):
        raise ValueError("Studio must resolve authorized asset handles to HTTPS before live Sync requests.")
    _storage_gate()
    if len(plan) > 1:
        return _submit_chunks(request, transport, plan)
    return _summary(_submit_single(request, transport))


def _poll_remote(manifest: JobManifest) -> dict[str, Any]:
    if manifest.transport == "fal":
        from providers.fal.api import get_video_task as get_fal_video_task

        try:
            return get_fal_video_task(manifest.endpoint_handle, download=False)
        except queue.FalAPIError as exc:
            raise RuntimeError(f"Sync fal API error HTTP {exc.status_code}.") from None
        except (httpx.HTTPError, RuntimeError, ValueError):
            raise RuntimeError("Sync fal polling returned an invalid result or could not complete.") from None
    payload = _direct_request("GET", manifest.request_id)
    status = DIRECT_STATES.get(payload.get("status"))
    if status is None:
        raise RuntimeError("Direct Sync returned an unknown task state.")
    if payload.get("id", manifest.request_id) != manifest.request_id:
        raise RuntimeError("Direct Sync returned a different task identifier.")
    return {"status": status, "video_url": payload.get("outputUrl")}


def _download(video_url: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f".{uuid.uuid4().hex}.part")
    try:
        with httpx.stream("GET", video_url, follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            with temporary.open("wb") as target:
                for data in response.iter_bytes():
                    target.write(data)
        if not temporary.is_file() or not temporary.stat().st_size:
            raise RuntimeError("Sync returned an empty video.")
        media.validate_mp4(temporary)
        temporary.replace(output)
    except httpx.HTTPError:
        raise RuntimeError("Sync video download failed; the saved job can be polled again.") from None
    finally:
        temporary.unlink(missing_ok=True)


def _poll_single(manifest: JobManifest, *, download: bool) -> dict[str, Any]:
    if manifest.request_id is None:
        return _summary(manifest)
    payload = _poll_remote(manifest)
    status = payload.get("status")
    if status == "dry_run":
        return {**_summary(manifest), "status": "dry_run"}
    if status not in {"queued", "running", "succeeded", "failed"}:
        raise RuntimeError("Sync returned an unknown task state.")
    if status == "succeeded":
        video_url = payload.get("video_url")
        if not isinstance(video_url, str):
            raise RuntimeError("Completed Sync result did not contain an HTTPS video URL.")
        try:
            contracts.validate_media_reference(video_url, allow_asset=False)
        except ValueError:
            raise RuntimeError("Completed Sync result did not contain a valid HTTPS video URL.") from None
        _, output = _paths(manifest.job_id)
        if download:
            if not output.is_file() or not output.stat().st_size:
                _download(video_url, output)
            else:
                media.validate_mp4(output)
            manifest.output_path, manifest.downloaded = str(output), True
            _publish_artifact(manifest, output)
        manifest.output_reference = contracts.reference_for_metadata(video_url)
    manifest.status = status
    manifest.error = "Sync generation failed." if status == "failed" else None
    _write(manifest)
    if status == "succeeded":
        return {"video_url": video_url, **_completed_summary(manifest)}
    return _summary(manifest)


def _poll_chunks(manifest: JobManifest) -> dict[str, Any]:
    outputs = []
    for record in manifest.chunks:
        if record.job_id is None:
            continue
        child = get_video_task(record.job_id, download=True)
        record.status = child["status"]
        if child["status"] == "succeeded":
            _, path = _paths(record.job_id)
            if not path.is_file():
                saved_child = _read(record.job_id, _kind(record.job_id))
                if not saved_child.artifact_key or not _store_bucket():
                    raise RuntimeError("Completed Sync child has no durable or local video.")
                _restore_artifact(saved_child, path)
            if not path.is_file() or not path.stat().st_size:
                raise RuntimeError("Completed Sync child did not produce a nonempty local video.")
            outputs.append(path)
        _write(manifest)
    if not manifest.submission_complete or any(record.status == "failed" for record in manifest.chunks):
        manifest.status = "failed"
        manifest.error = "Partial or failed chunk run. Reuse saved accepted jobs; no chunks were retried."
    elif all(record.status == "succeeded" for record in manifest.chunks):
        _, output = _paths(manifest.job_id)
        chunks.merge(outputs, output_path=output)
        if not output.is_file() or not output.stat().st_size:
            raise RuntimeError("Sync concatenation produced an empty final video.")
        media.validate_mp4(output)
        _publish_artifact(manifest, output)
        manifest.status = "succeeded"
        manifest.output_path, manifest.downloaded, manifest.error = str(output), True, None
    else:
        manifest.status = "queued" if all(record.status == "queued" for record in manifest.chunks) else "running"
    _write(manifest)
    return _completed_summary(manifest) if manifest.status == "succeeded" else _summary(manifest)


def get_video_task(job_id: str, download: bool = False) -> dict:
    """Poll a saved Sync job once without resubmitting; save completed MP4s with download=true."""
    request = contracts.PollRequest.model_validate(locals())
    kind = _kind(request.job_id)
    if kind == "dry":
        return {"job_id": job_id, "status": "dry_run", "provider": "sync", **contracts.training_metadata(contracts.configured_transport())}
    transport = _saved_transport(job_id, kind)
    if _is_dry(transport):
        return {"job_id": job_id, "status": "dry_run", "provider": "sync", "transport": transport, **contracts.training_metadata(transport)}
    with _lock(job_id):
        manifest = _read(job_id, kind)
        if _is_dry(manifest.transport):
            return {**_summary(manifest), "status": "dry_run"}
        blocker = contracts.live_blocker({"model": manifest.model}, transport=manifest.transport)
        if blocker:
            raise ValueError(blocker)
        _, output = _paths(job_id)
        if manifest.status == "succeeded" and manifest.artifact_key and _store_bucket():
            return _completed_summary(manifest)
        if manifest.status == "succeeded" and manifest.downloaded and output.is_file() and output.stat().st_size:
            media.validate_mp4(output)
            if not os.getenv("AWS_LAMBDA_FUNCTION_NAME") or kind == "chunks":
                return _completed_summary(manifest)
        if kind == "chunks":
            return _poll_chunks(manifest)
        return _poll_single(manifest, download=request.download)


TOOL_HANDLERS = {"lipsync_video": lipsync_video, "get_video_task": get_video_task}
GATEWAY_TOOLS = tuple(TOOL_HANDLERS)
