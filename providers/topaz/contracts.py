"""Topaz fal request contracts checked 2026-10-09.

https://fal.ai/models/topaz/upscale/video/generative/api
https://fal.ai/models/topaz/interpolate/video/api
https://developer.topazlabs.com/video-models/starlight/starlight-precise-2.6
https://developer.topazlabs.com/video-models/frame-interpolation/apollo
https://developer.topazlabs.com/video-models/frame-interpolation/chronos
https://fal.ai/legal/terms-of-service
"""

from __future__ import annotations

import ipaddress
import math
import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


DEFAULT_UPSCALE_MODEL = "Starlight Precise 2.6"
DEFAULT_INTERPOLATE_MODEL = "Apollo"
UPSCALE_ENDPOINT = "topaz/upscale/video/generative"
INTERPOLATE_ENDPOINT = "topaz/interpolate/video"
GENERATING_TOOLS = ("upscale_video", "interpolate_video")
MODEL_ALIASES = {"slp-2.6": DEFAULT_UPSCALE_MODEL, "apo-8": "Apollo", "chr-2": "Chronos"}
TRAINING_METADATA = {
    "training_eligible": False,
    "weights_license": "closed-weights",
    "license": "service-terms",
    "license_source": "https://fal.ai/legal/terms-of-service",
    "hosted_terms_url": "https://fal.ai/legal/terms-of-service",
    "license_read_date": "2026-10-09",
}
FIELD_DESCRIPTIONS = {
    "video_url": "Public HTTPS source video or renderhaus-asset:// version handle for preview. Resolve Studio handles before live submission.",
    "source_duration_seconds": "Measured source duration in seconds, greater than zero and at most 300. Required for a cost estimate.",
    "source_fps": "Measured positive source frame rate. Used to compute output and price, never sent to fal.",
    "source_width": "Measured positive source width in pixels. Output must fit landscape or portrait 4K.",
    "source_height": "Measured positive source height in pixels. Output must fit landscape or portrait 4K.",
    "upscale_factor": "Scale both dimensions by 1 to 4. Defaults to 2 when target_resolution is absent.",
    "target_resolution": "Optional 1080p or 4K short-edge target preserving aspect. Must agree with any supplied upscale_factor.",
    "target_fps": "Optional output FPS. Upscale accepts 16 to 60; interpolation accepts 16 to 120 and defaults to 60. Changing FPS during upscale adds Apollo interpolation.",
    "fps_multiplier": "Optional multiplier of measured source_fps for interpolation. Supply this or target_fps, with an integral result from 16 to 120.",
    "model": "Upscale uses Starlight Precise 2.6. Interpolation uses Apollo by default or Chronos for plain linear-motion FPS conversion. Direct aliases slp-2.6, apo-8 and chr-2 normalize to fal names.",
    "softness": "Optional Starlight Precise 2.6 softness from 1, sharpest, to 5, softest. Unset uses Topaz's default.",
    "slowdown_factor": "Integer 1 to 8. Multiplies output duration at the target FPS. Unverified prices remain preview-only.",
    "H264_output": "Use H264 for browser playback. Defaults to true; fal's default H265 can require a compatible player.",
    "job_id": "Exact Topaz handle returned by a submit tool. Contains model identity for polling after a restart.",
    "download": "Download a completed video and validate its MP4 video container before reporting an artifact.",
}
ARGUMENT_RULES: dict[str, dict[str, Any]] = {}


@dataclass(frozen=True)
class Endpoint:
    id: str
    model: str
    api_url: str


ENDPOINTS = {
    UPSCALE_ENDPOINT: Endpoint(UPSCALE_ENDPOINT, DEFAULT_UPSCALE_MODEL, f"https://fal.ai/models/{UPSCALE_ENDPOINT}/api"),
    INTERPOLATE_ENDPOINT: Endpoint(INTERPOLATE_ENDPOINT, DEFAULT_INTERPOLATE_MODEL, f"https://fal.ai/models/{INTERPOLATE_ENDPOINT}/api"),
}


def configured_model(tool: str, arguments: dict[str, Any] | None = None) -> str:
    value = (arguments or {}).get("model")
    if value is None:
        return DEFAULT_UPSCALE_MODEL if tool == "upscale_video" else DEFAULT_INTERPOLATE_MODEL
    return MODEL_ALIASES.get(value, value)


