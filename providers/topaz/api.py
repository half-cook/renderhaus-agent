"""Paid video finishing with explicit dry-run gates and fal queue polling."""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from providers.fal import queue
from providers.remotion import local
from providers.sync import media
from providers.topaz import contracts


JOB_PATTERN = re.compile(r"topaz:(upscale|apollo|chronos):([A-Za-z0-9_-]+)")
JOB_KINDS = {
    "upscale": (contracts.UPSCALE_ENDPOINT, "Starlight Precise 2.6", "upscale_video", "topaz_upscale"),
    "apollo": (contracts.INTERPOLATE_ENDPOINT, "Apollo", "interpolate_video", "topaz_interpolate"),
    "chronos": (contracts.INTERPOLATE_ENDPOINT, "Chronos", "interpolate_video", "topaz_interpolate"),
}


def dry_run() -> bool:
    return os.getenv("TOPAZ_DRY_RUN", "true").lower() != "false" or queue.dry_run()


def _identity(kind: str, request_id: str) -> dict[str, Any]:
    endpoint, model, mode, capability = JOB_KINDS[kind]
    return {
        "job_id": f"topaz:{kind}:{request_id}", "provider": "topaz", "transport": "fal",
        "endpoint_id": endpoint, "model": model, "mode": mode, "capability_id": capability,
        **contracts.TRAINING_METADATA,
    }


