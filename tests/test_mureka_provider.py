from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import wave
from contextlib import ExitStack
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx


class MurekaProviderTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('providers.mureka.api'), 'Mureka provider is not implemented')
        from providers.mureka import api, contracts

        self.api, self.contracts = api, contracts
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.dict(os.environ, {'MUREKA_DRY_RUN': 'true', 'FAL_DRY_RUN': 'true', 'MUREKA_MODEL': 'mureka-9.5', 'RENDERHAUS_MEDIA_DIR': self.root}))
        self.submit_patch = patch('providers.fal.queue.submit', return_value={'request_id': 'req_123', 'status': 'IN_QUEUE'})
        self.submit = self.submit_patch.start()
        self.addCleanup(self.submit_patch.stop)
        self.quote_patch = patch('server.billing_rates.mureka_price_cents', return_value=Decimal('22.5'), create=True)
        self.quote = self.quote_patch.start()
        self.addCleanup(self.quote_patch.stop)

    def live(self):
        self.stack.enter_context(patch.dict(os.environ, {'MUREKA_DRY_RUN': 'false', 'FAL_DRY_RUN': 'false'}))

    def queued(self, kind='song'):
        self.live()
        if kind == 'song':
            return self.api.generate_song(lyrics='Hello world')
        return self.api.generate_instrumental(prompt='Warm piano')

    def poll_dependencies(self, result=None, status=None):
        self.stack.enter_context(patch('providers.fal.queue.status', return_value=status or {'status': 'COMPLETED'}))
        self.stack.enter_context(patch('providers.fal.queue.result', return_value=result or {'song_id': 'song_1', 'audio': {'url': 'https://media.example.test/music.mp3', 'content_type': 'audio/mpeg'}, 'duration': 12000, 'lyrics_sections': [{'start': 0, 'end': 12000, 'lines': [{'text': 'Hello world', 'start': 0, 'end': 12000}]}]}))

    def test_default_song_is_preview_without_media_or_submit(self):
        result = self.api.generate_song(lyrics='Hello world')
        self.assertEqual(result['status'], 'dry_run')
        self.assertEqual(result['model'], 'mureka-9.5')
        self.assertFalse(result['training_eligible'])
        self.assertNotIn('audio_url', result)
        self.assertNotIn('output_path', result)
        self.submit.assert_not_called()

    def test_either_dry_run_flag_prevents_paid_submission(self):
        for mureka, fal in [('true', 'false'), ('false', 'true')]:
            with self.subTest(mureka=mureka, fal=fal), patch.dict(os.environ, {'MUREKA_DRY_RUN': mureka, 'FAL_DRY_RUN': fal}):
                self.assertEqual(self.api.generate_instrumental(prompt='Piano')['status'], 'dry_run')
        self.submit.assert_not_called()

    def test_song_body_uses_official_fields_and_retains_style_prompt(self):
        result = self.queued()
        self.assertEqual(result['status'], 'queued')
        self.assertEqual(self.submit.call_args.args, ('mureka/api/generate/song', {'lyrics': 'Hello world', 'model': 'mureka-9.5', 'enable_safety_checker': True}))
        body = self.contracts.request_for('generate_song', {'lyrics': 'Words', 'prompt': 'Warm jazz', 'gender': 'female'}).fal_body()
        self.assertEqual(body['prompt'], 'Warm jazz')
        self.assertEqual(body['gender'], 'female')
        self.assertNotIn('n', body)

    def test_prompt_mode_accepts_documented_styles(self):
        body = self.contracts.request_for('generate_song', {'prompt': 'Love song', 'styles': ['pop', 'lo-fi']}).fal_body()
        self.assertEqual(body['styles'], ['pop', 'lo-fi'])

    def test_invalid_song_controls_never_submit(self):
        self.live()
        for args in [{}, {'lyrics': ' '}, {'prompt': 'x' * 2001}, {'lyrics': 'x' * 5001}, {'lyrics': 'Words', 'styles': ['pop']}, {'prompt': 'Words', 'styles': []}, {'prompt': 'Words', 'styles': ['invented']}, {'prompt': 'Words', 'gender': 'male'}, {'prompt': 5}, {'prompt': 'Words', 'vocal_id': 'clone'}]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.contracts.request_for('generate_song', args)
        self.submit.assert_not_called()

    def test_instrumental_requires_exactly_one_source(self):
        for args in [{}, {'prompt': 'Piano', 'instrumental_id': 'reference'}, {'prompt': 'x' * 1025}, {'prompt': ' '}]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.contracts.request_for('generate_instrumental', args)
        body = self.contracts.request_for('generate_instrumental', {'instrumental_id': 'ref_1'}).fal_body()
        self.assertEqual(body['instrumental_id'], 'ref_1')

    def test_unknown_model_remains_unverified_preview_when_live_enabled(self):
        self.live()
        with patch.dict(os.environ, {'MUREKA_MODEL': 'mureka-future'}):
            result = self.api.generate_song(prompt='Love song')
        self.assertEqual(result['status'], 'dry_run')
        self.assertIn('UNVERIFIED', result['verification'])
        self.assertIsNone(result['estimated_cost_usd'])
        self.submit.assert_not_called()

    def test_model_override_is_not_silently_replaced(self):
        result = self.api.generate_instrumental(prompt='Piano', model='mureka-future')
        self.assertEqual(result['model'], 'mureka-future')
        self.assertEqual(result['request_preview']['model'], 'mureka-future')

    def test_video_body_supports_rows_and_vertical_layout(self):
        result = self.api.generate_lyrics_video(song_id='song_1', layout='layout_3', aspect_ratio='9:16', lyrics_start_row=1, lyrics_end_row=4, title='My song')
        self.assertEqual(result['status'], 'dry_run')
        body = result['request_preview']
        self.assertEqual(body['song_id'], 'song_1')
        self.assertEqual(body['lyrics_start_row'], 1)
        self.assertNotIn('model', body)
        self.assertNotIn('audio_url', body)

    def test_video_supports_uploaded_audio_and_millisecond_selection(self):
        body = self.contracts.request_for('generate_lyrics_video', {'upload_audio_id': 'upload_1', 'selection_start': 0, 'selection_end': 12000, 'aspect_ratio': '16:9'}).fal_body()
        self.assertEqual(body['selection_end'], 12000)
        self.assertEqual(body['aspect_ratio'], '16:9')

    def test_video_rejects_invalid_sources_ranges_and_layout(self):
        bad = [{}, {'song_id': 's', 'upload_audio_id': 'u'}, {'song_id': 's', 'lyrics_start_row': 1}, {'song_id': 's', 'lyrics_start_row': 3, 'lyrics_end_row': 1}, {'song_id': 's', 'lyrics_start_row': 1, 'lyrics_end_row': 2, 'selection_start': 0, 'selection_end': 100}, {'song_id': 's', 'selection_start': 10, 'selection_end': 10}, {'song_id': 's', 'selection_start': True, 'selection_end': 100}, {'song_id': 's', 'layout': 'layout_8'}, {'song_id': 's', 'cover_url': 'https://media.example.test/cover.png'}, {'song_id': 's', 'layout': 'layout_2', 'cover_url': 'http://localhost/image.jpg'}, {'song_id': 's', 'audio_url': 'https://example.test/music.mp3'}]
        for args in bad:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.contracts.request_for('generate_lyrics_video', args)

    def test_live_video_uses_same_fal_endpoint_request_handle(self):
        self.live()
        result = self.api.generate_lyrics_video(song_id='song_1')
        self.assertEqual(result['job_id'], 'mureka/api/generate/lyrics-video:req_123')
        self.assertEqual(result['capability_id'], 'mureka_lyrics_video')
        self.assertEqual(self.submit.call_args.args[0], 'mureka/api/generate/lyrics-video')

    def test_unknown_price_blocks_live_submit(self):
        self.live()
        self.quote.return_value = None
        with self.assertRaisesRegex(ValueError, 'unknown'):
            self.api.generate_song(prompt='Love song')
        self.submit.assert_not_called()

    def test_missing_request_id_is_not_success(self):
        self.live()
        self.submit.return_value = {'status': 'IN_QUEUE'}
        with self.assertRaises(RuntimeError):
            self.api.generate_instrumental(prompt='Piano')

    def test_music_poll_preserves_model_after_environment_changes(self):
        job = self.queued()
        self.poll_dependencies()
        with patch.dict(os.environ, {'MUREKA_MODEL': 'mureka-future'}):
            result = self.api.get_music_task(job['job_id'])
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['model'], 'mureka-9.5')
        self.assertEqual(result['song_id'], 'song_1')
        self.assertEqual(result['duration_seconds'], 12)
        self.assertEqual(result['lyrics_sections'][0]['lines'][0]['text'], 'Hello world')
        self.assertIsNone(result.get('output_path'))
        self.assertFalse(result['downloaded'])
        self.assertEqual(self.submit.call_count, 1)

    def test_instrumental_poll_preserves_kind(self):
        job = self.queued('instrumental')
        self.poll_dependencies()
        result = self.api.get_music_task(job['job_id'])
        self.assertEqual(result['mode'], 'generate_instrumental')

    def test_poll_pending_and_failure_do_not_fetch_result(self):
        job = self.queued()
        with patch('providers.fal.queue.status', return_value={'status': 'IN_PROGRESS'}), patch('providers.fal.queue.result') as result:
            self.assertEqual(self.api.get_music_task(job['job_id'])['status'], 'running')
            result.assert_not_called()
        with patch('providers.fal.queue.status', return_value={'status': 'IN_PROGRESS', 'error': 'denied'}):
            self.assertEqual(self.api.get_music_task(job['job_id'])['status'], 'failed')

    def test_dry_run_handles_stay_previews_after_flag_changes(self):
        music = self.api.generate_song(prompt='A song')
        video = self.api.generate_lyrics_video(song_id='song_1')
        self.live()
        with patch('providers.fal.queue.status') as status:
            self.assertEqual(self.api.get_music_task(music['job_id'])['status'], 'dry_run')
            self.assertEqual(self.api.get_video_task(video['job_id'])['status'], 'dry_run')
            status.assert_not_called()

    def test_malformed_job_ids_are_rejected_without_network(self):
        for job in ['../secret', 'https://evil.test/request', 'mureka:music:song:mureka-9.5:../secret', 'mureka/api/generate/song:req_123']:
            with self.subTest(job=job), self.assertRaises(ValueError):
                self.api.get_music_task(job)
        with self.assertRaises(ValueError):
            self.api.get_video_task('mureka/api/generate/lyrics-video:../secret')

    def test_success_requires_audio_url_and_valid_duration(self):
        job = self.queued()
        for result in [{'audio': {}}, {'audio': {'url': 'javascript:bad'}}, {'audio': {'url': 'https://media.example.test/music.mp3', 'content_type': 'audio/mpeg'}, 'duration': -1}, {'audio': {'url': 'https://media.example.test/music.mp3', 'content_type': 'audio/mpeg'}, 'duration': True}]:
            with self.subTest(result=result), patch('providers.fal.queue.status', return_value={'status': 'COMPLETED'}), patch('providers.fal.queue.result', return_value=result), self.assertRaises(RuntimeError):
                self.api.get_music_task(job['job_id'])

    def test_completed_video_uses_shared_poller_and_keeps_mureka_provenance(self):
        self.live()
        with patch('providers.fal.api._poll_video_task', return_value={'status': 'succeeded', 'video_url': 'https://media.example.test/music.mp4', 'downloaded': False}) as poll:
            result = self.api.get_video_task('mureka/api/generate/lyrics-video:req_123')
        self.assertEqual(result['provider'], 'mureka')
        self.assertFalse(result['training_eligible'])
        self.assertEqual(poll.call_args.args[:3], ('mureka/api/generate/lyrics-video:req_123', 'mureka/api/generate/lyrics-video', 'req_123'))

    def test_audio_download_is_atomic_validated_and_does_not_store_signed_urls(self):
        if not shutil.which('ffmpeg'):
            self.skipTest('Local ffmpeg required to construct an actual MP3 fixture')
        fixture = Path(self.root) / 'fixture.mp3'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.1', '-y', str(fixture)], check=True)
        job = self.queued()
        self.poll_dependencies({'song_id': 'song_1', 'audio': {'url': 'https://media.example.test/music.mp3?signature=secret', 'content_type': 'audio/mpeg'}, 'duration': 100})
        response = MagicMock()
        response.iter_bytes.return_value = [fixture.read_bytes()]
        response.__enter__.return_value = response
        with patch('httpx.stream', return_value=response):
            result = self.api.get_music_task(job['job_id'], download=True)
        path = Path(result['output_path'])
        self.assertTrue(result['downloaded'])
        self.assertGreater(path.stat().st_size, 0)
        self.assertFalse(list(path.parent.glob('*.tmp')))
        self.assertFalse(any('signature=secret' in p.read_text(errors='ignore') for p in Path(self.root).rglob('*.json')))

    def test_corrupt_audio_download_leaves_no_artifact(self):
        job = self.queued()
        self.poll_dependencies()
        response = MagicMock()
        response.iter_bytes.return_value = [b'<html>provider error</html>']
        response.__enter__.return_value = response
        with patch('httpx.stream', return_value=response), self.assertRaises(RuntimeError):
            self.api.get_music_task(job['job_id'], download=True)
        self.assertFalse(list(Path(self.root).rglob('*.mp3')))
        self.assertFalse(list(Path(self.root).rglob('*.tmp')))

    def test_generic_wav_output_keeps_extension_and_validates_actual_container(self):
        if not shutil.which('ffprobe'):
            self.skipTest('Local ffprobe required for verified non-MP3 audio')
        data = io.BytesIO()
        with wave.open(data, 'wb') as file:
            file.setnchannels(1)
            file.setsampwidth(2)
            file.setframerate(8000)
            file.writeframes(b'\x00\x00' * 800)
        job = self.queued()
        self.poll_dependencies({'audio': {'url': 'https://media.example.test/file', 'content_type': 'audio/wav', 'file_name': 'song.wav'}, 'duration': 100})
        response = MagicMock()
        response.__enter__.return_value = response
        response.iter_bytes.return_value = [data.getvalue()]
        with patch('httpx.stream', return_value=response):
            result = self.api.get_music_task(job['job_id'], download=True)
        self.assertEqual(Path(result['output_path']).suffix, '.wav')
        self.assertEqual(result['audio_content_type'], 'audio/wav')
        self.assertTrue(result['downloaded'])

    def test_filename_identifies_supported_audio_when_mime_is_absent(self):
        job = self.queued()
        self.poll_dependencies({'audio': {'url': 'https://media.example.test/file', 'file_name': 'Song.MP3'}})
        result = self.api.get_music_task(job['job_id'])
        self.assertEqual(result['audio_content_type'], 'audio/mpeg')
        self.assertFalse(result['downloaded'])

    def test_unknown_or_contradictory_audio_format_is_rejected_before_download(self):
        job = self.queued()
        values = [
            {'content_type': 'audio/unknown', 'file_name': 'song.mp3'},
            {'content_type': 'audio/mpeg', 'file_name': 'song.wav'},
            {'content_type': 'text/html'},
            {'content_type': 1},
            {'file_name': 'song.unsupported'},
            {'file_name': 1},
            {},
        ]
        for fields in values:
            output = {'audio': {'url': 'https://media.example.test/file', **fields}}
            with self.subTest(fields=fields), patch('providers.fal.queue.status', return_value={'status': 'COMPLETED'}), patch('providers.fal.queue.result', return_value=output), patch('httpx.stream') as download:
                with self.assertRaises(RuntimeError):
                    self.api.get_music_task(job['job_id'], download=True)
                download.assert_not_called()

    def test_mp3_label_does_not_accept_a_wav_container(self):
        if not shutil.which('ffprobe'):
            self.skipTest('Local ffprobe required to compare claimed and actual audio formats')
        data = io.BytesIO()
        with wave.open(data, 'wb') as file:
            file.setnchannels(1)
            file.setsampwidth(2)
            file.setframerate(8000)
            file.writeframes(b'\x00\x00' * 800)
        job = self.queued()
        self.poll_dependencies()
        response = MagicMock()
        response.__enter__.return_value = response
        response.iter_bytes.return_value = [data.getvalue()]
        with patch('httpx.stream', return_value=response), self.assertRaises(RuntimeError):
            self.api.get_music_task(job['job_id'], download=True)
        self.assertFalse(list(Path(self.root).rglob('*.mp3')))
        self.assertFalse(list(Path(self.root).rglob('*.tmp')))

    def test_non_mp3_download_requires_available_container_validation(self):
        job = self.queued()
        self.poll_dependencies({'audio': {'url': 'https://media.example.test/file', 'content_type': 'audio/flac'}})
        with patch('shutil.which', return_value=None), patch('httpx.stream') as download, self.assertRaisesRegex(RuntimeError, 'ffprobe'):
            self.api.get_music_task(job['job_id'], download=True)
        download.assert_not_called()

    def test_real_billing_helper_quotes_gateway_arguments_without_wire_fields(self):
        self.quote_patch.stop()
        self.live()
        for tool, arguments, price in [
            ('generate_song', {'lyrics': 'Hello world'}, 0.225),
            ('generate_song', {'prompt': 'Love song'}, 0.75),
            ('generate_instrumental', {'prompt': 'Piano'}, 0.225),
            ('generate_lyrics_video', {'song_id': 'song_1'}, 0.15),
        ]:
            with self.subTest(tool=tool, arguments=arguments):
                result = getattr(self.api, tool)(**arguments)
                self.assertEqual(result['status'], 'queued')
                self.assertEqual(result['estimated_cost_usd'], price)

    def test_catalog_is_offline_and_reports_terms_and_price_sources(self):
        catalog = self.api.list_mureka_models()
        self.assertEqual(catalog['read_date'], '2026-10-09')
        self.assertFalse(catalog['training_eligible'])
        self.assertEqual(len(catalog['models']), 3)
        self.assertTrue(all(row['api_url'].startswith('https://fal.ai/models/mureka/') for row in catalog['models']))
        self.submit.assert_not_called()


