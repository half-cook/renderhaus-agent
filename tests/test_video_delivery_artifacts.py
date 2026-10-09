import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent.studio_agent_next import (
    StudioAgentContext, StudioAgentRequest, StudioToolEvent, _validate_video_delivery,
)


class VideoDeliveryArtifactTests(unittest.TestCase):
    def test_shot_and_clip_require_a_completed_render_with_real_media(self):
        for noun in ('5-second cinematic shot', '5 s clip', 'five-second clip'):
            request = StudioAgentRequest(prompt=f'Make a {noun} with a calm voiceover')
            with self.subTest(noun=noun):
                self.assertFalse(_validate_video_delivery(request, StudioAgentContext()))
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'final.mp4'
                    for value in (None, b'', b'not video'):
                        if value is not None:
                            path.write_bytes(value)
                        studio = self._context({'output_path': str(path)})
                        if value == b'not video' and not shutil.which('ffprobe'):
                            continue
                        self.assertFalse(_validate_video_delivery(request, studio))
                self.assertFalse(_validate_video_delivery(request, self._context({}, assets=[{'id': 'invented'}])))
                self.assertTrue(_validate_video_delivery(request, self._context({'url': 'https://cdn.example/final.mp4'})))
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
            return
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'final.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=blue:s=64x64:d=0.2', '-c:v', 'libx264', str(path)], check=True, capture_output=True)
            self.assertTrue(_validate_video_delivery(request, self._context({'output_path': str(path)})))

    @staticmethod
    def _context(result, **kwargs):
        return StudioAgentContext(tool_events=[StudioToolEvent(
            id='render', name='Remotion___get_render_progress', label='Render',
            status='succeeded', summary='Done', provider='remotion',
            result={'status': 'succeeded', **result}, **kwargs,
        )])
