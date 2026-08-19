"""Fish Audio TTS provider API."""

from __future__ import annotations

import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import httpx


FISH_BASE_URL = "https://api.fish.audio"
DEFAULT_MODEL = "s2.1-pro-free"
MODELS = ("s1", "s2-pro", "s2.1-pro", "s2.1-pro-free")
HEX_ID = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)

# Starter voices from https://docs.fish.audio/developer-guide/getting-started/quickstart
STARTER_VOICES: tuple[tuple[str, str], ...] = (
    ("Energetic Male", "9a9cf47702da476aa4629e2506d4a857"),
    ("E-Girl", "ca3007f96ae7499ab87d27ea3599956a"),
)
VOICES = [label for label, _voice_id in STARTER_VOICES]
VOICE_IDS = {label.lower(): voice_id for label, voice_id in STARTER_VOICES}


def _media_dir() -> Path:
    path = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def dry_run() -> bool:
    return os.getenv("FISH_AUDIO_DRY_RUN", "true").lower() != "false"


def _model(model: str | None = None) -> str:
    selected = (model or os.getenv("FISH_AUDIO_MODEL") or DEFAULT_MODEL).strip()
    return selected or DEFAULT_MODEL


def _api_key() -> str:
    key = (os.getenv("FISH_API_KEY") or os.getenv("FISH_AUDIO_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("FISH_API_KEY is required for live Fish Audio calls.")
    return key


def _headers(*, include_model: bool = False, model: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }
    if include_model:
        headers["model"] = _model(model)
    return headers


def _provider_error(response: httpx.Response) -> RuntimeError:
    try:
        payload = response.json()
    except ValueError:
        return RuntimeError(f"Fish Audio API error {response.status_code}: {response.text[:1000]}")
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("reason") or payload
        return RuntimeError(f"Fish Audio API error {response.status_code}: {message}")
    return RuntimeError(f"Fish Audio API error {response.status_code}: {payload}")


def _lookup_voice_id(title: str) -> str | None:
    with httpx.Client(timeout=20) as client:
        response = client.get(
            f"{FISH_BASE_URL}/model",
            headers=_headers(),
            params={"title": title, "page_size": 5, "page_number": 1},
        )
        if response.is_error:
            raise _provider_error(response)
        payload = response.json()
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return None
    lowered = title.lower()
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("title") or "").strip().lower() == lowered:
            voice_id = str(item.get("_id") or "").strip()
            if voice_id:
                return voice_id
    first = items[0] if items else None
    if isinstance(first, dict):
        voice_id = str(first.get("_id") or "").strip()
        return voice_id or None
    return None


def _resolve_voice(voice: str, *, lookup: bool = False) -> str | None:
    raw = voice.strip()
    if not raw:
        return None
    mapped = VOICE_IDS.get(raw.lower())
    if mapped:
        return mapped
    if HEX_ID.fullmatch(raw):
        return raw
    if lookup:
        found = _lookup_voice_id(raw)
        if found:
            return found
    return raw


def _suffix_for(format_name: str, content_type: str) -> str:
    mime = content_type.lower()
    if "wav" in mime or format_name == "wav":
        return ".wav"
    if "mpeg" in mime or "mp3" in mime or format_name == "mp3":
        return ".mp3"
    if "ogg" in mime or "opus" in mime:
        return ".ogg"
    return f".{format_name}" if format_name else ".mp3"


def list_voices() -> dict:
    """List starter Fish Audio voices, plus popular public models when live."""
    voices = list(VOICES)
    voice_ids = {label: voice_id for label, voice_id in STARTER_VOICES}
    note = "Starter voices from the Fish Audio quickstart. Paste any fish.audio model id."
    if dry_run():
        return {
            "provider": "fish-audio",
            "model": _model(),
            "voices": voices,
            "voice_ids": voice_ids,
            "note": note,
        }
    try:
        with httpx.Client(timeout=20) as client:
            response = client.get(
                f"{FISH_BASE_URL}/model",
                headers=_headers(),
                params={"page_size": 20, "page_number": 1, "sort_by": "task_count"},
            )
            if response.is_error:
                raise _provider_error(response)
            payload = response.json()
    except Exception as exc:  # noqa: BLE001 - live catalog is optional
        return {
            "provider": "fish-audio",
            "model": _model(),
            "voices": voices,
            "voice_ids": voice_ids,
            "note": f"{note} Live catalog unavailable: {exc}",
        }
    items = payload.get("items") if isinstance(payload, dict) else None
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            voice_id = str(item.get("_id") or "").strip()
            if not title or not voice_id:
                continue
            voice_ids.setdefault(title, voice_id)
            if title not in voices:
                voices.append(title)
    return {
        "provider": "fish-audio",
        "model": _model(),
        "voices": voices,
        "voice_ids": voice_ids,
        "note": note,
    }


def generate_speech(
    text: str,
    voice: str = "Energetic Male",
    output_format: Literal["wav", "mp3"] = "mp3",
    model: Literal["s1", "s2-pro", "s2.1-pro", "s2.1-pro-free"] | None = None,
) -> dict:
    """Generate Fish Audio speech and save a local audio file when live."""
    job_id = f"fish_audio_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    selected_model = _model(model)
    requested = str(output_format or "mp3").strip().lower().lstrip(".") or "mp3"
    if requested not in {"wav", "mp3"}:
        requested = "mp3"
    audio_dir = _media_dir() / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    placeholder = audio_dir / f"{job_id}.{requested}"

    if dry_run():
        reference_id = _resolve_voice(voice)
        return {
            "job_id": job_id,
            "status": "dry_run",
            "provider": "fish-audio",
            "model": selected_model,
            "voice": voice,
            "reference_id": reference_id,
            "text": text,
            "output_path": str(placeholder),
            "note": "Dry run only. Set FISH_AUDIO_DRY_RUN=false to generate live Fish Audio speech.",
        }

    reference_id = _resolve_voice(voice, lookup=True)
    body: dict[str, Any] = {
        "text": text,
        "format": requested,
    }
    if reference_id:
        body["reference_id"] = reference_id
    url = f"{FISH_BASE_URL}/v1/tts"
    with httpx.Client(timeout=180) as client:
        response = client.post(
            url,
            headers=_headers(include_model=True, model=selected_model),
            json=body,
        )
        if response.is_error:
            raise _provider_error(response)
        audio_bytes = response.content
    if not audio_bytes:
        raise RuntimeError("Fish Audio returned empty audio data.")
    suffix = _suffix_for(requested, response.headers.get("content-type", ""))
    output_path = (audio_dir / f"{job_id}{suffix}").resolve()
    output_path.write_bytes(audio_bytes)
    return {
        "job_id": job_id,
        "status": "succeeded",
        "provider": "fish-audio",
        "model": selected_model,
        "voice": voice,
        "reference_id": reference_id,
        "text": text,
        "output_path": str(output_path),
        "mime_type": response.headers.get("content-type", ""),
        "note": "Fish Audio speech generated.",
    }


def estimate_tts_cost(text: str) -> dict:
    """Return simple character-count data for Fish Audio TTS cost planning."""
    return {
        "provider": "fish-audio",
        "characters": len(text),
        "note": "Pricing is provider/account dependent; use this count for preflight estimates.",
    }


TOOL_HANDLERS: dict[str, Any] = {
    "list_voices": list_voices,
    "generate_speech": generate_speech,
    "estimate_tts_cost": estimate_tts_cost,
}

GATEWAY_TOOLS = (
    "list_voices",
    "generate_speech",
    "estimate_tts_cost",
)
