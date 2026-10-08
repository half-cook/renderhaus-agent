"""Runway tools for queued video and image jobs, with one task poll per call.

Sources checked 2026-10-08:
https://docs.dev.runwayml.com/api/
https://docs.dev.runwayml.com/assets/inputs/
https://docs.dev.runwayml.com/assets/outputs/
https://docs.dev.runwayml.com/assets/uploads/

RUNWAY_DRY_RUN defaults to true. Set it to false and provide RUNWAYML_API_SECRET
to submit live jobs. Submissions are never automatically retried because a failed
connection can leave a paid task running. Output requests use a separate client
without Runway authentication. Runway output URLs expire, so download completed
assets to retain them. Local task metadata is optional, not required for polling.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from providers.runway.contracts import (
    CATALOG_SOURCE,
    CATALOG_VERIFIED_ON,
    MODEL_CONSTRAINTS,
    validate_https_url,
    validate_job_id,
    validate_runway_arguments,
)


API_BASE = "https://api.dev.runwayml.com/v1"
API_VERSION = "2024-11-06"
POLL_INTERVAL_SECONDS = 5
STATE_MAP = {
    "PENDING": "queued",
    "THROTTLED": "queued",
    "RUNNING": "running",
    "SUCCEEDED": "succeeded",
    "FAILED": "failed",
    "CANCELLED": "cancelled",
}
_ENDPOINTS = {
    "text_to_video": "/text_to_video",
    "image_to_video": "/image_to_video",
    "video_to_video": "/video_to_video",
    "text_to_image": "/text_to_image",
    "image_to_image": "/text_to_image",
}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
_MIME_EXTENSIONS = {
    "image/jpg": ".jpg",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/x-matroska": ".mkv",
}


def dry_run() -> bool:
    return os.getenv("RUNWAY_DRY_RUN", "true").lower() != "false"


def _headers() -> dict[str, str]:
    key = os.getenv("RUNWAYML_API_SECRET")
    if not key:
        raise RuntimeError("RUNWAYML_API_SECRET is required for live Runway calls.")
    return {
        "Authorization": f"Bearer {key}",
        "X-Runway-Version": API_VERSION,
        "Content-Type": "application/json",
    }


def _media_dir() -> Path:
    return Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser()


def _task_meta_path(job_id: str) -> Path:
    validate_job_id(job_id)
    return _media_dir() / "runway" / ".tasks" / f"{job_id}.json"


def _write_task_meta(job_id: str, metadata: dict[str, Any]) -> None:
    path = _task_meta_path(job_id)
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, suffix=".tmp", delete=False
        ) as file:
            temporary = Path(file.name)
            json.dump(metadata, file, indent=2, sort_keys=True)
        os.replace(temporary, path)
    except OSError:
        # Metadata is optional. A paid submission must still return its task ID.
        return
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _read_task_meta(job_id: str) -> dict[str, Any]:
    path = _task_meta_path(job_id)
    try:
        metadata = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _safe_code(value: Any) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_.]{0,99}", value):
        return value
    return None


def _provider_error(response: httpx.Response) -> RuntimeError:
    # Upstream bodies can echo prompts, signed input URLs, or credential-like text.
    # Report only structured identifiers rather than reflecting arbitrary messages.
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    code = _safe_code(payload.get("reason")) if isinstance(payload, dict) else None
    request_id = response.headers.get("x-request-id")
    details = []
    if code:
        details.append(f"code={code}")
    if request_id and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", request_id):
        details.append(f"request_id={request_id}")
    suffix = f" ({', '.join(details)})" if details else ""
    return RuntimeError(f"Runway API error HTTP {response.status_code}{suffix}.")


def _request(method: str, endpoint: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    headers = _headers()
    try:
        with httpx.Client(timeout=60, follow_redirects=False) as client:
            response = client.request(method, f"{API_BASE}{endpoint}", headers=headers, json=body)
    except httpx.RequestError:
        note = (
            " Check the task status before resubmitting a paid request." if method == "POST" else ""
        )
        raise RuntimeError(f"Runway API connection failed.{note}") from None
    if not response.is_success:
        raise _provider_error(response)
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError("Runway API returned invalid JSON.") from None
    if not isinstance(payload, dict):
        raise RuntimeError("Runway API returned a JSON response that is not an object.")
    return payload


def _create_task(mode: str, body: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    metadata = {
        "provider": "runway",
        "mode": mode,
        "model": body["model"],
        "media_kind": MODEL_CONSTRAINTS[body["model"]]["media_kind"],
        "created_at": int(time.time()),
        **metadata,
    }
    if dry_run():
        job_id = f"runway_dry_{uuid.uuid4().hex}"
        status = "dry_run"
        note = "Dry run only. Set RUNWAY_DRY_RUN=false to submit a live Runway job."
        payload = {}
    else:
        payload = _request("POST", _ENDPOINTS[mode], body)
        job_id = payload.get("id")
        try:
            validate_job_id(job_id)
        except ValueError:
            raise RuntimeError(
                "Runway did not return a valid task ID. Check your account before resubmitting."
            ) from None
        if job_id.startswith("runway_dry_"):
            raise RuntimeError("Runway did not return a live task UUID.")
        status = "queued"
        note = "Runway task created. Call get_runway_task once every five seconds until terminal."
    metadata.update({"job_id": job_id, "status": status})
    _write_task_meta(job_id, metadata)
    result = {**metadata, "note": note}
    if "estimatedCost" in payload:
        result["estimated_cost"] = payload["estimatedCost"]
    if status == "queued":
        result["poll_interval_seconds"] = POLL_INTERVAL_SECONDS
    return result


def _seed(body: dict[str, Any], seed: int | None) -> dict[str, Any]:
    if seed is not None:
        body["seed"] = seed
    return body


def text_to_video(
    prompt: str,
    duration_seconds: int = 5,
    ratio: str = "1280:720",
    model: str = "gen4.5",
    seed: int | None = None,
) -> dict[str, Any]:
    """Create a queued Gen-4.5 video from text, then poll get_runway_task."""
    arguments = dict(
        prompt=prompt, duration_seconds=duration_seconds, ratio=ratio, model=model, seed=seed
    )
    validate_runway_arguments("text_to_video", arguments)
    body = _seed(
        {"model": model, "promptText": prompt, "duration": duration_seconds, "ratio": ratio}, seed
    )
    return _create_task(
        "text_to_video", body, {"duration_seconds": duration_seconds, "ratio": ratio}
    )


def image_to_video(
    image_path_or_url: str,
    prompt: str,
    duration_seconds: int = 5,
    ratio: str = "1280:720",
    model: str = "gen4.5",
    seed: int | None = None,
) -> dict[str, Any]:
    """Animate an image URI with Gen-4.5, then poll get_runway_task."""
    arguments = dict(
        image_path_or_url=image_path_or_url,
        prompt=prompt,
        duration_seconds=duration_seconds,
        ratio=ratio,
        model=model,
        seed=seed,
    )
    validate_runway_arguments("image_to_video", arguments)
    body = _seed(
        {
            "model": model,
            "promptText": prompt,
            "promptImage": image_path_or_url,
            "duration": duration_seconds,
            "ratio": ratio,
        },
        seed,
    )
    return _create_task(
        "image_to_video", body, {"duration_seconds": duration_seconds, "ratio": ratio}
    )


def video_to_video(
    video_path_or_url: str,
    prompt: str,
    video_duration_seconds: float,
    reference_image_path_or_url: str | None = None,
    reference_seconds: float = 0,
    model: str = "aleph2",
    seed: int | None = None,
) -> dict[str, Any]:
    """Edit a 2-30 second, at most 30 fps, up-to-1080p video with Aleph 2, then poll get_runway_task.

    The caller must supply the true input duration for the cost estimate and a
    compatible clip. This tool checks URI syntax, not remote media properties.
    The optional image URI becomes a guidance keyframe at reference_seconds.
    """
    arguments = dict(
        video_path_or_url=video_path_or_url,
        prompt=prompt,
        video_duration_seconds=video_duration_seconds,
        reference_image_path_or_url=reference_image_path_or_url,
        reference_seconds=reference_seconds,
        model=model,
        seed=seed,
    )
    validate_runway_arguments("video_to_video", arguments)
    body = _seed({"model": model, "promptText": prompt, "videoUri": video_path_or_url}, seed)
    if reference_image_path_or_url is not None:
        body["keyframes"] = [{"uri": reference_image_path_or_url, "seconds": reference_seconds}]
    return _create_task("video_to_video", body, {"video_duration_seconds": video_duration_seconds})


def text_to_image(
    prompt: str,
    ratio: str = "1280:720",
    model: str = "gen4_image",
    seed: int | None = None,
) -> dict[str, Any]:
    """Create a queued Gen-4 Image from text, then poll get_runway_task."""
    arguments = dict(prompt=prompt, ratio=ratio, model=model, seed=seed)
    validate_runway_arguments("text_to_image", arguments)
    body = _seed({"model": model, "promptText": prompt, "ratio": ratio}, seed)
    return _create_task("text_to_image", body, {"ratio": ratio})


def image_to_image(
    image_path_or_url: str,
    prompt: str,
    ratio: str = "1280:720",
    model: str = "gen4_image",
    reference_images: list[dict[str, Any]] | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Edit an image URI with Gen-4 Image or Image Turbo, then poll get_runway_task.

    reference_images can add up to two images, each with uri and an optional
    3-16 character lowercase tag. The primary image makes one to three total.
    """
    arguments = dict(
        image_path_or_url=image_path_or_url,
        prompt=prompt,
        ratio=ratio,
        model=model,
        reference_images=reference_images,
        seed=seed,
    )
    validate_runway_arguments("image_to_image", arguments)
    references = [{"uri": image_path_or_url}, *(reference_images or [])]
    body = _seed(
        {"model": model, "promptText": prompt, "ratio": ratio, "referenceImages": references}, seed
    )
    return _create_task("image_to_image", body, {"ratio": ratio})