def _submit(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from server.billing_rates import topaz_price_cents

    request = contracts.request_for(tool, arguments)
    kind = "upscale" if tool == "upscale_video" else request.model.lower()
    endpoint = JOB_KINDS[kind][0]
    estimate = topaz_price_cents(tool, arguments)
    quote = {
        "estimated_cost_usd": float(estimate / 100) if estimate is not None else None,
        "cost_estimate": "unknown" if estimate is None else f"${estimate / 100:.2f} provider estimate before Renderhaus fee",
    }
    if dry_run():
        return {
            **_identity(kind, "dry_" + uuid.uuid4().hex), **quote, "status": "dry_run",
            "request_preview": request.fal_body(), "preview_only": True,
            "note": "No paid request or output artifact. Both TOPAZ_DRY_RUN=false and FAL_DRY_RUN=false are required for live finishing.",
        }
    if request.video_url.startswith("renderhaus-asset://"):
        raise ValueError("Studio asset handles must resolve to an authorized HTTPS source before live finishing.")
    if estimate is None:
        raise ValueError("Topaz cost estimate is unknown for this output. Only dry-run previews are allowed.")
    payload = queue.submit(endpoint, request.fal_body())
    request_id = payload.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise RuntimeError("fal submission did not return a Topaz request_id.")
    queue.request_url(endpoint, request_id)
    status = queue.mapped_status({"status": "IN_QUEUE", **payload})
    if status == "succeeded":
        status = "queued"
    return {
        **_identity(kind, request_id), **quote, "status": status,
        "error": payload.get("error"), "error_type": payload.get("error_type"),
        "note": "Poll get_video_task with this job_id until terminal. Request download=true to validate and save the MP4.",
    }


def upscale_video(
    video_url: str,
    source_duration_seconds: float,
    source_fps: float,
    source_width: int,
    source_height: int,
    upscale_factor: float | None = None,
    target_resolution: str | None = None,
    target_fps: int | None = None,
    model: str | None = None,
    softness: float | None = None,
    H264_output: bool = True,
) -> dict:
    """Upscale an existing video with Starlight Precise 2.6. Paid finishing requires approval and a known cost."""
    return _submit("upscale_video", locals())


def interpolate_video(
    video_url: str,
    source_duration_seconds: float,
    source_fps: float,
    source_width: int,
    source_height: int,
    target_fps: int | None = None,
    fps_multiplier: float | None = None,
    model: str | None = None,
    slowdown_factor: int = 1,
    H264_output: bool = True,
) -> dict:
    """Convert frame rate with Apollo or Chronos. Paid finishing requires approval and a known cost."""
    return _submit("interpolate_video", locals())


def _validate_mp4(path: Path) -> None:
    invalid = RuntimeError("Topaz returned an invalid or truncated MP4 video container.")
    try:
        size = path.stat().st_size
        with path.open("rb") as source:
            boxes = list(media._boxes(source, 0, size))
            headers = [(start, end) for kind, start, end in boxes if kind == b"ftyp"]
            movies = [(start, end) for kind, start, end in boxes if kind == b"moov"]
            if len(headers) != 1 or len(movies) != 1 or not any(kind == b"mdat" and end > start for kind, start, end in boxes):
                raise invalid
            start, end = headers[0]
            if not 8 <= end - start <= 256 or (end - start) % 4:
                raise invalid
            source.seek(start)
            brands = source.read(end - start)
            candidates = [brands[:4], *(brands[index:index + 4] for index in range(8, len(brands), 4))]
            if not any(brand in media.MP4_BRANDS or (brand[:3] == b"iso" and brand[3:].isdigit()) for brand in candidates):
                raise invalid
            if b"vide" not in media._handlers(source, *movies[0]):
                raise invalid
        if shutil.which("ffprobe"):
            probe = local._probe(path)
            duration = float(probe["format"]["duration"])
            if not any(stream.get("codec_type") == "video" for stream in probe["streams"]) or not math.isfinite(duration) or duration <= 0:
                raise invalid
    except (RuntimeError, KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
        raise invalid from None


def get_video_task(job_id: str, download: bool = False) -> dict:
    """Poll the saved Topaz job without resubmitting. Optionally download and validate its completed video."""
    contracts.PollRequest.model_validate(locals())
    from providers.fal import api as fal_api

    match = JOB_PATTERN.fullmatch(job_id)
    if not match:
        raise ValueError("job_id must be the handle returned by a Topaz submit tool.")
    kind, request_id = match.groups()
    identity = _identity(kind, request_id)
    endpoint = identity["endpoint_id"]
    queue.request_url(endpoint, request_id)
    if dry_run() or request_id.startswith("dry_"):
        return {**identity, "status": "dry_run", "preview_only": True, "downloaded": False}
    result = fal_api._poll_video_task(job_id, endpoint, request_id, download=download)
    if result.get("downloaded"):
        path = Path(result["output_path"])
        try:
            _validate_mp4(path)
        except RuntimeError:
            path.unlink(missing_ok=True)
            raise
    return {**result, **identity}


def list_topaz_models() -> dict:
    """List verified Topaz finishing models and documented example prices without API requests."""
    return {
        "provider": "topaz", "transport": "fal", "dry_run": dry_run(),
        "read_date": "2026-10-09", "evidence": "Vendor capability claims. A/B on Renderhaus footage remains pending.",
        "models": [
            {
                "model": "Starlight Precise 2.6", "direct_model_id": "slp-2.6",
                "endpoint_id": contracts.UPSCALE_ENDPOINT, "capability_id": "topaz_upscale",
                "api_url": contracts.ENDPOINTS[contracts.UPSCALE_ENDPOINT].api_url,
                "pricing_url": f"https://fal.ai/models/{contracts.UPSCALE_ENDPOINT}/pricing",
                "example_prices_usd": {"10s_1080p30": 1.2, "10s_4K30": 2.6, "10s_1080p60": 2.4, "10s_4K60": 5.1},
                **contracts.TRAINING_METADATA,
            },
            *[
                {
                    "model": model, "direct_model_id": direct_id,
                    "endpoint_id": contracts.INTERPOLATE_ENDPOINT, "capability_id": "topaz_interpolate",
                    "api_url": contracts.ENDPOINTS[contracts.INTERPOLATE_ENDPOINT].api_url,
                    "pricing_url": f"https://fal.ai/models/{contracts.INTERPOLATE_ENDPOINT}/pricing",
                    "example_prices_usd": {"10s_1080p_30_to_60": 0.3, "10s_4K_30_to_60": 0.6},
                    **contracts.TRAINING_METADATA,
                }
                for model, direct_id in (("Apollo", "apo-8"), ("Chronos", "chr-2"))
            ],
        ],
    }


TOOL_HANDLERS = {
    "upscale_video": upscale_video,
    "interpolate_video": interpolate_video,
    "get_video_task": get_video_task,
    "list_topaz_models": list_topaz_models,
}
