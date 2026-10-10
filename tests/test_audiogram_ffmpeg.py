from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest

from providers.ffmpeg.api import execute, validate_arguments


class EnvelopeBoundaryTests(unittest.TestCase):
    def test_parameters_are_bounded_without_media_io(self):
        for params in ({'duration_seconds': 91}, {'fps': 300}, {'smoothing': 1}, {'start_seconds': -1},
                       {'command': 'rm file'}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                validate_arguments({'op': 'audio_envelope', 'job_id': 'test', 'input_path': 'clip.wav', 'params': params})


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg/ffprobe required')
class RealEnvelopeTests(unittest.TestCase):
    def test_real_sine_select_envelope_and_audio_only_trim(self):
        with tempfile.TemporaryDirectory() as folder:
            job = Path(folder)
            subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-v', 'error',
                '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=16000:duration=2',
                '-af', "volume='if(lt(t,1),0,1)':eval=frame", str(job / 'clip.wav')], check=True, timeout=20)
            result = execute('audio_envelope', job, 'clip.wav', {'duration_seconds': 2, 'fps': 20, 'smoothing': 0})
            self.assertTrue(result['ok'], result)
            amplitudes = result['metrics']['amplitudes']
            self.assertEqual(len(amplitudes), 40)
            self.assertTrue(all(value == 0 for value in amplitudes[:18]))
            self.assertTrue(all(.08 < value < .10 for value in amplitudes[22:]))
            self.assertRegex(result['metrics']['source_sha256'], r'^[0-9a-f]{64}$')
            trimmed = execute('trim', job, 'clip.wav', {'t0_s': 1, 't1_s': 2})
            self.assertTrue(trimmed['ok'], trimmed)
            self.assertAlmostEqual(trimmed['metrics']['duration_s'], 1, delta=.1)
