from __future__ import annotations

import asyncio
import threading
import unittest
from unittest.mock import patch
import os

import mcp_types as types


class LocalGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_progressive_search_reveals_schema_then_dispatches_registered_tool(self) -> None:
        from scripts.local_gateway import LocalGateway, SEARCH_NAME
        gateway = LocalGateway()
        listed = await gateway.list_tools(None, None)
        self.assertEqual([tool.name for tool in listed.tools], [SEARCH_NAME])
        result = await gateway.call_tool(None, types.CallToolRequestParams(
            name=SEARCH_NAME, arguments={'query': 'Remotion render_timeline get_render_progress'}))
        tools = result.structured_content['tools']
        self.assertTrue({'Remotion___render_timeline', 'Remotion___get_render_progress'}
                        <= {tool['name'] for tool in tools})
        self.assertTrue(all(tool['inputSchema']['type'] == 'object' for tool in tools))
        with patch('scripts.local_gateway.dispatch', return_value={'status': 'dry_run'}) as dispatch:
            called = await gateway.call_tool(None, types.CallToolRequestParams(
                name='Remotion___get_render_progress', arguments={'render_id': 'dry-run', 'bucket_name': 'local'}))
        dispatch.assert_called_once_with('remotion', 'get_render_progress',
                                        {'render_id': 'dry-run', 'bucket_name': 'local'})
        self.assertEqual(called.structured_content['status'], 'dry_run')

    async def test_optional_spend_cap_blocks_unknown_estimates_and_reserves_in_flight_calls(self) -> None:
        from scripts.local_gateway import LocalGateway
        gateway = LocalGateway(max_spend_cents=100)
        with patch.dict(os.environ, {'STRIPE_SECRET_KEY': '', 'ELEVENLABS_TOOL_COST_CENTS_JSON': '{}',
                                     'REMOTION_RENDER_BACKEND': 'lambda'}), \
                patch('scripts.local_gateway.dispatch') as dispatch:
            for name in ('Remotion___render_timeline', 'ElevenLabs___music_compose'):
                with self.subTest(name=name):
                    result = await gateway.call_tool(None, types.CallToolRequestParams(name=name, arguments={}))
                    self.assertTrue(result.is_error)
                    self.assertIn('known cost estimate', result.structured_content['error'])
        dispatch.assert_not_called()
        from agent.deep_agent.routing import CostEstimate
        started, release = threading.Event(), threading.Event()
        def provider_call(*args):
            started.set()
            release.wait(2)
            return {'status': 'queued'}
        request = types.CallToolRequestParams(name='Remotion___render_timeline', arguments={})
        with patch('scripts.local_gateway.estimate_cost', return_value=CostEstimate(60)), \
                patch('scripts.local_gateway.dispatch', side_effect=provider_call) as dispatch:
            first = asyncio.create_task(gateway.call_tool(None, request))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                second = await gateway.call_tool(None, request)
                self.assertTrue(second.is_error)
                self.assertIn('cap', second.structured_content['error'])
            finally:
                release.set()
            self.assertEqual((await first).structured_content['status'], 'queued')
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(gateway.spent_cents, 60)
