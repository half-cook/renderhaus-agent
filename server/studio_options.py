"""Accepted values for local studio forms (prompts stay free text)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from providers.fish_audio.api import MODELS, VOICES
from providers.runway.contracts import I2V_RATIOS, IMAGE_RATIOS
from providers.fal.wan import ASPECT_RATIOS, EDIT_MODES, MODELS as FAL_MODELS, RESOLUTIONS
from providers.fal import wan3, mirelo
from providers.luma.catalog import (
    ASPECT_RATIOS as LUMA_ASPECT_RATIOS,
    DURATIONS as LUMA_DURATIONS,
    EDIT_STRENGTHS as LUMA_EDIT_STRENGTHS,
    MODEL_IDS as LUMA_MODEL_IDS,
    RESOLUTIONS as LUMA_RESOLUTIONS,
)
from providers.seedance.api import MAX_DURATION_SECONDS, MIN_DURATION_SECONDS
from providers.openai_images import contracts as openai_images


SEEDANCE_RATIOS = ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive")
SEEDREAM_RATIOS = ("1:1", "16:9", "9:16")
SEEDANCE_RESOLUTIONS = ("480p", "720p", "1080p")
SEEDREAM_SIZES = ("1K", "2K", "3K")
STATIC_FIELD_OPTIONS: dict[str, dict[str, list[str | int]]] = {
    "mureka": {
        "model": ["mureka-9.5"], "aspect_ratio": ["16:9", "9:16", "3:4", "4:3"],
        "layout": [f"layout_{i}" for i in range(1, 8)], "gender": ["female", "male"],
        "styles": ["pop", "rock", "jazz", "r&b", "edm", "ambient", "folk", "latin", "k-pop", "j-pop", "house", "gospel", "lo-fi"],
    },
    "topaz": {
        "model": ["Starlight Precise 2.6", "Apollo", "Chronos"],
        "target_resolution": ["1080p", "4K"],
    },
    "heygen": {
        "model": ["avatar_v"], "resolution": ["720p", "1080p"],
        "aspect_ratio": ["16:9", "9:16", "4:5", "5:4", "1:1", "auto"],
    },
    "sync": {
        "model": ["sync-3"],
        "sync_mode": ["cut_off", "loop", "bounce", "silence", "remap"],
    },
    "openai_images": {
        "model": list(openai_images.MODELS), "aspect_ratio": list(openai_images.RATIOS),
        "size": list(openai_images.SIZES), "quality": list(openai_images.QUALITY),
        "background": ["auto", "opaque", "transparent"],
        "output_format": list(openai_images.FORMAT), "moderation": ["auto", "low"],
        "n": list(range(1, 11)),
    },
    "kling": {
        "aspect_ratio": ["16:9", "9:16", "1:1"],
        "resolution": ["720p", "1080p", "4k"],
        "duration_seconds": list(range(3, 16)),
        "model": ["kling-3.0", "kling-3.0-turbo", "kling-3.0-omni"],
    },
    "runway": {
        "model": ["gen4.5", "aleph2", "gen4_image", "gen4_image_turbo", "act_two"],
        "character_type": ["image", "video"], "boundary_kind": ["shot", "silence"],
        "ratio": list(dict.fromkeys(I2V_RATIOS + IMAGE_RATIOS)),
        "duration_seconds": list(range(2, 11)),
    },
    "fal": {
        "character_orientation": ["video", "image"],
        "model": list(FAL_MODELS) + list(wan3.ENDPOINTS) + ["fal-ai/kling-video/v3/pro/motion-control", mirelo.ENDPOINT_ID],
        "num_samples": [1, 2, 3, 4],
        "aspect_ratio": list(dict.fromkeys((*ASPECT_RATIOS, *wan3.ASPECT_RATIOS))),
        "resolution": list(dict.fromkeys((*RESOLUTIONS, *wan3.RESOLUTIONS))),
        "duration": list(range(2, 31)),
        "edit_mode": list(EDIT_MODES),
        "task": list(EDIT_MODES[1:]),
    },
    "luma": {
        "model": list(LUMA_MODEL_IDS),
        "aspect_ratio": list(LUMA_ASPECT_RATIOS),
        "resolution": list(LUMA_RESOLUTIONS),
        "duration_seconds": list(LUMA_DURATIONS),
        "source_duration_seconds": list(LUMA_DURATIONS),
        "direction": ["forward", "backward"],
        "strength": list(LUMA_EDIT_STRENGTHS),
    },
    "alibaba_modelstudio": {
        "aspect_ratio": ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
        "resolution": ["480p", "720p", "1080p"],
        "duration": [-1, *range(2, 31)],
        "direction": ["forward", "backward", "both"],
    },
    "seedance": {
        "aspect_ratio": list(SEEDANCE_RATIOS),
        "resolution": list(SEEDANCE_RESOLUTIONS),
        "duration_seconds": list(range(MIN_DURATION_SECONDS, MAX_DURATION_SECONDS + 1)),
        "service_tier": ["default", "flex"],
        "model": ["dreamina-seedance-2-5-260628", "seedance-1-5-pro-251215"],
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
    ("heygen", "list_avatars", "avatar_id"),
    ("heygen", "list_voices", "voice_id"),
    ("kling", "list_kling_models", "model"),
    ("fal", "list_fal_models", "model"),
    ("luma", "list_luma_models", "model"),
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
                add(item.get("id") or item.get("voice_id") or item.get("name"))
    return found


def static_field_options() -> dict[str, dict[str, list[str | int]]]:
    return deepcopy(STATIC_FIELD_OPTIONS)
