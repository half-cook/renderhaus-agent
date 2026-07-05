from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

from fastmcp import FastMCP
from pydantic import Field


mcp = FastMCP("renderhaus-gemini-tts")

VOICES = [
    "Zephyr",
    "Puck",
    "Charon",
    "Kore",
    "Fenrir",
    "Leda",
    "Orus",
    "Aoede",
    "Callirrhoe",
    "Autonoe",
]


def _media_dir() -> Path:
    path = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _dry_run() -> bool:
    return os.getenv("GEMINI_TTS_DRY_RUN", "true").lower() != "false"


@mcp.tool()
def list_voices() -> dict:
    """List a starter set of Gemini TTS voice names for prompt planning."""
    return {
        "provider": "google-gemini-tts",
        "model": os.getenv("GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview"),
        "voices": VOICES,
        "note": "Voice list is a starter set. Confirm against Google docs before production.",
    }


@mcp.tool()
def generate_speech(
    text: str = Field(description="Exact text to synthesize."),
    voice: str = Field(default="Zephyr"),
    style_prompt: str = Field(default="Natural narration, clear pacing."),
    output_format: str = Field(default="wav"),
) -> dict:
    """Generate Gemini TTS speech. Currently dry-runs the provider call."""
    job_id = f"gemini_tts_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    output_path = _media_dir() / "audio" / f"{job_id}.{output_format}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return {
        "job_id": job_id,
        "status": "dry_run" if _dry_run() else "queued",
        "provider": "google-gemini-tts",
        "model": os.getenv("GEMINI_TTS_MODEL", "gemini-3.1-flash-tts-preview"),
        "voice": voice,
        "style_prompt": style_prompt,
        "text": text,
        "output_path": str(output_path),
        "note": (
            "Dry run only. Set GEMINI_TTS_DRY_RUN=false after implementing the Gemini API call."
            if _dry_run()
            else "Live mode is enabled, but the Gemini API call is not implemented yet."
        ),
    }


@mcp.tool()
def estimate_tts_cost(text: str) -> dict:
    """Return simple character-count data for Gemini TTS cost planning."""
    return {
        "provider": "google-gemini-tts",
        "characters": len(text),
        "note": "Pricing is provider/account dependent; use this count for preflight estimates.",
    }


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
