"""Wan VACE generation through fal's queue, checked 2026-10-08.

https://docs.fal.ai/model-apis/model-endpoints/queue
https://fal.ai/models/fal-ai/wan-vace-14b/api
https://fal.ai/models/fal-ai/wan-22-vace-fun-a14b/api
Per-endpoint contracts and source links live in providers.fal.wan.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from providers.contracts import validate_tool_arguments
from providers.fal import queue, wan
from providers.registry import schema_from_callable


def _validated(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    schema = schema_from_callable(tool, TOOL_HANDLERS[tool])["inputSchema"]
    return validate_tool_arguments("fal", tool, arguments, schema)


def _paths(job_id: str) -> tuple[Path, Path]:
    video_dir = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")) / "video"
    metadata_dir = video_dir / ".tasks" / "fal"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    filename = "fal_" + hashlib.sha256(job_id.encode()).hexdigest()
    return metadata_dir / f"{filename}.json", video_dir / f"{filename}.mp4"


def _job(endpoint_id: str, request_id: str) -> str:
    queue.request_url(endpoint_id, request_id)
    return f"{endpoint_id}:{request_id}"


def _parse_job(job_id: str) -> tuple[str, str]:
    endpoint_id, separator, request_id = job_id.partition(":")
    if not separator or endpoint_id not in wan.ENDPOINTS:
        raise ValueError("job_id must be the handle returned by a fal submit tool.")
    queue.request_url(endpoint_id, request_id)
    return endpoint_id, request_id


def _write_metadata(path: Path, metadata: dict[str, Any]) -> None:
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(metadata, indent=2))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _submit(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    arguments = _validated(tool, arguments)
    endpoint, body = wan.request_body(tool, arguments)
    if queue.dry_run():
        return {
            "job_id": _job(endpoint.id, "dry_" + uuid.uuid4().hex),
            "status": "dry_run",
            "provider": "fal",
            "model": endpoint.model,
            "endpoint_id": endpoint.id,
            "mode": tool,
            **wan.TRAINING_METADATA,
            "note": "No fal request made. Set FAL_DRY_RUN=false for live generation.",
        }
    estimate = wan.price_cents(endpoint, arguments["resolution"], arguments["num_frames"])
    payload = queue.submit(endpoint.id, body)
    request_id = payload.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise RuntimeError("fal submission did not return request_id.")
    job_id = _job(endpoint.id, request_id)
    status = queue.mapped_status({"status": "IN_QUEUE", **payload})
    if status == "succeeded":
        status = "queued"
    metadata_path, _ = _paths(job_id)
    _write_metadata(
        metadata_path,
        {
            "job_id": job_id,
            "endpoint_id": endpoint.id,
            "mode": tool,
            "arguments": arguments,
            **wan.TRAINING_METADATA,
        },
    )
    return {
        "job_id": job_id,
        "status": status,
        "provider": "fal",
        "mode": tool,
        "model": endpoint.model,
        "endpoint_id": endpoint.id,
        "estimated_cost_usd": float(estimate / 100),
        "error": payload.get("error"),
        "error_type": payload.get("error_type"),
        **wan.TRAINING_METADATA,
        "note": "Call get_video_task with this job_id until terminal; use download=true for the MP4.",
    }


def text_to_video(
    prompt: str,
    model: str = wan.DEFAULT_MODEL,
    num_frames: int = 81,
    frames_per_second: int = 16,
    resolution: str = "720p",
    aspect_ratio: str = "16:9",
    negative_prompt: str | None = None,
    seed: int | None = None,
) -> dict:
    """Submit text-only Wan VACE freeform generation; poll get_video_task."""
    return _submit("text_to_video", locals())


def image_to_video(
    first_frame_url: str,
    prompt: str,
    model: str = wan.DEFAULT_MODEL,
    num_frames: int = 81,
    frames_per_second: int = 16,
    resolution: str = "720p",
    aspect_ratio: str = "16:9",
    last_frame_url: str | None = None,
    negative_prompt: str | None = None,
    seed: int | None = None,
) -> dict:
    """Submit Wan VACE freeform animation guided by a first frame; poll get_video_task."""
    return _submit("image_to_video", locals())


def reference_to_video(
    ref_image_urls: list[str],
    prompt: str,
    model: str = wan.DEFAULT_MODEL,
    num_frames: int = 81,
    frames_per_second: int = 16,
    resolution: str = "720p",
    aspect_ratio: str = "16:9",
    first_frame_url: str | None = None,
    last_frame_url: str | None = None,
    negative_prompt: str | None = None,
    seed: int | None = None,
) -> dict:
    """Submit Wan VACE freeform generation using subject references; poll get_video_task."""
    return _submit("reference_to_video", locals())


def video_to_video(
    video_url: str,
    prompt: str = "",
    edit_mode: str = "depth",
    task: str | None = None,
    model: str = wan.DEFAULT_MODEL,
    num_frames: int = 81,
    frames_per_second: int = 16,
    resolution: str = "720p",
    aspect_ratio: str = "16:9",
    mask_video_url: str | None = None,
    mask_image_url: str | None = None,
    ref_image_urls: list[str] | None = None,
    first_frame_url: str | None = None,
    last_frame_url: str | None = None,
    preprocess: bool | None = None,
    expand_left: bool | None = None,
    expand_right: bool | None = None,
    expand_top: bool | None = None,
    expand_bottom: bool | None = None,
    expand_ratio: float | None = None,
    zoom_factor: float | None = None,
    trim_borders: bool | None = None,
    negative_prompt: str | None = None,
    seed: int | None = None,
) -> dict:
    """Submit VACE freeform/inpainting/outpainting/reframe/depth/pose editing; poll get_video_task."""
    return _submit("video_to_video", locals())


def _download(video_url: str, output_path: Path) -> None:
    temporary = output_path.with_suffix(f".{uuid.uuid4().hex}.part")
    try:
        with httpx.stream("GET", video_url, follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
        if not temporary.stat().st_size:
            raise RuntimeError("fal returned an empty video.")
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)


def get_video_task(job_id: str, download: bool = False) -> dict:
    """Poll one fal queue status, fetch a completed result, and optionally save the MP4."""
    _validated("get_video_task", locals())
    endpoint_id, request_id = _parse_job(job_id)
    if queue.dry_run():
        return {"job_id": job_id, "provider": "fal", "status": "dry_run", **wan.TRAINING_METADATA}
    endpoint = wan.ENDPOINTS[endpoint_id]
    base = {
        "job_id": job_id,
        "provider": "fal",
        "model": endpoint.model,
        "endpoint_id": endpoint_id,
        **wan.TRAINING_METADATA,
    }
    payload = queue.status(endpoint_id, request_id)
    status = queue.mapped_status(payload)
    if status == "failed":
        return {
            **base,
            "status": "failed",
            "error": payload.get("error"),
            "error_type": payload.get("error_type"),
        }
    if status != "succeeded":
        return {**base, "status": status, "queue_position": payload.get("queue_position")}
    try:
        result = queue.result(endpoint_id, request_id)
    except queue.FalAPIError as exc:
        # Auth, not-found, and rate limits remain retryable tool errors, not failed jobs.
        if exc.status_code not in {400, 422}:
            raise
        return {**base, "status": "failed", "error": str(exc)}
    if result.get("error") or result.get("error_type"):
        return {
            **base,
            "status": "failed",
            "error": result.get("error"),
            "error_type": result.get("error_type"),
        }
    video = result.get("video")
    video_url = video.get("url") if isinstance(video, dict) else None
    if not isinstance(video_url, str):
        raise RuntimeError("Completed fal result did not contain an HTTP(S) video.url.")
    parsed = urlsplit(video_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("Completed fal result did not contain an HTTP(S) video.url.")
    metadata_path, output_path = _paths(job_id)
    if download and (not output_path.exists() or not output_path.stat().st_size):
        _download(video_url, output_path)
    normalized = {
        **base,
        "status": "succeeded",
        "video_url": video_url,
        "output_path": str(output_path) if output_path.exists() else None,
        "downloaded": output_path.exists(),
        "seed": result.get("seed"),
    }
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    metadata.update(normalized)
    _write_metadata(metadata_path, metadata)
    return normalized


def list_fal_models() -> dict:
    """List the documented Wan VACE endpoint catalog and pricing without calling fal."""
    return {
        "status": "dry_run" if queue.dry_run() else "ok",
        "selected_model": wan.DEFAULT_MODEL,
        "models": [{"id": model, **wan.TRAINING_METADATA} for model in wan.MODELS],
        "endpoints": [
            {
                "id": endpoint.id,
                "model": endpoint.model,
                "edit_mode": endpoint.mode,
                "api_url": endpoint.api_url,
                "pricing_url": endpoint.api_url.removesuffix("/api"),
                "price_unit": "video_second_at_16_fps",
                "pricing_checked_at": "2026-10-08",
                "usd_per_unit_by_resolution": {
                    resolution: str(rate / 100)
                    for resolution, rate in (endpoint.price_cents_per_video_second or {}).items()
                },
                "pricing_confirmed": endpoint.price_cents_per_video_second is not None,
                **wan.TRAINING_METADATA,
            }
            for endpoint in wan.ENDPOINTS.values()
        ],
        "note": "Static documented catalog. Does not confirm account access. fal hosted Terms of Service apply.",
    }


TOOL_HANDLERS = {
    "text_to_video": text_to_video,
    "image_to_video": image_to_video,
    "reference_to_video": reference_to_video,
    "video_to_video": video_to_video,
    "get_video_task": get_video_task,
    "list_fal_models": list_fal_models,
}
GATEWAY_TOOLS = tuple(TOOL_HANDLERS)
