"""Official HeyGen v3 Avatar V contracts, checked 2026-10-09.

https://developers.heygen.com/avatar-v
https://developers.heygen.com/reference/create-video
https://developers.heygen.com/docs/avatar-consent
https://developers.heygen.com/docs/usage-limits
"""

from __future__ import annotations

import ipaddress
import os
import re
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator


DEFAULT_MODEL = "avatar_v"
GENERATING_TOOLS = ("create_avatar_video",)
TERMS_URL = "https://www.heygen.com/terms"
TRAINING_METADATA = {
    "training_eligible": False,
    "weights_license": "closed-weights",
    "license": "service-terms",
    "license_source": TERMS_URL,
    "hosted_terms_url": TERMS_URL,
}
FIELD_DESCRIPTIONS = {
    "avatar_id": "Existing HeyGen LOOK id, not an avatar group id. Live Avatar V requires a completed digital_twin look explicitly listing avatar_v in supported_api_engines and accepted consent on its group.",
    "duration_seconds": "Measured audio length or requested script-video length used for the cost estimate, not a vendor duration control. Maximum audio 600 seconds; script-video 1800 seconds. Actual duration is returned after completion.",
    "subjects": "Identify every real person whose likeness or voice is used. The record must cover all subjects, including a cloned voice.",
    "consent_confirmed": "Required boolean true confirming explicit permission for every supplied likeness and voice. Spending approval does not replace consent.",
    "consent_record_id": "Opaque id of the recorded source rights and consent. Do not supply a signed URL, credentials, or a consent video here.",
    "script": "1 to 5000 nonblank characters. Requires an authorized voice_id. Supply script or audio_url, never both.",
    "voice_id": "Existing authorized HeyGen voice id for script speech. Voice creation and cloning are outside this tool.",
    "audio_url": "Existing HTTPS speech audio or an authorized renderhaus-asset:// version handle, maximum 600 seconds. Replaces script plus voice_id.",
    "language": "Optional speech locale, for example fr-CA, sent as voice_settings.locale for script speech. It is not a translation operation.",
    "resolution": "Allowed values: 720p, 1080p. Avatar V 4K output is not verified.",
    "aspect_ratio": "Allowed values: 16:9, 9:16, 4:5, 5:4, 1:1, auto.",
    "motion_prompt": "Optional natural-language body motion and gesture direction for the eligible digital twin.",
    "model": "avatar_v is verified. Unsupported or unverified engines always produce a dry-run preview, even when HEYGEN_DRY_RUN=false.",
    "job_id": "Exact saved HeyGen handle returned by create_avatar_video. Polling never submits work. Dry handles remain dry after configuration changes.",
    "download": "Atomically save and validate a completed MP4. A queued job or a dry-run preview is not produced media.",
    "limit": "Page size: 1-50 for avatars, 1-100 for voices. Default 20.",
    "next_token": "Opaque next_token from the previous list response, sent as the official API token query parameter.",
}
ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,255}")
JOB_PATTERN = re.compile(r"heygen:(dry|live):[a-f0-9]{32}")


def configured_model(arguments: dict[str, Any] | None = None) -> str:
    model = (arguments or {}).get("model") or os.getenv("HEYGEN_MODEL") or DEFAULT_MODEL
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", model):
        raise ValueError("Invalid HeyGen engine identifier.")
    return model


def live_blocker(arguments: dict[str, Any] | None = None) -> str | None:
    if configured_model(arguments) != DEFAULT_MODEL:
        return "UNVERIFIED HeyGen engine; only dry-run previews are allowed."
    if os.getenv("HEYGEN_API_PLAN", "unknown") not in {"paid_self_serve", "enterprise"}:
        return "Live HeyGen generation requires a verified paid API plan; unknown and free plans are blocked."
    return None


def validate_id(value: str, field: str) -> str:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError(f"{field} must be an existing opaque HeyGen id.")
    return value


