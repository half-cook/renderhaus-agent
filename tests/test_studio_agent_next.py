from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agents.memory import OpenAIResponsesCompactionSession

from agent.studio_agent_next import (
    StudioAgentContext,
    StudioAgentOutput,
    StudioAgentRequest,
    StudioNode,
    StudioToolEvent,
    _build_agent,
    _compaction_is_safe,
    _TurnCompactionPolicy,
    _committed_gateway_tools,
    _describe_gateway_mcp_tools,
    _gateway_tool_catalog,
    _gateway_requires_approval,
    _input_for,
    _record_run_tool_events,
    _record_stream_event,
    _tool_names_from_search_result,
    _tools_from_search_result,
    _unwrap_tool_output,
    _validate_video_delivery,
    _visible_gateway_tools,
    agent_invocation,
    normalize_markdown_filename,
    run_studio_agent,
)


class FakeRunner:
    seen_agent = None
    seen_input = ""
    seen_session = None
    seen_run_config = None

    @classmethod
    async def run(cls, agent, input_value, **kwargs):
        cls.seen_agent = agent
        cls.seen_input = input_value
        cls.seen_session = kwargs["session"]
        cls.seen_run_config = kwargs["run_config"]
        await cls.seen_session.add_items(
            [
                {"role": "user", "content": "Create a launch outline"},
                {"role": "assistant", "content": "The outline is ready."},
            ]
        )

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

    def test_versioned_nodes_expose_opaque_handles_not_expired_sources(self) -> None:
        rendered = _input_for(
            "Animate it",
            [
                StudioNode(
                    id="node-1",
                    title="Hero",
                    kind="image",
                    source="https://expired.example/frame.png",
                    version_id="version-1",
                )
            ],
        )
        self.assertIn("renderhaus-asset://version-1", rendered)
        self.assertNotIn("expired.example", rendered)

    def test_gateway_arguments_resolve_nested_asset_handles_at_call_time(self) -> None:
        published: list[str] = []

        def publish(version_id: str) -> str:
            published.append(version_id)
            return f"https://signed.example/{version_id}"

        studio = StudioAgentContext(source_publisher=publish)
        resolved = studio.prepare_gateway_arguments(
            "Remotion___render_timeline",
            {"visuals": [{"kind": "image", "url": "renderhaus-asset://version-1"}]},
        )
        self.assertEqual(resolved["visuals"][0]["url"], "https://signed.example/version-1")
        self.assertEqual(published, ["version-1"])

    def test_request_model_rejects_empty_prompt(self) -> None:
        with self.assertRaises(Exception):
            StudioAgentRequest.model_validate({"prompt": ""})

    def test_request_accepts_a_prompt_larger_than_four_thousand_tokens(self) -> None:
        prompt = "cinematic product detail " * 1_000

        request = StudioAgentRequest.model_validate({"prompt": prompt})

        self.assertGreater(len(request.prompt), 8_000)

    async def test_run_studio_agent_builds_input_and_sanitizes_filename(self) -> None:
        with patch.dict(os.environ, {"AGENT_MODEL": "openai:gpt-4.1-mini"}):
            output = await run_studio_agent(
                StudioAgentRequest(
                    prompt="Create a launch outline",
                    nodes=[StudioNode(id="node-1", title="Hero image", kind="image")],
                    conversation_id="conversation-1",
                    session_items=[
                        {"role": "user", "content": "Draft the launch concept"},
                        {
                            "role": "assistant",
                            "content": "The concept centers on a quiet product reveal.",
                        },
                    ],
                    job_id="job-1",
                ),
                runner=FakeRunner,
                mcp_servers=[],
            )

        self.assertEqual(output.title, "Launch outline")
        self.assertEqual(output.filename, "Launch-outline.md")
        self.assertIn("Customer request", FakeRunner.seen_input)
        self.assertNotIn("Earlier turns in this project conversation", FakeRunner.seen_input)
        self.assertNotIn("quiet product reveal", FakeRunner.seen_input)
        self.assertIn("node-1", FakeRunner.seen_input)
        session_items = await FakeRunner.seen_session.get_items()
        self.assertEqual(session_items[1]["role"], "assistant")
        self.assertIn("quiet product reveal", session_items[1]["content"])
        self.assertEqual(FakeRunner.seen_run_config.group_id, "conversation-1")
        self.assertEqual(FakeRunner.seen_run_config.workflow_name, "Renderhaus agent")
        self.assertIsInstance(FakeRunner.seen_session, OpenAIResponsesCompactionSession)
        self.assertEqual(FakeRunner.seen_session.compaction_mode, "input")
        self.assertEqual(FakeRunner.seen_session.model, "gpt-4.1-mini")
        self.assertEqual([tool.name for tool in FakeRunner.seen_agent.tools], ["report_progress"])
        self.assertEqual(FakeRunner.seen_agent.mcp_servers, [])
        self.assertEqual(FakeRunner.seen_agent.model, "gpt-4.1-mini")

    def test_agent_defaults_to_gpt_5_6_luna(self) -> None:
        with patch.dict(os.environ, {"AGENT_MODEL": ""}):
            agent = _build_agent([])

        self.assertEqual(agent.model, "gpt-5.6-luna")
        self.assertIsNone(agent.model_settings.reasoning)
        self.assertEqual(agent.model_settings.verbosity, "low")

    def test_gateway_calls_require_approval_unless_autonomous(self) -> None:
        manual = SimpleNamespace(context=StudioAgentContext(autonomous=False))
        autonomous = SimpleNamespace(context=StudioAgentContext(autonomous=True))

        self.assertTrue(_gateway_requires_approval(manual, None, None))
        self.assertFalse(_gateway_requires_approval(autonomous, None, None))

    def test_compaction_waits_for_all_pending_tool_outputs(self) -> None:
        history = [
            {"type": "message", "role": "assistant", "content": f"turn {index}"}
            for index in range(10)
        ]
        context = {
            "session_items": history,
            "compaction_candidate_items": history,
        }
        self.assertTrue(_compaction_is_safe(context))

        pending = {"type": "function_call", "call_id": "call-1", "name": "tool"}
        context["session_items"] = [*history, pending]
        context["compaction_candidate_items"] = [*history, pending]
        self.assertFalse(_compaction_is_safe(context))

        context["session_items"] = [
            *history,
            pending,
            {"type": "function_call_output", "call_id": "call-1", "output": "done"},
        ]
        self.assertTrue(_compaction_is_safe(context))

        # Streamed runs can expose the next tool call in the candidate list before
        # it appears in the full session snapshot.
        context["session_items"] = history
        context["compaction_candidate_items"] = [*history, pending]
        self.assertFalse(_compaction_is_safe(context))

    def test_compaction_policy_only_runs_between_completed_agent_turns(self) -> None:
        history = [
            {"type": "message", "role": "assistant", "content": f"turn {index}"}
            for index in range(10)
        ]
        context = {
            "session_items": history,
            "compaction_candidate_items": history,
        }
        policy = _TurnCompactionPolicy()

        self.assertFalse(policy(context))
        policy.enabled = True
        self.assertTrue(policy(context))

    def test_agent_omits_gpt_5_only_settings_for_gpt_4(self) -> None:
        with patch.dict(os.environ, {"AGENT_MODEL": "openai:gpt-4.1-mini"}):
            agent = _build_agent([])

        self.assertEqual(agent.model, "gpt-4.1-mini")
        self.assertIsNone(agent.model_settings.reasoning)
        self.assertIsNone(agent.model_settings.verbosity)

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
            chunks = [
                chunk
                async for chunk in agent_invocation(
                    {
                        "prompt": "Make the result",
                        "job_id": "job-9",
                        "conversation_id": "conversation-9",
                        "session_items": [{"role": "user", "content": "Earlier request"}],
                    },
                    SimpleNamespace(session_id="session-9"),
                )
            ]
            payload = chunks[-1]["payload"]

        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["result"]["title"], "Customer result")
        self.assertEqual(payload["job_id"], "job-9")
        self.assertEqual(payload["session_id"], "session-9")
        self.assertEqual(payload["tool_events"], [])
        self.assertEqual(payload["session_items"][0]["content"], "Earlier request")
        runner.assert_awaited_once()
        request = runner.await_args.args[0]
        self.assertEqual(request.prompt, "Make the result")
        self.assertEqual(request.job_id, "job-9")

    async def test_agent_invocation_returns_json_error_instead_of_raising(self) -> None:
        chunks = [
            chunk async for chunk in agent_invocation({}, SimpleNamespace(session_id="session-err"))
        ]
        payload = chunks[-1]["payload"]
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
                        arguments=json.dumps(
                            {
                                "prompt": "A quiet product reveal",
                                "aspect_ratio": "9:16",
                                "api_token": "must-not-leak",
                                "config": {
                                    "api_key": "nested-secret",
                                    "options": [
                                        {
                                            "authorization": "Bearer nested",
                                            "x-api-key": "nested-key",
                                            "quality": "high",
                                        },
                                        None,
                                    ],
                                    "optional": None,
                                },
                            }
                        ),
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
        self.assertEqual(
            event.arguments,
            {
                "prompt": "A quiet product reveal",
                "aspect_ratio": "9:16",
                "config": {"options": [{"quality": "high"}]},
            },
        )
        self.assertEqual(event.public()["arguments"], event.arguments)
        self.assertEqual(event.result["image_url"], "https://cdn.example/hero.png")
        self.assertEqual(event.assets, [])

    def test_unwrap_openai_mcp_text_part_json(self) -> None:
        payload = _unwrap_tool_output(
            {
                "type": "text",
                "text": json.dumps(
                    {"status": "succeeded", "image_url": "https://cdn.example/hero.png"}
                ),
            }
        )
        self.assertEqual(payload["image_url"], "https://cdn.example/hero.png")

    def test_harvest_unwraps_sdk_text_part_output(self) -> None:
        studio = StudioAgentContext()
        _record_run_tool_events(
            SimpleNamespace(
                new_items=[
                    SimpleNamespace(
                        type="tool_call_item",
                        call_id="call-sdk",
                        tool_name="Seedream___text_to_image",
                    ),
                    SimpleNamespace(
                        type="tool_call_output_item",
                        call_id="call-sdk",
                        output={
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "status": "succeeded",
                                    "image_url": "https://cdn.example/from-sdk.png",
                                }
                            ),
                        },
                    ),
                ]
            ),
            studio,
        )
        self.assertEqual(
            studio.tool_events[0].result["image_url"], "https://cdn.example/from-sdk.png"
        )

    def test_gateway_mcp_descriptions_are_restored(self) -> None:
        catalog = _gateway_tool_catalog()
        self.assertIn("Remotion___render_timeline", catalog)
        self.assertIn(
            "edit decision list",
            catalog["Remotion___render_timeline"]["description"].lower(),
        )
        described = _describe_gateway_mcp_tools(
            [
                {"name": "Remotion___render_timeline", "description": ""},
                {"name": "Seedream___text_to_image"},
            ]
        )
        self.assertTrue(described[0]["description"])
        self.assertEqual(described[0]["title"], "Compose final MP4")
        self.assertIn("image", described[1]["description"].lower())

    def test_gateway_search_reveals_only_discovered_tools(self) -> None:
        tools = [
            {"name": "x_amz_bedrock_agentcore_search"},
            {"name": "Seedream___text_to_image"},
            {"name": "Mureka___generate_music"},
        ]
        self.assertEqual(
            [item["name"] for item in _visible_gateway_tools(tools, set())],
            ["x_amz_bedrock_agentcore_search"],
        )
        discovered = _tool_names_from_search_result(
            SimpleNamespace(
                structuredContent={
                    "tools": [
                        {
                            "name": "Seedream___text_to_image",
                            "description": "Generate a still image.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"prompt": {"type": "string"}},
                                "required": ["prompt"],
                            },
                        }
                    ]
                }
            )
        )
        self.assertEqual(discovered, {"Seedream___text_to_image"})
        self.assertEqual(
            [item["name"] for item in _visible_gateway_tools(tools, discovered)],
            ["x_amz_bedrock_agentcore_search", "Seedream___text_to_image"],
        )
        definitions = _tools_from_search_result(
            {
                "structuredContent": {
                    "tools": [
                        {
                            "name": "Seedream___text_to_image",
                            "description": "Generate a still image.",
                            "inputSchema": {"type": "object", "properties": {}},
                        }
                    ]
                }
            }
        )
        self.assertEqual(definitions[0].name, "Seedream___text_to_image")

    def test_paused_gateway_tool_definition_can_be_restored(self) -> None:
        tools = _committed_gateway_tools({"Remotion___render_timeline"})

        self.assertEqual([tool.name for tool in tools], ["Remotion___render_timeline"])
        self.assertIn("visuals", tools[0].input_schema["properties"])

    def test_stream_events_expose_safe_reasoning_and_tool_progress(self) -> None:
        studio = StudioAgentContext()
        names: dict[str, str] = {}
        arguments: dict[str, dict] = {}
        _record_stream_event(
            SimpleNamespace(
                type="run_item_stream_event",
                name="reasoning_item_created",
                item=SimpleNamespace(
                    raw_item=SimpleNamespace(
                        summary=[SimpleNamespace(text="Checking which image tool fits.")],
                        content=[SimpleNamespace(text="private chain of thought")],
                    )
                ),
            ),
            studio,
            names,
            arguments,
        )
        _record_stream_event(
            SimpleNamespace(
                type="run_item_stream_event",
                name="tool_called",
                item=SimpleNamespace(
                    call_id="call-1",
                    tool_name="Seedream___text_to_image",
                    arguments={"prompt": "A quiet portrait"},
                ),
            ),
            studio,
            names,
            arguments,
        )
        _record_stream_event(
            SimpleNamespace(
                type="run_item_stream_event",
                name="tool_output",
                item=SimpleNamespace(
                    call_id="call-1",
                    output={"status": "succeeded", "image_url": "https://cdn.example/image.png"},
                ),
            ),
            studio,
            names,
            arguments,
        )

        self.assertEqual(studio.progress_events[0].message, "Checking which image tool fits.")
        self.assertNotIn("private chain", studio.progress_events[0].message)
        self.assertEqual(studio.progress_events[-1].type, "TOOL_CALL_RESULT")
        self.assertEqual(studio.tool_events[0].status, "succeeded")

    def test_report_progress_tool_wrapper_does_not_leak_as_generic_tool(self) -> None:
        studio = StudioAgentContext()
        names: dict[str, str] = {}
        arguments: dict[str, dict] = {}

        _record_stream_event(
            SimpleNamespace(
                type="run_item_stream_event",
                name="tool_called",
                item=SimpleNamespace(
                    call_id="progress-1",
                    tool_name="report_progress",
                    arguments={"message": "I am checking the model catalog."},
                ),
            ),
            studio,
            names,
            arguments,
        )
        _record_stream_event(
            SimpleNamespace(
                type="run_item_stream_event",
                name="tool_output",
                item=SimpleNamespace(
                    call_id="progress-1",
                    output="Update shown to the customer.",
                ),
            ),
            studio,
            names,
            arguments,
        )

        self.assertEqual(names, {"progress-1": "report_progress"})
        self.assertEqual(studio.tool_events, [])
        self.assertEqual(studio.progress_events, [])

    def test_video_delivery_requires_a_model_planned_successful_remotion_render(self) -> None:
        request = StudioAgentRequest(prompt="Create a short alien video")
        studio = StudioAgentContext(
            tool_events=[
                StudioToolEvent(
                    id="create-video",
                    name="Seedance___text_to_video",
                    label="Generate video",
                    status="succeeded",
                    summary="Clip ready.",
                    provider="seedance",
                    result={"status": "succeeded", "video_url": "https://cdn/clip.mp4"},
                )
            ]
        )

        final = StudioAgentOutput(
            title="Alien video",
            summary="The result is ready.",
            markdown="# Alien video",
            filename="alien-video.md",
        )
        self.assertFalse(_validate_video_delivery(request, studio, final))
        self.assertIn("Video export incomplete", final.markdown)
        self.assertEqual(studio.progress_events[-1].status, "failed")

        studio.tool_events.append(
            StudioToolEvent(
                id="render-progress",
                name="Remotion___get_render_progress",
                label="Poll Remotion render",
                status="succeeded",
                summary="Final MP4 ready.",
                provider="remotion",
                result={"status": "succeeded", "url": "https://cdn/final.mp4"},
            )
        )
        self.assertTrue(_validate_video_delivery(request, studio))

    def test_video_delivery_guard_ignores_video_context_without_a_video_deliverable(
        self,
    ) -> None:
        studio = StudioAgentContext(
            tool_events=[
                StudioToolEvent(
                    id="create-image",
                    name="Seedream___text_to_image",
                    label="Generate image",
                    status="succeeded",
                    summary="Image ready.",
                    provider="seedream",
                )
            ]
        )
        prior = [{"role": "user", "content": "Create a 60 second product video"}]

        self.assertTrue(
            _validate_video_delivery(
                StudioAgentRequest(prompt="Retry it", session_items=prior),
                studio,
            )
        )
        self.assertTrue(
            _validate_video_delivery(
                StudioAgentRequest(prompt="Describe this video", session_items=prior),
                studio,
            )
        )
        self.assertTrue(
            _validate_video_delivery(
                StudioAgentRequest(prompt="Create a video thumbnail", session_items=prior),
                studio,
            )
        )
        self.assertFalse(
            _validate_video_delivery(
                StudioAgentRequest(prompt="Render these videos into one MP4", session_items=prior),
                studio,
            )
        )

    def test_post_stream_harvest_does_not_register_the_same_asset_twice(self) -> None:
        registrations: list[str] = []

        def register_assets(**_kwargs):
            registrations.append("registered")
            return [
                {
                    "asset_id": "asset-1",
                    "version_id": "version-1",
                    "kind": "image",
                }
            ]

        studio = StudioAgentContext(asset_registrar=register_assets)
        names: dict[str, str] = {}
        arguments: dict[str, dict] = {}
        call = SimpleNamespace(
            type="tool_call_item",
            call_id="streamed-image",
            tool_name="Seedream___text_to_image",
            arguments={"prompt": "A portrait"},
        )
        output = SimpleNamespace(
            type="tool_call_output_item",
            call_id="streamed-image",
            output={"status": "succeeded", "image_url": "https://cdn.example/portrait.png"},
        )
        _record_stream_event(
            SimpleNamespace(type="run_item_stream_event", name="tool_called", item=call),
            studio,
            names,
            arguments,
        )
        _record_stream_event(
            SimpleNamespace(type="run_item_stream_event", name="tool_output", item=output),
            studio,
            names,
            arguments,
        )
        _record_run_tool_events(SimpleNamespace(new_items=[call, output]), studio)

        self.assertEqual(registrations, ["registered"])
        self.assertEqual(len(studio.tool_events), 1)
        self.assertEqual(studio.tool_events[0].assets[0]["version_id"], "version-1")

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
                            output={
                                "status": "succeeded",
                                "audio_url": "https://cdn.example/bed.mp3",
                            },
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

    async def test_gateway_connection_does_not_emit_scripted_progress(self) -> None:
        class FakeManager:
            def __init__(self, *_args, **_kwargs) -> None:
                self.active_servers = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

        studio = StudioAgentContext()
        with (
            patch.dict(os.environ, {"AGENT_MODEL": "openai:gpt-4.1-mini"}),
            patch("agent.studio_agent_next.gateway_mcp_server", return_value=object()),
            patch("agent.studio_agent_next.MCPServerManager", FakeManager),
        ):
            await run_studio_agent(
                StudioAgentRequest(prompt="Make a launch outline", job_id="job-gateway"),
                runner=FakeRunner,
                studio=studio,
            )

        self.assertFalse(any(event.id == "gateway-connect" for event in studio.progress_events))
        self.assertFalse(any("Choosing" in event.message for event in studio.progress_events))

    async def test_model_failure_emits_only_the_real_run_error(self) -> None:
        class FakeManager:
            def __init__(self, *_args, **_kwargs) -> None:
                self.active_servers = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

        class FailingRunner:
            @classmethod
            async def run(cls, *_args, **_kwargs):
                raise RuntimeError("model failed")

        studio = StudioAgentContext()
        with (
            patch.dict(os.environ, {"AGENT_MODEL": "gpt-5.6-luna"}),
            patch("agent.studio_agent_next.gateway_mcp_server", return_value=object()),
            patch("agent.studio_agent_next.MCPServerManager", FakeManager),
        ):
            with self.assertRaises(RuntimeError):
                await run_studio_agent(
                    StudioAgentRequest(prompt="Make a launch outline", job_id="job-failure"),
                    runner=FailingRunner,
                    studio=studio,
                )

        self.assertFalse(any(event.id == "gateway-connect" for event in studio.progress_events))
        self.assertEqual(studio.progress_events[-1].type, "RUN_ERROR")


if __name__ == "__main__":
    unittest.main()
