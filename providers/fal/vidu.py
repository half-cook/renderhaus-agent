"""Vidu Q4 endpoint contracts, checked against fal's public schema 2026-10-08.

https://fal.ai/models/fal-ai/vidu/q4/image-to-video/api
https://fal.ai/models/fal-ai/vidu/q4/reference-to-video/api
Hosted service terms: https://fal.ai/legal/terms-of-service
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from providers.contracts import ArgumentRule


TOOL_ENDPOINTS = {
    "vidu_q4_i2v": "fal-ai/vidu/q4/image-to-video",
    "vidu_q4_r2v": "fal-ai/vidu/q4/reference-to-video",
}
GENERATING_TOOLS = tuple(TOOL_ENDPOINTS)
RESOLUTIONS = ("540p", "720p", "1080p", "2K", "4K")
ASPECT_RATIOS = ("16:9", "9:16", "4:3", "3:4", "1:1")
TRAINING_METADATA = {
    "training_eligible": False,
    "weights_license": "review-required",
    "hosted_terms_url": "https://fal.ai/legal/terms-of-service",
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


ENDPOINTS = {
    endpoint_id: Endpoint(endpoint_id, tool) for tool, endpoint_id in TOOL_ENDPOINTS.items()
}
_DEFAULTS = {"duration": 5, "resolution": "720p", "enable_safety_checker": True}
DEFAULTS = {
    "vidu_q4_i2v": {**_DEFAULTS, "prompt": ""},
    "vidu_q4_r2v": {**_DEFAULTS, "aspect_ratio": "16:9", "audio": False},
}
_COMMON_RULES = {
    "duration": ArgumentRule(minimum=3, maximum=16),
    "resolution": ArgumentRule(choices=RESOLUTIONS),
}
ARGUMENT_RULES = {
    "vidu_q4_i2v": {
        **_COMMON_RULES,
        "prompt": ArgumentRule(
            pattern=r"[\s\S]{0,5000}", pattern_hint="Must contain at most 5000 characters"
        ),
    },
    "vidu_q4_r2v": {
        **_COMMON_RULES,
        "aspect_ratio": ArgumentRule(choices=ASPECT_RATIOS),
        "prompt": ArgumentRule(
            pattern=r"[\s\S]{1,5000}", pattern_hint="Must contain 1 to 5000 characters"
        ),
    },
}
FIELD_DESCRIPTIONS = {
    "image_url": "Public URL or base64 data URI of the first frame. PNG, JPEG, or WebP up to 50 MB.",
    "reference_image_urls": "Optional list of up to 12 reference images. Public URLs or base64 data URIs of PNG, JPEG, or WebP images.",
    "reference_audio_urls": "Optional list of up to 3 MP3 reference voice clips. Each clip is 3 to 12 seconds and at most 50 MB. Use public URLs or base64 data URIs.",
    "audio": "Generate dialogue and sound effects when true. Defaults to false, which produces silent video.",
    "enable_safety_checker": "Defaults to true. Authorized callers may set false to request relaxed screening.",
    "seed": "Optional unrestricted integer seed. Omit it to use a random seed.",
}


def endpoint_for(tool: str, arguments: dict[str, Any]) -> Endpoint:
    if tool not in TOOL_ENDPOINTS:
        raise ValueError(f"Unknown Vidu Q4 tool: {tool}.")
    return ENDPOINTS[TOOL_ENDPOINTS[tool]]


def validate_arguments(tool: str, arguments: dict[str, Any]) -> None:
    if tool not in TOOL_ENDPOINTS:
        return
    for field, maximum in (("reference_image_urls", 12), ("reference_audio_urls", 3)):
        if field in arguments and len(arguments[field]) > maximum:
            raise ValueError(f"{field} accepts at most {maximum} references.")
    for field in ("image_url", "reference_image_urls", "reference_audio_urls"):
        if field not in arguments:
            continue
        values = arguments[field] if field.endswith("_urls") else [arguments[field]]
        for url in values:
            parsed = urlsplit(url)
            if not (
                (parsed.scheme in {"http", "https"} and parsed.netloc) or url.startswith("data:")
            ):
                raise ValueError(f"{field} requires a public HTTP(S) URL or data URI.")


def request_body(tool: str, arguments: dict[str, Any]) -> tuple[Endpoint, dict[str, Any]]:
    endpoint = endpoint_for(tool, arguments)
    body = {
        **DEFAULTS[tool],
        **{key: value for key, value in arguments.items() if value is not None},
    }
    return endpoint, body
