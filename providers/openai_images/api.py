"""Synchronous OpenAI Images API with local base64 artifacts; dry-run by default."""

from __future__ import annotations

import base64
import binascii
import os
import uuid
from pathlib import Path
from typing import Literal

import boto3
import httpx

from providers.openai_images.contracts import MODELS, TRAINING_METADATA, request_for


BASE_URL = "https://api.openai.com/v1/images"
MAX_ENCODED_IMAGE = 20971520


def dry_run() -> bool:
    return os.getenv("OPENAI_IMAGES_DRY_RUN", "true").lower() != "false"


def _image_format(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 33:
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    raise ValueError("Image must contain PNG, JPEG or WebP bytes.")


def _image_reference(value: str) -> dict:
    if value.startswith("https://"):
        return {"image_url": value}
    if value.startswith("data:"):
        try:
            data = base64.b64decode(value.split(",", 1)[1], validate=True)
            _image_format(data)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid base64 image reference.") from exc
        return {"image_url": value}
    root = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser().resolve()
    path = Path(value).expanduser().resolve()
    if root not in path.parents or not path.is_file():
        raise ValueError("Local image must be an existing file under the media directory.")
    if path.stat().st_size > (MAX_ENCODED_IMAGE - 40) * 3 // 4:
        raise ValueError("Local image exceeds the 20 MiB encoded reference limit.")
    data = path.read_bytes()
    mime = _image_format(data)
    return {"image_url": f"data:image/{mime};base64,{base64.b64encode(data).decode('ascii')}"}


def _submit(tool: str, arguments: dict) -> dict:
    request = request_for(tool, arguments)
    verification = "verified official model and JSON Images API" if request.model in MODELS else "UNVERIFIED model ID; dry-run only"
    result = {
        "provider": "openai_images", "model": request.model, "mode": tool,
        "job_id": "openai_images_" + uuid.uuid4().hex, "size": request.size,
        "quality": request.quality, "output_format": request.output_format,
        "verification": verification, "estimated_cost_usd": None,
        "cost_estimate": "unknown; UNVERIFIED pre-call token count for selected size/quality and inputs",
        **TRAINING_METADATA,
    }
    if dry_run():
        return {**result, "status": "dry_run", "note": "No request or source read. OPENAI_IMAGES_DRY_RUN defaults true. Synchronous API has no poll tool."}
    if request.model not in MODELS:
        raise ValueError("UNVERIFIED model ID is dry-run only.")
    bucket = os.getenv("AWS_S3_BUCKET") or os.getenv("REMOTION_APP_BUCKET_NAME")
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME") and not bucket:
        raise RuntimeError("Configure AWS_S3_BUCKET or REMOTION_APP_BUCKET_NAME for OpenAI Images media output.")
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is required for live OpenAI Images calls.")
    body = request.model_dump(exclude_none=True, exclude={"aspect_ratio", "image_path_or_url", "reference_image_urls", "mask_path_or_url"})
    if tool == "edit_image":
        body["images"] = [_image_reference(value) for value in [request.image_path_or_url, *(request.reference_image_urls or [])]]
        if request.mask_path_or_url:
            body["mask"] = _image_reference(request.mask_path_or_url)
    endpoint = "edits" if tool == "edit_image" else "generations"
    with httpx.Client(timeout=180) as client:
        response = client.post(f"{BASE_URL}/{endpoint}", json=body,
                               headers={"Authorization": f"Bearer {key}"})
    if response.is_error:
        # Raw provider messages can echo input media or credentials.
        raise RuntimeError(f"OpenAI Images API error HTTP {response.status_code}.")
    try:
        payload = response.json()
        images = payload.get("data")
        if not isinstance(images, list) or len(images) != request.n:
            raise ValueError("Missing output images.")
        decoded = [base64.b64decode(image["b64_json"], validate=True) for image in images]
        if any(_image_format(data) != request.output_format for data in decoded):
            raise ValueError("Unexpected output format.")
    except (ValueError, TypeError, KeyError, AttributeError, binascii.Error) as exc:
        raise RuntimeError("OpenAI Images returned invalid or incomplete base64 image output.") from exc
    suffix = "jpg" if request.output_format == "jpeg" else request.output_format
    if bucket:
        s3 = boto3.client("s3")
        outputs = []
        for i, data in enumerate(decoded):
            filename = f"{result['job_id']}_{i}.{suffix}"
            storage_key = "renderhaus-openai-images/" + filename
            mime = "image/" + request.output_format
            s3.put_object(Bucket=bucket, Key=storage_key, Body=data, ContentType=mime)
            url = s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": storage_key}, ExpiresIn=21600)
            outputs.append({"image_url": url, "filename": filename, "mime_type": mime, "size_bytes": len(data)})
    else:
        directory = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser() / "images"
        directory.mkdir(parents=True, exist_ok=True)
        paths = [directory / f"{result['job_id']}_{i}.{suffix}" for i in range(request.n)]
        try:
            for path, data in zip(paths, decoded):
                temporary = path.with_suffix(".part")
                try:
                    temporary.write_bytes(data)
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
        except OSError:
            for path in paths:
                path.unlink(missing_ok=True)
            raise
        outputs = [{"output_path": str(path.resolve())} for path in paths]
    from server.billing_rates import openai_images_usage_cost

    usage = payload.get("usage")
    return {**result, "status": "succeeded", **outputs[0],
            "images": outputs, "usage": usage,
            "actual_cost_usd": openai_images_usage_cost(usage),
            "note": "Synchronous completion. Review the saved images before animation; output is ineligible for training."}


def generate_image(
    prompt: str, aspect_ratio: Literal["1:1", "16:9", "9:16"] = "1:1", size: str = "2K",
    model: str | None = None, quality: Literal["low", "medium", "high", "xhigh", "max", "auto"] = "high",
    background: Literal["auto", "opaque", "transparent"] = "auto",
    output_format: Literal["png", "jpeg", "webp"] = "png", n: int = 1,
    moderation: Literal["auto", "low"] = "auto", output_compression: int | None = None,
) -> dict:
    """Generate Sunburst stills synchronously; paid image approval applies, estimated cost unknown."""
    return _submit("generate_image", locals())


def edit_image(
    prompt: str, image_path_or_url: str, reference_image_urls: list[str] | None = None,
    mask_path_or_url: str | None = None, aspect_ratio: Literal["1:1", "16:9", "9:16"] = "1:1",
    size: str = "2K", model: str | None = None,
    quality: Literal["low", "medium", "high", "xhigh", "max", "auto"] = "high",
    background: Literal["auto", "opaque", "transparent"] = "auto",
    output_format: Literal["png", "jpeg", "webp"] = "png", n: int = 1,
    moderation: Literal["auto", "low"] = "auto", output_compression: int | None = None,
) -> dict:
    """Edit a primary image with up to 15 references and an optional mask; no polling required."""
    return _submit("edit_image", locals())


TOOL_HANDLERS = {"generate_image": generate_image, "edit_image": edit_image}
GATEWAY_TOOLS = tuple(TOOL_HANDLERS)
