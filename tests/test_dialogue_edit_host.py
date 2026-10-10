from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mcp import Tool

from agent.deep_agent import routing
from agent.deep_agent.runner import run_with_servers
from agent.gateway_executor import GatewayExecutor, tool_needs_approval
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, StudioToolEvent,
    _context_from_request, _validate_video_delivery,
)
from test_deep_agent import Gateway, ScriptedModel, call, final


SOURCE = {
    "source_video_url": "https://assets.sync.so/test/presenter.mp4",
    "source_duration_seconds": 12.0, "speaker_count": 1,
    "subjects": "Alice authorized her likeness and cloned source voice",
    "consent_confirmed": True,
}
PREVIEW = {
    **SOURCE, "transcription_id": "transcription_1", "action_id": "edit-take-1",
    "edits": [{"kind": "change", "wordId": "w_2", "replacement": "annual"}],
}
VIDEO = {
    **SOURCE, "dialogue_edit_id": "dialogue_1", "source_fps": 25.0,
    "preview_duration_seconds": 10.0, "preview_reviewed": True,
    "idempotency_key": "approved-take-1",
}


class DialogueRoutingTests(unittest.TestCase):
    def test_word_and_phrase_edits_use_dialogue_skill_and_existing_canonical_model(self):
        for prompt in [
            'Change the spoken word "quarterly" to "annual" in this footage',
            'Remove the spoken phrase "limited time" from this video',
            'Fix a flubbed word in my existing presenter clip',
            'Dialogue-edit this 90 second presenter video',
        ]:
            for confidential in (False, True):
                with self.subTest(prompt=prompt, confidential=confidential):
                    route = routing.route_intent(prompt, confidential=confidential)
                    self.assertEqual((route.skill, route.alias, route.model),
                                     ("dialogue-edit", "sync3_lipsync", "sync-3"))
                    self.assertEqual(route.tool, "Sync___create_dialogue_video")
                    self.assertEqual(route.dispatch_tool, "call_media_tool")

    def test_other_editing_intents_keep_their_routes(self):
        cases = {
            "dub this interview clip into Spanish": "lipsync",
            "replace the voice in this video": "lipsync",
            "generate a cartoon talking shot": "t2v",
            "remove filler words and silences from this clip": "conversational-edit",
            'Change the text "quarterly" in this banner': "image-gen",
        }
        for prompt, skill in cases.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(routing.route_intent(prompt).skill, skill)

    def test_multispeaker_and_overlong_dialogue_requests_refuse(self):
        for prompt, arguments, reason in [
            ("Dialogue-edit this multi-speaker interview", {}, "single speaker"),
            ("Dialogue-edit this 11 minute video", {}, "10 minutes"),
            ("Dialogue-edit this footage", {"speaker_count": 2}, "single speaker"),
            ("Dialogue-edit this footage", {"source_duration_seconds": 601.0}, "10 minutes"),
        ]:
            with self.subTest(prompt=prompt, arguments=arguments):
                route = routing.route_intent(prompt, arguments=arguments)
                self.assertEqual(route.status, "blocked")
                self.assertIsNone(route.tool)
                self.assertIn(reason, route.reason)

    def test_explicit_other_provider_is_not_silently_replaced(self):
        route = routing.route_intent('Use Kling to change the spoken word "bad" in this footage')
        self.assertEqual(route.status, "blocked")
        self.assertIn("word-level", route.reason)

    def test_paid_dialogue_steps_pause_even_when_autonomous_and_switch_disabled(self):
        with patch.dict(os.environ, {"RENDERHAUS_PREMIUM_VIDEO_APPROVAL": "false"}):
            for name in ("Sync___create_dialogue_edit", "Sync___create_dialogue_video"):
                for autonomous in (False, True):
                    self.assertTrue(tool_needs_approval(name, autonomous))
        for name in ("Sync___transcribe_video", "Sync___get_transcription", "Sync___get_dialogue_edit"):
            self.assertTrue(routing.is_free_tool(name))
            self.assertEqual(routing.estimate_cost(name, {}).total_cents, 0)

    def test_preview_quote_unknown_by_default_and_dry_run_cost_is_zero(self):
        from server.billing_rates import cost_for

        with patch.dict(os.environ, {"SYNC_DRY_RUN": "true", "SYNC_DIALOGUE_PREVIEW_COST_CENTS": ""}):
            quote = routing.estimate_cost("Sync___create_dialogue_edit", PREVIEW, list_price=True)
            self.assertIsNone(quote.total_cents)
            self.assertIn("unknown", quote.description)
            self.assertEqual(cost_for("sync", "create_dialogue_edit", PREVIEW).total_cents, 0)

    def test_video_quote_uses_direct_host_output_duration_and_fps(self):
        from server.billing_rates import cost_for

        with patch.dict(os.environ, {"SYNC_DRY_RUN": "false", "SYNC_TRANSPORT": "fal",
                                    "SYNC_DIRECT_AUTHORIZED": "true", "SYNC_BILLING_PLAN": "legacy_base"}):
            cost = cost_for("sync", "create_dialogue_video", VIDEO)
            self.assertEqual(cost.provider_cents, 134)
            self.assertEqual(cost_for("sync", "create_dialogue_video", {**VIDEO, "source_fps": 50.0}).provider_cents, 267)
            self.assertEqual(routing.estimate_cost("Sync___create_dialogue_video", VIDEO).total_cents,
                             cost.total_cents)

    def test_host_checks_consent_speaker_duration_before_approval(self):
        executor = GatewayExecutor(_context_from_request(StudioAgentRequest(prompt="Dialogue-edit this footage")), [])
        for name, arguments in [("Sync___create_dialogue_edit", PREVIEW),
                                ("Sync___create_dialogue_video", VIDEO)]:
            with self.subTest(name=name):
                self.assertIsNone(executor.selection_blocker(name, arguments, executor.media_selection(name, arguments)))
                for changes in ({"consent_confirmed": False}, {"consent_confirmed": "true"},
                                {"speaker_count": 2}, {"source_duration_seconds": 601.0}):
                    self.assertIsNotNone(executor.selection_blocker(name, {**arguments, **changes}, None))
                disclosure = executor.dispatch_disclosure(name, arguments, None)
                self.assertIn("direct", disclosure)
                self.assertIn("Alice", disclosure)
                self.assertIn("cloned", disclosure)


class DialogueApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_canvas_invoke_cannot_bypass_dialogue_approval(self):
        from fastapi import HTTPException
        import server.studio as studio

        for tool, arguments in [("create_dialogue_edit", PREVIEW), ("create_dialogue_video", VIDEO)]:
            body = studio.InvokeBody(provider="sync", tool=tool, arguments=arguments, project_id="untitled")
            with self.subTest(tool=tool), patch.object(studio.repository, "require_project"), \
                    patch.object(studio, "dispatch") as dispatch, patch.object(studio, "cost_for") as quote:
                with self.assertRaises(HTTPException) as denied:
                    await studio.invoke_tool(body, None)
                self.assertEqual(denied.exception.status_code, 409)
                self.assertIn("approval", denied.exception.detail.lower())
                dispatch.assert_not_called()
                quote.assert_not_called()

    async def test_preview_and_video_approval_resume_and_rejection(self):
        for name, arguments in [("Sync___create_dialogue_edit", PREVIEW),
                                ("Sync___create_dialogue_video", VIDEO)]:
            for decision in ("approve", "reject"):
                with self.subTest(name=name, decision=decision), tempfile.TemporaryDirectory() as directory:
                    request = StudioAgentRequest(prompt="Dialogue-edit this footage", autonomous=True,
                        workspace_id="w", project_id="p", conversation_id=f"{name}-{decision}", job_id="dialogue")
                    gateway = Gateway([Tool(name=name, inputSchema={"type": "object"})])
                    studio = _context_from_request(request)
                    with patch.dict(os.environ, {"RENDERHAUS_OUTCOME_DIR": directory,
                        "SYNC_DRY_RUN": "true", "SYNC_DIALOGUE_PREVIEW_COST_CENTS": "",
                        "RENDERHAUS_PREMIUM_VIDEO_APPROVAL": "false"}):
                        with self.assertRaises(StudioAgentApprovalRequired) as paused:
                            await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                                call("read_file", {"file_path": "/skills/dialogue-edit/SKILL.md"}, "skill"),
                                call("call_media_tool", {"tool_name": name, "arguments": arguments}, "edit"),
                            ]))
                        gateway.call_tool.assert_not_awaited()
                        approval = paused.exception.approvals[0]
                        self.assertIn("Alice", approval.description)
                        self.assertIn("direct", approval.description)
                        self.assertIn("unknown" if name.endswith("create_dialogue_edit") else "$1.74", approval.description)
                        resumed = request.model_copy(update={
                            "session_items": json.loads(json.dumps(studio.session_items)),
                            "resume_state": paused.exception.state,
                            "approval_decisions": [StudioApprovalDecision(call_id=approval.call_id, decision=decision)],
                        })
                        await run_with_servers(resumed, _context_from_request(resumed), [gateway],
                                               model=ScriptedModel([final()]))
                        if decision == "approve":
                            gateway.call_tool.assert_awaited_once_with(name, arguments)
                        else:
                            gateway.call_tool.assert_not_awaited()

    async def test_unknown_preview_cannot_be_resubmitted_with_a_new_tool_call_id(self):
        request = StudioAgentRequest(prompt="Dialogue-edit this footage", autonomous=True, job_id="dialogue")
        studio = _context_from_request(request)
        name = "Sync___create_dialogue_edit"
        gateway = Gateway([Tool(name=name, inputSchema={"type": "object"})])
        gateway.call_tool.return_value = {"status": "submission_unknown", "action_id": "edit-take-1",
            "next_action": "check_status_or_ask_user", "note": "Do not automatically retry preview creation."}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "RENDERHAUS_OUTCOME_DIR": directory, "SYNC_DRY_RUN": "true",
        }):
            executor = GatewayExecutor(studio, [gateway])
            await executor.execute({"tool_name": name, "arguments": PREVIEW, "call_id": "first"}, approved=True)
            result = await executor.execute({"tool_name": name, "arguments": {**PREVIEW, "action_id": "new-action"},
                                             "call_id": "second"}, approved=True)
        gateway.call_tool.assert_awaited_once()
        self.assertEqual(result["status"], "submission_unknown")

    async def test_lost_gateway_response_does_not_retry_preview(self):
        request = StudioAgentRequest(prompt="Dialogue-edit this footage", autonomous=True, job_id="dialogue")
        studio = _context_from_request(request)
        name = "Sync___create_dialogue_edit"
        gateway = Gateway([Tool(name=name, inputSchema={"type": "object"})])
        gateway.call_tool.side_effect = RuntimeError("Gateway connection lost after dispatch")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "RENDERHAUS_OUTCOME_DIR": directory, "SYNC_DRY_RUN": "true",
        }):
            executor = GatewayExecutor(studio, [gateway])
            first = await executor.execute({"tool_name": name, "arguments": PREVIEW, "call_id": "first"}, approved=True)
            result = await executor.execute({"tool_name": name, "arguments": PREVIEW, "call_id": "second"}, approved=True)
        gateway.call_tool.assert_awaited_once()
        self.assertEqual(first["status"], "submission_unknown")
        self.assertEqual(result["next_action"], "check_status_or_ask_user")


