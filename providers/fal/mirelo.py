"""Mirelo SFX 1.6 hosted commercial API, verified 2026-10-09.

https://fal.ai/models/mirelo-ai/sfx1.6/video-to-video/api
https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=mirelo-ai/sfx1.6/video-to-video
https://fal.ai/models/mirelo-ai/sfx1.6/video-to-video
https://fal.ai/legal/terms-of-service
No weights or upstream code are included. Multi-sample billing is UNVERIFIED.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from providers.contracts import ArgumentRule
from providers.runway.contracts import validate_https_url


ENDPOINT_ID = "mirelo-ai/sfx1.6/video-to-video"
GENERATING_TOOLS = ("mirelo_v2a",)
TOOL_ENDPOINTS = {"mirelo_v2a": ENDPOINT_ID}
TRAINING_METADATA = {
    "training_eligible": False,
    "weights_license": "closed-weights",
    "license": "service-terms",
    "license_source": "https://fal.ai/models/mirelo-ai/sfx1.6/video-to-video",
    "hosted_terms_url": "https://fal.ai/legal/terms-of-service",
}
ARGUMENT_RULES = {"mirelo_v2a": {
    "duration": ArgumentRule(minimum=1, maximum=60),
    "num_samples": ArgumentRule(minimum=1, maximum=4),
    "seed": ArgumentRule(minimum=-1, maximum=18446744073709552000),
}}
FIELD_DESCRIPTIONS = {
    "video_url": "Public HTTPS URL or renderhaus-asset:// version handle of a silent or edited video. Resolve authorized Studio handles before live submission. Input rights and required likeness/voice consents must be held.",
    "text_prompt": "Optional sound description to guide picture-synchronized foley; describe sounds, not visual changes.",
    "duration": "Generated SFX seconds, 1-60. Above 10 uses sliding-window generation. Match the measured clip duration; no automatic duration detection.",
    "num_samples": "Variations, 1-4. Renderhaus defaults to 1; vendor default is 2. Samples 2-4 are dry-run-only until their billing is verified; estimate unknown.",
    "seed": "Optional integer seed. -1 or null selects random generation.",
}


@dataclass(frozen=True)
class Endpoint:
    id: str = ENDPOINT_ID
    model: str = ENDPOINT_ID


ENDPOINTS = {ENDPOINT_ID: Endpoint()}


class MireloRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False, hide_input_in_errors=True)

    video_url: str
    text_prompt: str | None = None
    duration: float = Field(default=10, ge=1, le=60)
    num_samples: int = Field(default=1, ge=1, le=4)
    seed: int | None = Field(default=None, ge=-1, le=18446744073709552000)

    @model_validator(mode="after")
    def valid(self):
        if not re.fullmatch(r"renderhaus-asset://[A-Za-z0-9_-]+", self.video_url):
            validate_https_url(self.video_url, "video_url")
        return self


def request_for(arguments: dict) -> MireloRequest:
    try:
        return MireloRequest.model_validate(arguments)
    except ValidationError:
        raise ValueError("Invalid Mirelo request. Require public HTTPS video_url, duration 1-60, num_samples 1-4 and an optional integer seed >= -1.") from None


def validate_arguments(tool: str, arguments: dict) -> None:
    if tool in GENERATING_TOOLS:
        request_for(arguments)


def request_body(tool: str, arguments: dict) -> tuple[Endpoint, dict]:
    request = request_for(arguments)
    return ENDPOINTS[TOOL_ENDPOINTS[tool]], request.model_dump(exclude_none=True)


def result_videos(result: dict) -> list[dict]:
    videos = result.get("video")
    if not isinstance(videos, list) or not videos:
        raise RuntimeError("Completed Mirelo result must contain a non-empty video list.")
    for video in videos:
        url = video.get("url") if isinstance(video, dict) else None
        if not isinstance(url, str):
            raise RuntimeError("Completed Mirelo result must contain HTTP(S) video URLs.")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise RuntimeError("Completed Mirelo result must contain HTTP(S) video URLs.")
    return videos