def _kind_from_extension(extension: str) -> str | None:
    if extension in _IMAGE_EXTENSIONS:
        return "image"
    if extension in _VIDEO_EXTENSIONS:
        return "video"
    return None


def _validate_output_request(request: httpx.Request) -> None:
    # Validate redirects too. Never attach the authenticated API client's headers.
    validate_https_url(str(request.url), "Runway output URL", max_length=16384)


def _output_client() -> httpx.Client:
    return httpx.Client(
        timeout=120,
        follow_redirects=True,
        event_hooks={"request": [_validate_output_request]},
    )


def _output_type(url: str) -> tuple[str, str]:
    try:
        with _output_client() as client:
            response = client.head(url)
    except (httpx.RequestError, ValueError):
        raise RuntimeError("Runway output media type could not be checked.") from None
    if not response.is_success:
        raise RuntimeError(f"Runway output type check returned HTTP {response.status_code}.")
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    extension = _MIME_EXTENSIONS.get(content_type)
    kind = _kind_from_extension(extension or "")
    if not kind or not extension:
        raise RuntimeError("Runway output has an unsupported or missing media content type.")
    return kind, extension


def _download_output(url: str, output_path: Path, expected_kind: str) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with _output_client() as client:
            with client.stream("GET", url) as response:
                if not response.is_success:
                    raise RuntimeError(
                        f"Runway output download returned HTTP {response.status_code}."
                    )
                content_type = (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                )
                content_kind = _kind_from_extension(_MIME_EXTENSIONS.get(content_type, ""))
                if (
                    content_type
                    and content_type != "application/octet-stream"
                    and content_kind != expected_kind
                ):
                    raise RuntimeError(
                        "Runway output download did not return the expected media type."
                    )
                with tempfile.NamedTemporaryFile(
                    dir=output_path.parent, suffix=".tmp", delete=False
                ) as file:
                    temporary = Path(file.name)
                    size = 0
                    for chunk in response.iter_bytes():
                        file.write(chunk)
                        size += len(chunk)
                    if size == 0:
                        raise RuntimeError("Runway output download returned an empty asset.")
                os.replace(temporary, output_path)
    except (httpx.RequestError, ValueError):
        raise RuntimeError("Runway output download failed.") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _assets(job_id: str, output: Any, download: bool) -> list[dict[str, Any]]:
    if (
        not isinstance(output, list)
        or not output
        or any(not isinstance(url, str) for url in output)
    ):
        raise RuntimeError("Runway reported success without valid output URLs.")
    assets = []
    for index, url in enumerate(output):
        try:
            validate_https_url(url, "Runway output URL", max_length=16384)
        except ValueError:
            raise RuntimeError("Runway returned an invalid output URL.") from None
        extension = Path(urlsplit(url).path).suffix.lower()
        kind = _kind_from_extension(extension)
        if kind is None:
            kind, extension = _output_type(url)
        asset: dict[str, Any] = {"kind": kind, "url": url, f"{kind}_url": url}
        if download:
            suffix = "" if index == 0 else f"_{index + 1}"
            output_path = _media_dir() / kind / f"{job_id}{suffix}{extension}"
            if (
                output_path.is_symlink()
                or not output_path.is_file()
                or output_path.stat().st_size == 0
            ):
                _download_output(url, output_path, kind)
            asset["output_path"] = str(output_path)
        assets.append(asset)
    return assets


