from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp import Tool

from agent.deep_agent import routing
from agent.gateway_executor import GatewayExecutor, tool_needs_approval
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, _context_from_request,
)
from test_deep_agent import Gateway, ScriptedModel, call, final

EDIT = 'Seedance___edit_video'
EXTEND = 'Seedance___extend_video'
SOURCE = {'video_url': 'https://example.invalid/source.mp4', 'prompt': 'Make it clay',
          'source_duration_seconds': 5, 'source_fps': 24, 'source_aspect_ratio': '16:9', 'duration_seconds': 7, 'resolution': '720p'}
ENV = {'SEEDANCE_DRY_RUN': 'true', 'SEEDANCE_TRANSPORT': 'fal', 'SEEDANCE_FAL_REGION': 'us',
       'FAL_DRY_RUN': 'true', 'MODELSTUDIO_DRY_RUN': 'true'}


class SeedanceRoutingTests(unittest.TestCase):
    def test_licence_interim_and_single_switch_restore_default(self):
        with patch.dict(os.environ, ENV):
            for capability, alias, tool in [('v2v_edit', 'wan3_edit', EDIT), ('extend', 'wan3_extend', EXTEND)]:
                route = routing.select_provider(capability)
                self.assertEqual((route.status, route.alias, route.tool), ('ready', alias, tool))
                self.assertIn('licence', route.disclosure)
                self.assertIn('interim', route.disclosure)
                self.assertEqual(routing.resolve_alias(alias), tool)
                policy = routing.POLICY['providers']['alibaba_modelstudio']['model_policies']['wan3.0-video']
                with patch.dict(policy, {'live_enabled': True}):
                    restored = routing.select_provider(capability)
                    expected = 'ModelStudio___edit_wan3_video' if capability == 'v2v_edit' else 'ModelStudio___extend_wan3_video'
                    self.assertEqual(restored.tool, expected)
                    self.assertEqual(routing.resolve_alias(alias), expected)

    def test_dialogue_tools_are_ready_and_transport_model_is_consistent(self):
        with patch.dict(os.environ, ENV):
            for prompt, alias, verb in [('a robot says "hi"', 'seedance25_t2v', 'text_to_video'),
                                        ('animate mascot image speaking', 'seedance25_i2v', 'image_to_video'),
                                        ('synthetic characters from refs talking', 'seedance25_r2v', 'reference_to_video')]:
                route = routing.route_intent(prompt)
                self.assertEqual((route.status, route.alias, route.tool), ('ready', alias, f'Seedance___{verb}'))
                self.assertEqual(route.model, routing.effective_model('seedance', verb, {}))
                self.assertNotIn('pending', route.disclosure)

    def test_real_person_flags_cannot_be_weakened(self):
        with patch.dict(os.environ, ENV):
            for marker in ['real_face_refs', 'user_supplied_real_person_refs']:
                route = routing.select_provider('i2v', provider='seedance', arguments={marker: True})
                self.assertEqual(route.tool, 'Fal___generate_wan3_i2v')
                self.assertTrue(route.required['real_face_refs'])
            route = routing.route_intent('use Seedance with my CEO photo saying "hi"',
                                         arguments={'real_face_refs': False, 'user_supplied_real_person_refs': False})
            self.assertEqual(route.tool, 'Fal___generate_wan3_i2v')
            self.assertTrue(route.required['real_face_refs'])
            for capability in ['v2v_edit', 'extend']:
                route = routing.select_provider(capability, arguments={'user_supplied_real_person_refs': True})
                self.assertEqual(route.status, 'blocked')
                self.assertIn('real', route.reason.lower())
                self.assertIsNone(route.tool)

    def test_explicit_wan_and_missing_interim_never_silently_change_provider(self):
        with patch.dict(os.environ, ENV):
            self.assertEqual(routing.route_intent('use Wan 3 to edit this video').tool, 'ModelStudio___edit_wan3_video')
            self.assertEqual(routing.select_provider('v2v_edit', available_tools={'Luma___modify_video'}).status, 'blocked')
            for tool in [EDIT, EXTEND, 'Seedance___reference_to_video']:
                self.assertTrue(tool_needs_approval(tool, autonomous=True))

    def test_extension_by_seconds_requires_total_output_duration(self):
        with patch.dict(os.environ, ENV):
            route = routing.route_intent('extend this clip by 2 seconds', arguments=SOURCE)
            self.assertEqual(route.tool, EXTEND)
            self.assertEqual(route.required['duration_seconds'], 7)
            request = StudioAgentRequest(prompt='extend this clip by 2 seconds', autonomous=True, job_id='duration')
            executor = GatewayExecutor(_context_from_request(request), [Gateway()])
            self.assertIn('duration', executor.selection_blocker(EXTEND, {**SOURCE, 'duration_seconds': 2}, route))

    def test_transport_regions_and_explicit_legacy_model(self):
        with patch.dict(os.environ, {**ENV, 'SEEDANCE_FAL_REGION': 'global'}):
            route = routing.route_intent('Seedance video')
            self.assertEqual(route.model, 'bytedance/seedance-2.5/text-to-video')
        with patch.dict(os.environ, {**ENV, 'SEEDANCE_TRANSPORT': 'byteplus', 'RENDERHAUS_CUSTOMER_REGION': 'CA'}):
            route = routing.route_intent('Seedance 1.5 video')
            self.assertEqual((route.status, route.model), ('ready', 'seedance-1-5-pro-251215'))
            explicit = routing.select_provider('t2v', provider='seedance', model='seedance-1-5-pro-251215')
            self.assertEqual((explicit.status, explicit.model), ('ready', 'seedance-1-5-pro-251215'))
            self.assertIsNotNone(routing.policy_blocker('Seedance___text_to_video', {}, region='US'))
        with patch.dict(os.environ, {**ENV, 'SEEDANCE_TRANSPORT': 'byteplus', 'SEEDANCE_DRY_RUN': 'false',
                                    'RENDERHAUS_CUSTOMER_REGION': 'CA', 'SEEDANCE_BYTEPLUS_PLATFORM_AUTHORIZED': 'false'}):
            self.assertIn('authorization', routing.policy_blocker('Seedance___text_to_video', {}))


class SeedanceGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_graph_interim_autonomous_approval_and_resume(self):
        from agent.deep_agent.runner import run_with_servers

        for verb, prompt in [(EDIT, 'restyle this footage'), (EXTEND, 'extend this clip')]:
            for decision in ['approve', 'reject']:
                with self.subTest(verb=verb, decision=decision), tempfile.TemporaryDirectory() as directory, patch.dict(
                    os.environ, {**ENV, 'RENDERHAUS_OUTCOME_DIR': directory},
                ):
                    request = StudioAgentRequest(prompt=prompt, autonomous=True, job_id=verb + decision)
                    studio = _context_from_request(request)
                    gateway = Gateway([Tool(name=verb, inputSchema={'type': 'object'})], {'status': 'queued', 'job_id': 'saved'})
                    arguments = {**SOURCE, 'duration_seconds': -1 if verb == EDIT else 7}
                    quote = routing.estimate_cost(verb, arguments, list_price=True)
                    self.assertIsNotNone(quote.total_cents)
                    self.assertGreater(quote.total_cents, 0)
                    with self.assertRaises(StudioAgentApprovalRequired) as paused:
                        await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                            call('read_file', {'file_path': '/skills/edit-v2v/SKILL.md'}, 'skill'),
                            call('call_media_tool', {'tool_name': verb, 'arguments': arguments}, 'video'),
                        ]))
                    approval = paused.exception.approvals[0]
                    self.assertIn('Seedance', approval.description)
                    self.assertIn('Estimated', approval.description)
                    self.assertIn(f'${quote.total_cents / 100:.2f}', approval.description)
                    gateway.call_tool.assert_not_awaited()
                    resumed = request.model_copy(update={'session_items': studio.session_items,
                        'resume_state': paused.exception.state,
                        'approval_decisions': [StudioApprovalDecision(call_id=approval.call_id, decision=decision)]})
                    await run_with_servers(resumed, _context_from_request(resumed), [gateway], model=ScriptedModel([final()]))
                    if decision == 'approve':
                        gateway.call_tool.assert_awaited_once()
                    else:
                        gateway.call_tool.assert_not_awaited()
                        rows = [json.loads(line) for line in (Path(directory) / 'outcomes.jsonl').read_text().splitlines()]
                        self.assertFalse(rows[-1]['training_eligible'])

    async def test_gateway_rejects_stale_default_and_asset_real_face_metadata(self):
        with patch.dict(os.environ, ENV):
            request = StudioAgentRequest(prompt='restyle this footage', autonomous=True, job_id='guard')
            studio = _context_from_request(request)
            gateway = Gateway([Tool(name=name, inputSchema={'type': 'object'}) for name in [EDIT, 'ModelStudio___edit_wan3_video']])
            executor = GatewayExecutor(studio, [gateway])
            result = await executor.execute({'tool_name': 'ModelStudio___edit_wan3_video', 'arguments': SOURCE, 'call_id': 'stale'}, approved=True)
            self.assertEqual(result['status'], 'not_run')
            self.assertIn(EDIT, result['reason'])
            studio.working_assets['person'] = {'version_id': 'person', 'real_face_refs': True}
            result = await executor.execute({'tool_name': EDIT, 'arguments': {**SOURCE,
                'video_url': 'renderhaus-asset://person', 'real_face_refs': False}, 'call_id': 'face'}, approved=True)
            self.assertEqual(result['status'], 'not_run')
            self.assertIn('real', result['reason'].lower())
            gateway.call_tool.assert_not_awaited()

    async def test_fal_poll_matches_saved_endpoint_not_only_job_id(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {**ENV, 'RENDERHAUS_OUTCOME_DIR': directory}):
            endpoint = 'bytedance/seedance-2.5/us/reference-to-video'
            handle = endpoint + ':saved'
            request = StudioAgentRequest(prompt='check the saved video', autonomous=True, job_id='poll')
            studio = _context_from_request(request)
            saved = {'media_jobs': {
                'good': {'provider': 'seedance', 'model': endpoint, 'provider_job_id': handle, 'status': 'queued',
                         'job_type': 'v2v_edit', 'arguments': SOURCE, 'required': {}, 'asset': {}, 'endpoint_id': endpoint},
                'bad': {'provider': 'seedance', 'model': 'dreamina-seedance-2-5-260628', 'provider_job_id': handle,
                        'status': 'queued', 'job_type': 'v2v_edit', 'arguments': SOURCE, 'required': {}, 'asset': {}},
            }}
            gateway = Gateway([Tool(name='Fal___get_video_task', inputSchema={'type': 'object'})],
                              {'status': 'succeeded', 'job_id': handle, 'endpoint_id': endpoint, 'model': endpoint,
                               'video_url': 'https://example.invalid/result.mp4'})
            executor = GatewayExecutor(studio, [gateway], saved)
            await executor.execute({'tool_name': 'Fal___get_video_task', 'arguments': {'job_id': handle}, 'call_id': 'poll'})
            self.assertEqual(executor.media_jobs['good']['status'], 'succeeded')
            self.assertEqual(executor.media_jobs['bad']['status'], 'queued')
            self.assertFalse(executor.media_jobs['good']['asset']['training_eligible'])
