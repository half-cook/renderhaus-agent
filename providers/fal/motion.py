"""Kling 3 Pro Motion Control via fal. Schema, price and commercial label read 2026-10-09.

https://fal.ai/models/fal-ai/kling-video/v3/pro/motion-control/api
https://fal.ai/models/fal-ai/kling-video/v3/pro/motion-control
https://fal.ai/legal/terms-of-service
Direct Kling Motion Control is UNVERIFIED and is not exposed by this adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from providers.runway.contracts import validate_https_url


ENDPOINT_ID = "fal-ai/kling-video/v3/pro/motion-control"
TOOL_ENDPOINTS = {"kling_motion_control": ENDPOINT_ID}
GENERATING_TOOLS = tuple(TOOL_ENDPOINTS)
TRAINING_METADATA = {"training_eligible": False, "weights_license": "closed-weights",
                     "license": "service-terms", "license_source": "https://fal.ai/legal/terms-of-service",
                     "hosted_terms_url": "https://fal.ai/legal/terms-of-service"}
FIELD_DESCRIPTIONS = {"performance_duration_seconds": "Measured driving clip duration. 3-30 seconds for video orientation; 3-10 for image orientation. Not a vendor duration control.",
                      "subjects": "Identify every real face, voice and body in the inputs.",
                      "consent_confirmed": "Must be true. Caller acknowledges rights and consent for all depicted likenesses, performances and voices."}


@dataclass(frozen=True)
class Endpoint:
    id: str = ENDPOINT_ID
    model: str = ENDPOINT_ID


ENDPOINTS = {ENDPOINT_ID: Endpoint()}


class MotionRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False, hide_input_in_errors=True)

    image_url: str
    video_url: str
    performance_duration_seconds: float = Field(ge=3, le=30)
    subjects: str = Field(min_length=1, max_length=1000)
    consent_confirmed: bool
    character_orientation: Literal["image", "video"] = "video"
    keep_original_sound: bool = True
    prompt: str = Field(default="", max_length=2500)

    @model_validator(mode="after")
    def valid(self):
        validate_https_url(self.image_url, "image_url")
        validate_https_url(self.video_url, "video_url")
        if self.character_orientation == "image" and self.performance_duration_seconds > 10:
            raise ValueError("Image orientation permits at most 10 seconds; video orientation permits 30.")
        if not self.subjects.strip() or self.consent_confirmed is not True:
            raise ValueError("Identify every face, voice and body subject and acknowledge consent_confirmed=true.")
        return self


def request_for(arguments: dict) -> MotionRequest:
    try:
        return MotionRequest.model_validate(arguments)
    except ValidationError:
        raise ValueError("Invalid Kling Motion Control request. Require consent, HTTPS media and a 3-30s driving clip (image orientation max 10s).") from None


def validate_arguments(tool: str, arguments: dict) -> None:
    if tool in GENERATING_TOOLS:
        request_for(arguments)


def request_body(tool: str, arguments: dict) -> tuple[Endpoint, dict]:
    request = request_for(arguments)
    return ENDPOINTS[TOOL_ENDPOINTS[tool]], request.model_dump(exclude={"subjects", "consent_confirmed", "performance_duration_seconds"})
