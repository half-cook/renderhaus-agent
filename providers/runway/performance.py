"""Act-Two request contract. Official Runway SDK/OpenAPI and pricing read 2026-10-09.

https://github.com/runwayml/sdk-python/blob/main/src/runwayml/types/character_performance_create_params.py
https://docs.dev.runwayml.com/guides/pricing/
https://runway.com/terms-of-use
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from providers.runway.contracts import I2V_RATIOS, validate_media_uri


TRAINING_METADATA = {"training_eligible": False, "weights_license": "closed-weights",
                     "license": "service-terms", "license_source": "https://runway.com/terms-of-use"}


class ActTwoRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False, hide_input_in_errors=True)

    character_uri: str
    performance_uri: str
    performance_duration_seconds: float = Field(ge=3, le=30)
    subjects: str = Field(min_length=1, max_length=1000)
    consent_confirmed: bool
    character_type: Literal["image", "video"] = "image"
    ratio: str = "1280:720"
    body_control: bool = True
    expression_intensity: int = Field(default=3, ge=1, le=5)
    seed: int | None = Field(default=None, ge=0, le=4294967295)
    source_duration_seconds: float | None = Field(default=None, ge=3)
    performance_start_seconds: float = Field(default=0, ge=0)
    boundary_kind: Literal["shot", "silence"] | None = None

    @model_validator(mode="after")
    def valid(self):
        validate_media_uri(self.character_uri, "character_uri", self.character_type)
        validate_media_uri(self.performance_uri, "performance_uri", "video")
        if self.ratio not in I2V_RATIOS:
            raise ValueError("Act-Two ratio must be a documented output dimension.")
        if self.character_type == "video" and self.body_control:
            raise ValueError("Gesture transfer requires a character image; use body_control=false for character video.")
        if not self.subjects.strip() or self.consent_confirmed is not True:
            raise ValueError("Identify every face, voice and body subject and acknowledge consent_confirmed=true.")
        if self.source_duration_seconds is not None:
            if self.boundary_kind is None:
                raise ValueError("Source segments require boundary_kind=shot or silence.")
            if self.performance_start_seconds + self.performance_duration_seconds > self.source_duration_seconds:
                raise ValueError("Performance segment must fit inside the measured source duration.")
            if not self.performance_uri.startswith("https://"):
                raise ValueError("Segment preprocessing requires a hosted HTTPS source.")
        elif self.performance_start_seconds or self.boundary_kind is not None:
            raise ValueError("Segment controls require source_duration_seconds.")
        return self

    def body(self, performance_uri: str | None = None) -> dict:
        result = {"model": "act_two", "character": {"type": self.character_type, "uri": self.character_uri},
                  "reference": {"type": "video", "uri": performance_uri or self.performance_uri},
                  "ratio": self.ratio, "bodyControl": self.body_control,
                  "expressionIntensity": self.expression_intensity}
        if self.seed is not None:
            result["seed"] = self.seed
        return result


def request_for(arguments: dict) -> ActTwoRequest:
    try:
        return ActTwoRequest.model_validate(arguments)
    except ValidationError:
        raise ValueError("Invalid Act-Two request. Require consent, media URIs, a 3-30s performance and documented controls.") from None
