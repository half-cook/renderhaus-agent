from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from agent.deep_agent import routing
from agent.gateway_executor import tool_needs_approval
from providers.registry import dispatch
from providers.runway import api as runway
from providers.fal import api as fal
from server.billing_rates import cost_for


ACT = "Runway___act_two"
MOTION = "Fal___kling_motion_control"
ACT_ARGS = dict(character_uri="https://example.com/character.png",
                performance_uri="https://example.com/performance.mp4",
                performance_duration_seconds=5, subjects="Actor and character likeness owner",
                consent_confirmed=True)
MOTION_ARGS = dict(image_url="https://example.com/character.png",
                   video_url="https://example.com/performance.mp4",
                   performance_duration_seconds=5, subjects="Dancer and character likeness owner",
                   consent_confirmed=True)


class PerformanceContracts(unittest.TestCase):
    def test_invalid_inputs_never_reach_network(self):
        for provider, tool, args in [("runway", "act_two", ACT_ARGS),
                                     ("fal", "kling_motion_control", MOTION_ARGS)]:
            cases = [{"consent_confirmed": False}, {"subjects": " "},
                     {"performance_duration_seconds": 2.99}, {"performance_duration_seconds": 31},
                     {"performance_duration_seconds": True}, {"performance_duration_seconds": float("nan")},
                     {"consent_confirmed": "true"}, {"extra": "unsupported"}]
            cases += ([{"character_type": "audio"}, {"body_control": "false"},
                       {"expression_intensity": 6}, {"expression_intensity": True},
                       {"ratio": "16:9"}, {"character_uri": "/etc/passwd"}]
                      if provider == "runway" else
                      [{"character_orientation": "image", "performance_duration_seconds": 11},
                       {"image_url": "http://example.com/image.png"}, {"keep_original_sound": "true"}])
            with patch.dict(os.environ, {"RUNWAY_DRY_RUN": "false", "FAL_DRY_RUN": "false"}), patch.object(httpx, "Client") as client:
                for invalid in cases:
                    with self.subTest(provider=provider, invalid=invalid), self.assertRaises(ValueError):
                        dispatch(provider, tool, {**args, **invalid})
                    client.assert_not_called()

    def test_dry_run_is_offline_and_poll_stays_dry_after_flag_change(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
            {"RENDERHAUS_MEDIA_DIR": directory, "RUNWAY_DRY_RUN": "true", "FAL_DRY_RUN": "true"}), patch.object(httpx, "Client") as client:
            for provider, tool, args, poll in [("runway", "act_two", ACT_ARGS, "get_runway_task"),
                ("fal", "kling_motion_control", MOTION_ARGS, "get_video_task")]:
                result = dispatch(provider, tool, args)
                self.assertEqual(result["status"], "dry_run")
                self.assertFalse(result["training_eligible"])
                self.assertNotIn("output_path", result)
                with patch.dict(os.environ, {"RUNWAY_DRY_RUN": "false", "FAL_DRY_RUN": "false"}):
                    self.assertEqual(dispatch(provider, poll, {"job_id": result["job_id"]})["status"], "dry_run")
            client.assert_not_called()

    def test_act_two_posts_official_body_and_reuses_task_poll(self):
        job = "12345678-1234-4234-8234-123456789abc"
        calls = []
        def respond(request):
            calls.append(request)
            return httpx.Response(200, json={"id": job} if request.method == "POST" else
                {"id": job, "status": "SUCCEEDED", "output": ["https://example.com/result.mp4"]})
        client = httpx.Client(transport=httpx.MockTransport(respond))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
            {"RENDERHAUS_MEDIA_DIR": directory, "RUNWAY_DRY_RUN": "false", "RUNWAYML_API_SECRET": "fake"}), patch.object(runway.httpx, "Client", return_value=client):
            result = dispatch("runway", "act_two", {**ACT_ARGS, "character_type": "video", "body_control": False, "expression_intensity": 4, "seed": 42})
        body = json.loads(calls[0].content)
        self.assertEqual(calls[0].url.path, "/v1/character_performance")
        self.assertEqual(body, {"model": "act_two", "character": {"type": "video", "uri": ACT_ARGS["character_uri"]},
            "reference": {"type": "video", "uri": ACT_ARGS["performance_uri"]},
            "ratio": "1280:720", "bodyControl": False, "expressionIntensity": 4, "seed": 42})
        self.assertEqual(result["job_id"], job)
        self.assertNotIn("subjects", body)
        with patch.dict(os.environ, {"RUNWAY_DRY_RUN": "false"}), patch.object(runway, "_request", return_value=
            {"id": job, "status": "SUCCEEDED", "output": ["https://example.com/result.mp4"]}) as request:
            self.assertEqual(runway.get_runway_task(job)["status"], "succeeded")
            request.assert_called_once_with("GET", f"/tasks/{job}")

    def test_motion_control_body_and_fal_poll(self):
        endpoint = "fal-ai/kling-video/v3/pro/motion-control"
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
            {"RENDERHAUS_MEDIA_DIR": directory, "FAL_DRY_RUN": "false"}), patch.object(fal.queue, "submit", return_value={"request_id": "fake-motion-job"}) as submit:
            result = dispatch("fal", "kling_motion_control", MOTION_ARGS)
            submit.assert_called_once_with(endpoint, {"image_url": MOTION_ARGS["image_url"], "video_url": MOTION_ARGS["video_url"],
                "character_orientation": "video", "keep_original_sound": True, "prompt": ""})
            with patch.object(fal.queue, "status", return_value={"status": "COMPLETED"}), patch.object(fal.queue, "result", return_value={"video": {"url": "https://example.com/result.mp4"}}):
                polled = dispatch("fal", "get_video_task", {"job_id": result["job_id"]})
                self.assertEqual(polled["model"], endpoint)
                self.assertFalse(polled["training_eligible"])
                self.assertEqual(polled["status"], "succeeded")


