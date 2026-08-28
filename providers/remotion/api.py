"""Remotion Lambda provider API.

Gateway tools start a render and poll once. Blocking wait stays off Lambda.
"""

from __future__ import annotations

import copy
import hashlib
import json
import mimetypes
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlparse

import boto3
from botocore.exceptions import ClientError
from remotion_lambda import Privacy, RemotionClient, RenderMediaParams, ValidStillImageFormats
from remotion_lambda.exception import RemotionException


ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT_PATH = ROOT / ".renderhaus" / "remotion" / "deployment.json"
OUTPUT_DIR = ROOT / ".renderhaus" / "media" / "remotion"
COMPOSITION_ID = "RenderhausTimeline"
ASPECT_SIZES = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}


@dataclass(frozen=True, slots=True)
class RemotionSettings:
    region: str
    function_name: str
    serve_url: str
    bucket_name: str


def dry_run() -> bool:
    return os.getenv("REMOTION_DRY_RUN", "true").lower() != "false"


def _on_lambda() -> bool:
    return bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))


def load_remotion_settings() -> RemotionSettings:
    stored: dict[str, Any] = {}
    if DEPLOYMENT_PATH.is_file():
        value = json.loads(DEPLOYMENT_PATH.read_text())
        if isinstance(value, dict):
            stored = value

    def get(env_name: str, stored_name: str) -> str:
        return str(os.getenv(env_name) or stored.get(stored_name) or "").strip()

    settings = RemotionSettings(
        region=get("REMOTION_APP_REGION", "region"),
        function_name=get("REMOTION_APP_FUNCTION_NAME", "functionName"),
        serve_url=get("REMOTION_APP_SERVE_URL", "serveUrl"),
        bucket_name=get("REMOTION_APP_BUCKET_NAME", "bucketName"),
    )
    missing = [
        name
        for name, value in (
            ("REMOTION_APP_REGION", settings.region),
            ("REMOTION_APP_FUNCTION_NAME", settings.function_name),
            ("REMOTION_APP_SERVE_URL", settings.serve_url),
            ("REMOTION_APP_BUCKET_NAME", settings.bucket_name),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Remotion Lambda is not configured ({', '.join(missing)}).")
    return settings


def _safe_output_name(value: str) -> str:
    stem = Path(value).name.removesuffix(".mp4")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._") or "renderhaus-video"
    return f"{stem[:90]}.mp4"


def _allowed_local_roots() -> tuple[Path, ...]:
    media = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser()
    if not media.is_absolute():
        media = (ROOT / media).resolve()
    else:
        media = media.resolve()
    return (ROOT / ".renderhaus", media)


def _is_allowed_local(path: Path) -> bool:
    resolved = path.resolve()
    return any(root == resolved or root in resolved.parents for root in _allowed_local_roots())


def _uploaded_source_url(source: str, *, settings: RemotionSettings, s3) -> str:
    if source.startswith(("https://", "http://", "data:")):
        return source
    path = Path(source).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not _is_allowed_local(path) or not path.is_file() or path.stat().st_size <= 0:
        raise ValueError("Remotion sources must be existing media inside the Renderhaus workspace.")
    digest_builder = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest_builder.update(chunk)
    digest = digest_builder.hexdigest()[:20]
    key = f"renderhaus-inputs/{digest}-{path.name}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        s3.head_object(Bucket=settings.bucket_name, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
            raise
        s3.upload_file(
            str(path),
            settings.bucket_name,
            key,
            ExtraArgs={"ContentType": content_type},
        )
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.bucket_name, "Key": key},
        ExpiresIn=6 * 60 * 60,
    )