def get_runway_task(job_id: str, download: bool = False) -> dict[str, Any]:
    """Poll one Runway task once, optionally download its completed image or video outputs."""
    validate_runway_arguments("get_runway_task", {"job_id": job_id, "download": download})
    metadata = _read_task_meta(job_id)
    model = metadata.get("model")
    model = model if isinstance(model, str) and model in MODEL_CONSTRAINTS else None
    mode = metadata.get("mode")
    mode = mode if isinstance(mode, str) and mode in _ENDPOINTS else None
    media_kind = metadata.get("media_kind")
    media_kind = (
        media_kind if isinstance(media_kind, str) and media_kind in {"image", "video"} else None
    )
    result: dict[str, Any] = {
        "provider": "runway",
        "job_id": job_id,
        "mode": mode,
        "model": model,
        "media_kind": media_kind,
    }
    if job_id.startswith("runway_dry_") or metadata.get("status") == "dry_run" or dry_run():
        return {
            **result,
            "status": "dry_run",
            "note": "Dry-run task or dry-run polling; no live Runway task was queried.",
        }
    payload = _request("GET", f"/tasks/{job_id}")
    if payload.get("id") != job_id:
        raise RuntimeError("Runway returned a different task ID.")
    provider_status = payload.get("status")
    if not isinstance(provider_status, str) or provider_status not in STATE_MAP:
        raise RuntimeError("Runway returned an unsupported task status.")
    status = STATE_MAP[provider_status]
    result.update({"status": status, "provider_status": provider_status})
    if status in {"queued", "running"}:
        result["poll_interval_seconds"] = POLL_INTERVAL_SECONDS
    for source, target in (
        ("progress", "progress"),
        ("estimatedCost", "estimated_cost"),
        ("cost", "cost"),
    ):
        if source in payload:
            result[target] = payload[source]
    if status == "failed":
        result["error"] = (
            "Runway generation failed. Inspect the failure code or the Runway developer account."
        )
        result["failure_code"] = _safe_code(payload.get("failureCode"))
    if status == "succeeded":
        assets = _assets(job_id, payload.get("output"), download)
        result["assets"] = assets
        kinds = {asset["kind"] for asset in assets}
        result["media_kind"] = next(iter(kinds)) if len(kinds) == 1 else "mixed"
        for kind in ("video", "image"):
            first = next((asset for asset in assets if asset["kind"] == kind), None)
            if first:
                result[f"{kind}_url"] = first["url"]
        if download:
            result["downloaded"] = True
            result["output_path"] = assets[0]["output_path"]
    metadata.update(
        {
            key: result[key]
            for key in ("provider", "job_id", "mode", "model", "media_kind", "status")
        }
    )
    metadata["updated_at"] = int(time.time())
    _write_task_meta(job_id, metadata)
    return result


def list_runway_models() -> dict[str, Any]:
    """List this provider's documented model catalog; account availability is not queried."""
    return {
        "provider": "runway",
        "status": "ok",
        "catalog_kind": "documented",
        "source": CATALOG_SOURCE,
        "verified_on": CATALOG_VERIFIED_ON,
        "account_availability_verified": False,
        "models": [{"id": model, **deepcopy(rules)} for model, rules in MODEL_CONSTRAINTS.items()],
        "note": "Local documented catalog. Runway has no documented /models endpoint; this does not verify live account availability.",
    }


TOOL_HANDLERS = {
    "text_to_video": text_to_video,
    "image_to_video": image_to_video,
    "video_to_video": video_to_video,
    "text_to_image": text_to_image,
    "image_to_image": image_to_image,
    "get_runway_task": get_runway_task,
    "list_runway_models": list_runway_models,
}
GATEWAY_TOOLS = tuple(TOOL_HANDLERS)
