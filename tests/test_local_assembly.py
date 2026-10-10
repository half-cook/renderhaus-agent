from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from providers.remotion import api
from providers.registry import dispatch


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg/ffprobe required')
class LocalAssemblyTests(unittest.TestCase):
    def test_local_submit_poll_delivers_trimmed_video_and_delayed_voice(self) -> None:
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
            'REMOTION_RENDER_BACKEND': 'local', 'REMOTION_DRY_RUN': 'false',
            'RENDERHAUS_MEDIA_DIR': folder,
        }), patch.dict(api.ASPECT_SIZES, {'16:9': (320, 180)}):
            root = Path(folder)
            clip, voice = root / 'clip.mp4', root / 'voice.wav'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'color=c=red:s=160x160:r=16:d=1', '-f', 'lavfi', '-i',
                            'color=c=blue:s=160x160:r=16:d=1', '-filter_complex',
                            '[0:v][1:v]concat=n=2:v=1:a=0[v]', '-map', '[v]',
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(clip)],
                           check=True, timeout=20)
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'sine=frequency=440:duration=1', str(voice)], check=True, timeout=20)
            with patch.object(api, 'load_remotion_settings', side_effect=AssertionError('AWS called')):
                started = dispatch('remotion', 'render_timeline', {'title': 'Local shot', 'visuals': [{
                    'kind': 'video', 'output_path': str(clip), 'duration_seconds': 1,
                    'source_in_seconds': 1, 'fit': 'contain', 'fade_in_seconds': .1,
                    'fade_out_seconds': .1,
                }], 'audio_tracks': [{'output_path': str(voice), 'duration_seconds': .5,
                                  'start_seconds': .25, 'volume': .5,
                                  'fade_in_seconds': .05, 'fade_out_seconds': .05}],
                                             'aspect_ratio': '16:9', 'fps': 16})
                self.assertEqual(started['status'], 'queued')
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    finished = dispatch('remotion', 'get_render_progress', {
                        'render_id': started['render_id'], 'bucket_name': started['bucket_name']})
                    if finished['status'] != 'queued':
                        break
                    time.sleep(.05)
            self.assertEqual(finished['status'], 'succeeded', finished)
            self.assertEqual([(e['start_s'], e['end_s']) for e in finished['motion_carry_timeline']['elements']], [(0, 1)])
            from providers.remotion import local
            with patch.dict(local._PROCESSES, {}, clear=True):
                repeated = api.get_render_progress(started['render_id'], started['bucket_name'])
            self.assertEqual(repeated, finished)
            output = Path(finished['output_path'])
            self.assertGreater(output.stat().st_size, 0)
            self.assertTrue(root in output.parents)
            probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error',
                '-show_streams', '-show_format', '-of', 'json', str(output)]))
            self.assertAlmostEqual(float(probe['format']['duration']), 1, delta=.08)
            self.assertEqual({s['codec_type'] for s in probe['streams']}, {'video', 'audio'})
            pixels = subprocess.check_output(['ffmpeg', '-v', 'error', '-ss', '0.5', '-i',
                str(output), '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'])
            video = next(stream for stream in probe['streams'] if stream['codec_type'] == 'video')
            center = ((video['height'] // 2) * video['width'] + video['width'] // 2) * 3
            self.assertGreater(pixels[center + 2], 200)  # source trim selected blue
            self.assertLess(pixels[0], 20)  # contain preserved black sidebars
            pcm = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(output),
                '-vn', '-ar', '8000', '-ac', '1', '-f', 'f32le', 'pipe:1'])
            import array
            samples = array.array('f', pcm)
            rms = lambda a, b: (sum(x*x for x in samples[int(a*8000):int(b*8000)]) /
                                 max(1, int((b-a)*8000))) ** .5
            self.assertLess(rms(.05, .15), .001)
            self.assertGreater(rms(.35, .55), .015)
            self.assertLess(rms(.85, .95), .001)

    def test_local_sources_cannot_escape_media_root(self) -> None:
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
            'REMOTION_RENDER_BACKEND': 'local', 'REMOTION_DRY_RUN': 'false',
            'RENDERHAUS_MEDIA_DIR': folder,
        }):
            for source in ('/etc/passwd', 'file:///etc/passwd', 'https://127.0.0.1/private'):
                with self.subTest(source=source), self.assertRaises(ValueError):
                    api.render_timeline('Forbidden source', [{'kind': 'video', 'url': source,
                                                              'duration_seconds': 1}])

    def test_success_requires_terminal_zero_exit_and_complete_expected_duration(self) -> None:
        from providers.remotion import local
        with tempfile.TemporaryDirectory() as folder:
            roots = (Path(folder),)
            render_id = 'local-' + 'a' * 32
            directory = Path(folder) / 'remotion' / 'local' / render_id
            directory.mkdir(parents=True)
            (directory / 'job.json').write_text(json.dumps({
                'filename': 'partial.mp4', 'pid': os.getpid(), 'duration': 1,
                'started': time.time(), 'timeout': 1200, 'fps': 30,
            }))
            (directory / 'partial.mp4').write_bytes(b'playable-partial-fixture')
            (directory / 'progress.txt').write_text('progress=end\n')
            for exit_code, duration, expected in [(None, 1, 'queued'), (1, 1, 'failed'),
                                                   (0, .5, 'failed'), (0, 1, 'succeeded'), (0, 'timeout', 'failed')]:
                with self.subTest(exit_code=exit_code, duration=duration):
                    terminal = directory / 'terminal.json'
                    terminal.unlink(missing_ok=True)
                    if exit_code is not None:
                        terminal.write_text(json.dumps({'exit_code': exit_code}))
                    with patch.object(local, '_probe', return_value={
                        'format': {'duration': str(duration)}, 'streams': [{'codec_type': 'video'}],
                    }, side_effect=subprocess.TimeoutExpired('ffprobe', 30) if duration == 'timeout' else None):
                        result = local.get_progress(render_id, media_roots=roots)
                    self.assertEqual(result['status'], expected)
