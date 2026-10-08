"""Publish owned Runway inputs and measure Aleph clips before quoting paid work.

https://docs.dev.runwayml.com/assets/inputs/
https://docs.dev.runwayml.com/assets/uploads/
https://docs.dev.runwayml.com/api/

Runway requires HEAD-capable input URLs. S3 GET presigned URLs are method-specific,
so owned inputs use data URIs or official ephemeral uploads instead.
"""

from __future__ import annotations

import base64
import json
import ipaddress
import socket
import math
import mimetypes
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from dataclasses import dataclass
from http.client import HTTPSConnection, HTTPException
from urllib.parse import urlsplit
from typing import Any

import httpx

from providers.runway.api import _request, dry_run
from providers.runway.contracts import MAX_DATA_URI_BYTES, validate_media_uri, validate_runway_arguments


@dataclass(frozen=True)
class _OwnedInput:
    path: Path
    filename: str
    mime_type: str | None


class _PublicHTTPSConnection(HTTPSConnection):
    """Pin a verified public address while preserving hostname TLS verification."""

    def connect(self) -> None:
        addresses = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        if not addresses or any(
            not ipaddress.ip_address(item[4][0]).is_global
            or ipaddress.ip_address(item[4][0]).is_multicast
            for item in addresses
        ):
            raise ValueError("Aleph HTTPS source must resolve only to public addresses.")
        self.sock = socket.create_connection((addresses[0][4][0], self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)
        except Exception:
            self.sock.close()
            raise


MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_VIDEO_URL_BYTES = 32 * 1024 * 1024
_VIDEO_MIMES = {
    "video/mp4", "video/quicktime", "video/x-matroska", "video/webm",
    "video/3gpp", "video/ogg", "video/x-msvideo", "video/x-flv", "video/mpeg",
}


def _publish_file(path: Path, filename: str | None = None, mime_type: str | None = None) -> str:
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
    payload = _request("POST", "/uploads", {"type": "ephemeral", "filename": name})
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


def _probe_video(path: Path) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, check=True,
        )
        info = json.loads(result.stdout)
        duration = float(info["format"]["duration"])
        video = next(stream for stream in info["streams"] if stream.get("codec_type") == "video")
        numerator, denominator = video["r_frame_rate"].split("/")
        fps = float(numerator) / float(denominator)
        short_side = min(int(video["width"]), int(video["height"]))
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, StopIteration, TypeError, ZeroDivisionError):
        raise ValueError("Aleph input could not be measured. Install ffprobe on the Studio host and supply a valid video.") from None
    if not math.isfinite(duration) or not 2 <= duration <= 30:
        raise ValueError("Aleph source video must be 2-30 seconds.")
    if not math.isfinite(fps) or not 0 < fps <= 30 or not 0 < short_side <= 1080:
        raise ValueError("Aleph source video must be at most 30 FPS and 1080p.")
    return duration


def _capture_video(uri: str, destination: Path) -> str:
    validate_media_uri(uri, "video_path_or_url", "video")
    if uri.startswith("data:"):
        destination.write_bytes(base64.b64decode(uri.partition(",")[2], validate=True))
        return uri[5:].partition(";")[0]
    if uri.startswith("runway://"):
        raise ValueError("Aleph billing cannot measure an external upload handle. Use a Studio video asset, HTTPS source, or data URI.")
    parsed = urlsplit(uri)
    connection = _PublicHTTPSConnection(parsed.hostname, timeout=90)
    try:
        connection.request("GET", parsed.path + ("?" + parsed.query if parsed.query else "") or "/")
        with connection.getresponse() as response:
            if not 200 <= response.status < 300:
                raise ValueError("Aleph source video could not be downloaded for measurement.")
            mime = response.getheader("content-type", "").split(";", 1)[0].lower()
            if mime not in _VIDEO_MIMES:
                raise ValueError("Aleph source must return a supported video Content-Type.")
            size = 0
            with destination.open("wb") as file:
                while chunk := response.read(65536):
                    size += len(chunk)
                    if size > MAX_VIDEO_URL_BYTES:
                        raise ValueError("Aleph HTTPS source exceeds the 32 MiB URL input limit.")
                    file.write(chunk)
        return mime
    except (OSError, HTTPException):
        raise ValueError("Aleph source video could not be downloaded for measurement.") from None
    finally:
        connection.close()


def prepare_runway_arguments(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    source_resolver: Callable[[str], str] | None = None,
    source_versions: dict[str, str] | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Resolve scoped handles and submit the exact Aleph bytes used for the price quote."""
    if workspace_id and not source_resolver and tool_name not in {"get_runway_task", "list_runway_models"}:
        raise ValueError("Runway generation requires the scoped Studio asset and task context. The separate AgentCore runtime is unsupported.")
    if tool_name == "get_runway_task" and workspace_id:
        from server.studio import repository

        repository.require_provider_task(workspace_id, "runway", arguments.get("job_id", ""))
    owned: dict[str, _OwnedInput] = {}

    def resolve(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if not isinstance(value, str):
            return value
        version_id = (source_versions or {}).get(value)
        if value.startswith("renderhaus-asset://"):
            version_id = value.removeprefix("renderhaus-asset://")
        if version_id is None:
            return value
        if not source_resolver:
            raise ValueError("This Runway request has no scoped Studio asset resolver.")
        path = Path(source_resolver(version_id))
        placeholder = f"runway://renderhaus-owned-{len(owned)}"
        filename, mime = path.name, None
        if workspace_id:
            from server.studio import repository

            reference = repository.get_version(workspace_id, version_id)
            if reference is None:
                raise ValueError("Runway input asset was not found in this workspace.")
            filename, mime = reference.filename, reference.mime_type
        owned[placeholder] = _OwnedInput(path, filename, mime)
        return placeholder

    resolved = resolve(arguments)
    validate_runway_arguments(tool_name, resolved)
    with tempfile.TemporaryDirectory(prefix="runway-input-") as temp:
        video_placeholder = resolved.get("video_path_or_url") if tool_name == "video_to_video" else None
        measured_video: Path | None = None
        captured_mime: str | None = None
        if video_placeholder is not None and not dry_run():
            owned_video = owned.get(video_placeholder)
            measured_video = owned_video.path if owned_video else None
            if measured_video is None:
                measured_video = Path(temp) / "source.mp4"
                captured_mime = _capture_video(video_placeholder, measured_video)
            resolved["video_duration_seconds"] = _probe_video(measured_video)
            validate_runway_arguments(tool_name, resolved)

        def publish(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: publish(item) for key, item in value.items()}
            if isinstance(value, list):
                return [publish(item) for item in value]
            if isinstance(value, str) and value in owned:
                source = owned[value]
                return _publish_file(source.path, source.filename, source.mime_type)
            return value

        resolved = publish(resolved)
        if measured_video is not None and video_placeholder not in owned:
            resolved["video_path_or_url"] = _publish_file(measured_video, "source", captured_mime)
    validate_runway_arguments(tool_name, resolved)
    return resolved
