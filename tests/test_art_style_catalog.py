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
        self.assertEqual(self.source['sha256']['styleboard/opuscar98_styles.json'],
                         'd20b2ea8600f55c1fc1e06393178ba945db8f86d2cd86ae1abb2d82fe6b503c6')
        for path in guides:
            self.assertTrue(json.loads(files[path])['slug'])
        dimensions = [film['render'] for film in board['films']]
        self.assertEqual([dimensions.count(tag) for tag in ['2D', '2.5D', '3D']], [77, 4, 17])
        self.assertEqual(len({film['prompt_en'] for film in board['films']}), 98)
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
        combined = '\n'.join(strings(self.index['styles']))
        for term in terms:
            boundary = r'(?<!\w)' + re.escape(term) + r'(?!\w)' if term.isascii() else re.escape(term)
            self.assertIsNone(re.search(boundary, combined, re.I), term)
        for value in strings(self.index['styles']):
            self.assertNotRegex(value, r'(?i)\b(?:fee|usd|pricing|price per)\b|\$\s*\d')
        self.assertEqual(self.scan['remaining_public_matches'], [])
        self.assertTrue(any(match['term'] == 'Clawd' for match in self.scan['source_matches']))
        self.assertTrue(self.scan['scrubs'])
        self.assertEqual(self.scan['scrubbed_styles'], len({s['slug'] for s in self.scan['scrubs']}))
        for scrub in self.scan['scrubs']:
            self.assertNotEqual(scrub['before'], scrub['after'])

    def test_verbatim_source_and_scan_are_outside_agent_skill_filesystem(self):
        skills = ROOT / 'agent/deep_agent/skills'
        self.assertFalse(PROVENANCE.is_relative_to(skills))
        for path in CATALOG.rglob('*'):
            self.assertNotIn(path.name, {'source.json', 'BRAND_SCAN.json'})

    def test_catalog_data_and_licence_are_packaged(self):
        import tomllib

        config = tomllib.loads((ROOT / 'pyproject.toml').read_text())['tool']['setuptools']
        package_root = ROOT / 'agent/deep_agent'
        included = {path for glob in config['package-data']['agent.deep_agent'] for path in package_root.glob(glob)}
        self.assertTrue({CATALOG / 'index.json', CATALOG / 'LICENSE'} <= included)
        self.assertIn('third_party/lemo-opuscar/LICENSE', config['license-files'])

    def test_builtin_display_and_prompt_cards_are_neutral(self):
        terms = self.scan['deny_terms']
        references = CATALOG.parent
        table = '\n'.join(line for name in ['style-cards.md', 'grammar-cards.md']
                          for line in (references / name).read_text().splitlines() if line.startswith('| '))
        for term in terms:
            boundary = r'(?<!\w)' + re.escape(term) + r'(?!\w)' if term.isascii() else re.escape(term)
            self.assertIsNone(re.search(boundary, table, re.I), term)

    def test_catalog_rebuild_has_no_drift(self):
        from scripts.import_art_style_catalog import build

        index, scan = build()
        self.assertEqual(index, self.index)
        self.assertEqual(scan, self.scan)

    def test_palette_descriptions_survive_name_scrubbing(self):
        row = next(row for row in self.index['styles'] if row['slug'] == 'stained-glass')
        self.assertIn('cobalt ground, deep red, touches of gold', row['style_prompt'])
        self.assertNotIn('still experience', '\n'.join(strings(self.index['styles'])))
        self.assertRegex('\n'.join(strings(self.index['styles'])), r'#[0-9A-Fa-f]{6}\b')

    def test_source_brand_and_person_references_are_denied_even_in_avoidance_notes(self):
        combined = '\n'.join(strings(self.index['styles']))
        for term in ['LEGO', 'minifigure', 'Chaplin', 'NES', 'ENDESGA', 'Krackle',
                     'Pollock', 'Mickey', 'VT323', 'B612', 'minifig']:
            with self.subTest(term=term):
                self.assertTrue(term in self.scan['deny_terms'], term)
                self.assertIsNone(re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', combined, re.I), term)

    def test_ordinary_movement_and_halftone_terms_survive_short_name_collisions(self):
        rows = {row['slug']: row for row in self.index['styles']}
        self.assertIn('small vertical bounce', ' '.join(rows['brick-toy']['shot_direction_notes']))
        self.assertIn('body bounce', ' '.join(rows['rubber-hose']['shot_direction_notes']))
        self.assertIn('head bounce', ' '.join(rows['liminal-found-footage']['shot_direction_notes']))
        self.assertIn('boats rise and fall', ' '.join(rows['lowpoly-island']['shot_direction_notes']))
        self.assertIn('pitched chime', ' '.join(rows['game-show']['shot_direction_notes']))
        self.assertIn('45° halftone dots', rows['four-color-energy-comics']['style_prompt'])


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

    def test_inference_requires_descriptive_metadata_but_search_keeps_prose_matches(self):
        from agent.deep_agent.art_style_catalog import search_styles, select_style, style_context

        for query in ['composition', 'palette choice', 'silhouettes', '30']:
            with self.subTest(query=query):
                self.assertTrue(search_styles(query))
                self.assertIsNone(select_style(query)['selected'])
                self.assertIsNone(style_context(query)['selected'])

        description = 'Make an animated short with grainy urban textures'
        for result in [select_style(description), style_context(description)]:
            self.assertEqual(result['selected']['slug'], 'grainy-urban-chase')
            self.assertEqual(result['basis'], 'described look')

    def test_empty_query_lists_bounded_results_and_unknown_does_not_invent_match(self):
        from agent.deep_agent.art_style_catalog import search_styles, select_style

        for query in ['', ' \t\n ']:
            self.assertEqual(len(search_styles(query, limit=5)), 5)
        self.assertEqual(search_styles('zzzznonexistentzzzz'), [])
        self.assertIsNone(select_style('zzzznonexistentzzzz')['selected'])

    def test_nonempty_queries_without_supported_tokens_do_not_list_styles(self):
        from agent.deep_agent.art_style_catalog import search_styles

        for query in ['完全不存在', '???']:
            with self.subTest(query=query):
                self.assertEqual(search_styles(query), [])

    def test_excluded_described_looks_are_not_inferred(self):
        from agent.deep_agent.art_style_catalog import search_styles, select_style, style_context

        for prompt in [
            'Make an animated short without grainy urban textures',
            'Make an animated short; avoid grainy urban textures',
            'Make an animated short; do not use grainy urban textures',
            'Make an animated short without grainy textures in an urban scene',
        ]:
            with self.subTest(prompt=prompt):
                for result in [select_style(prompt), style_context(prompt)]:
                    self.assertNotEqual((result['selected'] or {}).get('slug'), 'grainy-urban-chase')

        prompt = 'Make an animated short without grainy urban textures but with backlit leaded colored glass'
        for result in [select_style(prompt), style_context(prompt)]:
            self.assertEqual(result['selected']['slug'], 'stained-glass')
        self.assertEqual(search_styles('without grainy urban textures', limit=1)[0]['slug'], 'grainy-urban-chase')
        prompt = 'Use Grainy Urban Chase style, without grainy urban textures'
        for result in [select_style(prompt), style_context(prompt)]:
            self.assertEqual(result['selected']['slug'], 'grainy-urban-chase')
            self.assertEqual(result['basis'], 'explicit style')

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

    def test_generic_style_questions_do_not_open_the_art_catalog(self):
        from agent.deep_agent.art_style_catalog import catalog_motion_request, style_context
        from agent.deep_agent.routing import route_intent

        for prompt in ['What styles of leadership work best for managers?',
                       'Which styles of CSS can I use for plain motion graphics titles?']:
            with self.subTest(prompt=prompt):
                self.assertFalse(catalog_motion_request(prompt))
                self.assertNotEqual(style_context(prompt)['mode'], 'browse')
                self.assertNotEqual(route_intent(prompt).skill, 'art-style-motion')

    def test_subject_lists_do_not_select_material_styles(self):
        from agent.deep_agent.art_style_catalog import style_context
        from agent.deep_agent.routing import route_intent

        for prompt, expected in [
            ('Make a silent explainer about art deco and stained glass history', 'knowledge-explainer'),
            ('Create an animated explainer about the history and manufacture of stained glass', 'i2v'),
        ]:
            with self.subTest(prompt=prompt):
                self.assertIsNone(style_context(prompt)['selected'])
                self.assertEqual(route_intent(prompt).skill, expected)
        selected = style_context('Make an explainer about stained glass history using Ukiyo-e Woodblock style')
        self.assertEqual(selected['selected']['slug'], 'ukiyo-e-woodblock')

    def test_using_and_use_inside_a_subject_do_not_request_a_style(self):
        from agent.deep_agent.art_style_catalog import select_style, style_context
        from agent.deep_agent.routing import route_intent

        for prompt in [
            'Make a silent explainer about using watercolor pigments',
            'Make a silent explainer about how to use stained glass panels',
            'Make a silent explainer about the use of stained glass',
            'Make a silent explainer about how to draw using stained glass panels',
            'Make a silent explainer about artists using watercolor pigments',
            'Make a silent explainer about factories using stained glass panels',
            'Make a silent explainer about artists using Bauhaus tools',
            'Make a silent explainer about tides, not in stained glass style',
            'Make a silent explainer about tides without using stained glass style',
        ]:
            with self.subTest(prompt=prompt):
                for result in [select_style(prompt), style_context(prompt)]:
                    self.assertIsNone(result['selected'])
                self.assertEqual(route_intent(prompt).skill, 'knowledge-explainer')

        for prompt, slug in [
            ('Make a silent explainer about tides using stained glass', 'stained-glass'),
            ('Make a silent explainer about using watercolor pigments. Use stained glass style.', 'stained-glass'),
            ('Make a silent explainer about tides in stained glass style', 'stained-glass'),
            ('Make a silent explainer about tides in the Stained Glass style', 'stained-glass'),
            ('Make a silent explainer about tides using Stained Glass look', 'stained-glass'),
            ('Make a silent explainer about tides using HD-2D grammar', 'pixel-sprites-with-depth'),
            ('Make a silent explainer about tides using Bauhaus', 'geometric-primary-colors'),
            ('Make a silent explainer about artists using Bauhaus style', 'geometric-primary-colors'),
        ]:
            with self.subTest(prompt=prompt):
                for result in [select_style(prompt), style_context(prompt)]:
                    self.assertEqual(result['selected']['slug'], slug)
                self.assertEqual(route_intent(prompt).skill, 'art-style-motion')

    def test_a_topic_or_duration_does_not_infer_a_catalog_look(self):
        from agent.deep_agent.art_style_catalog import select_style, style_context

        for prompt in [
            'Use art-style-motion for a 30-second animated short about tides',
            'Use art-style-motion for a one-minute long animated short about tides',
            'Use art-style-motion for an 80s animated short about tides',
            'Use art-style-motion to explain palette choice',
            'Use art-style-motion to explain composition',
            'Use art-style-motion to explain silhouettes',
        ]:
            with self.subTest(prompt=prompt):
                self.assertIsNone(style_context(prompt)['selected'])
                self.assertIsNone(select_style(prompt)['selected'])

        for prompt in ['Make an animated short with backlit leaded colored glass',
                       'Make an animated short with translucent watercolor washes']:
            self.assertIsNotNone(style_context(prompt)['selected'])

    def test_existing_named_style_after_the_topic_is_preserved_in_host_context(self):
        from agent.deep_agent.art_style_catalog import style_context

        selected = style_context('Make an animated explainer about coral reefs in Bauhaus style')
        self.assertEqual(selected['selected']['slug'], 'geometric-primary-colors')


if __name__ == '__main__':
    unittest.main()
