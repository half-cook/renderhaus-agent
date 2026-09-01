from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from providers.remotion.api import (
    build_timeline_props,
    dry_run,
    get_render_progress,
    render_timeline,
)


class RemotionProviderTests(unittest.TestCase):
    def test_live_rendering_is_the_default(self) -> None:
        with patch.dict(os.environ):
            os.environ.pop("REMOTION_DRY_RUN", None)
            self.assertFalse(dry_run())

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
                visuals=[
                    {"kind": "image", "url": "https://example/hero.png", "duration_seconds": 1}
                ],
            )
            progress = get_render_progress("dry-run", "")
        self.assertEqual(started["status"], "dry_run")
        self.assertEqual(progress["status"], "dry_run")
        self.assertTrue(progress["done"])

    def test_edit_plan_maps_b_roll_motion_titles_and_audio_fades(self) -> None:
        props = build_timeline_props(
            "Editorial cut",
            visuals=[
                {
                    "kind": "video",
                    "url": "https://example/main.mp4",
                    "duration_seconds": 4,
                    "transition": "fade",
                    "playback_rate": 1.25,
                    "motion": "zoom_in",
                },
                {
                    "kind": "image",
                    "url": "https://example/broll.png",
                    "track": 1,
                    "start_seconds": 1,
                    "duration_seconds": 2,
                    "fit": "contain",
                },
            ],
            audio_tracks=[
                {
                    "url": "https://example/music.mp3",
                    "duration_seconds": 4,
                    "volume": 0.4,
                    "fade_in_seconds": 0.5,
                    "fade_out_seconds": 0.75,
                }
            ],
            text_overlays=[
                {
                    "text": "Launch day",
                    "start_seconds": 0.5,
                    "duration_seconds": 2,
                    "position": "bottom",
                }
            ],
        )

        tracks = props["document"]["tracks"]
        self.assertEqual(
            [track["kind"] for track in tracks], ["video", "overlay", "audio", "caption"]
        )
        self.assertEqual(tracks[0]["items"][0]["motion"], "zoom_in")
        self.assertEqual(tracks[0]["items"][0]["playbackRate"], 1.25)
        self.assertEqual(tracks[2]["items"][0]["fadeOut"], 0.75)
        self.assertEqual(tracks[3]["items"][0]["text"], "Launch day")


if __name__ == "__main__":
    unittest.main()
