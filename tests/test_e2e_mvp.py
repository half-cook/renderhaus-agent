from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts import e2e_mvp as mvp


class MVPTests(unittest.TestCase):
    def test_source_duration_and_frame_rate_are_checked_before_assembly(self):
        for duration, rate, accepted in [('4.041667', '24/1', True), ('3.958333', '24/1', True),
                                         ('3.9', '24/1', False), ('4', '0/0', False),
                                         ('4', '0/1', False), ('4', 'garbage', False)]:
            metadata = {'streams': [{'codec_type': 'video', 'duration': duration, 'avg_frame_rate': rate}]}
            with self.subTest(duration=duration, rate=rate), patch.object(mvp, 'probe', return_value=metadata):
                if accepted:
                    self.assertEqual(str(mvp.verify_source(Path('source.mp4'))), '24')
                else:
                    with self.assertRaises(ValueError):
                        mvp.verify_source(Path('source.mp4'))

    def test_wrong_codecs_or_changed_frame_rate_fail_before_export_acceptance(self):
        for video_codec, audio_codec, rate in [('hevc', 'aac', '24/1'),
                                               ('h264', 'mp3', '24/1'),
                                               ('h264', 'aac', '30/1')]:
            metadata = {'streams': [{'codec_type': 'video', 'codec_name': video_codec, 'avg_frame_rate': rate},
                                     {'codec_type': 'audio', 'codec_name': audio_codec}]}
            with self.subTest(video=video_codec, audio=audio_codec, fps=rate), \
                    patch.object(mvp, 'probe', return_value=metadata), self.assertRaises(ValueError):
                mvp.verify(Path('final.mp4'), expected_fps='24/1')

    def test_assembly_retry_requires_explicit_live_resume(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(mvp, '_run_locked') as run:
            for arguments in ({}, {'live': True}, {'resume': True}):
                with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                    mvp.run(Path(directory), retry_assembly=True, **arguments)
            run.assert_not_called()

    def test_assembly_retry_archives_confirmed_failure_before_submitting_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'receipt.json'
            previous = {'status': 'queued', 'render_id': 'failed-render', 'bucket_name': 'bucket', 'output_key': 'old-key'}
            receipt = {'steps': {'assembly': previous, 'video-1': {'job_id': 'keep-video'}}}
            mvp.save(path, receipt)
            with patch.object(mvp.remotion, 'get_render_progress', return_value={'status': 'failed'}) as progress:
                mvp.retry_failed_assembly(receipt, path)
            progress.assert_called_once_with('failed-render', 'bucket', 'old-key', download=False)
            def replacement():
                saved = json.loads(path.read_text())
                self.assertEqual(saved['assembly_attempts'], [{**previous, 'status': 'failed'}])
                self.assertEqual(saved['steps']['assembly']['status'], 'submitting')
                self.assertEqual(saved['steps']['video-1']['job_id'], 'keep-video')
                return {'status': 'queued', 'render_id': 'replacement', 'bucket_name': 'bucket'}
            mvp.submit_once(receipt, path, 'assembly', replacement)
            self.assertEqual(receipt['steps']['assembly']['render_id'], 'replacement')

    def test_assembly_retry_refuses_running_successful_missing_or_uncertain_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'receipt.json'
            for status in ('queued', 'running', 'succeeded', 'unknown', 'dry_run'):
                receipt = {'steps': {'assembly': {'status': 'queued', 'render_id': 'original', 'bucket_name': 'bucket'}}}
                mvp.save(path, receipt)
                before = path.read_text()
                with self.subTest(status=status), patch.object(mvp.remotion, 'get_render_progress', return_value={'status': status}), \
                        self.assertRaisesRegex(ValueError, 'definitively failed'):
                    mvp.retry_failed_assembly(receipt, path)
                self.assertEqual(path.read_text(), before)
            for previous in ({}, {'status': 'submitting'}):
                with patch.object(mvp.remotion, 'get_render_progress') as progress, self.assertRaisesRegex(ValueError, 'uncertain'):
                    mvp.retry_failed_assembly({'steps': {'assembly': previous}}, path)
                progress.assert_not_called()

    def test_concurrent_resume_is_rejected_before_reading_receipts_or_contacting_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            with mvp.directory_lock(out):
                result = subprocess.run([sys.executable, '-c',
                    'from pathlib import Path; from scripts.e2e_mvp import run; '
                    'run(Path(__import__("sys").argv[1]), live=True, resume=True)', str(out)],
                    cwd=mvp.ROOT, capture_output=True, text=True, timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('already has an active MVP run', result.stderr)
            self.assertTrue((out / '.run.lock').is_file())
            with patch.object(mvp, '_run_locked', return_value={'status': 'dry_run'}) as run:
                self.assertEqual(mvp.run(out)['status'], 'dry_run')
                run.assert_called_once()

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    def test_decoded_silent_audio_is_rejected_and_audible_audio_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            for name, source in [('silent', 'anullsrc=r=8000:cl=mono'),
                                 ('audible', 'sine=frequency=440:sample_rate=8000')]:
                path = out / (name + '.mp4')
                subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                                'color=size=1280x720:rate=1', '-f', 'lavfi', '-i', source,
                                '-t', '8', '-c:v', 'libx264', '-preset', 'ultrafast',
                                '-c:a', 'aac', str(path)], check=True, capture_output=True, timeout=30)
                if name == 'silent':
                    with self.assertRaisesRegex(ValueError, 'silent or inaudible'):
                        mvp.verify(path)
                else:
                    self.assertEqual(mvp.verify(path)['duration_seconds'], 8)

    def test_dry_run_calls_real_adapters_without_network_and_validates_edit(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True), \
                patch('httpx.Client', side_effect=AssertionError('dry run contacted provider')), \
                patch.object(mvp.seedance, 'text_to_video', wraps=mvp.seedance.text_to_video) as video, \
                patch.object(mvp.fish, 'generate_speech', wraps=mvp.fish.generate_speech) as voice, \
                patch.object(mvp.remotion, 'render_timeline', wraps=mvp.remotion.render_timeline) as render:
            result = mvp.run(Path(directory))
            self.assertEqual(result['status'], 'dry_run')
            self.assertEqual(result['adapter_statuses'], ['dry_run'] * 4)
            self.assertEqual(video.call_count, 2)
            voice.assert_called_once_with(mvp.NARRATION)
            render.assert_called_once()
            props = json.loads((Path(directory) / 'timeline.json').read_text())
            self.assertEqual(props['renderConfig']['durationInFrames'], 192)
            tracks = props['document']['tracks']
            self.assertEqual([item['start'] for item in tracks[0]['items']], [0, 4])
            self.assertEqual([t['name'] for t in tracks], ['Main video', 'Audio 1', 'Titles', 'Subtitles'])
            self.assertFalse((Path(directory) / 'final.mp4').exists())

    def test_secret_live_flags_cannot_override_explicit_dry_mode(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True), \
                patch('server.secrets.fetch_secret_map', return_value={
                    'SEEDANCE_DRY_RUN': 'false', 'FAL_DRY_RUN': 'false',
                    'FISH_AUDIO_DRY_RUN': 'false', 'REMOTION_DRY_RUN': 'false',
                    'RENDERHAUS_SECRETS_NAME': 'renderhaus/app', 'RENDERHAUS_SECRETS_ARN': 'secret-arn',
                    'REMOTION_RENDER_BACKEND': 'local', 'SEEDANCE_TRANSPORT': 'byteplus',
                }):
            mvp.configure(Path(directory), live=False, secrets=True)
            self.assertEqual(os.environ['REMOTION_RENDER_BACKEND'], 'lambda')
            self.assertEqual(os.environ['SEEDANCE_TRANSPORT'], 'fal')
            self.assertEqual(os.environ['FAL_DRY_RUN'], 'true')
            self.assertEqual(os.environ['RENDERHAUS_SECRETS_NAME'], '')
            self.assertEqual(os.environ['RENDERHAUS_SECRETS_ARN'], '')

    def test_uncertain_submission_is_durable_and_never_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = {'steps': {}}
            path = Path(directory) / 'receipt.json'
            with self.assertRaises(TimeoutError), patch.object(mvp.seedance, 'text_to_video', side_effect=TimeoutError) as submit:
                mvp.submit_once(receipt, path, 'video-1', submit)
            saved = json.loads(path.read_text())
            self.assertEqual(saved['steps']['video-1']['status'], 'submitting')
            with self.assertRaisesRegex(ValueError, 'uncertain'):
                mvp.submit_once(saved, path, 'video-1', submit)
            self.assertEqual(submit.call_count, 1)

    def test_receipt_keeps_handles_without_credentials_or_signed_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            receipt = {'steps': {}}
            path = Path(directory) / 'receipt.json'
            calls = []
            def submit():
                calls.append(1)
                return {'status': 'queued', 'job_id': 'endpoint:request-1',
                        'video_url': 'https://host/video?secret=signed', 'FAL_KEY': 'secret'}
            first = mvp.submit_once(receipt, path, 'video-1', submit)
            second = mvp.submit_once(receipt, path, 'video-1', submit, resume=True)
            self.assertEqual(first, second)
            self.assertEqual(len(calls), 1)
            self.assertNotIn('secret', path.read_text())
            with self.assertRaisesRegex(ValueError, 'never regenerates'):
                mvp.submit_once(receipt, path, 'video-2', submit, resume=True)

    def test_live_resume_polls_saved_handles_and_uses_actual_lambda(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            out = Path(directory)
            voice = out / 'voice.mp3'
            voice.write_bytes(b'voice')
            source = out / 'source.mp4'
            source.write_bytes(b'video')
            receipt = {'version': 1, 'mode': 'live', 'steps': {
                'video-1': {'status': 'queued', 'job_id': 'one'},
                'video-2': {'status': 'queued', 'job_id': 'two'},
                'narration': {'status': 'succeeded', 'job_id': 'voice', 'output_path': str(voice)},
                'assembly': {'status': 'queued', 'render_id': 'render-one', 'bucket_name': 'bucket'},
            }}
            mvp.save(out / 'receipt.json', receipt)
            props = {'document': {'tracks': []}, 'renderConfig': {'durationInFrames': 192, 'fps': 24}}
            with patch.object(mvp, 'configure'), patch.object(mvp, 'probe', return_value={'format': {'duration': '5'}}), \
                    patch.object(mvp.seedance, 'text_to_video') as submit, \
                    patch.object(mvp.fish, 'generate_speech') as speech, \
                    patch.object(mvp.seedance, 'get_video_task', return_value={'status': 'succeeded', 'output_path': str(source)}) as poll, \
                    patch.object(mvp.remotion, 'build_timeline_props', return_value=props), \
                    patch.object(mvp, 'validate_document'), patch.object(mvp.remotion, 'render_timeline') as render, \
                    patch.object(mvp.remotion, 'get_render_progress', return_value={
                        'status': 'succeeded', 'output_path': str(source), 'source_resolution': '1280x720'}), \
                    patch.object(mvp, 'verify_source', return_value='24/1') as check_source, \
                    patch.object(mvp, 'verify', return_value={'width': 1280, 'height': 720}) as check_final:
                result = mvp.run(out, live=True, resume=True)
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['source_resolution'], '1280x720')
            self.assertEqual(poll.call_count, 2)
            self.assertEqual(check_source.call_count, 2)
            check_final.assert_called_once_with(out.resolve() / 'final.mp4', narration_seconds=5, expected_fps='24/1')
            submit.assert_not_called()
            speech.assert_not_called()
            render.assert_not_called()


if __name__ == '__main__':
    unittest.main()
