"""Accepted values for local studio forms (prompts stay free text)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from providers.fish_audio.api import MODELS, VOICES
from providers.runway.contracts import I2V_RATIOS, IMAGE_RATIOS
from providers.fal.wan import ASPECT_RATIOS, EDIT_MODES, MODELS as FAL_MODELS, RESOLUTIONS
from providers.seedance.api import MAX_DURATION_SECONDS, MIN_DURATION_SECONDS


SEEDANCE_RATIOS = ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive")
SEEDREAM_RATIOS = ("1:1", "16:9", "9:16")
SEEDANCE_RESOLUTIONS = ("480p", "720p", "1080p")
SEEDREAM_SIZES = ("1K", "2K", "3K")
STATIC_FIELD_OPTIONS: dict[str, dict[str, list[str | int]]] = {
    "kling": {
        "aspect_ratio": ["16:9", "9:16", "1:1"],
        "resolution": ["720p", "1080p", "4k"],
        "duration_seconds": list(range(3, 16)),
        "model": ["kling-3.0", "kling-3.0-turbo", "kling-3.0-omni"],
    },
    "runway": {
        "model": ["gen4.5", "aleph2", "gen4_image", "gen4_image_turbo"],
        "ratio": list(dict.fromkeys(I2V_RATIOS + IMAGE_RATIOS)),
        "duration_seconds": list(range(2, 11)),
    },
    "fal": {
        "model": list(FAL_MODELS),
        "aspect_ratio": list(ASPECT_RATIOS),
        "resolution": list(RESOLUTIONS),
        "edit_mode": list(EDIT_MODES),
        "task": list(EDIT_MODES[1:]),
    },
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
    "fish_audio": {
        "voice": list(VOICES),
        "output_format": ["wav", "mp3"],
        "model": list(MODELS),
    },
}

LIVE_CHOICE_TOOLS: tuple[tuple[str, str, str], ...] = (
    ("kling", "list_kling_models", "model"),
    ("fal", "list_fal_models", "model"),
    ("seedance", "list_seedance_models", "model"),
    ("seedream", "list_seedream_models", "model"),
    ("elevenlabs", "voices_search", "voice_id"),
)


def extract_choice_ids(payload: Any) -> list[str]:
    found: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value and value not in found:
            found.append(value)

    if not isinstance(payload, dict):
        return found
    if isinstance(payload.get("result"), dict):
        payload = payload["result"]
    for key in ("supported", "voices"):
        values = payload.get(key)
        if isinstance(values, list):
            for item in values:
                if isinstance(item, str):
                    add(item)
                elif isinstance(item, dict):
                    add(item.get("voice_id"))
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
