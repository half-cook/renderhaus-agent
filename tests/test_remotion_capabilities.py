from __future__ import annotations

import copy
from dataclasses import replace
import unittest

from providers.catalog import get_provider
from providers.registry import generate_schemas


class CapabilityGuardTests(unittest.TestCase):
    def schemas(self):
        return generate_schemas(get_provider('remotion'))

    def test_committed_schema_and_skill_claims_match_capabilities(self):
        from scripts.ci_check import check_remotion_capabilities
        check_remotion_capabilities()

    def test_new_schema_field_without_capability_fails(self):
        from providers.remotion.capabilities import check_contract
        schemas = self.schemas()
        render = next(tool for tool in schemas if tool['name'] == 'render_timeline')
        render['inputSchema']['properties']['visuals']['items']['properties']['keyframes'] = {'type': 'array'}
        with self.assertRaisesRegex(AssertionError, 'keyframes'):
            check_contract(schemas, [])

    def test_removed_schema_field_still_in_table_fails(self):
        from providers.remotion.capabilities import check_contract
        schemas = self.schemas()
        render = next(tool for tool in schemas if tool['name'] == 'render_timeline')
        del render['inputSchema']['properties']['visuals']['items']['properties']['motion']
        with self.assertRaisesRegex(AssertionError, 'motion'):
            check_contract(schemas, [])

    def test_skill_claiming_local_only_feature_on_lambda_fails(self):
        from providers.remotion.capabilities import check_contract
        skill = {'name': 'bad', 'metadata': {'gateway_tools': 'Remotion___render_timeline',
                 'remotion_backend': 'lambda', 'remotion_features': 'crop_reframe'}}
        with self.assertRaisesRegex(AssertionError, 'crop_reframe.*lambda'):
            check_contract(self.schemas(), [skill])

    def test_skill_claiming_unknown_feature_fails(self):
        from providers.remotion.capabilities import check_contract
        skill = {'name': 'bad', 'metadata': {'gateway_tools': 'Remotion___render_timeline',
                 'remotion_backend': 'local', 'remotion_features': 'arbitrary_keyframes'}}
        with self.assertRaisesRegex(AssertionError, 'arbitrary_keyframes'):
            check_contract(self.schemas(), [skill])

    def test_backend_change_requires_schema_refusal_disclosure(self):
        from providers.remotion.capabilities import CAPABILITIES, check_contract
        changed = copy.copy(CAPABILITIES)
        changed['motion'] = replace(changed['motion'], local='refused-with-explicit-error')
        with self.assertRaisesRegex(AssertionError, 'motion'):
            check_contract(self.schemas(), [], capabilities=changed)

    def test_no_silently_ignored_features_are_allowed(self):
        from providers.remotion.capabilities import CAPABILITIES, check_contract
        changed = copy.copy(CAPABILITIES)
        changed['motion'] = replace(changed['motion'], local='unsupported-but-silently-ignored')
        with self.assertRaisesRegex(AssertionError, 'silently'):
            check_contract(self.schemas(), [], capabilities=changed)

    def test_nested_box_schema_drift_fails(self):
        from providers.remotion.capabilities import check_contract
        schemas = self.schemas()
        render = next(tool for tool in schemas if tool['name'] == 'render_timeline')
        render['inputSchema']['properties']['visuals']['items']['properties']['box']['properties']['keyframes'] = {'type': 'array'}
        with self.assertRaisesRegex(AssertionError, 'keyframes'):
            check_contract(schemas, [])

    def test_unsupported_motion_choice_in_schema_fails(self):
        from providers.remotion.capabilities import check_contract
        schemas = self.schemas()
        render = next(tool for tool in schemas if tool['name'] == 'render_timeline')
        motion = render['inputSchema']['properties']['visuals']['items']['properties']['motion']
        motion['description'] = motion['description'].replace('pan_right.', 'pan_right, bounce.', 1)
        with self.assertRaisesRegex(AssertionError, 'motion'):
            check_contract(schemas, [])

    def test_workflow_schema_drift_requires_capability_review(self):
        from providers.remotion.capabilities import check_contract
        schemas = self.schemas()
        workflow = next(tool for tool in schemas if tool['name'] == 'render_ad_variants')
        workflow['inputSchema']['properties']['rows']['items']['properties']['animation'] = {'type': 'string'}
        with self.assertRaisesRegex(AssertionError, 'render_ad_variants'):
            check_contract(schemas, [])

    def test_primitive_type_drift_fails(self):
        from providers.remotion.capabilities import check_contract
        schemas = self.schemas()
        render = next(tool for tool in schemas if tool['name'] == 'render_timeline')
        render['inputSchema']['properties']['visuals']['items']['properties']['scale']['type'] = 'string'
        with self.assertRaisesRegex(AssertionError, 'scale'):
            check_contract(schemas, [])

    def test_repeated_schema_generation_does_not_mutate_descriptions(self):
        first = copy.deepcopy(self.schemas())
        self.assertEqual(self.schemas(), first)
        from providers.contracts import enrich_tool_schema
        render = next(tool for tool in first if tool['name'] == 'render_timeline')
        self.assertEqual(enrich_tool_schema('remotion', copy.deepcopy(render)), render)
        for field in ('title', 'fps', 'output_filename'):
            render = next(tool for tool in first if tool['name'] == 'render_timeline')
            self.assertEqual(render['inputSchema']['properties'][field]['description'].count('Backend support:'), 1)

    def test_local_workflow_skill_cannot_advertise_lambda(self):
        from providers.remotion.capabilities import check_contract
        skill = {'name': 'bad', 'metadata': {'gateway_tools': 'Remotion___qc_deliverable',
                                           'remotion_backend': 'lambda'}}
        with self.assertRaisesRegex(AssertionError, 'qc_deliverable.*lambda'):
            check_contract(self.schemas(), [skill])
