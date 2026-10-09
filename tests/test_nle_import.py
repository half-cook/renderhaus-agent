from __future__ import annotations

import copy
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

import opentimelineio as otio

from providers.nle.formats import fcpxml_text, media_paths, otio_text
from providers.nle.model import parse_snapshot
from providers.registry import dispatch, generate_schemas, load_committed_schemas
from providers.catalog import get_provider
from test_nle_export import snapshot

FIXTURES = Path(__file__).parent / 'fixtures' / 'nle_import'


def exported(current, format):
    timeline = parse_snapshot(current)
    return (fcpxml_text if format == 'fcpxml' else otio_text)(timeline, media_paths(timeline))


def import_edit(text, current, format):
    from providers.nle.importer import import_timeline
    return import_timeline(text, current, format)


class NleImportTests(unittest.TestCase):
    def test_roundtrip_preserves_normalized_tracks_and_pinned_assets(self):
        for fps, df in [(24, False), (25, False), ('30000/1001', True)]:
            for format in ('fcpxml', 'otio'):
                with self.subTest(fps=fps, format=format):
                    current = snapshot(fps, df)
                    before = copy.deepcopy(current)
                    expected = parse_snapshot(current)
                    result = import_edit(exported(current, format), current, format)
                    self.assertEqual(result['status'], 'succeeded')
                    self.assertEqual(result['unmatched_media'], [])
                    actual = parse_snapshot(result['timeline'])
                    self.assertEqual(actual.tracks, expected.tracks)
                    self.assertEqual(actual.assets, expected.assets)
                    self.assertEqual(actual.duration, expected.duration)
                    self.assertEqual(actual.start_frame, expected.start_frame)
                    self.assertEqual(current, before)

    def test_fcpxml_versions_and_connected_lane_source_coordinates(self):
        for version in ('1.9', '1.10', '1.11'):
            current = snapshot()
            root = ET.fromstring(exported(current, 'fcpxml'))
            root.set('version', version)
            result = import_edit(ET.tostring(root, encoding='unicode'), current, 'fcpxml')
            self.assertEqual(result['status'], 'succeeded')
            clips = {c['id']: c for t in result['timeline']['document']['tracks'] for c in t['items']}
            self.assertEqual(clips['generated-clip']['start'], 1)
            self.assertEqual(clips['camera-clip']['sourceIn'], 1)

    def test_editor_fixtures_trim_reorder_delete_and_add_markers(self):
        for format in ('fcpxml', 'otio'):
            result = import_edit((FIXTURES / f'edited.{format}').read_text(), snapshot(), format)
            self.assertEqual(result['status'], 'succeeded')
            doc = result['timeline']['document']
            clips = [c for t in doc['tracks'] for c in t['items']]
            self.assertEqual([c['id'] for c in clips], ['generated-clip'])
            self.assertEqual(clips[0]['start'], 0)
            self.assertEqual(clips[0]['duration'], 0.5)
            self.assertEqual(clips[0]['sourceIn'], 0.5)
            self.assertEqual(clips[0]['markers'][0]['name'], 'Review this cut')
            self.assertEqual(clips[0]['markers'][0]['start'], 0.25)
            self.assertEqual(doc['tracks'][0]['id'], 'renderhaus-generated-d804c07f273fb64d')

    def test_otio_ignores_stale_timing_metadata_after_reorder(self):
        current = snapshot()
        current['document']['assets'][1]['generated'] = False
        timeline = otio.adapters.read_from_string(exported(current, 'otio'), 'otio_json')
        first, second = timeline.tracks[0][:2]
        timeline.tracks[0][0], timeline.tracks[0][1] = second, first
        result = import_edit(otio.adapters.write_to_string(timeline, 'otio_json'), current, 'otio')
        clips = result['timeline']['document']['tracks'][0]['items']
        self.assertEqual([c['assetId'] for c in clips], ['generated', 'camera'])
        self.assertEqual([c['start'] for c in clips], [0, 1])

    def test_filename_and_full_duration_fallback_is_unique(self):
        current = snapshot()
        root = ET.fromstring(exported(current, 'fcpxml'))
        for metadata in root.findall('.//metadata'):
            for item in list(metadata):
                if item.get('key') in {'com.renderhaus.assetId', 'com.renderhaus.versionId'}:
                    metadata.remove(item)
        for asset, old in zip(root.findall('./resources/asset'), current['document']['assets']):
            asset.find('media-rep').set('src', 'file:///editor/' + old['url'])
        result = import_edit(ET.tostring(root, encoding='unicode'), current, 'fcpxml')
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(result['matched_by']['filename_duration'], 2)

    def test_missing_ambiguous_and_conflicting_identity_never_guess(self):
        for mode in ('missing', 'ambiguous', 'conflict'):
            current = snapshot()
            root = ET.fromstring(exported(current, 'fcpxml'))
            if mode == 'ambiguous':
                duplicate = copy.deepcopy(current['document']['assets'][0])
                duplicate['id'] = 'duplicate'
                current['document']['assets'].append(duplicate)
            for item in root.findall('.//md'):
                if item.get('key') == 'com.renderhaus.assetId':
                    item.set('value', 'unknown' if mode == 'missing' else 'camera')
                if item.get('key') == 'com.renderhaus.versionId' and mode == 'conflict':
                    item.set('value', 'other-version')
            if mode == 'ambiguous':
                for metadata in root.findall('.//metadata'):
                    for item in list(metadata):
                        if item.get('key') in {'com.renderhaus.assetId', 'com.renderhaus.versionId'}:
                            metadata.remove(item)
                root.find('./resources/asset/media-rep').set('src', 'camera.mp4')
            result = import_edit(ET.tostring(root, encoding='unicode'), current, 'fcpxml')
            self.assertEqual(result['status'], 'blocked')
            self.assertTrue(result['unmatched_media'])
            self.assertIsNone(result['timeline'])

    def test_no_media_reference_is_fetched_or_opened(self):
        current = snapshot()
        root = ET.fromstring(exported(current, 'fcpxml'))
        root.find('./resources/asset/media-rep').set('src', 'https://example.invalid/media?token=private')
        with patch('httpx.Client', side_effect=AssertionError('network')), patch('boto3.Session', side_effect=AssertionError('AWS')):
            result = import_edit(ET.tostring(root, encoding='unicode'), current, 'fcpxml')
        self.assertEqual(result['status'], 'succeeded')
        self.assertNotIn('private', json.dumps(result))
        self.assertEqual(result['timeline']['document']['assets'], current['document']['assets'])

    def test_rejects_malformed_hostile_and_oversized_inputs(self):
        cases = ['<fcpxml>', '<!DOCTYPE fcpxml SYSTEM "file:///etc/passwd"><fcpxml version="1.9"/>',
                 '<!DOCTYPE fcpxml [<!ENTITY x "boom">]><fcpxml>&x;</fcpxml>',
                 '<fcpxml version="1.8"/>', '<xmeml/>', '<fcpxml>' + ' ' * (2 * 1024 * 1024) + '</fcpxml>',
                 '<fcpxml version="1.9">' + '<gap>' * 100 + '</gap>' * 100 + '</fcpxml>']
        for text in cases:
            with self.subTest(text=text[:80]), self.assertRaises(ValueError):
                import_edit(text, snapshot(), 'fcpxml')
        for text in ('{', '{"x": NaN}', '[' * 1000 + ']' * 1000):
            with self.subTest(text=text[:30]), self.assertRaises(ValueError):
                import_edit(text, snapshot(), 'otio')

    def test_unsupported_effects_and_multicam_block_complete_import(self):
        current = snapshot()
        for tag in ('timeMap', 'filter-video', 'mc-clip'):
            root = ET.fromstring(exported(current, 'fcpxml'))
            ET.SubElement(root.find('.//asset-clip'), tag)
            result = import_edit(ET.tostring(root, encoding='unicode'), current, 'fcpxml')
            self.assertEqual(result['status'], 'blocked')
            self.assertTrue(result['unsupported'])
            self.assertIsNone(result['timeline'])

    def test_invalid_source_window_and_rate_mismatch_rejected(self):
        current = snapshot()
        root = ET.fromstring(exported(current, 'fcpxml'))
        root.find('.//asset-clip').set('start', '99s')
        with self.assertRaises(ValueError):
            import_edit(ET.tostring(root, encoding='unicode'), current, 'fcpxml')
        root = ET.fromstring(exported(current, 'fcpxml'))
        root.find('./resources/format').set('frameDuration', '1/25s')
        with self.assertRaises(ValueError):
            import_edit(ET.tostring(root, encoding='unicode'), current, 'fcpxml')

    def test_deleting_all_clips_is_a_valid_empty_edit(self):
        current = snapshot()
        timeline = otio.adapters.read_from_string(exported(current, 'otio'), 'otio_json')
        for track in timeline.tracks:
            track.clear()
        result = import_edit(otio.adapters.write_to_string(timeline, 'otio_json'), current, 'otio')
        self.assertEqual(result['status'], 'succeeded')
        self.assertTrue(all(not t['items'] for t in result['timeline']['document']['tracks']))

    def test_gateway_dry_run_contract_local_lambda_and_cost(self):
        from lambdas.handler import handler
        from server.billing_rates import cost_for
        from agent.deep_agent.routing import estimate_cost, is_free_tool
        from agent.gateway_executor import APPROVAL_EXEMPT_TOOLS, tool_needs_approval

        current = snapshot()
        args = {'interchange_text': exported(current, 'fcpxml'), 'timeline_json': json.dumps(current), 'format': 'fcpxml'}
        spec = get_provider('remotion')
        self.assertEqual(generate_schemas(spec), load_committed_schemas(spec))
        with patch.dict(os.environ, {'REMOTION_DRY_RUN': 'true'}):
            result = dispatch('remotion', 'import_nle_timeline', args)
            self.assertEqual(result['status'], 'dry_run')
            with self.assertRaises(ValueError):
                dispatch('remotion', 'import_nle_timeline', {**args, 'format': 'edl'})
            with self.assertRaises(ValueError):
                dispatch('remotion', 'import_nle_timeline', {**args, 'interchange_text': '<broken'})
        with patch.dict(os.environ, {'REMOTION_DRY_RUN': 'false', 'RENDERHAUS_PROVIDER': 'remotion'}), patch('httpx.Client', side_effect=AssertionError('network')), patch('boto3.Session', side_effect=AssertionError('AWS')):
            local = dispatch('remotion', 'import_nle_timeline', args)
            remote = handler({'_tool_name': 'import_nle_timeline', **args}, None)
            self.assertEqual(local, remote)
            self.assertEqual(local['status'], 'succeeded')
        name = 'Remotion___import_nle_timeline'
        self.assertEqual(cost_for('remotion', 'import_nle_timeline', args).total_cents, 0)
        self.assertEqual(estimate_cost(name, args).total_cents, 0)
        self.assertTrue(is_free_tool(name))
        self.assertFalse(tool_needs_approval(name, True))
        self.assertFalse(tool_needs_approval(name, False))
        self.assertEqual(APPROVAL_EXEMPT_TOOLS, frozenset({'Remotion___export_nle_timeline'}))

    def test_routing_import_and_export_remain_distinct(self):
        from agent.deep_agent.routing import route_intent, resolve_alias
        for prompt in ('import editor FCPXML back', 'import OTIO timeline', 'roundtrip my edit'):
            route = route_intent(prompt)
            self.assertEqual(route.skill, 'resolve-handoff')
            self.assertEqual(route.tool, 'Remotion___import_nle_timeline')
            self.assertEqual(route.status, 'ready')
        self.assertEqual(resolve_alias('nle_import'), 'Remotion___import_nle_timeline')
        self.assertEqual(route_intent('export FCPXML').tool, 'Remotion___export_nle_timeline')