def _prepare_input_props(
    input_props: dict[str, Any], *, settings: RemotionSettings, session: boto3.Session
) -> dict[str, Any]:
    prepared = copy.deepcopy(input_props)
    s3 = session.client("s3")
    document = prepared.get("document")
    if not isinstance(document, dict) or not isinstance(document.get("assets"), list):
        raise ValueError("Remotion input props must include a timeline document with assets.")
    for asset in document["assets"]:
        if not isinstance(asset, dict) or not isinstance(asset.get("url"), str):
            raise ValueError("Every Remotion timeline asset must have a source URL or local path.")
        asset["url"] = _uploaded_source_url(asset["url"], settings=settings, s3=s3)
    return prepared


def build_timeline_props(
    title: str,
    visuals: list[dict[str, Any]],
    audio_tracks: list[dict[str, Any]] | None = None,
    aspect_ratio: str = "9:16",
    fps: int = 30,
) -> dict[str, Any]:
    if aspect_ratio not in ASPECT_SIZES:
        raise ValueError(f"aspect_ratio must be one of {', '.join(ASPECT_SIZES)}.")
    if not visuals:
        raise ValueError("At least one visual clip is required for a Remotion render.")
    width, height = ASPECT_SIZES[aspect_ratio]
    assets: list[dict[str, Any]] = []
    visual_items: list[dict[str, Any]] = []
    for index, clip in enumerate(visuals):
        kind = str(clip.get("kind") or "image")
        if kind not in {"image", "video"}:
            raise ValueError("Each visual clip kind must be image or video.")
        url = str(clip.get("url") or "").strip()
        if not url:
            raise ValueError("Each visual clip needs a url (canvas node source or https URL).")
        duration = float(clip.get("duration_seconds") or 0)
        if duration <= 0:
            raise ValueError("Each visual clip needs duration_seconds greater than 0.")
        start = float(clip.get("start_seconds") or 0)
        source_in = float(clip.get("source_in_seconds") or 0)
        asset_id = f"visual-{index + 1}"
        assets.append(
            {
                "id": asset_id,
                "name": f"{kind.title()} {index + 1}",
                "kind": kind,
                "url": url,
                "durationSec": duration,
            }
        )
        visual_items.append(
            {
                "id": f"visual-clip-{index + 1}",
                "type": "clip",
                "assetId": asset_id,
                "start": start,
                "duration": duration,
                "sourceIn": source_in,
                "sourceOut": source_in + duration,
            }
        )
    tracks: list[dict[str, Any]] = [
        {"id": "video-1", "kind": "video", "name": "Video", "items": visual_items}
    ]
    for index, clip in enumerate(audio_tracks or []):
        url = str(clip.get("url") or "").strip()
        if not url:
            raise ValueError("Each audio clip needs a url (canvas node source or https URL).")
        duration = float(clip.get("duration_seconds") or 0)
        if duration <= 0:
            raise ValueError("Each audio clip needs duration_seconds greater than 0.")
        start = float(clip.get("start_seconds") or 0)
        source_in = float(clip.get("source_in_seconds") or 0)
        volume = float(clip.get("volume") if clip.get("volume") is not None else 1)
        asset_id = f"audio-{index + 1}"
        assets.append(
            {
                "id": asset_id,
                "name": f"Audio {index + 1}",
                "kind": "audio",
                "url": url,
                "durationSec": duration,
            }
        )
        tracks.append(
            {
                "id": f"audio-track-{index + 1}",
                "kind": "audio",
                "name": f"Audio {index + 1}",
                "items": [
                    {
                        "id": f"audio-clip-{index + 1}",
                        "type": "clip",
                        "assetId": asset_id,
                        "start": start,
                        "duration": duration,
                        "sourceIn": source_in,
                        "sourceOut": source_in + duration,
                        "volume": volume,
                    }
                ],
            }
        )
    return {
        "document": {
            "id": "agent-render",
            "name": (title or "Renderhaus video")[:160],
            "assets": assets,
            "tracks": tracks,
        },
        "renderConfig": {
            "fps": max(12, min(int(fps), 60)),
            "width": width,
            "height": height,
        },
    }