def validate_media_reference(value: str, *, allow_asset: bool = True) -> None:
    if allow_asset and isinstance(value, str) and re.fullmatch(r"renderhaus-asset://[A-Za-z0-9_-]+", value):
        return
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname and "." in parsed.hostname
                 and not parsed.username and not parsed.password and not parsed.fragment
                 and parsed.port in {None, 443} and not any(character.isspace() for character in value))
        if valid:
            try:
                valid = ipaddress.ip_address(parsed.hostname).is_global
            except ValueError:
                valid = parsed.hostname != "localhost" and not parsed.hostname.endswith(".localhost")
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("HeyGen media requires public HTTPS without credentials or fragments.")


def reference_for_metadata(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


class AvatarRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False, hide_input_in_errors=True)

    avatar_id: str
    duration_seconds: float = Field(gt=0, le=1800)
    subjects: str = Field(min_length=1, max_length=12000)
    consent_confirmed: bool
    consent_record_id: str = Field(pattern=r"^[A-Za-z0-9_:.-]{1,255}$")
    script: str | None = Field(default=None, min_length=1, max_length=5000)
    voice_id: str | None = None
    audio_url: str | None = Field(default=None, max_length=16384)
    language: str | None = Field(default=None, pattern=r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
    resolution: Literal["720p", "1080p"] = "720p"
    aspect_ratio: Literal["16:9", "9:16", "4:5", "5:4", "1:1", "auto"] = "16:9"
    motion_prompt: str | None = None
    model: str | None = None

    @model_validator(mode="after")
    def supported_request(self) -> AvatarRequest:
        validate_id(self.avatar_id, "avatar_id")
        if self.consent_confirmed is not True or not self.subjects.strip():
            raise ValueError("Identify every face and voice subject and confirm their explicit consent.")
        self.subjects = self.subjects.strip()
        if (self.script is None) == (self.audio_url is None):
            raise ValueError("Supply exactly one of script or audio_url.")
        if self.script is not None:
            if not self.script.strip():
                raise ValueError("script must contain nonblank text.")
            validate_id(self.voice_id, "voice_id")
        else:
            if self.voice_id is not None:
                raise ValueError("audio_url replaces script and voice_id.")
            validate_media_reference(self.audio_url)
            if self.duration_seconds > 600:
                raise ValueError("HeyGen supplied audio must be at most 600 seconds.")
        if self.motion_prompt is not None and not self.motion_prompt.strip():
            raise ValueError("motion_prompt must contain nonblank direction.")
        self.model = configured_model({"model": self.model})
        return self


class PollRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    job_id: str = Field(pattern=r"^heygen:(dry|live):[a-f0-9]{32}$")
    download: bool = False


class PageRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    limit: int = Field(default=20, ge=1, le=100)
    next_token: str | None = Field(default=None, min_length=1, max_length=4096)


def request_for(arguments: dict[str, Any]) -> AvatarRequest:
    return AvatarRequest.model_validate(arguments)


def validate_arguments(tool: str, arguments: dict[str, Any]) -> None:
    if tool == "create_avatar_video":
        request_for(arguments)
    elif tool == "get_video_status":
        PollRequest.model_validate(arguments)
    elif tool in {"list_avatars", "list_voices"}:
        page = PageRequest.model_validate(arguments)
        if tool == "list_avatars" and page.limit > 50:
            raise ValueError("HeyGen avatar page limit must be at most 50.")
    else:
        raise ValueError("Unknown HeyGen tool.")


def request_body(request: AvatarRequest) -> dict[str, Any]:
    body = {"type": "avatar", "avatar_id": request.avatar_id, "engine": {"type": request.model},
            "resolution": request.resolution, "aspect_ratio": request.aspect_ratio, "output_format": "mp4"}
    if request.script is not None:
        body.update(script=request.script, voice_id=request.voice_id)
        if request.language:
            body["voice_settings"] = {"locale": request.language}
    else:
        body["audio_url"] = request.audio_url
    if request.motion_prompt:
        body["motion_prompt"] = request.motion_prompt
    return body
