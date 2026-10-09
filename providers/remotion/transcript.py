from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Any, Literal

from providers.contracts import validate_remotion_text_items


Grade = Literal["none", "neutral", "warm"]
ASPECT_RATIOS = {"16:9", "9:16", "1:1", "2.39:1"}
AUDIO_FADE_SECONDS = 0.03


@dataclass(frozen=True, slots=True)
class TimedWord:
    text: str
    start: float
    end: float


@dataclass(frozen=True, slots=True)
class TranscriptSource:
    id: str
    url: str
    duration: float
    words: tuple[TimedWord, ...]
    audio_events: tuple[TimedWord, ...]


@dataclass(frozen=True, slots=True)
class WordCut:
    source: TranscriptSource
    first_word: int
    last_word: int
    first_frame: int
    end_frame: int


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a finite number.")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"{path} must be a finite number.") from exc
    if not math.isfinite(result):
        raise ValueError(f"{path} must be a finite number.")
    return result


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be non-empty text.")
    return value.strip()


def _record(value: Any, required: set[str], optional: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object.")
    if set(value) - required - optional:
        raise ValueError(f"{path} contains unsupported fields.")
    if required - set(value):
        raise ValueError(f"{path} is missing required fields.")
    return value


def _parse_sources(raw_sources: list[dict[str, Any]]) -> dict[str, TranscriptSource]:
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ValueError("sources must contain at least one transcript source.")
    sources: dict[str, TranscriptSource] = {}
    for index, raw in enumerate(raw_sources):
        path = f"sources[{index}]"
        raw = _record(raw, {"id", "url", "duration_seconds", "words"}, {"metadata"}, path)
        identifier = _text(raw["id"], f"{path}.id")
        if identifier in sources:
            raise ValueError("Source ids must be unique.")
        url = _text(raw["url"], f"{path}.url")
        duration = _number(raw["duration_seconds"], f"{path}.duration_seconds")
        if duration <= 0:
            raise ValueError(f"{path}.duration_seconds must be greater than 0.")
        if "metadata" in raw and not isinstance(raw["metadata"], dict):
            raise ValueError(f"{path}.metadata must be an object.")
        if not isinstance(raw["words"], list) or not raw["words"]:
            raise ValueError(f"{path}.words must be a non-empty token list.")
        words: list[TimedWord] = []
        audio_events: list[TimedWord] = []
        previous_end = 0.0
        for token_index, token in enumerate(raw["words"]):
            token_path = f"{path}.words[{token_index}]"
            token = _record(token, {"text", "start", "end"}, {"type"}, token_path)
            kind = token.get("type", "word")
            if not isinstance(kind, str) or kind not in {"word", "spacing", "silence", "audio_event"}:
                raise ValueError(f"{token_path}.type must be word, spacing, silence, or audio_event.")
            if not isinstance(token["text"], str):
                raise ValueError(f"{token_path}.text must be text.")
            start = _number(token["start"], f"{token_path}.start")
            end = _number(token["end"], f"{token_path}.end")
            if start < previous_end or end > duration or end < start or (kind != "spacing" and end == start):
                raise ValueError(f"{token_path} timing must be ordered, non-overlapping, and inside the source.")
            previous_end = end
            if kind == "word":
                words.append(TimedWord(_text(token["text"], f"{token_path}.text"), start, end))
            elif kind == "audio_event":
                audio_events.append(TimedWord(token["text"], start, end))
        if not words:
            raise ValueError(f"{path} must contain at least one type=word token.")
        sources[identifier] = TranscriptSource(identifier, url, duration, tuple(words), tuple(audio_events))
    return sources


def _floor_frame(seconds: float, fps: int) -> int:
    return math.floor(seconds * fps + 1e-9)


def _ceil_frame(seconds: float, fps: int) -> int:
    return math.ceil(seconds * fps - 1e-9)


def _parse_cuts(raw_segments: list[dict[str, Any]], sources: dict[str, TranscriptSource], fps: int) -> tuple[WordCut, ...]:
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("segments must contain at least one kept word range.")
    cuts: list[WordCut] = []
    for index, raw in enumerate(raw_segments):
        path = f"segments[{index}]"
        raw = _record(raw, {"source_id", "first_word", "last_word"}, {"padding_seconds"}, path)
        source_id = _text(raw["source_id"], f"{path}.source_id")
        if source_id not in sources:
            raise ValueError(f"{path}.source_id must identify an existing source.")
        source = sources[source_id]
        first, last = raw["first_word"], raw["last_word"]
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (first, last)):
            raise ValueError(f"{path} word indices must be integers.")
        if not 0 <= first <= last < len(source.words):
            raise ValueError(f"{path} must be an inclusive, ordered type=word index range.")
        padding = _number(raw.get("padding_seconds", 0.05), f"{path}.padding_seconds")
        if not 0.03 <= padding <= 0.2:
            raise ValueError(f"{path}.padding_seconds must be between 0.03 and 0.2.")
        start, end = source.words[first].start, source.words[last].end
        lower = source.words[first - 1].end if first else 0.0
        upper = source.words[last + 1].start if last + 1 < len(source.words) else source.duration
        for event in source.audio_events:
            if event.end <= start:
                lower = max(lower, event.end)
            elif event.start >= end:
                upper = min(upper, event.start)
            else:
                raise ValueError(f"{path} crosses an audio_event. Split the kept range around the event.")
        first_min, first_max = _ceil_frame(lower, fps), _floor_frame(start, fps)
        end_min, end_max = _ceil_frame(end, fps), _floor_frame(upper, fps)
        if first_min > first_max or end_min > end_max:
            raise ValueError(f"{path} has no safe frame boundary. Include the adjacent word or use a higher fps.")
        first_frame = max(first_min, min(_ceil_frame(start - padding, fps), first_max))
        end_frame = min(end_max, max(_floor_frame(end + padding, fps), end_min))
        cuts.append(WordCut(source, first, last, first_frame, end_frame))
    return tuple(cuts)


