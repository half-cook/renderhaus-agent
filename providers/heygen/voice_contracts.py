"""Instant Voice contracts verified against official HeyGen docs on 2026-10-09.

https://developers.heygen.com/docs/voices/heygen-voice-instant-clone
https://developers.heygen.com/docs/voices/heygen-voice-speech
Non-promo prices and model-specific US account availability remain UNVERIFIED.
"""
from __future__ import annotations

import os
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from providers.heygen.contracts import TRAINING_METADATA, validate_media_reference

DEFAULT_MODEL = "heygen-voice-1"
VOICE_TOOLS = {"voice_clone", "voice_tts", "get_voice_status"}
LANGUAGES = frozenset("ar be bg ca cs da de el en es fa fi fr he hi hr hu id it ja ko mk ms nl pl pt ro ru sk sl sr sv ta th tl tr uk vi zh".split())
TRAINING_STATEMENT = (
    "HeyGen terms permit training on uploaded content; a Voice-specific no-training guarantee is UNVERIFIED. "
    "Outputs are not training eligible."
)
FIELD_DESCRIPTIONS = {
    "reference_audio_url": "One authorized public HTTPS MP3, WAV or OGG recording. It will be uploaded to HeyGen on future live activation. No upload occurs in dry-run.",
    "reference_duration_seconds": "Measured positive recording duration. Only the first 180 seconds are used, even for longer recordings.",
    "reference_size_bytes": "Measured file size, 1 through 104857600 bytes (100 MiB). URL fetch must complete in 30 seconds on HeyGen.",
    "reference_format": "Allowed values: mp3, wav, ogg. This adapter supports URL input only.",
    "name": "Instant voice display name, 1-64 nonblank characters.",
    "mode": "Only instant is supported. Professional clones are out of scope and rejected.",
    "subjects": "Name the real voice owner. Recorded permission must cover voice cloning, upload processing and vendor data use.",
    "consent_confirmed": "Required boolean true for recorded voice-owner consent. Spending approval does not replace consent.",
    "consent_record_id": "Opaque recorded-consent identifier, never a credential or signed URL.",
    "account_id": "Authenticated Studio user_id from read_studio_context. Must match the host account; voices cannot cross accounts.",
    "workspace_id": "Current Studio workspace_id. Must match the host workspace.",
    "project_id": "Current Studio project_id. Clone handles belong to this project only.",
    "voice_id": "Saved project-owned instant clone id. Dry handles stay dry after flag changes. Never use a catalog or global voice id.",
    "text": "1-5000 nonblank plain-text characters. Instant voices reject SSML and professional prosody controls.",
    "language": "Supported HeyGen base language or regional tag, such as en, en-US or fr-CA. Regional tags do not choose an accent.",
    "model": "heygen-voice-1 is verified. Unknown models are UNVERIFIED preview-only, with unknown estimates.",
    "expressiveness_boost": "Instant voice expression, 0.0 through 1.0; API default 1.0.",
    "similarity": "Allowed values: medium, high, extra_high, max. API default extra_high.",
    "remove_background_noise": "Clean the recording before instant cloning; default true.",
}


def configured_model(arguments: dict | None = None) -> str:
    value = (arguments or {}).get("model") or os.getenv("HEYGEN_VOICE_MODEL", DEFAULT_MODEL)
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", value):
        raise ValueError("Invalid HeyGen Voice model identifier.")
    return value


def live_blocker(arguments: dict | None = None) -> str:
    if configured_model(arguments) != DEFAULT_MODEL:
        return "UNVERIFIED HeyGen Voice model; estimate unknown and live use blocked."
    return ("HeyGen Voice is dry-run-only. Non-promo TTS and clone prices, model-specific US availability "
            "and permission for comparative A/B use are UNVERIFIED; live use blocked.")


