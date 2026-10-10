"""Dialogue contracts verified from sync.so API documentation on 2026-10-10.

https://sync.so/docs/developer-guides/dialogue-editing
https://sync.so/docs/api-reference/api/dialogue-edits-api/create
https://sync.so/docs/api-reference/api/transcriptions-api/create
https://sync.so/docs/api-reference/api/generate-api/create
"""
from __future__ import annotations

import os
import re
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from providers.sync import contracts


TOOLS = ("transcribe_video", "get_transcription", "create_dialogue_edit", "get_dialogue_edit", "create_dialogue_video")
FIELD_DESCRIPTIONS = {
    "source_video_url": "Exact whole-source HTTPS URL on assets.sync.so. Upload the source through Sync's asset upload flow before using this tool.",
    "source_duration_seconds": "Measured whole-source duration, greater than zero and at most 600 seconds. Windowed sources are unsupported.",
    "speaker_count": "Must be integer 1. Multi-speaker dialogue edits are unsupported.",
    "subjects": "Identify the single speaker whose source voice is cloned and whose likeness appears.",
    "consent_confirmed": "Must be boolean true. Confirms explicit permission to clone the source voice and edit the depicted likeness.",
    "transcription_id": "Exact Sync transcription ID from transcribe_video. The provider fetches and forwards the original transcript unchanged.",
    "edits": "1 to 100 change or remove operations using original word IDs. Removals must be contiguous and operations must not overlap.",
    "action_id": "Stable unique identifier for this approved preview action. Reuse it after any interruption. A lost response never triggers another preview submission.",
    "voice_id": "Optional source-cloned voice ID from an earlier dialogue job for this exact source, with rerun_of_job_id. Foreign voice hints are ignored.",
    "rerun_of_job_id": "Optional prior dialogue job ID used to verify same-source voice reuse.",
    "dialogue_edit_id": "Exact Sync dialogue edit ID from create_dialogue_edit.",
    "preview_reviewed": "Must be boolean true after the user listens to the completed preview audio.",
    "preview_duration_seconds": "Measured previewDurationMs divided by 1000, greater than zero and at most 600. The paid output estimate uses this duration.",
    "idempotency_key": "Stable key for this approved video generation, 1 to 128 ASCII letters, digits, dot, underscore, tilde or hyphen.",
    "accept_partial": "True only after the user explicitly accepts COMPLETED_PARTIAL preview results and their reported failures.",
}
EDIT_SCHEMA = {
    "type": "array", "items": {"type": "object", "properties": {
        "kind": {"type": "string", "description": "change or remove"},
        "wordId": {"type": "string", "description": "Required for change."},
        "replacement": {"type": "string", "description": "Nonblank replacement for change."},
        "pronunciation": {"type": "string", "description": "Optional pronunciation hint for change."},
        "wordIds": {"type": "array", "items": {"type": "string"}, "description": "Required contiguous word IDs for remove."},
    }, "required": ["kind"]},
}


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False, hide_input_in_errors=True)


