from __future__ import annotations

import copy
import io
import struct
import unittest
import wave
from unittest.mock import patch

from providers.remotion import api
from providers.remotion.capabilities import validate_document
from providers.remotion.templates import (
    group_captions, layout_for_aspect, pcm_amplitudes, progress_at, template_plan,
)


def words(count=13):
    return [{'text': f'word{i}', 'start': i / 10, 'end': (i + 1) / 10} for i in range(count)]


def audiogram():
    return {'name': 'podcast-audiogram', 'duration_seconds': 2, 'words': words(),
            'amplitudes': [0.2] * 60, 'show_name': 'The show', 'speaker_name': 'Ada'}


class CaptionPlannerTests(unittest.TestCase):
    def test_groups_rebalance_single_tail_and_preserve_text_and_timing(self):
        source = words()
        source[2]['text'] = 'um,'
        source[3]['text'] = 'Renderhaus'
        groups, flags = group_captions(source, duration=2, correction_terms=['Renderhaus'])
        self.assertEqual([len(group['words']) for group in groups], [6, 5, 2])
        self.assertEqual([word for group in groups for word in group['words']], source)
        self.assertEqual(groups[0]['text'], 'word0 word1 um, Renderhaus word4 word5')
        self.assertEqual(groups[0]['start'], 0)
        self.assertEqual(groups[-1]['end'], 1.3)
        self.assertEqual(flags, [{'word_index': 3, 'text': 'Renderhaus'}])

    def test_fillers_are_only_removed_when_requested(self):
        source = [{'text': 'uh', 'start': 0, 'end': .2},
                  {'text': 'Hello', 'start': .2, 'end': .5},
                  {'text': 'world!', 'start': .5, 'end': 1}]
        self.assertEqual(group_captions(source, duration=1)[0][0]['text'], 'uh Hello world!')
        self.assertEqual(group_captions(source, duration=1, remove_fillers=True)[0][0]['text'], 'Hello world!')

    def test_bad_words_refuse_without_inventing_timestamps(self):
        for source in ([{'text': 'x', 'start': 1, 'end': .5}],
                       [{'text': 'x', 'start': 0, 'end': float('nan')}],
                       [{'text': 'x', 'start': 0, 'end': 3}],
                       [{'text': 'x', 'start': 0, 'end': 1}, {'text': 'y', 'start': .5, 'end': 2}]):
            with self.subTest(source=source), self.assertRaises(ValueError):
                group_captions(source, duration=2)

    def test_every_longer_quote_has_groups_of_two_to_six(self):
        for count in range(2, 100):
            groups, _ = group_captions(words(count), duration=10)
            self.assertTrue(all(2 <= len(group['words']) <= 6 for group in groups), count)


class TemplatePlannerTests(unittest.TestCase):
    def test_all_aspects_keep_content_inside_safe_rectangle(self):
        for aspect in ('9:16', '1:1', '4:5', '16:9'):
            layout = layout_for_aspect(aspect)
            safe = layout['safe']
            for key, box in layout.items():
                with self.subTest(aspect=aspect, key=key):
                    self.assertGreaterEqual(box['x'], safe['x'])
                    self.assertGreaterEqual(box['y'], safe['y'])
                    self.assertLessEqual(box['x'] + box['width'], safe['x'] + safe['width'] + 1e-9)
                    self.assertLessEqual(box['y'] + box['height'], safe['y'] + safe['height'] + 1e-9)

    def test_progress_has_exact_first_and_last_frame_endpoints(self):
        self.assertEqual([progress_at(f, 60) for f in (0, 30, 59)], [0, 30 / 59, 1])
        self.assertEqual(progress_at(100, 60), 1)

    def test_waveform_is_bounded_and_count_matches_timeline(self):
        plan = template_plan(audiogram(), aspect_ratio='1:1', fps=30, width=200, height=200)
        self.assertEqual(plan['bars'], 32)
        self.assertEqual(plan['amplitudes'], [.2] * 60)
        for mutation in ({'amplitudes': [0] * 59}, {'amplitudes': [2] * 60},
                         {'waveform': 'random'}, {'bars': 300}, {'duration_seconds': 91},
                         {'fps': 120}, {'unexpected': True}):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                template_plan({**audiogram(), **mutation}, aspect_ratio='1:1', fps=30, width=200, height=200)

    def test_channel_templates_enforce_duration_and_reserve_empty_native_zones(self):
        for duration in (2, 6):
            with self.assertRaises(ValueError):
                template_plan({'name': 'youtube-intro-sting', 'duration_seconds': duration},
                              aspect_ratio='16:9', fps=30, width=1920, height=1080)
        end = template_plan({'name': 'youtube-end-screen', 'duration_seconds': 20, 'show_name': 'Subscribe'},
                            aspect_ratio='16:9', fps=30, width=1920, height=1080)
        for zone in end['reserved_zones']:
            for key in ('art', 'identity', 'captions'):
                box = end['layout'][key]
                self.assertFalse(box['x'] < zone['x'] + zone['width'] and zone['x'] < box['x'] + box['width']
                                 and box['y'] < zone['y'] + zone['height'] and zone['y'] < box['y'] + box['height'])
        with self.assertRaises(ValueError):
            template_plan({'name': 'youtube-end-screen', 'duration_seconds': 20},
                          aspect_ratio='9:16', fps=30, width=1080, height=1920)

    def test_phrase_srt_keeps_cues_and_does_not_invent_word_highlights(self):
        data = audiogram()
        del data['words']
        data['captions_srt'] = '1\n00:00:00,000 --> 00:00:01,000\nHello world'
        plan = template_plan(data, aspect_ratio='1:1', fps=30, width=200, height=200)
        self.assertEqual(plan['captions'][0]['text'], 'Hello world')
        self.assertEqual(plan['captions'][0]['words'], [])
        self.assertIn('cue timing', ' '.join(plan['warnings']))

    def test_wide_glyph_captions_refuse_overflow_before_media(self):
        raw = audiogram()
        raw['words'] = [{'text': 'W' * 80, 'start': 0, 'end': 1}]
        with self.assertRaisesRegex(ValueError, 'text_overflow'):
            template_plan(raw, aspect_ratio='9:16', fps=30, width=1080, height=1920)

    def test_landscape_fit_uses_actual_canvas_and_blank_srt_is_refused(self):
        props = api.build_timeline_props(title='End', visuals=[], aspect_ratio='16:9',
            template={'name': 'youtube-end-screen', 'duration_seconds': 20, 'show_name': 'W' * 25})
        self.assertEqual((props['template']['width'], props['template']['height']), (1920, 1080))
        raw = audiogram()
        del raw['words']
        raw['captions_srt'] = '1\n00:00:00,000 --> 00:00:01,000\n   '
        with self.assertRaises(ValueError):
            template_plan(raw, aspect_ratio='1:1', fps=30, width=1080, height=1080)


