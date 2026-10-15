from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from langchain_core.messages import ToolMessage

from agent.deep_agent.runner import run_with_servers
from agent.studio_agent_next import StudioAgentRequest, _context_from_request
from test_deep_agent import Gateway, ScriptedModel, call


class ArtCatalogHostTests(unittest.IsolatedAsyncioTestCase):
    async def read_context(self, prompt, inspect):
        request = StudioAgentRequest(prompt=prompt, workspace_id='workspace', project_id='project',
                                     conversation_id='catalog', job_id='catalog')
        studio = _context_from_request(request)
        gateway = Gateway([])

        def observe(messages, tools):
            context = next(json.loads(message.content) for message in messages
                           if isinstance(message, ToolMessage) and message.name == 'read_studio_context')
            inspect(context)
            return call('StudioAgentOutput', {
                'title': 'Style plan', 'summary': 'Style selection is ready. Rendering is pending.',
                'markdown': '# Style plan\nRendering is pending.', 'filename': 'style-plan.md',
            }, 'finish')

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            'RENDERHAUS_PROJECT_MEMORY_DIR': directory, 'RENDERHAUS_SECRETS_NAME': '',
            'RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS': '',
        }), patch('socket.create_connection', side_effect=AssertionError('network forbidden')):
            result = await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                call('read_studio_context', {}, 'context'), observe,
            ]))
        gateway.call_tool.assert_not_awaited()
        self.assertTrue(result.title)
        self.assertFalse(any(event.status == 'awaiting_approval' for event in studio.tool_events))

    async def test_native_context_supplies_safe_selected_prompt_and_shot_notes(self):
        def inspect(context):
            self.assertEqual(context['intent_route']['skill'], 'art-style-motion')
            catalog = context['style_catalog']
            self.assertEqual(catalog['selected']['slug'], 'stencil-ink-print')
            self.assertEqual(catalog['basis'], 'explicit style')
            self.assertGreater(len(catalog['selected']['style_prompt']), 80)
            self.assertTrue(catalog['selected']['shot_direction_notes'])
            self.assertNotIn('risograph', json.dumps(catalog).lower())
            self.assertNotIn('source_path', json.dumps(catalog))

        await self.read_context('Make a risograph animated explainer with the catalog', inspect)

    async def test_native_context_resolves_papercut_to_neutral_grammar_without_dispatch(self):
        def inspect(context):
            self.assertEqual(context['intent_route']['skill'], 'art-style-motion')
            self.assertEqual(context['intent_route']['alias'], 'remotion_render')
            catalog = context['style_catalog']
            self.assertEqual(catalog['selected']['slug'], 'document-evidence')
            self.assertEqual(catalog['selected']['name'], 'Document Evidence')
            self.assertEqual(catalog['basis'], 'explicit built-in style')
            self.assertNotIn('vox', json.dumps(catalog).lower())
            self.assertNotIn('source_path', json.dumps(catalog))

        await self.read_context('Make a silent papercut explainer about tides', inspect)

    async def test_native_context_lists_every_safe_style_without_selecting_a_render(self):
        def inspect(context):
            self.assertEqual(context['intent_route']['skill'], 'art-style-motion')
            catalog = context['style_catalog']
            self.assertEqual((catalog['mode'], catalog['total']), ('browse', 141))
            self.assertIsNone(catalog['selected'])
            self.assertEqual(len(catalog['matches']), 141)
            self.assertEqual(len({row['slug'] for row in catalog['matches']}), 141)
            self.assertNotIn('source_path', json.dumps(catalog))
            self.assertNotIn('film-look', json.dumps(catalog))
            self.assertTrue(all(set(row) == {'slug', 'name', 'category', 'dimension', 'typical_uses'}
                                for row in catalog['matches']))

        await self.read_context('Show me the available film-look styles', inspect)

    async def test_unrelated_native_context_does_not_include_catalog(self):
        def inspect(context):
            self.assertEqual(context['intent_route']['skill'], 'knowledge-explainer')
            self.assertNotIn('style_catalog', context)

        await self.read_context('Make a silent explainer about stained glass manufacture', inspect)


