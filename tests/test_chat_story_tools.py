from __future__ import annotations

import copy
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


if __name__ == '__main__':
    unittest.main()
