from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from PIL import Image

from providers.remotion import api, local
from providers.remotion.templates import template_plan, template_document
from providers.remotion.template_frames import write_template_video


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg/ffprobe required')
class RealAudiogramRenderTests(unittest.TestCase):
    def test_rendered_mp4_has_exact_aspect_duration_audio_and_moving_waveform(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / 'voice.wav'
            Image.new('RGB', (80, 80), (230, 40, 40)).save(root / 'cover.png')
            subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-v', 'error', '-f', 'lavfi', '-i',
                            'sine=frequency=440:duration=1:sample_rate=16000', str(audio)], check=True, timeout=20)
            raw = {'name': 'podcast-audiogram', 'duration_seconds': 1,
                   'words': [{'text': 'Hello', 'start': 0, 'end': .4}, {'text': 'world', 'start': .4, 'end': 1}],
                   'amplitudes': [index / 12 for index in range(12)], 'show_name': 'Show', 'speaker_name': 'Ada',
                   'cover_url': str(root / 'cover.png')}
            for aspect, size in {'9:16': (90, 160), '1:1': (160, 160), '4:5': (128, 160), '16:9': (160, 90)}.items():
                with self.subTest(aspect=aspect):
                    directory = root / aspect.replace(':', '-')
                    directory.mkdir()
                    props = api.build_timeline_props(title='Test', visuals=[], template=raw,
                        audio_tracks=[{'url': str(audio), 'duration_seconds': 1}], aspect_ratio=aspect, fps=12)
                    props['renderConfig'].update(width=size[0], height=size[1])
                    props['renderConfig']['resolution'].update(width=size[0], height=size[1])
                    props['template'] = template_plan(raw, aspect_ratio=aspect, fps=12, width=size[0], height=size[1])
                    props['document'] = template_document('Test', props['template'],
                        [{'url': str(audio), 'duration_seconds': 1}], str(root / 'cover.png'))
                    command, _ = local._command(props, directory, media_roots=(root,), source_root=root, filename='out.mp4')
                    write_template_video(props['template'], directory)
                    subprocess.run(command, check=True, timeout=30, capture_output=True)
                    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                                                               '-of', 'json', str(directory / 'out.mp4')]))
                    video = next(stream for stream in probe['streams'] if stream['codec_type'] == 'video')
                    self.assertEqual((video['width'], video['height']), size)
                    self.assertAlmostEqual(float(probe['format']['duration']), 1, delta=.1)
                    self.assertTrue(any(stream['codec_type'] == 'audio' for stream in probe['streams']))
                    frames = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(directory / 'out.mp4'),
                                                      '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-an', '-'])
                    frame_bytes = size[0] * size[1] * 3
                    self.assertNotEqual(frames[:frame_bytes], frames[-frame_bytes:])

    def test_owned_async_worker_generates_template_then_returns_real_mp4(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = {'name': 'youtube-intro-sting', 'duration_seconds': 3, 'show_name': 'Channel'}
            props = api.build_timeline_props(title='Intro', visuals=[], template=raw, aspect_ratio='16:9', fps=12)
            props['renderConfig'].update(width=160, height=90)
            props['renderConfig']['resolution'].update(width=160, height=90)
            props['template'] = template_plan(raw, aspect_ratio='16:9', fps=12, width=160, height=90)
            started = local.start_render(props, output_filename='intro.mp4', media_roots=(root,), source_root=api.ROOT)
            self.assertEqual(started['status'], 'queued')
            deadline = time.monotonic() + 20
            result = started
            while result['status'] == 'queued' and time.monotonic() < deadline:
                time.sleep(.05)
                result = local.get_progress(started['render_id'], media_roots=(root,))
            self.assertEqual(result['status'], 'succeeded', result)
            self.assertEqual((result['width'], result['height']), (160, 90))
            self.assertTrue(Path(result['output_path']).is_file())

    def test_template_lambda_payload_is_shared_and_preflight_refuses_tampered_geometry(self):
        raw = {'name': 'youtube-intro-sting', 'duration_seconds': 4, 'show_name': 'Channel'}
        props = api.build_timeline_props(title='Intro', visuals=[], template=raw, aspect_ratio='16:9', fps=30)
        with patch.dict('os.environ', {'REMOTION_TEMPLATE_CONTRACT_VERSION': '1'}):
            from providers.remotion.capabilities import validate_document

            validate_document(props, 'lambda')
            bad = copy.deepcopy(props)
            bad['template']['layout']['identity']['x'] = 10
            with self.assertRaises(ValueError):
                validate_document(bad, 'lambda')
