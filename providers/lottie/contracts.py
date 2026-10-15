from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from providers.ffmpeg.sandbox import validate_input_path, validate_job_id

TARGETS = ("lottie-web", "lottie-ios", "lottie-android", "dotlottie")
Target = Literal["lottie-web", "lottie-ios", "lottie-android", "dotlottie"]
Vector = Annotated[list[float], Field(min_length=2, max_length=2)]
Color = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class BezierPath(StrictModel):
    v: list[Vector] = Field(min_length=2, max_length=2048)
    i: list[Vector] = Field(min_length=2, max_length=2048)
    o: list[Vector] = Field(min_length=2, max_length=2048)
    c: bool = False

    @model_validator(mode="after")
    def consistent_points(self) -> Self:
        if not len(self.v) == len(self.i) == len(self.o):
            raise ValueError("path v, i and o must have equal point counts")
        if any(abs(n) > 32768 for vectors in (self.v, self.i, self.o) for point in vectors for n in point):
            raise ValueError("path coordinates must be between -32768 and 32768")
        return self


class SceneKeyframe(StrictModel):
    frame: int = Field(ge=0, le=3600)
    value: float | Vector
    easing: Literal["linear", "ease-in", "ease-out", "ease-in-out"] = "linear"


class AnimationTrack(StrictModel):
    property: Literal["position", "scale", "rotation", "opacity", "trim_end"]
    keyframes: list[SceneKeyframe] = Field(min_length=2, max_length=256)

    @model_validator(mode="after")
    def valid_values(self) -> Self:
        frames = [key.frame for key in self.keyframes]
        if any(a >= b for a, b in zip(frames, frames[1:])):
            raise ValueError("keyframe frames must be strictly increasing")
        vector = self.property in {"position", "scale"}
        for key in self.keyframes:
            if vector != isinstance(key.value, list):
                raise ValueError(f"{self.property} keyframes require {'two numbers' if vector else 'a scalar'}")
            values = key.value if isinstance(key.value, list) else [key.value]
            if any(abs(n) > 32768 for n in values):
                raise ValueError("keyframe values must be between -32768 and 32768")
            if self.property in {"opacity", "trim_end"} and not 0 <= values[0] <= 100:
                raise ValueError(f"{self.property} keyframes must be between 0 and 100")
        return self


class SceneLayer(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    shape: Literal["rectangle", "ellipse", "path"]
    position: Vector | None = None
    size: Vector = Field(default_factory=lambda: [64.0, 64.0])
    path: BezierPath | None = None
    fill: Color | None = "#2563eb"
    stroke: Color | None = None
    stroke_width: float = Field(default=4, gt=0, le=256)
    rotation: float = Field(default=0, ge=-32768, le=32768)
    opacity: float = Field(default=100, ge=0, le=100)
    animate: list[AnimationTrack] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def valid_geometry(self) -> Self:
        if not self.name.strip() or any(ord(c) < 32 for c in self.name):
            raise ValueError("layer name must be nonblank and contain no control characters")
        if (self.shape == "path") != (self.path is not None):
            raise ValueError("path geometry is required only for shape=path")
        if any(not 0 < n <= 4096 for n in self.size):
            raise ValueError("layer size must be positive and at most 4096")
        if self.position is not None and any(abs(n) > 32768 for n in self.position):
            raise ValueError("layer position must be between -32768 and 32768")
        if self.fill is None and self.stroke is None:
            raise ValueError("a layer requires fill or stroke")
        properties = [track.property for track in self.animate]
        if len(properties) != len(set(properties)):
            raise ValueError("a layer cannot repeat an animation property")
        if "trim_end" in properties and (self.shape != "path" or self.stroke is None or self.fill is not None):
            raise ValueError("trim_end requires a stroked path without fill")
        return self


class SceneSpec(StrictModel):
    width: int = Field(default=256, ge=16, le=2048)
    height: int = Field(default=256, ge=16, le=2048)
    fps: float = Field(default=60, ge=1, le=120)
    frames: int = Field(default=90, ge=1, le=3600)
    name: str = Field(default="UI animation", min_length=1, max_length=120)
    background: Color | None = None
    layers: list[SceneLayer] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def valid_timing(self) -> Self:
        if self.frames / self.fps > 120:
            raise ValueError("scene duration must be at most 120 seconds")
        if not self.name.strip() or any(ord(c) < 32 for c in self.name):
            raise ValueError("scene name must be nonblank and contain no control characters")
        for layer in self.layers:
            for track in layer.animate:
                if track.keyframes[-1].frame > self.frames:
                    raise ValueError(f"{layer.name} keyframes must fit within scene frames")
        return self


def _relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or len(value) > 1024 or "\\" in value or "\x00" in value
            or ":" in value or ".." in path.parts or value == "."):
        raise ValueError("input paths must be files confined to the job directory")
    return value


class JobRequest(StrictModel):
    job_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,79}$")


