"""Mirelo SFX 2.0 hosted commercial API, verified 2026-10-15.

https://fal.ai/models/mirelo-ai/sfx2.0/video-to-audio
https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=mirelo-ai/sfx2.0/video-to-audio
https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=mirelo-ai/sfx2.0/video-to-video
https://fal.ai/legal/terms-of-service
No weights or upstream code included. Legacy 1.6 multi-sample billing is UNVERIFIED.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from providers.contracts import ArgumentRule
from providers.runway.contracts import validate_https_url


ENDPOINT_ID = "mirelo-ai/sfx2.0/video-to-audio"
VIDEO_ENDPOINT_ID = "mirelo-ai/sfx2.0/video-to-video"
LEGACY_ENDPOINT_ID = "mirelo-ai/sfx1.6/video-to-video"
Model = Literal["mirelo-ai/sfx2.0/video-to-audio", "mirelo-ai/sfx2.0/video-to-video", "mirelo-ai/sfx1.6/video-to-video"]
AudioFormat = Literal["wav", "mp3", "aac", "flac"]
GENERATING_TOOLS = ("mirelo_v2a",)
TOOL_ENDPOINTS = {"mirelo_v2a": ENDPOINT_ID}
TRAINING_METADATA = {
    "training_eligible": False,
    "weights_license": "closed-weights",
    "license": "service-terms",
    "license_source": "https://fal.ai/models/" + ENDPOINT_ID,
    "hosted_terms_url": "https://fal.ai/legal/terms-of-service",
}
ARGUMENT_RULES = {"mirelo_v2a": {
    "model": ArgumentRule(choices=(ENDPOINT_ID, VIDEO_ENDPOINT_ID, LEGACY_ENDPOINT_ID)),
    "duration": ArgumentRule(minimum=1, maximum=600),
    "num_samples": ArgumentRule(minimum=1, maximum=4),
    "seed": ArgumentRule(minimum=-1, maximum=18446744073709552000),
    "upload_audio_format": ArgumentRule(choices=("wav", "mp3", "aac", "flac")),
    "upload_audio_bitrate_kbps": ArgumentRule(minimum=32, maximum=320),
}}
FIELD_DESCRIPTIONS = {
    "video_url": "Public HTTPS URL or renderhaus-asset:// version handle of a silent or edited video. Resolve authorized Studio handles before live submission. Input rights and required likeness/voice consents must be held.",
    "text_prompt": "Optional sound description to guide picture-synchronized foley; describe sounds, not visual changes.",
    "model": "Default SFX 2.0 video-to-audio; choose 2.0 video-to-video for a muxed MP4 or explicitly select 1.6 video-to-video for A/B. Never silently fall back.",
    "duration": "Measured output seconds, 1-600 for 2.0 or 1-60 for 1.6. Clamped to video length; above 10 uses windows. No automatic duration detection.",
    "num_samples": "Variations, 1-4. Renderhaus defaults to 1; vendor default is 2. SFX 2.0 bills total output seconds across samples. Legacy 1.6 samples 2-4 stay dry-run-only with unknown cost.",
    "seed": "Optional integer seed. -1 or null selects random generation.",
    "preserve_speech": "SFX 2.0 only. Defaults true to preserve dialogue. False suppresses speech and generates effects only. Unsupported on 1.6.",
    "negative_prompt": "SFX 2.0 only. Optional sounds to exclude, up to 1000 characters.",
    "upload_audio_format": "SFX 2.0 video-to-audio only. Defaults wav; mp3, aac and flac also supported.",
    "upload_audio_bitrate_kbps": "Audio-only lossy encoding. MP3 uses a documented CBR value from 32-320; AAC accepts 32-256. Omit for wav/flac.",
}


@dataclass(frozen=True)
class Endpoint:
    id: str
    output_kind: Literal["audio", "video"]
    max_duration: int

    @property
    def model(self) -> str:
        return self.id


ENDPOINTS = {endpoint.id: endpoint for endpoint in (
    Endpoint(ENDPOINT_ID, "audio", 600),
    Endpoint(VIDEO_ENDPOINT_ID, "video", 600),
    Endpoint(LEGACY_ENDPOINT_ID, "video", 60),
)}


class MireloRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False, hide_input_in_errors=True)

    video_url: str
    model: Model = ENDPOINT_ID
    text_prompt: str | None = Field(default=None, max_length=2000)
    duration: float = Field(default=10, ge=1, le=600)
    num_samples: int = Field(default=1, ge=1, le=4)
    seed: int | None = Field(default=None, ge=-1, le=18446744073709552000)
    negative_prompt: str | None = Field(default=None, max_length=1000)
    preserve_speech: bool = True
    upload_audio_format: AudioFormat = "wav"
    upload_audio_bitrate_kbps: int | None = Field(default=None, ge=32, le=320)

    @model_validator(mode="after")
    def valid(self):
        if not re.fullmatch(r"renderhaus-asset://[A-Za-z0-9_-]+", self.video_url):
            validate_https_url(self.video_url, "video_url")
        endpoint = ENDPOINTS[self.model]
        if self.duration > endpoint.max_duration:
            raise ValueError("Duration exceeds the selected version limit.")
        if self.model == LEGACY_ENDPOINT_ID and self.model_fields_set & {
            "preserve_speech", "negative_prompt", "upload_audio_format", "upload_audio_bitrate_kbps",
        }:
            raise ValueError("SFX 1.6 does not support SFX 2.0 controls.")
        if endpoint.output_kind != "audio" and self.model_fields_set & {"upload_audio_format", "upload_audio_bitrate_kbps"}:
            raise ValueError("Audio encoding controls require the audio endpoint.")
        if self.upload_audio_bitrate_kbps is not None:
            if self.upload_audio_format in {"wav", "flac"}:
                raise ValueError("Lossless formats do not accept bitrate.")
            if self.upload_audio_format == "aac" and self.upload_audio_bitrate_kbps > 256:
                raise ValueError("AAC bitrate exceeds 256.")
            if self.upload_audio_format == "mp3" and self.upload_audio_bitrate_kbps not in {
                32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320,
            }:
                raise ValueError("Unsupported MP3 CBR bitrate.")
        return self


def request_for(arguments: dict) -> MireloRequest:
    try:
        return MireloRequest.model_validate(arguments)
    except ValidationError:
        raise ValueError("Invalid Mirelo request. Require authorized HTTPS video_url, a verified model, duration 1-600 for 2.0 or 1-60 for 1.6, num_samples 1-4 and version-compatible speech/audio controls.") from None


def validate_arguments(tool: str, arguments: dict) -> None:
    if tool in GENERATING_TOOLS:
        request_for(arguments)


def request_body(tool: str, arguments: dict) -> tuple[Endpoint, dict]:
    request = request_for(arguments)
    endpoint = ENDPOINTS[request.model]
    excluded = {"model"}
    if endpoint.output_kind != "audio":
        excluded.update({"upload_audio_format", "upload_audio_bitrate_kbps"})
    if endpoint.id == LEGACY_ENDPOINT_ID:
        excluded.update({"preserve_speech", "negative_prompt"})
    return endpoint, request.model_dump(exclude=excluded, exclude_none=True)


def result_audio(result: dict) -> list[dict]:
    return _result_files(result, "audio")


def result_videos(result: dict) -> list[dict]:
    return _result_files(result, "video")


def _result_files(result: dict, kind: str) -> list[dict]:
    videos = result.get(kind)
    if not isinstance(videos, list) or not videos:
        raise RuntimeError(f"Completed Mirelo result must contain a non-empty {kind} list.")
    for video in videos:
        url = video.get("url") if isinstance(video, dict) else None
        if not isinstance(url, str):
            raise RuntimeError(f"Completed Mirelo result must contain HTTP(S) {kind} URLs.")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError(f"Completed Mirelo result must contain HTTP(S) {kind} URLs.")
    return videos


def audio_suffix(audio: dict) -> str:
    suffix = urlsplit(audio["url"]).path.rsplit(".", 1)[-1].lower()
    mime = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/mpeg": "mp3", "audio/mp3": "mp3",
            "audio/aac": "aac", "audio/flac": "flac", "audio/x-flac": "flac"}
    format = mime.get(str(audio.get("content_type")), suffix)
    if format not in {"wav", "mp3", "aac", "flac"}:
        raise RuntimeError("Completed Mirelo audio has no supported format.")
    return "." + format
