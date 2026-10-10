from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'providers/shot_recipes'
FORBIDDEN = {'.mp3', '.wav', '.ogg', '.m4a', '.mp4', '.webm', '.mov', '.gif',
             '.png', '.jpg', '.jpeg', '.svg', '.tsx', '.ts', '.js', '.woff', '.ttf'}
BRANDS = ('Mixkit', 'Firecrawl', 'Willow Voice', 'Honor', 'Apple', 'CapCut',
          'Jianying', 'Seedance', 'Wan', 'ElevenLabs', 'Mureka', 'fal.ai', 'platform fee')


def storyboard():
    return {
        'target_duration_s': 6, 'aspect': '16:9', 'fps': 30,
        'beat_grid_s': [0, 3, 6],
        'beats': [
            {'beat': 'reveal', 'card_id': 'brand-ink-open', 'start_s': 0,
             'duration_s': 3, 'sfx_cue': 'impact', 'selection': 'user_named'},
            {'beat': 'cta', 'card_id': 'brand-ink-open', 'start_s': 3,
             'duration_s': 3, 'sfx_cue': 'transition', 'cut_snap': 3},
        ],
        'named_cards': {'reveal': 'brand-ink-open'},
        'audio_stems': {'sfx': [], 'music': [], 'vo': []},
    }


