"""Official Luma Ray 3.2 submit and single-poll video tools.

Contracts checked on 2026-10-08 against the official documentation.
https://docs.lumalabs.ai/docs/welcome
https://docs.agents.lumalabs.ai/guides/videos/generation/
https://docs.agents.lumalabs.ai/guides/videos/editing/
https://docs.agents.lumalabs.ai/guides/videos/migration/
https://docs.agents.lumalabs.ai/api/resources/generations/methods/get/
"""

from __future__ import annotations

import base64
import json
import math
import mimetypes
import os
import struct
import tempfile
import time
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from providers.luma.catalog import (
    ASPECT_RATIOS,
    DOCS_VERIFIED_DATE,
    DURATIONS,
    EDIT_STRENGTHS,
    EXTEND_RESOLUTIONS,
    MODEL,
    MODEL_IDS,
    RESOLUTIONS,
)

API_BASE_URL = "https://agents.lumalabs.ai/v1"
MAX_IMAGE_BYTES = 50 * 1024 * 1024
MAX_VIDEO_BYTES = 200 * 1024 * 1024
# This adapter allows one 24fps frame of timing drift; Luma publishes no duration tolerance.
FRAME_TOLERANCE_SECONDS = 1 / 24
_STATUSES = {
    "queued": "queued",
    "processing": "running",
    "completed": "succeeded",
    "failed": "failed",
}
_METADATA_FIELDS = (
    "prompt",
    "duration_seconds",
    "source_duration_seconds",
    "aspect_ratio",
    "resolution",
    "direction",
)


@dataclass(frozen=True, slots=True)
class LumaTask:
    job_id: str
    status: str
    provider: str = "luma"
    model: str = MODEL
    training_eligible: bool = False
    mode: str | None = None
    prompt: str | None = None
    duration_seconds: int | None = None
    source_duration_seconds: int | None = None
    aspect_ratio: str | None = None
    resolution: str | None = None
    direction: str | None = None
    video_url: str | None = None
    output_path: str | None = None
    downloaded: bool = False
    failure_code: str | None = None
    failure_reason: str | None = None
    note: str = ""


def _dry_run() -> bool:
    return os.getenv("LUMA_DRY_RUN", "true").lower() != "false"


