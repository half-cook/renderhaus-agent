from __future__ import annotations

import hashlib
import hmac
import logging
import mimetypes
import os
import re
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode

import boto3
from botocore.exceptions import ClientError

from server.config import ROOT

AssetKind = Literal["upload", "video", "image", "music"]

logger = logging.getLogger(__name__)

CACHE_DIR = ROOT / ".renderhaus" / "cache"
CONTENT_URL_TTL_SECONDS = 15 * 60
PROVIDER_INPUT_URL_TTL_SECONDS = 6 * 60 * 60
DEFAULT_ASSETS_TABLE = "renderhaus-assets"


@dataclass(frozen=True)
class Asset:
    id: str
    user_id: str
    kind: str
    mime_type: str
    size_bytes: int
    checksum: str
    storage_backend: str
    storage_key: str
    filename: str
    created_at: int


def _signing_secret() -> bytes:
    raw = (
        os.getenv("ASSET_SIGNING_SECRET")
        or os.getenv("INTERNAL_API_SECRET")
        or os.getenv("CLERK_SECRET_KEY")
        or "renderhaus-local-asset-signing"
    )
    return raw.encode("utf-8")


def aws_region() -> str:
    return os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"


def s3_bucket() -> str:
    return (os.getenv("AWS_S3_BUCKET") or "").strip()


def provider_input_bucket() -> str:
    """Private bucket used to make local Studio versions reachable by media providers."""
    return (
        os.getenv("PROVIDER_INPUT_BUCKET")
        or os.getenv("AWS_S3_BUCKET")
        or os.getenv("REMOTION_APP_BUCKET_NAME")
        or ""
    ).strip()


def dynamodb_table_name() -> str:
    return (
        os.getenv("AWS_DYNAMODB_ASSETS_TABLE")
        or os.getenv("AWS_DYNAMODB_TABLE")
        or DEFAULT_ASSETS_TABLE
    ).strip()


def aws_configured() -> bool:
    return bool(
        s3_bucket()
        and (
            os.getenv("AWS_ACCESS_KEY_ID")
            or os.getenv("AWS_PROFILE")
            or os.getenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI")
        )
    )


@lru_cache(maxsize=1)
def _session() -> boto3.session.Session:
    return boto3.session.Session(
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID") or None,
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY") or None,
        region_name=aws_region(),
    )


def _s3():
    return _session().client("s3")


def _dynamodb():
    return _session().resource("dynamodb")


def _require_bucket() -> str:
    bucket = s3_bucket()
    if not bucket:
        raise RuntimeError(
            "AWS_S3_BUCKET is not set. Add it to .env.local to store artifacts in S3."
        )
    return bucket


def _item_to_asset(item: dict[str, Any]) -> Asset:
    return Asset(
        id=str(item["asset_id"]),
        user_id=str(item["user_id"]),
        kind=str(item["kind"]),
        mime_type=str(item["mime_type"]),
        size_bytes=int(item["size_bytes"]),
        checksum=str(item["checksum"]),
        storage_backend=str(item.get("storage_backend") or "s3"),
        storage_key=str(item["storage_key"]),
        filename=str(item["filename"]),
        created_at=int(item["created_at"]),
    )


