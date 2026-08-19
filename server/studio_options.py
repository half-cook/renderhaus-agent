"""Accepted values for local studio forms (prompts stay free text)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from providers.fish_audio.api import MODELS, VOICES
from providers.mureka.api import list_models as list_mureka_models
from providers.seedance.api import MAX_DURATION_SECONDS, MIN_DURATION_SECONDS


SEEDANCE_RATIOS = ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive")
SEEDREAM_RATIOS = ("1:1", "16:9", "9:16")
SEEDANCE_RESOLUTIONS = ("480p", "720p", "1080p")
SEEDREAM_SIZES = ("1K", "2K", "3K")
MUREKA_MODELS = tuple(list_mureka_models()["supported"])
MUREKA_PURPOSES = (
    "reference",
    "melody",
    "instrumental",
    "voice",
    "audio",
    "remix",
    "soundtrack",
    "lyrics-video",
)
MUREKA_TRACK_TYPES = ("vocals", "accompaniment", "instrument")

STATIC_FIELD_OPTIONS: dict[str, dict[str, list[str | int]]] = {
    "seedance": {
        "aspect_ratio": list(SEEDANCE_RATIOS),
        "resolution": list(SEEDANCE_RESOLUTIONS),
        "duration_seconds": list(range(MIN_DURATION_SECONDS, MAX_DURATION_SECONDS + 1)),
        "service_tier": ["default", "flex"],
        "model": ["seedance-1-5-pro-251215"],
    },
    "seedream": {
        "aspect_ratio": list(SEEDREAM_RATIOS),
        "size": list(SEEDREAM_SIZES),
        "response_format": ["url", "b64_json"],
        "model": ["seedream-5-0-lite-260128"],
    },
    "mureka": {
        "model": list(MUREKA_MODELS),
        "gender": ["male", "female"],
        "n": [1, 2, 3],
        "track_type": list(MUREKA_TRACK_TYPES),
        "purpose": list(MUREKA_PURPOSES),
        "aspect_ratio": ["16:9", "9:16", "1:1", "4:3", "3:4"],
    },
    "fish_audio": {
        "voice": list(VOICES),
        "output_format": ["wav", "mp3"],
        "model": list(MODELS),
    },
}

LIVE_CHOICE_TOOLS: tuple[tuple[str, str, str], ...] = (
    ("seedance", "list_seedance_models", "model"),
    ("seedream", "list_seedream_models", "model"),
    ("fish_audio", "list_voices", "voice"),
)


def extract_choice_ids(payload: Any) -> list[str]:
    found: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value and value not in found:
            found.append(value)

    if not isinstance(payload, dict):
        return found
    for key in ("supported", "voices"):
        values = payload.get(key)
        if isinstance(values, list):
            for item in values:
                add(item)
    models = payload.get("models")
    if models is None:
        models = payload.get("data")
    if isinstance(models, list):
        for item in models:
            if isinstance(item, str):
                add(item)
            elif isinstance(item, dict):
                add(item.get("id") or item.get("name"))
    return found


def static_field_options() -> dict[str, dict[str, list[str | int]]]:
    return deepcopy(STATIC_FIELD_OPTIONS)
