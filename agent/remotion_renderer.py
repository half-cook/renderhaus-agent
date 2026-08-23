"""Remotion Lambda rendering for typed Renderhaus timeline documents."""

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
from typing import Any
from urllib.parse import unquote, urlparse

import boto3
from botocore.exceptions import ClientError
from remotion_lambda import Privacy, RemotionClient, RenderMediaParams, ValidStillImageFormats
from remotion_lambda.exception import RemotionException


ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENT_PATH = ROOT / ".renderhaus" / "remotion" / "deployment.json"
OUTPUT_DIR = ROOT / ".renderhaus" / "media" / "remotion"
ALLOWED_LOCAL_ROOT = ROOT / ".renderhaus"
COMPOSITION_ID = "RenderhausTimeline"


@dataclass(frozen=True, slots=True)
class RemotionSettings:
    region: str
    function_name: str
    serve_url: str
    bucket_name: str


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


def _uploaded_source_url(source: str, *, settings: RemotionSettings, s3) -> str:
    if source.startswith(("https://", "http://", "data:")):
        return source
    path = Path(source).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if ALLOWED_LOCAL_ROOT not in path.parents or not path.is_file() or path.stat().st_size <= 0:
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


def render_timeline_and_wait(
    input_props: dict[str, Any],
    *,
    output_filename: str,
    timeout_seconds: float | None = None,
    poll_interval_seconds: float | None = None,
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
    requested_out_key = f"renderhaus-outputs/{uuid.uuid4().hex}/{safe_name}"
    response = client.render_media_on_lambda(
        RenderMediaParams(
            composition=COMPOSITION_ID,
            input_props=prepared,
            codec="h264",
            image_format=ValidStillImageFormats.JPEG,
            privacy=Privacy.PRIVATE,
            out_name=requested_out_key,
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

    timeout = timeout_seconds or float(os.getenv("REMOTION_RENDER_TIMEOUT_SECONDS", "1200"))
    interval = poll_interval_seconds or float(os.getenv("REMOTION_POLL_INTERVAL_SECONDS", "5"))
    deadline = time.monotonic() + max(1.0, timeout)
    progress = None
    progress_errors = 0
    completed_from_s3 = False
    s3 = session.client("s3")
    while time.monotonic() < deadline:
        try:
            progress = client.get_render_progress(response.render_id, response.bucket_name)
            progress_errors = 0
        except (ClientError, RemotionException) as exc:
            try:
                output = s3.head_object(
                    Bucket=response.bucket_name,
                    Key=requested_out_key,
                )
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
                    break
            progress_errors += 1
            if progress_errors >= 12:
                raise RuntimeError(
                    "Remotion progress checks repeatedly failed while the render was running."
                ) from exc
            time.sleep(max(0.25, interval))
            continue
        if progress and progress.fatalErrorEncountered:
            messages = [str(item.get("message") or item) for item in progress.errors[:3]]
            raise RuntimeError("Remotion render failed: " + "; ".join(messages))
        if progress and progress.done:
            break
        time.sleep(max(0.25, interval))
    if not completed_from_s3 and (progress is None or not progress.done):
        raise TimeoutError(f"Remotion render {response.render_id} did not finish in time.")

    out_key = requested_out_key if completed_from_s3 else str(progress.outKey or "")
    if not out_key and progress and progress.outputFile:
        out_key = unquote(urlparse(str(progress.outputFile)).path.lstrip("/"))
    if not out_key:
        raise RuntimeError("Remotion completed but did not return an output object key.")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    destination = OUTPUT_DIR / f"{response.render_id}-{safe_name}"
    s3.download_file(response.bucket_name, out_key, str(destination))
    if not destination.is_file() or destination.stat().st_size <= 0:
        raise RuntimeError("The rendered MP4 could not be downloaded from S3.")
    return {
        "status": "succeeded",
        "render_id": response.render_id,
        "bucket_name": response.bucket_name,
        "output_path": str(destination),
        "filename": safe_name,
        "progress": 1.0,
    }
