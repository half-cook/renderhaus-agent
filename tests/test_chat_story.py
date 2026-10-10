from __future__ import annotations

import copy
import csv
import io
import json
import os
import unittest
from unittest.mock import patch

from providers.remotion import chat_story as chat


class MessageContractTests(unittest.TestCase):
    def test_json_and_csv_preserve_quotes_emoji_rtl_and_whitespace(self):
        text = '  "Hello, friend"\nمرحبا 🙂  '
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(['from', 'text', 'typingMs', 'delayMs', 'status', 'reaction'])
        writer.writerow(['them', text, '900', '600', '', '👍'])
        expected = chat.normalize({'messages': [{'from': 'them', 'text': text, 'typingMs': 900,
                                                  'delayMs': 600, 'reaction': '👍'}]})
        self.assertEqual(chat.normalize({'messages': buffer.getvalue()}), expected)
        self.assertEqual(chat.normalize({'messages': json.dumps(expected['messages'])}), expected)
        self.assertEqual(expected['messages'][0]['text'], text)

    def test_rejects_invalid_rows_without_coercing_sender(self):
        for change in ({'from': 'other'}, {'text': '  '}, {'text': 'a' * 501}, {'text': 12},
                       {'typingMs': True}, {'typingMs': float('nan')}, {'delayMs': -1},
                       {'typingMs': 10001}, {'delayMs': 30001}, {'status': 'verified'},
                       {'reaction': '💰'}, {'html': '<b>x</b>'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                chat.normalize({'messages': [{'from': 'them', 'text': 'Hello', **change}]})

    def test_bounded_tables_and_strict_csv(self):
        for messages in ([], [{'from': 'me', 'text': 'x'}] * 41,
                         'from,text,text\nme,a,b', 'from,text\nme,a,extra', 'from,text\nme,"unterminated'):
            with self.subTest(messages=str(messages)[:50]), self.assertRaises(ValueError):
                chat.normalize({'messages': messages})

    def test_batch_csv_has_one_payload_per_script_row_and_keeps_invalid_rows(self):
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(['variant_key', 'messages', 'contact', 'theme', 'aspect'])
        writer.writerow(['a', json.dumps([{'from': 'me', 'text': 'Hello, 🙂'}]), 'Friend', 'generic', '9:16'])
        writer.writerow(['b', 'not valid JSON', 'Friend', 'generic', '9:16'])
        rows = chat.batch_rows(buffer.getvalue())
        self.assertEqual(len(rows), 2)
        self.assertEqual(chat.normalize(rows[0]['chat_story'])['messages'][0]['text'], 'Hello, 🙂')
        with self.assertRaises(ValueError):
            chat.normalize(rows[1]['chat_story'])
        with self.assertRaises(ValueError):
            chat.batch_rows('variant_key,messages,messages\na,[],[]')

    def test_sent_messages_cannot_have_typing_or_received_receipts(self):
        for row in ({'from': 'me', 'text': 'x', 'typingMs': 500},
                    {'from': 'them', 'text': 'x', 'status': 'read'}):
            with self.assertRaises(ValueError):
                chat.normalize({'messages': [row]})

    def test_phone_numbers_markup_and_photos_refused(self):
        for text in ('Call +1 (416) 555-0123', '416.555.0123', '٠٠١ ٤١٦ ٥٥٥ ٠١٢٣',
                     '<img src=x onerror=alert(1)>', '<script>alert(1)</script>'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                chat.normalize({'messages': [{'from': 'me', 'text': text}]})
        for avatar in ('https://example.com/alice.jpg', '/tmp/alice.jpg', {'url': 'photo'}):
            with self.assertRaises(ValueError):
                chat.normalize({'messages': [{'from': 'me', 'text': 'x'}],
                                'contact': {'name': 'Friend', 'avatar': avatar}})

    def test_impersonation_is_flagged_and_never_silently_rewritten(self):
        payload = chat.normalize({'messages': [{'from': 'them', 'text': 'This is Apple support, send your password'}]})
        self.assertTrue(any('impersonation' in warning for warning in payload['warnings']))
        self.assertEqual(payload['messages'][0]['text'], 'This is Apple support, send your password')

    def test_themes_are_disabled_and_generic_fallback_disclosed(self):
        with patch.dict(os.environ, {'CHAT_STORY_LOOKALIKE_THEMES': 'off'}):
            for theme in ('WhatsApp-style', 'iMessage-style', 'slate', 'moss'):
                payload = chat.normalize({'messages': [{'from': 'me', 'text': 'x'}], 'theme': theme})
                self.assertEqual(payload['theme'], 'generic')
                self.assertTrue(any('not enabled' in note for note in payload['warnings']))
        with patch.dict(os.environ, {'CHAT_STORY_LOOKALIKE_THEMES': 'on'}):
            self.assertEqual(chat.normalize({'messages': [{'from': 'me', 'text': 'x'}], 'theme': 'moss'})['theme'], 'moss')

    def test_normalization_is_idempotent_and_does_not_mutate_input(self):
        source = {'messages': [{'from': 'me', 'text': ' x '}], 'dramatization': True}
        before = copy.deepcopy(source)
        normalized = chat.normalize(source)
        self.assertEqual(source, before)
        self.assertEqual(chat.normalize(normalized), normalized)


class TimingTests(unittest.TestCase):
    def test_frames_and_duration_derive_from_one_clock(self):
        payload = chat.normalize({'messages': [
            {'from': 'them', 'text': 'Hello', 'typingMs': 1000, 'delayMs': 500},
            {'from': 'me', 'text': 'Hi', 'delayMs': 600, 'status': 'read', 'reaction': '👍'},
        ], 'holdMs': 2000})
        plan = chat.plan(payload)
        a, b = plan['bubbles']
        self.assertEqual((a['typingStartFrame'], a['startFrame']), (15, 45))
        self.assertEqual(b['startFrame'], 71)
        self.assertEqual(b['reactionFrame'], b['startFrame'] + 12)
        self.assertEqual(b['receiptFrame'], b['startFrame'] + 9)
        self.assertEqual(plan['durationInFrames'], 139)
        self.assertEqual(plan['sfxCues'], [{'frame': 45, 'kind': 'receive'}, {'frame': 71, 'kind': 'send'}])
        self.assertEqual(chat.plan(payload), plan)

    def test_typing_defaults_scale_with_length_and_are_bounded(self):
        short = chat.normalize({'messages': [{'from': 'them', 'text': 'Hi'}]})
        long = chat.normalize({'messages': [{'from': 'them', 'text': 'x' * 300}]})
        self.assertEqual(short['messages'][0]['typingMs'], 700)
        self.assertEqual(long['messages'][0]['typingMs'], 1500)

    def test_scroll_keeps_newest_bubble_and_typing_in_safe_band(self):
        for aspect in ('9:16', '1:1', '4:5'):
            payload = chat.normalize({'aspect': aspect, 'messages': [
                {'from': 'me' if i % 2 else 'them', 'text': 'Long readable message ' * 7}
                for i in range(20)]})
            plan = chat.plan(payload)
            self.assertGreater(plan['bubbles'][-1]['scrollOffset'], 0)
            for bubble in plan['bubbles']:
                self.assertLessEqual(bubble['y'] + bubble['height'] - bubble['scrollOffset'],
                                     plan['height'] - plan['safeBottom'])
                self.assertLessEqual(bubble['width'], plan['width'] * .74)
            self.assertEqual(plan['bubbles'][-1]['tail'], True)

    def test_warning_for_platform_target_and_no_frame_zero_dump(self):
        plan = chat.plan(chat.normalize({'messages': [{'from': 'me', 'text': 'x'}], 'platformTargetMs': 1000}))
        self.assertGreater(plan['bubbles'][0]['startFrame'], 0)
        self.assertTrue(plan['warnings'])

    def test_extreme_timings_refuse_worker_duration_limit(self):
        with self.assertRaisesRegex(ValueError, '600'):
            chat.plan(chat.normalize({'messages': [{'from': 'them', 'text': 'x', 'typingMs': 10000,
                                                    'delayMs': 30000}] * 40}))

    def test_audio_bed_is_ducked_at_bubble_cues(self):
        payload = chat.normalize({'messages': [{'from': 'me', 'text': 'Hello'}], 'music_ref': 'bed.wav'})
        plan = chat.plan(payload)
        tracks = chat.music_tracks(payload, plan)
        cue = plan['sfxCues'][0]['frame'] / plan['fps']
        self.assertTrue(any(track['start_seconds'] <= cue < track['start_seconds'] + track['duration_seconds']
                            and track['volume'] < .18 for track in tracks))
        self.assertAlmostEqual(sum(t['duration_seconds'] for t in tracks), plan['durationInFrames'] / plan['fps'])


if __name__ == '__main__':
    unittest.main()