class PerformanceRouting(unittest.TestCase):
    def test_default_exception_explicit_and_confidential_independence(self):
        for prompt, tool in [("transfer my facial acting onto this character", ACT),
                             ("copy my whole-body dance", MOTION),
                             ("use Runway for my whole-body dance", ACT),
                             ("use Kling to transfer my facial acting", MOTION)]:
            with self.subTest(prompt=prompt):
                route = routing.route_intent(prompt)
                self.assertEqual((route.status, route.tool), ("ready", tool))
                self.assertEqual(route.public(), routing.route_intent(prompt, confidential=True).public())

    def test_estimates_use_official_rates_even_during_dry_run(self):
        for name, provider, tool, args, cents in [(ACT, "runway", "act_two", ACT_ARGS, 25),
                                                (MOTION, "fal", "kling_motion_control", MOTION_ARGS, 84)]:
            with patch.dict(os.environ, {"RUNWAY_DRY_RUN": "true", "FAL_DRY_RUN": "true"}):
                self.assertEqual(cost_for(provider, tool, args).total_cents, 0)
                self.assertGreater(routing.estimate_cost(name, args).total_cents, cents)
            with patch.dict(os.environ, {"RUNWAY_DRY_RUN": "false", "FAL_DRY_RUN": "false"}):
                self.assertEqual(cost_for(provider, tool, args).provider_cents, cents)
            self.assertIsNone(routing.estimate_cost(name, {}).total_cents)

    def test_always_pauses_and_poll_remains_free(self):
        with patch.dict(os.environ, {"RENDERHAUS_PREMIUM_VIDEO_APPROVAL": "false"}):
            for name in (ACT, MOTION, "runway_act_two", "kling_motion_control"):
                for autonomous in (True, False):
                    self.assertTrue(tool_needs_approval(name, autonomous))
        self.assertFalse(tool_needs_approval("Runway___get_runway_task", True))
        self.assertFalse(tool_needs_approval("Fal___get_video_task", True))