class AudioEnvelopeTests(unittest.TestCase):
    def test_pcm_envelope_tracks_real_energy_without_normalizing_source(self):
        handle = io.BytesIO()
        with wave.open(handle, 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(16000)
            out.writeframes(b'\0\0' * 8000 + struct.pack('<h', 16384) * 8000)
        result = pcm_amplitudes(io.BytesIO(handle.getvalue()), duration=1, fps=20, smoothing=0)
        self.assertEqual(result[:10], [0] * 10)
        self.assertEqual(result[10:], [.5] * 10)
        self.assertEqual(len(result), 20)

    def test_stereo_energy_does_not_cancel_opposite_phases(self):
        handle = io.BytesIO()
        with wave.open(handle, 'wb') as out:
            out.setparams((2, 2, 16000, 0, 'NONE', 'not compressed'))
            out.writeframes(struct.pack('<hh', 16384, -16384) * 16000)
        result = pcm_amplitudes(io.BytesIO(handle.getvalue()), duration=1, fps=20, smoothing=0)
        self.assertEqual(result, [.5] * 20)


class TemplateBoundaryTests(unittest.TestCase):
    def test_unsupported_caption_or_name_glyphs_refuse_before_media_io(self):
        for field, text in (('words', '你好'), ('words', '🤖'), ('speaker_name', '你好')):
            raw = audiogram()
            raw[field] = [{'text': text, 'start': 0, 'end': 1}] if field == 'words' else text
            with self.subTest(field=field, text=text), \
                    patch.dict('os.environ', {'REMOTION_DRY_RUN': 'true', 'REMOTION_RENDER_BACKEND': 'local'}), \
                    patch.object(api, '_start_render') as render, patch.object(api, '_visual_metadata') as probe:
                with self.assertRaisesRegex(ValueError, 'text_unsupported_glyph'):
                    api.render_timeline(title='Podcast', visuals=[], template=raw,
                        audio_tracks=[{'url': 'missing.wav', 'duration_seconds': 2}])
                render.assert_not_called()
                probe.assert_not_called()

    def test_real_gateway_template_dry_run_is_validated_without_io(self):
        with patch.dict('os.environ', {'REMOTION_DRY_RUN': 'true', 'REMOTION_RENDER_BACKEND': 'local'}), \
                patch.object(api.boto3, 'Session') as aws, patch.object(api, '_visual_metadata') as probe:
            result = api.render_timeline(title='Podcast', visuals=[], template=audiogram(),
                                         audio_tracks=[{'url': 'missing.wav', 'duration_seconds': 2}], aspect_ratio='1:1')
            self.assertEqual(result['status'], 'dry_run')
            self.assertEqual(result['template_preview']['review_times_seconds'], [.2, 1.2])
            self.assertEqual(result['template_preview']['captions'][0]['text'], 'word0 word1 word2 word3 word4 word5')
            aws.assert_not_called()
            probe.assert_not_called()

    def test_old_lambda_composition_refuses_before_aws_or_media(self):
        with patch.dict('os.environ', {'REMOTION_DRY_RUN': 'false', 'REMOTION_RENDER_BACKEND': 'lambda',
                                      'REMOTION_TEMPLATE_CONTRACT_VERSION': '0'}), patch.object(api.boto3, 'Session') as aws:
            with self.assertRaisesRegex(ValueError, 'template contract'):
                api.render_timeline(title='Podcast', visuals=[], template=audiogram(),
                                     audio_tracks=[{'url': 'missing.wav', 'duration_seconds': 2}])
            aws.assert_not_called()

    def test_canonical_plan_cannot_be_changed_after_validation(self):
        props = api.build_timeline_props(title='Podcast', visuals=[], template=audiogram(),
                                        audio_tracks=[{'url': 'missing.wav', 'duration_seconds': 2}],
                                        aspect_ratio='1:1', measure_local=False)
        validate_document(props, 'local')
        broken = copy.deepcopy(props)
        broken['template']['layout']['captions']['y'] = .99
        with self.assertRaises(ValueError):
            validate_document(broken, 'local')


if __name__ == '__main__':
    unittest.main()
