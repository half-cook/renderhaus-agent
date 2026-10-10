from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import ImageChops, ImageColor

from providers.remotion.template_frames import render_template_frame, write_template_video


def plan(name='podcast-audiogram', *, waveform='bars'):
    return {
        'name': name, 'duration_seconds': 1, 'fps': 12, 'width': 320, 'height': 180,
        'layout': {
            'safe': {'x': .05, 'y': .05, 'width': .9, 'height': .9},
            'art': {'x': .05, 'y': .05, 'width': .15, 'height': .2},
            'identity': {'x': .25, 'y': .05, 'width': .65, 'height': .2},
            'waveform': {'x': .05, 'y': .3, 'width': .9, 'height': .2},
            'captions': {'x': .05, 'y': .55, 'width': .9, 'height': .25},
            'progress': {'x': .05, 'y': .87, 'width': .9, 'height': .03},
        },
        'captions': [{'text': 'Hello world', 'start': .2, 'end': .8, 'words': [
            {'text': 'Hello', 'start': .2, 'end': .5},
            {'text': 'world', 'start': .5, 'end': .8},
        ]}],
        'amplitudes': [0] * 6 + [1] * 6, 'waveform': waveform, 'bars': 16,
        'smoothing': .65, 'speaker_name': 'Speaker', 'show_name': 'Show',
        'background_color': '#12202c', 'accent_color': '#f2b339', 'text_color': '#ffffff',
        'reserved_zones': [],
    }


class TemplateFrameTests(unittest.TestCase):
    def test_frame_is_deterministic_and_uses_the_planned_canvas(self):
        template = plan()
        before = copy.deepcopy(template)
        first = render_template_frame(template, 4)
        second = render_template_frame(template, 4)
        self.assertEqual(first.mode, 'RGB')
        self.assertEqual(first.size, (320, 180))
        self.assertIsNone(ImageChops.difference(first, second).getbbox())
        self.assertEqual(template, before)

    def test_waveform_changes_with_real_frame_amplitudes_for_bars_and_line(self):
        for waveform in ('bars', 'line'):
            template = plan(waveform=waveform)
            template['captions'] = []
            silent = render_template_frame({**template, 'amplitudes': [0] * 12}, 6)
            speaking = render_template_frame({**template, 'amplitudes': [1] * 12}, 6)
            delta = ImageChops.difference(silent, speaking)
            self.assertIsNotNone(delta.crop((16, 54, 304, 90)).getbbox())
            self.assertIsNone(delta.crop((0, 0, 320, 50)).getbbox())

    def test_progress_reaches_the_end_on_the_last_frame(self):
        template = plan()
        first = render_template_frame(template, 0)
        last = render_template_frame(template, 11)
        accent = ImageColor.getrgb(template['accent_color'])
        self.assertNotEqual(first.getpixel((300, 158)), accent)
        self.assertEqual(last.getpixel((300, 158)), accent)

    def test_caption_words_have_active_highlight_and_appear_only_inside_the_group_interval(self):
        template = plan()
        first_word = render_template_frame(template, 4)
        second_word = render_template_frame(template, 7)
        after = render_template_frame(template, 10)
        caption_box = (16, 99, 304, 144)
        self.assertIsNotNone(ImageChops.difference(first_word, second_word).crop(caption_box).getbbox())
        background = ImageColor.getrgb(template['background_color'])
        self.assertEqual(after.crop(caption_box).getextrema(), tuple((v, v) for v in background))

    def test_long_caption_and_names_stay_inside_their_declared_rectangles(self):
        template = plan()
        template['captions'][0]['words'] = [
            {'text': 'extraordinary', 'start': .2, 'end': .4},
            {'text': 'internationalisation', 'start': .4, 'end': .8},
        ]
        template['captions'][0]['text'] = 'extraordinary internationalisation'
        template['show_name'] = 'A very long show name that stays inside the identity rectangle'
        template['speaker_name'] = 'Someone With A Lengthy Name'
        picture = render_template_frame(template, 5)
        background = ImageColor.getrgb(template['background_color'])
        self.assertEqual(picture.crop((0, 144, 320, 156)).getextrema(), tuple((v, v) for v in background))

    def test_end_screen_reservations_remain_empty_at_start_middle_and_last(self):
        template = plan('youtube-end-screen')
        template['layout']['identity'] = {'x': .05, 'y': .05, 'width': .25, 'height': .35}
        template['reserved_zones'] = [
            {'x': .4, 'y': .1, 'width': .5, 'height': .35},
            {'x': .65, 'y': .55, 'width': .2, 'height': .25},
        ]
        background = ImageColor.getrgb(template['background_color'])
        for frame in (0, 6, 11):
            picture = render_template_frame(template, frame)
            for box in ((128, 18, 288, 81), (208, 99, 272, 144)):
                self.assertEqual(picture.crop(box).getextrema(), tuple((v, v) for v in background))

    def test_intro_is_frame_driven_and_has_no_waveform_captions_or_progress(self):
        template = plan('youtube-intro-sting')
        first = render_template_frame(template, 0)
        settled = render_template_frame(template, 8)
        self.assertIsNotNone(ImageChops.difference(first, settled).getbbox())
        background = ImageColor.getrgb(template['background_color'])
        self.assertEqual(settled.crop((16, 54, 304, 162)).getextrema(), tuple((v, v) for v in background))


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg/ffprobe required')
class TemplateVideoTests(unittest.TestCase):
    def test_encode_refuses_an_existing_file_without_deleting_it(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'template-visual.mp4'
            target.write_bytes(b'existing output')
            with self.assertRaises(FileExistsError):
                write_template_video(plan(), Path(folder))
            self.assertEqual(target.read_bytes(), b'existing output')

    def test_binary_absence_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder, patch('providers.remotion.template_frames.shutil.which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'requires ffmpeg'):
                write_template_video(plan(), Path(folder))

    def test_real_encode_has_planned_dimensions_duration_and_no_extra_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            template = plan()
            output = write_template_video(template, Path(folder))
            probe = json.loads(subprocess.check_output([
                'ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(output),
            ], timeout=10))
            video = next(stream for stream in probe['streams'] if stream['codec_type'] == 'video')
            self.assertEqual((video['width'], video['height']), (320, 180))
            self.assertEqual(video['codec_name'], 'h264')
            self.assertAlmostEqual(float(probe['format']['duration']), 1, delta=1 / 12)
            self.assertFalse(any(stream['codec_type'] == 'audio' for stream in probe['streams']))
            self.assertTrue(output.is_relative_to(Path(folder)))
            self.assertLess(output.stat().st_size, 128 * 1024 * 1024)


if __name__ == '__main__':
    unittest.main()
