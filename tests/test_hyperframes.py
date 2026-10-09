from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage
from agent.deep_agent.runner import run_with_servers
from agent.studio_agent_next import (
    StudioAgentApprovalRequired,
    StudioAgentRequest,
    StudioApprovalDecision,
    _context_from_request,
    _validate_video_delivery,
    StudioToolEvent,
)
from test_deep_agent import ScriptedModel, Gateway, call, final

TOOL_NAME = "HyperFrames___render_composition"
COMPOSITION = {
    "html": "<!doctype html><html><body>Launch</body></html>",
    "duration_seconds": 2,
    "width": 1280,
    "height": 720,
    "fps": 30,
}
PREVIEW_ENV = {"HYPERFRAMES_ENABLED": "true", "HYPERFRAMES_DRY_RUN": "true"}


class HyperFramesRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_defaults_hide_tool_and_never_render(self):
        from agent.hyperframes import HyperFramesServer, enabled, dry_run

        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(enabled())
            self.assertTrue(dry_run())
            server = HyperFramesServer()
            self.assertEqual(await server.list_tools(), [])
            result = await server.call_tool(TOOL_NAME, COMPOSITION)
        self.assertEqual(result["status"], "not_run")
        self.assertIn("disabled", result["reason"].lower())
        self.assertFalse({"url", "output_path", "job_id", "render_id"} & result.keys())

    async def test_preview_returns_no_fabricated_artifact(self):
        from agent.hyperframes import HyperFramesServer

        with patch.dict(os.environ, PREVIEW_ENV):
            server = HyperFramesServer()
            tools = await server.list_tools()
            self.assertEqual([tool.name for tool in tools], [TOOL_NAME])
            result = await server.call_tool(TOOL_NAME, COMPOSITION)
        self.assertEqual(result["status"], "dry_run")
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["composition"], {key: value for key, value in COMPOSITION.items() if key != "html"})
        self.assertFalse({"url", "output_path", "job_id", "render_id"} & result.keys())

    async def test_enabled_server_rechecks_flag_at_dispatch(self):
        from agent.hyperframes import HyperFramesServer

        server = HyperFramesServer()
        with patch.dict(os.environ, PREVIEW_ENV):
            self.assertEqual(len(await server.list_tools()), 1)
        with patch.dict(os.environ, {"HYPERFRAMES_ENABLED": "false"}):
            result = await server.call_tool(TOOL_NAME, COMPOSITION)
        self.assertEqual(result["status"], "not_run")
        self.assertIn("disabled", result["reason"].lower())

    async def test_live_request_fails_closed_without_renderer(self):
        from agent.hyperframes import HyperFramesServer

        with patch.dict(os.environ, {**PREVIEW_ENV, "HYPERFRAMES_DRY_RUN": "false"}):
            result = await HyperFramesServer().call_tool(TOOL_NAME, COMPOSITION)
        self.assertEqual(result["status"], "not_run")
        self.assertIn("isolated renderer not configured", result["reason"].lower())
        self.assertFalse({"url", "output_path", "job_id", "render_id"} & result.keys())

    async def test_schema_rejects_invalid_and_unbounded_compositions(self):
        from agent.hyperframes import HyperFramesServer

        with patch.dict(os.environ, PREVIEW_ENV):
            server = HyperFramesServer()
            for changes in [
                {"html": ""}, {"html": "x" * 200001}, {"duration_seconds": 0},
                {"duration_seconds": 301}, {"width": 3841}, {"height": 2161},
                {"fps": 0}, {"fps": 61}, {"width": True}, {"fps": 29.97},
                {"duration_seconds": float("nan")},
                {"command": "npx hyperframes"},
            ]:
                with self.subTest(changes=list(changes)):
                    result = await server.call_tool(TOOL_NAME, {**COMPOSITION, **changes})
                    self.assertEqual(result["status"], "not_run")
                    self.assertIn("schema", result["reason"].lower())
            result = await server.call_tool("HyperFrames___unknown", COMPOSITION)
            self.assertEqual(result["status"], "not_run")


