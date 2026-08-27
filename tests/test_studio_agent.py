from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agents import RunContextWrapper
import server.studio as studio_module

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
from server.studio import (
    AgentBody,
    _agent_result,
    _hydrate_tool_event_assets,
    _partial_agent_result,
    _encode_playback_ticket,
    _playback_ticket_workspace,
    studio_asset_content,
    studio_agent,
    studio_agent_job,
)
from server.studio_state import CanvasConflictError, StudioRepository
from server.auth import _authorized_parties, current_workspace_id


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
    def test_primary_agent_asset_preserves_the_latest_media_kind(self) -> None:
        audio = {
            "asset_id": "audio-asset",
            "version_id": "audio-version",
            "kind": "audio",
            "filename": "bed.mp3",
            "mime_type": "audio/mpeg",
        }
        image = {
            "asset_id": "image-asset",
            "version_id": "image-version",
            "kind": "image",
            "filename": "cover.png",
            "mime_type": "image/png",
        }
        final = StudioAgentOutput(
            title="Campaign assets",
            summary="A music bed and cover image are ready.",
            markdown="# Campaign assets",
            filename="campaign-assets.md",
        )
        outcome = StudioAgentRun(
            final=final,
            tool_events=[
                StudioToolEvent(
                    id="audio-call",
                    name="generate_music",
                    label="Music generation",
                    status="succeeded",
                    summary="Music ready.",
                    assets=[audio],
                ),
                StudioToolEvent(
                    id="image-call",
                    name="generate_image",
                    label="Image generation",
                    status="succeeded",
                    summary="Image ready.",
                    assets=[image],
                ),
            ],
        )

        self.assertEqual(_agent_result(outcome)["primary_asset"], image)
        self.assertEqual(
            _partial_agent_result({"tool_calls": [event.public() for event in outcome.tool_events]})[
                "primary_asset"
            ],
            image,
        )

    def test_hydrate_ingests_gateway_http_urls_and_skips_lambda_tmp_paths(self) -> None:
        event = StudioToolEvent(
            id="call-1",
            name="Seedream___text_to_image",
            label="Seedream text to image",
            status="succeeded",
            summary="Image ready.",
            result={
                "status": "succeeded",
                "image_url": "https://cdn.example/hero.png",
                "output_path": "/tmp/renderhaus/media/hero.png",
            },
        )
        captured: list[dict] = []

        def fake_register(**kwargs):
            captured.append(kwargs)
            return [
                {
                    "asset_id": "asset-1",
                    "version_id": "version-1",
                    "kind": "image",
                    "filename": "hero.png",
                }
            ]

        with patch.object(studio_module, "_register_payload_assets", side_effect=fake_register):
            _hydrate_tool_event_assets(
                [event],
                workspace_id="user:local",
                project_id="untitled",
                user_id="local",
                execution_id="job-1",
            )

        self.assertEqual(event.assets[0]["version_id"], "version-1")
        self.assertEqual(captured[0]["payload"], {"image_url": "https://cdn.example/hero.png"})
        self.assertEqual(captured[0]["kind"], "image")
        self.assertEqual(_agent_result(StudioAgentRun(
            final=StudioAgentOutput(
                title="Hero",
                summary="Ready.",
                markdown="# Hero",
                filename="hero.md",
            ),
            tool_events=[event],
        ))["primary_asset"]["version_id"], "version-1")

    def test_hydrate_skips_queued_poll_results(self) -> None:
        event = StudioToolEvent(
            id="poll-1",
            name="Seedance___get_video_task",
            label="Get video task",
            status="queued",
            summary="Still rendering.",
            result={"status": "queued", "video_url": "https://cdn.example/clip.mp4"},
        )
        with patch.object(studio_module, "_register_payload_assets") as register:
            _hydrate_tool_event_assets(
                [event],
                workspace_id="user:local",
                project_id="untitled",
                user_id="local",
                execution_id="job-1",
            )
        register.assert_not_called()
        self.assertEqual(event.assets, [])

    def test_playback_ticket_is_asset_and_workspace_scoped(self) -> None:
        with patch.dict(os.environ, {"STUDIO_MEDIA_TICKET_SECRET": "test-ticket-secret"}):
            ticket = _encode_playback_ticket(
                workspace_id="user:one",
                version_id="version-1",
                expires_at=4_102_444_800,
            )
            self.assertEqual(_playback_ticket_workspace(ticket, "version-1"), "user:one")
            self.assertIsNone(_playback_ticket_workspace(ticket, "version-2"))
            self.assertIsNone(_playback_ticket_workspace(f"{ticket}tampered", "version-1"))

    async def test_playback_ticket_serves_only_the_scoped_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = StudioRepository(
                Path(directory) / "studio.sqlite3",
                Path(directory) / "media",
            )
            repository.list_projects("user:one", "one")
            asset = repository.register_bytes(
                workspace_id="user:one",
                project_id="untitled",
                user_id="one",
                content=b"generated-frame",
                filename="frame.png",
                kind="image",
                mime_type="image/png",
            )
            with (
                patch.object(studio_module, "repository", repository),
                patch.dict(os.environ, {"STUDIO_MEDIA_TICKET_SECRET": "test-ticket-secret"}),
            ):
                ticket = _encode_playback_ticket(
                    workspace_id="user:one",
                    version_id=asset.version_id,
                    expires_at=4_102_444_800,
                )
                response = await studio_asset_content(asset.version_id, auth=None, ticket=ticket)

            self.assertEqual(Path(response.path).read_bytes(), b"generated-frame")
            self.assertEqual(response.headers["cache-control"], "private, max-age=300")

    def test_default_clerk_parties_include_both_local_frontends(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLERK_AUTHORIZED_PARTIES", None)
            parties = _authorized_parties()

        self.assertIn("http://localhost:3000", parties)
        self.assertIn("http://localhost:5174", parties)

    def test_clerk_organization_is_the_workspace_boundary(self) -> None:
        auth = SimpleNamespace(payload={"sub": "user_123", "org_id": "org_456"})
        self.assertEqual(current_workspace_id(auth), "org:org_456")  # type: ignore[arg-type]

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

    async def test_generated_asset_handle_can_feed_a_later_tool(self) -> None:
        def fake_dispatch(_provider, _tool, _arguments):
            return {"status": "succeeded", "image_url": "https://example.test/hero.png"}

        def fake_registrar(**_kwargs):
            return [
                {
                    "asset_id": "asset-1",
                    "version_id": "version-1",
                    "kind": "image",
                    "filename": "hero.png",
                    "mime_type": "image/png",
                }
            ]

        context = StudioAgentContext(
            dispatcher=fake_dispatch,
            asset_registrar=fake_registrar,
            source_resolver=lambda version_id: f"/managed/{version_id}.png",
        )
        payload = await _invoke_provider(
            RunContextWrapper(context=context),
            name="generate_image",
            label="Image generation",
            provider="seedream",
            tool_name="text_to_image",
            arguments={"prompt": "A product hero"},
            output_kind="image",
        )

        self.assertEqual(json.loads(payload)["assets"][0]["version_id"], "version-1")
        self.assertEqual(context.source_for("version-1", "image"), "/managed/version-1.png")

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
        self.assertEqual(len(FakeRunner.seen_agent.tools), 7)
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
                    id="tool-call-1",
                    name="generate_image",
                    label="Image generation",
                    status="dry_run",
                    summary="Dry run complete.",
                )
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            test_repository = StudioRepository(
                Path(directory) / "studio.sqlite3",
                Path(directory) / "media",
            )
            test_repository.create_project("user:local", "local", "Untitled", project_id="untitled")
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), patch(
                "server.studio.repository", test_repository
            ), patch("server.studio.run_studio_agent", new=AsyncMock(return_value=outcome)):
                queued = await studio_agent(AgentBody(prompt="Make the result"), None)
                await asyncio.sleep(0.05)
                payload = await studio_agent_job(queued["job_id"], None)

        self.assertEqual(queued["status"], "queued")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["result"]["filename"], "customer-result.md")
        self.assertEqual(payload["result"]["tool_events"][0]["name"], "generate_image")

    def test_asset_versions_are_workspace_scoped_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = StudioRepository(
                Path(directory) / "studio.sqlite3",
                Path(directory) / "media",
            )
            repository.create_project("user:one", "one", "Project", project_id="project-one")
            repository.create_project("user:two", "two", "Project", project_id="project-one")
            self.assertEqual(len(repository.list_projects("user:two", "two")), 1)
            first = repository.register_bytes(
                workspace_id="user:one",
                project_id="project-one",
                user_id="one",
                content=b"first image",
                filename="hero.png",
                kind="image",
                mime_type="image/png",
            )
            second = repository.register_bytes(
                workspace_id="user:one",
                project_id="project-one",
                user_id="one",
                content=b"second image",
                filename="hero-v2.png",
                kind="image",
                mime_type="image/png",
                asset_id=first.asset_id,
                source_version_ids=[first.version_id],
            )

            self.assertEqual(first.asset_id, second.asset_id)
            self.assertNotEqual(first.version_id, second.version_id)
            self.assertIsNotNone(repository.get_version("user:one", first.version_id))
            self.assertIsNone(repository.get_version("user:two", first.version_id))
            self.assertEqual(repository.version_path("user:one", first.version_id).read_bytes(), b"first image")

            revision = repository.get_canvas("user:one", "project-one")["revision"]
            repository.save_canvas(
                "user:one",
                "project-one",
                "one",
                {"projectName": "Project", "nodes": [], "edges": [], "viewport": {}},
                expected_revision=revision,
            )
            with self.assertRaises(CanvasConflictError):
                repository.save_canvas(
                    "user:one",
                    "project-one",
                    "one",
                    {"projectName": "Stale", "nodes": [], "edges": [], "viewport": {}},
                    expected_revision=revision,
                )

    def test_default_project_creation_is_idempotent_under_concurrency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = StudioRepository(
                Path(directory) / "studio.sqlite3",
                Path(directory) / "media",
            )

            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(
                    pool.map(
                        lambda _index: repository.list_projects("user:one", "one"),
                        range(24),
                    )
                )

            self.assertTrue(all(items[0]["id"] == "untitled" for items in results))
            self.assertEqual(len(repository.list_projects("user:one", "one")), 1)


if __name__ == "__main__":
    unittest.main()
