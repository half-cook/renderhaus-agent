"""Pure storyboard timing validation and compilation to the existing timeline API."""
from __future__ import annotations

from copy import deepcopy
import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from providers.shot_recipes.library import load_index, neutral_text

Seconds = Annotated[float, Field(ge=0, le=600)]
PositiveSeconds = Annotated[float, Field(gt=0, le=600)]
CardId = Annotated[str, Field(max_length=100, pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$')]
Cue = Literal['transition', 'impact', 'riser', 'ui', 'text', 'data', 'ambience', 'none']


class Contract(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)


class Beat(Contract):
    beat: Annotated[str, Field(min_length=1, max_length=100)]
    card_id: CardId
    start_s: Seconds
    duration_s: PositiveSeconds
    sfx_cue: Cue | None = None
    cut_snap: Seconds | None = None
    selection: Literal['agent', 'user_named'] = 'agent'
    visual: dict | None = None
    realization: Literal['pre_rendered_asset', 'timeline_preset'] = 'pre_rendered_asset'


class Stems(Contract):
    sfx: Annotated[list[dict], Field(max_length=100)]
    music: Annotated[list[dict], Field(max_length=100)]
    vo: Annotated[list[dict], Field(max_length=100)]


class Storyboard(Contract):
    target_duration_s: PositiveSeconds
    aspect: Literal['16:9', '9:16', '1:1', '4:5', '2.39:1']
    fps: Annotated[float, Field(ge=1, le=120)]
    beat_grid_s: Annotated[list[Seconds], Field(min_length=1, max_length=2000)]
    beats: Annotated[list[Beat], Field(min_length=1, max_length=100)]
    audio_stems: Stems
    named_cards: dict[Annotated[str, Field(min_length=1, max_length=100)], CardId] = Field(default_factory=dict, max_length=100)
    title: Annotated[str, Field(min_length=1, max_length=200)] = 'Product launch film'

    @model_validator(mode='before')
    @classmethod
    def bound_payload(cls, value):
        import json

        try:
            if len(json.dumps(value, ensure_ascii=False, allow_nan=False)) > 128 * 1024:
                raise ValueError('Storyboard exceeds 128 KiB.')
        except (TypeError, OverflowError, RecursionError):
            raise ValueError('Storyboard must be a bounded JSON object.') from None
        return value


def parse_storyboard(value: dict) -> Storyboard:
    try:
        return Storyboard.model_validate(value)
    except ValidationError as exc:
        messages = ['.'.join(str(p) for p in error['loc']) + ': ' + error['msg']
                    for error in exc.errors(include_input=False, include_url=False)]
        raise ValueError('; '.join(messages)) from None


def snap_cut(cut_s: float, beat_grid_s: list[float], fps: float) -> float:
    """Choose the nearest detected beat, then its nearest frame, with earlier ties."""
    values = [cut_s, fps, *beat_grid_s]
    if (not beat_grid_s or any(type(value) not in (int, float) or not math.isfinite(value) for value in values)
            or not 1 <= fps <= 120 or cut_s < 0 or any(value < 0 for value in beat_grid_s)):
        raise ValueError('Snapping requires finite nonnegative times, a beat grid and fps 1-120.')
    nearest = min(beat_grid_s, key=lambda beat: (abs(beat - cut_s), beat))
    return math.floor(nearest * fps + .5) / fps


def _render_plan(story: Storyboard) -> dict:
    from providers.catalog import get_provider
    from providers.registry import generate_schemas
    from providers.contracts import validate_tool_arguments

    stems = story.audio_stems.model_dump()
    visuals = []
    missing = []
    for beat in story.beats:
        if beat.visual is None:
            missing.append(neutral_text(beat.beat))
            continue
        visual = deepcopy(beat.visual)
        if any(field in visual for field in ('start_seconds', 'duration_seconds')):
            raise ValueError('Beat visual timing comes from start_s and duration_s; do not override it.')
        visuals.append({**visual, 'start_seconds': beat.start_s, 'duration_seconds': beat.duration_s,
                        'volume': 0})
    args = {'title': neutral_text(story.title), 'aspect_ratio': story.aspect, 'fps': story.fps,
            'visuals': visuals, 'audio_tracks': [deepcopy(track) for tracks in stems.values() for track in tracks]}
    schema = next(s for s in generate_schemas(get_provider('remotion')) if s['name'] == 'render_timeline')
    validate_tool_arguments('remotion', 'render_timeline', args, schema['inputSchema'],
                            allow_empty_visuals=bool(missing))
    total = sum(beat.duration_s for beat in story.beats)
    for tracks in stems.values():
        for track in tracks:
            if not track.get('url') and not track.get('output_path'):
                raise ValueError('Each stem track requires a supplied audio asset.')
            if 'duration_seconds' not in track:
                raise ValueError('Each stem track requires its measured duration_seconds.')
            start = float(track.get('start_seconds', 0))
            if start >= total or start + float(track['duration_seconds']) > total + 1e-9:
                raise ValueError('Audio stem tracks must remain inside the storyboard.')
    return {
        'audio_stems': stems, 'render_args': args, 'render_ready': not missing,
        'missing_visual_beats': missing,
        'stem_render_args': {stem: {**deepcopy(args), 'audio_tracks': deepcopy(tracks)}
                             for stem, tracks in stems.items()},
        'loudness_target': {'integrated_lufs': -14, 'tolerance_lu': 1},
        'visual_review': 'pending', 'media_qc': 'pending',
    }


def validate_storyboard(value: dict) -> dict:
    """Validate a plan without rendering, changing its cuts, or asserting media QC."""
    try:
        story = parse_storyboard(value)
        index = load_index()
        errors = []
        total = sum(beat.duration_s for beat in story.beats)
        if abs(total - story.target_duration_s) > story.target_duration_s * .05 + 1e-9:
            errors.append('Total beat duration must be within +/-5% of the target.')
        if story.beat_grid_s != sorted(set(story.beat_grid_s)):
            errors.append('The supplied beat grid must be sorted with unique times.')
        if len({beat.beat for beat in story.beats}) != len(story.beats):
            errors.append('Beat names must be unique.')
        end = 0
        tolerance = 1 / story.fps + 1e-9
        for i, beat in enumerate(story.beats):
            if beat.card_id not in index:
                errors.append(f'Beat {i + 1} has an unknown card id.')
            if abs(beat.start_s - end) > 1e-9:
                errors.append(f'Beat {i + 1} must start at the previous beat end.')
            if abs(beat.start_s * story.fps - round(beat.start_s * story.fps)) > 1e-6:
                errors.append(f'Beat {i + 1} cut must land on a frame.')
            if i and min(abs(beat.start_s - point) for point in story.beat_grid_s) > tolerance:
                errors.append(f'Beat {i + 1} cut is more than one frame from the supplied beat grid.')
            if beat.cut_snap is not None:
                if abs(beat.cut_snap - beat.start_s) > 1e-9:
                    errors.append(f'Beat {i + 1} cut_snap must equal its actual cut time.')
                if abs(beat.cut_snap - snap_cut(beat.start_s, story.beat_grid_s, story.fps)) > tolerance:
                    errors.append(f'Beat {i + 1} cut_snap must match the supplied beat grid within one frame.')
            end = beat.start_s + beat.duration_s
        by_name = {beat.beat: beat for beat in story.beats}
        for beat_name, card_id in story.named_cards.items():
            beat = by_name.get(beat_name)
            if card_id not in index or beat is None or beat.card_id != card_id or beat.selection != 'user_named':
                errors.append('Each user-named card must be used by its named beat with selection=user_named.')
        for beat in story.beats:
            if beat.selection == 'user_named' and story.named_cards.get(beat.beat) != beat.card_id:
                errors.append('Record each user-named selection in named_cards.')
        if errors:
            return {'ok': False, 'errors': errors}
        plan = _render_plan(story)
        warnings = ['Timing validation does not verify rendered stems, loudness, or visual acceptance.']
        if not story.audio_stems.sfx:
            warnings.append('An empty SFX stem is planned. No SFX assets were supplied.')
        if not plan['render_ready']:
            warnings.append('Supply rendered shot assets or supported timeline visuals before assembly.')
        return {'ok': True, 'render_plan': plan, 'duration_s': total, 'warnings': warnings}
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return {'ok': False, 'errors': [neutral_text(str(exc)) if isinstance(exc, ValueError)
                                      else 'Storyboard library or render contract is unavailable.']}
