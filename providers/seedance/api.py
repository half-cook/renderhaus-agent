"""Seedance 2.5 through fal by default, with opt-in BytePlus transport.

Official request contracts and sources are in providers.seedance.contracts.
Every generation remains dry-run unless the applicable transport flags are disabled.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import httpx

from providers.contracts import validate_tool_arguments
from providers.fal import queue
from providers.registry import schema_from_callable
from providers.seedance import contracts


MIN_DURATION_SECONDS = 4
MAX_DURATION_SECONDS = 30
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "canceled", "deleted", "expired",
                     "timeout", "timed_out", "timeouted", "dry_run"}


def _dry_run() -> bool:
    return os.getenv("SEEDANCE_DRY_RUN", "true").lower() != "false"


def dry_run() -> bool:
    return _dry_run() or (contracts.transport() == "fal" and queue.dry_run())


def _base_url() -> str:
    base = os.getenv("BYTEPLUS_BASE_URL", "https://ark.ap-southeast.bytepluses.com/api/v3").rstrip("/")
    return base if base.endswith("/api/v3") else f"{base}/api/v3"


def _model(model: str | None = None) -> str:
    return model or os.getenv("SEEDANCE_MODEL") or contracts.MODEL_25


def _api_key() -> str:
    key = os.getenv("BYTEPLUS_API_KEY") or os.getenv("ARK_API_KEY")
    if not key:
        raise RuntimeError("BYTEPLUS_API_KEY or ARK_API_KEY is required for live Seedance calls.")
    return key


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_api_key()}", "Content-Type": "application/json"}


def _video_dir() -> Path:
    path = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser() / "video"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _task_meta_path(job_id: str) -> Path:
    directory = _video_dir() / ".tasks" / "seedance"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / (hashlib.sha256(job_id.encode()).hexdigest() + ".json")


def _write_task_meta(job_id: str, metadata: dict[str, Any]) -> None:
    path = _task_meta_path(job_id)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(metadata, indent=2, sort_keys=True))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_task_meta(job_id: str) -> dict[str, Any]:
    path = _task_meta_path(job_id)
    if not path.exists():
        if re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
            legacy = _video_dir() / ".tasks" / f"{job_id}.json"
            if legacy.exists():
                return json.loads(legacy.read_text())
        return {}
    return json.loads(path.read_text())


def _output_path(job_id: str) -> Path:
    return _video_dir() / ("seedance_" + hashlib.sha256(job_id.encode()).hexdigest() + ".mp4")


def _as_modelark_image_url(path_or_url: str) -> str:
    if path_or_url.startswith(("http://", "https://", "data:")):
        return path_or_url
    path = Path(path_or_url).expanduser()
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _provider_error(response: httpx.Response) -> RuntimeError:
    try:
        payload = response.json()
    except ValueError:
        return RuntimeError(f"BytePlus API error {response.status_code}: {response.text[:1000]}")
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return RuntimeError(f"BytePlus API error {response.status_code} ({error.get('code', 'UnknownCode')}): {error.get('message')}")
    return RuntimeError(f"BytePlus API error {response.status_code}: {payload}")


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_error:
        raise _provider_error(response)


def _validated(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    schema = schema_from_callable(tool, TOOL_HANDLERS[tool])["inputSchema"]
    return validate_tool_arguments("seedance", tool, arguments, schema)


def _submit(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from server.billing_rates import seedance_price_cents

    arguments = _validated(tool, arguments)
    model, body = contracts.request_body(tool, arguments)
    host = contracts.transport()
    verified = contracts.verified_model(tool, arguments)
    estimate_reason = None
    try:
        estimate = seedance_price_cents(tool, arguments)
    except ValueError as exc:
        estimate = None
        estimate_reason = str(exc)
    dry = dry_run() or not verified
    metadata = {
        "provider": "seedance", "transport": host, "mode": tool, "model": model,
        "endpoint_id": model if host == "fal" else None,
        "duration_seconds": arguments.get("duration_seconds", -1 if tool == "edit_video" else 5),
        "aspect_ratio": contracts.output_aspect_ratio(tool, arguments),
        "resolution": arguments.get("resolution", "720p"),
        "estimated_cost_usd": float(estimate / 100) if estimate is not None else None,
        "cost_estimate": f"${estimate / 100:.2f} provider estimate before Renderhaus fee" if estimate is not None else "unknown",
        "cost_estimate_reason": estimate_reason,
        "pricing_verified_on": "2026-10-09", "verification_status": "verified" if verified else "UNVERIFIED",
        **contracts.TRAINING_METADATA,
        "hosted_terms_url": contracts.BYTEPLUS_TERMS_URL if host == "byteplus" else contracts.TRAINING_METADATA["hosted_terms_url"],
    }
    if dry:
        job_id = f"{model}:dry_{uuid.uuid4().hex}" if host == "fal" else f"seedance_dry_{uuid.uuid4().hex}"
        return {**metadata, "job_id": job_id, "status": "dry_run", "request_preview": body,
                "note": "UNVERIFIED model; dry-run only." if not verified else "No provider request made. Enable the selected transport flags only after approval."}
    blocker = contracts.live_blocker(tool, arguments)
    if blocker:
        raise ValueError(blocker)
    if estimate is None:
        raise ValueError("Seedance cost estimate unknown. Supply a measured source_aspect_ratio for image/video inputs or a concrete output aspect_ratio before live generation.")
    body = dict(body)
    if host == "fal":
        for field in ("image_url", "end_image_url"):
            if field in body:
                body[field] = _as_modelark_image_url(body[field])
        payload = queue.submit(model, body)
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise RuntimeError("fal submission did not return request_id.")
        queue.request_url(model, request_id)
        job_id = f"{model}:{request_id}"
        status = queue.mapped_status({"status": "IN_QUEUE", **payload})
        if status == "succeeded":
            status = "queued"
    else:
        content = []
        for item in body["content"]:
            if item["type"] == "image_url":
                item = {**item, "image_url": {"url": _as_modelark_image_url(item["image_url"]["url"])}}
            content.append(item)
        body["content"] = content
        with httpx.Client(timeout=60) as client:
            response = client.post(f"{_base_url()}/contents/generations/tasks", headers=_headers(), json=body)
            _raise_for_status(response)
            payload = response.json()
        job_id = payload.get("id")
        if not isinstance(job_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
            raise RuntimeError("BytePlus did not return a valid task id.")
        status = "queued"
    result = {**metadata, "job_id": job_id, "status": status,
              "note": "Poll get_video_task with download=true until terminal and inspect the finished MP4."}
    _write_task_meta(job_id, result)
    return result


def text_to_video(
    prompt: str, duration_seconds: int = 5, aspect_ratio: str = "16:9", resolution: str = "720p",
    model: str | None = None, watermark: bool = True, generate_audio: bool = True,
    service_tier: Literal["default", "flex"] | None = None, seed: int | None = None,
    real_face_refs: bool = False, user_supplied_real_person_refs: bool = False,
) -> dict:
    """Submit a synthetic Seedance dialogue shot; paid video requires approval."""
    return _submit("text_to_video", locals())


def image_to_video(
    image_path_or_url: str, prompt: str, duration_seconds: int = 5, aspect_ratio: str = "16:9",
    resolution: str = "720p", model: str | None = None, watermark: bool = True,
    generate_audio: bool = True, service_tier: Literal["default", "flex"] | None = None,
    end_image_path_or_url: str | None = None, source_aspect_ratio: str | None = None,
    seed: int | None = None, real_face_refs: bool = False, user_supplied_real_person_refs: bool = False,
) -> dict:
    """Animate a synthetic frame, optionally ending on a second frame; real faces forbidden."""
    return _submit("image_to_video", locals())


def reference_to_video(
    prompt: str, reference_image_urls: list[str] | None = None,
    reference_video_urls: list[str] | None = None, reference_audio_urls: list[str] | None = None,
    reference_video_durations: list[float] | None = None, reference_video_fps: list[float] | None = None,
    reference_audio_durations: list[float] | None = None, duration_seconds: int = 5,
    aspect_ratio: str = "16:9", resolution: str = "720p", model: str | None = None,
    watermark: bool = True, generate_audio: bool = True,
    service_tier: Literal["default", "flex"] | None = None, seed: int | None = None,
    real_face_refs: bool = False, user_supplied_real_person_refs: bool = False,
) -> dict:
    """Generate synthetic-character video with image, video, and audio references."""
    return _submit("reference_to_video", locals())


def edit_video(
    video_url: str, prompt: str, source_duration_seconds: float, source_fps: float,
    source_aspect_ratio: str | None = None, duration_seconds: int = -1,
    aspect_ratio: str = "adaptive", resolution: str = "720p", model: str | None = None,
    reference_image_urls: list[str] | None = None, reference_audio_urls: list[str] | None = None,
    reference_audio_durations: list[float] | None = None, watermark: bool = True,
    generate_audio: bool = True, service_tier: Literal["default", "flex"] | None = None,
    seed: int | None = None, real_face_refs: bool = False, user_supplied_real_person_refs: bool = False,
) -> dict:
    """Edit a synthetic source video while retaining source timing; real faces forbidden."""
    return _submit("edit_video", locals())


def extend_video(
    video_url: str, prompt: str, source_duration_seconds: float, source_fps: float,
    source_aspect_ratio: str | None = None, duration_seconds: int = 5,
    aspect_ratio: str = "adaptive", resolution: str = "720p", model: str | None = None,
    reference_image_urls: list[str] | None = None, reference_audio_urls: list[str] | None = None,
    reference_audio_durations: list[float] | None = None, watermark: bool = True,
    generate_audio: bool = True, service_tier: Literal["default", "flex"] | None = None,
    seed: int | None = None, real_face_refs: bool = False, user_supplied_real_person_refs: bool = False,
) -> dict:
    """Request a synthetic video extension; duration describes generated output, not a stitched timeline."""
    return _submit("extend_video", locals())


def _download_video(video_url: str, output_path: Path) -> None:
    temporary = output_path.with_suffix(f".{uuid.uuid4().hex}.part")
    try:
        with httpx.stream("GET", video_url, follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
        if not temporary.stat().st_size:
            raise RuntimeError("BytePlus returned an empty video.")
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)


def _retrieve_task(job_id: str, download: bool) -> dict:
    if ":" in job_id:
        from providers.fal.api import get_video_task as get_fal_task

        endpoint, _, request_id = job_id.partition(":")
        if endpoint not in contracts.ENDPOINTS:
            if request_id.startswith("dry_"):
                return {"job_id": job_id, "model": endpoint, "provider": "seedance", "status": "dry_run", "verification_status": "UNVERIFIED", **contracts.TRAINING_METADATA}
            raise ValueError("Seedance fal job handle requires a documented Seedance endpoint.")
        if _dry_run():
            return {"job_id": job_id, "model": endpoint, "provider": "seedance", "status": "dry_run", **contracts.TRAINING_METADATA}
        return get_fal_task(job_id, download=download)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
        raise ValueError("Invalid BytePlus job id.")
    metadata = _read_task_meta(job_id)
    if _dry_run() or job_id.startswith("seedance_dry_"):
        return {"job_id": job_id, "status": "dry_run", "provider": "seedance", **contracts.TRAINING_METADATA}
    blocker = contracts.byteplus_platform_blocker()
    if blocker:
        raise ValueError(blocker)
    with httpx.Client(timeout=60) as client:
        response = client.get(f"{_base_url()}/contents/generations/tasks/{job_id}", headers=_headers())
        _raise_for_status(response)
        payload = response.json()
    content = payload.get("content")
    video_url = content.get("video_url") if isinstance(content, dict) else None
    status = payload.get("status", "unknown")
    output = Path(metadata.get("output_path") or _output_path(job_id))
    if download and status == "succeeded" and video_url:
        if not output.exists() or not output.stat().st_size:
            _download_video(video_url, output)
    result = {"job_id": job_id, "status": status, "provider": "seedance", "transport": "byteplus",
              "model": payload.get("model") or metadata.get("model"), "video_url": video_url,
              "output_path": str(output) if output.exists() else None, "downloaded": output.exists(),
              "usage": payload.get("usage"), "error": payload.get("error"), **contracts.TRAINING_METADATA,
              "hosted_terms_url": contracts.BYTEPLUS_TERMS_URL}
    _write_task_meta(job_id, {**metadata, **result})
    return result


def get_video_task(job_id: str, download: bool = False) -> dict:
    """Poll an existing Seedance job; fal handles reuse the existing fal polling implementation."""
    arguments = _validated("get_video_task", locals())
    return _retrieve_task(**arguments)


def wait_for_video_task(job_id: str, timeout_seconds: int = 600, poll_interval_seconds: int = 5, download: bool = True) -> dict:
    """Local helper. Poll asynchronously through get_video_task on Gateway."""
    deadline = time.time() + timeout_seconds
    result: dict[str, Any] = {}
    while time.time() < deadline:
        result = _retrieve_task(job_id=job_id, download=download)
        if str(result.get("status", "")).lower() in TERMINAL_STATUSES:
            return result
        time.sleep(poll_interval_seconds)
    return {**result, "timed_out": True, "note": f"Timed out after {timeout_seconds}s waiting for Seedance task {job_id}."}


def text_to_video_and_wait(prompt: str, duration_seconds: int = 4, aspect_ratio: str = "16:9", resolution: str = "720p", timeout_seconds: int = 600, poll_interval_seconds: int = 5, model: str | None = None, watermark: bool = True, generate_audio: bool = True, service_tier: Literal["default", "flex"] | None = None) -> dict:
    """Local helper, never exposed as a blocking Gateway tool."""
    created = text_to_video(prompt, duration_seconds, aspect_ratio, resolution, model, watermark, generate_audio, service_tier)
    if created["status"] == "dry_run":
        return created
    result = wait_for_video_task(created["job_id"], timeout_seconds, poll_interval_seconds)
    return {"created": created, "result": result}


def list_seedance_models() -> dict:
    """Return the verified offline Seedance catalog without credentials or account requests."""
    try:
        selected = contracts.effective_model("text_to_video", {})
        configuration_error = None
    except ValueError as exc:
        selected = contracts.configured_model({})
        configuration_error = str(exc)
    return {
        "status": "dry_run" if _dry_run() else "ok",
        "selected_model": selected, "configuration_error": configuration_error,
        "transport": contracts.transport(), "verified_on": "2026-10-09",
        "models": [{"id": endpoint, "api_url": spec.api_url, **contracts.TRAINING_METADATA}
                   for endpoint, spec in contracts.ENDPOINTS.items()]
        + [{"id": model, "transport": "byteplus", "requires_platform_authorization": True,
            **contracts.TRAINING_METADATA, "hosted_terms_url": contracts.BYTEPLUS_TERMS_URL}
           for model in (contracts.MODEL_25, contracts.MODEL_15)],
        "note": "Static documented catalog. BytePlus is unavailable to US customers and requires written platform authorization. fal US-hosted endpoints are the default. Account access is not verified.",
    }


TOOL_HANDLERS = {"text_to_video": text_to_video, "image_to_video": image_to_video,
                 "reference_to_video": reference_to_video, "edit_video": edit_video, "extend_video": extend_video,
                 "get_video_task": get_video_task, "wait_for_video_task": wait_for_video_task,
                 "text_to_video_and_wait": text_to_video_and_wait, "list_seedance_models": list_seedance_models}
GATEWAY_TOOLS = (*contracts.GENERATING_TOOLS, "get_video_task", "list_seedance_models")
