from __future__ import annotations

import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

from agents import RunContextWrapper

from agent.studio_agent import (
    StudioAgentContext,
    StudioAgentOutput,
    StudioAgentRun,
    StudioNodeReference,
    StudioToolEvent,
    _invoke_provider,
    normalize_markdown_filename,
    run_studio_agent,
)
from server.studio import _AGENT_JOBS, AgentBody, studio_agent, studio_agent_job


class FakeRunner:
    seen_agent = None
    seen_input = ""
    seen_context = None

    @classmethod
    async def run(cls, agent, input_value, *, context, **_kwargs):
        cls.seen_agent = agent
        cls.seen_input = input_value
        cls.seen_context = context

        class Result:
            final_output = StudioAgentOutput(
                title="Launch outline",
                summary="A concise launch outline is ready.",
                markdown="# Launch outline\n\n- Open with the product.",
                filename="Launch outline",
            )

        return Result()


class StudioAgentTests(unittest.IsolatedAsyncioTestCase):
    def test_filename_is_safe_and_downloadable(self) -> None:
        self.assertEqual(normalize_markdown_filename("../Campaign Brief.md", "Ignored"), "Campaign-Brief.md")
        self.assertEqual(normalize_markdown_filename("", "Agent result"), "agent-result.md")

    async def test_provider_tool_records_a_redacted_event(self) -> None:
        def fake_dispatch(_provider, _tool, _arguments):
            return {
                "status": "dry_run",
                "job_id": "job-123",
                "api_key": "must-not-reach-the-model",
                "message": "authorization: Bearer-secret-value",
            }

        context = StudioAgentContext(dispatcher=fake_dispatch)
        payload = await _invoke_provider(
            RunContextWrapper(context=context),
            name="generate_image",
            label="Image generation",
            provider="seedream",
            tool_name="text_to_image",
            arguments={"prompt": "A clean product still"},
        )

        decoded = json.loads(payload)
        self.assertEqual(decoded["status"], "dry_run")
        self.assertNotIn("api_key", decoded["result"])
        self.assertNotIn("Bearer-secret-value", decoded["result"]["message"])
        self.assertEqual(context.tool_events[0].name, "generate_image")
        self.assertEqual(context.tool_events[0].status, "dry_run")

    async def test_provider_tool_polls_queued_media_to_completion(self) -> None:
        calls: list[str] = []

        def fake_dispatch(_provider, tool, _arguments):
            calls.append(tool)
            if tool == "text_to_video":
                return {"status": "queued", "job_id": "video-123"}
            return {
                "status": "succeeded",
                "job_id": "video-123",
                "output_path": ".renderhaus/media/video/video-123.mp4",
            }

        context = StudioAgentContext(dispatcher=fake_dispatch)
        with patch.dict(os.environ, {"STUDIO_AGENT_POLL_INTERVAL_SECONDS": "0"}):
            payload = await _invoke_provider(
                RunContextWrapper(context=context),
                name="generate_video",
                label="Video generation",
                provider="seedance",
                tool_name="text_to_video",
                arguments={"prompt": "A product reveal"},
                poll_tool_name="get_video_task",
            )

        self.assertEqual(json.loads(payload)["status"], "succeeded")
        self.assertEqual(calls, ["text_to_video", "get_video_task"])
        self.assertEqual(context.tool_events[0].status, "succeeded")

    async def test_single_manager_returns_structured_artifact(self) -> None:
        with patch.dict(os.environ, {"AGENT_MODEL": "openai:gpt-4.1-mini"}):
            outcome = await run_studio_agent(
                "Create a launch outline",
                nodes=[StudioNodeReference(id="node-1", title="Hero image", kind="image")],
                runner=FakeRunner,
            )

        self.assertEqual(outcome.final.title, "Launch outline")
        self.assertEqual(outcome.final.filename, "Launch-outline.md")
        self.assertIn("Customer request", FakeRunner.seen_input)
        self.assertEqual(FakeRunner.seen_context.nodes[0].id, "node-1")
        self.assertEqual(len(FakeRunner.seen_agent.tools), 6)
        self.assertEqual(FakeRunner.seen_agent.model, "gpt-4.1-mini")

    async def test_studio_endpoint_runs_in_background_and_returns_canvas_result(self) -> None:
        outcome = StudioAgentRun(
            final=StudioAgentOutput(
                title="Customer result",
                summary="The result is complete.",
                markdown="# Customer result",
                filename="customer-result.md",
            ),
            tool_events=[
                StudioToolEvent(
                    name="generate_image",
                    label="Image generation",
                    status="dry_run",
                    summary="Dry run complete.",
                )
            ],
        )
        _AGENT_JOBS.clear()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), patch(
            "server.studio.run_studio_agent", new=AsyncMock(return_value=outcome)
        ):
            queued = await studio_agent(AgentBody(prompt="Make the result"))
            await asyncio.sleep(0)
            payload = await studio_agent_job(queued["job_id"])

        self.assertEqual(queued["status"], "queued")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["result"]["filename"], "customer-result.md")
        self.assertEqual(payload["result"]["tool_events"][0]["name"], "generate_image")


if __name__ == "__main__":
    unittest.main()
