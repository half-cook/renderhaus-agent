"""Pure validation for episodic fiction plans and continuity-locked storyboards."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError


_Text = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
_Seconds = Annotated[float, Field(gt=0, allow_inf_nan=False)]
_CJK = re.compile(
    "[\u1100-\u11ff\u3040-\u30ff\u3130-\u318f\u31f0-\u31ff"
    "\u3400-\u4dbf\u4e00-\u9fff\ua960-\ua97f\uac00-\ud7ff"
    "\uf900-\ufaff\uff66-\uff9f\U00020000-\U0002fa1f\U00030000-\U000323af]"
)


class _Document(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)


class _OutlineEpisode(_Document):
    id: _Text
    synopsis: _Text
    hook: _Text


class _Outline(_Document):
    series_id: _Text
    title: _Text
    revision: _Text
    adaptation_notes: _Text
    cast: list[_Text] = Field(min_length=1)
    beats: list[_Text] = Field(min_length=1)
    episodes: list[_OutlineEpisode] = Field(min_length=1)
    assets: list[_Text] = Field(min_length=1)


class _Character(_Document):
    id: _Text
    profile: _Text
    design_prompt: _Text
    voice_prompt: _Text


class _Art(_Document):
    id: _Text
    description: _Text
    design_prompt: _Text


class _Lock(_Document):
    id: _Text
    subject_id: _Text
    phrase: _Text


class _Action(_Document):
    id: _Text
    kind: Literal["action"]
    text: _Text
    duration_seconds: _Seconds


class _Dialogue(_Document):
    id: _Text
    kind: Literal["dialogue"]
    text: _Text
    speaker_id: _Text


class _Caption(_Document):
    line_id: _Text
    text: _Text


class _Cut(_Document):
    id: _Text
    duration_seconds: Annotated[float, Field(ge=2, le=5, allow_inf_nan=False)]
    subjects: list[_Text] = Field(min_length=1)
    lock_ids: list[_Text]
    keyframe_prompt: _Text
    video_prompt: _Text
    line_ids: list[_Text]


class _Segment(_Document):
    id: _Text
    cuts: list[_Cut] = Field(min_length=1)


class _Episode(_Document):
    episode_id: _Text
    outline_hash: _Text
    characters: list[_Character]
    art: list[_Art]
    locks: list[_Lock] = Field(min_length=1)
    script: list[Annotated[_Action | _Dialogue, Field(discriminator="kind")]] = Field(min_length=1)
    segments: list[_Segment] = Field(min_length=1)
    captions: list[_Caption] = Field(default_factory=list)


def _validation_errors(error: ValidationError) -> list[str]:
    return [
        f"{'.'.join(str(part) for part in item['loc']) or 'document'}: {item['msg']}"
        for item in error.errors(include_url=False, include_input=False)
    ]


def _duplicate_errors(values: Iterable[str], label: str) -> list[str]:
    return [
        f"{label}: duplicate ID {identifier!r}."
        for identifier, count in Counter(values).items()
        if count > 1
    ]


def _dialogue_seconds(text: str) -> float:
    cjk = len(_CJK.findall(text))
    other = sum(not character.isspace() for character in text) - cjk
    tenths = ((cjk * 3 + other) * 10 + 11) // 12
    return max(4, tenths) / 10


def check_outline(data: dict) -> dict:
    """Validate an outline and hash its canonical content, without approving it."""
    try:
        outline = _Outline.model_validate(data)
    except ValidationError as error:
        return {"ok": False, "errors": _validation_errors(error)}
    errors = [
        *_duplicate_errors(outline.cast, "cast"),
        *_duplicate_errors((episode.id for episode in outline.episodes), "episodes"),
        *_duplicate_errors(outline.assets, "assets"),
    ]
    if errors:
        return {"ok": False, "errors": errors}
    canonical = outline.model_dump(mode="json")
    encoded = json.dumps(
        canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return {
        "ok": True,
        "errors": [],
        "outline": canonical,
        "outline_hash": hashlib.sha256(encoded).hexdigest(),
    }


def check_episode(data: dict) -> dict:
    """Check timing, references, lock phrases and verbatim captions without media I/O."""
    result = {
        "ok": False,
        "errors": [],
        "duration_seconds": 0.0,
        "dialogue_estimates": {},
        "measured": False,
    }
    try:
        episode = _Episode.model_validate(data)
    except ValidationError as error:
        return {**result, "errors": _validation_errors(error)}

    errors: list[str] = []
    character_ids = {character.id for character in episode.characters}
    subject_ids = character_ids | {art.id for art in episode.art}
    locks = {lock.id: lock for lock in episode.locks}
    lines = {line.id: line for line in episode.script}
    estimates = {
        line.id: _dialogue_seconds(line.text)
        for line in episode.script
        if isinstance(line, _Dialogue)
    }
    cuts = [cut for segment in episode.segments for cut in segment.cuts]
    for values, label in (
        ([subject.id for subject in [*episode.characters, *episode.art]], "subjects"),
        ([lock.id for lock in episode.locks], "locks"),
        ([line.id for line in episode.script], "script"),
        ([segment.id for segment in episode.segments], "segments"),
        ([cut.id for cut in cuts], "cuts"),
        ([caption.line_id for caption in episode.captions], "captions"),
    ):
        errors.extend(_duplicate_errors(values, label))
    locks_by_subject: dict[str, set[str]] = {}
    for lock in episode.locks:
        if lock.subject_id not in subject_ids:
            errors.append(f"Lock {lock.id!r} refers to unknown subject {lock.subject_id!r}.")
        locks_by_subject.setdefault(lock.subject_id, set()).add(lock.id)
    for line in episode.script:
        if isinstance(line, _Dialogue) and line.speaker_id not in character_ids:
            errors.append(
                f"Dialogue {line.id!r} has unknown character speaker {line.speaker_id!r}."
            )

    total = Decimal(0)
    uses: Counter[str] = Counter()
    for segment in episode.segments:
        duration = sum((Decimal(str(cut.duration_seconds)) for cut in segment.cuts), Decimal(0))
        total += duration
        if duration > 15:
            errors.append(
                f"Segment {segment.id!r} duration is {duration} seconds; one generation must be at most 15 seconds."
            )
        for cut in segment.cuts:
            errors.extend(_duplicate_errors(cut.subjects, f"Cut {cut.id!r} subjects"))
            errors.extend(_duplicate_errors(cut.lock_ids, f"Cut {cut.id!r} lock_ids"))
            cited = set(cut.lock_ids)
            for subject in cut.subjects:
                if subject not in subject_ids:
                    errors.append(f"Cut {cut.id!r} depicts unknown subject {subject!r}.")
                required = locks_by_subject.get(subject, set())
                if not required:
                    errors.append(f"Cut {cut.id!r} subject {subject!r} needs a continuity lock.")
                for identifier in sorted(required - cited):
                    errors.append(
                        f"Cut {cut.id!r} is missing applicable lock {identifier!r} for subject {subject!r}."
                    )
            for identifier in cut.lock_ids:
                lock = locks.get(identifier)
                if lock is None:
                    errors.append(f"Cut {cut.id!r} cites unknown lock {identifier!r}.")
                    continue
                if lock.subject_id not in cut.subjects:
                    errors.append(
                        f"Cut {cut.id!r} cites lock {identifier!r} for undepicted subject {lock.subject_id!r}."
                    )
                for field in ("keyframe_prompt", "video_prompt"):
                    if lock.phrase not in getattr(cut, field):
                        errors.append(
                            f"Cut {cut.id!r} {field} is missing the verbatim phrase for lock {identifier!r}."
                        )
            required_time = Decimal(0)
            for identifier in cut.line_ids:
                uses[identifier] += 1
                line = lines.get(identifier)
                if line is None:
                    errors.append(f"Cut {cut.id!r} refers to unknown script line {identifier!r}.")
                else:
                    seconds = (
                        estimates[identifier]
                        if isinstance(line, _Dialogue)
                        else line.duration_seconds
                    )
                    required_time += Decimal(str(seconds))
            if required_time > Decimal(str(cut.duration_seconds)):
                errors.append(
                    f"Cut {cut.id!r} script duration needs {required_time} seconds but its duration is {cut.duration_seconds} seconds."
                )
    for identifier in lines:
        if uses[identifier] != 1:
            errors.append(
                f"Script line {identifier!r} must be used exactly once; found {uses[identifier]} uses."
            )
    for caption in episode.captions:
        line = lines.get(caption.line_id)
        if not isinstance(line, _Dialogue):
            errors.append(f"Caption {caption.line_id!r} must refer to a dialogue line.")
        elif caption.text != line.text:
            errors.append(f"Caption {caption.line_id!r} must match dialogue text verbatim.")

    result.update(
        errors=errors, duration_seconds=float(total), dialogue_estimates=estimates, ok=not errors
    )
    if not errors:
        result["episode"] = episode.model_dump(mode="json")
    return result