class AuthorRequest(JobRequest):
    scene: dict | None = None
    lottie: dict | None = None
    input_path: str | None = None
    svg_path: str | None = None
    patch: dict | None = None
    name: str = Field(default="animation", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

    @field_validator("input_path", "svg_path")
    @classmethod
    def local_paths(cls, value: str | None) -> str | None:
        return None if value is None else _relative_path(value)

    @model_validator(mode="after")
    def one_source(self) -> Self:
        if sum(item is not None for item in (self.scene, self.lottie, self.input_path, self.svg_path)) != 1:
            raise ValueError("exactly one of scene, lottie, input_path or svg_path is required")
        if self.patch is not None and self.lottie is None and self.input_path is None:
            raise ValueError("patch requires lottie or input_path")
        if self.scene is not None:
            SceneSpec.model_validate(self.scene)
        return self


class ValidateRequest(JobRequest):
    input_path: str
    targets: list[Target] | None = Field(default=None, min_length=1, max_length=4)

    @field_validator("input_path")
    @classmethod
    def local_path(cls, value: str) -> str:
        return _relative_path(value)

    @field_validator("targets")
    @classmethod
    def distinct_targets(cls, value: list[Target] | None) -> list[Target] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("targets must not repeat")
        return value


class PreviewRequest(JobRequest):
    input_path: str
    max_size: int = Field(default=256, ge=32, le=512)
    formats: list[Literal["mp4", "gif"]] | None = Field(default=None, max_length=2)

    @field_validator("input_path")
    @classmethod
    def local_path(cls, value: str) -> str:
        return _relative_path(value)

    @field_validator("formats")
    @classmethod
    def distinct_formats(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("formats must not repeat")
        return value


REQUESTS = {"lottie_author": AuthorRequest, "lottie_validate": ValidateRequest, "lottie_preview_render": PreviewRequest}
DESCRIPTIONS = {
    "lottie_author": "Create or patch a vector animation in the job directory and save JSON plus a portable animation package.",
    "lottie_validate": "Validate vector animation structure, bounds, keyframes and compatibility with app and web players.",
    "lottie_preview_render": "Create a scrubbable frame preview, contact sheet and MP4/GIF previews of supported vector animation features.",
}


def owned_input_placeholders(arguments: dict) -> dict:
    return {**arguments, **{field: 'owned-source.svg' if field == 'svg_path' else 'owned-source.json'
            for field in ('svg_path', 'input_path') if isinstance(arguments.get(field), str)
            and arguments[field].startswith('renderhaus-asset://')}}


def request_for(tool: str, arguments: dict) -> AuthorRequest | ValidateRequest | PreviewRequest:
    if tool not in REQUESTS:
        raise ValueError(f"unknown local animation tool {tool!r}")
    request = REQUESTS[tool].model_validate(arguments)
    validate_job_id(request.job_id)
    root = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser().resolve()
    candidate = root / request.job_id
    if candidate.is_symlink():
        raise ValueError("job directory must not be a symlink")
    directory = candidate.resolve()
    if directory == root or not directory.is_relative_to(root):
        raise ValueError("job directory must stay inside the local media root")
    for field in ("input_path", "svg_path"):
        value = getattr(request, field, None)
        if value is not None:
            validate_input_path(directory, value, must_exist=False)
    return request


def tool_schema(tool: str) -> dict:
    if tool not in REQUESTS:
        raise ValueError(f"unknown local animation tool {tool!r}")
    schema = REQUESTS[tool].model_json_schema()
    schema.pop("title", None)
    for value in schema["properties"].values():
        value.pop("title", None)
        if "anyOf" in value:
            options = [item for item in value.pop("anyOf") if item.get("type") != "null"]
            value.update(options[0])
            value.pop("default", None)
    if tool == "lottie_author":
        schema["properties"]["scene"]["description"] = (
            "Strict scene object. Defaults width/height=256, fps=60, frames=90, transparent background. "
            "layers up to 64; each requires semantic name and shape rectangle, ellipse or path. "
            "Optional position/size pairs, #RRGGBB fill/stroke, stroke_width, opacity/rotation. "
            "Bezier path requires v/i/o equal arrays of xy pairs and boolean c. "
            "animate tracks use property position/scale/rotation/opacity/trim_end and strictly increasing "
            "keyframes {frame,value,easing}; easing linear/ease-in/ease-out/ease-in-out. "
            "Runtime rejects unknown fields. Canvas 16..2048, fps1..120, frames1..3600, duration<=120s."
        )
    for field in ("svg_path", "input_path"):
        if field in schema["properties"]:
            schema["properties"][field]["description"] = (
                "File confined to the current job. Studio may stage an owned renderhaus-asset://version handle "
                "through its trusted resolver before invoking this provider; direct provider calls require a local path."
            )
    return {"name": tool, "description": DESCRIPTIONS[tool], "inputSchema": schema}
