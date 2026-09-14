import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

import server.studio as studio
from agent.codex_harness import CodexRunLimitExceeded
from server.studio_state import StudioRepository


class StudioRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = StudioRepository(Path(directory.name) / "studio.sqlite3", Path(directory.name) / "media")
        self.repo.create_project("user:local", "local", "Recovery", project_id="untitled")
        self.conversation = self.repo.create_conversation("user:local", "untitled", "local")["id"]
        self.job = self.create_job()
        self.patch = patch.object(studio, "repository", self.repo)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def create_job(self):
        return self.repo.create_execution(workspace_id="user:local", project_id="untitled", user_id="local",
                                          prompt="Finish my video", conversation_id=self.conversation)["job_id"]

    def update(self, status, **kwargs):
        return self.repo.update_execution("user:local", self.job, status=status, message=status, **kwargs)

    def execution(self):
        return self.repo.get_execution("user:local", self.job)

    def save_items(self):
        items = [{"role": "user", "content": "Finish my video"}]
        self.repo.save_agent_checkpoint("user:local", self.conversation, self.job, items)
        return items

    def save_tool(self, **changes):
        self.repo.append_tool_call(workspace_id="user:local", execution_id=self.job, event={
            "id": "render", "name": "Remotion___render_timeline", "status": "running",
            "result": {"render_id": "render-1", "bucket_name": "bucket-1"}, **changes,
        })

    async def run_job(self):
        await studio._run_studio_agent_job(self.job, "Finish my video", [], self.conversation,
                                          workspace_id="user:local", project_id="untitled", user_id="local")

    async def test_empty_or_failed_checkpoint_does_not_offer_resume(self):
        self.repo.save_agent_checkpoint("user:local", self.conversation, self.job, [])
        self.save_tool(status="failed", result={"error": "Connection failed"})
        self.update("error")
        self.assertFalse(self.execution()["recovery_available"])
        with patch.object(studio, "studio_agent", new_callable=AsyncMock) as submit:
            with self.assertRaises(HTTPException) as error:
                await studio.resume_studio_agent_job(self.job, None)
            self.assertEqual(error.exception.status_code, 409)
            submit.assert_not_called()

    def test_checkpoint_and_conversation_items_are_independent_recovery_sources(self):
        items = self.save_items()
        self.update("error")
        self.repo.replace_conversation_items("user:local", self.conversation, [])
        self.assertTrue(self.execution()["can_resume"])
        self.assertEqual(self.repo.get_conversation_recovery_items("user:local", self.conversation), items)
        with self.repo._connect() as connection:
            connection.execute("DELETE FROM agent_checkpoints")
        self.repo.replace_conversation_items("user:local", self.conversation, items)
        self.assertIsNone(self.execution()["checkpoint_at"])
        self.assertTrue(self.execution()["can_resume"])
        self.assertNotIn("Finish my video", json.dumps({k: v for k, v in self.execution().items() if k != "prompt"}))
        with self.assertRaises(KeyError):
            self.repo.get_conversation_recovery_items("user:other", self.conversation)

    async def test_resume_rejects_completed_and_unknown_status_even_with_saved_progress(self):
        self.save_items()
        for status in ("completed", "unknown", "archived", "queued", "running", "awaiting_approval"):
            with self.subTest(status=status), patch.object(studio, "studio_agent", new_callable=AsyncMock) as submit:
                self.update(status, result={"partial": True})
                self.assertFalse(self.execution()["can_resume"])
                with self.assertRaises(HTTPException) as error:
                    await studio.resume_studio_agent_job(self.job, None)
                self.assertEqual(error.exception.status_code, 409)
                submit.assert_not_called()

    async def test_ledger_only_resume_carries_original_request_and_saved_jobs(self):
        self.save_tool()
        self.update("error")
        self.assertTrue(self.execution()["can_resume"])
        with patch.object(studio, "studio_agent", new_callable=AsyncMock, return_value={"job_id": self.job}) as submit:
            await studio.resume_studio_agent_job(self.job, None)
        prompt = submit.call_args.args[0].prompt
        self.assertIn("Finish my video", prompt)
        self.assertIn("render-1", prompt)
        with patch.object(studio, "run_studio_agent", side_effect=CodexRunLimitExceeded()) as runner:
            with self.assertLogs(studio.logger, level="ERROR"):
                await self.run_job()
        # A new continuation restores the preceding run's ledger, even without native history.
        self.update("error")
        self.job = self.create_job()
        with patch.object(studio, "run_studio_agent", side_effect=CodexRunLimitExceeded()) as runner:
            with self.assertLogs(studio.logger, level="ERROR"):
                await self.run_job()
        self.assertEqual(runner.call_args.kwargs["prior_tool_events"][0].result["render_id"], "render-1")

    def test_only_latest_run_can_resume_and_history_can_supply_recovery(self):
        self.save_tool()
        self.update("error")
        old = self.job
        self.job = self.create_job()
        self.update("error")
        self.assertTrue(self.execution()["can_resume"])
        self.assertFalse(self.repo.get_execution("user:local", old)["can_resume"])

    async def test_run_limit_recovers_only_successful_remotion_video(self):
        for name, status, kind, expected in (
            ("Remotion___get_render_progress", "succeeded", "video", "completed"),
            ("render_remotion_video", "completed", "video", "completed"),
            ("Remotion___get_render_progress", "running", "video", "error"),
            ("Remotion___get_render_progress", "succeeded", "image", "error"),
            ("Seedance___get_video_task", "succeeded", "video", "error"),
        ):
            with self.subTest(name=name, status=status, kind=kind):
                self.save_tool(name=name, status=status, assets=[{"kind": kind, "version_id": "v1", "filename": "out.mp4"}])
                with patch.object(studio, "run_studio_agent", side_effect=CodexRunLimitExceeded()), self.assertLogs(studio.logger, level="ERROR"):
                    await self.run_job()
                execution = self.execution()
                self.assertEqual(execution["status"], expected)
                self.assertEqual(execution["result"]["primary_asset"]["version_id"], "v1")

    async def test_stop_preserves_completion_during_cancellation(self):
        started = asyncio.Event()
        async def finish_on_cancel():
            started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                self.update("completed", result={"title": "Complete MP4"})
        task = asyncio.create_task(finish_on_cancel(), name=f"studio-agent-{self.job}")
        await started.wait()
        with patch.object(studio, "_AGENT_TASKS", {task}):
            result = await studio.stop_studio_agent_job(self.job, None)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"], {"title": "Complete MP4"})
        self.assertIsNone(result["error_type"])

    async def test_stop_update_is_conditional_even_after_latest_read(self):
        original = self.repo.update_execution
        def complete_before_update(*args, **kwargs):
            original("user:local", self.job, status="completed", message="Done", result={"title": "MP4"})
            return original(*args, **kwargs)
        with patch.object(self.repo, "update_execution", side_effect=complete_before_update):
            result = await studio.stop_studio_agent_job(self.job, None)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"], {"title": "MP4"})
        self.assertIsNone(result["error_type"])

    async def test_stop_running_worker_records_user_stop_and_keeps_recovery(self):
        self.save_items()
        started = asyncio.Event()
        async def work(*args, **kwargs):
            started.set()
            await asyncio.Future()
        with patch.object(studio, "run_studio_agent", side_effect=work):
            task = asyncio.create_task(self.run_job(), name=f"studio-agent-{self.job}")
            await started.wait()
            with patch.object(studio, "_AGENT_TASKS", {task}):
                result = await studio.stop_studio_agent_job(self.job, None)
        self.assertEqual(result["error_type"], "UserStopped")
        self.assertTrue(result["can_resume"])


if __name__ == "__main__":
    unittest.main()
