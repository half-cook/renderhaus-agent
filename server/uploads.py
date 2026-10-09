from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, UploadFile

from server.config import ROOT


UploadKind = Literal["image", "video", "audio"]
UPLOAD_CHUNK_BYTES = 1024 * 1024
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