class MurekaHTTPTransportTests(unittest.TestCase):
    def setUp(self):
        MurekaProviderTests.setUp(self)
        self.submit_patch.stop()
        self.http_client_type = httpx.Client
        MurekaProviderTests.live(self)
        self.stack.enter_context(patch.dict(os.environ, {'FAL_KEY': 'offline-test-only-key'}))

    def transport(self, handler):
        client_type = self.http_client_type
        transport = httpx.MockTransport(handler)
        return self.stack.enter_context(patch('providers.fal.queue.httpx.Client', side_effect=lambda **kwargs: client_type(transport=transport, **kwargs)))

    def test_actual_queue_submits_each_verified_endpoint_and_body(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={'request_id': 'http_req', 'status': 'IN_QUEUE'})

        self.transport(handler)
        song = self.api.generate_song(prompt='Love song', styles=['pop'])
        instrumental = self.api.generate_instrumental(prompt='Piano')
        video = self.api.generate_lyrics_video(song_id='song_1', selection_start=0, selection_end=1000)
        self.assertEqual([result['status'] for result in [song, instrumental, video]], ['queued'] * 3)
        self.assertEqual([request.method for request in requests], ['POST'] * 3)
        self.assertEqual([request.url.path for request in requests], ['/mureka/api/generate/song', '/mureka/api/generate/instrumental', '/mureka/api/generate/lyrics-video'])
        self.assertTrue(all(request.url.host == 'queue.fal.run' for request in requests))
        self.assertTrue(all(request.headers['authorization'] == 'Key offline-test-only-key' for request in requests))
        self.assertEqual(json.loads(requests[0].content), {'prompt': 'Love song', 'styles': ['pop'], 'model': 'mureka-9.5', 'enable_safety_checker': True})
        self.assertNotIn('model', json.loads(requests[2].content))
        self.assertEqual(json.loads(requests[2].content)['selection_end'], 1000)

    def test_real_status_and_result_routes_preserve_audio_and_song_chain(self):
        requests = []

        def handler(request):
            requests.append((request.method, request.url.path))
            if request.method == 'POST':
                return httpx.Response(200, json={'request_id': 'http_req'})
            if request.url.path.endswith('/status'):
                return httpx.Response(200, json={'status': 'COMPLETED'})
            return httpx.Response(200, json={'song_id': 'song_from_http', 'duration': 1000, 'audio': {'url': 'https://media.example.test/generated.mp3', 'content_type': 'audio/mpeg'}, 'lyrics_sections': [{'start': 0, 'end': 1000, 'lines': [{'text': 'Hello'}]}]})

        self.transport(handler)
        job = self.api.generate_song(lyrics='Hello')
        result = self.api.get_music_task(job['job_id'])
        self.assertEqual(result['song_id'], 'song_from_http')
        self.assertEqual(result['duration_seconds'], 1)
        self.assertEqual(result['lyrics_sections'][0]['lines'][0]['text'], 'Hello')
        self.assertEqual(result['audio_url'], 'https://media.example.test/generated.mp3')
        self.assertEqual(requests, [('POST', '/mureka/api/generate/song'), ('GET', '/mureka/api/requests/http_req/status'), ('GET', '/mureka/api/requests/http_req')])

    def test_live_transport_missing_key_rejects_before_http(self):
        calls = []
        self.transport(lambda request: calls.append(request) or httpx.Response(200, json={'request_id': 'unexpected'}))
        with patch.dict(os.environ, {'FAL_KEY': ''}), self.assertRaisesRegex(RuntimeError, 'FAL_KEY'):
            self.api.generate_song(prompt='Love song')
        self.assertEqual(calls, [])

    def test_failed_paid_submission_is_not_retried(self):
        from providers.fal.queue import FalAPIError

        requests = []
        self.transport(lambda request: requests.append(request) or httpx.Response(401, json={'detail': 'Invalid test account'}))
        with self.assertRaises(FalAPIError):
            self.api.generate_instrumental(prompt='Piano')
        self.assertEqual(len(requests), 1)

    def test_uncertain_paid_submission_is_not_retried(self):
        requests = []

        def handler(request):
            requests.append(request)
            raise httpx.ReadTimeout('Mock transport timeout', request=request)

        self.transport(handler)
        with self.assertRaises(httpx.ReadTimeout):
            self.api.generate_song(prompt='Love song')
        self.assertEqual(len(requests), 1)

    def test_malformed_http_submit_json_is_not_reported_as_queued(self):
        from providers.fal.queue import FalAPIError

        for response in [httpx.Response(200, content=b'not JSON'), httpx.Response(200, json=[]), httpx.Response(200, json={})]:
            with self.subTest(content=response.content):
                self.transport(lambda request, response=response: response)
                with self.assertRaises((FalAPIError, RuntimeError)):
                    self.api.generate_song(prompt='Love song')

    def test_terminal_result_failure_is_not_audio_success(self):
        def handler(request):
            if request.url.path.endswith('/status'):
                return httpx.Response(200, json={'status': 'COMPLETED'})
            return httpx.Response(422, json={'detail': 'Generation rejected'})

        self.transport(handler)
        result = self.api.get_music_task('mureka:music:song:mureka-9.5:http_req')
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result.get('audio_url'))
        self.assertIsNone(result.get('output_path'))

    def test_malformed_remote_audio_output_is_not_an_artifact(self):
        for output in [{'audio': {'url': 'http://localhost/internal'}}, {'song_id': 's'}, {'audio': {'url': 'https://media.example.test/audio.mp3'}, 'duration': '1000'}]:
            def handler(request):
                payload = {'status': 'COMPLETED'} if request.url.path.endswith('/status') else output
                return httpx.Response(200, json=payload)

            with self.subTest(output=output):
                self.transport(handler)
                with self.assertRaises(RuntimeError):
                    self.api.get_music_task('mureka:music:song:mureka-9.5:http_req', download=True)
        self.assertFalse(list(Path(self.root).rglob('*.mp3')))
