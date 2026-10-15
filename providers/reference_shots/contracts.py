from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from providers.ffmpeg.sandbox import ID_PATTERN, validate_input_path


MAX_SECONDS = 600
MAX_SHOTS = 60
MAX_ARGUMENT_BYTES = 128 * 1024
SHA256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
ASSET_PATTERN = r"renderhaus-asset://[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}"
LabelText = Annotated[str, Field(min_length=1, max_length=1000)]
Seconds = Annotated[float, Field(ge=0, le=MAX_SECONDS)]
CameraMove = Literal['static', 'push', 'pull', 'pan', 'truck', 'track', 'dolly', 'tilt',
                     'zoom', 'crane', 'jib', 'orbit', 'handheld', 'mixed', 'unknown']


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class ShotLabel(ClosedModel):
    shot_id: Annotated[int, Field(ge=1, le=MAX_SHOTS)]
    shot_size: Annotated[str, Field(min_length=1, max_length=80)]
    category: Annotated[str, Field(min_length=1, max_length=80)]
    camera_move: CameraMove
    frame_description: LabelText
    rhythm_role: Annotated[str, Field(min_length=1, max_length=120)]

    @field_validator("shot_size", "category", "camera_move", "frame_description", "rhythm_role")
    @classmethod
    def readable_label(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Visual labels must contain readable text without control characters.")
        return value.strip()


class ShotLabels(ClosedModel):
    shots: Annotated[list[ShotLabel], Field(min_length=1, max_length=MAX_SHOTS)]

    @model_validator(mode="after")
    def unique_ids(self):
        if len({shot.shot_id for shot in self.shots}) != len(self.shots):
            raise ValueError("Visual labels must not repeat a shot_id.")
        return self


class MeasureParams(ClosedModel):
    pass


class ReportParams(ClosedModel):
    labels: Annotated[list[ShotLabel], Field(min_length=1, max_length=MAX_SHOTS)]
    labels_provenance: Literal["unverified", "simulated"] = "unverified"
    measurements_sha256: SHA256 | None = None


class Request(ClosedModel):
    op: Literal["measure", "report"]
    job_id: Annotated[str, Field(pattern=rf"^{ID_PATTERN}$", min_length=1, max_length=80)]
    input_path: Annotated[str, Field(min_length=1, max_length=1024)]
    params: dict | None = None


class PinnedFile(ClosedModel):
    path: Annotated[str, Field(min_length=1, max_length=1024)]
    sha256: SHA256
    bytes: Annotated[int, Field(gt=0, le=128 * 1024 * 1024)]


class Source(PinnedFile):
    duration_s: Annotated[float, Field(gt=0, le=MAX_SECONDS)]
    width: Annotated[int, Field(ge=2, le=4096)]
    height: Annotated[int, Field(ge=2, le=4096)]
    fps: Annotated[float, Field(gt=0, le=120)]
    decoded_frames: Annotated[int, Field(ge=1, le=72000)]


class MeasuredShot(ClosedModel):
    shot_id: Annotated[int, Field(ge=1, le=MAX_SHOTS)]
    start_s: Seconds
    end_s: Seconds
    duration_s: Annotated[float, Field(gt=0, le=MAX_SECONDS)]
    median_frame_difference: Annotated[float, Field(ge=0, le=1)] | None
    motion_frame_pairs: Annotated[int, Field(ge=0, le=72000)]
    frame_times_s: Annotated[list[Seconds], Field(min_length=2, max_length=2,
        description="Requested 15% and 85% positions inside the measured shot, not observed frame timestamps.")]
    sampled_frame_times_s: Annotated[list[Seconds], Field(min_length=2, max_length=2,
        description="Observed source frame timestamps for the actual paired sheet images.")]

    @model_validator(mode="after")
    def valid_interval(self):
        if (self.start_s >= self.end_s
                or not math.isclose(self.duration_s, self.end_s - self.start_s, abs_tol=1e-8)
                or any(not self.start_s < value < self.end_s for value in self.frame_times_s)):
            raise ValueError("Measured shots need increasing endpoints, exact deltas and interior keyframes.")
        if (self.motion_frame_pairs == 0) != (self.median_frame_difference is None):
            raise ValueError("Motion without consecutive frames must remain unknown.")
        expected = [self.start_s + self.duration_s * fraction for fraction in (.15, .85)]
        if any(not math.isclose(a, b, abs_tol=1e-8) for a, b in zip(self.frame_times_s, expected)):
            raise ValueError("Keyframes must be measured at 15% and 85% of each shot.")
        if any(not self.start_s - 1e-6 <= value < self.end_s for value in self.sampled_frame_times_s):
            raise ValueError("Observed keyframe timestamps must stay within their measured shot.")
        return self


class ThresholdResult(ClosedModel):
    threshold: Annotated[float, Field(ge=.1, le=.6)]
    scene_times_s: Annotated[list[Seconds], Field(max_length=MAX_SHOTS - 1)]


class ContactSheet(PinnedFile):
    shot_ids: Annotated[list[Annotated[int, Field(ge=1, le=MAX_SHOTS)]], Field(min_length=1, max_length=10)]


class Player(PinnedFile):
    kind: Literal["source", "proxy"]
    duration_s: Annotated[float, Field(gt=0, le=MAX_SECONDS)]
    width: Annotated[int, Field(ge=2, le=4096)]
    height: Annotated[int, Field(ge=2, le=4096)]


class Measurements(ClosedModel):
    schema_version: Literal[1] = 1
    phase: Literal["measured"] = "measured"
    source: Source
    shots: Annotated[list[MeasuredShot], Field(min_length=1, max_length=MAX_SHOTS)]
    selected_threshold: Annotated[float, Field(ge=.1, le=.6)]
    threshold_sweep: Annotated[list[ThresholdResult], Field(min_length=1, max_length=5)]
    contact_sheets: Annotated[list[ContactSheet], Field(min_length=1, max_length=6)]
    player: Player
    motion_method: Literal["native_consecutive_gray_mean_absolute_difference"] = "native_consecutive_gray_mean_absolute_difference"
    motion_sample_width: Literal[64] = 64
    motion_sample_height: Literal[36] = 36
    warnings: Annotated[list[Annotated[str, Field(max_length=500)]], Field(max_length=70)] = []

    @model_validator(mode="after")
    def complete_timeline(self):
        previous = 0.0
        for index, shot in enumerate(self.shots, 1):
            if shot.shot_id != index or not math.isclose(shot.start_s, previous, abs_tol=1e-8):
                raise ValueError("Measured shot ids must be sequential and intervals contiguous without overlap.")
            previous = shot.end_s
        if (not math.isclose(previous, self.source.duration_s, abs_tol=1e-8)
                or not math.isclose(math.fsum(shot.duration_s for shot in self.shots),
                                    self.source.duration_s, abs_tol=1e-8)):
            raise ValueError("Measured shot durations must sum exactly to the film duration.")
        if [i for sheet in self.contact_sheets for i in sheet.shot_ids] != list(range(1, len(self.shots) + 1)):
            raise ValueError("Contact sheets must cover every measured shot once in order.")
        candidates = {item.threshold: item.scene_times_s for item in self.threshold_sweep}
        if self.selected_threshold not in candidates:
            raise ValueError("The selected scene threshold must have a recorded measurement.")
        if candidates[self.selected_threshold] != [shot.start_s for shot in self.shots[1:]]:
            raise ValueError("Selected scene cuts must match the measured timeline.")
        if not math.isclose(self.player.duration_s, self.source.duration_s,
                            abs_tol=max(.1, 2 / self.source.fps)):
            raise ValueError("The report player must cover the complete measured film.")
        return self


class Integrity(ClosedModel):
    schema_version: Literal[1] = 1
    measurements_sha256: SHA256
    files: Annotated[list[PinnedFile], Field(min_length=2, max_length=10)]


def parse_arguments(arguments: dict) -> tuple[Request, MeasureParams | ReportParams]:
    try:
        if not isinstance(arguments, dict):
            raise ValueError("Shot breakdown arguments must be an object.")
        if len(json.dumps(arguments, allow_nan=False).encode()) > MAX_ARGUMENT_BYTES:
            raise ValueError("Shot breakdown arguments exceed the 128 KiB limit.")
        request = Request.model_validate(arguments)
        params_type = MeasureParams if request.op == "measure" else ReportParams
        params = params_type.model_validate({} if request.params is None else request.params)
        root = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser().resolve()
        directory = (root / request.job_id).resolve()
        if not directory.is_relative_to(root) or directory == root:
            raise ValueError("The job directory must stay inside the local media root.")
        if request.op == "measure" and re.fullmatch(ASSET_PATTERN, request.input_path):
            return request, params
        validate_input_path(directory, request.input_path, must_exist=False)
        return request, params
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(map(str, error['loc']))}: {error['msg']}"
                            for error in exc.errors(include_input=False)[:6])
        raise ValueError(f"Invalid shot breakdown arguments. {details}") from None
    except (TypeError, OverflowError):
        raise ValueError("Shot breakdown arguments must contain bounded JSON values.") from None


def validate_arguments(arguments: dict) -> None:
    """Validate the closed schema and lexical confinement without reading media."""
    parse_arguments(arguments)


def tool_schema() -> dict:
    schema = Request.model_json_schema()
    report = ReportParams.model_json_schema()
    schema.setdefault("$defs", {}).update(report.pop("$defs", {}))
    schema["allOf"] = [
        {"if": {"properties": {"op": {"const": "measure"}}},
         "then": {"properties": {"params": {"anyOf": [MeasureParams.model_json_schema(), {"type": "null"}]}}}},
        {"if": {"properties": {"op": {"const": "report"}}},
         "then": {"required": ["params"], "properties": {"params": report}}},
    ]
    return {"name": "shot_breakdown", "description": (
        "Measure a confined reference film locally, then add visual labels to its pinned report. "
        "Code measures all timings and motion. Visual labels never supply timing. "
        "Dry-run validates arguments only. Reports retain pending visual review."),
        "inputSchema": schema}
