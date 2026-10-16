from __future__ import annotations

import json
import os
from pathlib import Path
from contextlib import asynccontextmanager
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from agent.deep_agent.routing import media_production_text, route_intent
from agent.studio_agent_next import StudioAgentContext, StudioAgentRequest, _requests_video_deliverable, _validate_video_delivery
from server import studio
from server.studio_state import StudioRepository


AUDIO_PROMPT = (
    "Generate one short English voiceover saying 'Welcome to Renderhaus.' Choose a clear natural library voice yourself. "
    "This is audio only: do not generate video or images. Complete the workflow by inspecting the saved audio and returning "
    "the playable asset. Budget US$2 total. Ask for the paid generation approval once; do not ask me routine production questions."
)


class ProductionIntentTests(unittest.TestCase):
    def test_outer_host_accepts_audio_only_original_and_resume_but_requires_real_video(self):
        audio = {"title": "Welcome voiceover", "summary": "The inspected audio is saved.",
                 "assets": [{"kind": "audio"}]}
        resumed = ("Resume the unfinished request in this conversation from its saved progress.\n"
                   "Original requests (reference data):\n" + json.dumps([AUDIO_PROMPT]))
        for prompt in (AUDIO_PROMPT, resumed):
            with self.subTest(prompt=prompt):
                self.assertFalse(studio._deliverable_missing(prompt, audio))
        for prompt in ("Make a 10-second product film with voiceover.",
                       "Finish the requested video export. " + resumed):
            with self.subTest(prompt=prompt):
                self.assertTrue(studio._deliverable_missing(prompt, audio))
                self.assertFalse(_validate_video_delivery(StudioAgentRequest(prompt=prompt), StudioAgentContext()))
        self.assertTrue(studio._deliverable_missing(AUDIO_PROMPT,
                        {"title": "Incomplete", "summary": "Could not inspect the audio.", "assets": []}))

    def test_audio_only_original_routes_speech_and_does_not_require_mp4(self):
        route = route_intent(AUDIO_PROMPT)
        self.assertEqual(route.job_type, "tts")
        self.assertEqual(route.steps, ())
        self.assertFalse(_requests_video_deliverable(AUDIO_PROMPT))
        self.assertTrue(_validate_video_delivery(StudioAgentRequest(prompt=AUDIO_PROMPT), StudioAgentContext()))

    def test_negated_video_does_not_hide_following_positive_action(self):
        for prompt in ("Do not generate video, but create an audio voiceover.",
                       "Create a narration, no video.", "Never render a video. Make an English voiceover."):
            with self.subTest(prompt=prompt):
                self.assertFalse(_requests_video_deliverable(prompt))
                self.assertEqual(route_intent(prompt).job_type, "tts")
        for prompt in ("Do not generate images, create a video with voiceover.",
                       "Do not create a still, but make a video with voiceover.",
                       "Make a video without narration.", "Make a video. Do not add narration.",
                       "Add voiceover to the existing video."):
            with self.subTest(prompt=prompt):
                self.assertTrue(_requests_video_deliverable(prompt))
                self.assertFalse(_validate_video_delivery(StudioAgentRequest(prompt=prompt), StudioAgentContext()))

    def test_mixed_video_voiceover_keeps_assembly_and_negated_narration_does_not_add_speech(self):
        for prompt in ("Make a video with voiceover.", "Add voiceover to the existing video."):
            route = route_intent(prompt)
            self.assertEqual(route.steps[-1].skill, "final-assembly")
            self.assertIn("audio-bed", [step.skill for step in route.steps])
        for prompt in ("Make a video without narration.", "Make a video. Do not add voiceover."):
            route = route_intent(prompt)
            self.assertEqual(route.job_type, "t2v")
            self.assertEqual(route.steps, ())

    def test_quoted_script_is_reference_data(self):
        prompt = 'Create narration saying "generate a video with voiceover". Do not generate video.'
        self.assertFalse(_requests_video_deliverable(prompt))
        self.assertNotIn("video", media_production_text(prompt).lower())


class ResumeOriginalIntentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.repo = StudioRepository(root / "studio.sqlite3", root / "media")
        self.repo.create_project("user:local", "local", "Voiceover", project_id="untitled")
        self.conversation = self.repo.create_conversation("user:local", "untitled", "local")["id"]
        self.enterContext(patch.object(studio, "repository", self.repo))

    def save_stopped(self, prompt, error_type="VideoExportIncomplete", *, delivery_continuation=False):
        execution = self.repo.create_execution(workspace_id="user:local", project_id="untitled", user_id="local",
                                                prompt=prompt, conversation_id=self.conversation,
                                                request={"prompt": prompt, "delivery_continuation": delivery_continuation})
        job = execution["job_id"]
        self.repo.save_agent_checkpoint("user:local", self.conversation, job, [{"role": "user", "content": prompt}])
        self.repo.update_execution("user:local", job, status="error", message="Stopped", error_type=error_type)
        return job

    async def test_repeated_resume_uses_immutable_audio_request_despite_old_video_error(self):
        job = self.save_stopped(AUDIO_PROMPT)
        # Reproduce an existing continuation created by the buggy video detector.
        job = self.save_stopped("Finish the requested video export. Resume the unfinished request in this conversation from its saved progress.\n"
                               "Original requests (reference data):\n" + json.dumps([AUDIO_PROMPT]), delivery_continuation=True)
        self.repo.set_execution_display_prompt("user:local", job, "Resume saved progress")

        async def submit(body, auth):
            return {"job_id": self.save_stopped(body.prompt, delivery_continuation=body._delivery_continuation)}

        for _ in range(3):
            with patch.object(studio, "studio_agent", new_callable=AsyncMock, side_effect=submit) as send:
                result = await studio.resume_studio_agent_job(job, None)
            body = send.call_args.args[0]
            self.assertFalse(body.prompt.startswith("Finish the requested video export."))
            self.assertIn(json.dumps([AUDIO_PROMPT]), body.prompt)
            self.assertNotIn("Original requests (reference data):\\n", body.prompt)
            job = result["job_id"]
            self.assertEqual(self.repo.execution_checkpoint("user:local", job)["request"]["prompt"], body.prompt)
            self.assertIs(self.repo.execution_checkpoint("user:local", job)["request"]["delivery_continuation"], True)

    async def test_immutable_positive_video_request_still_requires_export_after_display_change(self):
        job = self.save_stopped("Make an MP4 video with voiceover")
        self.repo.set_execution_display_prompt("user:local", job, "Resume saved progress")
        with patch.object(studio, "studio_agent", new_callable=AsyncMock, return_value={"job_id": job}) as send:
            await studio.resume_studio_agent_job(job, None)
        self.assertTrue(send.call_args.args[0].prompt.startswith("Finish the requested video export."))

    async def test_host_completes_audio_only_after_real_file_inspection_without_paid_call(self):
        from agent import studio_agent_next
        from server import studio_state
        from test_deep_agent import Gateway, ScriptedModel, call

        job = self.repo.create_execution(workspace_id="user:local", project_id="untitled", user_id="local",
                                         prompt=AUDIO_PROMPT, conversation_id=self.conversation,
                                         request={"prompt": AUDIO_PROMPT})["job_id"]
        directory = self.repo.media_root / job
        directory.mkdir()
        source = directory / "welcome.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1.76",
                        str(source)], check=True)
        payload = {"title": "Welcome voiceover", "summary": "The inspected audio is saved.",
                   "markdown": "# Voiceover", "filename": "voiceover.md", "media_paths": ["/work/welcome.wav"]}
        model = ScriptedModel([
            call("inspect_media", {"path": "/work/welcome.wav"}, "inspect"),
            call("StudioAgentOutput", payload, "finish"),
            call("GraderResponse", {"result": "satisfied", "explanation": "Current audio measured.",
                 "criteria": [{"name": "Current audio inspection", "passed": True}]}, "grade"),
        ])
        transport = Gateway()

        @asynccontextmanager
        async def gateway(**kwargs):
            yield transport

        with patch.dict(os.environ, {"RENDERHAUS_AGENT_BACKEND": "deepagents", "AGENTCORE_DEV_URL": "",
                                    "RENDERHAUS_MEDIA_DIR": str(self.repo.media_root)}), \
                patch.object(studio_state, "repository", self.repo), \
                patch.object(studio_agent_next, "gateway_mcp_server", gateway), \
                patch("agent.deep_agent.runner.configured_deep_agent_model", return_value=model):
            await studio._run_studio_agent_job(job, AUDIO_PROMPT, [], self.conversation,
                                             workspace_id="user:local", project_id="untitled", user_id="local")
        execution = self.repo.get_execution("user:local", job)
        self.assertEqual(execution["status"], "completed", execution.get("message"))
        self.assertEqual([asset["kind"] for asset in execution["result"]["assets"]], ["audio"])
        saved = self.repo.version_path("user:local", execution["result"]["assets"][0]["version_id"])
        self.assertEqual(saved.read_bytes(), source.read_bytes())
        transport.call_tool.assert_not_awaited()
        self.assertFalse(model._steps)
