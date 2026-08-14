"""Seedance (BytePlus video) provider API."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel
from pydantic.fields import FieldInfo


class SeedanceTask(BaseModel):
    job_id: str
    status: str
    provider: str = "byteplus-seedance"
    mode: str
    prompt: str
    duration_seconds: int
    aspect_ratio: str
    resolution: str
    model: str | None = None
    estimated_cost_usd: float | None = None
    output_path: str | None = None
    video_url: str | None = None
    note: str


TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "canceled", "deleted"}

# Seedance 1.5 Pro accepts 4-12 second clips; longer requests are rejected by BytePlus.
MIN_DURATION_SECONDS = 4
MAX_DURATION_SECONDS = 12


def _field_value(value: Any, default: Any) -> Any:
    if isinstance(value, FieldInfo):
        return getattr(value, "default", default)
    return value


def _media_dir() -> Path:
    path = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _dry_run() -> bool:
    return os.getenv("SEEDANCE_DRY_RUN", "true").lower() != "false"


def _base_url() -> str:
    base_url = os.getenv(
        "BYTEPLUS_BASE_URL",
        "https://ark.ap-southeast.bytepluses.com/api/v3",
    ).rstrip("/")
    if not base_url.endswith("/api/v3"):
        base_url = f"{base_url}/api/v3"
    return base_url


def _model(model: str | None = None) -> str:
    return model or os.getenv("SEEDANCE_MODEL") or "seedance-1-5-pro-251215"


def _supports_service_tier(model: str) -> bool:
    # Seedance 2.0 T2V rejects service_tier entirely; older Seedance models may support it.
    return not model.startswith("dreamina-seedance-2-0")


def _api_key() -> str:
    key = os.getenv("BYTEPLUS_API_KEY") or os.getenv("ARK_API_KEY")
    if not key:
        raise RuntimeError("BYTEPLUS_API_KEY or ARK_API_KEY is required for live Seedance calls.")
    return key


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }


def _video_dir() -> Path:
    path = _media_dir() / "video"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _task_meta_dir() -> Path:
    path = _video_dir() / ".tasks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _task_meta_path(job_id: str) -> Path:
    return _task_meta_dir() / f"{job_id}.json"


def _write_task_meta(job_id: str, metadata: dict[str, Any]) -> None:
    _task_meta_path(job_id).write_text(json.dumps(metadata, indent=2, sort_keys=True))


def _read_task_meta(job_id: str) -> dict[str, Any]:
    path = _task_meta_path(job_id)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _output_path(job_id: str) -> Path:
    return _video_dir() / f"{job_id}.mp4"


def _as_modelark_image_url(path_or_url: str) -> str:
    if path_or_url.startswith(("http://", "https://", "data:")):
        return path_or_url

    path = Path(path_or_url).expanduser()
    if not path.exists():
        return path_or_url

    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _extract_video_url(response: dict[str, Any]) -> str | None:
    content = response.get("content")
    if isinstance(content, dict):
        video_url = content.get("video_url")
        if isinstance(video_url, str):
            return video_url
    return None


def _download_video(video_url: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", video_url, follow_redirects=True, timeout=120) as response:
        response.raise_for_status()
        with output_path.open("wb") as file:
            for chunk in response.iter_bytes():
                if chunk:
                    file.write(chunk)


def _provider_error(response: httpx.Response) -> RuntimeError:
    try:
        payload = response.json()
    except ValueError:
        message = response.text[:1000]
        return RuntimeError(f"BytePlus API error {response.status_code}: {message}")

    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        code = error.get("code") or "UnknownCode"
        message = error.get("message") or payload
        return RuntimeError(f"BytePlus API error {response.status_code} ({code}): {message}")
    return RuntimeError(f"BytePlus API error {response.status_code}: {payload}")


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_error:
        raise _provider_error(response)


def _dry_task(
    *,
    mode: str,
    prompt: str,
    duration_seconds: int,
    aspect_ratio: str,
    resolution: str,
    model: str | None,
) -> dict:
    job_id = f"seedance_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    output_path = _output_path(job_id)
    return SeedanceTask(
        job_id=job_id,
        status="dry_run",
        mode=mode,
        prompt=prompt,
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        model=_model(model),
        output_path=str(output_path),
        note="Dry run only. Set SEEDANCE_DRY_RUN=false to create a live BytePlus task.",
    ).model_dump()


def _create_task(
    *,
    mode: str,
    content: list[dict[str, Any]],
    prompt: str,
    duration_seconds: int,
    aspect_ratio: str,
    resolution: str,
    model: str | None,
    watermark: bool,
    generate_audio: bool,
    service_tier: Literal["default", "flex"] | None,
) -> dict:
    selected_model = _model(model)
    body: dict[str, Any] = {
        "model": selected_model,
        "content": content,
        "ratio": aspect_ratio,
        "duration": duration_seconds,
        "resolution": resolution,
        "watermark": watermark,
    }
    if service_tier is not None and _supports_service_tier(selected_model):
        body["service_tier"] = service_tier
    body["generate_audio"] = generate_audio

    url = f"{_base_url()}/contents/generations/tasks"
    with httpx.Client(timeout=60) as client:
        response = client.post(url, headers=_headers(), json=body)
        _raise_for_status(response)
        payload = response.json()

    job_id = payload.get("id")
    if not job_id:
        raise RuntimeError(f"BytePlus did not return a task id: {payload}")

    output_path = _output_path(job_id)
    metadata = {
        "job_id": job_id,
        "mode": mode,
        "prompt": prompt,
        "model": selected_model,
        "duration_seconds": duration_seconds,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "output_path": str(output_path),
        "create_response": payload,
        "created_at": int(time.time()),
    }
    _write_task_meta(job_id, metadata)

    return SeedanceTask(
        job_id=job_id,
        status="queued",
        mode=mode,
        prompt=prompt,
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        model=selected_model,
        output_path=str(output_path),
        note="Live BytePlus task created. Call get_video_task to poll it.",
    ).model_dump()


def _retrieve_task(job_id: str, download: bool) -> dict:
    if _dry_run():
        return {
            "job_id": job_id,
            "status": "dry_run",
            "provider": "byteplus-seedance",
            "note": "Dry run is enabled; no live BytePlus task exists.",
        }

    url = f"{_base_url()}/contents/generations/tasks/{job_id}"
    with httpx.Client(timeout=60) as client:
        response = client.get(url, headers=_headers())
        _raise_for_status(response)
        payload = response.json()

    status = payload.get("status", "unknown")
    video_url = _extract_video_url(payload)
    metadata = _read_task_meta(job_id)
    output_path = Path(metadata.get("output_path") or _output_path(job_id))
    downloaded = False

    if download and status == "succeeded" and video_url:
        if not output_path.exists() or output_path.stat().st_size == 0:
            _download_video(video_url, output_path)
        downloaded = True

    metadata.update(
        {
            "job_id": job_id,
            "status": status,
            "video_url": video_url,
            "output_path": str(output_path),
            "last_response": payload,
            "updated_at": int(time.time()),
        }
    )
    _write_task_meta(job_id, metadata)

    return {
        "job_id": job_id,
        "status": status,
        "provider": "byteplus-seedance",
        "model": payload.get("model") or metadata.get("model"),
        "video_url": video_url,
        "output_path": str(output_path) if downloaded or output_path.exists() else None,
        "downloaded": downloaded,
        "usage": payload.get("usage"),
        "raw": payload,
    }


def text_to_video(
    prompt: str,
    duration_seconds: int = 5,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    model: str | None = None,
    watermark: bool = False,
    generate_audio: bool = False,
    service_tier: Literal["default", "flex"] | None = None,
) -> dict:
    """Create a Seedance text-to-video task and return the task id."""
    duration_seconds = int(_field_value(duration_seconds, 5))
    duration_seconds = max(MIN_DURATION_SECONDS, min(MAX_DURATION_SECONDS, duration_seconds))
    aspect_ratio = str(_field_value(aspect_ratio, "16:9"))
    resolution = str(_field_value(resolution, "720p"))
    model = _field_value(model, None)
    watermark = bool(_field_value(watermark, False))
    generate_audio = bool(_field_value(generate_audio, False))
    service_tier = _field_value(service_tier, None)
    if _dry_run():
        return _dry_task(
            mode="text_to_video",
            prompt=prompt,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            model=model,
        )
    return _create_task(
        mode="text_to_video",
        content=[{"type": "text", "text": prompt}],
        prompt=prompt,
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        model=model,
        watermark=watermark,
        generate_audio=generate_audio,
        service_tier=service_tier,
    )


def image_to_video(
    image_path_or_url: str,
    prompt: str,
    duration_seconds: int = 5,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    model: str | None = None,
    watermark: bool = False,
    generate_audio: bool = False,
    service_tier: Literal["default", "flex"] | None = None,
) -> dict:
    """Create a Seedance image-to-video task and return the task id."""
    duration_seconds = int(_field_value(duration_seconds, 5))
    duration_seconds = max(MIN_DURATION_SECONDS, min(MAX_DURATION_SECONDS, duration_seconds))
    aspect_ratio = str(_field_value(aspect_ratio, "16:9"))
    resolution = str(_field_value(resolution, "720p"))
    model = _field_value(model, None)
    watermark = bool(_field_value(watermark, False))
    generate_audio = bool(_field_value(generate_audio, False))
    service_tier = _field_value(service_tier, None)
    if _dry_run():
        return _dry_task(
            mode="image_to_video",
            prompt=f"{prompt}\nReference image: {image_path_or_url}",
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            model=model,
        )
    return _create_task(
        mode="image_to_video",
        content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": _as_modelark_image_url(image_path_or_url)}},
        ],
        prompt=f"{prompt}\nReference image: {image_path_or_url}",
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        model=model,
        watermark=watermark,
        generate_audio=generate_audio,
        service_tier=service_tier,
    )


def get_video_task(
    job_id: str,
    download: bool = False,
) -> dict:
    """Retrieve a Seedance task status and optionally download the finished MP4."""
    download = bool(_field_value(download, False))
    return _retrieve_task(job_id=job_id, download=download)


def wait_for_video_task(
    job_id: str,
    timeout_seconds: int = 600,
    poll_interval_seconds: int = 5,
    download: bool = True,
) -> dict:
    """Poll a Seedance task until it reaches a terminal status or times out."""
    timeout_seconds = int(_field_value(timeout_seconds, 600))
    poll_interval_seconds = int(_field_value(poll_interval_seconds, 5))
    download = bool(_field_value(download, True))
    deadline = time.time() + timeout_seconds
    last_result: dict[str, Any] = {}

    while time.time() < deadline:
        last_result = _retrieve_task(job_id=job_id, download=download)
        status = str(last_result.get("status", "")).lower()
        if status in TERMINAL_STATUSES:
            return last_result
        time.sleep(poll_interval_seconds)

    return {
        **last_result,
        "timed_out": True,
        "note": f"Timed out after {timeout_seconds}s waiting for Seedance task {job_id}.",
    }


def text_to_video_and_wait(
    prompt: str,
    duration_seconds: int = 4,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    timeout_seconds: int = 600,
    poll_interval_seconds: int = 5,
    model: str | None = None,
    watermark: bool = False,
    generate_audio: bool = False,
    service_tier: Literal["default", "flex"] | None = None,
) -> dict:
    """Create a Seedance text-to-video task, poll it, and download the finished MP4."""
    duration_seconds = int(_field_value(duration_seconds, 4))
    aspect_ratio = str(_field_value(aspect_ratio, "16:9"))
    resolution = str(_field_value(resolution, "720p"))
    timeout_seconds = int(_field_value(timeout_seconds, 600))
    poll_interval_seconds = int(_field_value(poll_interval_seconds, 5))
    model = _field_value(model, None)
    watermark = bool(_field_value(watermark, False))
    generate_audio = bool(_field_value(generate_audio, False))
    service_tier = _field_value(service_tier, None)
    created = text_to_video(
        prompt=prompt,
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        model=model,
        watermark=watermark,
        generate_audio=generate_audio,
        service_tier=service_tier,
    )
    if created.get("status") == "dry_run":
        return created
    result = wait_for_video_task(
        job_id=created["job_id"],
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        download=True,
    )
    return {"created": created, "result": result}


def list_seedance_models() -> dict:
    """List Seedance/video generation models visible from this BytePlus API key."""
    if _dry_run():
        return {
            "status": "dry_run",
            "models": [],
            "note": "Dry run is enabled; set SEEDANCE_DRY_RUN=false to query BytePlus /models.",
        }

    with httpx.Client(timeout=60) as client:
        response = client.get(f"{_base_url()}/models", headers=_headers())
        _raise_for_status(response)
        payload = response.json()

    models = []
    for item in payload.get("data", []):
        text = json.dumps(item).lower()
        if "seedance" not in text and "videogeneration" not in text:
            continue
        models.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "status": item.get("status"),
                "domain": item.get("domain"),
                "task_type": item.get("task_type"),
                "modalities": item.get("modalities"),
            }
        )

    return {
        "status": "ok",
        "selected_model": _model(),
        "models": models,
        "note": (
            "Model visibility does not guarantee activation. If generation returns ModelNotOpen, "
            "activate that model service or buy the matching resource pack in Ark Console."
        ),
    }


TOOL_HANDLERS = {
    "text_to_video": text_to_video,
    "image_to_video": image_to_video,
    "get_video_task": get_video_task,
    "wait_for_video_task": wait_for_video_task,
    "text_to_video_and_wait": text_to_video_and_wait,
    "list_seedance_models": list_seedance_models,
}

GATEWAY_TOOLS = (
    "text_to_video",
    "image_to_video",
    "get_video_task",
    "list_seedance_models",
)
