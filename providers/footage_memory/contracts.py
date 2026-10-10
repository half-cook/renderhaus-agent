"""Parse bounded footage tool arguments before local I/O or backend invocation."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

ID = Annotated[str, Field(min_length=1, max_length=120, pattern=r'^[A-Za-z0-9_][A-Za-z0-9_-]*$')]
KEY = Annotated[str, Field(min_length=1, max_length=1024, pattern=r'^(?!.*(?:^|/)\.\.?(?:/|$))[A-Za-z0-9_][A-Za-z0-9_./-]*$')]
Seconds = Annotated[float, Field(ge=0, le=86400)]


class ProjectRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False, regex_engine='python-re')
    project_id: ID
    workspace_id: ID = 'local'


class SourceRequest(ProjectRequest):
    job_id: ID
    path: KEY | None = None
    folder: KEY | None = None
    asset_version_id: ID | None = None

    @model_validator(mode='after')
    def source(self):
        if (self.path is None) == (self.folder is None):
            raise ValueError('Supply exactly one path or folder.')
        if self.folder and self.asset_version_id:
            raise ValueError('An asset version identifies one clip, not a folder.')
        return self


class StatusRequest(SourceRequest):
    question_count: Annotated[int, Field(ge=1, le=100)] = 1


class BuildRequest(SourceRequest):
    depth: Literal['events', 'hierarchy'] = 'events'
    window_s: Annotated[float, Field(ge=10, le=60)] = 30.0
    stage: Literal['estimate', 'build'] = 'estimate'
    plan_hash: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')] | None = None


class QueryRequest(ProjectRequest):
    query: Annotated[str, Field(min_length=1, max_length=1000)]
    scope: ID | None = None
    limit: Annotated[int, Field(ge=1, le=50)] = 10


class WatchRequest(ProjectRequest):
    job_id: ID
    path: KEY
    question: Annotated[str, Field(min_length=1, max_length=1000)]
    asset_version_id: ID | None = None
    t0_s: Seconds | None = None
    t1_s: Seconds | None = None
    verify_hit_id: ID | None = None

    @model_validator(mode='after')
    def range(self):
        if (self.t0_s is None) != (self.t1_s is None):
            raise ValueError('Supply both window endpoints.')
        if self.t0_s is not None and self.t1_s <= self.t0_s:
            raise ValueError('Window end must follow its start.')
        if self.verify_hit_id and self.t0_s is None:
            raise ValueError('Verify requires a narrow time window.')
        return self


class SelectWindow(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)
    clip_id: ID
    t0_s: Seconds
    t1_s: Seconds

    @model_validator(mode='after')
    def range(self):
        if self.t1_s <= self.t0_s:
            raise ValueError('Select end must follow its start.')
        return self


class ExtractRequest(ProjectRequest):
    job_id: ID
    hit_ids: Annotated[list[ID], Field(min_length=1, max_length=50)] | None = None
    windows: Annotated[list[SelectWindow], Field(min_length=1, max_length=50)] | None = None
    handles_s: Annotated[float, Field(ge=0, le=10)] = 1.0
    allow_unverified: bool = False

    @model_validator(mode='after')
    def selects(self):
        if (self.hit_ids is None) == (self.windows is None):
            raise ValueError('Supply exactly one hit_ids or windows list.')
        if self.hit_ids and len(set(self.hit_ids)) != len(self.hit_ids):
            raise ValueError('Duplicate hit ids are not allowed.')
        return self


REQUESTS = {'footage_memory_status': StatusRequest, 'footage_memory_build': BuildRequest,
            'footage_memory_query': QueryRequest, 'footage_watch_answer': WatchRequest,
            'footage_clip_extract': ExtractRequest}


def request_for(tool: str, arguments: dict) -> ProjectRequest:
    try:
        return REQUESTS[tool].model_validate(arguments)
    except ValidationError as exc:
        raise ValueError('; '.join('.'.join(map(str, e['loc'])) + ': ' + e['msg']
                                  for e in exc.errors(include_input=False, include_url=False))) from None


def validate_arguments(tool: str, arguments: dict) -> None:
    request_for(tool, arguments)
