from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mcp import Tool
from langchain_core.messages import AIMessage

from agent.deep_agent.runner import run_with_servers
from agent.deep_agent.routing import estimate_cost, route_intent
from agent.gateway_executor import APPROVAL_EXEMPT_TOOLS, tool_needs_approval
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, _context_from_request,
)
from test_deep_agent import Gateway, ScriptedModel, call, final


PREPARE = Tool(
    name="Remotion___prepare_conversational_edit", description="Prepare word-boundary cuts",
    inputSchema={"type": "object", "properties": {
        "plan_summary": {"type": "string"}, "sources": {"type": "array"},
        "segments": {"type": "array"}, "title": {"type": "string"},
    }, "required": ["plan_summary", "sources", "segments", "title"]},
)
SUMMARY = "Keep the answer, remove the um and long pause, use a neutral grade and bold subtitles."
ARGS = {
    "plan_summary": SUMMARY, "title": "Interview cut",
    "sources": [{"id": "take", "url": "renderhaus-asset://owned-v1", "duration_seconds": 4,
                 "words": [{"text": "um", "start": .1, "end": .3},
                           {"text": "Hello", "start": 1, "end": 1.4}]}],
    "segments": [{"source_id": "take", "first_word": 1, "last_word": 1}],
}


def read_edit():
    return call("read_file", {"file_path": "/skills/conversational-edit/SKILL.md"}, "read-edit")


def prepare():
    return call("call_editor_tool", {"tool_name": PREPARE.name, "arguments": ARGS}, "prepare")


