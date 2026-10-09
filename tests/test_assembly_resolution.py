from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from providers.remotion import api


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
class AssemblyResolutionTests(unittest.TestCase):
    def test_720p_source_delivers_native_720p_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
            "REMOTION_RENDER_BACKEND": "local", "REMOTION_DRY_RUN": "false",
            "RENDERHAUS_MEDIA_DIR": folder,
        }):
            source = Path(folder) / "source.mp4"
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=1280x720:rate=24:duration=1", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(source),
            ], check=True, timeout=30)
            props = api.build_timeline_props("Native resolution", [{
                "kind": "video", "output_path": str(source), "duration_seconds": 1,
            }], aspect_ratio="16:9")
            result = api.render_timeline_and_wait(
                props, output_filename="native.mp4", poll_interval_seconds=.25, timeout_seconds=30,
            )
            self.assertEqual(result["status"], "succeeded", result)
            output = json.loads(subprocess.check_output([
                "ffprobe", "-v", "error", "-show_streams", "-of", "json", result["output_path"],
            ], timeout=30))["streams"][0]
            self.assertEqual((output["width"], output["height"]), (1280, 720))


if __name__ == "__main__":
    unittest.main()
