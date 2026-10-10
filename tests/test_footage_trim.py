from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


class SelectTrimTests(unittest.TestCase):
    def test_long_source_has_bounded_larger_probe_allowance_only(self):
        from providers.ffmpeg.api import ProcessResult, execute

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = directory / 'rushes.mp4'
            with source.open('wb') as handle:
                handle.truncate(129 * 1024 * 1024)
            payload = json.dumps({'streams': [{'codec_type': 'video'}], 'format': {'duration': '10800'}}).encode()
            with patch('providers.ffmpeg.api.shutil.which', return_value='/usr/bin/ffprobe'), patch(
                    'providers.ffmpeg.api._bounded_run', return_value=ProcessResult(0, payload, b'')) as run:
                self.assertTrue(execute('probe', directory, source.name)['ok'])
                self.assertGreater(run.call_count, 0)
                run.reset_mock()
                self.assertFalse(execute('sha256', directory, source.name)['ok'])
                run.assert_not_called()
                with source.open('wb') as handle:
                    handle.truncate(33 * 1024 ** 3)
                self.assertFalse(execute('probe', directory, source.name)['ok'])
                run.assert_not_called()

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'local ffmpeg unavailable')
    def test_trim_op_produces_readable_timed_select_with_native_geometry(self):
        from providers.ffmpeg.api import execute

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            source = directory / 'source.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=160x90:r=24:d=4',
                            '-f', 'lavfi', '-i', 'sine=frequency=440:duration=4', '-c:v', 'libx264', '-threads', '1',
                            '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)], check=True)
            result = execute('trim', directory, source.name, {'t0_s': 1.0, 't1_s': 2.5})
            self.assertTrue(result['ok'], result)
            output = result['outputs'][0]
            self.assertTrue(Path(output['path']).is_file())
            probe = execute('probe', directory, Path(output['path']).name)
            video = next(s for s in probe['metrics']['streams'] if s['codec_type'] == 'video')
            self.assertEqual((video['width'], video['height']), (160, 90))
            self.assertAlmostEqual(float(probe['metrics']['format']['duration']), 1.5, delta=.1)
            self.assertTrue(any(s['codec_type'] == 'audio' for s in probe['metrics']['streams']))
            invalid = execute('trim', directory, source.name, {'t0_s': 3.0, 't1_s': 2.0})
            self.assertFalse(invalid['ok'])
