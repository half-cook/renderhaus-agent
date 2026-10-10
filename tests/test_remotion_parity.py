from __future__ import annotations

import copy
from fractions import Fraction
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageChops, ImageStat

from providers.remotion import api, local
from providers.registry import dispatch


def arguments(source: str, **options) -> dict:
    visual = {'kind': 'video', 'output_path': source, 'duration_seconds': 1,
              'source_fps': 16, 'source_bitrate': 500_000}
    visual.update(options)
    return {'title': 'Parity', 'visuals': [visual], 'aspect_ratio': '16:9'}


class PreflightTests(unittest.TestCase):
    def test_unsupported_later_item_refuses_before_any_media_io(self):
        args = arguments('missing.mp4')
        args['visuals'].append({**args['visuals'][0], 'crop_box': {
            'x': 0, 'y': 0, 'width': 100, 'height': 100}})
        for dry in ('true', 'false'):
            with self.subTest(dry=dry), patch.dict(os.environ, {
                    'REMOTION_DRY_RUN': dry, 'REMOTION_RENDER_BACKEND': 'lambda'}), \
                    patch.object(api, '_visual_metadata') as media, \
                    patch.object(api.boto3, 'Session') as aws:
                with self.assertRaisesRegex(ValueError, 'local/worker'):
                    api.render_timeline(**args)
                media.assert_not_called()
                aws.assert_not_called()

    def test_invalid_effects_fail_in_dry_run_before_io(self):
        for field, value in [('scale', float('nan')), ('rotation_degrees', float('inf')),
                             ('motion', 'zoom_in;movie=/etc/passwd'),
                             ('grade', 'warm,eq=9'), ('keyframes', [])]:
            with self.subTest(field=field), patch.dict(os.environ, {
                    'REMOTION_DRY_RUN': 'true', 'REMOTION_RENDER_BACKEND': 'local'}), \
                    patch.object(api, '_visual_metadata') as media:
                with self.assertRaises(ValueError):
                    api.render_timeline(**arguments('missing.mp4', **{field: value}))
                media.assert_not_called()

    def test_unsupported_local_text_is_checked_before_media(self):
        for text_options in ({'color': 'rgb(1,2,3)'}, {'font_weight': 300}):
            with self.subTest(options=text_options), patch.dict(os.environ, {
                    'REMOTION_DRY_RUN': 'false', 'REMOTION_RENDER_BACKEND': 'local'}), \
                    patch.object(api, '_visual_metadata') as media:
                with self.assertRaisesRegex(ValueError, 'Lambda'):
                    api.render_timeline(**arguments('missing.mp4'), text_overlays=[{
                        'text': 'Buy', 'start_seconds': 0, 'duration_seconds': 1,
                        **text_options}])
                media.assert_not_called()

    def test_normalized_unknown_effect_is_not_silently_ignored(self):
        props = api.build_timeline_props(**arguments('missing.mp4'), measure_local=False)
        props['document']['tracks'][0]['items'][0]['keyframes'] = [{'scale': 2}]
        for backend in ('local', 'lambda'):
            with self.subTest(backend=backend), patch.dict(os.environ, {
                    'REMOTION_RENDER_BACKEND': backend}), patch.object(local, '_source') as source, \
                    patch.object(api.boto3, 'Session') as aws:
                with self.assertRaisesRegex(ValueError, 'keyframes'):
                    api._start_render(props, output_filename='test.mp4')
                source.assert_not_called()
                aws.assert_not_called()

    def test_default_dry_run_does_not_need_media_or_aws(self):
        with patch.dict(os.environ, {'REMOTION_DRY_RUN': 'true', 'REMOTION_RENDER_BACKEND': 'local'}), \
                patch.object(api, '_visual_metadata') as media, patch.object(api.boto3, 'Session') as aws:
            result = api.render_timeline(**arguments('missing.mp4', motion='pan_left', grade='warm'))
        self.assertEqual(result['status'], 'dry_run')
        media.assert_not_called()
        aws.assert_not_called()

    def test_top_level_numbers_refuse_before_media(self):
        for options in ({'fps': float('nan')}, {'video_bitrate': True}, {'fps': 0}):
            with self.subTest(options=options), patch.dict(os.environ, {'REMOTION_DRY_RUN': 'false'}), \
                    patch.object(api, '_visual_metadata') as media:
                with self.assertRaises(ValueError):
                    api.render_timeline(**{**arguments('missing.mp4'), **options})
                media.assert_not_called()

    def test_normalized_duration_and_transition_cannot_diverge(self):
        for mutation in ('duration', 'transition'):
            props = api.build_timeline_props(**arguments('missing.mp4'), measure_local=False)
            if mutation == 'duration':
                props['renderConfig']['durationInFrames'] = 32
            else:
                props['document']['tracks'][0]['items'][0]['transition'] = 'wipe'
            for backend in ('local', 'lambda'):
                with self.subTest(mutation=mutation, backend=backend), patch.dict(os.environ, {
                        'REMOTION_RENDER_BACKEND': backend}), patch.object(local, '_source') as media, \
                        patch.object(api.boto3, 'Session') as aws:
                    with self.assertRaises(ValueError):
                        api._start_render(props, output_filename='test.mp4')
                    media.assert_not_called()
                    aws.assert_not_called()

    def test_normalized_text_fit_cannot_disagree_with_rendered_text(self):
        props = api.build_timeline_props(**arguments('missing.mp4'), measure_local=False,
            text_overlays=[{'text': 'Buy', 'start_seconds': 0, 'duration_seconds': 1,
                            'box': {'x': 10, 'y': 10, 'width': 180, 'height': 100}, 'font_size': 20}])
        props['document']['tracks'][-1]['items'][0]['textFit']['height'] = 999
        for backend in ('local', 'lambda'):
            with self.subTest(backend=backend), patch.dict(os.environ, {
                    'REMOTION_RENDER_BACKEND': backend, 'REMOTION_OVERLAY_CONTRACT_VERSION': '2'}), \
                    patch.object(local, '_source') as media, patch.object(api.boto3, 'Session') as aws:
                with self.assertRaisesRegex(ValueError, 'textFit'):
                    api._start_render(props, output_filename='test.mp4')
                media.assert_not_called()
                aws.assert_not_called()

    def test_normalized_missing_text_fit_and_reframe_canvas_refuse_before_io(self):
        for mutation in ('textFit', 'reframeSize'):
            props = api.build_timeline_props(**arguments('missing.mp4'), measure_local=False,
                text_overlays=[{'text': 'Buy', 'start_seconds': 0, 'duration_seconds': 1,
                                'box': {'x': 10, 'y': 10, 'width': 180, 'height': 100}, 'font_size': 20}])
            if mutation == 'textFit':
                del props['document']['tracks'][-1]['items'][0]['textFit']
            else:
                item = props['document']['tracks'][0]['items'][0]
                item.update(cropBox={'x': 0, 'y': 0, 'width': 160, 'height': 90},
                            reframeSize={'width': 640, 'height': 360})
            for backend in ('local', 'lambda'):
                with self.subTest(mutation=mutation, backend=backend), patch.dict(os.environ, {
                        'REMOTION_RENDER_BACKEND': backend, 'REMOTION_OVERLAY_CONTRACT_VERSION': '2'}), \
                        patch.object(local, '_source') as media, patch.object(api.boto3, 'Session') as aws:
                    with self.assertRaises(ValueError):
                        api._start_render(props, output_filename='test.mp4')
                    media.assert_not_called()
                    aws.assert_not_called()

    def test_malformed_srt_and_out_of_timeline_text_refuse(self):
        for srt in ('https://example.test/captions.srt', '1\n00:00:00,750 --> 00:00:00,250\nBuy',
                    '1\n00:00:00,000 --> 00:00:02,000\nBuy'):
            with self.subTest(srt=srt), patch.object(api, '_visual_metadata') as media:
                with self.assertRaises(ValueError):
                    api.render_timeline(**arguments('missing.mp4'), subtitles_srt=srt)
                media.assert_not_called()

    def test_fitted_overlays_require_explicit_lambda_contract_version(self):
        args = arguments('missing.mp4', box={'x': 0, 'y': 0, 'width': 80, 'height': 60})
        for dry in ('true', 'false'):
            with self.subTest(dry=dry), patch.dict(os.environ, {
                    'REMOTION_RENDER_BACKEND': 'lambda', 'REMOTION_DRY_RUN': dry,
                    'REMOTION_OVERLAY_CONTRACT_VERSION': '1'}), patch.object(api, '_visual_metadata') as media, \
                    patch.object(api.boto3, 'Session') as aws:
                with self.assertRaisesRegex(ValueError, 'local/worker'):
                    api.render_timeline(**args)
                media.assert_not_called()
                aws.assert_not_called()


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'ffmpeg/ffprobe required')
class RealParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.root = Path(cls.folder.name)
        cls.source = cls.root / 'source.mp4'
        cls.still = cls.root / 'image.png'
        Image.new('RGBA', (80, 60), (240, 25, 10, 150)).save(cls.still)
        subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-v', 'error',
            '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=16:d=2',
            '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2',
            '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-shortest', str(cls.source)], check=True, timeout=20)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def render_local(self, args: dict) -> tuple[dict, Path]:
        with patch.dict(os.environ, {'REMOTION_DRY_RUN': 'false', 'REMOTION_RENDER_BACKEND': 'local',
                                     'RENDERHAUS_MEDIA_DIR': str(self.root)}):
            props = api.build_timeline_props(**{key: value for key, value in args.items() if key != 'output_filename'})
            result = api.render_timeline_and_wait(props, output_filename=args.get('output_filename', 'parity.mp4'),
                timeout_seconds=30, poll_interval_seconds=.25)
        self.assertEqual(result['status'], 'succeeded', result)
        path = Path(result['output_path'])
        probe = local._probe(path)
        video = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        config = props['renderConfig']
        self.assertIn('mp4', probe['format']['format_name'])
        self.assertEqual(video['codec_name'], 'h264')
        self.assertEqual((video['width'], video['height']), (config['width'], config['height']))
        self.assertAlmostEqual(float(Fraction(video['avg_frame_rate'])), config['fps'], places=3)
        self.assertAlmostEqual(float(probe['format']['duration']),
            config['durationInFrames'] / config['fps'], delta=1 / config['fps'])
        self.assertEqual(result['source_resolution'], '320x180')
        return props, path

    def lambda_payload(self, args: dict) -> dict:
        aws = Mock()
        aws.invoke.return_value = {'Payload': io.BytesIO(json.dumps({
            'type': 'success', 'bucketName': 'bucket', 'renderId': 'render'}).encode())}
        settings = api.RemotionSettings('us-east-1', 'function', 'https://site.invalid', 'bucket')
        with patch.dict(os.environ, {'REMOTION_DRY_RUN': 'false', 'REMOTION_RENDER_BACKEND': 'lambda',
                    'RENDERHAUS_MEDIA_DIR': str(self.root), 'REMOTION_OVERLAY_CONTRACT_VERSION': '2',
                    'REMOTION_FRAMES_PER_LAMBDA': '100'}), \
                patch.object(api, 'load_remotion_settings', return_value=settings), \
                patch.object(api.boto3, 'Session') as session, \
                patch.object(api, '_uploaded_source_url', side_effect=lambda source, **_:
                    'https://media.invalid/' + Path(source).name), \
                patch.object(api.uuid, 'uuid4', return_value=Mock(hex='fixed')):
            session.return_value.client.return_value = aws
            result = dispatch('remotion', 'render_timeline', args)
        self.assertEqual(result['status'], 'queued')
        aws.invoke.assert_called_once()
        self.assertEqual(aws.invoke.call_args.kwargs['FunctionName'], 'function')
        return json.loads(aws.invoke.call_args.kwargs['Payload'])

    def frame(self, path: Path, seconds=.5) -> Image.Image:
        pixels = subprocess.check_output(['ffmpeg', '-nostdin', '-hide_banner', '-v', 'error',
            '-ss', str(seconds), '-i', str(path), '-frames:v', '1', '-f', 'rawvideo',
            '-pix_fmt', 'rgb24', 'pipe:1'], timeout=20)
        return Image.frombytes('RGB', (320, 180), pixels)

    def test_shared_feature_matrix_uses_real_local_and_exact_lambda_payload(self):
        text = {'text': 'Buy $1.99', 'start_seconds': .25, 'duration_seconds': .5,
                'font_size': 20, 'font_weight': 700, 'color': '#ffffff',
                'background_color': '#000000', 'opacity': .8,
                'fade_in_seconds': .1, 'fade_out_seconds': .1}
        cases = [({}, {}), ({'source_in_seconds': .25, 'playback_rate': 1.5}, {}),
                 ({'transition': 'fade'}, {}), ({'transition': 'dip_to_black'}, {}),
                 ({'fit': 'contain', 'position_x': .2, 'position_y': .8, 'scale': .5}, {}),
                 ({'opacity': .5, 'fade_in_seconds': .1, 'fade_out_seconds': .2}, {}),
                 ({'rotation_degrees': 35}, {}), ({'grade': 'neutral'}, {}), ({'grade': 'warm'}, {}),
                 *[({'motion': motion}, {}) for motion in ('zoom_in', 'zoom_out', 'pan_left', 'pan_right')],
                 ({}, {'text_overlays': [text], 'subtitles': [{**text, 'text': 'Captions', 'position': 'bottom'}]}),
                 ({'audio_fade_in_seconds': .1, 'audio_fade_out_seconds': .1, 'volume': .4},
                  {'audio_tracks': [{'output_path': str(self.source), 'duration_seconds': 1,
                                    'source_in_seconds': .25, 'volume': .2,
                                    'fade_in_seconds': .1, 'fade_out_seconds': .1}]}),
                 ({}, {'fps': 24, 'video_bitrate': 1_000_000, 'output_resolution': 'source'}),
                 ({}, {'text_overlays': [{**text, 'box': {'x': 10, 'y': 30, 'width': 180, 'height': 80},
                                         'min_font_size': 16, 'max_font_size': 24,
                                         'font_family': 'dejavu-sans-bold'}]})]
        covered = set()
        from providers.remotion.capabilities import CAPABILITIES, field_capabilities
        declared = field_capabilities()
        for visual, options in cases:
            with self.subTest(visual=visual, options=options):
                args = {**arguments(str(self.source), **visual), **options}
                for field, capability in declared.items():
                    section, _, name = field.partition('.')
                    if ((not name and section in args) or
                            (name and any(name in item for item in args.get(section) or []))):
                        covered.update(key for key, value in CAPABILITIES.items() if value == capability)
                props, _ = self.render_local(args)
                payload = self.lambda_payload(args)
                expected = copy.deepcopy(props)
                for asset in expected['document']['assets']:
                    asset['url'] = 'https://media.invalid/' + Path(asset['url']).name
                self.assertEqual(json.loads(payload['inputProps']['payload']), expected)
                wire = json.loads((Path(__file__).parent / 'fixtures/remotion-lambda-request.json').read_text())
                wire.update(inputProps={'type': 'payload', 'payload': json.dumps(expected, separators=(',', ':'))},
                            forceFps=props['renderConfig']['fps'], videoBitrate=props['renderConfig']['videoBitrate'],
                            crf=props['renderConfig']['crf'])
                self.assertEqual(payload, wire)
                self.assertEqual(payload['codec'], 'h264')
                self.assertEqual(payload['forceFps'], props['renderConfig']['fps'])
        self.assertTrue({'identity', 'clip_timing', 'speed', 'source_metadata', 'transitions', 'fit_position',
                         'scale', 'rotation', 'motion', 'grade', 'opacity_fades', 'source_audio', 'audio_mix',
                         'titles', 'captions', 'fitted_overlays', 'canvas', 'encoding'} <= covered)

    def test_positioned_still_overlay_tracks_and_gaps_match_lambda_document(self):
        args = arguments(str(self.source), start_seconds=.125, duration_seconds=.875)
        args['visuals'].append({'kind': 'image', 'url': str(self.still), 'duration_seconds': .5,
                               'start_seconds': .25, 'track': 1,
                               'box': {'x': 220, 'y': 10, 'width': 80, 'height': 60},
                               'scale': .75, 'rotation_degrees': 15, 'motion': 'pan_right', 'grade': 'warm'})
        props, path = self.render_local(args)
        payload = self.lambda_payload(args)
        sent = json.loads(payload['inputProps']['payload'])
        self.assertEqual(sent['document']['tracks'], props['document']['tracks'])
        self.assertEqual(sent['renderConfig'], props['renderConfig'])
        _, baseline = self.render_local(arguments(str(self.source), start_seconds=.125, duration_seconds=.875))
        delta = ImageChops.difference(self.frame(path), self.frame(baseline))
        self.assertIsNotNone(delta.crop((220, 10, 300, 70)).getbbox())
        self.assertLess(max(ImageStat.Stat(delta.crop((0, 110, 140, 180))).mean), 2)

    def test_native_aspect_canvases_match_declared_lambda_configuration(self):
        for aspect in api.ASPECT_SIZES:
            with self.subTest(aspect=aspect):
                args = {**arguments(str(self.source), duration_seconds=.25), 'aspect_ratio': aspect}
                props, _ = self.render_local(args)
                sent = json.loads(self.lambda_payload(args)['inputProps']['payload'])
                self.assertEqual(sent['renderConfig'], props['renderConfig'])

    def test_srt_is_literal_output_timed_caption_text_on_both_paths(self):
        args = arguments(str(self.source))
        args['subtitles_srt'] = "1\n00:00:00,250 --> 00:00:00,750\nBuy $1: 'now'\n"
        props, path = self.render_local(args)
        caption = props['document']['tracks'][-1]['items'][0]
        self.assertEqual((caption['text'], caption['start'], caption['duration']), ("Buy $1: 'now'", .25, .5))
        payload = self.lambda_payload(args)
        self.assertEqual(json.loads(payload['inputProps']['payload'])['document']['tracks'],
                         props['document']['tracks'])
        self.assertTrue(path.is_file())

    def test_motion_grade_rotation_change_real_pixels(self):
        _, baseline = self.render_local(arguments(str(self.source)))
        original = self.frame(baseline)
        for field, value in [('motion', 'zoom_in'), ('motion', 'zoom_out'), ('motion', 'pan_left'),
                             ('motion', 'pan_right'), ('grade', 'neutral'), ('grade', 'warm'),
                             ('rotation_degrees', 35), ('scale', .5)]:
            with self.subTest(field=field, value=value):
                _, output = self.render_local(arguments(str(self.source), **{field: value}))
                self.assertIsNotNone(ImageChops.difference(original, self.frame(output)).getbbox())

    def test_linear_motion_moves_a_static_marker_in_the_requested_direction(self):
        from PIL import ImageDraw

        marker = self.root / 'marker.png'
        picture = Image.new('RGB', (320, 180), (0, 0, 80))
        ImageDraw.Draw(picture).rectangle((145, 70, 174, 109), fill=(240, 0, 0))
        picture.save(marker)
        for motion in ('zoom_in', 'zoom_out', 'pan_left', 'pan_right'):
            with self.subTest(motion=motion):
                args = arguments(str(self.source))
                args['visuals'].append({'kind': 'image', 'url': str(marker), 'duration_seconds': 1,
                                       'track': 1, 'motion': motion})
                _, path = self.render_local(args)
                boxes = [self.frame(path, t).split()[0].point(
                    lambda red: 255 if red > 180 else 0).getbbox() for t in (0, .9375)]
                first, last = boxes
                if motion.startswith('zoom'):
                    change = (last[2] - last[0]) - (first[2] - first[0])
                    self.assertGreater(change if motion == 'zoom_in' else -change, 0)
                else:
                    shift = last[0] - first[0]
                    self.assertGreater(shift if motion == 'pan_right' else -shift, 20)

    def test_local_only_features_render_and_lambda_refuses_before_aws(self):
        cases = [arguments(str(self.source), crop_box={'x': 0, 'y': 0, 'width': 160, 'height': 90},
                           reframe_size={'width': 160, 'height': 90}),
                 arguments(str(self.source), fit='pad_blur', pad_box={
                           'x': 30, 'y': 20, 'width': 240, 'height': 140})]
        for args in cases:
            with self.subTest(args=args):
                self.render_local(args)
                with patch.dict(os.environ, {'REMOTION_RENDER_BACKEND': 'lambda', 'REMOTION_DRY_RUN': 'false'}), \
                        patch.object(api, '_visual_metadata') as media, patch.object(api.boto3, 'Session') as aws:
                    with self.assertRaisesRegex(ValueError, 'local/worker'):
                        api.render_timeline(**args)
                    media.assert_not_called()
                    aws.assert_not_called()

    def test_source_audio_visual_fade_fallback_matches_declared_lambda_behavior(self):
        import array
        import math

        _, path = self.render_local(arguments(str(self.source), fade_in_seconds=.4, fade_out_seconds=.4))
        audio = subprocess.check_output(['ffmpeg', '-nostdin', '-hide_banner', '-v', 'error',
            '-i', str(path), '-vn', '-ac', '1', '-ar', '48000', '-f', 'f32le', 'pipe:1'], timeout=20)
        samples = array.array('f', audio)
        def rms(start, end):
            window = samples[round(start * 48000):round(end * 48000)]
            return math.sqrt(sum(value * value for value in window) / len(window))
        self.assertLess(rms(.02, .08), rms(.45, .55) / 3)
        self.assertLess(rms(.93, .99), rms(.45, .55) / 3)


if __name__ == '__main__':
    unittest.main()
