from __future__ import annotations

import json
import math
import os
import re
import shutil
import tempfile
import warnings
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, UploadFile
from PIL import Image

from server.config import ROOT


UploadKind = Literal["image", "video", "audio"]
UPLOAD_CHUNK_BYTES = 1024 * 1024
_IMAGE_FORMATS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP", ".gif": "GIF"}
_MEDIA_FORMATS = {
    ".mp4": "mov", ".mov": "mov", ".m4v": "mov", ".webm": "matroska",
    ".mp3": "mp3", ".wav": "wav", ".m4a": "mov", ".aac": "aac", ".ogg": "ogg", ".flac": "flac",
}
_DEFAULT_LIMITS: dict[UploadKind, int] = json.loads(
    (ROOT / "configs" / "studio-upload-limits.json").read_text()
)["max_upload_mb_by_kind"]


def _limit_from_env(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    if not re.fullmatch(r"[0-9]+", value) or not 0 < int(value) <= 9007199254740991:
        raise ValueError(f"{name} must be a positive integer in MB.")
    return int(value)


def upload_limits_mb() -> dict[UploadKind, int]:
    return {
        kind: _limit_from_env(
            f"STUDIO_MAX_{kind.upper()}_UPLOAD_MB",
            _limit_from_env("STUDIO_MAX_UPLOAD_MB", default),
        )
        for kind, default in _DEFAULT_LIMITS.items()
    }


def validate_uploaded_media(path: Path, *, filename: str, kind: UploadKind) -> None:
    """Check untrusted upload bytes before creating an asset; provider ingestion stays separate."""
    suffix = Path(filename).suffix.lower()
    detail = f"This file is not a valid {kind}. Choose a supported {kind} file."
    try:
        if kind == "image":
            if suffix == ".svg":
                from providers.svg import MAX_SVG_BYTES, sanitize_svg

                if path.stat().st_size > MAX_SVG_BYTES:
                    raise ValueError("SVG exceeds its existing size limit.")
                sanitize_svg(path.read_bytes())
                return
            image_format = _IMAGE_FORMATS[suffix]
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path, formats=[image_format]) as image:
                    image.verify()
                with Image.open(path, formats=[image_format]) as image:
                    image.load()
            return
        if kind not in {"audio", "video"}:
            raise ValueError("Unsupported upload kind.")
        if not shutil.which("ffprobe"):
            raise HTTPException(status_code=503, detail="Media validation is unavailable. Please try again later.")
        from providers.ffmpeg.api import execute

        probe = execute("probe", path.parent, path.name)
        if not probe.get("ok"):
            raise ValueError("Media could not be read.")
        metrics = probe["metrics"]
        if _MEDIA_FORMATS[suffix] not in metrics["format"].get("format_name", "").split(","):
            raise ValueError("Media format does not match its filename.")
        stream = next(stream for stream in metrics["streams"] if stream.get("codec_type") == kind)
        duration = float(metrics["format"].get("duration") or stream.get("duration") or 0)
        if not math.isfinite(duration) or duration <= 0 or not stream.get("codec_name"):
            raise ValueError("Media has no measurable stream.")
        dimensions = ("width", "height") if kind == "video" else ("channels", "sample_rate")
        if any(int(stream.get(dimension) or 0) <= 0 for dimension in dimensions):
            raise ValueError("Media has no usable stream.")
    except HTTPException:
        raise
    except (OSError, ValueError, KeyError, TypeError, StopIteration, Warning, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=415, detail=detail) from exc


@asynccontextmanager
async def bounded_upload_path(file: UploadFile, *, limit_mb: int) -> AsyncIterator[Path]:
    limit_bytes = limit_mb * 1024 * 1024
    detail = f"File is larger than {limit_mb} MB."
    if file.size is not None and file.size > limit_bytes:
        raise HTTPException(status_code=413, detail=detail)
    with tempfile.TemporaryDirectory(prefix="renderhaus-upload-") as directory:
        path = Path(directory) / "upload"
        size = 0
        with path.open("wb") as destination:
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                size += len(chunk)
                if size > limit_bytes:
                    raise HTTPException(status_code=413, detail=detail)
                destination.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="The file was empty.")
        yield path
