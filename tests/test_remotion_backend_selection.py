from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from agent.codex_harness import ToolApprovalPending
from agent.gateway_executor import GatewayExecutor
from agent.studio_agent_next import StudioAgentRequest, _context_from_request
from test_deep_agent import Gateway
from mcp import Tool

NAME = 'Remotion___render_timeline'
ARGS = {'title': 'Parity', 'visuals': [{'kind': 'image', 'url': 'still.png', 'duration_seconds': 1,
                                     'crop_box': {'x': 0, 'y': 0, 'width': 160, 'height': 90}}]}


class BackendSelectionTests(unittest.IsolatedAsyncioTestCase):
    def gateway(self):
        from providers.catalog import get_provider
        from providers.registry import generate_schemas
        return Gateway([Tool(name='Remotion___' + schema['name'], description=schema['description'],
                             inputSchema=schema['inputSchema'])
                        for schema in generate_schemas(get_provider('remotion'))])

    def executor(self, gateway, autonomous=True):
        context = _context_from_request(StudioAgentRequest(
            prompt='assemble existing clips', job_id='parity', autonomous=autonomous))
        context.source_versions['still.png'] = 'owned-still'
        context.source_resolver = Mock(return_value='/owned/still.png')
        return GatewayExecutor(context, [gateway])

    async def test_lambda_refuses_local_feature_before_approval_or_gateway_call(self):
        gateway = self.gateway()
        args = {**ARGS, 'visuals': [{**ARGS['visuals'][0], 'kind': 'video'}]}
        with patch.dict(os.environ, {'REMOTION_RENDER_BACKEND': 'lambda', 'REMOTION_DRY_RUN': 'true'}):
            result = await self.executor(gateway).execute({'tool_name': NAME, 'arguments': args, 'call_id': 'crop'})
        self.assertEqual(result['status'], 'not_run')
        self.assertIn('local/worker', result['reason'])
        gateway.call_tool.assert_not_called()

    async def test_poll_uses_saved_backend_not_current_configuration(self):
        name = 'Remotion___get_render_progress'
        for backend, render_id, on_worker in [('lambda', 'local-existing', True),
                                              ('local', 'aws-existing', False)]:
            gateway = self.gateway()
            with self.subTest(backend=backend), patch.dict(os.environ, {'REMOTION_RENDER_BACKEND': backend}), \
                    patch('providers.registry.dispatch', return_value={'status': 'dry_run'}) as worker:
                await self.executor(gateway).execute({'tool_name': name, 'arguments': {
                    'render_id': render_id, 'bucket_name': 'test-bucket'}, 'call_id': 'poll'}, approved=True)
            self.assertEqual(worker.call_count, int(on_worker))
            self.assertEqual(gateway.call_tool.call_count, int(not on_worker))

    async def test_local_dispatch_resolves_owned_handles_without_publishing(self):
        gateway = self.gateway()
        args = {'title': 'Handles', 'visuals': [{'kind': 'image', 'url': 'renderhaus-asset://owned',
                                               'duration_seconds': 1}],
                'audio_tracks': [{'url': 'known-original-url', 'duration_seconds': 1}]}
        executor = self.executor(gateway)
        executor.studio.source_resolver = Mock(side_effect=lambda version: '/owned/' + version)
        executor.studio.source_versions['known-original-url'] = 'owned-audio'
        executor.studio.source_publisher = Mock(side_effect=AssertionError('No upload on local backend'))
        with patch.dict(os.environ, {'REMOTION_RENDER_BACKEND': 'local'}), \
                patch('providers.registry.dispatch', return_value={'status': 'dry_run'}) as worker:
            await executor.execute({'tool_name': NAME, 'arguments': args, 'call_id': 'handles'}, approved=True)
        sent = worker.call_args.args[2]
        self.assertEqual(sent['visuals'][0]['url'], '/owned/owned')
        self.assertEqual(sent['audio_tracks'][0]['url'], '/owned/owned-audio')
        self.assertEqual(args['visuals'][0]['url'], 'renderhaus-asset://owned')
        executor.studio.source_publisher.assert_not_called()
        gateway.call_tool.assert_not_called()

    async def test_local_refuses_unowned_raw_paths_before_dispatch(self):
        for path in ('/media/other-job/private.mp4', '../other-job/private.mp4',
                     'renderhaus-asset://'):
            gateway = self.gateway()
            args = {'title': 'Unowned', 'visuals': [{'kind': 'image', 'output_path': path,
                                                   'duration_seconds': 1}]}
            with self.subTest(path=path), patch.dict(os.environ, {'REMOTION_RENDER_BACKEND': 'local'}), \
                    patch('providers.registry.dispatch') as worker:
                result = await self.executor(gateway).execute({
                    'tool_name': NAME, 'arguments': args, 'call_id': 'unowned'}, approved=True)
            self.assertEqual(result['status'], 'not_run')
            worker.assert_not_called()
            gateway.call_tool.assert_not_called()

    async def test_remote_poll_without_gateway_has_a_clear_refusal(self):
        gateway = Gateway([])
        with patch.dict(os.environ, {'REMOTION_RENDER_BACKEND': 'local'}):
            result = await self.executor(gateway).execute({'tool_name': 'Remotion___get_render_progress',
                'arguments': {'render_id': 'aws-existing', 'bucket_name': 'test'}, 'call_id': 'missing'})
        self.assertIn('Gateway', result.get('reason', result.get('error', '')))
        self.assertNotIn('NoneType', result.get('error', ''))
        gateway.call_tool.assert_not_called()

    async def test_local_accepts_raw_source_inside_trusted_current_job(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'parity' / 'source.png'
            source.parent.mkdir()
            source.write_bytes(b'fixture')
            gateway = self.gateway()
            args = {'title': 'Owned job', 'visuals': [{'kind': 'image', 'output_path': str(source),
                                                    'duration_seconds': 1}]}
            with patch.dict(os.environ, {'REMOTION_RENDER_BACKEND': 'local', 'RENDERHAUS_MEDIA_DIR': folder}), \
                    patch('providers.registry.dispatch', return_value={'status': 'dry_run'}) as worker:
                result = await self.executor(gateway).execute({
                    'tool_name': NAME, 'arguments': args, 'call_id': 'owned'}, approved=True)
            self.assertEqual(result['status'], 'dry_run')
            self.assertEqual(worker.call_args.args[2]['visuals'][0]['output_path'], str(source))
            gateway.call_tool.assert_not_called()

    async def test_configured_local_executes_on_worker_and_keeps_approval(self):
        gateway = self.gateway()
        args = {**ARGS, 'visuals': [{key: value for key, value in ARGS['visuals'][0].items() if key != 'crop_box'}]}
        with patch.dict(os.environ, {'REMOTION_RENDER_BACKEND': 'local', 'REMOTION_DRY_RUN': 'true'}):
            executor = self.executor(gateway, autonomous=False)
            with self.assertRaises(ToolApprovalPending):
                await executor.execute({'tool_name': NAME, 'arguments': args, 'call_id': 'local'})
            result = await executor.execute({'tool_name': NAME, 'arguments': args, 'call_id': 'local'}, approved=True)
        self.assertEqual(result['status'], 'dry_run')
        gateway.call_tool.assert_not_called()

    async def test_default_lambda_keeps_gateway_dispatch(self):
        gateway = self.gateway()
        args = {**ARGS, 'visuals': [{key: value for key, value in ARGS['visuals'][0].items() if key != 'crop_box'}]}
        with patch.dict(os.environ, {'REMOTION_RENDER_BACKEND': 'lambda', 'REMOTION_DRY_RUN': 'true'}):
            await self.executor(gateway).execute({'tool_name': NAME, 'arguments': args, 'call_id': 'lambda'}, approved=True)
        gateway.call_tool.assert_called_once()

    async def test_local_does_not_fall_back_to_gateway_for_css_text(self):
        gateway = self.gateway()
        args = {**ARGS, 'visuals': [{key: value for key, value in ARGS['visuals'][0].items() if key != 'crop_box'}],
                'text_overlays': [{'text': 'Buy', 'start_seconds': 0, 'duration_seconds': 1, 'font_weight': 300}]}
        with patch.dict(os.environ, {'REMOTION_RENDER_BACKEND': 'local'}):
            result = await self.executor(gateway).execute({'tool_name': NAME, 'arguments': args, 'call_id': 'text'})
        self.assertEqual(result['status'], 'not_run')
        self.assertIn('Lambda', result['reason'])
        gateway.call_tool.assert_not_called()
