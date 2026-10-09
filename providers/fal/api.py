"""Wan VACE, Wan 3.0 and Vidu Q4 generation through fal's queue, checked 2026-10-08/09.

https://docs.fal.ai/model-apis/model-endpoints/queue
https://fal.ai/models/fal-ai/wan-vace-14b/api
https://fal.ai/models/fal-ai/wan-22-vace-fun-a14b/api
Per-endpoint contracts and source links live in providers.fal.wan, vidu and wan3.
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
from providers.fal import queue, vidu, wan, wan3
from providers.registry import schema_from_callable
from providers.seedance import contracts as seedance_contracts
from providers.sync import contracts as sync_contracts
from providers.topaz import contracts as topaz_contracts
from providers.mureka import contracts as mureka_contracts


TOOL_CONTRACTS = {tool: contract for contract in (wan, vidu, wan3) for tool in contract.GENERATING_TOOLS}
ENDPOINT_CONTRACTS = {endpoint: contract for contract in (wan, vidu, wan3, seedance_contracts, sync_contracts, topaz_contracts, mureka_contracts) for endpoint in contract.ENDPOINTS}


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
    if not separator or endpoint_id not in ENDPOINT_CONTRACTS:
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
    contract = TOOL_CONTRACTS[tool]
    endpoint, body = contract.request_body(tool, arguments)
    if contract is wan3:
        from server.billing_rates import wan3_price_cents

        estimate = wan3_price_cents(arguments) if body["duration"] is not None else None
    else:
        estimate = None
    if queue.dry_run():
        preview = {}
        if contract is wan3:
            preview = {
                "request_preview": body,
                "estimated_cost_usd": float(estimate / 100) if estimate is not None else None,
                "cost_estimate": (
                    "unknown (smart duration)" if estimate is None
                    else f"${estimate / 100:.2f} provider estimate before Renderhaus fee"
                ),
            }
        return {
            **preview,
            "job_id": _job(endpoint.id, "dry_" + uuid.uuid4().hex),
            "status": "dry_run",
            "provider": "fal",
            "model": endpoint.model,
            "endpoint_id": endpoint.id,
            "mode": tool,
            **contract.TRAINING_METADATA,
            "note": "No fal request made. Set FAL_DRY_RUN=false for live generation.",
        }
    if contract is wan3:
        if estimate is None:
            raise ValueError(
                "Wan 3 smart duration is dry-run only until actual billing reconciliation "
                "is available; cost estimate unknown."
            )
    elif contract is vidu:
        from server.billing_rates import vidu_q4_price_cents

        estimate = vidu_q4_price_cents(body)
    else:
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
            **contract.TRAINING_METADATA,
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
        **contract.TRAINING_METADATA,
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


def vidu_q4_i2v(
    image_url: str,
    prompt: str = "",
    duration: int = 5,
    seed: int | None = None,
    resolution: str = "720p",
    enable_safety_checker: bool = True,
) -> dict:
    """Animate a first frame with Vidu Q4 native audio; poll get_video_task."""
    return _submit("vidu_q4_i2v", locals())


def vidu_q4_r2v(
    prompt: str,
    reference_image_urls: list[str] | None = None,
    reference_audio_urls: list[str] | None = None,
    duration: int = 5,
    seed: int | None = None,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    audio: bool = False,
    enable_safety_checker: bool = True,
) -> dict:
    """Generate Vidu Q4 video using optional image and voice references; poll get_video_task."""
    return _submit("vidu_q4_r2v", locals())


def generate_wan3_t2v(
    prompt: str,
    resolution: str = "1080p",
    aspect_ratio: str = "adaptive",
    duration: int | None = 5,
    audio: bool = True,
    enable_prompt_expansion: bool = True,
    enable_thinking: bool = False,
    seed: int | None = None,
    enable_safety_checker: bool = True,
    real_face_refs: bool = False,
    likeness_consent: bool = False,
) -> dict:
    """Submit Wan 3 text-to-video with native audio; approval required, then poll get_video_task."""
    return _submit("generate_wan3_t2v", locals())


def generate_wan3_i2v(
    start_image_url: str,
    prompt: str | None = None,
    end_image_url: str | None = None,
    resolution: str = "1080p",
    aspect_ratio: str = "adaptive",
    duration: int | None = 5,
    audio: bool = True,
    enable_prompt_expansion: bool = True,
    enable_thinking: bool = False,
    seed: int | None = None,
    enable_safety_checker: bool = True,
    real_face_refs: bool = False,
    likeness_consent: bool = False,
) -> dict:
    """Submit Wan 3 animation of first and optional last frames; real likeness requires consent."""
    return _submit("generate_wan3_i2v", locals())


def generate_wan3_r2v(
    prompt: str | None = None,
    reference_image_urls: list[str] | None = None,
    reference_video_urls: list[str] | None = None,
    reference_audio_urls: list[str] | None = None,
    reference_video_durations: list[float] | None = None,
    reference_video_fps: list[float] | None = None,
    reference_audio_durations: list[float] | None = None,
    file_url: str | None = None,
    web_url: str | None = None,
    resolution: str = "1080p",
    aspect_ratio: str = "adaptive",
    duration: int | None = 5,
    audio: bool = True,
    enable_prompt_expansion: bool = True,
    enable_thinking: bool = False,
    seed: int | None = None,
    enable_safety_checker: bool = True,
    real_face_refs: bool = False,
    likeness_consent: bool = False,
) -> dict:
    """Submit Wan 3 using up to 10 images, 5 videos and 5 audio references; measured video/audio seconds required."""
    return _submit("generate_wan3_r2v", locals())


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
    if (
        queue.dry_run() or request_id.startswith("dry_")
        or (endpoint_id in seedance_contracts.ENDPOINTS and os.getenv("SEEDANCE_DRY_RUN", "true").lower() != "false")
        or (endpoint_id in sync_contracts.ENDPOINTS and os.getenv("SYNC_DRY_RUN", "true").lower() != "false")
        or (endpoint_id in topaz_contracts.ENDPOINTS and os.getenv("TOPAZ_DRY_RUN", "true").lower() != "false")
        or (endpoint_id in mureka_contracts.ENDPOINTS and os.getenv("MUREKA_DRY_RUN", "true").lower() != "false")
    ):
        contract = ENDPOINT_CONTRACTS[endpoint_id]
        endpoint = contract.ENDPOINTS[endpoint_id]
        return {
            "job_id": job_id,
            "provider": "fal",
            "model": endpoint.model,
            "endpoint_id": endpoint_id,
            "status": "dry_run",
            **contract.TRAINING_METADATA,
        }
    return _poll_video_task(job_id, endpoint_id, request_id, download=download)


def _poll_video_task(job_id: str, endpoint_id: str, request_id: str, *, download: bool) -> dict:
    contract = ENDPOINT_CONTRACTS[endpoint_id]
    endpoint = contract.ENDPOINTS[endpoint_id]
    base = {
        "job_id": job_id,
        "provider": "fal",
        "model": endpoint.model,
        "endpoint_id": endpoint_id,
        **contract.TRAINING_METADATA,
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
    if contract is wan3:
        normalized.update(duration=result.get("duration"), actual_prompt=result.get("actual_prompt"))
    if contract not in (sync_contracts, topaz_contracts, mureka_contracts):
        metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
        metadata.update(normalized)
        _write_metadata(metadata_path, metadata)
    return normalized


def list_fal_models() -> dict:
    """List documented Wan VACE, Wan 3.0 and Vidu Q4 endpoints and pricing without calling fal."""
    from server.billing_rates import (
        VIDU_Q4_LIST_CENTS_PER_SECOND,
        VIDU_Q4_PROMO_EXPIRES_ON,
        WAN3_CENTS_PER_SECOND,
        vidu_q4_rates,
    )

    q4_rates = vidu_q4_rates()
    return {
        "status": "dry_run" if queue.dry_run() else "ok",
        "selected_model": wan3.TOOL_ENDPOINTS["generate_wan3_t2v"],
        "models": [{"id": model, **wan.TRAINING_METADATA} for model in wan.MODELS]
        + [
            {"id": endpoint, "license": "service-terms", **vidu.TRAINING_METADATA}
            for endpoint in vidu.ENDPOINTS
        ] + [{"id": endpoint, **wan3.TRAINING_METADATA} for endpoint in wan3.ENDPOINTS],
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
        ]
        + [
            {
                "id": endpoint.id,
                "model": endpoint.model,
                "endpoint_id": endpoint.id,
                "mode": endpoint.tool,
                "api_url": endpoint.api_url,
                "pricing_url": endpoint.api_url.removesuffix("/api"),
                "price_unit": "video_second",
                "pricing_checked_at": "2026-10-08",
                "usd_per_unit_by_resolution": {
                    resolution: str(rate / 100) for resolution, rate in q4_rates.items()
                },
                "list_usd_per_unit_by_resolution": {
                    resolution: str(rate / 100)
                    for resolution, rate in VIDU_Q4_LIST_CENTS_PER_SECOND.items()
                },
                "promo_expires_on": VIDU_Q4_PROMO_EXPIRES_ON.isoformat(),
                "promo_expiry_basis": "User-confirmed inclusive UTC date; pricing pages omit the year.",
                "pricing_confirmed": True,
                "audio_surcharge": False,
                "license": "service-terms",
                **vidu.TRAINING_METADATA,
            }
            for endpoint in vidu.ENDPOINTS.values()
        ] + [
            {
                "id": endpoint.id,
                "model": endpoint.model,
                "endpoint_id": endpoint.id,
                "mode": endpoint.tool,
                "api_url": endpoint.api_url,
                "pricing_url": endpoint.api_url.removesuffix("/api"),
                "price_unit": "output_and_reference_video_second",
                "pricing_checked_at": "2026-10-09",
                "usd_per_unit_by_resolution": {
                    resolution: str(rate / 100) for resolution, rate in WAN3_CENTS_PER_SECOND.items()
                },
                "pricing_confirmed": True,
                **wan3.TRAINING_METADATA,
            }
            for endpoint in wan3.ENDPOINTS.values()
        ],
        "note": "Static documented catalog. Does not confirm account access. fal hosted Terms of Service apply.",
    }


TOOL_HANDLERS = {
    "text_to_video": text_to_video,
    "image_to_video": image_to_video,
    "reference_to_video": reference_to_video,
    "video_to_video": video_to_video,
    "vidu_q4_i2v": vidu_q4_i2v,
    "vidu_q4_r2v": vidu_q4_r2v,
    "generate_wan3_t2v": generate_wan3_t2v,
    "generate_wan3_i2v": generate_wan3_i2v,
    "generate_wan3_r2v": generate_wan3_r2v,
    "get_video_task": get_video_task,
    "list_fal_models": list_fal_models,
}
GATEWAY_TOOLS = tuple(TOOL_HANDLERS)