class DialogueDeliveryTests(unittest.TestCase):
    def event(self, name, result, arguments=None):
        return StudioToolEvent(id=name, name=name, label="Dialogue work", summary="Offline result",
                               status=result["status"], result=result, arguments=arguments or {})

    def test_preview_alone_cannot_finish_word_edit_request(self):
        request = StudioAgentRequest(prompt='Change the spoken word "quarterly" in this footage')
        studio = _context_from_request(request)
        studio.tool_events.append(self.event("Sync___get_dialogue_edit", {
            "status": "succeeded", "previewAudioUrl": "https://assets.sync.so/preview.wav"}))
        self.assertFalse(_validate_video_delivery(request, studio))

    def test_only_current_matching_saved_video_can_finish_dialogue_edit(self):
        saved = {"status": "succeeded", "downloaded": True, "mode": "dialogue_edit_video",
                 "output_path": str(Path(__file__).parent / "fixtures/sync-video.mp4")}
        for job, expected in [("new-video", True), ("old-video", False)]:
            request = StudioAgentRequest(prompt="Dialogue-edit this footage")
            studio = _context_from_request(request)
            studio.tool_events.append(self.event("Sync___create_dialogue_video", {"status": "queued", "job_id": "new-video"}))
            studio.tool_events.append(self.event("Sync___get_video_task", {**saved, "job_id": job}, {"job_id": job}))
            self.assertEqual(_validate_video_delivery(request, studio), expected)

    def test_old_video_and_new_preview_cannot_finish_new_edit(self):
        old = self.event("Sync___get_video_task", {"status": "succeeded", "downloaded": True,
            "output_path": str(Path(__file__).parent / "fixtures/sync-video.mp4"), "job_id": "old-video"})
        request = StudioAgentRequest(prompt="Dialogue-edit this footage", prior_tool_events=[old.public()])
        studio = _context_from_request(request)
        studio.tool_events.append(self.event("Sync___create_dialogue_edit", {"status": "queued", "dialogue_edit_id": "new-preview"}))
        self.assertFalse(_validate_video_delivery(request, studio))


if __name__ == "__main__":
    unittest.main()