def _start_lambda_render(
    input_props: dict[str, Any],
    *,
    output_filename: str,
) -> dict[str, Any]:
    settings = load_remotion_settings()
    session = boto3.Session(region_name=settings.region)
    prepared = _prepare_input_props(input_props, settings=settings, session=session)
    client = RemotionClient(
        region=settings.region,
        serve_url=settings.serve_url,
        function_name=settings.function_name,
        session=session,
    )
    safe_name = _safe_output_name(output_filename)
    output_key = f"renderhaus-outputs/{uuid.uuid4().hex}/{safe_name}"
    response = client.render_media_on_lambda(
        RenderMediaParams(
            composition=COMPOSITION_ID,
            input_props=prepared,
            codec="h264",
            image_format=ValidStillImageFormats.JPEG,
            privacy=Privacy.PRIVATE,
            out_name=output_key,
            frames_per_lambda=max(
                20,
                int(os.getenv("REMOTION_FRAMES_PER_LAMBDA", "400")),
            ),
            max_retries=1,
            x264_preset="veryfast",
        )
    )
    if response is None:
        raise RuntimeError("Remotion Lambda did not return a render identifier.")
    return {
        "status": "queued",
        "render_id": response.render_id,
        "bucket_name": response.bucket_name,
        "output_key": output_key,
        "filename": safe_name,
        "progress": 0.0,
    }


def render_timeline(
    title: str,
    visuals: list[dict[str, Any]],
    audio_tracks: list[dict[str, Any]] | None = None,
    aspect_ratio: Literal["16:9", "9:16", "1:1"] = "9:16",
    fps: int = 30,
    output_filename: str = "renderhaus-video.mp4",
) -> dict[str, Any]:
    """Compose generated image, video, and audio clips into one final MP4, then poll get_render_progress."""
    if dry_run():
        return {
            "status": "dry_run",
            "render_id": "dry-run",
            "bucket_name": "",
            "output_key": "",
            "filename": _safe_output_name(output_filename),
            "progress": 0.0,
            "note": "Dry run is enabled; set REMOTION_DRY_RUN=false to start a Remotion Lambda render.",
        }
    props = build_timeline_props(
        title,
        visuals,
        audio_tracks=audio_tracks,
        aspect_ratio=str(aspect_ratio),
        fps=int(fps),
    )
    return _start_lambda_render(props, output_filename=output_filename)


def _progress_payload(
    *,
    render_id: str,
    bucket_name: str,
    output_key: str,
    progress: Any,
    completed_from_s3: bool,
    download: bool,
) -> dict[str, Any]:
    settings = load_remotion_settings()
    session = boto3.Session(region_name=settings.region)
    s3 = session.client("s3")
    done = completed_from_s3 or bool(progress and progress.done)
    failed = bool(progress and progress.fatalErrorEncountered)
    overall = float(getattr(progress, "overallProgress", 0) or 0) if progress else (1.0 if done else 0.0)
    if failed:
        messages = [str(item.get("message") or item) for item in (progress.errors[:3] if progress else [])]
        return {
            "status": "failed",
            "render_id": render_id,
            "bucket_name": bucket_name,
            "progress": overall,
            "error": "Remotion render failed: " + "; ".join(messages),
        }
    if not done:
        return {
            "status": "queued",
            "render_id": render_id,
            "bucket_name": bucket_name,
            "output_key": output_key,
            "progress": overall,
        }
    out_key = output_key if completed_from_s3 else str((progress.outKey if progress else "") or "")
    if not out_key and progress and progress.outputFile:
        out_key = unquote(urlparse(str(progress.outputFile)).path.lstrip("/"))
    if not out_key:
        raise RuntimeError("Remotion completed but did not return an output object key.")
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name, "Key": out_key},
        ExpiresIn=6 * 60 * 60,
    )
    result: dict[str, Any] = {
        "status": "succeeded",
        "render_id": render_id,
        "bucket_name": bucket_name,
        "output_key": out_key,
        "url": url,
        "filename": Path(out_key).name,
        "progress": 1.0,
    }
    should_download = download and not _on_lambda()
    if should_download:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        destination = OUTPUT_DIR / f"{render_id}-{Path(out_key).name}"
        s3.download_file(bucket_name, out_key, str(destination))
        if not destination.is_file() or destination.stat().st_size <= 0:
            raise RuntimeError("The rendered MP4 could not be downloaded from S3.")
        result["output_path"] = str(destination)
    return result


