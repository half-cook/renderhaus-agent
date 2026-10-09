"""Ideogram 4.5 edit and Recraft V4.1 Pro vector on fal, verified 2026-10-09.

https://fal.ai/models/ideogram/v4.5/edit/api
https://fal.ai/models/fal-ai/recraft/v4.1/pro/text-to-vector/api
https://fal.ai/legal/terms-of-service
Closed commercial APIs. No upstream code or weights included.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
from typing import Literal
import uuid

import boto3
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from providers.runway.contracts import validate_https_url
from providers.svg import MAX_SVG_BYTES, SVG_MIME, sanitize_svg


IDEOGRAM = "ideogram/v4.5/edit"
RECRAFT = "fal-ai/recraft/v4.1/pro/text-to-vector"
TOOL_ENDPOINTS = {"ideogram_edit": IDEOGRAM, "recraft_text_to_vector": RECRAFT}
GENERATING_TOOLS = tuple(TOOL_ENDPOINTS)
TRAINING_METADATA = {
    "training_eligible": False, "weights_license": "closed-weights", "license": "service-terms",
    "license_source": "https://fal.ai/legal/terms-of-service", "read_date": "2026-10-09",
}
FIELD_DESCRIPTIONS = {
    "prompt": "Describe the edit or vector design, 1-10000 characters. Recraft styles are described in the prompt; there is no separate style field.",
    "image_url": "Existing source image, public HTTPS URL or renderhaus-asset:// version handle. Resolve authorized handles before live submission.",
    "reference_image_urls": "Up to 4 references, or 3 when mask_url is present. Public HTTPS URLs or authorized Studio handles.",
    "mask_url": "Optional source-sized inpainting mask. Black edits, white preserves; both regions required by the vendor. Public HTTPS or authorized Studio handle.",
    "edit_precision": "high by default for unchanged-pixel restoration; regular redraws and permits resizing. Pixel preservation remains an A/B candidate, not a guarantee.",
    "image_size": "Ideogram defaults auto; masked or high-precision edits require auto. Recraft defaults square_hd. Named presets only; custom dimensions are not exposed.",
    "quality": "Ideogram quality very_low/low/medium/high, default medium. Provider price $0.008/$0.03/$0.06/$0.22 per image, independent of dimensions.",
    "num_images": "Ideogram variations, integer 1-8, default 1. Every output is billed.",
    "colors": "Preferred RGB palette, each channel an integer 0-255.",
    "background_color": "Preferred background RGB, each channel an integer 0-255.",
    "enable_safety_checker": "Defaults true. Disabling requires fal account authorization.",
}


@dataclass(frozen=True)
class Endpoint:
    id: str

    @property
    def model(self) -> str:
        return self.id


ENDPOINTS = {endpoint: Endpoint(endpoint) for endpoint in TOOL_ENDPOINTS.values()}
ImageSize = Literal["square_hd", "square", "portrait_4_3", "portrait_16_9", "landscape_4_3", "landscape_16_9"]


class ImageRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    prompt: str = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def nonblank(self):
        if not self.prompt.strip():
            raise ValueError("Prompt must contain text.")
        return self


def image_reference(value: str) -> None:
    if not re.fullmatch(r"renderhaus-asset://[A-Za-z0-9_-]+", value):
        validate_https_url(value, "image reference")


class IdeogramRequest(ImageRequest):
    image_url: str
    reference_image_urls: list[str] = Field(default_factory=list, max_length=4)
    mask_url: str | None = None
    edit_precision: Literal["regular", "high"] = "high"
    quality: Literal["very_low", "low", "medium", "high"] = "medium"
    image_size: ImageSize | Literal["auto"] = "auto"
    num_images: int = Field(default=1, ge=1, le=8)
    seed: int | None = None

    @model_validator(mode="after")
    def valid(self):
        for value in [self.image_url, *self.reference_image_urls, *([self.mask_url] if self.mask_url is not None else [])]:
            image_reference(value)
        if self.mask_url and len(self.reference_image_urls) > 3:
            raise ValueError("A mask permits at most 3 reference images.")
        if (self.mask_url or self.edit_precision == "high") and self.image_size != "auto":
            raise ValueError("Masked or high-precision edits require image_size=auto.")
        return self


class RGBColor(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    r: int = Field(ge=0, le=255)
    g: int = Field(ge=0, le=255)
    b: int = Field(ge=0, le=255)


class RecraftRequest(ImageRequest):
    image_size: ImageSize = "square_hd"
    colors: list[RGBColor] = Field(default_factory=list)
    background_color: RGBColor | None = None
    enable_safety_checker: bool = True


def request_for(tool: str, arguments: dict) -> IdeogramRequest | RecraftRequest:
    request_type = {"ideogram_edit": IdeogramRequest, "recraft_text_to_vector": RecraftRequest}[tool]
    optional = {"reference_image_urls", "mask_url", "seed", "colors", "background_color"}
    arguments = {key: value for key, value in arguments.items() if value is not None or key not in optional}
    try:
        return request_type.model_validate(arguments)
    except ValidationError:
        raise ValueError(f"Invalid {tool} request. Use the verified image schema, public HTTPS references and valid image controls.") from None


def validate_arguments(tool: str, arguments: dict) -> None:
    if tool in GENERATING_TOOLS:
        request_for(tool, arguments)


def request_body(tool: str, arguments: dict) -> tuple[Endpoint, dict]:
    request = request_for(tool, arguments)
    return ENDPOINTS[TOOL_ENDPOINTS[tool]], request.model_dump(exclude_none=True)


def output_bucket() -> str:
    return os.getenv("AWS_S3_BUCKET") or os.getenv("REMOTION_APP_BUCKET_NAME") or ""


def require_durable_output() -> None:
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME") and not output_bucket():
        raise RuntimeError("Configure AWS_S3_BUCKET or REMOTION_APP_BUCKET_NAME for fal image output.")


def require_resolved_references(body: dict) -> None:
    if any(value.startswith("renderhaus-asset://") for value in [body.get("image_url", ""), body.get("mask_url", ""), *body.get("reference_image_urls", [])]):
        raise ValueError("Studio image handles must resolve to authorized HTTPS media before live submission.")


def _download_image(image: dict, *, vector: bool) -> tuple[bytes, str, str]:
    url = image.get("url")
    if not isinstance(url, str):
        raise RuntimeError("Completed fal image result must contain public HTTPS URLs.")
    validate_https_url(url, "fal image output")
    declared = image.get("content_type")
    if vector and declared != SVG_MIME:
        raise RuntimeError("Recraft output must declare image/svg+xml.")
    with httpx.Client(timeout=90, follow_redirects=False) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > MAX_SVG_BYTES:
                    raise RuntimeError("fal image output must be at most 20 MiB.")
    if not content:
        raise RuntimeError("fal image output must be non-empty.")
    content = bytes(content)
    if vector:
        if mime != SVG_MIME:
            raise RuntimeError("Recraft download must use image/svg+xml content-type.")
        return sanitize_svg(content), SVG_MIME, "svg"
    signatures = {"image/png": (b"\x89PNG\r\n\x1a\n", "png"), "image/jpeg": (b"\xff\xd8\xff", "jpg"), "image/webp": (b"RIFF", "webp")}
    signature, extension = signatures.get(mime, (b"", ""))
    if not signature or not content.startswith(signature) or mime == "image/webp" and content[8:12] != b"WEBP":
        raise RuntimeError("Ideogram output must contain PNG, JPEG or WebP image bytes.")
    return content, mime, extension


def persist_images(job_id: str, endpoint_id: str, result: dict) -> dict:
    images = result.get("images")
    if not isinstance(images, list) or not images or any(not isinstance(image, dict) for image in images):
        raise RuntimeError("Completed fal result must contain a non-empty image list.")
    decoded = [_download_image(image, vector=endpoint_id == RECRAFT) for image in images]
    bucket = output_bucket()
    stem = "fal_" + hashlib.sha256(job_id.encode()).hexdigest()
    outputs = []
    for i, (content, mime, extension) in enumerate(decoded):
        filename = f"{stem}_{i}.{extension}"
        output = {"filename": filename, "mime_type": mime, "size_bytes": len(content)}
        if bucket:
            s3 = boto3.client("s3")
            key = "renderhaus-fal-images/" + filename
            s3.put_object(Bucket=bucket, Key=key, Body=content, ContentType=mime)
            output["image_url"] = s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=21600)
        else:
            directory = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser() / "images"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / filename
            temporary = path.with_suffix(f".{uuid.uuid4().hex}.part")
            try:
                temporary.write_bytes(content)
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            output["output_path"] = str(path.resolve())
        outputs.append(output)
    return {**outputs[0], "images": outputs, "downloaded": True, "seed": result.get("seed")}