class ArtCatalogSelectionTests(unittest.TestCase):
    def test_named_style_clauses_are_not_video_titles(self):
        from agent.deep_agent.art_style_catalog import style_context
        from agent.deep_agent.routing import route_intent

        for prompt in [
            'Make an animation in the style called Stained Glass',
            'Make a silent explainer using a style called Stained Glass',
            'Make an animation using a look named Stained Glass',
        ]:
            with self.subTest(prompt=prompt):
                self.assertEqual(style_context(prompt)['selected']['slug'], 'stained-glass')
                self.assertEqual(route_intent(prompt).skill, 'art-style-motion')

    def test_papercut_titles_and_negated_looks_do_not_select_a_style(self):
        from agent.deep_agent.art_style_catalog import style_context

        for prompt in [
            'Make a silent explainer titled Papercut explainer',
            'Make a silent explainer called Papercut animation',
            'Make a silent explainer, not in papercut style',
        ]:
            with self.subTest(prompt=prompt):
                self.assertIsNone(style_context(prompt)['selected'])
        self.assertEqual(style_context('Make an animated video titled Papercut explainer '
                                       'using stained glass style')['selected']['slug'], 'stained-glass')

    def test_named_style_later_in_full_length_brief_is_selected(self):
        from agent.deep_agent.art_style_catalog import style_context

        context = style_context('Make an animated short. ' + 'Detail. ' * 80 + 'Use stained glass style.')
        self.assertEqual(context['selected']['slug'], 'stained-glass')

    def test_title_subject_and_excluded_style_are_not_selected(self):
        from agent.deep_agent.art_style_catalog import style_context

        for prompt in ['Make an explainer titled "Stained Glass"',
                       'Use "Stained Glass" as the title for an explainer',
                       'Make an explainer about stained glass manufacture',
                       'Make an explainer; do not use stained glass style',
                       "Make an explainer; don't use stained glass style",
                       'Make an explainer; avoid stained glass and risograph styles']:
            with self.subTest(prompt=prompt):
                self.assertIsNone(style_context(prompt)['selected'])

    def test_quoted_positive_style_selection_is_still_explicit(self):
        from agent.deep_agent.art_style_catalog import style_context

        context = style_context('Make an animation using "Stained Glass" style')
        self.assertEqual(context['selected']['slug'], 'stained-glass')

    def test_unverified_source_slug_alias_is_input_only(self):
        from agent.deep_agent.art_style_catalog import select_style

        result = select_style('hd-2d')
        self.assertEqual(result['selected']['slug'], 'pixel-sprites-with-depth')
        self.assertNotIn('hd-2d', json.dumps(result).lower())

    def test_input_only_alias_search_finds_the_safe_card(self):
        from agent.deep_agent.art_style_catalog import search_styles

        for alias, slug in [('risograph', 'stencil-ink-print'), ('hd-2d', 'pixel-sprites-with-depth')]:
            with self.subTest(alias=alias):
                rows = search_styles(alias, limit=1)
                self.assertEqual(rows[0]['slug'], slug)
                self.assertNotIn(alias, json.dumps(rows).lower())

    def test_specific_catalog_name_wins_over_a_partial_builtin_name(self):
        from agent.deep_agent.art_style_catalog import style_context

        result = style_context('Make an animation in Backlit Gothic Stained Glass style')
        self.assertEqual(result['selected']['slug'], 'backlit-gothic-stained-glass')
        self.assertEqual(result['basis'], 'explicit style')

    def test_builtin_request_wins_over_catalog_default(self):
        from agent.deep_agent.art_style_catalog import select_style

        result = select_style('Bauhaus', default_slug='stencil-ink-print')
        self.assertEqual(result['selected']['slug'], 'geometric-primary-colors')
        self.assertEqual(result['basis'], 'explicit built-in style')


if __name__ == '__main__':
    unittest.main()
