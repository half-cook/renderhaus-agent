"""S3 helpers shared by the AgentCore runtime for returning durable media."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import uuid
from pathlib import Path
from typing import Any, Literal

import boto3


AssetKind = Literal["video", "image", "music", "upload"]


def aws_region() -> str:
    return os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"


def s3_bucket() -> str:
    return (os.getenv("AWS_S3_BUCKET") or "").strip()


def _s3():
    return boto3.client("s3", region_name=aws_region())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def upload_local_media(
    *,
    user_id: str,
    source_path: str | Path,
    kind: AssetKind,
    mime_type: str | None = None,
) -> dict[str, Any]:
    """Upload a local file and return durable storage metadata (no DynamoDB write)."""
    source = Path(source_path).expanduser().resolve()
    if not source.is_file() or source.stat().st_size <= 0:
        raise FileNotFoundError(f"Output file missing: {source}")
    bucket = s3_bucket()
    if not bucket:
        raise RuntimeError("AWS_S3_BUCKET is required to publish AgentCore media.")

    asset_id = uuid.uuid4().hex
    suffix = source.suffix or {
        "video": ".mp4",
        "image": ".png",
        "music": ".mp3",
        "upload": "",
    }.get(kind, "")
    filename = source.name or f"{asset_id}{suffix}"
    storage_key = f"users/{user_id}/assets/{asset_id}/{filename}"
    guessed = mime_type or mimetypes.guess_type(filename)[0]
    if not guessed:
        if kind == "image":
            guessed = "image/png"
        elif kind == "music":
            guessed = "audio/mpeg"
        else:
            guessed = "video/mp4"

    _s3().upload_file(
        Filename=str(source),
        Bucket=bucket,
        Key=storage_key,
        ExtraArgs={"ContentType": guessed},
    )
    return {
        "asset_id": asset_id,
        "storage_key": storage_key,
        "filename": filename,
        "mime_type": guessed,
        "size_bytes": source.stat().st_size,
        "checksum": _sha256_file(source),
        "kind": kind,
    }


def download_storage_key(storage_key: str, destination: Path) -> Path:
    bucket = s3_bucket()
    if not bucket:
        raise RuntimeError("AWS_S3_BUCKET is required to materialize reference media.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    _s3().download_file(Bucket=bucket, Key=storage_key, Filename=str(temporary))
    temporary.replace(destination)
    return destination
