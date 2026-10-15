from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.deep_agent.finishing_preview import FinishingPreviewGate, measure_video
from agent.studio_agent_next import StudioAgentRequest, StudioToolEvent, _context_from_request, _validate_video_delivery

UPSCALE = 'Topaz___upscale_video'
INTERPOLATE = 'Topaz___interpolate_video'


class FinishingPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = tempfile.TemporaryDirectory()
        cls.source = Path(cls.fixtures.name) / 'source.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'color=c=red:s=960x540:r=30:d=6', '-c:v', 'libx264',
                        '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(cls.source)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.fixtures.cleanup()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.paths = {'original': self.root / 'original.mp4'}
        shutil.copyfile(self.source, self.paths['original'])
        self.studio = _context_from_request(StudioAgentRequest(
            prompt='upscale this 6 second clip', workspace_id='workspace', project_id='project',
            conversation_id='conversation', job_id='preview-test'), source_resolver=self.resolve,
            asset_registrar=self.register)
        self.studio.add_assets([{'version_id': 'original', 'kind': 'video'}])
        self.env = patch.dict('os.environ', {'RENDERHAUS_MEDIA_DIR': str(self.root / 'media'), 'RENDERHAUS_OUTCOME_DIR': str(self.root / 'outcomes')})
        self.env.start()
        self.gate = FinishingPreviewGate(self.studio, scope='workspace/project/conversation')
        self.args = {'video_url': 'renderhaus-asset://original', 'source_duration_seconds': 6.0,
                     'source_fps': 30.0, 'source_width': 960, 'source_height': 540}

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()

    def resolve(self, version):
        return str(self.paths[version])

    def register(self, **kwargs):
        version = f'version-{len(self.paths)}'
        target = self.root / f'{version}.mp4'
        shutil.copyfile(kwargs['result']['output_path'], target)
        self.paths[version] = target
        return [{'version_id': version, 'kind': 'video', 'filename': f'{version}.mp4'}]

    def prepare(self, **kwargs):
        result = self.gate.prepare(UPSCALE, self.args, **kwargs)
        self.assertTrue(result['ok'], result)
        return result

    def ready(self, **kwargs):
        prepared = self.prepare(**kwargs)
        self.gate.claim_submission(UPSCALE, prepared['preview_arguments'], 'submit')
        job_id = 'topaz:upscale:preview-job' if len(self.gate.previews) == 1 else 'topaz:upscale:' + prepared['preview_id']
        self.gate.record_submission(UPSCALE, prepared['preview_arguments'], 'submit',
                                    {'status': 'queued', 'job_id': job_id})
        clip = self.paths[prepared['source_clip_version_id']]
        processed = self.root / (prepared['preview_id'] + '.mp4')
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(clip), '-vf', 'scale=1920:1080',
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(processed)], check=True)
        result = {'status': 'succeeded', 'downloaded': True, 'job_id': job_id,
                  'output_path': str(processed)}
        assets = self.register(result=result)
        self.studio.add_assets(assets)
        event = StudioToolEvent(id='poll', name='Topaz___get_video_task', label='Finishing status',
                               status='succeeded', summary='Saved', provider_job_id=result['job_id'],
                               arguments={'job_id': result['job_id'], 'download': True},
                               result=result, assets=assets)
        self.studio.tool_events.append(event)
        self.gate.observe(event)
        return prepared, event

    def test_prepared_clip_has_actual_three_second_bound_and_is_owned(self):
        result = self.prepare(duration_seconds=30)
        self.assertLessEqual(result['preview_arguments']['source_duration_seconds'], 3)
        self.assertEqual(result['preview_arguments']['video_url'],
                         'renderhaus-asset://' + result['source_clip_version_id'])
        self.assertEqual(len(self.paths), 2)
        self.assertEqual(self.prepare(duration_seconds=30)['preview_id'], result['preview_id'])
        self.assertEqual(len(self.paths), 2)
        self.assertIsNone(self.gate.blocker(UPSCALE, result['preview_arguments']))
        self.assertIsNotNone(self.gate.blocker(UPSCALE, self.args))

    def test_prepare_measures_owned_source_when_measurements_are_absent(self):
        result = self.gate.prepare(UPSCALE, {'video_url': 'renderhaus-asset://original', 'softness': 2.0})
        self.assertTrue(result['ok'], result)
        self.assertEqual((result['full_arguments']['source_width'], result['full_arguments']['source_height']),
                         (960, 540))
        self.assertEqual(result['full_arguments']['source_duration_seconds'], 6.0)
        self.assertEqual(result['full_arguments']['source_fps'], 30.0)
        self.assertEqual(result['preview_arguments']['softness'], 2.0)
        self.assertLessEqual(result['preview_arguments']['source_duration_seconds'], 3.0)

    def test_external_source_and_fabricated_measurements_cannot_prepare(self):
        for args in ({**self.args, 'video_url': 'https://example.test/source.mp4'},
                     {**self.args, 'source_duration_seconds': 3.0},
                     {**self.args, 'source_width': 1920}):
            self.assertFalse(self.gate.prepare(UPSCALE, args)['ok'])
        self.assertEqual(len(self.paths), 1)

    def test_review_payload_uses_measured_files_and_approval_only_unlocks_exact_request(self):
        prepared, event = self.ready()
        payload = self.gate.comparison(prepared['preview_id'])
        self.assertEqual(payload['before_version_id'], prepared['source_clip_version_id'])
        self.assertEqual(payload['after_version_id'], event.assets[0]['version_id'])
        self.assertEqual((payload['source_width'], payload['output_width']), (960, 1920))
        self.assertIsNotNone(self.gate.blocker(UPSCALE, self.args))
        self.assertEqual(self.gate.approve(prepared['preview_id'])['status'], 'approved')
        self.assertIsNone(self.gate.blocker(UPSCALE, self.args))
        self.assertIsNotNone(self.gate.blocker(UPSCALE, {**self.args, 'softness': 4.0}))
        self.assertTrue(event.result['finishing_preview_only'])

    def test_rejection_and_plain_media_outcome_do_not_unlock_full_spending(self):
        prepared, _ = self.ready()
        self.gate.reject(prepared['preview_id'])
        self.assertIsNotNone(self.gate.blocker(UPSCALE, self.args))
        self.assertEqual(self.gate.approve(prepared['preview_id'])['status'], 'not_run')

    def test_source_clip_or_result_substitution_invalidates_review(self):
        prepared, event = self.ready()
        for version in ('original', prepared['source_clip_version_id'], event.assets[0]['version_id']):
            path = self.paths[version]
            original = path.read_bytes()
            path.write_bytes(original + b'changed')
            with self.assertRaises(ValueError):
                self.gate.comparison(prepared['preview_id'])
            self.assertEqual(self.gate.approve(prepared['preview_id'])['status'], 'not_run')
            path.write_bytes(original)

    def test_dry_run_failed_missing_and_wrong_size_outputs_never_qualify(self):
        prepared = self.prepare()
        self.gate.claim_submission(UPSCALE, prepared['preview_arguments'], 'submit')
        self.gate.record_submission(UPSCALE, prepared['preview_arguments'], 'submit',
                                    {'status': 'queued', 'job_id': 'topaz:upscale:preview-job'})
        for status, downloaded, assets in [('dry_run', True, []), ('queued', False, []),
                                          ('failed', False, []), ('succeeded', True, []),
                                          ('succeeded', True, [{'version_id': 'original', 'kind': 'video'}])]:
            event = StudioToolEvent(id='poll', name='Topaz___get_video_task', label='Status',
                status=status, summary='Status', provider_job_id='topaz:upscale:preview-job',
                result={'status': status, 'downloaded': downloaded}, assets=assets)
            self.gate.observe(event)
            with self.assertRaises(ValueError):
                self.gate.comparison(prepared['preview_id'])

    def test_persisted_scope_and_submission_replay_do_not_repeat_paid_call(self):
        prepared = self.prepare()
        args = prepared['preview_arguments']
        self.gate.claim_submission(UPSCALE, args, 'submit')
        self.assertEqual(self.gate.replay(UPSCALE, args)['status'], 'submission_unknown')
        self.gate.record_submission(UPSCALE, args, 'submit',
                                    {'status': 'queued', 'job_id': 'topaz:upscale:preview-job'})
        restored = FinishingPreviewGate(self.studio, json.loads(json.dumps(self.gate.snapshot())),
                                       scope='workspace/project/conversation')
        self.assertEqual(restored.replay(UPSCALE, args)['job_id'], 'topaz:upscale:preview-job')
        other = FinishingPreviewGate(self.studio, self.gate.snapshot(), scope='other/project/conversation')
        self.assertIsNotNone(other.blocker(UPSCALE, args))

    def test_fractional_fps_preview_uses_actual_frames_without_crossing_three_seconds(self):
        source = self.root / 'fractional.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'color=c=red:s=960x540:r=30000/1001:d=6', '-c:v', 'libx264',
                        '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(source)], check=True)
        self.paths['original'] = source
        measured = measure_video(source)
        result = self.gate.prepare(INTERPOLATE, {**self.args,
            'source_duration_seconds': measured.duration_seconds, 'source_fps': measured.fps})
        self.assertTrue(result['ok'], result)
        clip = measure_video(self.paths[result['source_clip_version_id']])
        self.assertLessEqual(clip.duration_seconds, 3)
        self.assertAlmostEqual(clip.fps, 30000 / 1001, places=5)
        self.assertAlmostEqual(clip.duration_seconds, 89 * 1001 / 30000, places=5)

    def test_approved_short_source_is_final_without_duplicate_full_job(self):
        source = self.root / 'short.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(self.paths['original']), '-t', '2',
                        '-c:v', 'libx264', '-preset', 'ultrafast', str(source)], check=True)
        self.paths['original'] = source
        self.args['source_duration_seconds'] = 2.0
        prepared, event = self.ready()
        request = StudioAgentRequest(prompt='upscale this video')
        self.assertTrue(prepared['covers_full_source'])
        self.assertFalse(_validate_video_delivery(request, self.studio))
        approved = self.gate.approve(prepared['preview_id'])
        self.assertEqual(approved['status'], 'succeeded')
        self.assertTrue(_validate_video_delivery(request, self.studio))
        self.assertEqual(self.gate.replay(UPSCALE, self.args)['output_version_id'], event.assets[0]['version_id'])
        output = self.paths[event.assets[0]['version_id']]
        output.write_bytes(output.read_bytes() + b'changed')
        self.assertFalse(_validate_video_delivery(request, self.studio))

    def test_one_frame_source_is_preserved_as_a_complete_preview(self):
        source = self.root / 'one-frame.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'color=c=red:s=960x540:r=30:d=1', '-frames:v', '1', '-c:v', 'libx264',
                        '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(source)], check=True)
        self.paths['original'] = source
        self.args['source_duration_seconds'] = measure_video(source).duration_seconds
        prepared, _ = self.ready()
        self.assertTrue(prepared['covers_full_source'])
        self.assertAlmostEqual(prepared['preview_arguments']['source_duration_seconds'], 1 / 30, places=5)
        self.assertEqual(self.gate.approve(prepared['preview_id'])['status'], 'succeeded')

    def test_native_visual_pick_records_owned_preview_provenance_once(self):
        prepared, event = self.ready()
        self.gate.approve(prepared['preview_id'])
        self.gate.approve(prepared['preview_id'])
        self.gate.reject(prepared['preview_id'])
        rows = [json.loads(line) for line in self.gate.outcomes.path.read_text().splitlines()]
        self.assertEqual([row['outcome'] for row in rows], ['accepted', 'rejected'])
        self.assertTrue(all(row['stage'] == 'review' and row['ab_arm'] == 'finishing_preview'
                            and row['version_id'] == event.assets[0]['version_id']
                            and row['provider_job_id'] == 'topaz:upscale:preview-job'
                            and not row['training_eligible'] for row in rows))

    def test_long_source_preview_is_not_a_finished_deliverable(self):
        prepared, _ = self.ready()
        self.gate.approve(prepared['preview_id'])
        self.assertFalse(_validate_video_delivery(StudioAgentRequest(prompt='upscale this video'), self.studio))

    def test_full_job_submission_is_replayed_and_typed_aliases_share_approval(self):
        prepared, _ = self.ready()
        self.gate.approve(prepared['preview_id'])
        equivalent = {**self.args, 'model': 'slp-2.6', 'upscale_factor': 2.0, 'H264_output': True}
        self.assertIsNone(self.gate.blocker(UPSCALE, equivalent))
        self.gate.claim_submission(UPSCALE, equivalent, 'full')
        self.assertEqual(self.gate.replay(UPSCALE, self.args)['status'], 'submission_unknown')
        self.gate.record_submission(UPSCALE, self.args, 'full',
                                    {'status': 'queued', 'job_id': 'topaz:upscale:full-job'})
        self.assertEqual(self.gate.replay(UPSCALE, equivalent)['job_id'], 'topaz:upscale:full-job')
        with self.assertRaises(ValueError):
            self.gate.claim_submission(UPSCALE, self.args, 'duplicate')

    def test_a_later_poll_cannot_replace_the_reviewed_artifact(self):
        prepared, event = self.ready()
        self.gate.approve(prepared['preview_id'])
        original_id = event.assets[0]['version_id']
        original_sha = self.gate.previews[prepared['preview_id']].output_sha256
        candidate = self.root / 'different.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'color=c=blue:s=1920x1080:r=30:d=3', '-c:v', 'libx264',
                        '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(candidate)], check=True)
        event.assets = self.register(result={'output_path': str(candidate)})
        self.gate.observe(event)
        record = self.gate.previews[prepared['preview_id']]
        self.assertEqual((record.output_version_id, record.output_sha256), (original_id, original_sha))
        self.assertIsNotNone(self.gate.blocker(UPSCALE, self.args))

    def test_new_sample_rejection_cannot_inherit_an_older_approval(self):
        first, _ = self.ready()
        self.gate.approve(first['preview_id'])
        second, _ = self.ready(start_seconds=3)
        self.assertIsNotNone(self.gate.blocker(UPSCALE, self.args))
        with self.assertRaisesRegex(ValueError, 'newer source sample'):
            self.gate.comparison(first['preview_id'])
        self.gate.reject(second['preview_id'])
        self.assertIsNotNone(self.gate.blocker(UPSCALE, self.args))
        restored = FinishingPreviewGate(self.studio, json.loads(json.dumps(self.gate.snapshot(), sort_keys=True)),
                                       scope='workspace/project/conversation')
        self.assertIsNotNone(restored.blocker(UPSCALE, self.args))

    def test_changing_sample_cannot_duplicate_an_existing_full_submission(self):
        first, _ = self.ready()
        self.gate.approve(first['preview_id'])
        self.gate.claim_submission(UPSCALE, self.args, 'full-first')
        second, _ = self.ready(start_seconds=3)
        self.gate.record_submission(UPSCALE, self.args, 'full-first',
                                    {'status': 'queued', 'job_id': 'topaz:upscale:existing-full'})
        self.gate.approve(second['preview_id'])
        self.assertEqual(self.gate.replay(UPSCALE, self.args)['job_id'], 'topaz:upscale:existing-full')

    def test_dry_run_submission_cannot_be_promoted_by_a_poll(self):
        prepared, event = self.ready()
        record = self.gate.previews[prepared['preview_id']]
        record.status = 'failed'
        record.submit_result = {'status': 'dry_run', 'job_id': record.job_id}
        self.gate.observe(event)
        self.assertFalse(self.gate.can_review(prepared['preview_id']))

    def test_interpolation_slow_motion_stays_blocked(self):
        result = self.gate.prepare(INTERPOLATE, {**self.args, 'slowdown_factor': 2})
        self.assertFalse(result['ok'])
        self.assertIn('quote', result['error'].lower())


if __name__ == '__main__':
    unittest.main()