def _ensure_dynamodb_table() -> None:
    table_name = dynamodb_table_name()
    client = _session().client("dynamodb")
    try:
        client.describe_table(TableName=table_name)
        return
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise

    logger.info("Creating DynamoDB table %s", table_name)
    client.create_table(
        TableName=table_name,
        AttributeDefinitions=[
            {"AttributeName": "asset_id", "AttributeType": "S"},
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "created_at", "AttributeType": "N"},
        ],
        KeySchema=[{"AttributeName": "asset_id", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "user_id-created_at-index",
                "KeySchema": [
                    {"AttributeName": "user_id", "KeyType": "HASH"},
                    {"AttributeName": "created_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    waiter = client.get_waiter("table_exists")
    waiter.wait(TableName=table_name)


def _ensure_s3_bucket() -> None:
    bucket = _require_bucket()
    client = _s3()
    region = aws_region()
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code not in {"404", "NoSuchBucket", "NotFound", "403"}:
            # 403 can mean exists but no Head permission; try create only on 404.
            if code == "403":
                logger.warning("Cannot head S3 bucket %s (403); assuming it exists", bucket)
                return
            raise
        logger.info("Creating S3 bucket %s in %s", bucket, region)
        if region == "us-east-1":
            client.create_bucket(Bucket=bucket)
        else:
            client.create_bucket(
                Bucket=bucket,
                CreateBucketConfiguration={"LocationConstraint": region},
            )

    origins = [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]
    app_url = (os.getenv("APP_URL") or "").rstrip("/")
    if app_url and app_url not in origins:
        origins.append(app_url)
    try:
        client.put_bucket_cors(
            Bucket=bucket,
            CORSConfiguration={
                "CORSRules": [
                    {
                        "AllowedHeaders": ["*"],
                        "AllowedMethods": ["GET", "HEAD"],
                        "AllowedOrigins": origins,
                        "ExposeHeaders": ["Content-Length", "Content-Range", "Accept-Ranges"],
                        "MaxAgeSeconds": 3000,
                    }
                ]
            },
        )
    except ClientError as exc:
        logger.warning("Could not set S3 CORS on %s: %s", bucket, exc)


def init_assets_db() -> None:
    """Initialize DynamoDB table and verify/create the S3 bucket."""
    _session.cache_clear()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not s3_bucket():
        raise RuntimeError(
            "AWS_S3_BUCKET is not set. Add your bucket name to .env.local before starting the app."
        )
    _ensure_dynamodb_table()
    _ensure_s3_bucket()


def get_asset(asset_id: str) -> Asset | None:
    table = _dynamodb().Table(dynamodb_table_name())
    response = table.get_item(Key={"asset_id": asset_id})
    item = response.get("Item")
    return _item_to_asset(item) if item else None


def get_asset_for_user(asset_id: str, user_id: str) -> Asset | None:
    asset = get_asset(asset_id)
    if asset is None or asset.user_id != user_id:
        return None
    return asset


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _put_asset_record(
    *,
    asset_id: str,
    user_id: str,
    kind: AssetKind,
    mime_type: str,
    size_bytes: int,
    checksum: str,
    storage_key: str,
    filename: str,
) -> Asset:
    created_at = int(time.time())
    item = {
        "asset_id": asset_id,
        "user_id": user_id,
        "kind": kind,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
        "checksum": checksum,
        "storage_backend": "s3",
        "storage_key": storage_key,
        "filename": filename,
        "created_at": created_at,
    }
    table = _dynamodb().Table(dynamodb_table_name())
    table.put_item(Item=item)
    return _item_to_asset(item)


def _upload_bytes(*, storage_key: str, content: bytes, mime_type: str) -> None:
    _s3().put_object(
        Bucket=_require_bucket(),
        Key=storage_key,
        Body=content,
        ContentType=mime_type,
    )


def _upload_file(*, storage_key: str, path: Path, mime_type: str) -> None:
    extra = {"ContentType": mime_type}
    _s3().upload_file(
        Filename=str(path),
        Bucket=_require_bucket(),
        Key=storage_key,
        ExtraArgs=extra,
    )


def register_upload(
    *,
    user_id: str,
    content: bytes,
    suffix: str,
    mime_type: str,
    filename: str | None = None,
) -> Asset:
    asset_id = uuid.uuid4().hex
    safe_name = filename or f"reference{suffix}"
    storage_key = f"users/{user_id}/uploads/{asset_id}/{asset_id}{suffix}"
    _upload_bytes(storage_key=storage_key, content=content, mime_type=mime_type)
    return _put_asset_record(
        asset_id=asset_id,
        user_id=user_id,
        kind="upload",
        mime_type=mime_type,
        size_bytes=len(content),
        checksum=_sha256_bytes(content),
        storage_key=storage_key,
        filename=safe_name,
    )


def register_output_file(
    *,
    user_id: str,
    source_path: str | Path,
    kind: AssetKind,
    mime_type: str | None = None,
) -> Asset:
    source = Path(source_path).expanduser().resolve()
    if not source.is_file() or source.stat().st_size <= 0:
        raise FileNotFoundError(f"Output file missing: {source}")
    asset_id = uuid.uuid4().hex
    suffix = source.suffix or {
        "video": ".mp4",
        "image": ".png",
        "music": ".mp3",
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
    _upload_file(storage_key=storage_key, path=source, mime_type=guessed)
    return _put_asset_record(
        asset_id=asset_id,
        user_id=user_id,
        kind=kind,
        mime_type=guessed,
        size_bytes=source.stat().st_size,
        checksum=_sha256_file(source),
        storage_key=storage_key,
        filename=filename,
    )


def register_existing_s3_object(
    *,
    user_id: str,
    storage_key: str,
    kind: AssetKind,
    mime_type: str,
    size_bytes: int,
    checksum: str,
    filename: str,
    asset_id: str | None = None,
) -> Asset:
    """Register an object already uploaded (e.g. by AgentCore) into the assets table."""
    resolved_id = asset_id or uuid.uuid4().hex
    return _put_asset_record(
        asset_id=resolved_id,
        user_id=user_id,
        kind=kind,
        mime_type=mime_type,
        size_bytes=size_bytes,
        checksum=checksum,
        storage_key=storage_key,
        filename=filename,
    )


def materialize_asset_path(asset: Asset) -> Path:
    """Download an S3 asset into a local cache for agent/tool use."""
    if asset.storage_backend not in {"s3", "local"}:
        raise ValueError(f"Unsupported storage backend: {asset.storage_backend}")
    destination = CACHE_DIR / asset.user_id / asset.id / asset.filename
    if destination.is_file() and destination.stat().st_size == asset.size_bytes:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    _s3().download_file(
        Bucket=_require_bucket(),
        Key=asset.storage_key,
        Filename=str(temporary),
    )
    temporary.replace(destination)
    return destination


def local_path_for_asset(asset: Asset) -> Path:
    """Compatibility alias used by the web app for reference materialization."""
    return materialize_asset_path(asset)


def presigned_content_url(asset: Asset, *, ttl_seconds: int = CONTENT_URL_TTL_SECONDS) -> str:
    return _s3().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": _require_bucket(),
            "Key": asset.storage_key,
            "ResponseContentType": asset.mime_type,
            "ResponseContentDisposition": f'inline; filename="{asset.filename}"',
        },
        ExpiresIn=ttl_seconds,
    )


def publish_provider_input_url(
    *,
    source_path: str | Path,
    workspace_id: str,
    version_id: str,
    filename: str,
    mime_type: str | None = None,
    ttl_seconds: int = PROVIDER_INPUT_URL_TTL_SECONDS,
) -> str:
    """Publish an immutable Studio version and return a provider-reachable HTTPS URL.

    Provider APIs cannot fetch localhost playback routes and transient generation URLs can expire.
    The object remains private; only the time-limited signed GET is sent to the provider.
    """
    source = Path(source_path).expanduser().resolve()
    if not source.is_file() or source.stat().st_size <= 0:
        raise FileNotFoundError(f"Provider input file is unavailable: {source}")
    bucket = provider_input_bucket()
    if not bucket:
        raise RuntimeError(
            "Set PROVIDER_INPUT_BUCKET, AWS_S3_BUCKET, or REMOTION_APP_BUCKET_NAME "
            "so external media providers can fetch referenced Studio assets."
        )
    ttl = max(60, min(int(ttl_seconds), 7 * 24 * 60 * 60))
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(filename).name).strip("-._")
    safe_name = safe_name[:180] or f"{version_id}{source.suffix}"
    workspace_scope = hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()[:20]
    storage_key = f"renderhaus-provider-inputs/{workspace_scope}/{version_id}/{safe_name}"
    content_type = mime_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    client = _s3()
    should_upload = True
    try:
        remote = client.head_object(Bucket=bucket, Key=storage_key)
        should_upload = int(remote.get("ContentLength") or -1) != source.stat().st_size
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code") or "")
        if code not in {"404", "NoSuchKey", "NotFound"}:
            raise
    if should_upload:
        client.upload_file(
            Filename=str(source),
            Bucket=bucket,
            Key=storage_key,
            ExtraArgs={"ContentType": content_type},
        )
    return client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": storage_key,
            "ResponseContentType": content_type,
            "ResponseContentDisposition": f'inline; filename="{safe_name}"',
        },
        ExpiresIn=ttl,
    )