def internal_gate(user_id: str | None) -> bool:
    users = {value.strip() for value in os.getenv("HEYGEN_VOICE_AB_USERS", "").split(",") if value.strip()}
    return os.getenv("HEYGEN_VOICE_AB_GATE", "off") == "internal" and bool(user_id and user_id in users)


def needs_text_normalisation(text: str) -> bool:
    """Conservatively flag digits and common spoken shorthand without changing text."""
    return bool(re.search(r"\d|\b(?:Dr|Mr|Mrs|Ms|Prof|St)\.|\b(?:ASAP|CEO|CFO|ETA|FAQ|GB|MB|kg|km|mph)\b", text, re.I))


class Scope(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False, hide_input_in_errors=True)
    account_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,255}$")
    workspace_id: str = Field(pattern=r"^[A-Za-z0-9_:-]{1,255}$")
    project_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,255}$")


class CloneRequest(Scope):
    reference_audio_url: str = Field(max_length=16384)
    reference_duration_seconds: float = Field(gt=0)
    reference_size_bytes: int = Field(ge=1, le=100 * 1024 * 1024)
    reference_format: Literal["mp3", "wav", "ogg"]
    name: str = Field(min_length=1, max_length=64)
    subjects: str = Field(min_length=1, max_length=12000)
    consent_confirmed: bool
    consent_record_id: str = Field(pattern=r"^[A-Za-z0-9_:.-]{1,255}$")
    mode: str = "instant"
    language: str | None = None
    similarity: Literal["medium", "high", "extra_high", "max"] = "extra_high"
    remove_background_noise: bool = True
    model: str | None = None

    @model_validator(mode="after")
    def instant_with_consent(self) -> CloneRequest:
        if self.mode != "instant":
            raise ValueError("Instant mode only; professional voice cloning is out of scope.")
        if self.consent_confirmed is not True or not self.subjects.strip():
            raise ValueError("Name the voice owner and record explicit consent_confirmed=true.")
        if not self.name.strip():
            raise ValueError("Voice name must contain nonblank text.")
        validate_media_reference(self.reference_audio_url, allow_asset=False)
        if self.language is not None:
            validate_language(self.language)
        self.model = configured_model({"model": self.model})
        return self

    @property
    def used_reference_seconds(self) -> float:
        return min(180.0, self.reference_duration_seconds)


class PollRequest(Scope):
    voice_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,255}$")


class TTSRequest(PollRequest):
    text: str = Field(min_length=1, max_length=5000)
    language: str
    model: str | None = None
    expressiveness_boost: float = Field(default=1.0, ge=0, le=1)

    @model_validator(mode="after")
    def plain_instant_text(self) -> TTSRequest:
        if not self.text.strip() or re.search(r"<[^>]*>", self.text):
            raise ValueError("Instant speech requires nonblank plain text; SSML is unsupported.")
        validate_language(self.language)
        self.model = configured_model({"model": self.model})
        return self


def validate_language(language: str) -> None:
    if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*", language) or language.split("-", 1)[0].lower() not in LANGUAGES:
        raise ValueError("Unsupported HeyGen Voice language.")


def request_for(tool: str, arguments: dict) -> Scope:
    classes = {"voice_clone": CloneRequest, "voice_tts": TTSRequest, "get_voice_status": PollRequest}
    return classes[tool].model_validate(arguments)


def clone_body(request: CloneRequest) -> dict:
    body = {"mode": "instant", "name": request.name,
            "audio": [{"type": "url", "url": request.reference_audio_url}],
            "similarity": request.similarity, "remove_background_noise": request.remove_background_noise}
    if request.language:
        body["language"] = request.language
    return body


def tts_body(request: TTSRequest) -> dict:
    return {"model": request.model, "voice_id": request.voice_id, "text": request.text,
            "language": request.language, "expressiveness_boost": request.expressiveness_boost}


PROVENANCE = {**TRAINING_METADATA, "model": DEFAULT_MODEL, "consent_required": True}