class ConversationalRoutingTests(unittest.TestCase):
    def test_csv_rows_are_retained_with_exact_aliases_and_explicit_skips(self):
        cases = json.loads((Path(__file__).parent / "fixtures/skill_routing.json").read_text())
        rows = [case for case in cases if case["suite"] == "conversational-edit"]
        self.assertEqual([(row["prompt"], row["expected_tool"]) for row in rows], [
            ("cut filler ums and burn bold captions on this interview", "local_qc"),
            ("conversational edit talking head with HyperFrames overlays", "hyperframes_render"),
            ("export the edit to OTIO after agent cut", "otio_export"),
        ])
        self.assertTrue(rows[0]["skip_reason"])
        self.assertTrue(rows[1]["skip_reason"])
        self.assertFalse(rows[2]["skip_reason"])

    def test_editorial_intents_do_not_select_generation_or_lipsync(self):
        for prompt in [
            "cut filler ums and burn bold captions on this interview",
            "remove filler words and silences from this talking head",
            "conversational edit this existing footage with lower thirds",
            "make a transcript-driven cut of the generated tutorial",
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual((route.skill, route.tool, route.dispatch_tool, route.status),
                                 ("conversational-edit", PREPARE.name, "call_editor_tool", "ready"))

    def test_handoff_after_agent_cut_keeps_the_edit_skill(self):
        route = route_intent("export the edit to OTIO after agent cut")
        self.assertEqual((route.skill, route.tool),
                         ("conversational-edit", "Remotion___export_nle_timeline"))
        self.assertEqual(route_intent("export timeline to Resolve").skill, "resolve-handoff")
        self.assertEqual(route_intent("restyle this footage keep motion Aleph").skill, "edit-v2v")
        self.assertEqual(route_intent("edit multi-shot footage faithfully").skill, "edit-v2v")
        self.assertEqual(route_intent("TTS then talking head").skill, "lipsync")

    def test_hyperframes_request_is_explicitly_pending(self):
        route = route_intent("conversational edit talking head with HyperFrames overlays")
        self.assertEqual((route.skill, route.status), ("conversational-edit", "pending"))
        self.assertIsNone(route.tool)
        self.assertIn("HyperFrames", route.reason)

    def test_free_preparation_has_a_separate_plan_gate(self):
        from server.billing_rates import cost_for

        self.assertEqual(APPROVAL_EXEMPT_TOOLS, frozenset({"Remotion___export_nle_timeline"}))
        for autonomous in (False, True):
            self.assertTrue(tool_needs_approval(PREPARE.name, autonomous))
        self.assertEqual(estimate_cost(PREPARE.name, ARGS).total_cents, 0)
        self.assertEqual(cost_for("remotion", "prepare_conversational_edit", ARGS).total_cents, 0)
        self.assertTrue(tool_needs_approval("ElevenLabs___speech_to_text_convert", False))
        self.assertFalse(tool_needs_approval("ElevenLabs___speech_to_text_convert", True))
        self.assertIsNone(estimate_cost("ElevenLabs___speech_to_text_convert", {}).total_cents)

    def test_local_preparation_preserves_asset_handles_without_publication(self):
        studio = _context_from_request(StudioAgentRequest(prompt="Cut the interview"))
        studio.source_publisher = Mock(side_effect=AssertionError("No publishing for a pure plan"))
        original = copy.deepcopy(ARGS)
        self.assertEqual(studio.prepare_gateway_arguments(PREPARE.name, ARGS), original)
        self.assertEqual(ARGS, original)
        studio.source_publisher.assert_not_called()


class ConversationalGraphTests(unittest.IsolatedAsyncioTestCase):
    def request(self, **changes):
        return StudioAgentRequest(
            prompt="cut filler ums and burn bold captions on this interview",
            workspace_id="workspace", project_id="project", conversation_id="edit", job_id="job",
            **changes,
        )

    async def invoke(self, request, steps, gateway):
        studio = _context_from_request(request)
        model = ScriptedModel(steps)
        await run_with_servers(request, studio, [gateway], model=model)
        self.assertFalse(model._steps)
        return studio

    async def test_autonomous_plan_pauses_and_fresh_worker_approves_exactly_once(self):
        request = self.request(autonomous=True)
        studio = _context_from_request(request)
        gateway = Gateway([PREPARE], {"status": "dry_run", "render_arguments": {}})
        with self.assertRaises(StudioAgentApprovalRequired) as pending:
            await run_with_servers(request, studio, [gateway], model=ScriptedModel([read_edit(), prepare()]))
        gateway.call_tool.assert_not_awaited()
        approval = pending.exception.approvals[0]
        self.assertEqual(approval.tool_name, PREPARE.name)
        self.assertIn(SUMMARY, approval.description)
        self.assertIn("$0.00", approval.description)
        resumed = self.request(
            autonomous=True, session_items=json.loads(json.dumps(studio.session_items)),
            resume_state=pending.exception.state,
            approval_decisions=[StudioApprovalDecision(call_id=approval.call_id, decision="approve")],
        )
        restored = await self.invoke(resumed, [final()], gateway)
        gateway.call_tool.assert_awaited_once_with(PREPARE.name, ARGS)
        self.assertEqual(restored.tool_events[0].id, approval.call_id)
        self.assertEqual(restored.tool_events[0].status, "dry_run")

    async def test_rejected_plan_never_calls_gateway_or_starts_a_retry(self):
        request = self.request(autonomous=True)
        studio = _context_from_request(request)
        gateway = Gateway([PREPARE])
        with self.assertRaises(StudioAgentApprovalRequired) as pending:
            await run_with_servers(request, studio, [gateway], model=ScriptedModel([read_edit(), prepare()]))
        approval = pending.exception.approvals[0]
        restored = await self.invoke(self.request(
            autonomous=True, session_items=studio.session_items, resume_state=pending.exception.state,
            approval_decisions=[StudioApprovalDecision(call_id=approval.call_id, decision="reject")],
        ), [final()], gateway)
        gateway.call_tool.assert_not_awaited()
        self.assertEqual(restored.tool_events[0].status, "rejected")
        self.assertEqual(restored.session_items[0]["rejected_reviews"], {})

    async def test_editor_subagent_gets_only_editor_dispatch(self):
        gateway = Gateway([PREPARE])

        def check(messages, tools):
            self.assertIn("call_editor_tool", tools)
            self.assertNotIn("call_audio_tool", tools)
            self.assertNotIn("call_media_tool", tools)
            return AIMessage(
                content="The cut plan is ready for the manager to propose.")

        await self.invoke(self.request(autonomous=True), [
            call("task", {"subagent_type": "editor", "description": "Plan cuts for owned-v1."}, "editor"),
            read_edit(), check, final(),
        ], gateway)
        gateway.call_tool.assert_not_awaited()

    async def test_paid_transcription_still_pauses_and_unknown_cap_blocks_autonomous(self):
        scribe = Tool(name="ElevenLabs___speech_to_text_convert", description="Transcribe",
                      inputSchema={"type": "object", "properties": {"model_id": {"type": "string"}},
                                   "required": ["model_id"]})
        gateway = Gateway([scribe])
        transcribe = call("call_audio_tool", {"tool_name": scribe.name,
                                             "arguments": {"model_id": "scribe_v2"}}, "scribe")
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "RENDERHAUS_OUTCOME_DIR": directory, "ELEVENLABS_TOOL_COST_CENTS_JSON": "{}",
        }):
            with self.assertRaises(StudioAgentApprovalRequired) as pending:
                await self.invoke(self.request(), [read_edit(), transcribe], gateway)
            self.assertIn("unknown", pending.exception.approvals[0].description.lower())
            gateway.call_tool.assert_not_awaited()
            with patch.dict(os.environ, {"RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": "100"}):
                await self.invoke(self.request(autonomous=True), [read_edit(), transcribe, final()], gateway)
            gateway.call_tool.assert_not_awaited()
            self.assertFalse(list(Path(directory).glob("*.jsonl")))

    async def test_confidential_project_refuses_paid_scribe(self):
        scribe = Tool(name="ElevenLabs___speech_to_text_convert", description="Transcribe",
                      inputSchema={"type": "object", "properties": {}})
        gateway = Gateway([scribe])
        await self.invoke(self.request(autonomous=True, confidential=True), [
            read_edit(), call("call_audio_tool", {"tool_name": scribe.name, "arguments": {}}, "scribe"), final(),
        ], gateway)
        gateway.call_tool.assert_not_awaited()

    async def test_approved_plan_compiles_and_renders_only_a_dry_run(self):
        from providers.catalog import get_provider
        from providers.registry import dispatch, load_committed_schemas

        tools = [Tool(name=f"Remotion___{tool['name']}", description=tool["description"],
                      inputSchema=tool["inputSchema"])
                 for tool in load_committed_schemas(get_provider("remotion"))]
        gateway = Gateway(tools)
        compiled = {}

        async def local_dispatch(name, arguments):
            result = dispatch("remotion", name.split("___", 1)[1], arguments)
            if name == PREPARE.name:
                compiled.update(result)
            return result

        def render(messages, available):
            self.assertEqual(compiled["transcript"]["text"], "Hello")
            self.assertEqual(compiled["timeline"]["document"]["tracks"][-1]["name"], "Subtitles")
            return call("call_editor_tool", {"tool_name": "Remotion___render_timeline",
                                             "arguments": compiled["render_arguments"]}, "render")

        gateway.call_tool.side_effect = local_dispatch
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
            "RENDERHAUS_OUTCOME_DIR": directory, "REMOTION_DRY_RUN": "true",
            "RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": "",
        }), patch("socket.socket.connect", side_effect=AssertionError("No network")):
            studio = _context_from_request(self.request(autonomous=True))
            with self.assertRaises(StudioAgentApprovalRequired) as pending:
                await run_with_servers(self.request(autonomous=True), studio, [gateway],
                                       model=ScriptedModel([read_edit(), prepare()]))
            gateway.call_tool.assert_not_awaited()
            approval = pending.exception.approvals[0]
            restored = await self.invoke(self.request(
                autonomous=True, session_items=studio.session_items, resume_state=pending.exception.state,
                approval_decisions=[StudioApprovalDecision(call_id=approval.call_id, decision="approve")],
            ), [render, call("call_editor_tool", {
                "tool_name": "Remotion___get_render_progress", "arguments": {"render_id": "dry-run"},
            }, "poll"), final()], gateway)
            self.assertEqual(gateway.call_tool.await_count, 3)
            self.assertEqual([event.status for event in restored.tool_events], ["dry_run"] * 3)
            self.assertFalse(restored.session_items[0]["media_jobs"])
            self.assertFalse(list(Path(directory).glob("*.jsonl")))
            self.assertTrue(all(not event.assets for event in restored.tool_events))