def identifier(value: str, name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
        raise ValueError(f"{name} must be a valid Sync identifier.")
    return value


class SourceRequest(StrictModel):
    source_video_url: str
    source_duration_seconds: float = Field(gt=0, le=600)
    speaker_count: int
    subjects: str = Field(min_length=1, max_length=12000)
    consent_confirmed: bool

    @model_validator(mode="after")
    def supported_source(self):
        if self.speaker_count != 1:
            raise ValueError("Dialogue editing supports one speaker only. Use consented regular lip-sync for multi-speaker footage.")
        if self.consent_confirmed is not True:
            raise ValueError("consent_confirmed must be true for cloning the source voice and editing its depicted likeness.")
        if not self.subjects.strip():
            raise ValueError("subjects must identify the consented speaker and source voice.")
        contracts.validate_media_reference(self.source_video_url, allow_asset=False)
        source = urlsplit(self.source_video_url)
        if source.hostname != "assets.sync.so" or source.port not in {None, 443}:
            raise ValueError("Dialogue edits require an HTTPS source on assets.sync.so. Pre-upload the whole source with Sync's asset upload API.")
        return self


class TranscriptionPoll(StrictModel):
    transcription_id: str

    @model_validator(mode="after")
    def supported_id(self):
        identifier(self.transcription_id, "transcription_id")
        return self


class Change(StrictModel):
    kind: Literal["change"]
    wordId: str = Field(min_length=1)
    replacement: str = Field(min_length=1)
    pronunciation: str | None = None

    @model_validator(mode="after")
    def nonblank_text(self):
        if not self.wordId.strip() or not self.replacement.strip():
            raise ValueError("A change requires an original word ID and nonblank replacement.")
        if self.pronunciation is not None and not self.pronunciation.strip():
            raise ValueError("pronunciation must be nonblank when supplied.")
        return self


class Remove(StrictModel):
    kind: Literal["remove"]
    wordIds: list[str] = Field(min_length=1)


Edit = Annotated[Change | Remove, Field(discriminator="kind")]
EditList = Annotated[list[Edit], Field(min_length=1, max_length=100)]


def _check_conflicts(edits: list[Change | Remove]) -> None:
    touched = [word_id for edit in edits for word_id in ([edit.wordId] if isinstance(edit, Change) else edit.wordIds)]
    if len(touched) != len(set(touched)):
        raise ValueError("Dialogue edits cannot repeat or conflict on a word ID.")


class PreviewRequest(SourceRequest):
    transcription_id: str
    edits: EditList
    action_id: str = Field(min_length=1, max_length=128)
    voice_id: str | None = None
    rerun_of_job_id: str | None = None

    @model_validator(mode="after")
    def supported_preview(self):
        identifier(self.transcription_id, "transcription_id")
        if not re.fullmatch(r"[A-Za-z0-9._~-]+", self.action_id):
            raise ValueError("action_id requires ASCII letters, digits, dot, underscore, tilde or hyphen.")
        for name in ("voice_id", "rerun_of_job_id"):
            value = getattr(self, name)
            if value is not None:
                identifier(value, name)
        _check_conflicts(self.edits)
        return self


class DialoguePoll(StrictModel):
    dialogue_edit_id: str

    @model_validator(mode="after")
    def supported_id(self):
        identifier(self.dialogue_edit_id, "dialogue_edit_id")
        return self


class VideoRequest(SourceRequest):
    dialogue_edit_id: str
    source_fps: float = Field(gt=0)
    preview_duration_seconds: float = Field(gt=0, le=600)
    preview_reviewed: bool
    idempotency_key: str = Field(min_length=1, max_length=128)
    accept_partial: bool = False
    source_width: int | None = Field(default=None, gt=0)
    source_height: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def supported_video(self):
        identifier(self.dialogue_edit_id, "dialogue_edit_id")
        if self.preview_reviewed is not True:
            raise ValueError("The user must listen to and approve the preview before video generation.")
        if not re.fullmatch(r"[A-Za-z0-9._~-]+", self.idempotency_key):
            raise ValueError("idempotency_key requires 1 to 128 ASCII letters, digits, dot, underscore, tilde or hyphen.")
        if (self.source_width is None) != (self.source_height is None):
            raise ValueError("source_width and source_height must be supplied together.")
        return self


class Word(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow", hide_input_in_errors=True)
    id: str = Field(min_length=1)
    text: str
    startMs: int = Field(ge=0)
    endMs: int = Field(gt=0)


class Segment(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow", hide_input_in_errors=True)
    id: str = Field(min_length=1)
    words: list[Word] = Field(min_length=1)


class Transcript(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow", hide_input_in_errors=True)
    segments: list[Segment] = Field(min_length=1)
    speakerCount: int


def validate_edits(transcript: dict[str, Any], edits: list[dict[str, Any]], duration: float) -> None:
    parsed = Transcript.model_validate(transcript)
    if parsed.speakerCount != 1:
        raise ValueError("The upstream transcript contains multiple speakers. Dialogue editing supports one speaker only.")
    words = [word for segment in parsed.segments for word in segment.words]
    positions = {word.id: index for index, word in enumerate(words)}
    if len(positions) != len(words) or len({segment.id for segment in parsed.segments}) != len(parsed.segments):
        raise ValueError("Upstream transcript word and segment IDs must be unique.")
    if any(word.endMs <= word.startMs or word.endMs > duration * 1000 for word in words):
        raise ValueError("Transcript word timings must be positive and fit the whole source.")
    parsed_edits = TypeAdapter(EditList).validate_python(edits)
    _check_conflicts(parsed_edits)
    for edit in parsed_edits:
        ids = [edit.wordId] if isinstance(edit, Change) else edit.wordIds
        if any(word_id not in positions for word_id in ids):
            raise ValueError("Dialogue edit word IDs must exist in the upstream transcript.")
        indexes = [positions[word_id] for word_id in ids]
        if isinstance(edit, Remove) and indexes != list(range(indexes[0], indexes[0] + len(indexes))):
            raise ValueError("Removal word IDs must be contiguous in original transcript order.")


def validate_whole_source(payload: dict[str, Any], request: SourceRequest) -> None:
    if payload.get("sourceVideoUrl") != request.source_video_url:
        raise ValueError("The Sync job source must match the exact original source URL.")
    start, end = payload.get("sourceStartMs"), payload.get("sourceEndMs")
    if type(start) is not int or start != 0 or (
        end is not None and (type(end) is not int or abs(end - request.source_duration_seconds * 1000) > 1)
    ):
        raise ValueError("Dialogue edits require the whole source. Windowed transcription or preview is unsupported.")


def preview_quote_cents() -> int:
    value = os.getenv("SYNC_DIALOGUE_PREVIEW_COST_CENTS", "")
    if not re.fullmatch(r"[1-9][0-9]*", value):
        raise ValueError("Sync dialogue preview cost unknown; official rate TODO. Set an operator-confirmed quote before live submission.")
    return int(value)


def request_for(tool: str, arguments: dict[str, Any]) -> StrictModel:
    models = {
        "transcribe_video": SourceRequest, "get_transcription": TranscriptionPoll,
        "create_dialogue_edit": PreviewRequest, "get_dialogue_edit": DialoguePoll,
        "create_dialogue_video": VideoRequest,
    }
    return models[tool].model_validate(arguments)


def validate_arguments(tool: str, arguments: dict[str, Any]) -> None:
    if tool in TOOLS:
        request_for(tool, arguments)
