from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


class FootageToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.job = self.root / 'media' / 'job'
        self.job.mkdir(parents=True)
        (self.job / 'take.mp4').write_bytes(b'synthetic footage')
        self.env = patch.dict(os.environ, {
            'RENDERHAUS_MEDIA_DIR': str(self.root / 'media'),
            'RENDERHAUS_VIDEO_INDEX_ROOT': str(self.root / 'projects'),
            'FOOTAGE_MEMORY_DRY_RUN': 'true', 'FOOTAGE_MEMORY_BACKEND': 'mock',
            'FOOTAGE_MEMORY_CALL_CENTS': '',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.probe = patch('providers.footage_memory.service.probe_media', return_value={'duration_s': 65.0, 'fps': 24.0})
        self.probe.start()
        self.addCleanup(self.probe.stop)
        self.network = patch('socket.socket.connect', side_effect=AssertionError('network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.args = {'project_id': 'p1', 'workspace_id': 'w1', 'job_id': 'job', 'path': 'take.mp4'}

    def call(self, tool, **arguments):
        from providers.registry import dispatch

        return dispatch('footage_memory', tool, arguments)

    def build(self):
        from providers.footage_memory.service import authorize

        plan = self.call('footage_memory_build', **self.args)
        with authorize(plan['plan_hash']):
            return self.call('footage_memory_build', **self.args, stage='build', plan_hash=plan['plan_hash'])

    def test_estimate_first_and_trusted_approval_before_backend(self):
        with patch('providers.footage_memory.service.get_backend') as backend:
            estimate = self.call('footage_memory_build', **self.args)
            self.assertEqual(estimate['status'], 'estimate')
            self.assertEqual(estimate['backend_calls'], 3)
            self.assertIsNone(estimate['estimate_cents'])
            self.assertEqual(estimate['price_verification'], 'UNVERIFIED')
            backend.assert_not_called()
            blocked = self.call('footage_memory_build', **self.args, stage='build', plan_hash=estimate['plan_hash'])
            self.assertEqual(blocked['status'], 'awaiting_approval')
            backend.assert_not_called()
        with patch.dict(os.environ, {'FOOTAGE_MEMORY_CALL_CENTS': '2.5'}):
            priced = self.call('footage_memory_build', **self.args)
            self.assertEqual(priced['estimate_cents'], 8)
            self.assertEqual(priced['backend_calls'], 3)

    def test_one_call_per_window_and_hash_reuse(self):
        from providers.footage_memory.backends import get_backend

        backend = Mock(wraps=get_backend('mock'))
        backend.backend_ref = 'mock:synthetic-v1'
        with patch.object(backend, 'describe_window', wraps=backend.describe_window) as describe:
            with patch('providers.footage_memory.service.get_backend', return_value=backend):
                built = self.build()
                self.assertEqual(built['status'], 'dry_run')
                self.assertTrue(built['simulated'])
                self.assertEqual(describe.call_count, 3)
                reused = self.call('footage_memory_build', **self.args)
                self.assertEqual(reused['status'], 'reused')
                self.assertEqual(describe.call_count, 3)
        status = self.call('footage_memory_status', **self.args)
        self.assertTrue(status['assets'][0]['memory_exists'])
        self.assertEqual(status['recommendation'], 'query')
        (self.job / 'take.mp4').write_bytes(b'changed')
        status = self.call('footage_memory_status', **self.args)
        self.assertTrue(status['assets'][0]['stale'])

    def test_query_requires_verification_and_mock_watch_never_authorizes_real_cut(self):
        self.build()
        hits = self.call('footage_memory_query', project_id='p1', workspace_id='w1', query='childhood', limit=3)['hits']
        self.assertTrue(hits)
        self.assertTrue(all(h['verify_required'] for h in hits))
        extract = dict(project_id='p1', workspace_id='w1', job_id='job', hit_ids=[hits[0]['hit_id']])
        with patch('providers.ffmpeg.api.execute') as trim:
            refused = self.call('footage_clip_extract', **extract)
            self.assertEqual(refused['status'], 'blocked')
            trim.assert_not_called()
            watched = self.call('footage_watch_answer', **self.args, question='childhood', verify_hit_id=hits[0]['hit_id'],
                                t0_s=hits[0]['t0_s'], t1_s=hits[0]['t1_s'])
            self.assertTrue(watched['simulated'])
            self.assertIn(watched['verdict'], {'verified', 'refuted', 'ambiguous'})
            self.assertEqual(self.call('footage_clip_extract', **extract)['status'], 'blocked')
            trim.return_value = {'ok': True, 'outputs': [{'path': str(self.job / 'select.mp4')}], 'metrics': {}}
            accepted = self.call('footage_clip_extract', **extract, allow_unverified=True, handles_s=1.0)
            self.assertTrue(accepted['ok'])
            self.assertEqual(trim.call_args.args[0], 'trim')
            self.assertTrue(accepted['warnings'])

    def test_path_scope_types_and_window_bounds_rejected_before_backend(self):
        with patch('providers.footage_memory.service.get_backend') as backend:
            for change in ({'path': '../take.mp4'}, {'path': 'https://example.com/video'}, {'project_id': '..'},
                           {'path': 'take.mp4', 'folder': 'clips'}, {'window_s': True}):
                with self.subTest(change=change):
                    with self.assertRaises(ValueError):
                        self.call('footage_memory_build', **(self.args | change))
            backend.assert_not_called()
            result = self.call('footage_watch_answer', **self.args, question='what', t0_s=64.0, t1_s=80.0)
            self.assertFalse(result['ok'])
            backend.assert_not_called()
        (self.job / 'escape.mp4').symlink_to(self.root / 'outside.mp4')
        (self.root / 'outside.mp4').write_bytes(b'secret')
        self.assertFalse(self.call('footage_memory_status', **(self.args | {'path': 'escape.mp4'}))['ok'])

    def test_changed_plan_and_different_projects_cannot_reuse_approval_or_hits(self):
        from providers.footage_memory.service import authorize

        plan = self.call('footage_memory_build', **self.args)
        (self.job / 'take.mp4').write_bytes(b'changed')
        with authorize(plan['plan_hash']):
            self.assertEqual(self.call('footage_memory_build', **self.args, stage='build', plan_hash=plan['plan_hash'])['status'], 'blocked')
        self.build()
        other = self.call('footage_memory_query', project_id='p2', workspace_id='w1', query='childhood')
        self.assertEqual(other['hits'], [])

    def test_neutral_outputs_and_live_disabled_with_both_settings(self):
        outputs = [self.call('footage_memory_status', **self.args), self.call('footage_memory_build', **self.args),
                   self.call('footage_watch_answer', **self.args, question='whiteboard')]
        for output in outputs:
            body = json.dumps(output).lower()
            for word in ('gemini', 'qwen', 'alibaba', 'google', 'fee'):
                self.assertNotIn(word, body)
        with patch.dict(os.environ, {'FOOTAGE_MEMORY_DRY_RUN': 'false', 'FOOTAGE_MEMORY_BACKEND': 'gemini'}):
            result = self.call('footage_watch_answer', **self.args, question='whiteboard')
            self.assertEqual(result['status'], 'blocked')

    def test_folder_reuses_duplicate_content_and_status_refreshes_job_pointer(self):
        from providers.footage_memory.service import authorize

        folder = self.job / 'clips'
        folder.mkdir()
        for filename in ('a.mp4', 'b.mp4'):
            (folder / filename).write_bytes(b'same footage')
        args = {k: v for k, v in self.args.items() if k != 'path'} | {'folder': 'clips'}
        estimate = self.call('footage_memory_build', **args)
        self.assertEqual(estimate['backend_calls'], 3)
        with authorize(estimate['plan_hash']):
            built = self.call('footage_memory_build', **args, stage='build', plan_hash=estimate['plan_hash'])
        self.assertEqual(len(built['assets']), 1)
        other_job = self.root / 'media' / 'job2'
        other_job.mkdir()
        (other_job / 'take.mp4').write_bytes(b'same footage')
        refreshed = self.call('footage_memory_status', **(self.args | {'job_id': 'job2'}))
        self.assertEqual(refreshed['recommendation'], 'query')
        with patch('providers.ffmpeg.api.execute', return_value={'ok': True, 'outputs': [], 'metrics': {}}):
            hit = self.call('footage_memory_query', project_id='p1', workspace_id='w1', query='childhood')['hits'][0]
            result = self.call('footage_clip_extract', project_id='p1', workspace_id='w1', job_id='job2',
                               hit_ids=[hit['hit_id']], allow_unverified=True)
            self.assertTrue(result['ok'], result)

    def test_verified_select_uses_refined_timestamp_with_handles(self):
        from providers.footage_memory.contracts import ProjectRequest
        from providers.footage_memory.service import open_index

        self.build()
        hit = self.call('footage_memory_query', project_id='p1', workspace_id='w1', query='childhood')['hits'][0]
        with open_index(ProjectRequest(project_id='p1', workspace_id='w1')) as index:
            index.verify_event(hit['hit_id'], 'verified', 7000, 8000)
        with patch('providers.ffmpeg.api.execute', return_value={'ok': True, 'outputs': [], 'metrics': {}}) as trim:
            result = self.call('footage_clip_extract', project_id='p1', workspace_id='w1', job_id='job',
                               hit_ids=[hit['hit_id']], handles_s=1.0)
            self.assertTrue(result['ok'], result)
            self.assertEqual(trim.call_args.args[3], {'t0_s': 6.0, 't1_s': 9.0})

    def test_long_footage_can_be_inspected_above_short_worker_size_limit(self):
        with (self.job / 'take.mp4').open('wb') as handle:
            handle.truncate(129 * 1024 * 1024)
        result = self.call('footage_memory_status', **self.args, question_count=2)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['recommendation'], 'build')

    def test_interrupted_build_can_retry_with_changed_window_size(self):
        from providers.footage_memory.backends import get_backend
        from providers.footage_memory.service import authorize

        backend = Mock(wraps=get_backend('mock'))
        backend.backend_ref = 'mock:synthetic-v1'
        backend.describe_window.side_effect = ValueError('Analysis interrupted.')
        with patch('providers.footage_memory.service.get_backend', return_value=backend):
            plan = self.call('footage_memory_build', **self.args)
            with authorize(plan['plan_hash']):
                failed = self.call('footage_memory_build', **self.args, stage='build', plan_hash=plan['plan_hash'])
            self.assertEqual(failed['status'], 'blocked')
        args = self.args | {'window_s': 20.0}
        plan = self.call('footage_memory_build', **args)
        with authorize(plan['plan_hash']):
            result = self.call('footage_memory_build', **args, stage='build', plan_hash=plan['plan_hash'])
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['backend_calls'], 4)
        self.assertTrue(self.call('footage_memory_query', project_id='p1', workspace_id='w1', query='childhood')['hits'])


class FootageHostTests(unittest.TestCase):
    def test_confidential_project_blocks_future_third_party_access_without_routing_change(self):
        from agent.gateway_executor import GatewayExecutor
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request
        from providers.footage_memory.contracts import ProjectRequest
        from providers.footage_memory.service import project_directory

        fixture = FootageToolsTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        directory = project_directory(ProjectRequest(project_id='p1', workspace_id='w1'))
        (directory / 'settings.json').write_text(json.dumps({'allow_third_party_vlm': True}))
        name = 'FootageMemory___footage_watch_answer'
        args = fixture.args | {'question': 'whiteboard'}
        with patch.dict(os.environ, {'FOOTAGE_MEMORY_DRY_RUN': 'false', 'FOOTAGE_MEMORY_BACKEND': 'gemini'}):
            for confidential, expected in ((False, 'not implemented'), (True, 'not enabled for this project')):
                request = StudioAgentRequest(prompt='Find a moment', project_id='p1', workspace_id='w1',
                                             job_id='job', confidential=confidential)
                executor = GatewayExecutor(_context_from_request(request), [])
                self.assertIsNone(executor.media_selection(name, args))
                self.assertIn(expected, executor.selection_blocker(name, args, None))

    def test_native_approval_policy_keeps_long_build_paused_autonomously(self):
        from agent.gateway_executor import APPROVAL_EXEMPT_TOOLS, tool_needs_approval

        self.assertEqual(APPROVAL_EXEMPT_TOOLS, frozenset({'Remotion___export_nle_timeline'}))
        for autonomous in (False, True):
            self.assertFalse(tool_needs_approval('FootageMemory___footage_memory_status', autonomous))
            self.assertFalse(tool_needs_approval('FootageMemory___footage_memory_build', autonomous, {'stage': 'estimate'}))
            self.assertTrue(tool_needs_approval('FootageMemory___footage_memory_build', autonomous, {'stage': 'build'}))
        self.assertTrue(tool_needs_approval('FootageMemory___footage_watch_answer', False))


class FootageNativeHostTests(unittest.IsolatedAsyncioTestCase):
    async def test_approval_resume_and_rejection_never_build_before_human_decision(self):
        from agent.deep_agent.runner import run_with_servers
        from agent.studio_agent_next import StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, _context_from_request
        from test_deep_agent import ScriptedModel, call, final
        from providers.registry import dispatch

        fixture = FootageToolsTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        estimate = dispatch('footage_memory', 'footage_memory_build', fixture.args)
        args = fixture.args | {'stage': 'build', 'plan_hash': estimate['plan_hash']}
        name = 'FootageMemory___footage_memory_build'
        for decision in ('reject', 'approve'):
            request = StudioAgentRequest(prompt='Find a childhood moment in these interview rushes',
                project_id='p1', workspace_id='w1', job_id='job', autonomous=True,
                conversation_id='footage-' + decision)
            context = _context_from_request(request)
            with patch('providers.footage_memory.service.build', wraps=__import__('providers.footage_memory.service', fromlist=['build']).build) as build:
                with self.assertRaises(StudioAgentApprovalRequired) as caught:
                    await run_with_servers(request, context, [], model=ScriptedModel([
                        call('call_editor_tool', {'tool_name': name, 'arguments': args}, 'build')]))
                build.assert_not_called()
                approval = caught.exception.approvals[0]
                self.assertIn('analysis calls', approval.description)
                self.assertIn('UNVERIFIED', approval.description)
                self.assertIsNone(approval.estimated_cost['total_cents'])
                for word in ('gemini', 'qwen', 'fee'):
                    self.assertNotIn(word, json.dumps(approval.model_dump()).lower())
                resumed = request.model_copy(update={'session_items': context.session_items,
                    'resume_state': caught.exception.state, 'approval_decisions': [StudioApprovalDecision(
                        call_id=approval.call_id, decision=decision, message='reviewed')]})
                await run_with_servers(resumed, context, [], model=ScriptedModel([final()]))
                self.assertEqual(build.call_count, int(decision == 'approve'))

    async def test_project_and_job_scope_gate_and_estimates_do_not_consume_spend_cap(self):
        from agent.gateway_executor import GatewayExecutor
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request

        fixture = FootageToolsTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        request = StudioAgentRequest(prompt='Find a moment', project_id='p1', workspace_id='w1', job_id='job', autonomous=True)
        with patch.dict(os.environ, {'RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS': '1'}):
            executor = GatewayExecutor(_context_from_request(request), [])
            for changes in ({'project_id': 'p2'}, {'workspace_id': 'w2'}, {'job_id': 'other'}):
                response = await executor.execute({'tool_name': 'FootageMemory___footage_memory_build',
                    'arguments': fixture.args | changes, 'call_id': next(iter(changes))})
                self.assertEqual(response['status'], 'not_run')
            plan = await executor.execute({'tool_name': 'FootageMemory___footage_memory_build',
                'arguments': fixture.args, 'call_id': 'estimate'})
            self.assertEqual(plan['status'], 'estimate')
            self.assertEqual(executor.reservations, {})
