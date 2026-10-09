import json
import os
import unittest
from unittest.mock import patch

from mcp import Tool

from agent.gateway_executor import GatewayExecutor
from agent.studio_agent_next import StudioAgentRequest, _context_from_request
from test_deep_agent import Gateway


class ProviderCostLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_call_logs_estimate_and_latency_without_input(self):
        name = 'ElevenLabs___text_to_speech_convert'
        gateway = Gateway([Tool(name=name, inputSchema={'type': 'object'})])
        gateway.call_tool.return_value = {'status': 'succeeded', 'result': {'output_path': '/tmp/voice.mp3'}}
        studio = _context_from_request(StudioAgentRequest(prompt='Narrate this line', job_id='cost-log', autonomous=True))
        executor = GatewayExecutor(studio, [gateway])
        with patch.dict(os.environ, {'STRIPE_SECRET_KEY': '', 'ELEVENLABS_TOOL_COST_CENTS_JSON': '{}'}, clear=True):
            with self.assertLogs('renderhaus.gateway_executor', level='INFO') as logs:
                await executor.execute({'tool_name': name, 'arguments': {'text': 'PRIVATE NARRATION', 'voice_id': 'test'}, 'call_id': 'cost-call'}, approved=True)
        record = json.loads(logs.records[-1].message)
        self.assertEqual(record['event'], 'provider_call')
        self.assertEqual(record['request_id'], 'cost-log')
        self.assertEqual(record['call_id'], 'cost-call')
        self.assertEqual(record['status'], 'succeeded')
        self.assertGreater(record['provider_cost_estimate_cents'], 0)
        self.assertGreaterEqual(record['latency_seconds'], 0)
        self.assertNotIn('PRIVATE NARRATION', logs.output[-1])
        self.assertNotIn('/tmp/voice.mp3', logs.output[-1])
