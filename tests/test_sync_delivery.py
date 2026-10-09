from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.studio_agent_next import (
    StudioAgentRequest, StudioToolEvent, _context_from_request, _validate_video_delivery,
)


class SyncDeliveryTests(unittest.TestCase):
    def test_saved_sync_mp4_finishes_existing_footage_request(self):
        request = StudioAgentRequest(prompt="make a lip-synced MP4 from this existing video")
        studio = _context_from_request(request)
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.mp4"
            video.write_bytes(b"provider-validated-mp4")
            studio.tool_events.append(StudioToolEvent(
                id="sync-poll", name="Sync___get_video_task", label="Sync poll", summary="Saved provider result", status="succeeded",
                result={"status": "succeeded", "downloaded": True, "output_path": str(video)},
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
