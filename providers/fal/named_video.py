"""Named-only Pixelcut and PixVerse contracts verified from fal on 2026-10-10.

https://fal.ai/models/pixelcut/looping-video/api
https://fal.ai/models/pixverse/music-video/vibemv/api
https://fal.ai/legal/terms-of-service
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, get_args
from urllib.parse import urlsplit

from providers.contracts import ArgumentRule


PixelcutResolution = Literal["480p", "768p", "1080p"]
VibeResolution = Literal["720p", "1080p"]
VibeAspect = Literal["16:9", "9:16", "1:1", "4:3", "3:4"]
VibeStyle = Literal[
    "Custom", "Cinematic", "Lo-fi", "Dreamscape", "Woolen Felt", "Candy", "Golden Age",
    "Voxel", "Retro Game", "Claymation", "Woodland Tale", "Impressionism", "Decadence",
    "Futuristic", "Chromatic Clash", "Holiday",
]
MusicStyle = Literal[
    "Pop", "Rock", "Hip Hop", "R&B", "Jazz", "Reggae", "Country", "Folk", "Electronic",
    "Classical", "Soul", "Funk", "Metal", "Ambient", "Others",
]
TOOL_ENDPOINTS = {
    "pixelcut_looping_video": "pixelcut/looping-video",
    "pixverse_vibemv": "pixverse/music-video/vibemv",
}
GENERATING_TOOLS = tuple(TOOL_ENDPOINTS)
READ_DATE = "2026-10-10"
TRAINING_METADATA = {
    "training_eligible": False,
    "weights_license": "closed-weights",
    "license": "service-terms",
    "hosted_terms_url": "https://fal.ai/legal/terms-of-service",
}
LOCAL_FIELDS = {"audio_duration_seconds", "real_face_refs", "real_voice_refs", "likeness_consent"}
MEDIA_FIELDS = ("image_url", "audio_url", "style_image_url")
DEFAULTS = {
    "pixelcut_looping_video": {
        "prompt": "", "duration": 5, "resolution": "1080p", "motion": "subtle", "include_audio": False,
    },
    "pixverse_vibemv": {
        "style": "Cinematic", "aspect_ratio": "16:9", "resolution": "720p",
        "lip_sync_switch": False, "enable_safety_checker": True,
    },
}
ARGUMENT_RULES = {
    "pixelcut_looping_video": {
        "duration": ArgumentRule(minimum=5, maximum=15),
        "resolution": ArgumentRule(choices=("480p", "768p", "1080p")),
        "motion": ArgumentRule(choices=("subtle", "spin")),
        "prompt": ArgumentRule(pattern=r"[\s\S]{0,4000}", pattern_hint="At most 4000 characters"),
    },
    "pixverse_vibemv": {
        "audio_duration_seconds": ArgumentRule(minimum=10, maximum=360),
        "resolution": ArgumentRule(choices=("720p", "1080p")),
        "aspect_ratio": ArgumentRule(choices=("16:9", "9:16", "1:1", "4:3", "3:4")),
        "style": ArgumentRule(choices=get_args(VibeStyle)),
        "music_style": ArgumentRule(choices=get_args(MusicStyle)),
        "lyrics": ArgumentRule(pattern=r"[\s\S]{0,5000}", pattern_hint="At most 5000 characters"),
    },
}
FIELD_DESCRIPTIONS = {
    "image_url": "Authorized JPEG, PNG or WebP image URL, data URI or Studio asset handle. Pixelcut needs a product frame; VibeMV accepts an optional character reference.",
    "audio_url": "Authorized MP3 or WAV URL, data URI or Studio asset handle. Supply the actual measured audio_duration_seconds from 10 through 360.",
    "audio_duration_seconds": "Measured input audio seconds, 10-360. Local quote field, never sent to fal. Whole seconds rounded up for VibeMV billing. Do not invent measurements.",
    "style_image_url": "Style image URL, data URI or Studio asset handle. Requires style=Custom; Custom requires this reference.",
    "real_face_refs": "True when input references depict real people. Requires likeness_consent=true for every person.",
    "real_voice_refs": "True when input audio contains a real person's voice. Requires likeness_consent=true for every speaker or singer.",
    "likeness_consent": "Explicit permission for every real face or voice used in the inputs. Local acknowledgement, never sent to fal.",
    "include_audio": "Keep Pixelcut's generated audio when true. Default false. Motion and audio do not change its price.",
    "lip_sync_switch": "Enable VibeMV mouth motion matching the vocals. Default false; a character reference works best.",
    "enable_safety_checker": "Default true. Only vendor-authorized callers may request relaxed screening with false.",
}


@dataclass(frozen=True)
class Endpoint:
    id: str
    tool: str

    @property
    def model(self) -> str:
        return self.id

    @property
    def api_url(self) -> str:
        return f"https://fal.ai/models/{self.id}/api"


ENDPOINTS = {endpoint: Endpoint(endpoint, tool) for tool, endpoint in TOOL_ENDPOINTS.items()}


def validate_arguments(tool: str, arguments: dict[str, Any]) -> None:
    if tool not in TOOL_ENDPOINTS:
        return
    for field in MEDIA_FIELDS:
        if (value := arguments.get(field)) is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"{field} must be a media URL or Studio asset handle.")
        parsed = urlsplit(value)
        media_type = "audio" if field == "audio_url" else "image"
        if not ((parsed.scheme in {"https", "http"} and parsed.netloc)
                or value.startswith(f"data:{media_type}/")
                or (parsed.scheme == "renderhaus-asset" and parsed.netloc)):
            raise ValueError(f"{field} requires an HTTP(S) URL, {media_type} data URI or Studio asset handle.")
    if (arguments.get("real_face_refs") or arguments.get("real_voice_refs")) and arguments.get("likeness_consent") is not True:
        raise ValueError("Real face/voice inputs require explicit likeness_consent=true for every subject.")
    if tool == "pixverse_vibemv":
        custom = arguments.get("style", "Cinematic") == "Custom"
        if custom != bool(arguments.get("style_image_url")):
            raise ValueError("Custom style requires style_image_url; a style reference requires style=Custom.")


def require_resolved_references(body: dict[str, Any]) -> None:
    if any(str(body.get(field, "")).startswith("renderhaus-asset://") for field in MEDIA_FIELDS):
        raise ValueError("Studio asset handles must resolve to authorized HTTPS media before live named-video submission.")


def request_body(tool: str, arguments: dict[str, Any]) -> tuple[Endpoint, dict[str, Any]]:
    return ENDPOINTS[TOOL_ENDPOINTS[tool]], {
        **DEFAULTS[tool], **{key: value for key, value in arguments.items() if key not in LOCAL_FIELDS and value is not None},
    }
