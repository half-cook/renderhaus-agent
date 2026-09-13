from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
import unittest
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import AsyncMock, patch

from mcp import Tool
from mcp.types import CallToolResult, TextContent

from agent.codex_harness import (
    AppServer,
    CodexProtocolError,
    SESSION_TYPE,
)
from agent.gateway_client import GatewayClient
from agent.studio_agent_next import (
    GatewayMCPServer,
    StudioAgentApprovalRequired,
    StudioAgentContext,
    StudioAgentRequest,
    StudioApprovalDecision,
    StudioToolEvent,
    _GATEWAY_SEARCH_TOOL,
    _agent_model,
    run_studio_agent,
)

FINAL = {
    "title": "Launch outline",
    "summary": "Your outline is ready.",
    "markdown": "# Launch outline",
    "filename": "../Launch outline",
}
IMAGE_TOOL = Tool(
    name="Seedream___text_to_image",
    description="Generate an image",
    inputSchema={
        "type": "object",
        "properties": {"prompt": {"type": "string"}},
        "required": ["prompt"],
        "additionalProperties": False,
    },
)
SEARCH_TOOL = Tool(
    name=_GATEWAY_SEARCH_TOOL,
    description="Search tools",
    inputSchema={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
)


class FakeHarness:
    def __init__(self, calls=(), failure=None):
        self.calls, self.failure = calls, failure
        self.session = None
        self.kwargs = None
        self.results = []

    async def run(self, **kwargs):
        self.kwargs = kwargs
        self.session = {
            "type": SESSION_TYPE,
            "version": 1,
            "thread_id": "thread-1",
            "rollout_path": "sessions/rollout.jsonl",
            "rollout": "native history",
        }
        if self.failure:
            raise self.failure
        kwargs["on_event"](
            "item/completed",
            {
                "item": {
                    "id": "update-1",
                    "type": "agentMessage",
                    "phase": "commentary",
                    "text": "I found the image.",
                }
            },
        )
        for call in self.calls:
            self.results.append(await kwargs["call_tool"](call))
        return json.dumps(FINAL)


def image_call(call_id="image-1", **args):
    return {
        "callId": call_id,
        "tool": "call_gateway_tool",
        "arguments": {
            "tool_name": IMAGE_TOOL.name,
            "arguments_json": json.dumps(args or {"prompt": "Product hero"}),
        },
    }


class FakeGateway:
    def __init__(self):
        self.calls = []

    async def list_tools(self):
        return [IMAGE_TOOL]

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {"status": "succeeded", "image_url": "https://cdn.example/hero.png"}


class StudioCodexTests(unittest.IsolatedAsyncioTestCase):
    async def test_structured_artifact_history_and_model_configuration(self):
        harness = FakeHarness()
        studio = StudioAgentContext()
        prior = [{"role": "assistant", "content": "Use a quiet product reveal."}]
        with patch.dict(os.environ, {"AGENT_MODEL": "openai:gpt-5.6-luna"}):
            result = await run_studio_agent(
                StudioAgentRequest(prompt="Create a launch outline", session_items=prior),
                studio=studio,
                harness=harness,
                mcp_servers=[],
            )
        self.assertEqual(result.filename, "Launch-outline.md")
        self.assertEqual(harness.kwargs["legacy_items"], prior)
        self.assertNotIn("quiet product reveal", harness.kwargs["prompt"])
        self.assertEqual(harness.kwargs["model"], "gpt-5.6-luna")
        self.assertFalse(harness.kwargs["output_schema"]["additionalProperties"])
        self.assertEqual(studio.session_items[0]["thread_id"], "thread-1")
        self.assertEqual(studio.progress_events[0].message, "I found the image.")

    async def test_pending_media_waits_in_host_and_keeps_one_tool_step(self):
        tool = Tool(name="Mureka___query_music_task", description="Poll music",
                    inputSchema={"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]})
        gateway = FakeGateway()
        gateway.list_tools = AsyncMock(return_value=[tool])
        gateway.call_tool = AsyncMock(side_effect=[{"status": "running", "job_id": "music-1"},
                                                  {"status": "succeeded", "job_id": "music-1", "audio_url": "https://cdn.example/music.mp3"}])
        harness = FakeHarness([{"callId": "poll-1", "tool": "call_gateway_tool", "arguments": {
            "tool_name": tool.name, "arguments_json": '{"job_id":"music-1"}'}}])
        studio = StudioAgentContext(autonomous=True)
        with patch("agent.studio_codex_runner.asyncio.sleep", new=AsyncMock()):
            await run_studio_agent(StudioAgentRequest(prompt="Check music", autonomous=True), studio=studio,
                                   harness=harness, mcp_servers=[gateway])
        self.assertEqual(gateway.call_tool.await_count, 2)
        self.assertEqual(len(studio.tool_events), 1)
        self.assertEqual(studio.tool_events[0].status, "succeeded")
        self.assertEqual(next(e for e in studio.progress_events if e.id == "wait-poll-1").status, "completed")

    async def test_render_poll_uses_saved_identifiers_instead_of_model_copy(self):
        tool = Tool(name="Remotion___get_render_progress", description="Poll",
                    inputSchema={"type": "object", "properties": {key: {"type": "string"} for key in ["render_id", "bucket_name", "output_key"]}, "required": ["render_id", "bucket_name"]})
        gateway = FakeGateway()
        gateway.list_tools = AsyncMock(return_value=[tool])
        gateway.call_tool = AsyncMock(return_value={"status": "succeeded", "url": "https://cdn.example/final.mp4"})
        studio = StudioAgentContext(autonomous=True, tool_events=[StudioToolEvent(id="started", name="Remotion___render_timeline", label="Export", status="queued", summary="Queued", result={"render_id":"render1", "bucket_name":"bucket-correct2", "output_key":"renders/render1/final.mp4"})])
        harness = FakeHarness([{"callId": "poll", "tool": "call_gateway_tool", "arguments": {"tool_name": tool.name, "arguments_json": '{"render_id":"render1","bucket_name":"bucket-correct"}'}}])
        await run_studio_agent(StudioAgentRequest(prompt="Finish the video", autonomous=True), studio=studio, harness=harness, mcp_servers=[gateway])
        self.assertEqual(gateway.call_tool.call_args.args[1], {"render_id":"render1", "bucket_name":"bucket-correct2", "output_key":"renders/render1/final.mp4"})

    async def test_failure_still_saves_checkpoint(self):
        sink = unittest.mock.Mock()
        studio = StudioAgentContext(session_sink=sink)
        with self.assertRaises(CodexProtocolError):
            await run_studio_agent(StudioAgentRequest(prompt="Make an outline"), studio=studio,
                                   harness=FakeHarness(failure=CodexProtocolError("disconnected")), mcp_servers=[])
        sink.assert_called_once()
        self.assertEqual(sink.call_args.args[0][0]["thread_id"], "thread-1")

    async def test_queued_render_prevents_paid_replacement(self):
        gateway = FakeGateway()
        studio = StudioAgentContext(autonomous=True, tool_events=[StudioToolEvent(
            id="started", name="Remotion___render_timeline", label="Export", status="queued", summary="Queued",
            result={"status":"queued", "render_id":"saved", "bucket_name":"bucket"})])
        harness = FakeHarness([{"callId":"duplicate", "tool":"call_gateway_tool", "arguments":{
            "tool_name":"Remotion___render_timeline", "arguments_json":"{}"}}])
        await run_studio_agent(StudioAgentRequest(prompt="Finish the video", autonomous=True), studio=studio,
                               harness=harness, mcp_servers=[gateway])
        self.assertEqual(gateway.calls, [])
        self.assertEqual(harness.results[0]["arguments"]["render_id"], "saved")

    async def test_successful_poll_is_reused_without_another_approval(self):
        gateway = FakeGateway()
        studio = StudioAgentContext(tool_events=[StudioToolEvent(
            id="finished", name="Remotion___get_render_progress", label="Export", status="succeeded", summary="Ready",
            arguments={"render_id":"saved"}, result={"status":"succeeded", "url":"https://cdn.example/final.mp4"})])
        harness = FakeHarness([{"callId":"repeat", "tool":"call_gateway_tool", "arguments":{
            "tool_name":"Remotion___get_render_progress", "arguments_json":'{"render_id":"saved"}'}}])
        await run_studio_agent(StudioAgentRequest(prompt="Finish the video"), studio=studio,
                               harness=harness, mcp_servers=[gateway])
        self.assertEqual(gateway.calls, [])
        self.assertEqual(harness.results[0]["status"], "succeeded")

    def test_default_model_is_preserved(self):
        with patch.dict(os.environ, {"AGENT_MODEL": ""}):
            self.assertEqual(_agent_model(), "gpt-5.6-luna")

    async def test_autonomous_tool_registers_assets_and_progress_once(self):
        gateway, harness = FakeGateway(), FakeHarness([image_call()])
        registrar = unittest.mock.Mock(return_value=[{"version_id": "image-v1", "kind": "image"}])
        studio = StudioAgentContext(autonomous=True, asset_registrar=registrar)
        await run_studio_agent(
            StudioAgentRequest(prompt="Make an image", autonomous=True),
            studio=studio,
            harness=harness,
            mcp_servers=[gateway],
        )
        self.assertEqual(len(gateway.calls), 1)
        registrar.assert_called_once()
        self.assertEqual(studio.tool_events[0].status, "succeeded")
        self.assertEqual(harness.results[0]["image_url"], "https://cdn.example/hero.png")
        self.assertIn("image-v1", studio.working_assets)

    async def _pause(self):
        gateway, harness = FakeGateway(), FakeHarness([image_call()])
        request = StudioAgentRequest(
            prompt="Make an image",
            workspace_id="workspace-1",
            conversation_id="conversation-1",
            job_id="job-1",
        )
        studio = StudioAgentContext()
        with self.assertRaises(StudioAgentApprovalRequired) as paused:
            await run_studio_agent(request, studio=studio, harness=harness, mcp_servers=[gateway])
        self.assertEqual(gateway.calls, [])
        self.assertEqual(paused.exception.approvals[0].tool_name, IMAGE_TOOL.name)
        self.assertEqual(paused.exception.approvals[0].arguments, {"prompt": "Product hero"})
        request.resume_state = paused.exception.state
        request.session_items = paused.exception.session_items
        return request, studio, gateway

    async def test_approval_resume_runs_exact_saved_call_once(self):
        request, studio, gateway = await self._pause()
        request.approval_decisions = [StudioApprovalDecision(call_id="image-1", decision="approve")]
        # A fresh harness resumes the native thread after applying the saved call.
        harness = FakeHarness()
        await run_studio_agent(request, studio=studio, harness=harness, mcp_servers=[gateway])
        self.assertEqual(gateway.calls, [(IMAGE_TOOL.name, {"prompt": "Product hero"})])
        self.assertEqual(harness.kwargs["session"]["thread_id"], "thread-1")
        self.assertIn("https://cdn.example/hero.png", harness.kwargs["prompt"])
        # Replaying a checkpoint with its persisted tool result does not dispatch again.
        await run_studio_agent(request, studio=studio, harness=FakeHarness(), mcp_servers=[gateway])
        self.assertEqual(len(gateway.calls), 1)

    async def test_rejection_never_calls_provider(self):
        request, studio, gateway = await self._pause()
        request.approval_decisions = [StudioApprovalDecision(call_id="image-1", decision="reject")]
        harness = FakeHarness()
        await run_studio_agent(request, studio=studio, harness=harness, mcp_servers=[gateway])
        self.assertEqual(gateway.calls, [])
        self.assertEqual(studio.tool_events[0].status, "rejected")
        self.assertIn('"decision": "reject"', harness.kwargs["prompt"])

    async def test_missing_decision_and_wrong_scope_fail_before_dispatch(self):
        request, studio, gateway = await self._pause()
        with self.assertRaises(StudioAgentApprovalRequired):
            await run_studio_agent(
                request, studio=studio, harness=FakeHarness(), mcp_servers=[gateway]
            )
        request.workspace_id = "workspace-2"
        request.approval_decisions = [StudioApprovalDecision(call_id="image-1", decision="approve")]
        with self.assertRaisesRegex(ValueError, "different workspace"):
            await run_studio_agent(
                request, studio=studio, harness=FakeHarness(), mcp_servers=[gateway]
            )
        self.assertEqual(gateway.calls, [])

    async def test_unknown_tool_and_invalid_arguments_never_dispatch(self):
        unknown = image_call()
        unknown["arguments"]["tool_name"] = "Invented___generate"
        gateway, harness = FakeGateway(), FakeHarness([unknown, image_call(prompt=3)])
        await run_studio_agent(
            StudioAgentRequest(prompt="Make an image", autonomous=True),
            harness=harness,
            mcp_servers=[gateway],
        )
        self.assertEqual(gateway.calls, [])
        self.assertEqual([r["status"] for r in harness.results], ["failed", "failed"])

    async def test_gateway_search_unlocks_only_returned_tools(self):
        server = GatewayMCPServer({"url": "https://gateway.example"}, name="gateway")
        server._tools_list = [SEARCH_TOOL]
        calls = [
            {"callId": "search-1", "tool": _GATEWAY_SEARCH_TOOL, "arguments": {"query": "image"}},
            image_call(),
        ]
        harness = FakeHarness(calls)

        async def dispatch(name, arguments, **_kwargs):
            if name == _GATEWAY_SEARCH_TOOL:
                return {"tools": [IMAGE_TOOL.model_dump(by_alias=True)]}
            return {"status": "succeeded", "image_url": "https://cdn.example/hero.png"}

        with patch.object(GatewayClient, "call_tool", side_effect=dispatch) as invoke:
            await run_studio_agent(
                StudioAgentRequest(prompt="Make an image", autonomous=True),
                harness=harness,
                mcp_servers=[server],
            )
        self.assertEqual(invoke.await_count, 2)
        self.assertEqual(harness.results[0]["tools"][0]["name"], IMAGE_TOOL.name)
        self.assertEqual(harness.session["gateway_tools"][0]["name"], IMAGE_TOOL.name)

    async def test_model_failure_emits_error(self):
        studio = StudioAgentContext()
        with self.assertRaisesRegex(RuntimeError, "model failed"):
            await run_studio_agent(
                StudioAgentRequest(prompt="Make an outline"),
                studio=studio,
                harness=FakeHarness(failure=RuntimeError("model failed")),
                mcp_servers=[],
            )
        self.assertEqual(studio.progress_events[-1].type, "RUN_ERROR")

    async def test_gateway_expands_seedream_presets_after_pricing(self):
        gateway = GatewayMCPServer({"url": "https://gateway.example"}, name="gateway")
        for tool in ("Seedream___text_to_image", "Seedream___image_to_image"):
            for size, ratio, expected in (
                ("1K", "1:1", "1024x1024"),
                ("2K", "16:9", "2560x1440"),
                ("3K", "9:16", "1728x3072"),
                ("2400x1000", "16:9", "2400x1000"),
            ):
                arguments = {"prompt": "Test", "size": size, "aspect_ratio": ratio}
                with (
                    self.subTest(tool=tool, size=size),
                    patch.object(gateway, "_billed_cost", return_value=None) as price,
                    patch.object(GatewayClient, "call_tool", new_callable=AsyncMock) as call,
                ):
                    call.return_value = {"status": "succeeded"}
                    await gateway.call_tool(tool, arguments)
                    price.assert_called_once_with(tool, arguments)
                    self.assertEqual(arguments["size"], size)
                    self.assertEqual(call.await_args.args[1]["size"], expected)

    async def test_gateway_refunds_lambda_errors_without_mcp_error_flag(self):
        from types import SimpleNamespace

        gateway = GatewayMCPServer(
            {"url": "https://gateway.example"}, name="gateway", user_id="user-test"
        )
        charge = object()
        for payload in ({"error": "invalid size"}, {"status": "failed", "message": "failed"}):
            with (
                self.subTest(payload=payload),
                patch.object(
                    gateway, "_billed_cost", return_value=SimpleNamespace(total_cents=5)
                ),
                patch.object(GatewayClient, "call_tool", new_callable=AsyncMock) as call,
                patch("agent.studio_agent_next.repository.charge_usage", return_value=charge),
                patch("agent.studio_agent_next.repository.refund_usage") as refund,
            ):
                call.return_value = CallToolResult(
                    content=[TextContent(type="text", text=json.dumps(payload))], isError=False
                )
                with self.assertRaises(RuntimeError):
                    await gateway.call_tool(IMAGE_TOOL.name, {"prompt": "Test", "size": "2K"})
                refund.assert_called_once_with(
                    "user-test", charge, f"refund: agent call to {IMAGE_TOOL.name} failed"
                )


class NativeProtocolTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def mcp_fixture(self):
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append(body)
                if "id" not in body:
                    self.send_response(202)
                    self.end_headers()
                    return
                method = body["method"]
                if method == "initialize":
                    result = {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fixture", "version": "1"},
                    }
                elif method == "tools/list":
                    second_page = body.get("params", {}).get("cursor") == "second"
                    result = {
                        "tools": [
                            (SEARCH_TOOL if second_page else IMAGE_TOOL).model_dump(by_alias=True)
                        ]
                    }
                    if not second_page:
                        result["nextCursor"] = "second"
                else:
                    result = {"content": [{"type": "text", "text": '{"status":"succeeded"}'}]}
                encoded = json.dumps(
                    {"jsonrpc": "2.0", "id": body["id"], "result": result}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=http.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{http.server_port}/mcp", calls
        finally:
            await asyncio.to_thread(http.shutdown)
            http.server_close()
            worker.join(timeout=2)

    async def test_real_mcp_transport_initializes_paginates_and_calls(self):
        async with self.mcp_fixture() as (url, calls):
            async with GatewayClient(
                {"url": url}, name="fixture"
            ) as gateway:
                tools = await gateway.list_tools()
                self.assertEqual([tool.name for tool in tools], [IMAGE_TOOL.name, SEARCH_TOOL.name])
                await gateway.list_tools()
                result = await gateway.call_tool(IMAGE_TOOL.name, {"prompt": "test"})
                self.assertFalse(result.is_error)
            self.assertEqual(sum(call["method"] == "tools/list" for call in calls), 2)
            self.assertEqual(calls[-1]["params"]["arguments"], {"prompt": "test"})

    async def test_real_mcp_transport_preserves_approval_pause(self):
        async with self.mcp_fixture() as (url, calls):
            gateway = GatewayMCPServer({"url": url}, name="fixture")
            tool_call = {
                "callId": "search-1",
                "tool": _GATEWAY_SEARCH_TOOL,
                "arguments": {"query": "image generation"},
            }
            with patch("agent.studio_agent_next.gateway_mcp_server", return_value=gateway):
                with self.assertRaises(StudioAgentApprovalRequired) as paused:
                    await run_studio_agent(
                        StudioAgentRequest(prompt="Make an image", autonomous=False),
                        harness=FakeHarness([tool_call]),
                    )
            self.assertEqual(paused.exception.approvals[0].call_id, "search-1")
            self.assertEqual(paused.exception.approvals[0].arguments, tool_call["arguments"])
            self.assertEqual(json.loads(paused.exception.state)["harness"], "codex")
            self.assertEqual(paused.exception.session_items[0]["thread_id"], "thread-1")
            self.assertFalse(any(call["method"] == "tools/call" for call in calls))
            self.assertIsNone(gateway._session)
            self.assertIsNone(gateway._stack)

    async def test_real_codex_tool_loop_and_approval_resume_with_local_model(self):
        # Exercise the actual native model loop against a localhost Responses
        # fixture. No OpenAI or media provider request is made.
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                requests.append(json.loads(body))
                if len(requests) == 1:
                    item = {
                        "type": "custom_tool_call",
                        "id": "fc_1",
                        "call_id": "call_1",
                        "name": "exec",
                        "namespace": "functions",
                        "input": "const jobs = "
                        + json.dumps([image_call()["arguments"]] * batch_size)
                        + "; text(await Promise.all(jobs.map(args => tools.call_gateway_tool(args))));",
                    }
                else:
                    item = {
                        "type": "message",
                        "id": "msg_1",
                        "role": "assistant",
                        "phase": "final_answer",
                        "content": [{"type": "output_text", "text": json.dumps(FINAL)}],
                    }
                response_id = f"response_{len(requests)}"
                events = [
                    {"type": "response.created", "response": {"id": response_id}},
                    {"type": "response.output_item.done", "output_index": 0, "item": item},
                    {
                        "type": "response.completed",
                        "response": {
                            "id": response_id,
                            "status": "completed",
                            "output": [item],
                            "usage": {"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
                        },
                    },
                ]
                encoded = "".join(
                    "data: " + json.dumps(event) + "\n\n" for event in events
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        original = AppServer.request

        async def use_local_model(server, method, params):
            if method in ("thread/start", "thread/resume"):
                params = {
                    **params,
                    "modelProvider": "test",
                    "config": {
                        "model_providers.test": {
                            "name": "test",
                            "base_url": f"http://127.0.0.1:{http.server_port}",
                            "wire_api": "responses",
                            "requires_openai_auth": False,
                            "supports_websockets": False,
                        },
                        "features.enable_request_compression": False,
                    },
                }
            return await original(server, method, params)

        try:
            with (
                patch.object(AppServer, "request", use_local_model),
                patch.dict(
                    os.environ,
                    {
                        "OPENAI_API_KEY": "local-test-placeholder",
                        "CODEX_RUN_TIMEOUT_SECONDS": "15",
                    },
                ),
            ):
                for autonomous, batch_size, decision in (
                    (True, 1, None),
                    (False, 1, "approve"),
                    (True, 3, None),
                    (False, 3, "approve"),
                    (False, 3, "reject"),
                ):
                    requests.clear()
                    gateway = FakeGateway()
                    request = StudioAgentRequest(prompt="Make an image", autonomous=autonomous)
                    studio = StudioAgentContext(autonomous=autonomous)
                    if autonomous:
                        result = await run_studio_agent(
                            request, studio=studio, mcp_servers=[gateway]
                        )
                    else:
                        with self.assertRaises(StudioAgentApprovalRequired) as paused:
                            await run_studio_agent(request, studio=studio, mcp_servers=[gateway])
                        self.assertEqual(gateway.calls, [])
                        request.resume_state = paused.exception.state
                        request.session_items = paused.exception.session_items
                        request.prior_tool_events = [event.public() for event in studio.tool_events]
                        request.approval_decisions = [
                            StudioApprovalDecision(
                                call_id=paused.exception.approvals[0].call_id, decision=decision
                            )
                        ]
                        # Reconstruct the Studio context, matching a new AgentCore worker.
                        result = await run_studio_agent(request, mcp_servers=[gateway])
                    self.assertEqual(result.title, FINAL["title"])
                    self.assertEqual(
                        len(gateway.calls),
                        batch_size if autonomous else int(decision == "approve"),
                        [x for x in requests[-1]["input"] if "output" in x.get("type", "")],
                    )
                    self.assertGreaterEqual(len(requests), 2)
                    forbidden = {
                        "exec_command",
                        "shell",
                        "apply_patch",
                        "web_search",
                        "image_generation",
                    }
                    declared_tools = [
                        *requests[0].get("tools", []),
                        *[
                            tool
                            for item in requests[0]["input"]
                            if item.get("type") == "additional_tools"
                            for tool in item.get("tools", [])
                        ],
                    ]

                    def names(specs):
                        for spec in specs:
                            yield spec.get("name", spec.get("type"))
                            yield from names(spec.get("tools", []))

                    tool_names = set(names(declared_tools))
                    self.assertIn("call_gateway_tool", json.dumps(declared_tools))
                    self.assertFalse(tool_names & forbidden, tool_names)
                    self.assertNotIn("local-test-placeholder", studio.session_items[0]["rollout"])
        finally:
            await asyncio.to_thread(http.shutdown)
            http.server_close()
            thread.join(timeout=2)

    async def test_real_runtime_restores_history_and_dynamic_tools_without_model_request(self):
        # This starts/resumes metadata only. It never starts a turn or authenticates.
        with tempfile.TemporaryDirectory(prefix="renderhaus-codex-test-") as directory:
            root = Path(directory).resolve()
            home, workspace = root / "home", root / "workspace"
            home.mkdir()
            workspace.mkdir()
            tool = {
                "type": "function",
                "name": "studio_test",
                "description": "test",
                "inputSchema": {"type": "object", "properties": {}},
            }
            async with AppServer(home, workspace) as server:
                started = await server.request(
                    "thread/start",
                    {
                        "model": "gpt-5.6-luna",
                        "cwd": str(workspace),
                        "sandbox": "read-only",
                        "approvalPolicy": "untrusted",
                        "dynamicTools": [tool],
                        "environments": [],
                    },
                )
                thread = started["thread"]
                await server.request(
                    "thread/inject_items",
                    {
                        "threadId": thread["id"],
                        "items": [
                            {
                                "type": "message",
                                "role": "user",
                                "content": [{"type": "input_text", "text": "Earlier scene."}],
                            }
                        ],
                    },
                )
            rollout = Path(thread["path"])
            saved = rollout.read_text()
            self.assertIn("Earlier scene.", saved)
            self.assertIn("studio_test", saved)
            other_home = root / "other-home"
            other_rollout = other_home / rollout.relative_to(home)
            other_rollout.parent.mkdir(parents=True)
            other_rollout.write_text(saved)
            async with AppServer(other_home, workspace) as server:
                resumed = await server.request(
                    "thread/resume",
                    {
                        "threadId": thread["id"],
                        "cwd": str(workspace),
                        "sandbox": "read-only",
                        "approvalPolicy": "untrusted",
                        "model": "gpt-5.6-luna",
                    },
                )
            self.assertEqual(resumed["thread"]["id"], thread["id"])
            self.assertIn("studio_test", other_rollout.read_text())


if __name__ == "__main__":
    unittest.main()
