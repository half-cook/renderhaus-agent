"""The configured catalog must not revive removed integrations or relax approvals."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from mcp import Tool

from agent.deep_agent.routing import POLICY, capability_table, policy_blocker, request_tool_blocker, route_intent
from agent.gateway_executor import GatewayExecutor, tool_needs_approval
from agent.studio_agent_next import StudioAgentRequest, _context_from_request
from providers.catalog import PROVIDERS


class SupportedIntegrationsTests(unittest.IsolatedAsyncioTestCase):
    def test_catalog_has_only_built_policy_bindings(self):
        self.assertFalse({'runway', 'kling', 'luma', 'heygen', 'footage_memory', 'alibaba_modelstudio'}
                         & {spec.id for spec in PROVIDERS})
        for row in capability_table():
            self.assertIn(row['policy_ref'], POLICY['providers'])
        self.assertTrue(all(tool.get('gateway_tool') and tool['status'] == 'ready'
                            for tool in POLICY['tools'].values()))

    def test_spending_approval_survives_provider_cleanup(self):
        with patch.dict('os.environ', {'RENDERHAUS_PREMIUM_VIDEO_APPROVAL': 'false'}):
            for name in ('Sync___lipsync_video', 'Topaz___upscale_video', 'Topaz___interpolate_video',
                         'Mureka___generate_lyrics_video', 'Fal___kling_motion_control',
                         'Remotion___prepare_conversational_edit'):
                self.assertTrue(tool_needs_approval(name, autonomous=True), name)
                self.assertTrue(tool_needs_approval(name, autonomous=False), name)

    def test_unavailable_visual_qc_never_falls_back_to_generation(self):
        for prompt in ('Check shot continuity between these generated shots.',
                       'Check if the generated person looks the same across shots.',
                       'Review character consistency across the clips.'):
            route = route_intent(prompt)
            self.assertEqual(route.status, 'blocked')
            self.assertIsNone(route.tool)
            self.assertIsNotNone(request_tool_blocker(prompt, 'Fal___generate_wan3_t2v'))
        explicit = 'Use Gemini to judge continuity across these shots.'
        self.assertEqual(route_intent(explicit).tool, 'Gemini___judge_continuity')
        self.assertIsNone(request_tool_blocker(explicit, 'Gemini___judge_continuity'))
        self.assertIsNone(request_tool_blocker('Check for black frames.', 'Ffmpeg___ffmpeg_tool'))

    async def test_studio_options_use_supported_catalogs(self):
        from server.studio import studio_options
        from server.studio_options import LIVE_CHOICE_TOOLS

        with patch('server.studio.dispatch', return_value={}) as dispatch:
            result = await studio_options()
        supported = {spec.id for spec in PROVIDERS}
        self.assertLessEqual(set(result['providers']), supported)
        self.assertEqual(dispatch.call_count, len(LIVE_CHOICE_TOOLS))
        for provider, _, _ in LIVE_CHOICE_TOOLS:
            self.assertIn(provider, supported)

    async def test_removed_tools_are_hidden_even_from_saved_gateway_catalogs(self):
        removed = ['Runway___get_runway_task', 'HeyGen___create_avatar_video',
                   'HyperFrames___render_composition', 'Sync___create_dialogue_edit']
        server = SimpleNamespace(list_tools=AsyncMock(return_value=[
            Tool(name=name, inputSchema={'type': 'object'}) for name in removed
        ]))
        executor = GatewayExecutor(_context_from_request(StudioAgentRequest(prompt='make a video')), [server])
        available = await executor.available()
        for name in removed:
            self.assertNotIn(name, available)
            self.assertIsNotNone(policy_blocker(name, {}))
        self.assertEqual(executor.filter_discovery([{'name': name} for name in removed]), [])
