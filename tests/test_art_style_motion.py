from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

import yaml

from agent.deep_agent.routing import filter_request_tools, route_intent

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'agent/deep_agent/skills/art-style-motion'


class ArtStyleMotionRoutingTests(unittest.TestCase):
    def test_published_card_titles_can_be_requested_by_name(self):
        for filename in ['style-cards.md', 'grammar-cards.md']:
            titles = [line.split('|')[1].strip() for line in (SKILL / 'references' / filename).read_text().splitlines()
                      if line.startswith('| ') and not line.startswith(('| Card |', '| Grammar |'))]
            self.assertTrue(titles)
            for title in titles:
                with self.subTest(title=title):
                    route = route_intent(f'Make an animated video using {title} style')
                    self.assertEqual((route.skill, route.alias), ('art-style-motion', 'remotion_render'))

    def test_named_art_and_explainer_grammars_select_remotion(self):
        for prompt in [
            'Make a Van Gogh painting move with swirling brushwork',
            'Animate a Monet pond with moving reflections',
            'Make a Bauhaus animation',
            'Make an ukiyo-e art-style short',
            'Make an 8-bit animated art short',
            'Create a Kurzgesagt-style explainer video with voiceover',
            'Make a Vox-style explainer video over my recording',
            'Make a 3Blue1Brown animation of gradient descent',
            'Make a 3b1b explainer animation',
            'Make a video without narration in Vox style',
            'Make an animation without music in Bauhaus style',
            'Make a Vox-style explainer animation without HyperFrames',
            'Make a silent Bauhaus animation; do not lip-sync anyone',
            'Create a kinetic typography explainer video',
            'Make a Dalí-style animation',
            'Make a cave painting animation',
            'Make an early ray-traced CGI animation',
            'Make a contemporary flat animation',
            'Make an illustrated-presenter animation with narration',
            'Make a whiteboard-style animated explainer with narration',
            'Make a keynote-style animated product explainer',
            'Make a finance-chart-style animated explainer with voiceover',
            'Make a character walk through a series of famous paintings',
            'Recreate this animation in Bauhaus style',
            'Use art-style-motion for this short',
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual((route.skill, route.alias, route.tool, route.status),
                                 ('art-style-motion', 'remotion_render', 'Remotion___render_timeline', 'ready'))
                self.assertFalse(route.steps)
                self.assertIn('default', route.disclosure)

    def test_plain_and_silent_explainers_keep_their_existing_skills(self):
        for prompt, skill in [
            ('Make a silent explainer video with no narration and synced sound effects', 'knowledge-explainer'),
            ('Make a silent whiteboard explainer with event foley only', 'knowledge-explainer'),
            ('Make a no-narration Vibe-style knowledge short', 'knowledge-explainer'),
            ('Make a whiteboard explainer with voiceover narration', 'whiteboard-explainer'),
            ('Draw and explain this concept as whiteboard video', 'whiteboard-explainer'),
            ('Make a silent explainer titled "Vox style" with no narration', 'knowledge-explainer'),
            ('Make a silent explainer; do not use Vox style', 'knowledge-explainer'),
            ('Make a silent explainer video about ancient Egyptian farming', 'knowledge-explainer'),
            ('Make a silent animated explainer about ancient Egyptian farming', 'knowledge-explainer'),
            ('Make a silent animated explainer about the life of Monet', 'knowledge-explainer'),
            ('Make a silent explainer video, not Vox style', 'knowledge-explainer'),
            ('Make a silent explainer video with no Vox style', 'knowledge-explainer'),
            ('Make a silent explainer video on ancient Egyptian farming', 'knowledge-explainer'),
            ('Make a silent explainer video explaining Egyptian farming', 'knowledge-explainer'),
        ]:
            with self.subTest(prompt=prompt):
                self.assertEqual(route_intent(prompt).skill, skill)

    def test_static_art_provider_video_and_audio_postprocess_are_not_style_workflows(self):
        for prompt, arguments, skill in [
            ('Generate a Van Gogh still image', None, 'image-gen'),
            ('Restyle this existing footage as a Monet painting', {'video_url': 'https://example.invalid/clip.mp4'}, 'edit-v2v'),
            ('Add foley to this existing silent Vox-style explainer', {'video_url': 'https://example.invalid/clip.mp4'}, 'audio-bed'),
            ('Make a photoreal cinematic drone shot', None, 't2v'),
            ('Who was Van Gogh?', None, None),
            ('Make a narrated video about Monet with archival photographs', None, 't2v'),
        ]:
            with self.subTest(prompt=prompt):
                self.assertEqual(route_intent(prompt, arguments=arguments).skill, skill)
        for provider, tool in [('Kling', 'Kling___text_to_video'), ('Runway', 'Runway___text_to_video'),
                               ('Luma', 'Luma___text_to_video')]:
            route = route_intent(f'Use {provider} to make a Bauhaus-style video')
            self.assertEqual((route.skill, route.tool), ('named-provider', tool))
            self.assertIn('explicit request', route.disclosure)
        route = route_intent('Use Kling to make a Vox-style video with voiceover')
        self.assertEqual(route.steps[0].tool, 'Kling___text_to_video')
        self.assertEqual(route.steps[-1].tool, 'Remotion___render_timeline')
        for provider, tool in [('Runway', 'Runway___text_to_video'), ('Luma', 'Luma___text_to_video')]:
            prompt = f'Make a Vox-style video using OpenAI character frames and {provider} for video'
            route = route_intent(prompt)
            self.assertEqual((route.skill, route.tool), ('named-provider', tool))
            self.assertIn('explicit request', route.disclosure)
            voiced = route_intent(prompt + ' with voiceover')
            self.assertEqual(voiced.steps[0].tool, tool)

    def test_explicit_hyperframes_uses_same_skill_with_feature_and_availability_gates(self):
        prompt = 'Make a Vox-style explainer animation with HyperFrames'
        with patch.dict(os.environ, {'HYPERFRAMES_ENABLED': 'true', 'HYPERFRAMES_DRY_RUN': 'true'}):
            route = route_intent(prompt)
            self.assertEqual((route.skill, route.alias, route.tool, route.status),
                             ('art-style-motion', 'hyperframes_render', 'HyperFrames___render_composition', 'ready'))
            self.assertIn('explicit HyperFrames request', route.disclosure)
            missing = route_intent(prompt, available_tools={'Remotion___render_timeline'})
            self.assertEqual((missing.skill, missing.status, missing.tool), ('art-style-motion', 'blocked', None))
        with patch.dict(os.environ, {'HYPERFRAMES_ENABLED': 'false'}):
            route = route_intent(prompt)
            self.assertEqual((route.skill, route.status, route.tool), ('art-style-motion', 'blocked', None))
            self.assertIn('disabled', route.reason)
        html = route_intent('Make a Vox-style explainer animation using an HTML template')
        self.assertEqual(html.alias, 'remotion_render')

    def test_confidential_tier_and_price_words_do_not_choose_renderer(self):
        for tier in [None, 'draft', 'premium']:
            for confidential in [False, True]:
                with self.subTest(tier=tier, confidential=confidential):
                    route = route_intent('Make the cheapest Bauhaus animation', tier=tier, confidential=confidential)
                    self.assertEqual((route.skill, route.alias), ('art-style-motion', 'remotion_render'))

    def test_narrated_style_workflow_keeps_character_images_and_scopes_audio_provider(self):
        from agent.gateway_executor import GatewayExecutor
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request

        prompt = 'Make a Vox-style explainer video with ElevenLabs voiceover and character frames'
        names = {'OpenAI___generate_image', 'ElevenLabs___text_to_speech_convert',
                 'ElevenLabs___text_to_sound_effects_convert', 'Remotion___render_timeline'}
        self.assertEqual(filter_request_tools(prompt, names), names)
        executor = GatewayExecutor(_context_from_request(StudioAgentRequest(prompt=prompt)), [])
        for tool, args, alias in [
            ('OpenAI___generate_image', {'prompt': 'An original presenter', 'background': 'transparent'}, 'gpt_image25_t2i'),
            ('ElevenLabs___text_to_speech_convert', {'text': 'A concept', 'voice_id': 'offline', 'model_id': 'eleven_v4_turbo'}, 'eleven_v4_turbo'),
            ('ElevenLabs___text_to_sound_effects_convert', {'text': 'A soft pop', 'duration_seconds': 1, 'model_id': 'eleven_text_to_sound_v2'}, 'elevenlabs_sfx_v2'),
        ]:
            with self.subTest(tool=tool):
                route = executor.media_selection(tool, args)
                self.assertEqual((route.status, route.alias, route.tool), ('ready', alias, tool))
                self.assertIsNone(executor.selection_blocker(tool, args, route))
        self.assertNotIn('OpenAI___generate_image', filter_request_tools('Make a cinematic video with voiceover', names))

    def test_silent_named_style_keeps_images_sfx_and_excludes_speech(self):
        allowed = {'OpenAI___generate_image', 'ElevenLabs___text_to_sound_effects_convert', 'Remotion___render_timeline'}
        for prompt in [
            'Make a silent Vox-style explainer video with no narration and event sound effects',
            'Make a silent Bauhaus animation without narration',
            'Make a video without narration in Vox style',
        ]:
            with self.subTest(prompt=prompt):
                self.assertEqual(route_intent(prompt).skill, 'art-style-motion')
                self.assertEqual(filter_request_tools(prompt, allowed | {'ElevenLabs___text_to_speech_convert'}), allowed)
        prompt = 'Make a silent Bauhaus animation with no speech'
        self.assertNotIn('HeyGen___voice_tts', filter_request_tools(prompt, {'HeyGen___voice_tts'}))


class ArtStyleMotionSkillTests(unittest.TestCase):
    def test_distribution_includes_references_and_licence_notices(self):
        config = tomllib.loads((ROOT / 'pyproject.toml').read_text())['tool']['setuptools']
        package_root = ROOT / 'agent/deep_agent'
        included = {path for pattern in config['package-data']['agent.deep_agent']
                    for path in package_root.glob(pattern)}
        self.assertTrue(set(SKILL.glob('references/*.md')) <= included)
        self.assertIn('third_party/huashu-art-motion/LICENSE', config['license-files'])
        self.assertIn('THIRD_PARTY_NOTICES', config['license-files'])

    def test_skill_is_parseable_and_all_local_references_are_shipped(self):
        from deepagents.middleware.skills import _parse_skill_metadata

        path = SKILL / 'SKILL.md'
        self.assertTrue(path.is_file(), 'The art-style-motion skill must ship.')
        body = path.read_text()
        self.assertIsNotNone(_parse_skill_metadata(body, str(path), 'art-style-motion'))
        meta = yaml.safe_load(body.split('---', 2)[1])['metadata']
        self.assertEqual(set(meta['routing_tools'].split()),
                         {'remotion_render', 'hyperframes_render', 'gpt_image25_t2i', 'eleven_v4_turbo', 'elevenlabs_sfx_v2'})
        paths = [path, *SKILL.glob('references/*.md')]
        self.assertEqual({p.name for p in paths},
                         {'SKILL.md', 'method.md', 'style-cards.md', 'grammar-cards.md'})
        for source in paths:
            for target in re.findall(r'\[[^\]\n]+\]\(([^)\s]+)\)', source.read_text()):
                link = urlsplit(target)
                if not link.scheme and link.path:
                    self.assertTrue((source.parent / unquote(link.path)).exists(), (source, target))

    def test_adapted_text_retains_mit_notice_and_does_not_vendor_the_renderer(self):
        licence = ROOT / 'third_party/huashu-art-motion/LICENSE'
        self.assertTrue(licence.is_file())
        notice = licence.read_text().strip()
        self.assertIn('Copyright (c) 2026 alchaincyf (花叔 · 花生)', notice)
        self.assertIn('Permission is hereby granted, free of charge', notice)
        for path in [SKILL / 'SKILL.md', *SKILL.glob('references/*.md')]:
            self.assertIn(notice, path.read_text(), path)
            self.assertIn('d861767d180008d27675819932070a670a3ae43f', path.read_text(), path)
        notices = (ROOT / 'THIRD_PARTY_NOTICES').read_text()
        self.assertIn('huashu-art-motion', notices)
        self.assertIn('demo-only', notices)
        self.assertFalse(list(SKILL.rglob('*.py')))
        self.assertFalse(list((ROOT / 'third_party/huashu-art-motion').rglob('*.py')))


class ArtStyleMotionApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_skill_loading_and_render_rejection_resume_without_submission(self):
        from langchain_core.messages import ToolMessage
        from mcp import Tool

        from agent.deep_agent.runner import run_with_servers
        from agent.studio_agent_next import StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, _context_from_request
        from test_deep_agent import Gateway, ScriptedModel, call, final

        schema = next(row for row in json.loads((ROOT / 'configs/gateway/remotion.tools.json').read_text())
                      if row['name'] == 'render_timeline')
        gateway = Gateway([Tool(name='Remotion___render_timeline', description=schema['description'], inputSchema=schema['inputSchema'])])
        request = StudioAgentRequest(prompt='Make a Vox-style explainer video with supplied character frames',
                                     autonomous=True, job_id='art-render', workspace_id='workspace', project_id='project')
        studio = _context_from_request(request)
        model = ScriptedModel([
            call('read_file', {'file_path': '/skills/art-style-motion/SKILL.md', 'limit': 1000}, 'skill'),
            call('read_file', {'file_path': '/skills/art-style-motion/references/grammar-cards.md', 'limit': 1000}, 'cards'),
            call('read_studio_context', {}, 'context'),
            call('call_editor_tool', {'tool_name': 'Remotion___render_timeline', 'arguments': {
                'title': 'Original art explainer', 'visuals': [{'kind': 'image', 'url': 'https://example.invalid/frame.png', 'duration_seconds': 3}]}}, 'render'),
        ])
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            'RENDERHAUS_OUTCOME_DIR': directory, 'REMOTION_DRY_RUN': 'true', 'RENDERHAUS_PREMIUM_VIDEO_APPROVAL': 'true',
        }):
            with self.assertRaises(StudioAgentApprovalRequired) as paused:
                await run_with_servers(request, studio, [gateway], model=model)
            messages = model._seen[-1][0]
            skill = next(message for message in messages if isinstance(message, ToolMessage) and message.tool_call_id == 'skill')
            self.assertIn('Design one frame', skill.content)
            cards = next(message for message in messages if isinstance(message, ToolMessage) and message.tool_call_id == 'cards')
            self.assertIn('Kurzgesagt', cards.content)
            context = next(json.loads(message.content) for message in messages if isinstance(message, ToolMessage) and message.name == 'read_studio_context')
            self.assertEqual(context['intent_route']['skill'], 'art-style-motion')
            approval = paused.exception.approvals[0]
            self.assertEqual(approval.tool_name, 'Remotion___render_timeline')
            self.assertIn('Estimated cost', approval.description)
            self.assertIn('unknown', approval.description)
            gateway.call_tool.assert_not_awaited()
            resumed = request.model_copy(update={'session_items': studio.session_items, 'resume_state': paused.exception.state,
                'approval_decisions': [StudioApprovalDecision(call_id=approval.call_id, decision='reject')]})
            await run_with_servers(resumed, _context_from_request(resumed), [gateway], model=ScriptedModel([final()]))
            gateway.call_tool.assert_not_awaited()
            row = json.loads((Path(directory) / 'outcomes.jsonl').read_text().splitlines()[-1])
            self.assertEqual((row['provider'], row['outcome'], row['stage']), ('remotion', 'rejected', 'approval'))
