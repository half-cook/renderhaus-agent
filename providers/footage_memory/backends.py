"""Offline footage understanding candidates. No transport or credentials are implemented.

The hosted candidate shares GeminiSettings with the existing continuity judge.
Live integration, per-window pricing and quality remain UNVERIFIED here.
Official video guide and pricing read 2026-10-10:
https://ai.google.dev/gemini-api/docs/video-understanding
https://ai.google.dev/gemini-api/docs/pricing
Hosted licence is service terms: https://ai.google.dev/gemini-api/terms
The disabled candidate requires international service-term and US/Canada review.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import re
from typing import Callable, Protocol, runtime_checkable

from providers.gemini.contracts import GeminiSettings


@dataclass(frozen=True)
class MediaWindow:
    path: Path
    t0_s: float
    t1_s: float
    content_hash: str
    fixture_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.path, Path):
            raise ValueError("Footage media must have a local path.")
        if (
            any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in (self.t0_s, self.t1_s)
            )
            or self.t0_s < 0
            or self.t1_s - self.t0_s < 0.001
        ):
            raise ValueError("Footage window must span at least one millisecond at finite times.")
        if not isinstance(self.content_hash, str) or not self.content_hash:
            raise ValueError("Footage content hash is required.")
        if self.fixture_id is not None and not isinstance(self.fixture_id, str):
            raise ValueError("Footage fixture identifier must be a string.")


@runtime_checkable
class Backend(Protocol):
    name: str
    backend_ref: str
    dry_run: bool

    def describe_window(self, window_media: MediaWindow, prompt: str) -> list[dict]: ...

    def answer(self, question: str, window_media: MediaWindow) -> dict: ...


@lru_cache(maxsize=1)
def _fixtures() -> dict:
    return json.loads(Path(__file__).with_name("fixtures.json").read_text(encoding="utf-8"))


_IGNORED_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "be",
    "clip",
    "did",
    "do",
    "every",
    "find",
    "footage",
    "give",
    "happened",
    "in",
    "is",
    "it",
    "me",
    "moment",
    "of",
    "on",
    "or",
    "same",
    "segment",
    "that",
    "the",
    "this",
    "to",
    "verify",
    "was",
    "what",
    "when",
    "where",
    "with",
}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - _IGNORED_WORDS


@dataclass(frozen=True)
class MockBackend:
    name: str = "mock"
    backend_ref: str = "mock:synthetic-v1"
    dry_run: bool = True

    def describe_window(self, window_media: MediaWindow, prompt: str) -> list[dict]:
        lower_ms = math.ceil(window_media.t0_s * 1000)
        upper_ms = math.floor(window_media.t1_s * 1000)
        if upper_ms <= lower_ms:
            raise ValueError("Footage window contains no complete millisecond.")
        span_ms = upper_ms - lower_ms
        events = []
        for template in _fixtures()["event_templates"]:
            start = min(upper_ms - 1, lower_ms + int(template["start_fraction"] * span_ms))
            end = min(upper_ms, max(start + 1, lower_ms + int(template["end_fraction"] * span_ms)))
            events.append(
                {
                    "kind": template["kind"],
                    "t0_ms": start,
                    "t1_ms": end,
                    "speaker_id": template.get("speaker_id"),
                    "speaker_label": "Guest" if template.get("speaker_id") else None,
                    "text": template["text"],
                    "confidence": template["confidence"],
                    "attrs_json": {**deepcopy(template.get("attrs", {})), "simulated": True},
                }
            )
        if window_media.fixture_id is not None:
            source = next(
                (media for media in _fixtures()["media"] if media["id"] == window_media.fixture_id),
                None,
            )
            if source is None:
                raise ValueError("Footage fixture does not exist.")
            for event in source["events"]:
                start = max(lower_ms, event["t0_ms"])
                end = min(upper_ms, event["t1_ms"])
                if start < end:
                    events.append(
                        {
                            **deepcopy(event),
                            "t0_ms": start,
                            "t1_ms": end,
                            "speaker_id": event.get("speaker_id"),
                            "speaker_label": "Guest" if event.get("speaker_id") else None,
                            "confidence": 0.8,
                            "attrs_json": {"simulated": True},
                        }
                    )
        return sorted(events, key=lambda event: (event["t0_ms"], event["kind"], event["text"]))

    def answer(self, question: str, window_media: MediaWindow) -> dict:
        terms = _tokens(question)
        events = self.describe_window(window_media, question)
        ranked = sorted(
            ((len(terms & _tokens(event["text"])), event) for event in events),
            key=lambda item: (-item[0], item[1]["t0_ms"], item[1]["kind"], item[1]["text"]),
        )
        if not ranked or not ranked[0][0]:
            return {
                "answer": "Simulated review found no matching observation in this window.",
                "t0_s": window_media.t0_s,
                "t1_s": window_media.t1_s,
                "verdict": "ambiguous",
                "confidence": 0.0,
                "simulated": True,
            }
        event = ranked[0][1]
        return {
            "answer": "Simulated observation. " + event["text"],
            "t0_s": event["t0_ms"] / 1000,
            "t1_s": event["t1_ms"] / 1000,
            "verdict": "verified",
            "confidence": event["confidence"],
            "simulated": True,
        }


def _gemini_candidate() -> Backend:
    try:
        settings = GeminiSettings.from_env()
    except ValueError:
        raise ValueError("Footage analysis configuration is invalid.") from None
    return MockBackend(
        name="gemini", backend_ref=f"gemini:{settings.model}:synthetic-v1", dry_run=True
    )


def _disabled_candidate() -> Backend:
    raise ValueError("This footage memory backend is disabled pending access and terms review.")


BACKENDS: dict[str, Callable[[], Backend]] = {
    "mock": MockBackend,
    "gemini": _gemini_candidate,
    "qwen_omni": _disabled_candidate,
}


def get_backend(name: str | None = None, *, allow_third_party_vlm: bool = False) -> Backend:
    selected = name if name is not None else os.getenv("FOOTAGE_MEMORY_BACKEND", "gemini")
    if not isinstance(selected, str) or selected not in BACKENDS:
        raise ValueError("Unknown footage memory backend selection.")
    if type(allow_third_party_vlm) is not bool:
        raise ValueError("Third-party footage permission must be a boolean.")
    flag = os.getenv("FOOTAGE_MEMORY_DRY_RUN", "true").strip().lower()
    if flag not in {"true", "false"}:
        raise ValueError("Footage memory dry-run setting must be true or false.")
    if selected == "qwen_omni":
        return BACKENDS[selected]()
    if selected != "mock" and flag == "false":
        if not allow_third_party_vlm:
            raise ValueError("Third-party footage analysis is not enabled for this project.")
        raise ValueError("Live footage analysis is not implemented; use dry-run.")
    return BACKENDS[selected]()