def _generation_id(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Luma generation id must be a UUID.")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ValueError("Luma generation id must be a UUID.") from exc
    if str(parsed) != value:
        raise ValueError("Luma generation id must be a canonical UUID.")
    return value


def _choice(name: str, value: Any, choices: tuple[Any, ...]) -> None:
    if isinstance(value, bool) or value not in choices:
        raise ValueError(f"Luma {name} must be one of {', '.join(map(str, choices))}.")


def _reference(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Luma {name} must be a non-empty media reference.")
    if value.startswith(("http://", "https://")):
        parsed = urlsplit(value)
        if not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(f"Luma {name} must be an HTTP URL without embedded credentials.")


def validate_generation_arguments(tool: str, arguments: dict[str, Any]) -> None:
    """Validate generation choices and combinations without credentials, files, or HTTP."""
    if tool not in {"text_to_video", "image_to_video", "extend_video", "modify_video"}:
        raise ValueError(f"Unknown Luma generation tool: {tool}")
    prompt = arguments.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or not 1 <= len(prompt) <= 6000:
        raise ValueError("Luma prompt must contain 1 to 6000 characters.")
    _choice("model", arguments.get("model", MODEL), MODEL_IDS)
    resolutions = EXTEND_RESOLUTIONS if tool == "extend_video" else RESOLUTIONS
    _choice("resolution", arguments.get("resolution", "720p"), resolutions)
    if tool in {"text_to_video", "image_to_video"}:
        duration = arguments.get("duration_seconds", 5)
        if not isinstance(duration, int):
            raise ValueError("Luma duration_seconds must be an integer.")
        _choice("duration_seconds", duration, DURATIONS if tool == "text_to_video" else (5,))
        _choice("aspect_ratio", arguments.get("aspect_ratio", "16:9"), ASPECT_RATIOS)
    if tool == "image_to_video":
        anchors = [arguments.get(name) for name in ("image_path_or_url", "last_frame_path_or_url")]
        if all(value is None for value in anchors):
            raise ValueError("Luma image_to_video requires a start image or an end image.")
        for name, value in zip(("image_path_or_url", "last_frame_path_or_url"), anchors):
            if value is not None:
                _reference(name, value)
    if tool == "extend_video":
        _generation_id(arguments.get("generation_id"))
        _choice("direction", arguments.get("direction", "forward"), ("forward", "backward"))
    if tool == "modify_video":
        duration = arguments.get("source_duration_seconds")
        if not isinstance(duration, int):
            raise ValueError("Luma source_duration_seconds must be an integer.")
        _choice("source_duration_seconds", duration, DURATIONS)
        source = arguments.get("video_path_or_url")
        generation = arguments.get("source_generation_id")
        if (source is None) == (generation is None):
            raise ValueError("Luma modify_video requires exactly one video source.")
        if source is not None:
            _reference("video_path_or_url", source)
        if generation is not None:
            _generation_id(generation)
        strength = arguments.get("strength")
        if strength is not None:
            _choice("strength", strength, EDIT_STRENGTHS)


def _headers() -> dict[str, str]:
    key = os.getenv("LUMA_API_KEY")
    if not key:
        raise RuntimeError("LUMA_API_KEY is required for live Luma calls.")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _raise_for_status(response: httpx.Response) -> None:
    if not response.is_error:
        return
    try:
        payload = response.json()
    except ValueError:
        detail = response.text[:1000]
    else:
        detail = (
            payload.get("detail", payload.get("error", payload))
            if isinstance(payload, dict)
            else payload
        )
    raise RuntimeError(f"Luma API error {response.status_code}: {str(detail)[:1000]}")


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=60) as client:
            response = client.request(
                method, f"{API_BASE_URL}{path}", headers=_headers(), json=body
            )
            _raise_for_status(response)
    except httpx.RequestError as exc:
        raise RuntimeError(f"Luma request failed: {exc}") from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("Luma returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Luma returned an invalid generation response.")
    return payload


def _video_dir() -> Path:
    return (
        Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser() / "video" / "luma"
    )


def _metadata_path(job_id: str) -> Path:
    return _video_dir() / ".tasks" / f"{_generation_id(job_id)}.json"


def _read_metadata(job_id: str) -> dict[str, Any]:
    path = _metadata_path(job_id)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise RuntimeError("Luma task metadata is invalid.")
    return payload


def _write_metadata(job_id: str, metadata: dict[str, Any]) -> None:
    path = _metadata_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps({**metadata, "training_eligible": False}, indent=2))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _normalized(
    payload: dict[str, Any], metadata: dict[str, Any], expected_id: str | None = None
) -> LumaTask:
    try:
        job_id = _generation_id(payload.get("id"))
    except ValueError as exc:
        raise RuntimeError("Luma returned an invalid generation id.") from exc
    if expected_id is not None and job_id != expected_id:
        raise RuntimeError("Luma returned a different generation id.")
    state = payload.get("state")
    if not isinstance(state, str) or state not in _STATUSES:
        raise RuntimeError(f"Luma returned an unknown generation state: {state!r}.")
    if payload.get("model", MODEL) != MODEL:
        raise RuntimeError("Luma returned an unexpected video model.")
    for name in ("failure_code", "failure_reason"):
        if payload.get(name) is not None and not isinstance(payload[name], str):
            raise RuntimeError(f"Luma returned an invalid {name}.")
    video_url = None
    if state == "completed":
        outputs = payload.get("output")
        if isinstance(outputs, list):
            video_url = next(
                (
                    item.get("url")
                    for item in outputs
                    if isinstance(item, dict)
                    and item.get("type") == "video"
                    and isinstance(item.get("url"), str)
                    and item["url"].startswith(("https://", "http://"))
                ),
                None,
            )
        if not video_url:
            raise RuntimeError("Luma completed without a usable video output.")
    return LumaTask(
        job_id=job_id,
        status=_STATUSES[state],
        mode=metadata.get("mode"),
        **{name: metadata.get(name) for name in _METADATA_FIELDS},
        video_url=video_url,
        failure_code=payload.get("failure_code"),
        failure_reason=payload.get("failure_reason"),
        note=payload.get("failure_reason") or "Call get_video_task to retrieve the video.",
    )


