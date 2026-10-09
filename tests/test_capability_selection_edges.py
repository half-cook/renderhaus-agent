import unittest

from agent.deep_agent import routing


class CapabilitySelectionEdges(unittest.TestCase):
    def test_named_gpt_image_uses_built_adapter(self):
        route = routing.route_intent("generate with GPT Image 2.5")
        self.assertEqual((route.alias, route.status, route.tool), ("gpt_image25_t2i", "ready", "OpenAI___generate_image"))
        self.assertIn("explicit request", route.disclosure)

    def test_named_seedance25_uses_the_built_adapter(self):
        route = routing.route_intent("use Seedance 2.5 to animate this image")
        self.assertEqual((route.alias, route.status, route.tool),
                         ("seedance25_i2v", "ready", "Seedance___image_to_video"))
        self.assertIn("explicit request", route.disclosure)
        self.assertNotIn("interim", route.disclosure)

    def test_named_wan_vace_uses_requested_modality(self):
        for prompt, tool in [("use Wan 2.2 VACE for a video", "text_to_video"),
                             ("animate this image with Wan 2.2 VACE", "image_to_video"),
                             ("restyle this footage with Wan 2.2 VACE", "video_to_video")]:
            route = routing.route_intent(prompt)
            self.assertEqual(route.tool, "Fal___" + tool)
            self.assertEqual(route.model, "fal-ai/wan-22-vace-fun-a14b")
            self.assertEqual(route.skill, "named-provider")

    def test_omni_explicit_request_selects_omni_tool(self):
        route = routing.route_intent("use Kling Omni for a multi-reference video")
        self.assertEqual(route.tool, "Kling___omni_video")
        self.assertIn("explicit request", route.disclosure)

    def test_bare_fish_name_is_explicit(self):
        route = routing.route_intent("use Fish to narrate this text")
        self.assertEqual((route.skill, route.tool), ("named-provider", "FishAudio___generate_speech"))

    def test_provider_names_do_not_override_assembly(self):
        route = routing.select_provider("motion_graphics")
        self.assertEqual(route.tool, "Remotion___render_timeline")

    def test_local_qc_is_ready_without_a_gateway_or_paid_provider(self):
        route = routing.route_intent("continuity QC these clips")
        self.assertEqual((route.alias, route.status, route.tool), ("local_qc", "ready", None))
        self.assertIsNone(route.dispatch_tool)

    def test_real_face_evidence_cannot_be_erased_by_tool_arguments(self):
        route = routing.route_intent('my CEO photo attached says "hi"', arguments={"real_face_refs": False})
        self.assertEqual((route.alias, route.status), ("wan3_i2v", "ready"))
        self.assertEqual(route.tool, "Fal___generate_wan3_i2v")
        self.assertTrue(route.required["real_face_refs"])
        self.assertIn("consent required", route.disclosure)

    def test_retired_explicit_request_is_retired_without_dispatch(self):
        route = routing.route_intent("generate with Veo 3.1 native audio dialogue")
        self.assertEqual(route.status, "retired")
        self.assertIsNone(route.tool)

    def test_reference_modality_has_priority_over_generic_video(self):
        self.assertEqual(routing.route_intent("use Seedance for reference-to-video").job_type, "reference_video")

    def test_audio_variants_keep_the_same_capability_selection(self):
        for name, capability in [('ElevenLabs___text_to_dialogue_convert', 'tts'),
                                 ('ElevenLabs___text_to_speech_stream', 'tts'),
                                 ('ElevenLabs___music_video_to_music', 'music'),
                                 ('ElevenLabs___music_compose_detailed', 'music')]:
            with self.subTest(name=name):
                self.assertEqual(routing.job_type(name), capability)
                route = routing.select_provider(capability, provider='elevenlabs' if capability == 'music' else None,
                                                tool_variant=routing.tool_variant(name))
                self.assertEqual(route.tool, name)
                self.assertIn('explicit' if capability == 'music' else 'default', route.disclosure)
        name = 'ElevenLabs___text_to_dialogue_convert'
        route = routing.select_provider('tts', provider='fish_audio', tool_variant=routing.tool_variant(name))
        self.assertEqual(route.tool, 'FishAudio___generate_speech')