def _captions(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    captions: list[dict[str, Any]] = []
    phrase: list[dict[str, Any]] = []
    for word in words:
        if phrase and (len(phrase) == 6 or len(" ".join(item["text"] for item in phrase + [word])) > 42):
            captions.append(_caption(phrase))
            phrase = []
        phrase.append(word)
    if phrase:
        captions.append(_caption(phrase))
    return captions


def _caption(words: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "text": " ".join(word["text"] for word in words),
        "start_seconds": words[0]["start"],
        "duration_seconds": words[-1]["end"] - words[0]["start"],
        "position": "bottom",
        "font_size": 56,
        "background_color": "#000000b3",
        "fade_in_seconds": 0,
        "fade_out_seconds": 0,
    }


def build_conversational_edit(
    title: str,
    plan_summary: str,
    sources: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    overlays: list[dict[str, Any]] | None = None,
    grade: Grade = "none",
    subtitles: bool = True,
    aspect_ratio: str = "9:16",
    fps: int = 30,
) -> dict[str, Any]:
    title = _text(title, "title")
    plan_summary = _text(plan_summary, "plan_summary")
    if isinstance(fps, bool) or not isinstance(fps, int) or not 12 <= fps <= 60:
        raise ValueError("fps must be an integer between 12 and 60.")
    if not isinstance(aspect_ratio, str) or aspect_ratio not in ASPECT_RATIOS:
        raise ValueError("aspect_ratio must be 16:9, 9:16, 1:1, or 2.39:1.")
    if not isinstance(grade, str) or grade not in {"none", "neutral", "warm"}:
        raise ValueError("grade must be none, neutral, or warm.")
    if not isinstance(subtitles, bool):
        raise ValueError("subtitles must be boolean.")
    validate_remotion_text_items(overlays if overlays is not None else [], "overlays")
    cuts = _parse_cuts(segments, _parse_sources(sources), fps)
    visuals: list[dict[str, Any]] = []
    output_words: list[dict[str, Any]] = []
    output_cuts: list[dict[str, Any]] = []
    captions: list[dict[str, Any]] = []
    output_frame = 0
    for segment_index, cut in enumerate(cuts):
        source_in, source_out = cut.first_frame / fps, cut.end_frame / fps
        duration = (cut.end_frame - cut.first_frame) / fps
        output_start = output_frame / fps
        audio_fade = min(AUDIO_FADE_SECONDS, duration / 2)
        visuals.append({
            "kind": "video", "url": cut.source.url, "start_seconds": output_start,
            "source_in_seconds": source_in, "duration_seconds": duration, "transition": "cut",
            "grade": grade, "fade_in_seconds": 0, "fade_out_seconds": 0,
            "audio_fade_in_seconds": audio_fade, "audio_fade_out_seconds": audio_fade,
        })
        segment_words = [{
            "text": word.text, "start": output_start + word.start - source_in,
            "end": output_start + word.end - source_in, "source_id": cut.source.id,
            "source_word_index": word_index, "segment_index": segment_index,
        } for word_index, word in enumerate(cut.source.words[cut.first_word:cut.last_word + 1],
                                           start=cut.first_word)]
        output_words.extend(segment_words)
        if subtitles:
            captions.extend(_captions(segment_words))
        output_frame += cut.end_frame - cut.first_frame
        output_cuts.append({
            "source_id": cut.source.id, "first_word": cut.first_word, "last_word": cut.last_word,
            "source_in_seconds": source_in, "source_out_seconds": source_out,
            "output_start_seconds": output_start, "output_end_seconds": output_frame / fps,
        })
    for overlay in overlays or []:
        if overlay["start_seconds"] + overlay["duration_seconds"] > output_frame / fps + 1e-9:
            raise ValueError("overlays must fit inside the edited output duration.")
    return {
        "status": "dry_run",
        "plan_summary": plan_summary,
        "render_arguments": {
            "title": title, "visuals": visuals, "text_overlays": copy.deepcopy(overlays or []),
            "subtitles": copy.deepcopy(captions), "aspect_ratio": aspect_ratio, "fps": fps,
        },
        "transcript": {"text": " ".join(word["text"] for word in output_words), "words": output_words},
        "captions": captions,
        "cuts": output_cuts,
        "qc_expectations": {
            "expected_duration_seconds": output_frame / fps, "duration_in_frames": output_frame,
            "word_count": len(output_words), "cut_count": len(cuts), "subtitle_count": len(captions),
            "kept_words_complete": True, "captions_last": True,
            "audio_fade_target_seconds": AUDIO_FADE_SECONDS,
            "audio_fade_limitation": "Audio fades use a per-frame envelope, not sample-accurate smoothing. Listen to the rendered cuts during QC.",
            "render_required": True,
        },
    }
