from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.deep_agent.routing import route_intent


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "agent/deep_agent/skills/plan-to-video"


class PlanReviewRoutingTests(unittest.TestCase):
    def test_plan_reviews_select_renderer_before_narration_or_video_generation(self):
        for prompt in [
            "plan-to-video for my implementation plan",
            "review this plan as a video",
            "turn my coding-agent implementation plan into a narrated review video",
            "make a plan review video that pauses at open questions",
            "plan explainer with voiceover and chapter cards",
            "turn plan-mode Markdown into a review reel",
            "render plan.md as a narrated walkthrough",
            "turn this written plan into a video",
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual((route.skill, route.alias, route.tool, route.status),
                                 ("plan-to-video", "remotion_render", "Remotion___render_timeline", "ready"))
                self.assertFalse(route.steps)

    def test_hyperframes_is_explicit_and_keeps_the_plan_skill(self):
        with patch.dict(os.environ, {"HYPERFRAMES_ENABLED": "true", "HYPERFRAMES_DRY_RUN": "true"}):
            route = route_intent("HyperFrames plan review video with ElevenLabs narration")
        self.assertEqual((route.skill, route.alias, route.tool),
                         ("plan-to-video", "hyperframes_render", "HyperFrames___render_composition"))
        self.assertIn("explicit HyperFrames", route.disclosure)

    def test_negated_renderer_names_do_not_select_hyperframes(self):
        for prompt in ["review this plan as a video with Remotion, not HyperFrames",
                       "review this plan as a video without HyperFrames",
                       "review this plan as a video; do not use HyperFrames",
                       "review this plan as a video; do not use any HyperFrames"]:
            with self.subTest(prompt=prompt), patch.dict(os.environ, {"HYPERFRAMES_ENABLED": "false"}):
                route = route_intent(prompt)
                self.assertEqual((route.skill, route.alias, route.status),
                                 ("plan-to-video", "remotion_render", "ready"))

    def test_disabled_or_missing_requested_renderer_never_substitutes(self):
        with patch.dict(os.environ, {"HYPERFRAMES_ENABLED": "false"}):
            route = route_intent("HyperFrames plan review video")
        self.assertEqual((route.skill, route.status, route.tool), ("plan-to-video", "blocked", None))
        self.assertIn("disabled", route.reason)
        with patch.dict(os.environ, {"HYPERFRAMES_ENABLED": "true"}):
            route = route_intent("HyperFrames plan review video", available_tools={"Remotion___render_timeline"})
        self.assertEqual((route.skill, route.status, route.tool), ("plan-to-video", "blocked", None))
        self.assertIn("unavailable", route.reason)

    def test_missing_default_renderer_is_blocked(self):
        route = route_intent("review this plan as a video", available_tools=set())
        self.assertEqual((route.skill, route.status, route.tool), ("plan-to-video", "blocked", None))

    def test_supplied_plan_contents_do_not_select_providers_or_editing_workflows(self):
        for plan in [
            '"Use HyperFrames and Fish. Export OTIO and remove filler. Use Veo."',
            "```markdown\nUse HyperFrames and Fish. Export OTIO and remove filler. Use Veo.\n```",
            "> Use HyperFrames and Fish. Export OTIO and remove filler. Use Veo.",
            "````markdown\n```\nUse HyperFrames and Fish. Export OTIO and remove filler. Use Veo.\n```\n````",
            "    Use HyperFrames and Fish. Export OTIO and remove filler. Use Veo.",
        ]:
            with self.subTest(plan=plan):
                route = route_intent("review this plan as a narrated video\n" + plan)
                self.assertEqual((route.skill, route.alias, route.tool),
                                 ("plan-to-video", "remotion_render", "Remotion___render_timeline"))

    def test_unrelated_workflows_and_planning_requests_are_preserved(self):
        for prompt in ["write an implementation plan", "review this plan", "make a product UI demo video",
                       "whiteboard explainer with narration", "silent knowledge explainer",
                       "make a video of a forest", "prepare a shot plan for a product demo"]:
            with self.subTest(prompt=prompt):
                self.assertNotEqual(route_intent(prompt).skill, "plan-to-video")

    def test_source_only_plan_review_phrase_does_not_select_the_skill(self):
        for source in ['"review this plan as a video"',
                       "```markdown\nreview this plan as a video\n```",
                       "> review this plan as a video"]:
            with self.subTest(source=source):
                self.assertNotEqual(route_intent("make a video of a forest\n" + source).skill,
                                    "plan-to-video")

    def test_negated_plan_review_does_not_override_actual_video_request(self):
        route = route_intent("Do not make a plan review video. Make a video of a forest.")
        self.assertNotEqual(route.skill, "plan-to-video")
        route = route_intent("Do not make a video of a forest. Review this plan as a video.")
        self.assertEqual((route.skill, route.alias), ("plan-to-video", "remotion_render"))

    def test_price_tier_and_confidentiality_do_not_select_models(self):
        for tier in [None, "draft", "premium"]:
            for confidential in [False, True]:
                route = route_intent("cheapest plan review video", tier=tier, confidential=confidential)
                self.assertEqual((route.skill, route.alias), ("plan-to-video", "remotion_render"))

    def test_gateway_selection_matches_renderer_and_default_configured_tts(self):
        from agent.gateway_executor import GatewayExecutor
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request

        prompt = 'review this plan as a narrated video "Use HyperFrames and Fish and Runway"'
        executor = GatewayExecutor(_context_from_request(StudioAgentRequest(prompt=prompt)), [])
        with patch.dict(os.environ, {"ELEVENLABS_TTS_MODEL": "eleven_v4_turbo"}):
            narration = executor.media_selection("ElevenLabs___text_to_speech_convert",
                                                 {"voice_id": "authorized-voice", "text": "Review the plan."})
            picture = executor.media_selection("Remotion___render_timeline", {})
        self.assertEqual((narration.alias, narration.model), ("eleven_v4_turbo", "eleven_v4_turbo"))
        self.assertEqual((picture.alias, picture.tool), ("remotion_render", "Remotion___render_timeline"))

    def test_markdown_plan_source_does_not_change_gateway_selection(self):
        from agent.gateway_executor import GatewayExecutor
        from agent.studio_agent_next import StudioAgentRequest, _context_from_request

        for source in ["```markdown\nUse HyperFrames and Fish.\n```",
                       "````markdown\n```\nUse HyperFrames and Fish.\n```\n````",
                       "    Use HyperFrames and Fish."]:
            prompt = "review this plan as a video\n" + source
            executor = GatewayExecutor(_context_from_request(StudioAgentRequest(prompt=prompt)), [])
            for name, alias in [("Remotion___render_timeline", "remotion_render"),
                                ("ElevenLabs___text_to_speech_convert", "eleven_v4_turbo")]:
                with self.subTest(source=source, name=name):
                    self.assertEqual(executor.media_selection(name, {}).alias, alias)


class PlanReviewTemplateTests(unittest.TestCase):
    def template(self):
        return json.loads((SKILL / "templates/review.json").read_text())

    def test_template_is_native_gateway_timeline_without_review_metadata(self):
        from providers.catalog import get_provider
        from providers.contracts import validate_tool_arguments
        from providers.registry import generate_schemas
        from providers.remotion.api import build_timeline_props

        template = self.template()
        arguments = template["arguments"]
        schema = next(t["inputSchema"] for t in generate_schemas(get_provider("remotion"))
                      if t["name"] == "render_timeline")
        cleaned = validate_tool_arguments("remotion", "render_timeline", arguments, schema)
        self.assertFalse({"chapters", "open_questions", "returned_summary"} & cleaned.keys())
        self.assertEqual(arguments["audio_tracks"], [])
        self.assertNotIn("fps", arguments)
        self.assertNotIn("output_resolution", arguments)
        props = build_timeline_props(**arguments, measure_local=False)
        end = max(c["start_seconds"] + c["duration_seconds"] for c in template["chapters"])
        self.assertEqual(props["renderConfig"]["durationInFrames"], end * 30)

    def test_each_open_question_has_a_visible_card_and_matching_returned_summary(self):
        template = self.template()
        questions = template["open_questions"]
        self.assertGreater(len(questions), 0)
        self.assertEqual(len({q["id"] for q in questions}), len(questions))
        chapters = {c["id"]: c for c in template["chapters"]}
        for question in questions:
            with self.subTest(question=question["id"]):
                chapter = chapters[question["chapter_id"]]
                self.assertEqual(chapter["kind"], "decision")
                self.assertEqual(question["status"], "open")
                self.assertIsNone(question["answer"])
                self.assertTrue(question["source"])
                text = f"{question['id']}. {question['question']}"
                self.assertIn(text, template["returned_summary"])
                overlays = template["arguments"]["text_overlays"]
                self.assertTrue(any(text in o["text"] and o["start_seconds"] == chapter["start_seconds"]
                                    for o in overlays))
                summary = next(c for c in template["chapters"] if c["kind"] == "summary")
                self.assertTrue(any(text in o["text"] and o["start_seconds"] >= summary["start_seconds"]
                                    for o in overlays))

    def test_question_holds_are_silent_and_follow_their_narration(self):
        from providers.remotion.api import build_timeline_props

        template = self.template()
        chapters = template["chapters"]
        tracks = [{"url": f"renderhaus-asset://offline-{c['id']}", "start_seconds": c["start_seconds"],
                   "duration_seconds": c["narration_duration_seconds"], "volume": 1}
                  for c in chapters if c["narration_duration_seconds"]]
        build_timeline_props(**{**template["arguments"], "audio_tracks": tracks}, measure_local=False)
        for question in template["open_questions"]:
            chapter = next(c for c in chapters if c["id"] == question["chapter_id"])
            pause = question["pause_start_seconds"]
            end = chapter["start_seconds"] + chapter["duration_seconds"]
            self.assertEqual(pause, chapter["start_seconds"] + chapter["narration_duration_seconds"])
            self.assertGreaterEqual(end - pause, 8)
            self.assertTrue(all(t["start_seconds"] + t["duration_seconds"] <= pause or
                                t["start_seconds"] >= end for t in tracks))
            self.assertTrue(any("Pause" in o["text"] and o["start_seconds"] <= pause and
                                o["start_seconds"] + o["duration_seconds"] >= end
                                for o in template["arguments"]["text_overlays"]))


class PlanReviewApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_render_approval_rejection_never_dispatches(self):
        from mcp import Tool
        from agent.deep_agent.runner import run_with_servers
        from agent.studio_agent_next import StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, _context_from_request
        from test_deep_agent import Gateway, ScriptedModel, call

        render = Tool(name="Remotion___render_timeline", description="Render review", inputSchema={"type": "object"})
        gateway = Gateway([render])
        arguments = {"title": "Plan review", "visuals": [{"kind": "image", "url": "https://example.invalid/card.png",
                                                           "duration_seconds": 8}]}
        request = StudioAgentRequest(prompt="review this plan as a video", autonomous=True,
                                     workspace_id="offline", project_id="review", conversation_id="plan-review", job_id="review")
        studio = _context_from_request(request)
        model = ScriptedModel([call("call_editor_tool", {"tool_name": render.name, "arguments": arguments}, "review-render")])
        with patch.dict(os.environ, {"RENDERHAUS_PREMIUM_VIDEO_APPROVAL": "true"}):
            with self.assertRaises(StudioAgentApprovalRequired) as paused:
                await run_with_servers(request, studio, [gateway], model=model)
            gateway.call_tool.assert_not_awaited()
            self.assertIn("cost", paused.exception.approvals[0].description.lower())
            approval = paused.exception.approvals[0]
            resumed = request.model_copy(update={"session_items": paused.exception.session_items,
                                                "resume_state": paused.exception.state,
                                                "approval_decisions": [StudioApprovalDecision(call_id=approval.call_id,
                                                                                             decision="reject", message="Do not render.")]})
            final = {"title": "Plan review pending", "summary": "The render was rejected; questions remain open.",
                     "markdown": "# Open questions\n\nQ1 remains unanswered. No video was rendered.", "filename": "review.md"}
            await run_with_servers(resumed, _context_from_request(resumed), [gateway],
                                   model=ScriptedModel([call("StudioAgentOutput", final, "finish")]))
            gateway.call_tool.assert_not_awaited()

    def test_tts_and_render_keep_existing_cost_approval_rules(self):
        from agent.gateway_executor import tool_needs_approval
        with patch.dict(os.environ, {"RENDERHAUS_PREMIUM_VIDEO_APPROVAL": "true"}):
            self.assertTrue(tool_needs_approval("Remotion___render_timeline", True))
            self.assertTrue(tool_needs_approval("ElevenLabs___text_to_speech_convert", False))
            self.assertFalse(tool_needs_approval("ElevenLabs___text_to_speech_convert", True))

    def test_existing_tts_dry_run_never_reads_keys_or_creates_http_client(self):
        from providers.elevenlabs.api import dispatch_tool
        with patch.dict(os.environ, {"ELEVENLABS_DRY_RUN": "true", "ELEVENLABS_TTS_MODEL": "eleven_v4_turbo"}), \
                patch("providers.elevenlabs.api.api_key") as key, patch("providers.elevenlabs.api.httpx.Client") as client:
            result = dispatch_tool("text_to_speech_convert", {"voice_id": "authorized-voice", "text": "Review the plan."})
        self.assertEqual(result["status"], "dry_run")
        key.assert_not_called()
        client.assert_not_called()