def _validate_reference(value: str) -> None:
    if re.fullmatch(r"renderhaus-asset://[A-Za-z0-9_-]+", value):
        return
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        valid = (
            parsed.scheme == "https" and hostname and not parsed.username
            and not parsed.password and not parsed.fragment
            and not any(character.isspace() for character in value)
            and (parsed.port is None or 0 < parsed.port <= 65535)
        )
    except ValueError:
        valid, hostname = False, None
    if not valid:
        raise ValueError("video_url requires public HTTPS without credentials or a valid Studio asset handle.")
    hostname = hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")) or "." not in hostname:
        raise ValueError("video_url cannot refer to a local or private host.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if not address.is_global:
        raise ValueError("video_url cannot refer to a local or private address.")


def _validate_dimensions(width: int, height: int) -> None:
    if max(width, height) > 3840 or min(width, height) > 2160:
        raise ValueError("Topaz output must fit a landscape or portrait 4K bounding box, 3840 by 2160.")


class SourceRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False, hide_input_in_errors=True)

    video_url: str
    source_duration_seconds: float = Field(gt=0, le=300)
    source_fps: float = Field(gt=0)
    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)
    model: str | None = None
    H264_output: bool = True

    @model_validator(mode="after")
    def valid_source(self) -> SourceRequest:
        _validate_reference(self.video_url)
        return self


class UpscaleRequest(SourceRequest):
    upscale_factor: float | None = Field(default=None, ge=1, le=4)
    target_resolution: Literal["1080p", "4K"] | None = None
    target_fps: int | None = Field(default=None, ge=16, le=60)
    softness: float | None = Field(default=None, ge=1, le=5)

    @model_validator(mode="after")
    def supported_upscale(self) -> UpscaleRequest:
        self.model = configured_model("upscale_video", {"model": self.model})
        if self.model != DEFAULT_UPSCALE_MODEL:
            raise ValueError("Only Starlight Precise 2.6 is supported for upscale.")
        if self.target_resolution:
            factor = (1080 if self.target_resolution == "1080p" else 2160) / min(self.source_width, self.source_height)
            if not 1 <= factor <= 4:
                raise ValueError("target_resolution requires an upscale_factor between 1 and 4.")
            if self.upscale_factor is not None and not math.isclose(self.upscale_factor, factor):
                raise ValueError("upscale_factor contradicts target_resolution.")
            self.upscale_factor = factor
        elif self.upscale_factor is None:
            self.upscale_factor = 2.0
        _validate_dimensions(self.output_width, self.output_height)
        return self

    @property
    def output_width(self) -> int:
        return math.ceil(self.source_width * self.upscale_factor)

    @property
    def output_height(self) -> int:
        return math.ceil(self.source_height * self.upscale_factor)

    @property
    def output_fps(self) -> float:
        return self.target_fps if self.target_fps is not None else self.source_fps

    @property
    def output_duration(self) -> float:
        return self.source_duration_seconds

    def fal_body(self) -> dict[str, Any]:
        body = {"video_url": self.video_url, "model": self.model, "upscale_factor": self.upscale_factor, "H264_output": self.H264_output}
        if self.target_fps is not None:
            body["target_fps"] = self.target_fps
        if self.softness is not None:
            body["softness"] = self.softness
        return body


class InterpolateRequest(SourceRequest):
    target_fps: int | None = Field(default=None, ge=16, le=120)
    fps_multiplier: float | None = Field(default=None, gt=0)
    slowdown_factor: int = Field(default=1, ge=1, le=8)

    @model_validator(mode="after")
    def supported_interpolation(self) -> InterpolateRequest:
        self.model = configured_model("interpolate_video", {"model": self.model})
        if self.model not in {"Apollo", "Chronos"}:
            raise ValueError("Only Apollo and Chronos are supported for interpolation.")
        if self.fps_multiplier is not None:
            if self.target_fps is not None:
                raise ValueError("Supply either target_fps or fps_multiplier.")
            derived = self.source_fps * self.fps_multiplier
            if not 16 <= derived <= 120 or not derived.is_integer():
                raise ValueError("fps_multiplier must produce an integral target_fps from 16 to 120.")
            self.target_fps = int(derived)
        elif self.target_fps is None:
            self.target_fps = 60
        _validate_dimensions(self.output_width, self.output_height)
        return self

    @property
    def output_width(self) -> int:
        return self.source_width

    @property
    def output_height(self) -> int:
        return self.source_height

    @property
    def output_fps(self) -> int:
        return self.target_fps

    @property
    def output_duration(self) -> float:
        return self.source_duration_seconds * self.slowdown_factor

    def fal_body(self) -> dict[str, Any]:
        return {
            "video_url": self.video_url, "model": self.model, "target_fps": self.target_fps,
            "slowdown_factor": self.slowdown_factor, "H264_output": self.H264_output,
        }


class PollRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    job_id: str = Field(min_length=1)
    download: bool = False


def request_for(tool: str, arguments: dict[str, Any]) -> UpscaleRequest | InterpolateRequest:
    if tool == "upscale_video":
        return UpscaleRequest.model_validate(arguments)
    if tool == "interpolate_video":
        return InterpolateRequest.model_validate(arguments)
    raise ValueError("Unknown Topaz submit tool.")


def validate_arguments(tool: str, arguments: dict[str, Any]) -> None:
    if tool in GENERATING_TOOLS:
        request_for(tool, arguments)
    elif tool == "get_video_task":
        PollRequest.model_validate(arguments)
