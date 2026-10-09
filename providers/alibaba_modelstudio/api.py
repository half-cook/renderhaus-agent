from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from providers.alibaba_modelstudio import config, contracts
from providers.contracts import validate_tool_arguments
from providers.registry import schema_from_callable


SUBMIT_PATH = "/api/v1/services/aigc/video-generation/video-synthesis"
STATES = {"PENDING": "queued", "RUNNING": "running", "SUCCEEDED": "succeeded",
          "FAILED": "failed", "CANCELED": "cancelled", "CANCELLED": "cancelled", "UNKNOWN": "unknown"}
MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024
TASK_PATTERN = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
DRY_PATTERN = re.compile(r"dry_[0-9a-f]{32}")


def _validated(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool not in TOOL_HANDLERS:
        raise ValueError("Unknown Model Studio tool.")
    schema = schema_from_callable(tool, TOOL_HANDLERS[tool])["inputSchema"]
    return validate_tool_arguments("alibaba_modelstudio", tool, arguments, schema)


def _task_id(job_id: Any) -> str:
    if not isinstance(job_id, str) or not (TASK_PATTERN.fullmatch(job_id) or DRY_PATTERN.fullmatch(job_id)):
        raise ValueError("job_id must be the exact task UUID returned by Model Studio.")
    return job_id.lower()


def _paths(job_id: str) -> tuple[Path, Path]:
    directory = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")) / "video"
    filename = "modelstudio_" + hashlib.sha256(job_id.encode()).hexdigest()
    return directory / ".tasks" / "alibaba_modelstudio" / f"{filename}.json", directory / f"{filename}.mp4"


def _sanitize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_metadata(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_metadata(item) for item in value]
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        parsed = urlsplit(value)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _write_metadata(path: Path, metadata: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        stored = {key: value for key, value in metadata.items() if key != "video_url"}
        temporary.write_text(json.dumps(_sanitize_metadata(stored), indent=2, allow_nan=False))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _save(path: Path, metadata: dict[str, Any], result: dict[str, Any]) -> None:
    try:
        _write_metadata(path, metadata)
    except OSError:
        result["warning"] = "Task retained, but local metadata could not be saved. Keep its job_id before retrying."


def _request(method: str, configuration: config.Settings, path: str,
             body: dict[str, Any] | None = None) -> dict[str, Any]:
    key = os.getenv("DASHSCOPE_API_KEY")
    if not key:
        raise RuntimeError("DASHSCOPE_API_KEY is required for live Model Studio calls.")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if method == "POST":
        headers["X-DashScope-Async"] = "enable"
    with httpx.Client(timeout=60, follow_redirects=False) as client:
        response = client.request(method, configuration.base_url + path, headers=headers, json=body)
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Model Studio returned non-JSON HTTP {response.status_code}.") from exc
    if response.is_error or response.is_redirect:
        code = payload.get("code") if isinstance(payload, dict) else "non-object response"
        raise RuntimeError(f"Model Studio API error {response.status_code}: {code}.")
    if not isinstance(payload, dict):
        raise RuntimeError("Model Studio returned a non-object response.")
    return payload


def _output(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    output = payload.get("output")
    if (not isinstance(output, dict) or not isinstance(output.get("task_status"), str)
            or output["task_status"] not in STATES):
        raise RuntimeError("Model Studio returned a missing or unknown task status.")
    return output, STATES[output["task_status"]]


def _base(configuration: config.Settings) -> dict[str, Any]:
    return {"provider": "alibaba_modelstudio", "model": configuration.model,
            "region": configuration.region, "endpoint_verification": configuration.endpoint_verification,
            **contracts.TRAINING_METADATA}


def _submit(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    arguments = _validated(tool, arguments)
    configuration = config.settings()
    body = contracts.request_body(tool, arguments, configuration.model)
    try:
        estimate = contracts.price_cents(tool, arguments, region=configuration.region, model=configuration.model)
    except ValueError:
        if arguments.get("duration", -1) != -1 and configuration.model == config.DEFAULT_MODEL:
            raise
        estimate = None
    base = {**_base(configuration), "mode": tool,
            "estimated_cost_usd": float(estimate / 100) if estimate is not None else None,
            "cost_estimate": "unknown (smart duration or UNVERIFIED model)" if estimate is None
            else f"${estimate / 100:.4f} provider estimate before Renderhaus fee"}
    if config.dry_run():
        return {**base, "job_id": "dry_" + uuid.uuid4().hex, "status": "dry_run", "request_preview": body,
                "base_url": configuration.base_url,
                "note": "No provider request made. MODELSTUDIO_DRY_RUN defaults to true."}
    blocker = config.live_blocker(configuration)
    if blocker:
        raise ValueError(blocker)
    if estimate is None:
        raise ValueError("Model Studio smart duration is dry-run only until actual billing reconciliation and an approval bound exist.")
    payload = _request("POST", configuration, SUBMIT_PATH, body)
    output, status = _output(payload)
    job_id = _task_id(output.get("task_id"))
    if DRY_PATTERN.fullmatch(job_id):
        raise RuntimeError("Model Studio returned a dry-run ID for a live task.")
    result = {**base, "job_id": job_id, "status": "queued" if status == "succeeded" else status,
              "error_code": output.get("code"), "error": output.get("message"),
              "note": "Poll get_task with this job_id. A queued task is not a completed video."}
    metadata = {**result, "arguments": arguments, "base_url": configuration.base_url,
                "pricing_checked_at": "2026-10-09", "price_source": contracts.PRICING_URL}
    _save(_paths(job_id)[0], metadata, result)
    return result


def edit_wan3_video(
    video_url: str, prompt: str, source_duration_seconds: float, source_fps: float,
    duration: int = -1, resolution: str = "1080p", aspect_ratio: str = "adaptive",
    audio: bool = True, prompt_extend: bool = True, watermark: bool = False,
    seed: int | None = None, reference_image_urls: list[str] | None = None,
    reference_audio_urls: list[str] | None = None, reference_audio_durations: list[float] | None = None,
    real_face_refs: bool = False, likeness_consent: bool = False,
) -> dict:
    """Preview Wan 3 edits offline; its evaluation-only preview licence blocks live customer use."""
    return _submit("edit_wan3_video", locals())


def extend_wan3_video(
    video_url: str, prompt: str, source_duration_seconds: float, source_fps: float,
    duration: int = -1, resolution: str = "1080p", aspect_ratio: str = "adaptive",
    audio: bool = True, prompt_extend: bool = True, watermark: bool = False,
    seed: int | None = None, reference_image_urls: list[str] | None = None,
    reference_audio_urls: list[str] | None = None, reference_audio_durations: list[float] | None = None,
    real_face_refs: bool = False, likeness_consent: bool = False, direction: str = "forward",
) -> dict:
    """Preview Wan 3 extensions offline; duration is total output seconds and preview licensing blocks live use."""
    return _submit("extend_wan3_video", locals())


def _download(video_url: str, output_path: Path) -> None:
    contracts.validate_url(video_url, "video_url")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(f".{uuid.uuid4().hex}.part")
    try:
        with httpx.Client(timeout=120, follow_redirects=False) as client:
            for _ in range(6):
                with client.stream("GET", video_url) as response:
                    if response.is_redirect:
                        video_url = str(response.url.join(response.headers.get("location", "")))
                        contracts.validate_url(video_url, "video_url")
                        continue
                    response.raise_for_status()
                    size = 0
                    with temporary.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > MAX_DOWNLOAD_BYTES:
                                raise RuntimeError("Model Studio video exceeds the download size limit.")
                            handle.write(chunk)
                    if size == 0:
                        raise RuntimeError("Model Studio returned an empty video.")
                    temporary.replace(output_path)
                    return
            raise RuntimeError("Model Studio video exceeded the download redirect limit.")
    finally:
        temporary.unlink(missing_ok=True)


def _actual_cost(usage: Any, metadata: dict[str, Any], configuration: config.Settings) -> float | None:
    duration = usage.get("duration") if isinstance(usage, dict) else None
    if (isinstance(duration, bool) or not isinstance(duration, (int, float))
            or not math.isfinite(duration) or not 0 < duration <= 30):
        return None
    for field in ("input_video_duration", "output_video_duration"):
        value = usage.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not math.isfinite(value) or value < 0):
            return None
        if value is not None and value > (15 if field == "input_video_duration" else 30):
            return None
    if all(field in usage for field in ("input_video_duration", "output_video_duration")):
        measured = Decimal(str(usage["input_video_duration"])) + Decimal(str(usage["output_video_duration"]))
        if abs(measured - Decimal(str(duration))) > Decimal("0.01"):
            return None
    arguments = metadata.get("arguments")
    resolution = arguments.get("resolution", "1080p") if isinstance(arguments, dict) else None
    if "SR" in usage:
        sr = usage["SR"]
        resolution = {480: "480p", 720: "720p", 1080: "1080p"}.get(sr) if type(sr) is int else None
    if configuration.model != config.DEFAULT_MODEL or resolution not in contracts.RESOLUTIONS:
        return None
    return float(contracts.CENTS_PER_SECOND[configuration.region][resolution] * Decimal(str(duration)) / 100)


def get_task(job_id: str, download: bool = True) -> dict:
    """Poll one saved Model Studio task and optionally persist its completed MP4 and provenance."""
    _validated("get_task", locals())
    job_id = _task_id(job_id)
    if DRY_PATTERN.fullmatch(job_id):
        return {"job_id": job_id, "provider": "alibaba_modelstudio", "status": "dry_run", **contracts.TRAINING_METADATA}
    metadata_path, output_path = _paths(job_id)
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    if not isinstance(metadata, dict) or metadata.get("job_id", job_id) != job_id:
        raise RuntimeError("Saved Model Studio task metadata is invalid.")
    if config.dry_run():
        return {"job_id": job_id, "status": "dry_run", **_base(config.settings())}
    configuration = config.settings(**{field: metadata[field] for field in ("base_url", "region", "model") if field in metadata})
    blocker = config.live_blocker(configuration)
    if blocker:
        raise ValueError(blocker)
    if metadata.get("status") == "succeeded" and output_path.exists() and output_path.stat().st_size:
        return {**metadata, **_base(configuration), "output_path": str(output_path), "downloaded": True}
    payload = _request("GET", configuration, f"/api/v1/tasks/{job_id}")
    output, status = _output(payload)
    if output.get("task_id") is not None and _task_id(output["task_id"]) != job_id:
        raise RuntimeError("Model Studio returned a different task_id.")
    result = {**_base(configuration), "job_id": job_id, "status": status,
              "error_code": output.get("code"), "error": output.get("message")}
    if status == "succeeded":
        video_url = contracts.validate_url(output.get("video_url"), "video_url")
        if download and (not output_path.exists() or not output_path.stat().st_size):
            _download(video_url, output_path)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        actual = _actual_cost(usage, metadata, configuration)
        result.update(video_url=video_url, output_path=str(output_path) if output_path.exists() else None,
                      downloaded=output_path.exists(), usage=usage, actual_cost_usd=actual,
                      actual_cost_estimate="unknown" if actual is None else "documented aggregate billed seconds")
    _save(metadata_path, {**metadata, **result, "base_url": configuration.base_url}, result)
    return result


TOOL_HANDLERS = {"edit_wan3_video": edit_wan3_video, "extend_wan3_video": extend_wan3_video, "get_task": get_task}
GATEWAY_TOOLS = tuple(TOOL_HANDLERS)
