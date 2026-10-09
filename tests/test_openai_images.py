from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx

from providers.openai_images import api
from providers.catalog import get_provider
from providers.registry import dispatch, generate_schemas
from agent.deep_agent import routing
from agent.gateway_executor import tool_needs_approval
from server.billing_rates import cost_for, openai_images_usage_cost


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==')
MODEL = 'gpt-image-2.5-sunburst'


class OpenAIImagesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, {'OPENAI_IMAGES_DRY_RUN': 'true', 'OPENAI_IMAGES_MODEL': MODEL,
                                     'RENDERHAUS_MEDIA_DIR': str(self.root), 'OPENAI_API_KEY': '',
                                     'OPENAI_IMAGES_TOOL_COST_CENTS_JSON': '', 'AWS_S3_BUCKET': '',
                                     'REMOTION_APP_BUCKET_NAME': '', 'AWS_LAMBDA_FUNCTION_NAME': ''})
        env.start()
        self.addCleanup(env.stop)

    def fake_response(self, payload, status=200):
        return httpx.Response(status, json=payload,
                              request=httpx.Request('POST', 'https://api.openai.com/v1/images/generations'))

    def test_catalog_and_schema(self):
        spec = get_provider('openai_images')
        self.assertEqual(spec.target_name, 'OpenAI')
        self.assertIn('OPENAI_API_KEY', spec.env_keys)
        self.assertEqual(spec.default_env['OPENAI_IMAGES_DRY_RUN'], 'true')
        schemas = {s['name']: s for s in generate_schemas(spec)}
        self.assertEqual(set(schemas), {'generate_image', 'edit_image'})
        self.assertIn('image_path_or_url', schemas['edit_image']['inputSchema']['required'])

    def test_dry_run_never_reads_sources_or_uses_key_or_network(self):
        with patch.object(api.httpx, 'Client', side_effect=AssertionError('network forbidden')):
            result = api.edit_image('Change the lighting', str(self.root / 'missing.png'),
                                    reference_image_urls=['https://example.test/product.png'],
                                    mask_path_or_url=str(self.root / 'missing-mask.png'))
        self.assertEqual(result['status'], 'dry_run')
        self.assertIsNone(result.get('output_path'))
        self.assertIsNone(result['estimated_cost_usd'])
        self.assertFalse(result['training_eligible'])

    def test_size_presets_and_documented_custom_dimensions(self):
        for ratio, size in [('1:1', '2048x2048'), ('16:9', '2560x1440'), ('9:16', '1440x2560')]:
            with self.subTest(ratio=ratio):
                self.assertEqual(api.generate_image('Hero', aspect_ratio=ratio)['size'], size)
        self.assertEqual(api.generate_image('Hero', size='1536x864')['size'], '1536x864')

    def test_invalid_arguments_rejected_in_direct_and_gateway_calls(self):
        for args in [{'n': True}, {'n': 0}, {'n': 11}, {'quality': 'hd'}, {'size': '1025x1024'},
                     {'size': '256x256'}, {'size': '3840x3840'}, {'size': '4096x1024'},
                     {'size': '3072x768'}, {'aspect_ratio': '4:1'}, {'moderation': 'off'},
                     {'output_compression': 50}, {'prompt': ' '}, {'prompt': 'x' * 32001},
                     {'background': 'transparent', 'output_format': 'jpeg'}]:
            with self.subTest(args={k: str(v)[:50] for k, v in args.items()}):
                kwargs = {'prompt': 'Hero', **args}
                with self.assertRaises(ValueError):
                    api.generate_image(**kwargs)
                with self.assertRaises(ValueError):
                    dispatch('openai_images', 'generate_image', kwargs)

    def test_edit_ref_limits_and_unverified_fidelity_fail_before_paid_request(self):
        for args in [{'reference_image_urls': ['https://example.test/ref.png'] * 16},
                     {'input_fidelity': 'high'}, {'image_path_or_url': 'file:///etc/passwd'},
                     {'reference_image_urls': ['http://example.test/ref.png']}]:
            with self.subTest(args=args), patch.object(api.httpx, 'Client') as client:
                with self.assertRaises(ValueError):
                    dispatch('openai_images', 'edit_image',
                             {'prompt': 'Edit', 'image_path_or_url': 'https://example.test/a.png', **args})
                client.assert_not_called()

    def test_unverified_model_is_configurable_but_blocked_live(self):
        with patch.dict(os.environ, {'OPENAI_IMAGES_MODEL': 'gpt-image-future'}):
            preview = api.generate_image('Hero')
            self.assertEqual(preview['model'], 'gpt-image-future')
            self.assertIn('UNVERIFIED', preview['verification'])
            with patch.dict(os.environ, {'OPENAI_IMAGES_DRY_RUN': 'false'}):
                with self.assertRaisesRegex(ValueError, 'UNVERIFIED'):
                    api.generate_image('Hero')

    def test_generate_persists_every_b64_image_and_usage(self):
        payload = {'data': [{'b64_json': base64.b64encode(PNG).decode()}] * 2,
                   'usage': {'input_tokens_details': {'text_tokens': 100, 'image_tokens': 0},
                             'input_tokens': 100, 'output_tokens': 10000}}
        with patch.dict(os.environ, {'OPENAI_IMAGES_DRY_RUN': 'false', 'OPENAI_API_KEY': 'test-key'}), \
             patch.object(api.httpx.Client, 'post', return_value=self.fake_response(payload)) as post:
            result = api.generate_image('Hero', n=2, quality='max')
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(len(result['images']), 2)
        self.assertTrue(all(Path(i['output_path']).read_bytes() == PNG for i in result['images']))
        self.assertEqual(result['usage'], payload['usage'])
        self.assertAlmostEqual(result['actual_cost_usd'], 0.3005)
        body = post.call_args.kwargs['json']
        self.assertEqual(body['model'], MODEL)
        self.assertEqual(body['quality'], 'max')
        self.assertNotIn('response_format', body)
        self.assertNotIn('input_fidelity', body)

    def test_lambda_requires_durable_output_before_paid_request(self):
        with patch.dict(os.environ, {"OPENAI_IMAGES_DRY_RUN": "false", "OPENAI_API_KEY": "test-key",
                                     "AWS_LAMBDA_FUNCTION_NAME": "image-worker"}), \
             patch.object(api.httpx.Client, "post") as post:
            with self.assertRaisesRegex(RuntimeError, "AWS_S3_BUCKET"):
                api.generate_image("Hero")
            post.assert_not_called()

    def test_bucket_outputs_are_fetchable_and_avoid_local_worker_paths(self):
        s3 = Mock()
        s3.generate_presigned_url.side_effect = ["https://example.test/first.png", "https://example.test/second.png"]
        payload = {"data": [{"b64_json": base64.b64encode(PNG).decode()}] * 2}
        with patch.dict(os.environ, {"OPENAI_IMAGES_DRY_RUN": "false", "OPENAI_API_KEY": "test-key",
                                     "AWS_S3_BUCKET": "test-media"}), \
             patch.object(api.boto3, "client", return_value=s3), \
             patch.object(api.httpx.Client, "post", return_value=self.fake_response(payload)):
            result = api.generate_image("Hero", n=2)
        self.assertEqual(result["image_url"], "https://example.test/first.png")
        self.assertEqual(len(result["images"]), 2)
        self.assertNotIn("output_path", result)
        self.assertEqual(s3.put_object.call_count, 2)
        self.assertTrue(all(call.kwargs["Body"] == PNG for call in s3.put_object.call_args_list))
        self.assertTrue(all(call.kwargs["ContentType"] == "image/png" for call in s3.put_object.call_args_list))

    def test_edit_sends_ordered_images_and_mask_with_json(self):
        source = self.root / 'source.png'
        source.write_bytes(PNG)
        payload = {'data': [{'b64_json': base64.b64encode(PNG).decode()}]}
        with patch.dict(os.environ, {'OPENAI_IMAGES_DRY_RUN': 'false', 'OPENAI_API_KEY': 'test-key'}), \
             patch.object(api.httpx.Client, 'post', return_value=self.fake_response(payload)) as post:
            api.edit_image('Keep the product', str(source),
                           reference_image_urls=['https://example.test/product.png'],
                           mask_path_or_url='https://example.test/mask.png', background='transparent')
        self.assertTrue(post.call_args.args[0].endswith('/images/edits'))
        body = post.call_args.kwargs['json']
        self.assertTrue(body['images'][0]['image_url'].startswith('data:image/png;base64,'))
        self.assertEqual(body['images'][1], {'image_url': 'https://example.test/product.png'})
        self.assertEqual(body['mask'], {'image_url': 'https://example.test/mask.png'})

    def test_local_source_cannot_escape_media_root(self):
        with patch.dict(os.environ, {'OPENAI_IMAGES_DRY_RUN': 'false', 'OPENAI_API_KEY': 'test-key'}), \
             patch.object(api.httpx.Client, 'post') as post:
            with self.assertRaisesRegex(ValueError, 'media'):
                api.edit_image('Edit', '/etc/passwd')
            post.assert_not_called()

    def test_failed_or_malformed_response_does_not_publish_artifact(self):
        for payload, status in [({'error': {'message': 'test-key', 'code': 'content_policy_violation'}}, 400),
                                ({'data': []}, 200), ({'data': [{'b64_json': 'bad!'}]}, 200),
                                ({'data': [{'b64_json': base64.b64encode(b'not an image').decode()}]}, 200)]:
            with self.subTest(payload=payload), \
                 patch.dict(os.environ, {'OPENAI_IMAGES_DRY_RUN': 'false', 'OPENAI_API_KEY': 'test-key'}), \
                 patch.object(api.httpx.Client, 'post', return_value=self.fake_response(payload, status)):
                with self.assertRaises(RuntimeError) as error:
                    api.generate_image('Hero')
                self.assertNotIn('test-key', str(error.exception))
                self.assertFalse(list(self.root.glob('images/*')))

    def test_billing_has_unknown_pre_call_quote_and_rated_usage(self):
        for name in ['generate_image', 'edit_image']:
            quote = routing.estimate_cost('OpenAI___' + name, {}, list_price=True)
            self.assertIsNone(quote.total_cents)
            self.assertIn('UNVERIFIED', quote.description)
            self.assertEqual(cost_for('openai_images', name, {'prompt': 'Hero', **({'image_path_or_url': 'https://example.test/a.png'} if name == 'edit_image' else {})}).total_cents, 0)
        with patch.dict(os.environ, {'OPENAI_IMAGES_DRY_RUN': 'false'}):
            with self.assertRaisesRegex(ValueError, 'unknown'):
                cost_for('openai_images', 'generate_image', {'prompt': 'Hero'})
        self.assertIsNone(openai_images_usage_cost({}))

    def test_default_explicit_and_specialist_routing(self):
        for prompt, tool in [('generate a still', 'generate_image'), ('edit this product image', 'edit_image'),
                             ('GPT Image 2.5 poster with text', 'generate_image')]:
            route = routing.route_intent(prompt)
            self.assertEqual(route.status, 'ready')
            self.assertEqual(route.tool, 'OpenAI___' + tool)
            self.assertEqual(route.provider, 'openai_images')
            self.assertEqual(route.model, MODEL)
            self.assertIn('unknown', route.disclosure)
        self.assertEqual(routing.route_intent('use Seedream for a still').tool, 'Seedream___text_to_image')
        self.assertEqual(routing.route_intent('editable SVG logo').status, 'pending')
        self.assertEqual(routing.route_intent('fix the typo in this banner').status, 'pending')
        self.assertEqual(routing.route_intent('generate a still', confidential=True).tool, 'OpenAI___generate_image')
        self.assertFalse(routing.training_eligible({'provider': 'openai_images', 'model': MODEL}))

    def test_studio_registers_all_outputs_with_training_excluded(self):
        from server import studio
        from server.studio_state import StudioRepository

        paths = [self.root / f"output-{i}.png" for i in range(2)]
        for path in paths:
            path.write_bytes(PNG)
        repository = StudioRepository(self.root / "studio.sqlite3", self.root / "stored")
        repository.create_project("workspace", "user", "Images", project_id="project")
        payload = {"status": "succeeded", "provider": "openai_images", "model": MODEL,
                   "training_eligible": False, "output_path": str(paths[0]),
                   "images": [{"output_path": str(path)} for path in paths]}
        with patch.object(studio, "repository", repository):
            assets = studio._register_payload_assets(payload=payload, workspace_id="workspace",
                     project_id="project", user_id="user", kind="image")
        self.assertEqual(len(assets), 2)
        self.assertTrue(all(asset["training_eligible"] is False for asset in assets))

    def test_edit_handles_are_resolved_in_primary_reference_mask_order(self):
        from agent.studio_agent_next import StudioAgentContext

        resolved = []
        def publish(version):
            resolved.append(version)
            return f"https://example.test/{version}.png"
        context = StudioAgentContext(source_publisher=publish)
        arguments = context.prepare_gateway_arguments("OpenAI___edit_image", {
            "prompt": "Keep the character", "image_path_or_url": "renderhaus-asset://primary",
            "reference_image_urls": ["renderhaus-asset://reference"],
            "mask_path_or_url": "renderhaus-asset://mask"})
        self.assertEqual(resolved, ["primary", "reference", "mask"])
        self.assertEqual(arguments["reference_image_urls"], ["https://example.test/reference.png"])
        self.assertEqual(dispatch("openai_images", "edit_image", arguments)["status"], "dry_run")

    def test_paid_image_approval_preserves_autonomous_rule(self):
        for tool in ['generate_image', 'edit_image']:
            self.assertTrue(tool_needs_approval('OpenAI___' + tool, False))
            self.assertFalse(tool_needs_approval('OpenAI___' + tool, True))

    def test_secret_sync_accepts_existing_openai_key_and_new_config(self):
        from server.secrets import secret_payload_from_mapping
        payload = secret_payload_from_mapping({'OPENAI_API_KEY': 'test-key', 'OPENAI_IMAGES_DRY_RUN': 'true',
                                               'OPENAI_IMAGES_MODEL': MODEL})
        self.assertEqual(payload['OPENAI_API_KEY'], 'test-key')
        self.assertEqual(payload['OPENAI_IMAGES_DRY_RUN'], 'true')

    def test_operator_quote_scales_with_output_count(self):
        with patch.dict(os.environ, {'OPENAI_IMAGES_DRY_RUN': 'false',
                                     'OPENAI_IMAGES_TOOL_COST_CENTS_JSON': json.dumps({'generate_image': 50})}):
            self.assertEqual(cost_for('openai_images', 'generate_image', {'prompt': 'Hero', 'n': 2}).provider_cents, 100)
