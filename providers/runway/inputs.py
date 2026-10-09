"""Publish owned Runway inputs. Official input/upload docs read 2026-10-09.

https://docs.dev.runwayml.com/assets/inputs/
https://docs.dev.runwayml.com/assets/uploads/
HTTPS sources must support HEAD; GET-presigned S3 URLs cannot be used.
"""

from __future__ import annotations

import base64
import math
import mimetypes
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from providers.runway.contracts import MAX_DATA_URI_BYTES, validate_media_uri


MAX_UPLOAD_BYTES = 200 * 1024 * 1024


def publish_file(
    path: Path, filename: str | None = None, mime_type: str | None = None,
    *, request: Callable[..., dict[str, Any]] | None = None,
) -> str:
    from providers.runway.api import _request, dry_run

    request = request or _request
    name = filename or path.name
    mime = mime_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
    extension = mimetypes.guess_extension(mime)
    if extension and mimetypes.guess_type(name)[0] != mime:
        name = Path(name).stem + extension
    kind = "video" if mime.startswith("video/") else "image"
    size = path.stat().st_size
    if size <= 0 or size > MAX_UPLOAD_BYTES:
        raise ValueError("Runway input must be nonempty and at most 200 MiB.")
    prefix = f"data:{mime};base64,"
    if len(prefix) + 4 * math.ceil(size / 3) <= MAX_DATA_URI_BYTES:
        uri = prefix + base64.b64encode(path.read_bytes()).decode("ascii")
        return validate_media_uri(uri, "owned input", kind)
    if size < 512:
        raise ValueError("Runway ephemeral uploads require at least 512 bytes.")
    if dry_run():
        return "runway://renderhaus-dry-input"
    payload = request("POST", "/uploads", {"type": "ephemeral", "filename": name})
    upload_url, fields, uri = payload.get("uploadUrl"), payload.get("fields"), payload.get("runwayUri")
    from providers.runway.contracts import validate_https_url

    validate_https_url(upload_url, "Runway upload URL", max_length=16384)
    validate_media_uri(uri, "Runway upload URI", kind)
    if not isinstance(uri, str) or not uri.startswith("runway://") or not isinstance(fields, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in fields.items()
    ):
        raise RuntimeError("Runway returned an invalid upload response.")
    try:
        with path.open("rb") as file, httpx.Client(timeout=120, follow_redirects=False) as client:
            response = client.post(upload_url, data=fields, files={"file": (name, file, mime)})
    except httpx.RequestError:
        raise RuntimeError("Runway input upload failed. No generation was submitted.") from None
    if not response.is_success:
        raise RuntimeError(f"Runway input upload returned HTTP {response.status_code}. No generation was submitted.")
    return uri