class HyperFramesRoutingTests(unittest.TestCase):
    def test_explicit_disabled_request_is_blocked_without_fallback(self):
        from agent.deep_agent.routing import route_intent, policy_blocker

        with patch.dict(os.environ, {"HYPERFRAMES_ENABLED": "false"}):
            for prompt in ["HTML CSS kinetic titles with HyperFrames", "product launch HyperFrames plus ElevenLabs VO"]:
                route = route_intent(prompt)
                self.assertEqual(route.skill, "hyperframes")
                self.assertEqual(route.status, "blocked")
                self.assertIsNone(route.tool)
            self.assertIn("disabled", policy_blocker(TOOL_NAME, COMPOSITION).lower())

    def test_enabled_explicit_renderer_uses_editor_role(self):
        from agent.deep_agent.routing import route_intent, policy_blocker

        with patch.dict(os.environ, PREVIEW_ENV):
            route = route_intent("HTML CSS kinetic titles with HyperFrames")
            self.assertEqual((route.skill, route.tool, route.dispatch_tool, route.status),
                             ("hyperframes", TOOL_NAME, "call_editor_tool", "ready"))
            self.assertIsNone(policy_blocker(TOOL_NAME, COMPOSITION))

    def test_explicit_renderer_cannot_claim_an_unavailable_tool(self):
        from agent.deep_agent.routing import route_intent

        with patch.dict(os.environ, PREVIEW_ENV):
            route = route_intent("HTML kinetic titles with HyperFrames", available_tools=set())
            self.assertEqual(route.status, "blocked")
            self.assertIsNone(route.tool)
            self.assertIn("unavailable", route.reason.lower())
            compound = route_intent("HyperFrames plus ElevenLabs voiceover",
                                    available_tools={"ElevenLabs___text_to_speech_convert"})
            self.assertEqual(compound.status, "blocked")
            self.assertIsNone(compound.tool)

    def test_requested_voiceover_keeps_hyperframes_workflow_and_audio_role(self):
        from agent.deep_agent.routing import route_intent

        with patch.dict(os.environ, PREVIEW_ENV):
            for prompt in ["product launch video HyperFrames plus ElevenLabs VO", "ElevenLabs voiceover for HyperFrames product launch"]:
                route = route_intent(prompt)
                self.assertEqual((route.skill, route.tool, route.dispatch_tool, route.status),
                                 ("hyperframes", "ElevenLabs___text_to_speech_convert", "call_audio_tool", "ready"))

    def test_remotion_remains_default_even_when_hyperframes_enabled(self):
        from agent.deep_agent.routing import route_intent

        for enabled in ["true", "false"]:
            with patch.dict(os.environ, {"HYPERFRAMES_ENABLED": enabled}):
                for prompt in ["Remotion lower thirds", "kinetic titles brand kit"]:
                    route = route_intent(prompt)
                    self.assertEqual((route.skill, route.tool), ("motion-graphics", "Remotion___render_timeline"))

    def test_compute_price_stays_unknown_and_approval_policy_unchanged(self):
        from agent.deep_agent.routing import estimate_cost, is_free_tool
        from agent.gateway_executor import APPROVAL_EXEMPT_TOOLS, tool_needs_approval

        with patch.dict(os.environ, PREVIEW_ENV):
            for list_price in [True, False]:
                quote = estimate_cost(TOOL_NAME, COMPOSITION, list_price=list_price)
                self.assertIsNone(quote.total_cents)
                self.assertIn("unknown", quote.description.lower())
            self.assertFalse(is_free_tool(TOOL_NAME))
            self.assertTrue(tool_needs_approval(TOOL_NAME, False))
            self.assertFalse(tool_needs_approval(TOOL_NAME, True))
        self.assertEqual(APPROVAL_EXEMPT_TOOLS, frozenset({"Remotion___export_nle_timeline"}))

    def test_apache_skill_license_does_not_authorize_training_on_compositions(self):
        from agent.deep_agent.routing import training_eligible

        with patch.dict(os.environ, PREVIEW_ENV):
            self.assertFalse(training_eligible({
                "provider": "hyperframes", "model": "html", "weights_license": "Apache-2.0",
                "training_eligible": True, "status": "succeeded",
            }))


class HyperFramesGraphTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        skill = root / "hyperframes" / "SKILL.md"
        skill.parent.mkdir()
        skill.write_text("---\nname: hyperframes\ndescription: Optional HTML motion preview\n"
                         "metadata:\n  include_tools: call_editor_tool call_audio_tool\n"
                         f"  gateway_tools: {TOOL_NAME} ElevenLabs___text_to_speech_convert\n"
                         "---\nPreview an HTML composition after discovering its exact schema.\n")
        self.addCleanup(self.directory.cleanup)
        self.skill_patch = patch("agent.deep_agent.runner.SKILLS_ROOT", root)
        self.skill_patch.start()
        self.addCleanup(self.skill_patch.stop)
        self.env_patch = patch.dict(os.environ, {**PREVIEW_ENV, "RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": ""})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def request(self, **changes):
        return StudioAgentRequest(prompt="Preview HTML kinetic titles with HyperFrames",
                                  workspace_id="workspace", project_id="project",
                                  conversation_id="conversation", job_id="job", **changes)

    def read_skill(self):
        return call("read_file", {"file_path": "/skills/hyperframes/SKILL.md"}, "skill")

    def render(self, dispatch="call_editor_tool"):
        return call(dispatch, {"tool_name": TOOL_NAME, "arguments": COMPOSITION}, "preview")

    async def test_skill_read_preserves_dispatch_tools_and_previews_with_editor(self):
        from agent.hyperframes import HyperFramesServer

        bound_tools = set()

        def before(messages, tools):
            self.assertTrue({"call_editor_tool", "call_audio_tool", "call_media_tool"}.issubset(tools))
            self.assertNotIn("Seedream___text_to_image", tools)
            bound_tools.update(tools)
            return self.read_skill()

        def after(messages, tools):
            self.assertEqual(tools, bound_tools)
            self.assertIn("Preview an HTML composition", messages[-1].text)
            return self.render()

        request = self.request(autonomous=True)
        studio = _context_from_request(request)
        await run_with_servers(request, studio, [HyperFramesServer()], model=ScriptedModel([before, after, final()]))
        self.assertEqual(studio.tool_events[0].name, TOOL_NAME)
        self.assertEqual(studio.tool_events[0].status, "dry_run")
        self.assertFalse(_validate_video_delivery(request, studio))

    async def pause(self, server):
        request = self.request()
        studio = _context_from_request(request)
        with self.assertRaises(StudioAgentApprovalRequired) as raised:
            await run_with_servers(request, studio, [server], model=ScriptedModel([self.read_skill(), self.render()]))
        approval = raised.exception.approvals[0]
        self.assertEqual(approval.tool_name, TOOL_NAME)
        self.assertIsNone(approval.estimated_cost["total_cents"])
        self.assertIn("unknown", approval.description.lower())
        server.call_tool.assert_not_awaited()
        return studio, raised.exception

    async def test_approval_resumes_fresh_worker_once_and_returns_preview(self):
        from agent.hyperframes import HyperFramesServer

        server = HyperFramesServer()
        server.call_tool = AsyncMock(wraps=server.call_tool)
        studio, paused = await self.pause(server)
        resumed = self.request(session_items=json.loads(json.dumps(studio.session_items)), resume_state=paused.state,
                               approval_decisions=[StudioApprovalDecision(call_id=paused.approvals[0].call_id, decision="approve")])
        restored = _context_from_request(resumed)
        await run_with_servers(resumed, restored, [server], model=ScriptedModel([final()]))
        server.call_tool.assert_awaited_once_with(TOOL_NAME, COMPOSITION)
        self.assertEqual(restored.tool_events[0].id, paused.approvals[0].call_id)
        self.assertEqual(restored.tool_events[0].status, "dry_run")

    async def test_editor_subagent_retains_role_restrictions_and_native_approval(self):
        from agent.hyperframes import HyperFramesServer

        server = HyperFramesServer()
        server.call_tool = AsyncMock(wraps=server.call_tool)
        request = self.request()
        studio = _context_from_request(request)

        def editor_render(messages, tools):
            self.assertIn("Renderhaus editor", messages[0].text)
            self.assertIn("call_editor_tool", tools)
            self.assertNotIn("call_audio_tool", tools)
            self.assertNotIn("call_media_tool", tools)
            return self.render()

        with self.assertRaises(StudioAgentApprovalRequired) as raised:
            await run_with_servers(request, studio, [server], model=ScriptedModel([
                call("task", {"subagent_type": "editor", "description": "Preview the explicit HyperFrames composition"}, "editor"),
                self.read_skill(), editor_render,
            ]))
        approval = raised.exception.approvals[0]
        server.call_tool.assert_not_awaited()
        self.assertEqual(approval.tool_name, TOOL_NAME)
        self.assertIsNone(approval.estimated_cost["total_cents"])
        resumed = self.request(session_items=json.loads(json.dumps(studio.session_items)),
                               resume_state=raised.exception.state,
                               approval_decisions=[StudioApprovalDecision(call_id=approval.call_id, decision="approve")])
        restored = _context_from_request(resumed)
        await run_with_servers(resumed, restored, [server], model=ScriptedModel([
            AIMessage(content="Composition preview only. No rendered MP4 is available."), final(),
        ]))
        server.call_tool.assert_awaited_once_with(TOOL_NAME, COMPOSITION)
        self.assertEqual(restored.tool_events[0].status, "dry_run")

    async def test_rejection_never_calls_local_renderer(self):
        from agent.hyperframes import HyperFramesServer

        server = HyperFramesServer()
        server.call_tool = AsyncMock(wraps=server.call_tool)
        studio, paused = await self.pause(server)
        resumed = self.request(session_items=studio.session_items, resume_state=paused.state,
                               approval_decisions=[StudioApprovalDecision(call_id=paused.approvals[0].call_id, decision="reject")])
        restored = _context_from_request(resumed)
        await run_with_servers(resumed, restored, [server], model=ScriptedModel([final()]))
        server.call_tool.assert_not_awaited()
        self.assertEqual(restored.tool_events[0].status, "rejected")

    async def test_disable_after_approval_blocks_fresh_worker_dispatch(self):
        from agent.hyperframes import HyperFramesServer

        server = HyperFramesServer()
        server.call_tool = AsyncMock(wraps=server.call_tool)
        studio, paused = await self.pause(server)
        resumed = self.request(session_items=studio.session_items, resume_state=paused.state,
                               approval_decisions=[StudioApprovalDecision(call_id=paused.approvals[0].call_id, decision="approve")])
        with patch.dict(os.environ, {"HYPERFRAMES_ENABLED": "false"}):
            await run_with_servers(resumed, _context_from_request(resumed), [server], model=ScriptedModel([final()]))
        server.call_tool.assert_not_awaited()

    async def test_unknown_compute_cost_stops_autonomous_dispatch_with_cap(self):
        from agent.hyperframes import HyperFramesServer

        server = HyperFramesServer()
        server.call_tool = AsyncMock(wraps=server.call_tool)
        request = self.request(autonomous=True)
        studio = _context_from_request(request)
        with patch.dict(os.environ, {"RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": "100"}):
            await run_with_servers(request, studio, [server], model=ScriptedModel([self.read_skill(), self.render(), final()]))
        server.call_tool.assert_not_awaited()
        spending = next(item["spending"] for item in studio.session_items if "spending" in item)
        self.assertTrue(spending["stopped"])
        self.assertEqual(spending["reservations"], {})

    async def test_default_disabled_gate_blocks_an_approved_stale_schema(self):
        from agent.hyperframes import HYPERFRAMES_TOOL
        from agent.gateway_executor import GatewayExecutor

        gateway = Gateway([HYPERFRAMES_TOOL])
        studio = _context_from_request(self.request())
        with patch.dict(os.environ, {}, clear=True):
            result = await GatewayExecutor(studio, [gateway]).execute({
                "tool_name": TOOL_NAME, "arguments": COMPOSITION, "call_id": "stale-schema",
            }, approved=True)
        self.assertEqual(result["status"], "not_run")
        self.assertIn("disabled", result["reason"].lower())
        gateway.call_tool.assert_not_awaited()

    async def test_local_schema_is_not_saved_or_restored_as_a_remote_gateway_tool(self):
        from agent.hyperframes import HYPERFRAMES_TOOL, HyperFramesServer
        from agent.gateway_executor import GatewayExecutor
        from agent.studio_agent_next import GatewayMCPServer

        studio = _context_from_request(self.request())
        local = HyperFramesServer()
        executor = GatewayExecutor(studio, [local])
        await executor.connect_tools()
        self.assertEqual(executor.snapshot()["gateway_tools"], [])
        remote = GatewayMCPServer({"url": "https://unused.invalid"}, name="gateway")
        remote._tools_list = []
        restored = GatewayExecutor(studio, [remote, local])
        with patch.dict(os.environ, {"HYPERFRAMES_ENABLED": "false"}):
            await restored.connect_tools({"gateway_tools": [HYPERFRAMES_TOOL.model_dump(by_alias=True)]})
            self.assertNotIn(TOOL_NAME, await restored.available())
        self.assertNotIn(TOOL_NAME, remote._discovered_tool_names)

    def test_prior_preview_does_not_invalidate_a_later_default_remotion_video(self):
        request = self.request().model_copy(update={"prompt": "Make a 5 second video of a red car"})
        studio = _context_from_request(request)
        studio.tool_events = [
            StudioToolEvent(id="old-preview", name=TOOL_NAME, label="Previous preview", status="dry_run",
                            summary="No MP4", result={"status": "dry_run"}),
            StudioToolEvent(id="current-remotion", name="Remotion___get_render_progress",
                            label="Completed render", status="succeeded", summary="Current MP4",
                            result={"status": "succeeded", "url": "https://cdn.example/current.mp4"}),
        ]
        self.assertTrue(_validate_video_delivery(request, studio))

    def test_saved_remotion_artifact_cannot_complete_a_hyperframes_export(self):
        request = self.request().model_copy(update={"prompt": "Make a HyperFrames video"})
        studio = _context_from_request(request)
        studio.tool_events = [
            StudioToolEvent(id="old-remotion", name="Remotion___get_render_progress",
                            label="Previous render", status="succeeded", summary="Previous MP4",
                            result={"status": "succeeded", "url": "https://cdn.example/previous.mp4"}),
        ]
        self.assertFalse(_validate_video_delivery(request, studio))
        studio.tool_events.append(StudioToolEvent(
            id="new-preview", name=TOOL_NAME, label="HyperFrames preview", status="dry_run",
            summary="No MP4", result={"status": "dry_run", "dry_run": True},
        ))
        self.assertFalse(_validate_video_delivery(request, studio))
        switched = request.model_copy(update={"prompt": "Use Remotion lower thirds instead"})
        self.assertTrue(_validate_video_delivery(switched, studio))

    async def test_media_role_cannot_dispatch_hyperframes(self):
        request = self.request(autonomous=True)
        studio = _context_from_request(request)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "media" / "SKILL.md"
            skill.parent.mkdir()
            skill.write_text("---\nname: media\ndescription: Media generation\n"
                             "metadata:\n  include_tools: call_media_tool\n---\nMedia only.\n")
            with patch("agent.deep_agent.runner.SKILLS_ROOT", root):
                model = ScriptedModel([
                    call("read_file", {"file_path": "/skills/media/SKILL.md"}, "skill"),
                    self.render("call_media_tool"), final(),
                ])
                gateway = Gateway([])
                await run_with_servers(request, studio, [gateway], model=model)
        gateway.call_tool.assert_not_awaited()
        messages = model._seen[-1][0]
        self.assertIn("This role cannot call that provider", "\n".join(message.text for message in messages))

    async def test_production_entrypoint_injects_local_tool_only_when_enabled(self):
        from agent.studio_agent_next import run_studio_agent

        request = self.request()
        for enabled in ["true", "false"]:
            with patch.dict(os.environ, {"HYPERFRAMES_ENABLED": enabled}), patch(
                "agent.deep_agent.runner.run_with_servers", new=AsyncMock()
            ) as run:
                await run_studio_agent(request, mcp_servers=[Gateway([])])
                servers = run.await_args.args[2]
                names = [tool.name for server in servers for tool in await server.list_tools()]
                self.assertEqual(TOOL_NAME in names, enabled == "true")

    async def test_codex_entrypoint_keeps_optional_tool_outside_its_catalog(self):
        from agent.studio_agent_next import run_studio_agent

        with patch("agent.studio_codex_runner.run_with_servers", new=AsyncMock()) as run:
            await run_studio_agent(self.request(), harness=object(), mcp_servers=[Gateway([])])
            servers = run.await_args.args[3]
            names = [tool.name for server in servers for tool in await server.list_tools()]
        self.assertNotIn(TOOL_NAME, names)