def iter_asset_bytes(asset: Asset, *, chunk_size: int = 1024 * 1024):
    """Stream asset bytes from S3 for same-origin proxy responses."""
    response = _s3().get_object(Bucket=_require_bucket(), Key=asset.storage_key)
    body = response["Body"]
    try:
        while True:
            chunk = body.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        try:
            body.close()
        except Exception:
            pass


def sign_content_url(asset_id: str, *, ttl_seconds: int = CONTENT_URL_TTL_SECONDS) -> str:
    """App-level opaque URL; the handler redirects to an S3 presigned GET."""
    exp = int(time.time()) + ttl_seconds
    message = f"{asset_id}:{exp}".encode("utf-8")
    signature = hmac.new(_signing_secret(), message, hashlib.sha256).hexdigest()
    query = urlencode({"exp": str(exp), "sig": signature})
    return f"/api/assets/{asset_id}/content?{query}"


def verify_content_signature(asset_id: str, exp: str | int | None, sig: str | None) -> bool:
    if exp is None or not sig:
        return False
    try:
        expires = int(exp)
    except (TypeError, ValueError):
        return False
    if expires < int(time.time()):
        return False
    message = f"{asset_id}:{expires}".encode("utf-8")
    expected = hmac.new(_signing_secret(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def asset_public_dict(asset: Asset, *, include_url: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": asset.id,
        "kind": asset.kind,
        "mime_type": asset.mime_type,
        "size_bytes": asset.size_bytes,
        "filename": asset.filename,
        "created_at": asset.created_at,
        "storage_backend": asset.storage_backend,
    }
    if include_url:
        payload["content_url"] = sign_content_url(asset.id)
    return payload
