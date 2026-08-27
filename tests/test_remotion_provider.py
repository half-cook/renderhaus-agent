from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from providers.remotion.api import build_timeline_props, get_render_progress, render_timeline


class RemotionProviderTests(unittest.TestCase):
    def test_build_timeline_props_maps_clips_to_document(self) -> None:
        props = build_timeline_props(
            "Launch cut",
            visuals=[
                {
                    "kind": "image",
                    "url": "https://example/hero.png",
                    "start_seconds": 0,
                    "duration_seconds": 2,
                }
            ],
            audio_tracks=[
                {
                    "url": "https://example/voice.mp3",
                    "start_seconds": 0,
                    "duration_seconds": 2,
                    "volume": 0.8,
                }
            ],
            aspect_ratio="9:16",
            fps=30,
        )
        document = props["document"]
        self.assertEqual(document["name"], "Launch cut")
        self.assertEqual(document["assets"][0]["url"], "https://example/hero.png")
        self.assertEqual(document["assets"][1]["kind"], "audio")
        self.assertEqual(props["renderConfig"]["width"], 1080)
        self.assertEqual(props["renderConfig"]["height"], 1920)

    def test_dry_run_render_does_not_need_remotion_config(self) -> None:
        with patch.dict(os.environ, {"REMOTION_DRY_RUN": "true"}):
            started = render_timeline(
                "Launch cut",
                visuals=[{"kind": "image", "url": "https://example/hero.png", "duration_seconds": 1}],
            )
            progress = get_render_progress("dry-run", "")
        self.assertEqual(started["status"], "dry_run")
        self.assertEqual(progress["status"], "dry_run")
        self.assertTrue(progress["done"])


if __name__ == "__main__":
    unittest.main()
