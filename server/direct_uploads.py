"""Browser-direct, resumable multipart uploads for customer footage.

The browser never streams footage through the app server. The server:
  1. creates an S3 multipart upload and returns a signed session token,
  2. signs short-lived per-part PUT URLs,
  3. lists already-stored parts so a dropped upload resumes from the last
     completed part,
  4. completes the upload, checks the stored size, and registers the asset.

The session token is HMAC-signed and bound to the workspace and user, so no
server-side session table is needed and one user cannot sign parts for
another user's upload.
"""

from __future__ import annotations

import asyncio
import base64
import fcntl
import hashlib
import hmac
import json
import math
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server import assets
from server.auth import AuthUser, current_user_id, current_workspace_id
from server.uploads import validate_uploaded_media

router = APIRouter(prefix="/api/studio/uploads/direct", tags=["studio-uploads"])

MIB = 1024 * 1024
MIN_PART_BYTES = 8 * MIB  # S3 minimum is 5 MiB; 8 MiB keeps retries cheap.
MAX_PARTS = 10_000
PART_URL_TTL_SECONDS = 15 * 60
SESSION_TTL_SECONDS = 7 * 24 * 3600
MAX_SIGN_BATCH = 100
DEFAULT_DIRECT_LIMIT_MB = 20 * 1024
SUFFIX_KIND = {
    **{s: "video" for s in (".mp4", ".webm", ".mov", ".m4v")},
    **{s: "audio" for s in (".mp3", ".wav", ".m4a", ".ogg", ".flac")},
    **{s: "image" for s in (".png", ".jpg", ".jpeg", ".webp", ".gif")},
}


def ingest_bucket() -> str:
    return (os.getenv("STUDIO_INGEST_BUCKET") or assets.s3_bucket() or "").strip()


def direct_upload_enabled() -> bool:
    if os.getenv("STUDIO_DIRECT_UPLOAD", "true").strip().lower() in {"0", "false", "off", "no"}:
        return False
    return bool(ingest_bucket())


def direct_upload_limit_mb() -> int:
    value = os.getenv("STUDIO_MAX_DIRECT_UPLOAD_MB", "").strip()
    if not value:
        return DEFAULT_DIRECT_LIMIT_MB
    if not re.fullmatch(r"[0-9]+", value) or int(value) <= 0:
        raise ValueError("STUDIO_MAX_DIRECT_UPLOAD_MB must be a positive integer in MB.")
    return int(value)


def public_config() -> dict[str, Any]:
    enabled = direct_upload_enabled()
    return {
        "enabled": enabled,
        "max_upload_mb": direct_upload_limit_mb() if enabled else 0,
        "min_part_bytes": MIN_PART_BYTES,
    }


def part_size_for(size_bytes: int) -> int:
    size = max(MIN_PART_BYTES, math.ceil(size_bytes / MAX_PARTS))
    return math.ceil(size / MIB) * MIB


def _s3():
    return assets._s3()


