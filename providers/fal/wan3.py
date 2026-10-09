"""Wan 3.0 contracts, verified against fal OpenAPI on 2026-10-09.

https://fal.ai/models/alibaba/wan-3.0/text-to-video/api
https://fal.ai/models/alibaba/wan-3.0/image-to-video/api
https://fal.ai/models/alibaba/wan-3.0/reference-to-video/api
Hosted commercial API terms: https://fal.ai/legal/terms-of-service
Closed weights. Public terms do not clearly permit output training use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from providers.contracts import ArgumentRule


TOOL_ENDPOINTS = {
    "generate_wan3_t2v": "alibaba/wan-3.0/text-to-video",
    "generate_wan3_i2v": "alibaba/wan-3.0/image-to-video",
    "generate_wan3_r2v": "alibaba/wan-3.0/reference-to-video",
}
GENERATING_TOOLS = tuple(TOOL_ENDPOINTS)
RESOLUTIONS = ("480p", "720p", "1080p")
ASPECT_RATIOS = ("adaptive", "16:9", "4:3", "1:1", "3:4", "9:16")
TRAINING_METADATA = {
    "training_eligible": False,
    "weights_license": "closed-weights",
    "license": "service-terms",
    "hosted_terms_url": "https://fal.ai/legal/terms-of-service",
}
LOCAL_FIELDS = frozenset({
    "real_face_refs", "likeness_consent", "reference_video_durations",
    "reference_video_fps", "reference_audio_durations",
})


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
_COMMON_DEFAULTS = {
    "resolution": "1080p", "aspect_ratio": "adaptive", "duration": 5, "audio": True,
    "enable_prompt_expansion": True, "enable_thinking": False, "enable_safety_checker": True,
}
DEFAULTS = {tool: dict(_COMMON_DEFAULTS) for tool in TOOL_ENDPOINTS}
_COMMON_RULES = {
    "duration": ArgumentRule(minimum=2, maximum=30),
    "seed": ArgumentRule(minimum=0, maximum=2147483647),
    "resolution": ArgumentRule(choices=RESOLUTIONS),
    "aspect_ratio": ArgumentRule(choices=ASPECT_RATIOS),
    "prompt": ArgumentRule(pattern=r"[\s\S]{0,20000}", pattern_hint="At most 20000 characters"),
}
ARGUMENT_RULES = {tool: dict(_COMMON_RULES) for tool in TOOL_ENDPOINTS}
FIELD_DESCRIPTIONS = {
    "seed": "Optional integer from 0 to 2147483647. Omit for a random seed.",
    "duration": "Output seconds from 2 to 30, default 5. Null requests smart duration in dry-run only; live smart duration is blocked until billing reconciliation exists.",
    "start_image_url": "Required first frame, as an HTTP(S) URL or base64 data URI.",
    "end_image_url": "Optional last frame, as an HTTP(S) URL or base64 data URI.",
    "reference_image_urls": "Up to 10 reference image URLs or base64 data URIs.",
    "reference_video_urls": "Up to 5 video references totaling at most 15 seconds, each at least 16 fps. Input video seconds are billed in addition to output seconds.",
    "reference_audio_urls": "Up to 5 audio references totaling at most 15 seconds.",
    "reference_video_durations": "Locally measured seconds for each reference video, in the same order. Required when video references exist; never sent to fal.",
    "reference_video_fps": "Locally measured frame rate for each reference video, in the same order. Every reference must be at least 16 fps; never sent to fal.",
    "reference_audio_durations": "Locally measured seconds for each reference audio clip, in the same order. Required when audio references exist; never sent to fal.",
    "real_face_refs": "True when references contain a real person's likeness. Requires likeness_consent=true.",
    "likeness_consent": "Acknowledge permission to use every real person's referenced likeness. Local policy field; never sent to fal.",
    "file_url": "Document URL or data URI. Requires enable_thinking=true.",
    "web_url": "Public HTTP(S) webpage that requires no login. Requires enable_thinking=true.",
    "audio": "Include native generated audio. Defaults to true.",
    "enable_safety_checker": "Defaults to true. Disabling requires vendor account authorization.",
}


def endpoint_for(tool: str, arguments: dict[str, Any]) -> Endpoint:
    if tool not in TOOL_ENDPOINTS:
        raise ValueError(f"Unknown Wan 3 tool: {tool}.")
    return ENDPOINTS[TOOL_ENDPOINTS[tool]]


def validate_arguments(tool: str, arguments: dict[str, Any]) -> None:
    if tool not in TOOL_ENDPOINTS:
        return
    if arguments.get("real_face_refs") and not arguments.get("likeness_consent"):
        raise ValueError("Real-person references require likeness_consent=true.")
    for field, maximum in (("reference_image_urls", 10), ("reference_video_urls", 5),
                           ("reference_audio_urls", 5)):
        if len(arguments.get(field) or []) > maximum:
            raise ValueError(f"{field} accepts at most {maximum} references.")
    for field in ("start_image_url", "end_image_url", "reference_image_urls",
                  "reference_video_urls", "reference_audio_urls", "file_url", "web_url"):
        values = arguments.get(field)
        if values is None:
            continue
        values = values if isinstance(values, list) else [values]
        for url in values:
            parsed = urlsplit(url)
            if not ((parsed.scheme in {"http", "https"} and parsed.netloc)
                    or (field != "web_url" and url.startswith("data:"))):
                raise ValueError(f"{field} requires an HTTP(S) URL" +
                                 (" or data URI." if field != "web_url" else "."))
    if (arguments.get("file_url") or arguments.get("web_url")) and not arguments.get("enable_thinking"):
        raise ValueError("file_url and web_url require enable_thinking=true.")
    for kind in ("video", "audio"):
        urls = arguments.get(f"reference_{kind}_urls") or []
        field = f"reference_{kind}_durations"
        durations = arguments.get(field) or []
        if len(durations) != len(urls):
            raise ValueError(f"{field} must have one measured duration per reference URL.")
        if any(value <= 0 for value in durations):
            raise ValueError(f"{field} values must be greater than zero.")
        if sum(durations) > 15:
            raise ValueError(f"{field} total must be at most 15 seconds.")
    urls = arguments.get("reference_video_urls") or []
    fps = arguments.get("reference_video_fps") or []
    if len(fps) != len(urls) or any(value < 16 for value in fps):
        raise ValueError("reference_video_fps requires one measured value of at least 16 per video.")


def request_body(tool: str, arguments: dict[str, Any]) -> tuple[Endpoint, dict[str, Any]]:
    endpoint = endpoint_for(tool, arguments)
    body = {**DEFAULTS[tool], **{key: value for key, value in arguments.items()
                               if key not in LOCAL_FIELDS and (value is not None or key == "duration")}}
    return endpoint, body
