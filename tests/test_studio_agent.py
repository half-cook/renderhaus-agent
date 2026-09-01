from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from botocore.exceptions import ClientError

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
from agent.studio_agent_next import StudioAgentApprovalRequired, StudioApprovalRequest
from server.studio import (
    AgentApprovalBody,
    AgentBody,
    _agent_result,
    _hydrate_tool_event_assets,
    _partial_agent_result,
    _media_generation_failed,
    _recent_conversation_media_references,
    _encode_playback_ticket,
    _playback_ticket_workspace,
    studio_asset_content,
    studio_agent,
    studio_agent_job,
    decide_studio_agent_tool,
)
from server.assets import publish_provider_input_url
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
    def test_deictic_video_edit_recovers_latest_durable_sequence_in_story_order(self) -> None:
        explicit = [
            StudioNodeReference(
                id="selected-image",
                title="Selected image",
                kind="image",
                asset_id="image-asset",
                version_id="image-version",
            )
        ]
        calls = [
            {
                "name": "Seedance___image_to_video",
                "arguments": {"prompt": "Opening aerial"},
                "result": {"job_id": "job-1"},
                "assets": [],
            },
            {
                "name": "Seedance___image_to_video",
                "arguments": {"prompt": "Ecological transformation"},
                "result": {"status": "failed"},
                "assets": [],
            },
            {
                "name": "Seedance___image_to_video",
                "arguments": {"prompt": "Final pullback"},
                "result": {"job_id": "job-3"},
                "assets": [],
            },
            {
                "name": "Seedance___image_to_video",
                "arguments": {"prompt": "Ecological transformation"},
                "result": {"job_id": "job-2"},
                "assets": [],
            },
            {
                "name": "Seedance___get_video_task",
                "arguments": {"job_id": "job-3"},
                "result": {"job_id": "job-3", "status": "succeeded"},
                "assets": [{"kind": "video", "asset_id": "asset-3", "version_id": "version-3"}],
            },
            {
                "name": "Seedance___get_video_task",
                "arguments": {"job_id": "job-1"},
                "result": {"job_id": "job-1", "status": "succeeded"},
                "assets": [{"kind": "video", "asset_id": "asset-1", "version_id": "version-1"}],
            },
            {
                "name": "Seedance___get_video_task",
                "arguments": {"job_id": "job-2"},
                "result": {"job_id": "job-2", "status": "succeeded"},
                "assets": [{"kind": "video", "asset_id": "asset-2", "version_id": "version-2"}],
            },
            {
                "name": "Mureka___query_music_task",
                "arguments": {},
                "result": {"status": "succeeded"},
                "assets": [{"kind": "audio", "asset_id": "score", "version_id": "score-version"}],
            },
        ]
        with patch.object(
            studio_module.repository,
            "list_executions",
            return_value=[{"status": "completed", "tool_calls": calls}],
        ):
            recovered = _recent_conversation_media_references(
                "Render these videos into one video",
                explicit,
                workspace_id="workspace",
                conversation_id="conversation",
            )

        self.assertEqual(
            [reference.version_id for reference in recovered],
            ["image-version", "version-1", "version-2", "version-3", "score-version"],
        )
        self.assertEqual(recovered[2].title, "Existing sequence clip 2")
        self.assertEqual(recovered[2].prompt, "Ecological transformation")

    def test_explicit_video_selection_is_not_replaced_by_conversation_history(self) -> None:
        explicit = [
            StudioNodeReference(id="one", title="One", kind="video"),
            StudioNodeReference(id="two", title="Two", kind="video"),
        ]

        with patch.object(studio_module.repository, "list_executions") as list_executions:
            recovered = _recent_conversation_media_references(
                "Merge these videos",
                explicit,
                workspace_id="workspace",
                conversation_id="conversation",
            )

        self.assertIs(recovered, explicit)
        list_executions.assert_not_called()

    def test_partial_result_does_not_label_started_tools_as_completed(self) -> None:
        result = _partial_agent_result(
            {
                "tool_calls": [
                    {
                        "id": "call-1",
                        "label": "Seedance get video task",
                        "status": "running",
                        "summary": "Calling seedance get video task.",
                        "assets": [],
                    }
                ]
            }
        )

        self.assertIn("No tool completed", result["markdown"])
        self.assertNotIn("Completed work", result["markdown"])

    def test_provider_input_publication_uploads_once_and_returns_signed_https_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "frame.png"
            source.write_bytes(b"durable-frame")
            s3 = MagicMock()
            s3.head_object.side_effect = ClientError(
                {"Error": {"Code": "404", "Message": "missing"}},
                "HeadObject",
            )
            s3.generate_presigned_url.return_value = "https://signed.example/frame.png"
            with (
                patch("server.assets._s3", return_value=s3),
                patch.dict(os.environ, {"PROVIDER_INPUT_BUCKET": "provider-inputs"}),
            ):
                url = publish_provider_input_url(
                    source_path=source,
                    workspace_id="user:local",
                    version_id="version-1",
                    filename="frame.png",
                    mime_type="image/png",
                )
        self.assertEqual(url, "https://signed.example/frame.png")
        s3.upload_file.assert_called_once()
        upload = s3.upload_file.call_args.kwargs
        self.assertEqual(upload["Bucket"], "provider-inputs")
        self.assertIn("/version-1/frame.png", upload["Key"])
        self.assertNotIn("user:local", upload["Key"])

    def test_failed_media_without_assets_is_not_a_completed_run(self) -> None:
        outcome = SimpleNamespace(
            tool_events=[
                StudioToolEvent(
                    id="video-1",
                    name="Seedance___image_to_video",
                    label="Animate image",
                    status="failed",
                    summary="Provider rejected the input.",
                )
            ]
        )
        self.assertTrue(_media_generation_failed(outcome, {"assets": []}))
        self.assertFalse(
            _media_generation_failed(outcome, {"assets": [{"version_id": "version-1"}]})
        )

    def test_api_accepts_large_agent_prompts(self) -> None:
        prompt = "cinematic product detail " * 1_000

        body = AgentBody(prompt=prompt)

        self.assertGreater(len(body.prompt), 8_000)

    def test_existing_execution_schema_migrates_without_losing_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "studio.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    """
                    CREATE TABLE workspaces (
                        id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL, created_at INTEGER NOT NULL
                    );
                    CREATE TABLE projects (
                        id TEXT NOT NULL, workspace_id TEXT NOT NULL, name TEXT NOT NULL,
                        created_by TEXT NOT NULL, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                        PRIMARY KEY(workspace_id, id)
                    );
                    CREATE TABLE executions (
                        id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, project_id TEXT,
                        created_by TEXT NOT NULL, prompt TEXT NOT NULL, status TEXT NOT NULL,
                        message TEXT NOT NULL, result_json TEXT, error_type TEXT,
                        created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
                    );
                    INSERT INTO workspaces VALUES ('user:local', 'local', 1);
                    INSERT INTO projects VALUES ('one', 'user:local', 'One', 'local', 1, 1);
                    INSERT INTO executions VALUES (
                        'legacy-run', 'user:local', 'one', 'local', 'Keep this', 'completed',
                        'Completed.', '{"markdown":"Preserved result"}', NULL, 1, 2
                    );
                    """
                )
            repository = StudioRepository(database, Path(directory) / "media")
            conversation = repository.list_conversations("user:local", "one", "local")[0]
            run = repository.get_execution("user:local", "legacy-run")
            items = repository.get_conversation_items("user:local", conversation["id"])

        self.assertEqual(run["conversation_id"], conversation["id"])
        self.assertEqual(run["turn_index"], 1)
        self.assertEqual(items[-1]["content"], "Preserved result")

    def test_legacy_runs_backfill_into_a_durable_project_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            test_repository = StudioRepository(
                Path(directory) / "studio.sqlite3",
                Path(directory) / "media",
            )
            test_repository.create_project("user:local", "local", "One", project_id="one")
            test_repository.create_project("user:local", "local", "Two", project_id="two")
            first = test_repository.create_execution(
                workspace_id="user:local",
                project_id="one",
                user_id="local",
                prompt="Create the concept",
            )
            test_repository.update_execution(
                "user:local",
                first["job_id"],
                status="completed",
                message="Completed concept.",
                result={"title": "Concept", "markdown": "A quiet product reveal."},
            )
            second = test_repository.create_execution(
                workspace_id="user:local",
                project_id="one",
                user_id="local",
                prompt="Make it warmer",
            )
            test_repository.update_execution(
                "user:local",
                second["job_id"],
                status="completed",
                message="Completed warmer concept.",
                result={"title": "Warm concept", "markdown": "Use amber light."},
            )
            test_repository.create_execution(
                workspace_id="user:local",
                project_id="two",
                user_id="local",
                prompt="Keep this out of project one",
            )
            conversations = test_repository.list_conversations("user:local", "one", "local")
            conversation_id = conversations[0]["id"]
            items = test_repository.get_conversation_items("user:local", conversation_id)
            runs = test_repository.list_executions(
                "user:local", project_id="one", conversation_id=conversation_id
            )
            other = test_repository.list_conversations("user:local", "two", "local")

        self.assertEqual(conversations[0]["title"], "Project conversation")
        self.assertEqual([item["role"] for item in items], ["user", "assistant"] * 2)
        self.assertEqual(items[-1]["content"], "Use amber light.")
        self.assertEqual([run["turn_index"] for run in reversed(runs)], [1, 2])
        self.assertNotEqual(other[0]["id"], conversation_id)

    def test_conversations_isolate_session_items_and_execution_lists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = StudioRepository(
                Path(directory) / "studio.sqlite3",
                Path(directory) / "media",
            )
            repository.create_project("user:local", "local", "One", project_id="one")
            first = repository.list_conversations("user:local", "one", "local")[0]
            second = repository.create_conversation("user:local", "one", "local", "Campaign B")
            repository.replace_conversation_items(
                "user:local", first["id"], [{"role": "user", "content": "Campaign A"}]
            )
            execution = repository.create_execution(
                workspace_id="user:local",
                project_id="one",
                conversation_id=second["id"],
                user_id="local",
                prompt="Campaign B",
            )
            repository.update_conversation(
                "user:local", second["id"], title="Renamed", status="archived"
            )
            active = repository.list_conversations("user:local", "one", "local")
            first_items = repository.get_conversation_items("user:local", first["id"])

        self.assertEqual(
            first_items[0]["content"],
            "Campaign A",
        )
        self.assertEqual(execution["conversation_id"], second["id"])
        self.assertNotIn(second["id"], {conversation["id"] for conversation in active})

    def test_tool_call_arguments_survive_execution_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            test_repository = StudioRepository(
                Path(directory) / "studio.sqlite3",
                Path(directory) / "media",
            )
            test_repository.create_project(
                "user:local",
                "local",
                "Project",
                project_id="project",
            )
            execution = test_repository.create_execution(
                workspace_id="user:local",
                project_id="project",
                user_id="local",
                prompt="Create a portrait",
            )
            test_repository.append_tool_call(
                workspace_id="user:local",
                execution_id=execution["job_id"],
                event={
                    "id": "tool-1",
                    "name": "Seedream___text_to_image",
                    "label": "Generate image",
                    "status": "succeeded",
                    "arguments": {
                        "prompt": "A quiet portrait",
                        "aspect_ratio": "9:16",
                    },
                    "result": {"status": "succeeded", "result": "provider value"},
                },
            )

            persisted = test_repository.get_execution("user:local", execution["job_id"])

        self.assertIsNotNone(persisted)
        tool_call = persisted["tool_calls"][0]
        self.assertEqual(tool_call["arguments"]["prompt"], "A quiet portrait")
        self.assertEqual(tool_call["arguments"]["aspect_ratio"], "9:16")

    def test_agent_progress_events_are_persisted_and_updated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            test_repository = StudioRepository(
                Path(directory) / "studio.sqlite3",
                Path(directory) / "media",
            )
            test_repository.create_project("user:local", "local", "Project", project_id="project")
            execution = test_repository.create_execution(
                workspace_id="user:local",
                project_id="project",
                user_id="local",
                prompt="Create a portrait",
            )
            event = {
                "id": "tool-call-1",
                "type": "TOOL_CALL_START",
                "title": "Generate image",
                "message": "Calling image generation.",
                "status": "running",
                "tool_call_id": "call-1",
                "tool_call_name": "Seedream___text_to_image",
            }
            test_repository.append_agent_event(
                workspace_id="user:local",
                execution_id=execution["job_id"],
                event=event,
            )
            test_repository.append_agent_event(
                workspace_id="user:local",
                execution_id=execution["job_id"],
                event={
                    **event,
                    "type": "TOOL_CALL_RESULT",
                    "message": "The image is ready.",
                    "status": "completed",
                },
            )
            persisted = test_repository.get_execution("user:local", execution["job_id"])

        self.assertIsNotNone(persisted)
        self.assertEqual(len(persisted["events"]), 1)
        self.assertEqual(persisted["events"][0]["type"], "TOOL_CALL_RESULT")
        self.assertEqual(
            persisted["events"][0]["tool_call_name"],
            "Seedream___text_to_image",
        )

    def test_tool_approvals_persist_the_resumable_checkpoint_and_each_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = StudioRepository(
                Path(directory) / "studio.sqlite3",
                Path(directory) / "media",
            )
            repository.create_project("user:local", "local", "Project", project_id="project")
            execution = repository.create_execution(
                workspace_id="user:local",
                project_id="project",
                user_id="local",
                prompt="Create two images",
                autonomous=False,
                request={"prompt": "Create two images", "project_id": "project"},
            )
            approvals = [
                {
                    "call_id": "call-1",
                    "tool_name": "Seedream___text_to_image",
                    "label": "Generate first image",
                    "arguments": {"prompt": "First"},
                },
                {
                    "call_id": "call-2",
                    "tool_name": "Seedream___text_to_image",
                    "label": "Generate second image",
                    "arguments": {"prompt": "Second"},
                },
            ]
            repository.pause_execution(
                "user:local",
                execution["job_id"],
                run_state="serialized-run-state",
                approvals=approvals,
            )

            first, ready = repository.decide_execution_approval(
                "user:local", execution["job_id"], "call-1", decision="approve"
            )
            self.assertFalse(ready)
            self.assertEqual(first["status"], "awaiting_approval")
            resumed, ready = repository.decide_execution_approval(
                "user:local", execution["job_id"], "call-2", decision="reject"
            )
            checkpoint = repository.execution_checkpoint("user:local", execution["job_id"])

        self.assertTrue(ready)
        self.assertEqual(resumed["status"], "queued")
        self.assertEqual(
            [item["decision"] for item in resumed["approvals"]],
            ["approve", "reject"],
        )
        self.assertEqual(checkpoint["run_state"], "serialized-run-state")

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
            _partial_agent_result(
                {"tool_calls": [event.public() for event in outcome.tool_events]}
            )["primary_asset"],
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
        self.assertEqual(
            _agent_result(
                StudioAgentRun(
                    final=StudioAgentOutput(
                        title="Hero",
                        summary="Ready.",
                        markdown="# Hero",
                        filename="hero.md",
                    ),
                    tool_events=[event],
                )
            )["primary_asset"]["version_id"],
            "version-1",
        )

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
        self.assertEqual(
            normalize_markdown_filename("../Campaign Brief.md", "Ignored"), "Campaign-Brief.md"
        )
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
        outcome = SimpleNamespace(
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
            session_items=[
                {"role": "user", "content": "Make the result"},
                {"role": "assistant", "content": "# Customer result"},
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            test_repository = StudioRepository(
                Path(directory) / "studio.sqlite3",
                Path(directory) / "media",
            )
            test_repository.create_project("user:local", "local", "Untitled", project_id="untitled")
            with (
                patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}),
                patch("server.studio.repository", test_repository),
                patch("server.studio.run_studio_agent", new=AsyncMock(return_value=outcome)),
            ):
                queued = await studio_agent(AgentBody(prompt="Make the result"), None)
                await asyncio.sleep(0.05)
                payload = await studio_agent_job(queued["job_id"], None)
                saved_items = test_repository.get_conversation_items(
                    "user:local", queued["conversation_id"]
                )

        self.assertEqual(queued["status"], "queued")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["prompt"], "Make the result")
        self.assertEqual(payload["message"], "Completed Customer result.")
        self.assertEqual(payload["result"]["filename"], "customer-result.md")
        self.assertEqual(payload["result"]["tool_events"][0]["name"], "generate_image")
        self.assertEqual(payload["conversation_id"], queued["conversation_id"])
        self.assertEqual(saved_items[-1]["content"], "# Customer result")

    async def test_studio_endpoint_pauses_for_approval_then_resumes_the_same_job(self) -> None:
        approval = StudioApprovalRequest(
            call_id="call-approve",
            tool_name="Seedream___text_to_image",
            label="Generate image",
            provider="seedream",
            arguments={"prompt": "A quiet portrait"},
        )
        completed = SimpleNamespace(
            final=StudioAgentOutput(
                title="Approved result",
                summary="The approved image is ready.",
                markdown="# Approved result",
                filename="approved-result.md",
            ),
            tool_events=[],
            session_items=[{"role": "assistant", "content": "# Approved result"}],
            progress_events=[],
        )
        runner = AsyncMock(
            side_effect=[
                StudioAgentApprovalRequired(
                    "serialized-state",
                    [approval],
                    [{"role": "user", "content": "Make an image"}],
                ),
                completed,
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            test_repository = StudioRepository(
                Path(directory) / "studio.sqlite3",
                Path(directory) / "media",
            )
            test_repository.create_project("user:local", "local", "Untitled", project_id="untitled")
            with (
                patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}),
                patch("server.studio.repository", test_repository),
                patch("server.studio.run_studio_agent", new=runner),
            ):
                queued = await studio_agent(
                    AgentBody(prompt="Make an image", autonomous=False),
                    None,
                )
                await asyncio.sleep(0.05)
                paused = await studio_agent_job(queued["job_id"], None)
                await decide_studio_agent_tool(
                    queued["job_id"],
                    "call-approve",
                    AgentApprovalBody(decision="approve"),
                    None,
                )
                await asyncio.sleep(0.05)
                resumed = await studio_agent_job(queued["job_id"], None)

        self.assertEqual(paused["status"], "awaiting_approval")
        self.assertEqual(paused["approvals"][0]["arguments"]["prompt"], "A quiet portrait")
        self.assertEqual(resumed["job_id"], queued["job_id"])
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(runner.await_count, 2)
        self.assertEqual(runner.await_args_list[1].kwargs["resume_state"], "serialized-state")
        self.assertEqual(
            runner.await_args_list[1].kwargs["approval_decisions"][0].decision, "approve"
        )

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
            self.assertEqual(
                repository.version_path("user:one", first.version_id).read_bytes(), b"first image"
            )

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