class CardImportTests(unittest.TestCase):
    def test_card_library_integrity_and_provenance(self):
        from providers.shot_recipes.library import load_index, parse_card

        cards = list((DATA / 'cards').glob('*/*.md'))
        self.assertEqual(len(cards), 157)
        index = load_index()
        self.assertEqual(len(index), 157)
        self.assertEqual({p.stem for p in cards}, set(index))
        for path in cards:
            with self.subTest(card=path.stem):
                front = yaml.safe_load(path.read_text().split('---', 2)[1])
                self.assertEqual(front['name'], path.stem)
                self.assertTrue({'一句话', '适用', '时长', '能量', '标签'} <= front.keys())
                entry = index[path.stem]
                self.assertEqual(entry['category'], path.parent.name)
                self.assertEqual(entry['source_path'], f'references/shots/{path.parent.name}/{path.name}')
                self.assertEqual(entry['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertTrue(entry['summary'].isascii())
                self.assertTrue(entry['keywords'])
                self.assertTrue(parse_card(path.stem)['parameter_table'])
        for name in ('LICENSE', 'NOTICE.md', 'ATTRIBUTION.md'):
            self.assertTrue((DATA / name).is_file(), name)
        notice = (DATA / 'NOTICE.md').read_text()
        self.assertIn('5ddbf52', notice)
        self.assertIn('unmodified', notice)
        self.assertIn('derivative metadata', (DATA / 'index.json').read_text())

    def test_data_contains_no_audio_media_code_or_symlinks(self):
        self.assertTrue(DATA.is_dir())
        for path in DATA.rglob('*'):
            self.assertFalse(path.is_symlink(), path)
            self.assertNotIn(path.suffix.lower(), FORBIDDEN, path)
            if path.is_file():
                self.assertLess(path.stat().st_size, 1024 * 1024)


class SearchTests(unittest.TestCase):
    def search(self, **kwargs):
        from providers.shot_recipes.api import shot_recipe_search

        with patch('socket.create_connection', side_effect=AssertionError('network forbidden')):
            return shot_recipe_search(**kwargs)

    def test_exact_id_wins_over_query_and_filters(self):
        result = self.search(card_id='brand-ink-open', query='odometer', category='camera',
                             max_duration_s=1, energy='high')
        self.assertTrue(result['ok'])
        self.assertEqual(result['results'][0]['id'], 'brand-ink-open')
        self.assertTrue(result['recipe']['intent'])
        self.assertTrue(result['recipe']['parameter_table'])
        self.assertTrue(result['recipe']['known_pitfalls'])
        self.assertTrue(result['recipe']['timing'])

    def test_alias_search_and_stable_ranking(self):
        self.assertEqual(self.search(query='ink press')['results'][0]['id'], 'brand-ink-open')
        self.assertEqual(self.search(query='INK PRESS'), self.search(query='ink press'))
        for query in ('crane reveal', 'odometer', 'camera'):
            result = self.search(query=query)
            self.assertTrue(result['results'], query)
            self.assertEqual(result, self.search(query=query))
        self.assertLessEqual(len(self.search(limit=20)['results']), 20)

    def test_filters_and_empty_match(self):
        result = self.search(category='opening', max_duration_s=10, energy='low')
        self.assertTrue(result['ok'])
        self.assertTrue(result['results'])
        for card in result['results']:
            self.assertEqual(card['category'], 'opening')
            self.assertLessEqual(card['duration_s'], 10)
            self.assertEqual(card['energy'], 'low')
        self.assertEqual(self.search(query='zzzznevermatching')['results'], [])

    def test_bounds_types_traversal_and_unknown_id(self):
        for arguments in ({'limit': 21}, {'limit': 0}, {'limit': True}, {'limit': '3'},
                          {'query': 'x' * 513}, {'card_id': '../LICENSE'},
                          {'card_id': '/etc/passwd'}, {'energy': 'very high'},
                          {'category': 'unknown'}, {'max_duration_s': float('nan')},
                          {'max_duration_s': -1}, {'mode': 'render'}):
            with self.subTest(arguments=arguments):
                result = self.search(**arguments)
                self.assertFalse(result['ok'])
                self.assertTrue(result['errors'])
        result = self.search(card_id='brand-ink-opne')
        self.assertFalse(result['ok'])
        self.assertIn('brand-ink-open', result['nearest_ids'])

    def test_neutral_output_for_all_cards(self):
        from providers.shot_recipes.library import load_index

        for card_id in load_index():
            with self.subTest(card=card_id):
                text = json.dumps(self.search(card_id=card_id), ensure_ascii=False).lower()
                for brand in BRANDS:
                    self.assertNotIn(brand.lower(), text)
                self.assertNotIn('参考实现', text)
                self.assertNotIn('.tsx', text)


class StoryboardTests(unittest.TestCase):
    def validate(self, value):
        from providers.shot_recipes.storyboard import validate_storyboard

        return validate_storyboard(value)

    def test_valid_plan_has_separate_stems_and_render_arguments(self):
        result = self.validate(storyboard())
        self.assertTrue(result['ok'], result)
        plan = result['render_plan']
        self.assertEqual(set(plan['audio_stems']), {'sfx', 'music', 'vo'})
        self.assertEqual(plan['render_args']['aspect_ratio'], '16:9')
        self.assertEqual(plan['render_args']['fps'], 30)
        self.assertEqual(plan['render_args']['audio_tracks'], [])
        self.assertEqual(plan['loudness_target'], {'integrated_lufs': -14, 'tolerance_lu': 1})
        self.assertTrue(any('empty SFX stem' in n for n in result['warnings']))

    def test_rejects_unknown_cards_duration_and_noncontiguous_beats(self):
        mutations = [
            lambda s: s['beats'][0].update(card_id='missing-card'),
            lambda s: s.update(target_duration_s=10),
            lambda s: s['beats'][1].update(start_s=4),
            lambda s: s['beats'][1].update(duration_s=-1),
            lambda s: s['beats'][0].update(sfx_cue='audio/impact.wav'),
            lambda s: s.update(fps=0),
            lambda s: s.update(beat_grid_s=[]),
            lambda s: s['beats'][1].update(cut_snap=4),
            lambda s: s['beats'][1].update(start_s=float('nan')),
            lambda s: s.update(audio_stems={'mixed': []}),
            lambda s: s['beats'][0].update(selection='agent'),
            lambda s: s['named_cards'].update(reveal='crane-reveal'),
        ]
        for mutate in mutations:
            value = storyboard()
            mutate(value)
            with self.subTest(value=value):
                result = self.validate(value)
                self.assertFalse(result['ok'], result)
                self.assertTrue(result['errors'])

    def test_frame_tolerance_and_duration_tolerance(self):
        value = storyboard()
        value['beat_grid_s'][1] = 3 + 1 / 30
        self.assertTrue(self.validate(value)['ok'])
        value['beat_grid_s'][1] += .001
        self.assertFalse(self.validate(value)['ok'])
        value = storyboard()
        value['target_duration_s'] = 6 / .95
        self.assertTrue(self.validate(value)['ok'])
        value['target_duration_s'] += .01
        self.assertFalse(self.validate(value)['ok'])

    def test_snap_is_pure_deterministic_and_frames_are_integral(self):
        from providers.shot_recipes.storyboard import snap_cut

        self.assertEqual(snap_cut(2.98, [0, 3, 6], 30), 3)
        self.assertEqual(snap_cut(2.5, [2, 3], 30), 2)
        value = storyboard()
        saved = copy.deepcopy(value)
        self.assertEqual(self.validate(value), self.validate(value))
        self.assertEqual(value, saved)

    def test_gateway_validation_mode_returns_the_same_plan(self):
        from providers.shot_recipes.api import shot_recipe_search

        self.assertEqual(shot_recipe_search(mode='validate_storyboard', storyboard=storyboard()),
                         self.validate(storyboard()))


class ShotGatewayTests(unittest.TestCase):
    def test_schema_registry_contract_and_free_approval_parity(self):
        from agent.deep_agent.routing import estimate_cost, is_free_tool, resolve_alias
        from agent.gateway_executor import tool_needs_approval
        from providers.catalog import get_provider
        from providers.registry import dispatch, generate_schemas, load_committed_schemas
        from server.billing_rates import cost_for

        spec = get_provider('shot_recipes')
        self.assertEqual(spec.target_name, 'ShotRecipes')
        self.assertEqual(spec.env_keys, ())
        self.assertEqual(generate_schemas(spec), load_committed_schemas(spec))
        self.assertEqual(resolve_alias('shot_recipe_search'), 'ShotRecipes___shot_recipe_search')
        for name in ('shot_recipe_search', 'ShotRecipes___shot_recipe_search'):
            self.assertTrue(is_free_tool(name))
            self.assertFalse(tool_needs_approval(name, False, {}))
            self.assertEqual(estimate_cost(name, {}).total_cents, 0)
        self.assertEqual(cost_for('shot_recipes', 'shot_recipe_search', {}).total_cents, 0)
        self.assertTrue(dispatch('shot_recipes', 'shot_recipe_search', {'query': 'ink press'})['ok'])
        for arguments in ({'limit': 21}, {'query': False}, {'card_id': '../x'}, {'extra': 1}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                dispatch('shot_recipes', 'shot_recipe_search', arguments)
        schema = generate_schemas(spec)[0]
        for brand in BRANDS:
            self.assertNotIn(brand.lower(), schema['description'].lower())


if __name__ == '__main__':
    unittest.main()