def _sign(payload: dict[str, Any]) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode().rstrip("=")
    mac = hmac.new(assets._signing_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{mac}"


def _verify(token: str, *, workspace_id: str, user_id: str) -> dict[str, Any]:
    try:
        body, mac = token.rsplit(".", 1)
        expected = hmac.new(assets._signing_secret(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, expected):
            raise ValueError
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception as exc:  # noqa: BLE001 - every malformed token is the same 400
        raise HTTPException(status_code=400, detail="This upload can't be resumed. Please start it again.") from exc
    if payload.get("ws") != workspace_id or payload.get("uid") != user_id:
        raise HTTPException(status_code=404, detail="Upload not found.")
    if int(payload.get("exp", 0)) < time.time():
        raise HTTPException(status_code=410, detail="This upload expired. Please start it again.")
    return payload


def _require_enabled() -> None:
    if not direct_upload_enabled():
        raise HTTPException(status_code=404, detail="Direct upload is not available.")


class CreateBody(BaseModel):
    project_id: str = Field(min_length=1, max_length=200)
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    content_type: str | None = Field(default=None, max_length=200)


class TokenBody(BaseModel):
    token: str = Field(min_length=10, max_length=4096)


class SignBody(TokenBody):
    part_numbers: list[int] = Field(min_length=1, max_length=MAX_SIGN_BATCH)


class CompletedPart(BaseModel):
    part_number: int = Field(ge=1, le=MAX_PARTS)
    etag: str = Field(min_length=1, max_length=200)


class CompleteBody(TokenBody):
    parts: list[CompletedPart] | None = None


def _repository():
    from server.studio_state import repository

    return repository


@router.post("/create", status_code=201)
async def create_direct_upload(body: CreateBody, auth: AuthUser) -> dict[str, Any]:
    _require_enabled()
    workspace_id = current_workspace_id(auth)
    user_id = current_user_id(auth)
    try:
        await asyncio.to_thread(_repository().require_project, workspace_id, body.project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found.") from exc
    suffix = Path(body.filename).suffix.lower()
    kind = SUFFIX_KIND.get(suffix)
    if kind is None:
        raise HTTPException(status_code=415, detail="Use an image, video, or audio file.")
    limit_mb = direct_upload_limit_mb()
    if body.size_bytes > limit_mb * MIB:
        raise HTTPException(status_code=413, detail=f"File is larger than {limit_mb} MB.")
    part_size = part_size_for(body.size_bytes)
    upload_ref = uuid.uuid4().hex
    key = f"users/{user_id}/ingest/{upload_ref}/original{suffix}"
    content_type = body.content_type or "application/octet-stream"
    try:
        response = await asyncio.to_thread(
            _s3().create_multipart_upload,
            Bucket=ingest_bucket(),
            Key=key,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )
    except ClientError as exc:
        raise HTTPException(status_code=502, detail="Upload could not start. Please try again.") from exc
    token = _sign({
        "v": 1,
        "ws": workspace_id,
        "uid": user_id,
        "pid": body.project_id,
        "key": key,
        "uploadId": response["UploadId"],
        "size": body.size_bytes,
        "part": part_size,
        "name": Path(body.filename).name,
        "kind": kind,
        "exp": int(time.time()) + SESSION_TTL_SECONDS,
    })
    return {
        "token": token,
        "part_size": part_size,
        "part_count": math.ceil(body.size_bytes / part_size),
    }


@router.post("/sign-parts")
async def sign_parts(body: SignBody, auth: AuthUser) -> dict[str, Any]:
    _require_enabled()
    session = _verify(body.token, workspace_id=current_workspace_id(auth), user_id=current_user_id(auth))
    part_count = math.ceil(session["size"] / session["part"])
    urls: dict[str, str] = {}
    for number in sorted(set(body.part_numbers)):
        if not 1 <= number <= part_count:
            raise HTTPException(status_code=400, detail="Part number out of range.")
        urls[str(number)] = _s3().generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": ingest_bucket(),
                "Key": session["key"],
                "UploadId": session["uploadId"],
                "PartNumber": number,
            },
            ExpiresIn=PART_URL_TTL_SECONDS,
        )
    return {"urls": urls, "expires_in": PART_URL_TTL_SECONDS}


async def _list_parts(session: dict[str, Any]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    marker = 0
    while True:
        try:
            response = await asyncio.to_thread(
                _s3().list_parts,
                Bucket=ingest_bucket(),
                Key=session["key"],
                UploadId=session["uploadId"],
                PartNumberMarker=marker,
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"NoSuchUpload", "404"}:
                raise HTTPException(status_code=410, detail="This upload expired. Please start it again.") from exc
            raise HTTPException(status_code=502, detail="Upload status is unavailable. Please try again.") from exc
        for item in response.get("Parts", []):
            parts.append({"part_number": int(item["PartNumber"]), "etag": item["ETag"], "size": int(item["Size"])})
        if not response.get("IsTruncated"):
            return parts
        marker = int(response.get("NextPartNumberMarker") or 0)


def _expected_part_size(session: dict[str, Any], number: int) -> int:
    part_count = math.ceil(session["size"] / session["part"])
    if number < part_count:
        return session["part"]
    return session["size"] - session["part"] * (part_count - 1)


def _upload_asset_id(session: dict[str, Any]) -> str:
    identity = json.dumps([session[k] for k in ("ws", "uid", "pid", "key", "uploadId")])
    return "ingest_" + hashlib.sha256(identity.encode()).hexdigest()


def _completed_asset(session: dict[str, Any]):
    repository = _repository()
    reference = repository.get_first_asset_version(session["ws"], _upload_asset_id(session))
    if reference is not None and reference.size_bytes == session["size"]:
        try:
            repository.version_path(session["ws"], reference.version_id)
        except (KeyError, FileNotFoundError, ValueError):
            return None
        return reference
    return None


def _register_completed_upload(session: dict[str, Any]) -> dict[str, Any]:
    repository = _repository()
    asset_id = _upload_asset_id(session)
    lock_path = repository.media_root / ".direct-uploads" / f"{asset_id}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # shortcut: locks share the current local SQLite/media store; use a shared lock with remote storage.
    with lock_path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        if reference := _completed_asset(session):
            return reference.public()
        bucket = ingest_bucket()
        try:
            head = _s3().head_object(Bucket=bucket, Key=session["key"])
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}:
                raise HTTPException(status_code=410, detail="This upload expired. Please start it again.") from exc
            raise HTTPException(status_code=502, detail="Upload status is unavailable. Please try again.") from exc
        if int(head["ContentLength"]) != int(session["size"]):
            raise HTTPException(status_code=422, detail="The uploaded file is incomplete. Please start it again.")
        try:
            with tempfile.TemporaryDirectory(prefix="renderhaus-direct-") as directory:
                local = Path(directory) / f"original{Path(session['name']).suffix.lower()}"
                _s3().download_file(bucket, session["key"], str(local))
                validate_uploaded_media(local, filename=session["name"], kind=session["kind"])
                reference = repository.register_file(
                    workspace_id=session["ws"],
                    project_id=session["pid"],
                    user_id=session["uid"],
                    path=local,
                    filename=session["name"],
                    kind=session["kind"],
                    asset_id=asset_id,
                )
        except HTTPException:
            raise
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Project not found.") from exc
        except Exception as exc:  # Registration can be retried against the completed object.
            raise HTTPException(status_code=502, detail="Upload could not be saved. Please try again.") from exc
        return reference.public()


@router.post("/status")
async def upload_status(body: TokenBody, auth: AuthUser) -> dict[str, Any]:
    """Parts S3 already holds. The browser resumes after the last of these."""
    _require_enabled()
    session = _verify(body.token, workspace_id=current_workspace_id(auth), user_id=current_user_id(auth))
    if reference := await asyncio.to_thread(_completed_asset, session):
        return {"completed_asset": reference.public()}
    try:
        stored = await _list_parts(session)
    except HTTPException as exc:
        if exc.status_code != 410:
            raise
        return {"completed_asset": await asyncio.to_thread(_register_completed_upload, session)}
    parts = [p for p in stored if p["size"] == _expected_part_size(session, p["part_number"])]
    return {
        "part_size": session["part"],
        "part_count": math.ceil(session["size"] / session["part"]),
        "completed_parts": [{"part_number": p["part_number"], "etag": p["etag"]} for p in parts],
        "uploaded_bytes": sum(p["size"] for p in parts),
    }


@router.post("/complete")
async def complete_upload(body: CompleteBody, auth: AuthUser) -> dict[str, Any]:
    _require_enabled()
    workspace_id = current_workspace_id(auth)
    user_id = current_user_id(auth)
    session = _verify(body.token, workspace_id=workspace_id, user_id=user_id)
    if reference := await asyncio.to_thread(_completed_asset, session):
        return reference.public()
    part_count = math.ceil(session["size"] / session["part"])
    # S3's own part list is the source of truth; the browser's ETags are only a hint.
    try:
        listed = await _list_parts(session)
    except HTTPException as exc:
        if exc.status_code != 410:
            raise
        return await asyncio.to_thread(_register_completed_upload, session)
    stored = {
        p["part_number"]: p
        for p in listed
        if p["size"] == _expected_part_size(session, p["part_number"])
    }
    missing = [n for n in range(1, part_count + 1) if n not in stored]
    if missing:
        raise HTTPException(status_code=409, detail={"message": "Some parts are missing.", "missing_parts": missing[:100]})
    bucket = ingest_bucket()
    try:
        await asyncio.to_thread(
            _s3().complete_multipart_upload,
            Bucket=bucket,
            Key=session["key"],
            UploadId=session["uploadId"],
            MultipartUpload={"Parts": [{"PartNumber": n, "ETag": stored[n]["etag"]} for n in range(1, part_count + 1)]},
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"NoSuchUpload", "404"}:
            raise HTTPException(status_code=502, detail="Upload could not be finished. Please try again.") from exc
    return await asyncio.to_thread(_register_completed_upload, session)


@router.post("/abort")
async def abort_upload(body: TokenBody, auth: AuthUser) -> dict[str, Any]:
    _require_enabled()
    session = _verify(body.token, workspace_id=current_workspace_id(auth), user_id=current_user_id(auth))
    try:
        await asyncio.to_thread(
            _s3().abort_multipart_upload, Bucket=ingest_bucket(), Key=session["key"], UploadId=session["uploadId"]
        )
    except ClientError:
        pass
    return {"aborted": True}
