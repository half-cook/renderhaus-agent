from __future__ import annotations

import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from agent.studio_agent_next import StudioAgentRequest, _context_from_request
from test_deep_agent import ScriptedModel, call


class ShotRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def request(self):
        return StudioAgentRequest(
            prompt="Use the 'ink press' style shot card for the product reveal in my promo video",
            workspace_id='workspace', project_id='project', conversation_id='conversation',
            job_id='job', autonomous=False,
        )

    async def test_worker_injects_and_executes_data_tool_without_gateway_or_media_job(self):
        from agent.gateway_executor import GatewayExecutor

        studio = _context_from_request(self.request())
        studio.job_id = None
        executor = GatewayExecutor(studio, [])
        available = await executor.available()
        self.assertIn('ShotRecipes___shot_recipe_search', available)
        self.assertIsNone(available['ShotRecipes___shot_recipe_search'][0])
        with patch('socket.create_connection', side_effect=AssertionError('network forbidden')):
            result = await executor.execute({'tool_name': 'ShotRecipes___shot_recipe_search',
                                             'arguments': {'query': 'ink press'}, 'call_id': 'search'})
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['results'][0]['id'], 'brand-ink-open')
        self.assertEqual(executor.reservations, {})
        self.assertFalse(any(e.status == 'awaiting_approval' for e in studio.tool_events))

    async def test_named_card_cannot_be_substituted_or_omitted_from_storyboard(self):
        from agent.gateway_executor import GatewayExecutor
        from test_shot_recipes import storyboard

        executor = GatewayExecutor(_context_from_request(self.request()), [])
        wrong = await executor.execute({'tool_name': 'ShotRecipes___shot_recipe_search',
                                        'arguments': {'card_id': 'odometer-digit-roll'}, 'call_id': 'wrong'})
        self.assertEqual(wrong['status'], 'not_run')
        self.assertIn('user-named', wrong['reason'])
        value = storyboard()
        value['named_cards'] = {}
        value['beats'][0]['selection'] = 'agent'
        omitted = await executor.execute({'tool_name': 'ShotRecipes___shot_recipe_search',
                                          'arguments': {'mode': 'validate_storyboard', 'storyboard': value},
                                          'call_id': 'omitted'})
        self.assertEqual(omitted['status'], 'not_run')
        self.assertFalse(any(e.status == 'awaiting_approval' for e in executor.studio.tool_events))

    async def test_malformed_storyboard_returns_a_blocker_before_approval_guard(self):
        from agent.gateway_executor import GatewayExecutor

        executor = GatewayExecutor(_context_from_request(self.request()), [])
        reason = executor.selection_blocker('ShotRecipes___shot_recipe_search',
                                            {'mode': 'validate_storyboard', 'storyboard': {'beats': [None]}}, None)
        self.assertIsInstance(reason, str)

    async def test_deep_agent_loads_skill_and_uses_free_editor_dispatch(self):
        from agent.deep_agent.runner import run_with_servers

        request = self.request()
        studio = _context_from_request(request)
        final = {'title': 'Recipe plan', 'summary': 'Reveal recipe selected. Media production is pending.',
                 'markdown': '# Recipe plan\nThe selected reveal card is brand-ink-open.',
                 'filename': 'recipe-plan.md'}
        model = ScriptedModel([
            call('read_file', {'file_path': '/skills/cinematic-product-promo/SKILL.md'}, 'skill'),
            call('call_editor_tool', {'tool_name': 'ShotRecipes___shot_recipe_search',
                                      'arguments': {'card_id': 'brand-ink-open'}}, 'recipe'),
            call('StudioAgentOutput', final, 'final'),
        ])
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            'RENDERHAUS_PROJECT_MEMORY_DIR': directory,
            'RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS': '',
        }):
            result = await run_with_servers(request, studio, [], model=model)
        self.assertEqual(result.title, 'Recipe plan')
        events = [event for event in studio.tool_events if event.name == 'ShotRecipes___shot_recipe_search']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].result['results'][0]['id'], 'brand-ink-open')
        self.assertFalse(any(e.status == 'awaiting_approval' for e in studio.tool_events))


class ShotMotionDeliveryTests(unittest.TestCase):
    def test_recipe_lookup_is_a_plan_but_rendering_keeps_motion_qc(self):
        from agent.deep_agent.motion_carry_gate import requires_motion_qc
        from agent.studio_agent_next import StudioToolEvent

        prompt = "Use the 'ink press' style shot card for the product reveal in my promo video"
        self.assertFalse(requires_motion_qc(prompt, []))
        render = StudioToolEvent(id='render', name='Remotion___render_timeline',
                                 label='Assemble film', status='succeeded', summary='Queued',
                                 provider='remotion', arguments={}, result={'render_id': 'saved-render'})
        self.assertTrue(requires_motion_qc(prompt, [render]))


class ShotPackagingTests(unittest.TestCase):
    def test_lambda_bundle_contains_all_verbatim_cards_and_search_runs_from_bundle(self):
        spec = importlib.util.spec_from_file_location('shot_deploy', 'scripts/deploy_gateway.py')
        deploy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(deploy)
        with patch.object(deploy.subprocess, 'run'):
            archive = deploy.build_lambda_zip()
        root = Path('providers/shot_recipes')
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            names = bundle.namelist()
            self.assertEqual(len([name for name in names if name.startswith('providers/shot_recipes/cards/')]), 157)
            for path in root.rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts:
                    self.assertEqual(bundle.read(path.as_posix()), path.read_bytes())
            for filename in ('LICENSE', 'NOTICE.md', 'ATTRIBUTION.md', 'index.json'):
                self.assertIn('providers/shot_recipes/' + filename, names)
            with tempfile.TemporaryDirectory() as directory:
                bundle.extractall(directory)
                from providers.shot_recipes import library
                from providers.shot_recipes.api import shot_recipe_search

                library._catalog.cache_clear()
                try:
                    with patch.object(library, 'ROOT', Path(directory) / 'providers/shot_recipes'):
                        result = shot_recipe_search(card_id='brand-ink-open')
                        self.assertTrue(result['ok'], result)
                        self.assertTrue(result['recipe']['parameter_table'])
                finally:
                    library._catalog.cache_clear()

    def test_wheel_package_data_and_container_copy_cover_library(self):
        import tomllib

        config = tomllib.loads(Path('pyproject.toml').read_text())
        data = config['tool']['setuptools']['package-data']['providers.shot_recipes']
        self.assertIn('cards/*/*.md', data)
        self.assertIn('index.json', data)
        self.assertIn('COPY providers ./providers', Path('Dockerfile.agentcore').read_text())


if __name__ == '__main__':
    unittest.main()