def _download(url: str, destination: Path, limit: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                length = response.headers.get("content-length")
                expected_bytes = int(length) if length and length.isdigit() else None
                if expected_bytes is not None and expected_bytes > limit:
                    raise ValueError("Luma media exceeds the supported download size.")
                downloaded = 0
                with temporary.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        downloaded += len(chunk)
                        if downloaded > limit:
                            raise ValueError("Luma media exceeds the supported download size.")
                        handle.write(chunk)
                if not downloaded or (expected_bytes is not None and downloaded != expected_bytes):
                    raise RuntimeError("Luma media download was empty or incomplete.")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _read_media(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError("Luma input media is empty or exceeds the supported size.")
    return data


def _image_reference(value: str) -> dict[str, str]:
    if value.startswith(("http://", "https://")):
        return {"url": value}
    if value.startswith("data:"):
        header, separator, encoded = value.partition(",")
        mime_type = header.removeprefix("data:").removesuffix(";base64")
        if not separator or not header.endswith(";base64") or not mime_type.startswith("image/"):
            raise ValueError("Luma inline images require a base64 image data URL.")
        try:
            data = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError("Luma inline image contains invalid base64.") from exc
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ValueError("Luma image exceeds the supported size or is empty.")
        return {"data": encoded, "media_type": mime_type}
    path = Path(value).expanduser()
    mime_type = mimetypes.guess_type(path.name)[0] or ""
    if not mime_type.startswith("image/"):
        raise ValueError("Luma local image must have an image file extension.")
    data = _read_media(path, MAX_IMAGE_BYTES)
    return {"data": base64.b64encode(data).decode("ascii"), "media_type": mime_type}


def _atoms(data: bytes, start: int, end: int) -> Iterator[tuple[bytes, int, int]]:
    cursor = start
    while cursor < end:
        if end - cursor < 8:
            raise ValueError("Luma Modify source has a truncated MP4 atom.")
        size, kind = struct.unpack_from(">I4s", data, cursor)
        header_size = 8
        if size == 1:
            if end - cursor < 16:
                raise ValueError("Luma Modify source has a truncated extended MP4 atom.")
            size = struct.unpack_from(">Q", data, cursor + 8)[0]
            header_size = 16
        elif size == 0:
            size = end - cursor
        if size < header_size or size > end - cursor:
            raise ValueError("Luma Modify source has invalid MP4 atom bounds.")
        yield kind, cursor + header_size, cursor + size
        cursor += size


def _mp4_duration_seconds(data: bytes) -> float:
    duration_seconds = None
    has_file_type = False
    for kind, start, end in _atoms(data, 0, len(data)):
        if kind == b"ftyp":
            has_file_type = end - start >= 8
        if kind != b"moov":
            continue
        for child, child_start, child_end in _atoms(data, start, end):
            if child != b"mvhd":
                continue
            if child_end - child_start < 4:
                raise ValueError("Luma Modify source has a truncated MP4 movie header.")
            version = data[child_start]
            if version == 0 and child_end - child_start >= 20:
                timescale, duration = struct.unpack_from(">II", data, child_start + 12)
                unknown_duration = 0xFFFFFFFF
            elif version == 1 and child_end - child_start >= 32:
                timescale, duration = struct.unpack_from(">IQ", data, child_start + 20)
                unknown_duration = 0xFFFFFFFFFFFFFFFF
            else:
                raise ValueError(
                    "Luma Modify source has an unsupported or truncated MP4 movie header."
                )
            if not timescale or not duration or duration == unknown_duration:
                raise ValueError("Luma Modify source duration cannot be determined.")
            if duration_seconds is not None:
                raise ValueError("Luma Modify source has multiple MP4 movie headers.")
            duration_seconds = duration / timescale
    if not has_file_type or duration_seconds is None:
        raise ValueError("Luma Modify supports MP4 sources with a known movie duration.")
    return duration_seconds


def _check_duration(data: bytes, quoted_duration: int) -> None:
    measured = _mp4_duration_seconds(data)
    if measured > 18:
        raise ValueError("Luma Modify sources cannot exceed 18 seconds.")
    if not math.isclose(
        measured, quoted_duration, rel_tol=0, abs_tol=FRAME_TOLERANCE_SECONDS + 1e-6
    ):
        raise ValueError(
            f"Luma Modify source is {measured:g}s, but the quoted duration is {quoted_duration}s. "
            "Published Modify prices support only 5s or 10s sources."
        )


def _video_source(arguments: dict[str, Any]) -> dict[str, str]:
    generation = arguments.get("source_generation_id")
    if generation is not None:
        payload = _request("GET", f"/generations/{generation}")
        task = _normalized(payload, {}, expected_id=generation)
        if task.status != "succeeded":
            raise ValueError(
                "Luma Modify requires a completed source generation with video output."
            )
        url = task.video_url
    else:
        value = arguments["video_path_or_url"]
        if not value.startswith(("http://", "https://")):
            path = Path(value).expanduser()
            if path.suffix.lower() != ".mp4":
                raise ValueError("Luma Modify currently supports MP4 sources only.")
            data = _read_media(path, MAX_VIDEO_BYTES)
            _check_duration(data, arguments["source_duration_seconds"])
            return {"data": base64.b64encode(data).decode("ascii"), "media_type": "video/mp4"}
        url = value
    with tempfile.TemporaryDirectory(prefix="luma-source-") as temporary:
        path = Path(temporary) / "source.mp4"
        _download(url, path, MAX_VIDEO_BYTES)
        _check_duration(_read_media(path, MAX_VIDEO_BYTES), arguments["source_duration_seconds"])
    if generation is not None:
        return {"generation_id": generation}
    return {"url": url, "media_type": "video/mp4"}


def _submit(mode: str, arguments: dict[str, Any]) -> dict[str, Any]:
    validate_generation_arguments(mode, arguments)
    metadata = {name: arguments[name] for name in _METADATA_FIELDS if name in arguments}
    metadata.update(
        {"mode": mode, "model": MODEL, "training_eligible": False, "created_at": int(time.time())}
    )
    if mode == "extend_video":
        metadata["duration_seconds"] = 5
    if _dry_run():
        return asdict(
            LumaTask(
                job_id=str(uuid.uuid4()),
                status="dry_run",
                mode=mode,
                **{name: metadata.get(name) for name in _METADATA_FIELDS},
                note="Dry run only. Set LUMA_DRY_RUN=false to submit a live Luma generation.",
            )
        )
    body: dict[str, Any] = {"model": MODEL, "type": "video", "prompt": arguments["prompt"]}
    video: dict[str, Any] = {"resolution": arguments["resolution"]}
    if mode in {"text_to_video", "image_to_video"}:
        body["aspect_ratio"] = arguments["aspect_ratio"]
        video["duration"] = f"{arguments['duration_seconds']}s"
    if mode == "image_to_video":
        for source, target in (
            ("image_path_or_url", "start_frame"),
            ("last_frame_path_or_url", "end_frame"),
        ):
            if arguments[source] is not None:
                video[target] = _image_reference(arguments[source])
    if mode == "extend_video":
        frame = "start_frame" if arguments["direction"] == "forward" else "end_frame"
        video[frame] = {"generation_id": arguments["generation_id"]}
    if mode == "modify_video":
        body["type"] = "video_edit"
        body["source"] = _video_source(arguments)
        video["edit"] = (
            {"strength": arguments["strength"]}
            if arguments["strength"] is not None
            else {"auto_controls": True}
        )
    body["video"] = video
    payload = _request("POST", "/generations", body)
    task = _normalized(payload, metadata)
    _write_metadata(task.job_id, {**metadata, "job_id": task.job_id, "status": task.status})
    return asdict(task)


def text_to_video(
    prompt: str,
    duration_seconds: int = 5,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    model: str = MODEL,
) -> dict:
    """Submit a Ray 3.2 text-to-video job, then poll get_video_task."""
    return _submit("text_to_video", locals())


def image_to_video(
    prompt: str,
    image_path_or_url: str | None = None,
    last_frame_path_or_url: str | None = None,
    duration_seconds: int = 5,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    model: str = MODEL,
) -> dict:
    """Submit a Ray 3.2 video with a start image, an end image, or both."""
    return _submit("image_to_video", locals())


def extend_video(
    prompt: str,
    generation_id: str,
    direction: Literal["forward", "backward"] = "forward",
    resolution: str = "720p",
    model: str = MODEL,
) -> dict:
    """Continue or prepend a completed Luma generation using one generation keyframe."""
    return _submit("extend_video", locals())


def modify_video(
    prompt: str,
    source_duration_seconds: int,
    video_path_or_url: str | None = None,
    source_generation_id: str | None = None,
    resolution: str = "720p",
    strength: str | None = None,
    model: str = MODEL,
) -> dict:
    """Edit a verified 5s or 10s MP4 or completed Luma video, then poll get_video_task."""
    return _submit("modify_video", locals())


def get_video_task(job_id: str, download: bool = True) -> dict:
    """Poll a Luma video once and optionally save its completed MP4 locally."""
    _generation_id(job_id)
    if not isinstance(download, bool):
        raise ValueError("Luma download must be a boolean.")
    if _dry_run():
        return asdict(
            LumaTask(
                job_id=job_id,
                status="dry_run",
                note="Dry run is enabled. No live Luma job was queried.",
            )
        )
    metadata = _read_metadata(job_id)
    payload = _request("GET", f"/generations/{job_id}")
    task = _normalized(payload, metadata, expected_id=job_id)
    result = asdict(task)
    output_path = _video_dir() / f"{job_id}.mp4"
    if task.status == "succeeded" and download:
        if not output_path.is_file() or output_path.stat().st_size == 0:
            _download(task.video_url, output_path, MAX_VIDEO_BYTES)
        result.update({"output_path": str(output_path), "downloaded": True})
    _write_metadata(
        job_id,
        {
            **metadata,
            "job_id": job_id,
            "model": MODEL,
            "status": task.status,
            "failure_code": task.failure_code,
            "failure_reason": task.failure_reason,
            "training_eligible": False,
            "updated_at": int(time.time()),
        },
    )
    return result


def list_luma_models() -> dict:
    """Return the documented Ray 3.2 catalog without contacting Luma."""
    return {
        "status": "ok",
        "provider": "luma",
        "training_eligible": False,
        "selected_model": MODEL,
        "docs_verified_date": DOCS_VERIFIED_DATE,
        "models": [
            {
                "id": MODEL,
                "name": "Ray 3.2",
                "resolutions": list(RESOLUTIONS),
                "duration_seconds": list(DURATIONS),
                "draft_resolution": "360p",
            }
        ],
        "note": "Ray 3.2 supports the cheaper 360p draft tier. The current API has no separate Flash model identifier.",
    }


TOOL_HANDLERS = {
    "text_to_video": text_to_video,
    "image_to_video": image_to_video,
    "extend_video": extend_video,
    "modify_video": modify_video,
    "get_video_task": get_video_task,
    "list_luma_models": list_luma_models,
}
GATEWAY_TOOLS = tuple(TOOL_HANDLERS)
