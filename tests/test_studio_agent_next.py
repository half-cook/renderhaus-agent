from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent.studio_agent_next import (
    StudioAgentContext,
    StudioAgentOutput,
    StudioAgentRequest,
    StudioNode,
    _record_run_tool_events,
    agent_invocation,
    normalize_markdown_filename,
    run_studio_agent,
)


class FakeRunner:
    seen_agent = None
    seen_input = ""

    @classmethod
    async def run(cls, agent, input_value, **_kwargs):
        cls.seen_agent = agent
        cls.seen_input = input_value

        class Result:
            final_output = StudioAgentOutput(
                title="Launch outline",
                summary="A concise launch outline is ready.",
                markdown="# Launch outline\n\n- Open with the product.",
                filename="Launch outline",
            )

        return Result()


class StudioAgentNextEntrypointTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_markdown_filename_slugs_unsafe_names(self) -> None:
        self.assertEqual(
            normalize_markdown_filename("Launch outline", "Launch outline"),
            "Launch-outline.md",
        )
        self.assertEqual(normalize_markdown_filename("../secret.md", "Notes"), "secret.md")
        self.assertEqual(normalize_markdown_filename("", "Hello World"), "hello-world.md")

    def test_request_accepts_prompt_and_nodes(self) -> None:
        request = StudioAgentRequest.model_validate(
            {
                "prompt": "Make a launch outline",
                "job_id": "job-1",
                "workspace_id": "user:local",
                "project_id": "untitled",
                "nodes": [
                    {
                        "id": "node-1",
                        "title": "Hero image",
                        "kind": "image",
                        "asset_id": "asset-1",
                        "version_id": "version-1",
                    }
                ],
            }
        )
        self.assertEqual(request.prompt, "Make a launch outline")
        self.assertEqual(request.job_id, "job-1")
        self.assertEqual(request.nodes[0].id, "node-1")
        self.assertEqual(request.nodes[0].version_id, "version-1")

    def test_request_model_rejects_empty_prompt(self) -> None:
        with self.assertRaises(Exception):
            StudioAgentRequest.model_validate({"prompt": ""})

    async def test_run_studio_agent_builds_input_and_sanitizes_filename(self) -> None:
        with patch.dict(os.environ, {"AGENT_MODEL": "openai:gpt-4.1-mini"}):
            output = await run_studio_agent(
                StudioAgentRequest(
                    prompt="Create a launch outline",
                    nodes=[StudioNode(id="node-1", title="Hero image", kind="image")],
                    job_id="job-1",
                ),
                runner=FakeRunner,
                mcp_servers=[],
            )

        self.assertEqual(output.title, "Launch outline")
        self.assertEqual(output.filename, "Launch-outline.md")
        self.assertIn("Customer request", FakeRunner.seen_input)
        self.assertIn("node-1", FakeRunner.seen_input)
        self.assertEqual(FakeRunner.seen_agent.tools, [])
        self.assertEqual(FakeRunner.seen_agent.mcp_servers, [])
        self.assertEqual(FakeRunner.seen_agent.model, "gpt-4.1-mini")

    async def test_agent_invocation_returns_structured_agentcore_result(self) -> None:
        output = StudioAgentOutput(
            title="Customer result",
            summary="The result is complete.",
            markdown="# Customer result",
            filename="customer-result.md",
        )
        with patch(
            "agent.studio_agent_next.run_studio_agent",
            new=AsyncMock(return_value=output),
        ) as runner:
            payload = await agent_invocation(
                {"prompt": "Make the result", "job_id": "job-9"},
                SimpleNamespace(session_id="session-9"),
            )

        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["result"]["title"], "Customer result")
        self.assertEqual(payload["job_id"], "job-9")
        self.assertEqual(payload["session_id"], "session-9")
        self.assertEqual(payload["tool_events"], [])
        runner.assert_awaited_once()
        request = runner.await_args.args[0]
        self.assertEqual(request.prompt, "Make the result")
        self.assertEqual(request.job_id, "job-9")

    async def test_agent_invocation_returns_json_error_instead_of_raising(self) -> None:
        payload = await agent_invocation({}, SimpleNamespace(session_id="session-err"))
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["error_type"], "ValidationError")
        self.assertIsNone(payload["result"])
        self.assertEqual(payload["session_id"], "session-err")

    def test_harvest_unwraps_gateway_mcp_image_output(self) -> None:
        studio = StudioAgentContext()
        wrapped = json.dumps(
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "status": "succeeded",
                                "image_url": "https://cdn.example/hero.png",
                                "output_path": "/tmp/renderhaus/media/hero.png",
                                "job_id": "seedream_1",
                            }
                        ),
                    }
                ],
                "isError": False,
            }
        )
        _record_run_tool_events(
            SimpleNamespace(
                new_items=[
                    SimpleNamespace(
                        type="tool_call_item",
                        call_id="call-1",
                        tool_name="Seedream___text_to_image",
                    ),
                    SimpleNamespace(
                        type="tool_call_output_item",
                        call_id="call-1",
                        output=wrapped,
                    ),
                ]
            ),
            studio,
        )

        self.assertEqual(len(studio.tool_events), 1)
        event = studio.tool_events[0]
        self.assertEqual(event.name, "Seedream___text_to_image")
        self.assertEqual(event.status, "succeeded")
        self.assertEqual(event.provider, "seedream")
        self.assertEqual(event.result["image_url"], "https://cdn.example/hero.png")
        self.assertEqual(event.assets, [])

    def test_harvest_reads_output_on_mcp_call_item(self) -> None:
        studio = StudioAgentContext()
        _record_run_tool_events(
            SimpleNamespace(
                new_items=[
                    SimpleNamespace(
                        type="tool_call_item",
                        call_id="mcp-9",
                        tool_name="Mureka___generate_music",
                        raw_item=SimpleNamespace(
                            name="Mureka___generate_music",
                            output={"status": "succeeded", "audio_url": "https://cdn.example/bed.mp3"},
                        ),
                    )
                ]
            ),
            studio,
        )
        self.assertEqual(studio.tool_events[0].result["audio_url"], "https://cdn.example/bed.mp3")

    async def test_run_studio_agent_returns_harvested_tool_events_on_context(self) -> None:
        class HarvestRunner:
            @classmethod
            async def run(cls, agent, input_value, **_kwargs):
                return SimpleNamespace(
                    final_output=StudioAgentOutput(
                        title="Hero",
                        summary="Image ready.",
                        markdown="# Hero",
                        filename="hero.md",
                    ),
                    new_items=[
                        SimpleNamespace(
                            type="tool_call_item",
                            call_id="call-img",
                            tool_name="Seedream___text_to_image",
                        ),
                        SimpleNamespace(
                            type="tool_call_output_item",
                            call_id="call-img",
                            output={
                                "status": "succeeded",
                                "image_url": "https://cdn.example/hero.png",
                            },
                        ),
                    ],
                )

        studio = StudioAgentContext()
        with patch.dict(os.environ, {"AGENT_MODEL": "openai:gpt-4.1-mini"}):
            await run_studio_agent(
                StudioAgentRequest(prompt="Make a hero image", job_id="job-img"),
                runner=HarvestRunner,
                studio=studio,
                mcp_servers=[],
            )

        self.assertEqual(studio.tool_events[0].result["image_url"], "https://cdn.example/hero.png")


if __name__ == "__main__":
    unittest.main()
