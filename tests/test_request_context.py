import unittest

from agent.studio_agent_next import StudioAgentContext, StudioAgentRequest, run_studio_agent
from test_codex_harness import FakeHarness


class RequestContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_routing_context_uses_current_prompt_with_supplied_session(self):
        studio = StudioAgentContext(prompt='Previous turn')
        request = StudioAgentRequest(prompt='Make a still with Seedream')
        await run_studio_agent(request, studio=studio, harness=FakeHarness(), mcp_servers=[])
        self.assertEqual(studio.prompt, request.prompt)
