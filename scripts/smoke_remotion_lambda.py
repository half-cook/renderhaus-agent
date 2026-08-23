#!/usr/bin/env python3
"""Render the first successful multi-tool run through Remotion Lambda."""

from __future__ import annotations

import json
from pathlib import Path

from agent.remotion_renderer import render_timeline_and_wait
from server.config import ROOT, load_local_env


IMAGE = ROOT / ".renderhaus" / "media" / "images" / "seedream_1787469012_d26bfd9d.jpg"
VOICEOVER = ROOT / ".renderhaus" / "media" / "audio" / "fish_audio_1787469012_5157b599.mp3"
MUSIC = ROOT / ".renderhaus" / "media" / "music" / "156847283896321.mp3"
VIDEO = ROOT / ".renderhaus" / "media" / "video" / "cgt-20260823151044-6jx5l.mp4"


def first_run_input_props() -> dict[str, object]:
    for path in (IMAGE, VOICEOVER, MUSIC, VIDEO):
        if not path.is_file() or path.stat().st_size <= 0:
            raise FileNotFoundError(f"Missing first-run artifact: {path}")
    return {
        "document": {
            "id": "first-agent-run",
            "name": "First agent run — Remotion Lambda test",
            "assets": [
                {
                    "id": "hero-image",
                    "name": IMAGE.name,
                    "kind": "image",
                    "url": str(IMAGE),
                    "durationSec": 3.0,
                },
                {
                    "id": "generated-video",
                    "name": VIDEO.name,
                    "kind": "video",
                    "url": str(VIDEO),
                    "durationSec": 8.04,
                },
                {
                    "id": "voiceover",
                    "name": VOICEOVER.name,
                    "kind": "audio",
                    "url": str(VOICEOVER),
                    "durationSec": 2.98,
                },
                {
                    "id": "music",
                    "name": MUSIC.name,
                    "kind": "audio",
                    "url": str(MUSIC),
                    "durationSec": 192.27,
                },
            ],
            "tracks": [
                {
                    "id": "video-1",
                    "kind": "video",
                    "name": "Visuals",
                    "items": [
                        {
                            "id": "hero-clip",
                            "type": "clip",
                            "assetId": "hero-image",
                            "start": 0,
                            "duration": 3.0,
                            "sourceIn": 0,
                            "sourceOut": 3.0,
                        },
                        {
                            "id": "video-clip",
                            "type": "clip",
                            "assetId": "generated-video",
                            "start": 3.0,
                            "duration": 8.04,
                            "sourceIn": 0,
                            "sourceOut": 8.04,
                        },
                    ],
                },
                {
                    "id": "voiceover-track",
                    "kind": "audio",
                    "name": "Voiceover",
                    "items": [
                        {
                            "id": "voiceover-clip",
                            "type": "clip",
                            "assetId": "voiceover",
                            "start": 0,
                            "duration": 2.98,
                            "sourceIn": 0,
                            "sourceOut": 2.98,
                            "volume": 1.0,
                        }
                    ],
                },
                {
                    "id": "music-track",
                    "kind": "audio",
                    "name": "Music",
                    "items": [
                        {
                            "id": "music-clip",
                            "type": "clip",
                            "assetId": "music",
                            "start": 0,
                            "duration": 11.04,
                            "sourceIn": 0,
                            "sourceOut": 11.04,
                            "volume": 0.14,
                        }
                    ],
                },
            ],
        },
        "renderConfig": {"fps": 30, "width": 1080, "height": 1920},
    }


def main() -> int:
    load_local_env()
    result = render_timeline_and_wait(
        first_run_input_props(),
        output_filename="first-agent-run-remotion.mp4",
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
