from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from providers.catalog import get_provider
from providers.registry import generate_schemas
from providers.remotion import api, ad_variants, chat_story


PAYLOAD = {'messages': [{'from': 'them', 'text': 'Are we still friends?'},
                        {'from': 'me', 'text': 'Always.', 'status': 'read'}]}


class ChatToolTests(unittest.TestCase):
    def test_existing_render_tool_accepts_typed_chat_without_supplied_visual(self):
        from providers.contracts import validate_tool_arguments

        schema = next(t['inputSchema'] for t in generate_schemas(get_provider('remotion'))
                      if t['name'] == 'render_timeline')
        with patch.dict(os.environ, {'REMOTION_RENDER_BACKEND': 'local', 'REMOTION_DRY_RUN': 'true'}):
            clean = validate_tool_arguments('remotion', 'render_timeline', {'title': 'Fiction', 'chat_story': PAYLOAD}, schema)
            self.assertEqual(api.render_timeline(**clean)['status'], 'dry_run')
        self.assertIn('chat_story', schema['properties'])

    def test_chat_validation_precedes_dry_run_and_media_io(self):
        with patch.dict(os.environ, {'REMOTION_RENDER_BACKEND': 'local', 'REMOTION_DRY_RUN': 'true'}):
            with patch.object(api, '_start_render') as start:
                with self.assertRaises(ValueError):
                    api.render_timeline('Bad', chat_story={'messages': [{'from': 'other', 'text': 'x'}]})
                start.assert_not_called()

    def test_chat_cannot_mix_unvalidated_visuals_or_override_duration(self):
        with patch.dict(os.environ, {'REMOTION_RENDER_BACKEND': 'local', 'REMOTION_DRY_RUN': 'true'}):
            with self.assertRaisesRegex(ValueError, 'visual'):
                api.render_timeline('Bad', chat_story=PAYLOAD, visuals=[{'kind': 'image', 'url': 'x', 'duration_seconds': 1}])

    def test_lambda_refuses_chat_before_client_or_media(self):
        with patch.dict(os.environ, {'REMOTION_RENDER_BACKEND': 'lambda', 'REMOTION_DRY_RUN': 'true'}):
            with patch.object(api, 'RemotionClient') as client:
                with self.assertRaisesRegex(ValueError, 'Lambda.*chat|lambda.*chat'):
                    api.render_timeline('Fiction', chat_story=PAYLOAD)
                client.assert_not_called()

    def test_worker_document_recomputes_geometry_and_refuses_tampering(self):
        from providers.remotion.capabilities import validate_document

        props = chat_story.build_props('Fiction', PAYLOAD)
        validate_document(props, 'local')
        for changed in ('plan', 'duration'):
            bad = copy.deepcopy(props)
            if changed == 'plan':
                bad['document']['chatStory']['plan']['bubbles'][0]['startFrame'] = 0
            else:
                bad['renderConfig']['durationInFrames'] += 1
            with self.assertRaises(ValueError):
                validate_document(bad, 'local')


class ChatBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'fiction').mkdir()
        self.env = patch.dict(os.environ, {'RENDERHAUS_MEDIA_DIR': str(self.root),
                                           'REMOTION_RENDER_BACKEND': 'local', 'REMOTION_DRY_RUN': 'true'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.temp.cleanup)
        self.rows = [{'variant_key': 'a', 'chat_story': copy.deepcopy(PAYLOAD)},
                     {'variant_key': 'b', 'chat_story': copy.deepcopy(PAYLOAD)}]

    def run_stage(self, stage='plan', rows=None, plan_hash=''):
        return ad_variants.render_ad_variants(stage, 'fiction', {'mode': 'chat_story'},
                                             self.rows if rows is None else rows, '', plan_hash, 1)

    def fake_render_entry(self, row, job, directory, approved_by, review, *, failed=False):
        artifact = directory / row['filename']
        artifact.write_bytes(b'Fake local encoder output for a batch bookkeeping test.')
        images = [directory / (row['variant_key'] + suffix)
                  for suffix in ('-sheet.jpg', '-0.png', '-1.png', '-2.png', '-3.png', '-4.png')]
        for image in images:
            image.write_bytes(b'Fake sampled frame.')
        required = ('container', 'video_codec', 'profile', 'pix_fmt', 'resolution', 'sar', 'fps',
                    'duration', 'cadence', 'frame_count', 'audio_present', 'black', 'freeze',
                    'faststart', 'filename', 'file_size', 'checksum', 'contact_sheet', 'review_frames')
        checks = [{'name': name, 'severity': 'error', 'pass': not (failed and name == 'freeze'),
                   'detail': 'Fixture freeze interval.' if failed and name == 'freeze' else 'Fixture check.'}
                  for name in required]
        checks.append({'name': 'vision_review', 'severity': 'warn', 'pass': False, 'detail': 'Pending.'})
        failures = ['freeze: Fixture freeze interval.'] if failed else []
        technical = {'file': str(artifact), 'output_path': str(artifact),
                     'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(),
                     'bytes': artifact.stat().st_size, 'passed': not failed,
                     'technical_passed': not failed, 'failures': failures, 'checks': checks,
                     'audio_present': False, 'contact_sheet': str(images[0]),
                     'review_frames': [str(image) for image in images[1:]],
                     'review_assets': [{'output_path': str(image), 'bytes': image.stat().st_size,
                                       'sha256': hashlib.sha256(image.read_bytes()).hexdigest()}
                                      for image in images]}
        report = directory / (row['variant_key'] + '-qc.json')
        report.write_text(json.dumps(technical))
        entry = {**{key: row[key] for key in ('variant_key', 'sku', 'locale', 'aspect', 'input_props_hash')},
                 'file': str(artifact), 'output_path': str(artifact), 'sha256': technical['sha256'],
                 'approved_by': approved_by, 'row_status': 'failed' if failed else 'rendered',
                 'delivery_status': 'failed' if failed else 'pending',
                 'qc': {'technical_report': technical},
                 'matrix_qc': {'report_path': str(report),
                               'sha256': hashlib.sha256(report.read_bytes()).hexdigest()}}
        if failed:
            entry['reasons'] = failures
        return entry

    def approved_stage(self, stage, plan_hash):
        with ad_variants.authorize(stage, plan_hash, 'test-human'):
            return self.run_stage(stage, plan_hash=plan_hash)

    def test_plan_is_free_and_binds_every_verbatim_row(self):
        with patch.object(api, 'render_timeline') as render:
            result = self.run_stage()
        render.assert_not_called()
        self.assertEqual(result['status'], 'planned')
        self.assertEqual(result['render_count'], 2)
        self.assertEqual(result['planned'][0]['render_arguments']['chat_story']['messages'][0]['text'],
                         PAYLOAD['messages'][0]['text'])
        changed = copy.deepcopy(self.rows)
        changed[1]['chat_story']['messages'][0]['text'] = 'New approved script'
        self.assertNotEqual(self.run_stage(rows=changed)['plan_hash'], result['plan_hash'])

    def test_invalid_row_is_recorded_while_other_rows_remain_planned(self):
        self.rows.insert(1, {'variant_key': 'invalid', 'chat_story': {'messages': []}})
        result = self.run_stage()
        self.assertEqual(result['render_count'], 2)
        self.assertEqual(result['blocked'][0]['variant_key'], 'invalid')
        self.assertTrue(result['blocked'][0]['reasons'])

    def test_batch_bound_and_untrusted_approval_fields_are_refused(self):
        with self.assertRaises(ValueError):
            self.run_stage(rows=[{'variant_key': str(i), 'chat_story': PAYLOAD} for i in range(51)])
        rows = [{'variant_key': 'x', 'chat_story': PAYLOAD, 'approved': True}]
        self.assertTrue(self.run_stage(rows=rows)['blocked'])

    def test_first_and_batch_require_existing_host_authorization_even_in_dry_run(self):
        plan_hash = self.run_stage()['plan_hash']
        for stage in ('render_first', 'render_batch'):
            self.assertEqual(self.run_stage(stage, plan_hash=plan_hash)['status'], 'blocked')
            with ad_variants.authorize(stage, plan_hash, 'test-human'):
                self.assertEqual(self.run_stage(stage, plan_hash=plan_hash)['status'], 'dry_run')
        changed = copy.deepcopy(self.rows)
        changed[0]['chat_story']['messages'][0]['text'] = 'changed'
        with ad_variants.authorize('render_first', plan_hash, 'test-human'):
            self.assertEqual(self.run_stage('render_first', rows=changed, plan_hash=plan_hash)['status'], 'blocked')

    def test_first_sample_gate_prevents_batch_without_artifact(self):
        plan_hash = self.run_stage()['plan_hash']
        with patch.dict(os.environ, {'REMOTION_DRY_RUN': 'false'}):
            with ad_variants.authorize('render_batch', plan_hash, 'test-human'), patch.object(api, 'render_timeline') as render:
                result = self.run_stage('render_batch', plan_hash=plan_hash)
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('first', result['reason'].lower())
        render.assert_not_called()

    def test_twenty_csv_script_rows_each_compile_to_one_render(self):
        rows = [{'variant_key': str(i), 'chat_story': {'messages': 'from,text\nme,"Hello, friend"'}}
                for i in range(20)]
        result = self.run_stage(rows=rows)
        self.assertEqual(result['render_count'], 20)
        self.assertEqual(len({row['filename'] for row in result['planned']}), 20)

    def test_batch_quote_counts_one_first_sample(self):
        from server.billing_rates import ad_matrix_estimate

        arguments = {'stage': 'render_first', 'brief': {'mode': 'chat_story'}, 'rows': self.rows}
        self.assertEqual(ad_matrix_estimate(arguments)['render_count'], 1)
        arguments['stage'] = 'render_batch'
        self.assertEqual(ad_matrix_estimate(arguments)['render_count'], 1)

    def test_runtime_failure_is_preserved_on_resume_and_only_files_count_as_rendered(self):
        self.rows += [{'variant_key': 'c', 'chat_story': copy.deepcopy(PAYLOAD)},
                      {'variant_key': 'invalid', 'chat_story': {'messages': []}}]
        plan_hash = self.run_stage()['plan_hash']

        def render(row, *args):
            if row['variant_key'] == 'b':
                raise RuntimeError('Exact encoder failure; inspect this job.')
            return self.fake_render_entry(row, *args)

        with patch.dict(os.environ, {'REMOTION_DRY_RUN': 'false'}), \
                patch.object(ad_variants, '_render', side_effect=render) as calls:
            self.approved_stage('render_first', plan_hash)
            batch = self.approved_stage('render_batch', plan_hash)
            self.assertEqual(batch['status'], 'failed')
            self.assertEqual({entry['variant_key'] for entry in batch['rendered']}, {'a', 'c'})
            self.assertEqual(batch['rendered_count'], 2)
            self.assertEqual(batch['failed'], [{'variant_key': 'b', 'reasons': ['Exact encoder failure; inspect this job.']}])
            before_resume = calls.call_count
            repeated = self.approved_stage('render_batch', plan_hash)
            self.assertEqual(calls.call_count, before_resume)
        self.assertEqual(repeated['status'], 'failed')
        self.assertEqual(repeated['failed'], batch['failed'])
        report = json.loads((Path(repeated['manifest_path']).parent / 'report.json').read_text())
        self.assertEqual(report['rendered'], 2)
        self.assertEqual(report['failed'], batch['failed'])
        self.assertEqual(len(json.loads(Path(repeated['manifest_path']).read_text())), 4)

    def test_saved_technical_failure_does_not_stop_remaining_rows_or_disappear(self):
        self.rows.append({'variant_key': 'c', 'chat_story': copy.deepcopy(PAYLOAD)})
        plan_hash = self.run_stage()['plan_hash']

        def render(row, *args):
            return self.fake_render_entry(row, *args, failed=row['variant_key'] == 'b')

        with patch.dict(os.environ, {'REMOTION_DRY_RUN': 'false'}), \
                patch.object(ad_variants, '_render', side_effect=render) as calls:
            self.approved_stage('render_first', plan_hash)
            batch = self.approved_stage('render_batch', plan_hash)
            self.assertEqual(calls.call_count, 3)
            self.assertEqual(batch['status'], 'failed')
            repeated = self.approved_stage('render_batch', plan_hash)
            self.assertEqual(repeated['status'], 'failed', repeated)
            self.assertEqual(repeated['failed'], [{'variant_key': 'b', 'reasons': ['freeze: Fixture freeze interval.']}])
            self.assertEqual(calls.call_count, 3)
        self.assertEqual(repeated['rendered_count'], 3)

    def test_resume_after_saved_failed_qc_renders_the_remaining_script(self):
        self.rows.append({'variant_key': 'c', 'chat_story': copy.deepcopy(PAYLOAD)})
        plan = self.run_stage()
        with patch.dict(os.environ, {'REMOTION_DRY_RUN': 'false'}), \
                patch.object(ad_variants, '_render', side_effect=self.fake_render_entry) as calls:
            first = self.approved_stage('render_first', plan['plan_hash'])
            manifest = Path(first['manifest_path'])
            failed = self.fake_render_entry(plan['planned'][1], self.root / 'fiction',
                                            manifest.parent, 'test-human', False, failed=True)
            entries = json.loads(manifest.read_text())
            manifest.write_text(json.dumps([*entries, failed]))
            result = self.approved_stage('render_batch', plan['plan_hash'])
        self.assertEqual(calls.call_count, 2)
        self.assertEqual(calls.call_args.args[0]['variant_key'], 'c')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['failed'], [{'variant_key': 'b', 'reasons': ['freeze: Fixture freeze interval.']}])
        self.assertEqual(result['rendered_count'], 3)

    def test_bad_render_response_is_one_row_failure_and_other_scripts_continue(self):
        self.rows.append({'variant_key': 'c', 'chat_story': copy.deepcopy(PAYLOAD)})
        for error in (KeyError('output_path'), TypeError('Malformed renderer response.')):
            with self.subTest(error=type(error).__name__):
                self.rows[0]['chat_story']['messages'][0]['text'] = type(error).__name__
                plan_hash = self.run_stage()['plan_hash']

                def render(row, *args):
                    if row['variant_key'] == 'b':
                        raise error
                    return self.fake_render_entry(row, *args)

                with patch.dict(os.environ, {'REMOTION_DRY_RUN': 'false'}), \
                        patch.object(ad_variants, '_render', side_effect=render):
                    self.approved_stage('render_first', plan_hash)
                    result = self.approved_stage('render_batch', plan_hash)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['rendered_count'], 2)
                self.assertEqual(result['failed'], [{'variant_key': 'b', 'reasons': [str(error)]}])

    def test_failed_first_sample_still_blocks_batch(self):
        plan_hash = self.run_stage()['plan_hash']

        def render(row, *args):
            return self.fake_render_entry(row, *args, failed=True)

        with patch.dict(os.environ, {'REMOTION_DRY_RUN': 'false'}), \
                patch.object(ad_variants, '_render', side_effect=render) as calls:
            first = self.approved_stage('render_first', plan_hash)
            self.assertEqual(first['status'], 'failed')
            batch = self.approved_stage('render_batch', plan_hash)
        self.assertEqual(batch['status'], 'blocked')
        self.assertIn('first', batch['reason'].lower())
        self.assertEqual(calls.call_count, 1)

    def test_failed_technical_qc_and_artifact_checksums_are_checked_on_resume(self):
        for changed in ('artifact', 'report'):
            with self.subTest(changed=changed):
                self.rows[0]['chat_story']['messages'][0]['text'] = changed
                plan_hash = self.run_stage()['plan_hash']

                def render(row, *args):
                    return self.fake_render_entry(row, *args, failed=row['variant_key'] == 'b')

                with patch.dict(os.environ, {'REMOTION_DRY_RUN': 'false'}), \
                        patch.object(ad_variants, '_render', side_effect=render):
                    self.approved_stage('render_first', plan_hash)
                    batch = self.approved_stage('render_batch', plan_hash)
                    failed = next(entry for entry in batch['rendered'] if entry['variant_key'] == 'b')
                    selected = failed['file'] if changed == 'artifact' else failed['matrix_qc']['report_path']
                    Path(selected).write_bytes(b'Changed since saved QC.')
                    with patch.object(ad_variants, '_render') as unexpected:
                        result = self.approved_stage('render_batch', plan_hash)
                    unexpected.assert_not_called()
                self.assertEqual(result['status'], 'blocked')

    def test_blocked_duplicate_key_cannot_suppress_the_valid_first_script(self):
        self.rows.append(copy.deepcopy(self.rows[0]))
        plan_hash = self.run_stage()['plan_hash']
        with patch.dict(os.environ, {'REMOTION_DRY_RUN': 'false'}), \
                patch.object(ad_variants, '_render', side_effect=self.fake_render_entry) as render:
            first = self.approved_stage('render_first', plan_hash)
        self.assertEqual(render.call_count, 1)
        self.assertEqual(first['rendered_count'], 1)
        self.assertEqual(first['rendered'][0]['variant_key'], 'a')

    def test_chat_output_carries_its_qc_spec_and_exact_technical_failure_reasons(self):
        planned = self.run_stage()['planned'][0]
        config = planned['timeline']['renderConfig']
        directory = self.root / 'fiction' / 'render-check'
        directory.mkdir()
        source = directory / 'source.mp4'
        source.write_bytes(b'Fake local encoder output.')
        outputs = [{'path': str(directory / f'frame-{index}.png')} for index in range(3)]
        measured = {'passed': False, 'failures': ['audio_present: No audio stream.']}
        with patch.object(api, 'render_timeline', return_value={'status': 'succeeded', 'output_path': str(source)}), \
                patch('providers.ffmpeg.api.execute', return_value={'ok': True, 'outputs': outputs, 'metrics': {'streams': []}}), \
                patch('providers.remotion.qc.inspect_file', return_value=measured) as inspect:
            entry = ad_variants._render(planned, self.root / 'fiction', directory, 'test-human', True)
        self.assertEqual(entry['row_status'], 'failed')
        self.assertEqual(entry['reasons'], measured['failures'])
        self.assertTrue(entry['qc_spec']['require_audio'], 'Requested pops require an audio stream even if it is missing.')
        for name in ('width', 'height', 'fps'):
            self.assertEqual(entry['qc_spec']['expected_' + name], config[name])
        self.assertEqual(entry['qc_spec']['expected_duration_s'], config['durationInFrames'] / config['fps'])
        self.assertEqual(entry['qc_spec']['allowed_freeze'], inspect.call_args.args[3]['allowed_freeze'])
        self.assertEqual(entry['qc_spec']['allowed_silence'], inspect.call_args.args[3]['allowed_silence'])
        self.assertNotIn('expected_filename', entry['qc_spec'], 'Delivery creates a versioned filename.')


if __name__ == '__main__':
    unittest.main()
