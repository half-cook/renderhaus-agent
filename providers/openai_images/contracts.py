"""OpenAI Images contracts verified against official docs on 2026-10-09.

https://developers.openai.com/api/reference/resources/images/methods/generate
https://developers.openai.com/api/reference/resources/images/methods/edit
https://developers.openai.com/api/docs/guides/image-generation
"""

from __future__ import annotations

import os
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


DEFAULT_MODEL = "gpt-image-2.5-sunburst"
MODELS = (DEFAULT_MODEL, "gpt-image-2.5-sunburst-2026-09-08")
QUALITY = ("low", "medium", "high", "xhigh", "max", "auto")
RATIOS = ("1:1", "16:9", "9:16")
SIZES = ("1K", "2K", "1024x1024", "1536x1024", "1024x1536", "2560x1440", "1440x2560", "auto")
FORMAT = ("png", "jpeg", "webp")
MODEL_URL = "https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst"
TERMS_URL = "https://openai.com/policies/services-agreement/"
TRAINING_METADATA = {
    "training_eligible": False, "weights_license": "closed-weights",
    "license": "service-terms", "license_source": TERMS_URL,
}


def size_for_ratio(size: str, aspect_ratio: str) -> str:
    presets = {
        "1K": {"1:1": "1024x1024", "16:9": "1536x864", "9:16": "864x1536"},
        "2K": {"1:1": "2048x2048", "16:9": "2560x1440", "9:16": "1440x2560"},
    }
    return presets.get(size, {}).get(aspect_ratio, size)


def validate_reference(value: str) -> None:
    if value.startswith("data:"):
        if not re.match(r"data:image/(png|jpeg|webp);base64,", value) or len(value) > 20971520:
            raise ValueError("Image data URL must be PNG, JPEG or WebP and at most 20 MiB encoded.")
        return
    parsed = urlsplit(value)
    if parsed.scheme == "renderhaus-asset" and parsed.netloc:
        return
    if parsed.scheme:
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Image reference must use HTTPS, a data URL, or a local media path.")
    elif not value.strip():
        raise ValueError("Image reference must not be empty.")


class ImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    prompt: str = Field(min_length=1, max_length=32000)
    model: str | None = None
    size: str = "2K"
    aspect_ratio: Literal["1:1", "16:9", "9:16"] = "1:1"
    quality: Literal["low", "medium", "high", "xhigh", "max", "auto"] = "high"
    background: Literal["auto", "opaque", "transparent"] = "auto"
    output_format: Literal["png", "jpeg", "webp"] = "png"
    output_compression: int | None = Field(default=None, ge=0, le=100)
    n: int = Field(default=1, ge=1, le=10)
    moderation: Literal["auto", "low"] = "auto"
    image_path_or_url: str | None = None
    reference_image_urls: list[str] | None = Field(default=None, max_length=15)
    mask_path_or_url: str | None = None

    @model_validator(mode="after")
    def supported_request(self) -> ImageRequest:
        if not self.prompt.strip():
            raise ValueError("prompt must not be blank.")
        self.model = self.model or os.getenv("OPENAI_IMAGES_MODEL") or DEFAULT_MODEL
        self.size = size_for_ratio(self.size, self.aspect_ratio)
        if self.size != "auto":
            match = re.fullmatch(r"([1-9]\d*)x([1-9]\d*)", self.size)
            if not match:
                raise ValueError("size must be 1K, 2K, auto or WIDTHxHEIGHT.")
            width, height = map(int, match.groups())
            if (max(width, height) > 3840 or width % 16 or height % 16
                    or max(width, height) > 3 * min(width, height)
                    or not 655360 <= width * height <= 8294400):
                raise ValueError("size violates documented edge, pixel, divisibility or aspect ratio limits.")
        if self.background == "transparent" and self.output_format == "jpeg":
            raise ValueError("transparent background requires png or webp output.")
        if self.output_compression is not None and self.output_format == "png":
            raise ValueError("output_compression requires jpeg or webp output.")
        for value in [self.image_path_or_url, self.mask_path_or_url, *(self.reference_image_urls or [])]:
            if value is not None:
                validate_reference(value)
        return self


def request_for(tool: str, arguments: dict) -> ImageRequest:
    request = ImageRequest.model_validate(arguments)
    if tool == "edit_image" and request.image_path_or_url is None:
        raise ValueError("edit_image requires image_path_or_url.")
    if tool == "generate_image" and any((request.image_path_or_url, request.reference_image_urls, request.mask_path_or_url)):
        raise ValueError("Image references require edit_image.")
    return request


FIELD_DESCRIPTIONS = {
    "size": "1K, 2K, auto or WIDTHxHEIGHT. Defaults to 2K. Edges divisible by 16, <=3840; aspect 1:3 to 3:1; 655360 to 8294400 pixels. Above 2560x1440 is experimental.",
    "n": "Number of output images, integer 1 to 10. Defaults to 1.",
    "prompt": "Nonblank image instruction, at most 32000 characters.",
    "image_path_or_url": "Primary image to edit. HTTPS, base64 PNG/JPEG/WebP data URL, immutable asset handle or local path under RENDERHAUS_MEDIA_DIR.",
    "reference_image_urls": "Up to 15 additional image references for character/product consistency, in order after the primary image. Same input types as image_path_or_url; 16 inputs total.",
    "mask_path_or_url": "Optional alpha mask for the first image. Same image reference types. Match source format and dimensions; transparent regions guide edits. Provider validates remote masks.",
    "output_compression": "Optional integer 0 to 100, only with jpeg/webp output.",
    "model": "Sunburst alias or 2026-09-08 snapshot. Other configured IDs are UNVERIFIED and dry-run only.",
}
