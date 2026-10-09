from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest

import httpx
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import server.studio as studio
from agent.studio_agent_next import agent_invocation
from server.studio_state import StudioRepository
from test_deep_agent import FINAL, Gateway, ScriptedModel, call, final, image, read_skill


class DeepAgentContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = StudioRepository(Path(directory.name) / "state.sqlite3", Path(directory.name) / "media")
        self.repo.create_project("user:local", "local", "Deep Agent", project_id="project")
        self.conversation = self.repo.create_conversation("user:local", "project", "local")["id"]
        self.job = self.repo.create_execution(
            workspace_id="user:local", project_id="project", user_id="local",
            prompt="Make a product still", conversation_id=self.conversation,
            request={"prompt": "Make a product still", "conversation_id": self.conversation,
                     "workspace_id": "user:local", "project_id": "project", "user_id": "local"},
        )["job_id"]
        self.gateway = Gateway()
        self.steps = [final()]

        @asynccontextmanager
        async def gateway(**kwargs):
            yield self.gateway

        for p in [
            patch.object(studio, "repository", self.repo),
            patch("agent.studio_agent_next.gateway_mcp_server", gateway),
            patch("agent.deep_agent.runner.configured_deep_agent_model", side_effect=lambda: ScriptedModel(self.steps)),
            patch.dict(os.environ, {"RENDERHAUS_AGENT_BACKEND": "deepagents", "AGENTCORE_DEV_URL": ""}),
        ]:
            p.start()
            self.addCleanup(p.stop)

    async def run_job(self):
        await studio._run_studio_agent_job(
            self.job, "Make a product still", [], self.conversation,
            workspace_id="user:local", project_id="project", user_id="local",
        )

    async def test_server_result_and_conversation_checkpoint_contract(self):
        await self.run_job()
        execution = self.repo.get_execution("user:local", self.job)
        self.assertEqual(execution["status"], "completed")
        self.assertEqual(execution["result"]["title"], FINAL["title"])
        self.assertEqual(execution["result"]["filename"], "Product-still.md")
        self.assertNotIn("session_items", execution)
        items = self.repo.get_conversation_items("user:local", self.conversation)
        self.assertEqual(items[0]["type"], "renderhaus_deepagents_session")
        self.assertTrue(items[0]["checkpoint"]["storage"])
        self.gateway.call_tool.assert_not_awaited()

    async def test_server_approval_route_rejects_and_resumes_same_job(self):
        self.steps = [read_skill(), image()]
        await self.run_job()
        execution = self.repo.get_execution("user:local", self.job)
        self.assertEqual(execution["status"], "awaiting_approval")
        approval = execution["approvals"][0]
        self.assertEqual(approval["tool_name"], "Seedream___text_to_image")
        self.gateway.call_tool.assert_not_awaited()
        self.steps = [final()]
        await studio.decide_studio_agent_tool(
            self.job, approval["call_id"], studio.AgentApprovalBody(decision="reject"), None,
        )
        tasks = list(studio._AGENT_TASKS)
        await asyncio.gather(*tasks)
        execution = self.repo.get_execution("user:local", self.job)
        self.assertEqual(execution["status"], "completed")
        self.assertTrue(any(t["status"] == "rejected" for t in execution["tool_calls"]))
        self.gateway.call_tool.assert_not_awaited()

    async def test_agentcore_sse_streams_progress_and_structured_result(self):
        self.steps = [
            call("report_progress", {"message": "I have the product brief."}, "progress"),
            final(),
        ]
        chunks = [chunk async for chunk in agent_invocation({
            "prompt": "Make a product still", "job_id": self.job,
            "workspace_id": "user:local", "project_id": "project", "conversation_id": self.conversation,
        }, SimpleNamespace(session_id="runtime-session"))]
        self.assertTrue(any(c["kind"] == "progress" for c in chunks))
        self.assertTrue(any(c["kind"] == "checkpoint" for c in chunks))
        self.assertEqual(chunks[-1]["kind"], "result")
        payload = chunks[-1]["payload"]
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["session_id"], "runtime-session")
        self.assertEqual(payload["job_id"], self.job)
        self.assertEqual(payload["result"]["title"], FINAL["title"])
        json.dumps(chunks)

    async def test_agentcore_approval_payload_is_portable(self):
        self.steps = [read_skill(), image()]
        chunks = [chunk async for chunk in agent_invocation({
            "prompt": "Make a product still", "job_id": self.job,
            "workspace_id": "user:local", "project_id": "project", "conversation_id": self.conversation,
        }, SimpleNamespace(session_id="runtime-session"))]
        payload = chunks[-1]["payload"]
        self.assertEqual(payload["status"], "awaiting_approval")
        self.assertEqual(payload["approvals"][0]["tool_name"], "Seedream___text_to_image")
        self.assertEqual(json.loads(payload["run_state"])["backend"], "deepagents")
        self.assertEqual(payload["session_items"][0]["type"], "renderhaus_deepagents_session")
        self.gateway.call_tool.assert_not_awaited()

    async def test_agentcore_failure_retains_tool_ledger_and_checkpoint(self):
        def failure(messages, tools):
            raise RuntimeError("Scripted model failed")

        self.gateway.call_tool.return_value = {"status": "dry_run"}
        self.steps = [read_skill(), image(), failure]
        chunks = [chunk async for chunk in agent_invocation({
            "prompt": "Make a product still", "autonomous": True, "job_id": self.job,
            "workspace_id": "user:local", "project_id": "project", "conversation_id": self.conversation,
        }, SimpleNamespace(session_id="runtime-session"))]
        payload = chunks[-1]["payload"]
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["tool_events"][0]["status"], "dry_run")
        self.assertTrue(payload["session_items"][0]["checkpoint"]["storage"])

    async def test_disconnected_runtime_stream_preserves_received_work(self):
        self.gateway.call_tool.return_value = {"status": "dry_run"}
        self.steps = [read_skill(), image(), final()]
        chunks = [chunk async for chunk in agent_invocation({
            "prompt": "Make a product still", "autonomous": True, "job_id": self.job,
            "workspace_id": "user:local", "project_id": "project", "conversation_id": self.conversation,
        }, SimpleNamespace(session_id="runtime-session"))]

        class InterruptedStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                for chunk in chunks:
                    if chunk["kind"] != "result":
                        yield ("data: " + json.dumps(chunk) + "\n\n").encode()
                raise httpx.ReadError("Runtime stream disconnected")

        def route(request):
            if request.url.path == "/ping":
                return httpx.Response(200, json={"status": "healthy"})
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=InterruptedStream())

        client = httpx.AsyncClient
        with patch.dict(os.environ, {"AGENTCORE_DEV_URL": "http://runtime.test"}), patch(
            "server.studio.httpx.AsyncClient", side_effect=lambda **kw: client(transport=httpx.MockTransport(route), **kw),
        ):
            await studio._run_studio_agent_job(
                self.job, "Make a product still", [], self.conversation,
                workspace_id="user:local", project_id="project", user_id="local", autonomous=True,
            )
        execution = self.repo.get_execution("user:local", self.job)
        self.assertEqual(execution["status"], "error")
        self.assertTrue(execution["recovery_available"])
        self.assertTrue(any(t["status"] == "dry_run" for t in execution["tool_calls"]))
        self.assertEqual(self.repo.get_conversation_items("user:local", self.conversation)[0]["type"],
                         "renderhaus_deepagents_session")

    async def test_streamed_asset_and_final_result_share_one_registered_version(self):
        png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jrXcAAAAASUVORK5CYII="
        self.gateway.call_tool.return_value = {"status": "succeeded", "image_url": "data:image/png;base64," + png}
        self.steps = [read_skill(), image(), final()]
        chunks = [chunk async for chunk in agent_invocation({
            "prompt": "Make a product still", "autonomous": True, "job_id": self.job,
            "workspace_id": "user:local", "project_id": "project", "conversation_id": self.conversation,
        }, SimpleNamespace(session_id="runtime-session"))]

        class ResultStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                for chunk in chunks:
                    yield ("data: " + json.dumps(chunk) + "\n\n").encode()

        def route(request):
            if request.url.path == "/ping":
                return httpx.Response(200, json={"status": "healthy"})
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=ResultStream())

        client = httpx.AsyncClient
        with patch.dict(os.environ, {"AGENTCORE_DEV_URL": "http://runtime.test"}), patch(
            "server.studio.httpx.AsyncClient", side_effect=lambda **kw: client(transport=httpx.MockTransport(route), **kw),
        ), patch.object(self.repo, "register_source", wraps=self.repo.register_source) as ingest:
            await studio._run_studio_agent_job(
                self.job, "Make a product still", [], self.conversation,
                workspace_id="user:local", project_id="project", user_id="local", autonomous=True,
            )
        execution = self.repo.get_execution("user:local", self.job)
        self.assertEqual(execution["status"], "completed")
        self.assertEqual(ingest.call_count, 1)
        self.assertEqual(len(execution["result"]["assets"]), 1)
        self.assertEqual(execution["result"]["assets"][0]["version_id"], execution["tool_calls"][0]["assets"][0]["version_id"])

    async def test_identical_search_in_two_jobs_preserves_both_ledgers(self):
        from agent.studio_agent_next import _GATEWAY_SEARCH_TOOL
        from mcp import Tool
        self.gateway.tools = [Tool(
            name=_GATEWAY_SEARCH_TOOL, description="Search tools", inputSchema={
                "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        )]
        self.gateway.call_tool.return_value = {"tools": []}
        first_job = self.job
        for index in range(2):
            self.steps = [call(_GATEWAY_SEARCH_TOOL, {"query": "product image"}, "search"), final()]
            if index:
                self.job = self.repo.create_execution(
                    workspace_id="user:local", project_id="project", user_id="local",
                    prompt="Make a product still", conversation_id=self.conversation,
                )["job_id"]
            await self.run_job()
        first = self.repo.get_execution("user:local", first_job)
        second = self.repo.get_execution("user:local", self.job)
        self.assertEqual(len(first["tool_calls"]), 1)
        self.assertEqual(len(second["tool_calls"]), 1)
        self.assertNotEqual(first["tool_calls"][0]["id"], second["tool_calls"][0]["id"])

    async def test_backend_flag_keeps_codex_runner_available(self):
        from agent.studio_agent_next import StudioAgentRequest, StudioAgentOutput, run_studio_agent
        output = StudioAgentOutput.model_validate(FINAL)
        with patch.dict(os.environ, {"RENDERHAUS_AGENT_BACKEND": "codex"}), patch(
            "agent.studio_codex_runner.run_with_servers", new=AsyncMock(return_value=output),
        ) as run:
            result = await run_studio_agent(StudioAgentRequest(prompt="Make an outline"), mcp_servers=[])
        self.assertEqual(result.title, FINAL["title"])
        run.assert_awaited_once()

    async def test_status_accepts_anthropic_without_an_openai_key(self):
        with patch.dict(os.environ, {"RENDERHAUS_AGENT_MODEL": "anthropic:test", "OPENAI_API_KEY": "",
                                     "ANTHROPIC_API_KEY": "test-only"}):
            self.assertTrue((await studio.studio_status())["agent"])
