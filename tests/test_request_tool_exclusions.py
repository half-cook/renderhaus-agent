import json
import unittest

from mcp import Tool

from agent.gateway_executor import GatewayExecutor
from agent.studio_agent_next import StudioAgentRequest, _context_from_request, _GATEWAY_SEARCH_TOOL
from test_deep_agent import Gateway


class RequestToolExclusionTests(unittest.IsolatedAsyncioTestCase):
    async def test_image_tools_never_reach_shot_voiceover_discovery_or_dispatch(self):
        tools = [Tool(name=name, inputSchema={'type': 'object'}) for name in (
            _GATEWAY_SEARCH_TOOL, 'Seedream___text_to_image', 'Runway___image_to_image',
            'Fal___generate_wan3_t2v', 'ElevenLabs___text_to_speech_convert',
        )]
        gateway = Gateway(tools)
        gateway.call_tool.return_value = {'tools': [t.model_dump(by_alias=True) for t in tools[1:]]}
        studio = _context_from_request(StudioAgentRequest(prompt='Make a 5-second shot with a calm voiceover'))
        executor = GatewayExecutor(studio, [gateway])
        visible = await executor.available()
        self.assertNotIn('Seedream___text_to_image', visible)
        self.assertNotIn('Runway___image_to_image', visible)
        searched = await executor.execute({'tool_name': _GATEWAY_SEARCH_TOOL, 'arguments': {'query': 'video'}, 'call_id': 'search'}, approved=True)
        self.assertNotIn('Seedream___text_to_image', str(searched))
        self.assertNotIn('Runway___image_to_image', str(searched))
        result = await executor.execute({'tool_name': 'Seedream___text_to_image', 'arguments': {'prompt': 'a still'}, 'call_id': 'image'}, approved=True)
        self.assertEqual(result['status'], 'not_run')
        self.assertEqual(gateway.call_tool.await_count, 1)
        self.assertFalse(any('Seedream' in e.message or 'Runway' in e.message for e in studio.progress_events))

    async def test_all_supported_search_tool_shapes_hide_forbidden_image_names(self):
        prompt = 'Make a 5-second shot with a calm voiceover'
        executor = GatewayExecutor(_context_from_request(StudioAgentRequest(prompt=prompt)), [])
        for key in ('name', 'toolName', 'tool_name'):
            definition = {key: 'Seedream___text_to_image', 'inputSchema': {'type': 'object'}}
            for value in ({'tool': definition}, {'tools': [definition]},
                          {'content': [{'type': 'text', 'text': json.dumps({'tool': definition})}]}):
                with self.subTest(key=key, value=value):
                    self.assertNotIn('Seedream___text_to_image', str(executor.filter_discovery(value)))
