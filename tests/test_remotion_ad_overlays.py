from __future__ import annotations

import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops

from providers.remotion import api, local


def props_for(source: Path, *, text: str | None = None) -> dict:
    items = [{'id': 'base', 'type': 'clip', 'assetId': 'master', 'start': 0,
              'duration': 1, 'fit': 'cover', 'volume': 0}]
    tracks = [{'id': 'video', 'kind': 'video', 'items': items}]
    if text is not None:
        tracks.append({'id': 'copy', 'kind': 'caption', 'items': [{
            'id': 'copy', 'type': 'text', 'text': text, 'start': 0, 'duration': 1,
            'box': {'x': 15, 'y': 20, 'width': 290, 'height': 140},
            'fontSize': 24, 'minFontSize': 16, 'maxFontSize': 24,
            'fontFamily': 'dejavu-sans', 'color': '#ffffff', 'fadeIn': 0, 'fadeOut': 0,
        }]})
    return {'document': {'id': 'test', 'assets': [{
        'id': 'master', 'kind': 'video', 'url': str(source)}], 'tracks': tracks},
        'renderConfig': {'width': 320, 'height': 180, 'fps': 16,
                         'durationInFrames': 16, 'videoBitrate': 1200000}}


class OverlayContractTests(unittest.TestCase):
    def test_copy_keeps_spaces_and_newlines_verbatim(self) -> None:
        props = api.build_timeline_props('ad', [{'kind': 'image', 'url': 'logo.png',
            'duration_seconds': 1}], text_overlays=[{'text': '  $1,99\nNow  ',
            'start_seconds': 0, 'duration_seconds': 1}], measure_local=False)
        self.assertEqual(props['document']['tracks'][1]['items'][0]['text'], '  $1,99\nNow  ')

    def test_explicit_zero_fade_is_preserved(self) -> None:
        props = api.build_timeline_props('ad', [{'kind': 'image', 'url': 'logo.png',
            'duration_seconds': 1}], text_overlays=[{'text': 'Sale', 'start_seconds': 0,
            'duration_seconds': 1, 'font_family': 'dejavu-sans',
            'fade_in_seconds': 0, 'fade_out_seconds': 0}], measure_local=False)
        item = props['document']['tracks'][1]['items'][0]
        self.assertEqual((item['fadeIn'], item['fadeOut']), (0, 0))

    def test_four_by_five_canvas_is_available(self) -> None:
        self.assertEqual(api.choose_canvas('4:5', [(1080, 1080)]), (1080, 1350))

    def test_box_font_fitting_returns_shared_lambda_props(self) -> None:
        props = api.build_timeline_props('ad', [{'kind': 'image', 'url': 'logo.png',
            'duration_seconds': 1, 'box': {'x': 50, 'y': 50, 'width': 100, 'height': 100}}],
            text_overlays=[{'text': 'Buy now', 'start_seconds': 0, 'duration_seconds': 1,
            'box': {'x': 60, 'y': 200, 'width': 250, 'height': 70},
            'min_font_size': 16, 'max_font_size': 64, 'font_family': 'dejavu-sans',
            'opacity': .8}], aspect_ratio='1:1', measure_local=False)
        image = props['document']['tracks'][0]['items'][0]
        text = props['document']['tracks'][1]['items'][0]
        self.assertEqual(image['box'], {'x': 50, 'y': 50, 'width': 100, 'height': 100})
        self.assertEqual(text['box'], {'x': 60, 'y': 200, 'width': 250, 'height': 70})
        self.assertTrue(16 <= text['fontSize'] < 64)
        self.assertLessEqual(text['textFit']['width'], 250)
        self.assertLessEqual(text['textFit']['height'], 70)
        self.assertEqual(text['opacity'], .8)

    def test_text_overflow_refuses_before_a_render(self) -> None:
        from providers.remotion.text import fit_text
        with self.assertRaisesRegex(ValueError, 'text_overflow'):
            fit_text({'text': 'W' * 50, 'box': {'x': 0, 'y': 0, 'width': 40, 'height': 40},
                      'fontSize': 30, 'minFontSize': 16, 'maxFontSize': 30}, 320, 180)

    def test_font_paths_and_unknown_font_ids_are_refused(self) -> None:
        from providers.remotion.text import fit_text
        for font in ['/etc/passwd', '../font.ttf', 'DejaVu Sans;movie=/etc/passwd', 'https://fonts/font']:
            with self.subTest(font=font), self.assertRaisesRegex(ValueError, 'allow-listed font'):
                fit_text({'text': 'Buy', 'fontFamily': font}, 320, 180)

    def test_unsafe_box_and_numeric_values_are_refused(self) -> None:
        from providers.remotion.text import fit_text
        for bad in [float('nan'), float('inf'), -1, 10**20, True, '1;movie=/etc/passwd']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                fit_text({'text': 'Buy', 'box': {'x': bad, 'y': 0, 'width': 100, 'height': 40}}, 320, 180)

    def test_box_outside_canvas_is_refused(self) -> None:
        from providers.remotion.text import fit_text
        with self.assertRaisesRegex(ValueError, 'inside the canvas'):
            fit_text({'text': 'Buy', 'box': {'x': 300, 'y': 0, 'width': 100, 'height': 40}}, 320, 180)

    def test_unavailable_glyph_is_reported_instead_of_tofu(self) -> None:
        from providers.remotion.text import fit_text
        with self.assertRaisesRegex(ValueError, 'text_unsupported_glyph'):
            fit_text({'text': 'Rocket 🚀', 'fontFamily': 'dejavu-sans'}, 320, 180)

    def test_literal_colors_cannot_inject_a_filter(self) -> None:
        for color in ['white;movie=/etc/passwd', '#ffffff:box=1', 'rgba(1,2,3,1)']:
            with self.subTest(color=color), tempfile.TemporaryDirectory() as folder:
                props = props_for(Path('/tmp/fake.mp4'), text='Buy')
                item = props['document']['tracks'][1]['items'][0]
                item['color'] = color
                with self.assertRaisesRegex(ValueError, 'color'):
                    local._text_layer(item, Path(folder), 1, width=320, height=180, frame_rate='16/1')

    def test_custom_text_is_not_truncated(self) -> None:
        with self.assertRaisesRegex(ValueError, '500'):
            api.build_timeline_props('ad', [{'kind': 'image', 'url': 'logo.png',
                'duration_seconds': 1}], text_overlays=[{'text': 'x' * 501,
                'start_seconds': 0, 'duration_seconds': 1}], measure_local=False)

    def test_old_lambda_rejects_new_contract_before_upload(self) -> None:
        props = props_for(Path('/tmp/fake.mp4'), text='Buy')
        with patch.dict(os.environ, {'REMOTION_OVERLAY_CONTRACT_VERSION': '1'}), self.assertRaisesRegex(
                ValueError, 'overlay contract version 2'), patch.object(api, 'load_remotion_settings',
                side_effect=AssertionError('AWS settings must not be loaded')):
            api._start_lambda_render(props, output_filename='ad.mp4')

    def test_old_lambda_refuses_before_worker_font_or_media_measurement(self) -> None:
        with patch.dict(os.environ, {'REMOTION_RENDER_BACKEND': 'lambda', 'REMOTION_DRY_RUN': 'false',
                                     'REMOTION_OVERLAY_CONTRACT_VERSION': '1'}), patch.object(
                api, 'build_timeline_props', side_effect=AssertionError('Font/media measurement must not start')):
            with self.assertRaisesRegex(ValueError, 'overlay contract version 2'):
                api.render_timeline('ad', [{'kind': 'video', 'url': 'master.mp4', 'duration_seconds': 1}],
                    text_overlays=[{'text': 'Sale', 'start_seconds': 0, 'duration_seconds': 1,
                                    'font_family': 'dejavu-sans'}])

    def test_lambda_v2_upload_keeps_geometry_and_fitted_text(self) -> None:
        props = props_for(Path('/tmp/fake.mp4'), text='Buy')
        from providers.remotion.text import fit_text
        item = props['document']['tracks'][1]['items'][0]
        item.update(fit_text(item, 320, 180))
        original = copy.deepcopy(props)
        settings = api.RemotionSettings(region='us-east-1', function_name='test',
            serve_url='https://test.invalid', bucket_name='test')
        fake_s3 = unittest.mock.Mock()
        fake_s3.head_object.side_effect = RuntimeError('not present')
        with patch.object(api, '_uploaded_source_url', return_value='https://assets.invalid/master.mp4'):
            prepared = api._prepare_input_props(props, settings=settings,
                session=unittest.mock.Mock(client=unittest.mock.Mock(return_value=fake_s3)))
        self.assertEqual(prepared['document']['tracks'], original['document']['tracks'])
        self.assertEqual(prepared['renderConfig'], original['renderConfig'])


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg/ffprobe required')
class RealOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'master.mp4'
        subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-v', 'error', '-f', 'lavfi',
            '-i', 'color=c=black:s=320x180:r=16:d=1', '-c:v', 'libx264', '-threads', '1',
            '-pix_fmt', 'yuv420p', str(self.source)], check=True, timeout=20)

    def render(self, props: dict, filename: str = 'out.mp4') -> Path:
        directory = self.root / f'job-{filename}'
        directory.mkdir()
        command, _ = local._command(props, directory, media_roots=(self.root,),
                                    source_root=self.root, filename=filename)
        subprocess.run(command, cwd=directory, check=True, capture_output=True, timeout=30)
        return directory / filename

    def frame(self, file: Path, seconds: float = .5) -> Image.Image:
        pixels = subprocess.check_output(['ffmpeg', '-nostdin', '-hide_banner', '-v', 'error',
            '-ss', str(seconds), '-i', str(file), '-frames:v', '1', '-f', 'rawvideo',
            '-pix_fmt', 'rgb24', 'pipe:1'], timeout=20)
        return Image.frombytes('RGB', (320, 180), pixels)

    def test_drawtext_draws_literal_adversarial_copy_without_filter_injection(self) -> None:
        texts = ["$1,99: 'Buy' \\ 100%\n%{metadata:key}",
                 'SALE\nFrançais 😀', 'اشتر الآن', "x'[v];movie=/etc/passwd[v];'y"]
        baseline = self.frame(self.render(props_for(self.source), 'base.mp4'))
        for index, text in enumerate(texts):
            with self.subTest(text=text):
                props = props_for(self.source, text=text)
                output = self.render(props, f'text-{index}.mp4')
                image = self.frame(output)
                self.assertIsNotNone(ImageChops.difference(image, baseline).getbbox())
                video = next(s for s in local._probe(output)['streams'] if s['codec_type'] == 'video')
                self.assertEqual((video['width'], video['height'], video['r_frame_rate']), (320, 180, '16/1'))
                self.assertEqual((output.parent / 'text-1.txt').read_text(), text)

    def test_positioned_alpha_logo_keeps_master_outside_box(self) -> None:
        logo = self.root / 'logo.png'
        image = Image.new('RGBA', (40, 40), (255, 0, 0, 255))
        for x in range(20):
            for y in range(40):
                image.putpixel((x, y), (0, 0, 0, 0))
        image.save(logo)
        props = props_for(self.source)
        props['document']['assets'].append({'id': 'logo', 'kind': 'image', 'url': str(logo)})
        props['document']['tracks'].append({'id': 'logo', 'kind': 'overlay', 'items': [{
            'id': 'logo', 'type': 'clip', 'assetId': 'logo', 'start': 0, 'duration': 1,
            'box': {'x': 240, 'y': 20, 'width': 60, 'height': 60}, 'fit': 'contain',
            'scale': 1, 'opacity': .5, 'fadeIn': .1, 'fadeOut': .1}]})
        frame = self.frame(self.render(props))
        self.assertLess(max(frame.getpixel((100, 100))), 10)
        self.assertLess(max(frame.getpixel((248, 45))), 10)
        self.assertTrue(90 < frame.getpixel((285, 45))[0] < 170)

    def test_fractional_logo_box_with_master_audio_renders(self) -> None:
        source = self.root / 'audio-master.mp4'
        subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-v', 'error', '-f', 'lavfi',
            '-i', 'color=c=black:s=320x180:r=16:d=1', '-f', 'lavfi', '-i',
            'sine=frequency=440:duration=1', '-c:v', 'libx264', '-threads', '1',
            '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(source)], check=True, timeout=20)
        logo = self.root / 'fractional-logo.png'
        Image.new('RGBA', (64, 32), (255, 0, 0, 255)).save(logo)
        props = props_for(source)
        props['document']['tracks'][0]['items'][0]['volume'] = 1
        props['document']['assets'].append({'id': 'logo', 'kind': 'image', 'url': str(logo)})
        props['document']['tracks'].append({'id': 'logo', 'kind': 'overlay', 'items': [{
            'id': 'logo', 'type': 'clip', 'assetId': 'logo', 'start': 0, 'duration': 1,
            'box': {'x': 240, 'y': 20, 'width': 52.8, 'height': 28.8}, 'fit': 'contain'}]})
        output = self.render(props)
        probe = local._probe(output)
        self.assertEqual({s['codec_type'] for s in probe['streams']}, {'video', 'audio'})
        self.assertGreater(self.frame(output).getpixel((266, 34))[0], 200)

    def test_video_scale_is_rendered_about_canvas_center(self) -> None:
        red = self.root / 'red.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
            'color=c=red:s=320x180:r=16:d=1', '-c:v', 'libx264', '-threads', '1',
            '-pix_fmt', 'yuv420p', str(red)], check=True, timeout=20)
        props = props_for(red)
        props['document']['tracks'][0]['items'][0]['scale'] = .5
        frame = self.frame(self.render(props))
        self.assertLess(max(frame.getpixel((5, 5))), 10)
        self.assertGreater(frame.getpixel((160, 90))[0], 200)

    def test_async_local_api_renders_titles_and_preserves_source_resolution(self) -> None:
        with patch.dict(os.environ, {'REMOTION_RENDER_BACKEND': 'local',
            'REMOTION_DRY_RUN': 'false', 'RENDERHAUS_MEDIA_DIR': str(self.root)}), patch.object(
            api, 'load_remotion_settings', side_effect=AssertionError('No Lambda calls')):
            started = api.render_timeline('ad', [{'kind': 'video', 'output_path': str(self.source),
                'duration_seconds': 1}], text_overlays=[{'text': 'SALE $1,99', 'start_seconds': 0,
                'duration_seconds': 1, 'box': {'x': 25, 'y': 40, 'width': 260, 'height': 80},
                'min_font_size': 16, 'max_font_size': 24, 'font_family': 'dejavu-sans',
                'fade_in_seconds': 0, 'fade_out_seconds': 0}], aspect_ratio='16:9')
            deadline = time.monotonic() + 20
            result = started
            while time.monotonic() < deadline:
                result = api.get_render_progress(started['render_id'], started['bucket_name'])
                if result['status'] != 'queued':
                    break
                time.sleep(.05)
            self.assertEqual(result['status'], 'succeeded', result)
            self.assertEqual((result['width'], result['height']), (320, 180))
            self.assertEqual(result['source_resolution'], '320x180')
            self.assertFalse(result['upscaled'])
            frame = self.frame(Path(result['output_path']))
            self.assertGreater(max(frame.crop((25, 40, 285, 120)).getextrema()[0]), 200)

    def test_text_opacity_and_fades_affect_real_pixels(self) -> None:
        props = props_for(self.source, text='SALE')
        item = props['document']['tracks'][1]['items'][0]
        item.update({'fadeIn': .3, 'fadeOut': .3, 'opacity': .5, 'backgroundColor': '#ffffff'})
        output = self.render(props)
        middle = self.frame(output, .5).getpixel((25, 30))[0]
        start = self.frame(output, .0625).getpixel((25, 30))[0]
        end = self.frame(output, .9375).getpixel((25, 30))[0]
        self.assertTrue(90 < middle < 170)
        self.assertLess(start, middle / 2)
        self.assertLess(end, 10)

    def test_text_timing_keeps_copy_outside_its_window(self) -> None:
        props = props_for(self.source, text='SALE')
        item = props['document']['tracks'][1]['items'][0]
        item.update({'start': .25, 'duration': .5})
        output = self.render(props)
        self.assertLess(max(self.frame(output, .0625).getextrema()[0]), 10)
        self.assertGreater(max(self.frame(output, .5).getextrema()[0]), 200)
        self.assertLess(max(self.frame(output, .875).getextrema()[0]), 10)

    def test_local_motion_grade_rotation_remain_refused(self) -> None:
        for field, value in [('motion', 'zoom_in'), ('grade', 'warm'), ('rotation', 10)]:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Lambda'):
                props = props_for(self.source)
                props['document']['tracks'][0]['items'][0][field] = value
                self.render(props, f'{field}.mp4')


if __name__ == '__main__':
    unittest.main()