def get_render_progress(
    render_id: str,
    bucket_name: str,
    output_key: str | None = None,
    download: bool = True,
) -> dict[str, Any]:
    """Poll a Remotion render once. Repeat until status is succeeded, failed, or dry_run."""
    if dry_run():
        return {
            "status": "dry_run",
            "render_id": render_id,
            "bucket_name": bucket_name,
            "done": True,
            "progress": 1.0,
            "filename": "renderhaus-video.mp4",
            "note": "Dry run is enabled; set REMOTION_DRY_RUN=false to poll a live Remotion render.",
        }
    settings = load_remotion_settings()
    session = boto3.Session(region_name=settings.region)
    client = RemotionClient(
        region=settings.region,
        serve_url=settings.serve_url,
        function_name=settings.function_name,
        session=session,
    )
    s3 = session.client("s3")
    requested_key = str(output_key or "")
    progress = None
    completed_from_s3 = False
    try:
        progress = client.get_render_progress(render_id, bucket_name)
    except (ClientError, RemotionException):
        if requested_key:
            try:
                output = s3.head_object(Bucket=bucket_name, Key=requested_key)
            except ClientError as head_exc:
                if head_exc.response.get("Error", {}).get("Code") not in {
                    "404",
                    "NoSuchKey",
                    "NotFound",
                }:
                    raise
            else:
                if int(output.get("ContentLength") or 0) > 0:
                    completed_from_s3 = True
        if not completed_from_s3:
            raise
    return _progress_payload(
        render_id=render_id,
        bucket_name=bucket_name,
        output_key=requested_key,
        progress=progress,
        completed_from_s3=completed_from_s3,
        download=download,
    )


def render_timeline_and_wait(
    input_props: dict[str, Any],
    *,
    output_filename: str,
    timeout_seconds: float | None = None,
    poll_interval_seconds: float | None = None,
) -> dict[str, Any]:
    """Start a render and poll until it finishes. Local/smoke helper, not a Gateway tool."""
    if dry_run():
        return {
            "status": "dry_run",
            "render_id": "dry-run",
            "filename": _safe_output_name(output_filename),
            "progress": 1.0,
            "note": "Dry run is enabled; set REMOTION_DRY_RUN=false to render on Remotion Lambda.",
        }
    started = _start_lambda_render(input_props, output_filename=output_filename)
    timeout = timeout_seconds or float(os.getenv("REMOTION_RENDER_TIMEOUT_SECONDS", "1200"))
    interval = poll_interval_seconds or float(os.getenv("REMOTION_POLL_INTERVAL_SECONDS", "5"))
    deadline = time.monotonic() + max(1.0, timeout)
    last: dict[str, Any] = started
    while time.monotonic() < deadline:
        last = get_render_progress(
            started["render_id"],
            started["bucket_name"],
            output_key=started.get("output_key"),
            download=True,
        )
        if last.get("status") in {"succeeded", "failed", "dry_run"}:
            if last.get("status") == "failed":
                raise RuntimeError(str(last.get("error") or "Remotion render failed."))
            return last
        time.sleep(max(0.25, interval))
    raise TimeoutError(f"Remotion render {started['render_id']} did not finish in time.")


TOOL_HANDLERS = {
    "render_timeline": render_timeline,
    "get_render_progress": get_render_progress,
}

GATEWAY_TOOLS = (
    "render_timeline",
    "get_render_progress",
)
