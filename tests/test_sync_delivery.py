from __future__ import annotations

import unittest
from pathlib import Path

from agent.studio_agent_next import (
    StudioAgentRequest, StudioToolEvent, _context_from_request, _validate_video_delivery,
)


class SyncDeliveryTests(unittest.TestCase):
    def test_saved_sync_mp4_finishes_existing_footage_request(self):
        request = StudioAgentRequest(prompt="make a lip-synced MP4 from this existing video")
        studio = _context_from_request(request)
        studio.tool_events.append(StudioToolEvent(
            id="sync-poll", name="Sync___get_video_task", label="Sync poll", summary="Saved provider result", status="succeeded",
            result={"status": "succeeded", "downloaded": True,
                    "output_path": str(Path(__file__).parent / "fixtures/sync-video.mp4")},
        ))
        self.assertTrue(_validate_video_delivery(request, studio))

    def test_sync_preview_pending_or_unsaved_output_never_finishes_video(self):
        for status, downloaded in (("dry_run", False), ("queued", False), ("succeeded", False)):
            with self.subTest(status=status):
                request = StudioAgentRequest(prompt="make a lip-synced MP4 from this existing video")
                studio = _context_from_request(request)
                studio.tool_events.append(StudioToolEvent(
                    id="sync-poll", name="Sync___get_video_task", label="Sync poll", summary="Saved provider result", status=status,
                    result={"status": status, "downloaded": downloaded},
                ))
                self.assertFalse(_validate_video_delivery(request, studio))

    def test_explicitly_omitted_captions_do_not_require_another_render(self):
        for omission in ("without captions", "do not add captions", "don't burn in subtitles"):
            with self.subTest(omission=omission):
                request = StudioAgentRequest(prompt=f"make a lip-synced MP4 from this existing video; {omission}")
                studio = _context_from_request(request)
                studio.tool_events.append(StudioToolEvent(
                    id="sync-poll", name="Sync___get_video_task", label="Sync poll", summary="Saved result", status="succeeded",
                    result={"status": "succeeded", "downloaded": True,
                            "output_path": str(Path(__file__).parent / "fixtures/sync-video.mp4")},
                ))
                self.assertTrue(_validate_video_delivery(request, studio))

    def test_caption_assembly_or_rejected_poll_still_requires_rendering(self):
        for prompt, status in (
            ("make a lip-synced MP4 from this video and add captions", "succeeded"),
            ("make a lip-synced MP4 from this video with captions", "succeeded"),
            ("make a lip-synced MP4 from this video, include subtitles", "succeeded"),
            ("make a lip-synced MP4 from this video without captions; add music", "succeeded"),
            ("make a lip-synced MP4 from this video", "rejected"),
        ):
            with self.subTest(prompt=prompt, status=status):
                request = StudioAgentRequest(prompt=prompt)
                studio = _context_from_request(request)
                studio.tool_events.append(StudioToolEvent(
                    id="sync-poll", name="Sync___get_video_task", label="Sync poll", summary="Saved result", status=status,
                    result={"status": "succeeded", "downloaded": True,
                            "output_path": str(Path(__file__).parent / "fixtures/sync-video.mp4")},
                ))
                self.assertFalse(_validate_video_delivery(request, studio))
