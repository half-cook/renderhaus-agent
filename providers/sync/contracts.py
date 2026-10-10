"""Sync contracts checked against official documentation on 2026-10-09.

https://fal.ai/models/fal-ai/sync-lipsync/v3/api
https://sync.so/docs/api-reference/api/generate-api/create
https://sync.so/docs/developer-guides/sync-mode
https://fal.ai/legal/terms-of-service
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


DEFAULT_MODEL = "sync-3"
FAL_ENDPOINT = "fal-ai/sync-lipsync/v3"
FAL_TERMS_URL = "https://fal.ai/legal/terms-of-service"
DIRECT_TERMS_URL = "https://sync.so/terms"
SYNC_MODES = ("cut_off", "loop", "bounce", "silence", "remap")
GENERATING_TOOLS = ("lipsync_video",)
TRAINING_METADATA = {
    "training_eligible": False,
    "weights_license": "closed-weights",
    "license": "service-terms",
    "license_source": FAL_TERMS_URL,
    "hosted_terms_url": FAL_TERMS_URL,
}
FIELD_DESCRIPTIONS = {
    "video_url": "Existing HTTPS video or renderhaus-asset:// version handle. Live handles must resolve through the authorized Studio asset resolver.",
    "audio_url": "Existing HTTPS speech audio or renderhaus-asset:// version handle. No new voice is generated.",
    "source_duration_seconds": "Measured positive finite duration of the source video in seconds. Used to validate chunking and quote cost.",
    "audio_duration_seconds": "Measured positive finite duration of the speech audio in seconds. Sync mode determines output length.",
    "source_fps": "Measured positive finite video frame rate. Direct legacy-base pricing scales by frame count; fal pricing does not.",
    "source_width": "Optional measured input width in positive pixels, paired with source_height. No provider resolution setting is sent; single jobs inherit input dimensions and the current chunk concatenator produces 720p.",
    "source_height": "Optional measured input height in positive pixels, paired with source_width. Required with width to assess an explicitly requested output resolution.",
    "subjects": "Nonblank declaration identifying everyone who appears and whose voice is used. An explicit synthetic-subject and synthetic-voice declaration is allowed.",
    "consent_confirmed": "Must be the boolean true, confirming permission to use every depicted likeness and supplied voice. Required even for synthetic declarations.",
    "sync_mode": "cut_off uses the shorter input; loop, bounce and remap follow audio length; silence uses the longer input. Long chunked runs support equal-length inputs with cut_off only.",
    "chunk_boundaries_seconds": "Strictly increasing internal silence or shot timestamps. Required when either input exceeds SYNC_MAX_CHUNK_SECONDS. Every resulting span must fit the cap. fal's hard duration maximum is UNVERIFIED.",
    "model": "Configured model override. sync-3 is verified. Other identifiers are UNVERIFIED and allowed only in dry-run previews.",
    "job_id": "Exact saved Sync job handle from lipsync_video. Polling never submits another generation.",
    "download": "Save a completed MP4 atomically. Aggregate jobs always download completed children to concatenate their outputs.",
}


@dataclass(frozen=True)
class Endpoint:
    id: str
    model: str


ENDPOINTS = {FAL_ENDPOINT: Endpoint(FAL_ENDPOINT, DEFAULT_MODEL)}


def configured_transport() -> str:
    transport = os.getenv("SYNC_TRANSPORT", "fal").strip().lower()
    if transport not in {"fal", "direct"}:
        raise ValueError("SYNC_TRANSPORT must be fal or direct.")
    return transport


def configured_model(arguments: dict[str, Any] | None = None) -> str:
    return (arguments or {}).get("model") or os.getenv("SYNC_MODEL") or DEFAULT_MODEL


def max_chunk_seconds() -> float:
    try:
        limit = float(os.getenv("SYNC_MAX_CHUNK_SECONDS", "60"))
    except ValueError:
        raise ValueError("SYNC_MAX_CHUNK_SECONDS must be a positive number at most 1800.") from None
    if not math.isfinite(limit) or not 0 < limit <= 1800:
        raise ValueError("SYNC_MAX_CHUNK_SECONDS must be a positive number at most 1800.")
    return limit


def live_blocker(arguments: dict[str, Any], *, transport: str | None = None) -> str | None:
    if configured_model(arguments) != DEFAULT_MODEL:
        return "UNVERIFIED Sync model identifier; only dry-run previews are allowed."
    selected = transport or configured_transport()
    if selected == "direct":
        if os.getenv("SYNC_DIRECT_AUTHORIZED", "false").lower() != "true":
            return (
                "Direct Sync live calls require express written permission under Sync's "
                "competitor terms. SYNC_DIRECT_AUTHORIZED=true declares that the operator holds it."
            )
        if os.getenv("SYNC_BILLING_PLAN", "legacy_base") != "legacy_base":
            return "UNVERIFIED direct Sync billing plan; only dry-run previews are allowed."
    return None


def training_metadata(transport: str) -> dict[str, Any]:
    terms = DIRECT_TERMS_URL if transport == "direct" else FAL_TERMS_URL
    return {**TRAINING_METADATA, "license_source": terms, "hosted_terms_url": terms}


def validate_media_reference(value: str, *, allow_asset: bool = True) -> None:
    if not value or any(character.isspace() for character in value):
        raise ValueError("Media references require HTTPS or a renderhaus-asset:// version handle.")
    if allow_asset and re.fullmatch(r"renderhaus-asset://[A-Za-z0-9_-]+", value):
        return
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme == "https" and parsed.hostname and not parsed.username
            and not parsed.password and not parsed.fragment
            and (parsed.port is None or 0 < parsed.port <= 65535)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Media references require HTTPS without embedded credentials or fragments.")


def reference_for_metadata(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


class SyncRequest(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="forbid", allow_inf_nan=False, hide_input_in_errors=True,
    )

    video_url: str
    audio_url: str
    source_duration_seconds: float = Field(gt=0)
    audio_duration_seconds: float = Field(gt=0)
    source_fps: float = Field(gt=0)
    subjects: str = Field(min_length=1, max_length=12000)
    consent_confirmed: bool
    sync_mode: Literal["cut_off", "loop", "bounce", "silence", "remap"] = "cut_off"
    chunk_boundaries_seconds: list[float] | None = None
    model: str | None = None
    source_width: int | None = Field(default=None, gt=0)
    source_height: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def supported_request(self) -> SyncRequest:
        if self.consent_confirmed is not True:
            raise ValueError("consent_confirmed must be true for every supplied likeness and voice.")
        if not self.subjects.strip():
            raise ValueError("subjects must identify who appears and whose voice is used.")
        self.subjects = self.subjects.strip()
        if (self.source_width is None) != (self.source_height is None):
            raise ValueError("source_width and source_height must be supplied together as measured pixels.")
        validate_media_reference(self.video_url)
        validate_media_reference(self.audio_url)
        self.model = configured_model({"model": self.model})
        if not re.fullmatch(r"[A-Za-z0-9_.\-/]+", self.model) or ".." in self.model:
            raise ValueError("Invalid Sync model identifier.")
        return self

    @property
    def output_duration(self) -> float:
        if self.sync_mode == "cut_off":
            return min(self.source_duration_seconds, self.audio_duration_seconds)
        if self.sync_mode == "silence":
            return max(self.source_duration_seconds, self.audio_duration_seconds)
        return self.audio_duration_seconds


class PollRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    job_id: str = Field(min_length=1)
    download: bool = False


def request_for(arguments: dict[str, Any]) -> SyncRequest:
    from providers.sync.chunks import plan_for

    request = SyncRequest.model_validate(arguments)
    plan_for(request)
    return request


def validate_arguments(tool: str, arguments: dict[str, Any]) -> None:
    from providers.sync.dialogue_contracts import validate_arguments as validate_dialogue_arguments

    validate_dialogue_arguments(tool, arguments)
    if tool == "lipsync_video":
        request_for(arguments)
    elif tool == "get_video_task":
        PollRequest.model_validate(arguments)


def request_body(request: SyncRequest, transport: str) -> dict[str, Any]:
    if transport == "fal":
        return {
            "video_url": request.video_url,
            "audio_url": request.audio_url,
            "sync_mode": request.sync_mode,
        }
    return {
        "model": request.model,
        "input": [
            {"type": "video", "url": request.video_url},
            {"type": "audio", "url": request.audio_url},
        ],
        "options": {"sync_mode": request.sync_mode},
    }