class ConversationalStudioTests(unittest.IsolatedAsyncioTestCase):
    async def test_invoke_pure_plan_does_not_publish_or_ingest_source_media(self):
        from server.studio import InvokeBody, invoke_tool
        from server.studio_state import StudioRepository

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = StudioRepository(root / "studio.sqlite3", root / "media")
            repository.create_project("workspace", "user", "Interview", project_id="project")
            preview = {"status": "dry_run", "render_arguments": {
                "visuals": [{"url": "https://example.test/take.mp4", "kind": "video"}],
            }}
            with (
                patch("server.studio.repository", repository),
                patch("server.studio.current_workspace_id", return_value="workspace"),
                patch("server.studio.current_user_id", return_value="user"),
                patch("server.studio.stripe_enabled", return_value=False),
                patch("server.studio.publish_provider_input_url", side_effect=AssertionError("No publishing")),
                patch.object(repository, "register_source", side_effect=AssertionError("No media ingestion")),
                patch("server.studio.dispatch", return_value=preview) as dispatch,
            ):
                result = await invoke_tool(InvokeBody(
                    provider="remotion", tool="prepare_conversational_edit", project_id="project",
                    arguments=copy.deepcopy(ARGS),
                ), SimpleNamespace())
            dispatch.assert_called_once_with("remotion", "prepare_conversational_edit", ARGS)
            self.assertEqual(result["assets"], [])
            self.assertEqual(result["cost"]["total_cents"], 0)
            self.assertEqual(result["result"], preview)
