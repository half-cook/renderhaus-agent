from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'agent/deep_agent/skills/art-style-motion/references/catalog'
PROVENANCE = ROOT / 'third_party/lemo-opuscar'


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


class CatalogIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.index = json.loads((CATALOG / 'index.json').read_text())
        self.source = json.loads((PROVENANCE / 'source.json').read_text())
        self.scan = json.loads((PROVENANCE / 'BRAND_SCAN.json').read_text())

    def test_all_source_records_reconcile_and_original_text_is_hash_verified(self):
        files = self.source['files']
        board = json.loads(files['styleboard/opuscar98_styles.json'])
        guides = [path for path in files if path.endswith('/style.json')]
        self.assertEqual((len(board['films']), len(guides), len(files)), (98, 43, 130))
        self.assertFalse(any('_template' in path for path in files))
        for path, original in files.items():
            self.assertEqual(hashlib.sha256(original.encode()).hexdigest(), self.source['sha256'][path], path)
        counts = self.index['counts']
        self.assertEqual(counts['film_prompts'], 98)
        self.assertEqual(counts['style_guides'], 43)
        self.assertEqual(len(self.index['styles']), 141 - counts['exact_duplicates'])
        links = self.scan['source_mapping']
        self.assertEqual(len(links), 141)
        self.assertEqual(set(links.values()), {row['slug'] for row in self.index['styles']})

    def test_every_style_is_neutral_and_complete(self):
        rows = self.index['styles']
        self.assertEqual(len({r['slug'] for r in rows}), len(rows))
        self.assertEqual(len({r['name'] for r in rows}), len(rows))
        for row in rows:
            self.assertEqual(set(row), {'slug', 'name', 'category', 'dimension', 'style_prompt',
                                       'shot_direction_notes', 'typical_uses', 'keywords', 'aliases'})
            self.assertRegex(row['slug'], r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
            self.assertIn(row['dimension'], {'2D', '2.5D', '3D'})
            for field in ['name', 'category', 'style_prompt', 'shot_direction_notes', 'typical_uses', 'keywords']:
                self.assertTrue(row[field], (row['slug'], field))
            self.assertGreater(len(row['style_prompt']), 80)
        self.assertIn('derivative', self.index['metadata'].lower())

    def test_mit_notice_and_data_only_import(self):
        licence = (PROVENANCE / 'LICENSE').read_text()
        self.assertIn('Copyright (c) 2026 LemoLab', licence)
        self.assertIn('Permission is hereby granted, free of charge', licence)
        notice = (PROVENANCE / 'NOTICE.md').read_text()
        self.assertIn(self.source['commit'], notice)
        self.assertIn('https://github.com/lemomo-ai/lemo-opuscar', notice)
        self.assertIn('unmodified', notice)
        for directory in [CATALOG, PROVENANCE]:
            for path in directory.rglob('*'):
                if path.is_file():
                    self.assertIn(path.suffix, {'.json', '.md', ''}, path)
        self.assertEqual((CATALOG / 'LICENSE').read_bytes(), (PROVENANCE / 'LICENSE').read_bytes())

    def test_scan_deny_list_guards_every_public_and_prompt_field(self):
        terms = self.scan['deny_terms']
        files = self.source['files']
        board = json.loads(files['styleboard/opuscar98_styles.json'])
        self.assertTrue({f['title'] for f in board['films']} <= set(terms))
        self.assertTrue({f['zh'] for f in board['films']} <= set(terms))
        for value in strings(self.index['styles']):
            for term in terms:
                boundary = r'(?<!\w)' + re.escape(term) + r'(?!\w)' if term.isascii() else re.escape(term)
                self.assertIsNone(re.search(boundary, value, re.I), (term, value[:200]))
            self.assertNotRegex(value, r'(?i)\b(?:fee|usd|pricing|price per)\b|\$\s*\d')
        self.assertEqual(self.scan['remaining_public_matches'], [])
        self.assertTrue(self.scan['scrubs'])
        self.assertEqual(self.scan['scrubbed_styles'], len({s['slug'] for s in self.scan['scrubs']}))
        for scrub in self.scan['scrubs']:
            self.assertNotEqual(scrub['before'], scrub['after'])

    def test_verbatim_source_and_scan_are_outside_agent_skill_filesystem(self):
        skills = ROOT / 'agent/deep_agent/skills'
        self.assertFalse(PROVENANCE.is_relative_to(skills))
        for path in CATALOG.rglob('*'):
            self.assertNotIn(path.name, {'source.json', 'BRAND_SCAN.json'})


class CatalogLookupTests(unittest.TestCase):
    def test_exact_name_slug_and_alias_win_over_default(self):
        from agent.deep_agent.art_style_catalog import select_style

        for request in ['stained-glass', 'Stained Glass', 'leaded glass']:
            result = select_style(request, default_slug='stencil-ink-print')
            self.assertEqual(result['selected']['slug'], 'stained-glass')
            self.assertEqual(result['basis'], 'explicit style')

    def test_input_only_trademark_alias_is_never_echoed(self):
        from agent.deep_agent.art_style_catalog import select_style

        result = select_style('risograph')
        self.assertEqual(result['selected']['slug'], 'stencil-ink-print')
        self.assertNotIn('risograph', json.dumps(result).lower())

    def test_descriptive_look_and_ukiyo_e_are_searchable(self):
        from agent.deep_agent.art_style_catalog import search_styles

        self.assertEqual(search_styles('ukiyo-e woodblock', limit=1)[0]['slug'], 'ukiyo-e-woodblock')
        self.assertEqual(search_styles('backlit leaded colored glass', limit=1)[0]['slug'], 'stained-glass')

    def test_empty_query_lists_bounded_results_and_unknown_does_not_invent_match(self):
        from agent.deep_agent.art_style_catalog import search_styles, select_style

        self.assertEqual(len(search_styles('', limit=5)), 5)
        self.assertEqual(search_styles('zzzznonexistentzzzz'), [])
        self.assertIsNone(select_style('zzzznonexistentzzzz')['selected'])

    def test_lookup_is_deterministic_and_callers_cannot_mutate_catalog(self):
        from agent.deep_agent.art_style_catalog import search_styles

        first = search_styles('glass', limit=4)
        self.assertEqual(first, search_styles('glass', limit=4))
        first[0]['name'] = 'corrupt'
        first[0]['keywords'].append('corrupt')
        self.assertNotEqual(first, search_styles('glass', limit=4))

    def test_bounds_are_enforced_before_lookup(self):
        from agent.deep_agent.art_style_catalog import search_styles

        for limit in [0, -1, 21, True, 1.5]:
            with self.assertRaises(ValueError):
                search_styles('glass', limit=limit)
        with self.assertRaises(ValueError):
            search_styles('x' * 501)

    def test_user_named_builtin_style_wins_and_returns_a_neutral_label(self):
        from agent.deep_agent.art_style_catalog import style_context

        result = style_context('Make a Bauhaus animation using the catalog')
        self.assertEqual(result['basis'], 'explicit built-in style')
        self.assertEqual(result['selected']['slug'], 'geometric-primary-colors')
        self.assertNotIn('bauhaus', json.dumps(result).lower())

    def test_catalog_listing_has_no_source_or_prompt_echo(self):
        from agent.deep_agent.art_style_catalog import style_context

        result = style_context('Show me the available film-look styles')
        self.assertEqual(result['mode'], 'browse')
        self.assertEqual(result['total'], 141)
        self.assertIsNone(result['selected'])
        self.assertEqual(len(result['matches']), 141)
        self.assertNotIn('source_path', json.dumps(result))
        self.assertNotIn('film-look', json.dumps(result))


class CatalogRoutingTests(unittest.TestCase):
    def test_catalog_requests_route_without_new_tools(self):
        from agent.deep_agent.routing import route_intent

        for prompt in [
            'Make a stained glass animated explainer with the catalog',
            'Make a risograph animated explainer with the catalog',
            'Make an ukiyo-e woodblock animated explainer with the catalog',
            'Show me the available film-look styles',
            'Make an animated short using Snowy Neon Night style from the catalog',
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual((route.skill, route.alias), ('art-style-motion', 'remotion_render'))

    def test_catalog_does_not_steal_existing_workflows_or_subject_mentions(self):
        from agent.deep_agent.routing import route_intent

        for prompt, expected in [
            ('Make a cinematic product promo for headphones', 'cinematic-product-promo'),
            ('Make a silent knowledge explainer about tides', 'knowledge-explainer'),
            ('Make plain motion graphics titles', 'motion-graphics'),
            ('Make a silent explainer about stained glass manufacture', 'knowledge-explainer'),
            ('Make a silent explainer; do not use stained glass style', 'knowledge-explainer'),
            ('Make a silent explainer titled "Stained Glass"', 'knowledge-explainer'),
        ]:
            with self.subTest(prompt=prompt):
                self.assertEqual(route_intent(prompt).skill, expected)


if __name__ == '__main__':
    unittest.main()
