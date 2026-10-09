from __future__ import annotations

import unittest

from agent.deep_agent import routing


class DeliverableDurationTests(unittest.TestCase):
    def test_deliverable_length_ignores_timing_cues_and_audio_requirements(self):
        cases = [
            ('Make a 5-second cinematic shot', 5), ('Make a 5 s clip', 5),
            ('Make a 5s clip', 5), ('Make a five seconds video', 5),
            ('Make a 10-sec shot', 10), ('Make a 1 minute video', 60),
            ('Make a clip lasting 5 seconds', 5),
            ('Add voiceover starting around 1.0 s to the clip', None),
            ('At 2 s fade the clip, after 4 seconds add audio', None),
            ('Start the clip around 1 second', None),
            ('Make a 5-second clip; start narration around 1.0 s', 5),
        ]
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                self.assertEqual(routing.intent_constraints(prompt)['required'].get('duration_seconds'), expected)
        constraints = routing.intent_constraints('Make a 5-second 1080p shot with voiceover around 1.0 s')
        route = routing.select_provider('tts', arguments={'text': 'Hello'}, **constraints)
        self.assertEqual(route.status, 'ready')
        self.assertNotIn('duration_seconds', route.required)
        self.assertNotIn('max_resolution', route.required)


class VideoVoiceoverTests(unittest.TestCase):
    def test_shot_voiceover_routes_ordered_steps_and_blocks_image_tools(self):
        for plain in ['Make a 5-second shot', 'Make a 5s clip']:
            with self.subTest(plain=plain):
                self.assertEqual(routing.route_intent(plain).alias, 'wan3_t2v')
        prompt = 'Make a 5-second cinematic shot with a voiceover: "Keep the light."'
        route = routing.route_intent(prompt)
        self.assertEqual(route.alias, 'wan3_t2v')
        self.assertEqual([step.alias for step in route.steps], ['wan3_t2v', 'eleven_v4_turbo', 'remotion_render'])
        self.assertEqual(route.expected_output, 'assembled MP4')
        self.assertNotIn('forbidden_tools', route.public())
        for request in ['Use Wan 3.0 to make a 5-second clip with voiceover', 'Use Kling to make a 5-second clip with voiceover']:
            with self.subTest(request=request):
                self.assertEqual(routing.route_intent(request).status, 'ready')
        for tool in ['Seedream___text_to_image', 'Seedream___image_to_image', 'Runway___text_to_image']:
            with self.subTest(tool=tool):
                constraints = routing.intent_constraints(prompt)
                self.assertEqual(routing.select_provider(routing.job_type(tool), **constraints).status, 'blocked')
                self.assertIsNotNone(routing.request_tool_blocker(prompt, tool))
        self.assertIsNone(routing.request_tool_blocker(prompt, 'Fal___generate_wan3_t2v'))

    def test_mp4_export_routes_assembly_while_nle_export_is_handoff(self):
        route = routing.route_intent('Add the voiceover to the referenced 5-second clip, starting around 1.0 s. Then assemble and export the final MP4.')
        self.assertEqual([step.alias for step in route.steps], ['eleven_v4_turbo', 'remotion_render'])
        self.assertEqual(routing.route_intent('assemble and export final MP4').skill, 'final-assembly')
        self.assertEqual(routing.route_intent('export an OTIO timeline').skill, 'resolve-handoff')

    def test_generic_still_blocks_seedream_but_named_request_preserves_it(self):
        route = routing.route_intent('Make a still image of a lighthouse')
        self.assertEqual(route.status, 'pending')
        self.assertIsNone(route.tool)
        self.assertIsNone(routing.resolve_alias('gpt_image25_t2i'))
        self.assertIsNotNone(routing.request_tool_blocker('Make a still image of a lighthouse', 'Seedream___text_to_image'))
        self.assertEqual(routing.route_intent('Make this still with Seedream: a lighthouse').tool, 'Seedream___text_to_image')


class MultiStepModalityTests(unittest.TestCase):
    def test_voiceover_preserves_video_modality_and_native_tts_dispatch(self):
        from agent.gateway_executor import GatewayExecutor
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request

        cases = [
            ('Make a 5-second clip from this start frame with a calm voiceover', 'wan3_i2v'),
            ('Make a 5-second clip from multi-ref images with a calm voiceover', 'wan3_r2v'),
            ('Use Wan 3.0 to make a 5-second clip with voiceover', 'wan3_t2v'),
            ('Use Kling to make a 5-second clip with voiceover', 'kling_t2v'),
        ]
        for prompt, alias in cases:
            with self.subTest(prompt=prompt):
                route = routing.route_intent(prompt)
                self.assertEqual(route.steps[0].alias, alias)
                executor = GatewayExecutor(_context_from_request(StudioAgentRequest(prompt=prompt)), [])
                args = {'text': 'Hello', 'voice_id': 'test'}
                audio = executor.media_selection('ElevenLabs___text_to_speech_convert', args)
                self.assertEqual(audio.status, 'ready')
                self.assertIsNone(executor.selection_blocker('ElevenLabs___text_to_speech_convert', args, audio))
