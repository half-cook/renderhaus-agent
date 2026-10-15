"""Strict operation-specific requests, enforced before files or rendering are touched."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from providers.ffmpeg.sandbox import validate_input_path, validate_job_id


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class VectorOptions(Strict):
    palette_size: int = Field(default=4, ge=1, le=8)


class EmptyOptions(Strict):
    pass


class ApprovalOptions(Strict):
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    rights_confirmed: bool


class MotionOptions(Strict):
    duration_seconds: float = Field(default=2, ge=1, le=3)
    style: Literal['reveal', 'splash', 'loader', 'idle-hover'] = 'reveal'
    personality: list[str] = Field(default_factory=lambda: ['precise', 'calm', 'confident'], min_length=1, max_length=3)
    idle_loop: bool = False
    background_color: str = Field(default='#101820', pattern=r'^#[0-9a-fA-F]{6}$')


class FinalOptions(Strict):
    svg_path: str
    template: dict


class EasingSample(Strict):
    time_ms: float = Field(ge=0, le=3000)
    value: float = Field(ge=-2, le=3)


class EasingOptions(Strict):
    token: Literal['enter', 'settle', 'linear']
    duration_ms: float = Field(ge=100, le=3000)
    samples: list[EasingSample] = Field(min_length=3, max_length=1000)


class ContinuitySample(Strict):
    part: str = Field(min_length=1, max_length=40)
    time_ms: float = Field(ge=0, le=30000)
    x: float = Field(ge=-4096, le=4096)
    y: float = Field(ge=-4096, le=4096)
    scale: float = Field(ge=0, le=4)
    opacity: float = Field(ge=0, le=1)


class ContinuityOptions(Strict):
    samples: list[ContinuitySample] = Field(min_length=3, max_length=10000)


MODELS = {'vectorize': VectorOptions, 'audit': EmptyOptions, 'approve': ApprovalOptions,
          'choreograph': MotionOptions, 'final_frame': FinalOptions,
          'easing': EasingOptions, 'continuity': ContinuityOptions}


def request_for(arguments: dict) -> tuple[str, dict]:
    if not isinstance(arguments, dict) or set(arguments) - {'op', 'job_id', 'input_path', 'params'}:
        raise ValueError('Logo arguments contain unknown fields.')
    op = arguments.get('op')
    if not isinstance(op, str) or op not in MODELS:
        raise ValueError('Unknown logo operation.')
    job = validate_job_id(arguments.get('job_id'))
    directory = Path(os.getenv('RENDERHAUS_MEDIA_DIR', '.renderhaus/media')).expanduser().resolve() / job
    input_path = arguments.get('input_path')
    if op == 'vectorize' and isinstance(input_path, str) and input_path.startswith('renderhaus-asset://'):
        if not re.fullmatch(r'renderhaus-asset://[A-Za-z0-9_-]{1,160}', input_path):
            raise ValueError('Logo source handle is invalid.')
    else:
        validate_input_path(directory, input_path, must_exist=False)
    raw = arguments.get('params') if arguments.get('params') is not None else {}
    try:
        if len(json.dumps(raw, allow_nan=False)) > 1_000_000:
            raise ValueError('Logo parameters exceed the bounded request size.')
        params = MODELS[op].model_validate(raw).model_dump()
    except (TypeError, ValidationError) as exc:
        raise ValueError('Logo parameters do not match the operation contract.') from exc
    if op == 'final_frame':
        validate_input_path(directory, params['svg_path'], must_exist=False)
    if op == 'choreograph':
        if any(not re.fullmatch(r'[A-Za-z][A-Za-z -]{0,31}', word) for word in params['personality']):
            raise ValueError('Personality requires short plain words.')
    return op, params


def validate_arguments(arguments: dict) -> None:
    request_for(arguments)
