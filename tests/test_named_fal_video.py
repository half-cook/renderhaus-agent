"""Named fal video contracts, exercised offline with fake HTTP and scripted agents."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import httpx
import yaml
from mcp import Tool

from agent.codex_harness import ToolApprovalPending
from agent.deep_agent import routing
from agent.deep_agent.runner import SKILLS_ROOT, run_with_servers
from agent.gateway_executor import GatewayExecutor, tool_needs_approval
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, _context_from_request,
)
from providers.catalog import get_provider
from providers.fal import api, queue
from providers.registry import dispatch, generate_schemas
from server.billing_rates import cost_for
from test_deep_agent import Gateway, ScriptedModel, call, final


CASES = (
    ("pixelcut_looping_video", "pixelcut/looping-video", "use Pixelcut looping video for this product photo",
     {"image_url": "https://example.test/product.png"}),
    ("pixverse_vibemv", "pixverse/music-video/vibemv", "PixVerse VibeMV music video for this track",
     {"audio_url": "https://example.test/song.wav", "audio_duration_seconds": 10.1}),
)
HTTPX_CLIENT = httpx.Client


def gateway_tool(verb):
    schema = next(row for row in generate_schemas(get_provider("fal")) if row["name"] == verb)
    return Tool(name="Fal___" + verb, description=schema["description"], inputSchema=schema["inputSchema"])


class NamedFalProviderTests(unittest.TestCase):
    def test_default_dry_run_and_saved_handle_never_touch_http(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(httpx, "Client") as client:
            for verb, endpoint, _, args in CASES:
                result = dispatch("fal", verb, args)
                self.assertEqual((result["status"], result["model"]), ("dry_run", endpoint))
                self.assertEqual(result["endpoint_id"], endpoint)
                self.assertIn("request_preview", result)
                self.assertFalse(result["training_eligible"])
                self.assertEqual(result["weights_license"], "closed-weights")
                self.assertNotIn("output_path", result)
                with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}):
                    polled = dispatch("fal", "get_video_task", {"job_id": result["job_id"], "download": True})
                self.assertEqual(polled["status"], "dry_run")
            client.assert_not_called()

    def test_pixelcut_payload_and_defaults_over_mock_http(self):
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={"request_id": "fake-loop", "status": "IN_QUEUE"})
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
            {"FAL_DRY_RUN": "false", "FAL_KEY": "offline-fake", "RENDERHAUS_MEDIA_DIR": directory}), \
                patch.object(queue.httpx, "Client", side_effect=lambda **kw: HTTPX_CLIENT(transport=httpx.MockTransport(respond), **kw)):
            result = dispatch("fal", "pixelcut_looping_video", CASES[0][3])
        self.assertEqual(str(requests[0].url), "https://queue.fal.run/pixelcut/looping-video")
        self.assertEqual(json.loads(requests[0].content), {
            "image_url": CASES[0][3]["image_url"], "prompt": "", "duration": 5,
            "resolution": "1080p", "motion": "subtle", "include_audio": False,
        })
        self.assertEqual((result["status"], result["job_id"]), ("queued", "pixelcut/looping-video:fake-loop"))
        self.assertEqual(result["estimated_cost_usd"], 1.6)

    def test_vibemv_payload_strips_local_measurements_and_consent(self):
        requests = []
        def respond(request):
            requests.append(request)
            return httpx.Response(200, json={"request_id": "fake-mv", "status": "IN_QUEUE"})
        args = {**CASES[1][3], "style": "Custom", "style_image_url": "https://example.test/style.png",
                "image_url": "https://example.test/person.png", "music_style": "Rock", "lyrics": "Hello world",
                "lip_sync_switch": True, "real_face_refs": True, "real_voice_refs": True, "likeness_consent": True,
                "aspect_ratio": "9:16", "resolution": "1080p"}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
            {"FAL_DRY_RUN": "false", "FAL_KEY": "offline-fake", "RENDERHAUS_MEDIA_DIR": directory}), \
                patch.object(queue.httpx, "Client", side_effect=lambda **kw: HTTPX_CLIENT(transport=httpx.MockTransport(respond), **kw)):
            result = dispatch("fal", "pixverse_vibemv", args)
        self.assertEqual(str(requests[0].url), "https://queue.fal.run/pixverse/music-video/vibemv")
        self.assertEqual(json.loads(requests[0].content), {
            k: v for k, v in {**args, "enable_safety_checker": True}.items()
            if k not in {"audio_duration_seconds", "real_face_refs", "real_voice_refs", "likeness_consent"}
        })
        self.assertEqual(result["estimated_cost_usd"], 0.99)

    def test_invalid_arguments_block_before_any_http(self):
        invalid = [
            (0, {"duration": 4}), (0, {"duration": 16}), (0, {"duration": 5.5}), (0, {"duration": True}),
            (0, {"resolution": "720p"}), (0, {"motion": "orbit"}), (0, {"prompt": "x" * 4001}),
            (0, {"include_audio": "false"}), (0, {"image_url": "file:///tmp/image.png"}),
            (0, {"real_face_refs": True}), (0, {"model": "other"}),
            (1, {"audio_duration_seconds": 9.9}), (1, {"audio_duration_seconds": 360.1}),
            (1, {"audio_duration_seconds": float("nan")}), (1, {"audio_duration_seconds": True}),
            (1, {"audio_duration_seconds": None}), (1, {"style": "unknown"}), (1, {"resolution": "4K"}),
            (1, {"aspect_ratio": "21:9"}), (1, {"music_style": "rock"}), (1, {"lyrics": "x" * 5001}),
            (1, {"audio_url": ""}), (1, {"image_url": "javascript:alert(1)"}),
            (1, {"real_voice_refs": True}), (1, {"style": "Custom"}),
            (1, {"style_image_url": "https://example.test/style.png"}),
        ]
        with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}), patch.object(httpx, "Client") as client:
            for index, changes in invalid:
                verb, _, _, args = CASES[index]
                with self.subTest(verb=verb, changes=changes), self.assertRaises(ValueError):
                    dispatch("fal", verb, {**args, **changes})
            client.assert_not_called()

    def test_unresolved_asset_previews_and_live_block_before_http(self):
        for index, field in ((0, "image_url"), (1, "audio_url"), (1, "style_image_url")):
            verb, _, _, args = CASES[index]
            args = {**args, field: "renderhaus-asset://version_123"}
            if field == "style_image_url":
                args["style"] = "Custom"
            with patch.dict(os.environ, {"FAL_DRY_RUN": "true"}):
                self.assertEqual(dispatch("fal", verb, args)["status"], "dry_run")
            with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}), patch.object(httpx, "Client") as client:
                with self.assertRaisesRegex(ValueError, "resolve"):
                    dispatch("fal", verb, args)
                client.assert_not_called()

    def test_shared_poll_uses_app_root_and_persists_model_and_download(self):
        for verb, endpoint, _, args in CASES:
            requests = []
            def respond(request):
                requests.append(request)
                if request.method == "POST":
                    return httpx.Response(200, json={"request_id": "fake-job", "status": "IN_QUEUE"})
                if request.url.path.endswith("/status"):
                    return httpx.Response(200, json={"status": "COMPLETED"})
                return httpx.Response(200, json={"video": {"url": "https://example.test/result.mp4"}})
            def download(url, path):
                path.write_bytes(b"fake-offline-media")
            with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,
                {"FAL_DRY_RUN": "false", "FAL_KEY": "offline-fake", "RENDERHAUS_MEDIA_DIR": directory}), \
                    patch.object(queue.httpx, "Client", side_effect=lambda **kw: HTTPX_CLIENT(transport=httpx.MockTransport(respond), **kw)), \
                    patch.object(api, "_download", side_effect=download) as save:
                job = dispatch("fal", verb, args)
                result = dispatch("fal", "get_video_task", {"job_id": job["job_id"], "download": True})
                self.assertEqual(result["status"], "succeeded")
                self.assertEqual(result["model"], endpoint)
                self.assertFalse(result["training_eligible"])
                self.assertEqual(Path(result["output_path"]).read_bytes(), b"fake-offline-media")
                dispatch("fal", "get_video_task", {"job_id": job["job_id"], "download": True})
                self.assertEqual(save.call_count, 1)
                metadata = json.loads(api._paths(job["job_id"])[0].read_text())
                self.assertEqual(metadata["mode"], verb)
                self.assertFalse(metadata["training_eligible"])
            root = "/".join(endpoint.split("/")[:2])
            self.assertEqual(str(requests[1].url), f"https://queue.fal.run/{root}/requests/fake-job/status")

    def test_shared_poll_exposes_failures_and_rejects_missing_video(self):
        for _, endpoint, _, _ in CASES:
            args = {"job_id": endpoint + ":fake-job", "download": True}
            with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}), \
                    patch.object(queue, "status", return_value={"status": "IN_PROGRESS"}), patch.object(queue, "result") as fetch:
                self.assertEqual(dispatch("fal", "get_video_task", args)["status"], "running")
                fetch.assert_not_called()
            with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}), \
                    patch.object(queue, "status", return_value={"status": "COMPLETED", "error": "safety rejection"}):
                result = dispatch("fal", "get_video_task", args)
                self.assertEqual((result["status"], result["error"]), ("failed", "safety rejection"))
            with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}), \
                    patch.object(queue, "status", return_value={"status": "COMPLETED"}), \
                    patch.object(queue, "result", return_value={"video": {"url": "file:///tmp/result.mp4"}}), \
                    patch.object(api, "_download") as save:
                with self.assertRaises(RuntimeError):
                    dispatch("fal", "get_video_task", args)
                save.assert_not_called()


class NamedFalRoutingTests(unittest.TestCase):
    def test_named_requests_select_only_named_skill_and_disclose_cost(self):
        for verb, endpoint, prompt, args in CASES:
            route = routing.route_intent(prompt, arguments=args)
            self.assertEqual((route.skill, route.tool, route.status), ("named-provider", "Fal___" + verb, "ready"))
            self.assertEqual((route.alias, route.provider, route.model), (verb, "fal", endpoint))
            self.assertEqual(route.dispatch_tool, "call_media_tool")
            self.assertIn("explicit request", route.disclosure)
            self.assertIn("Estimated cost $", route.disclosure)
            self.assertEqual(route.public(), routing.route_intent(prompt, arguments=args, confidential=True).public())
        self.assertEqual(routing.route_intent("VibeMV for this song").alias, "pixverse_vibemv")
        self.assertEqual(routing.route_intent("PixVerse VibeMV karaoke lyrics video for my track").skill, "named-provider")

    def test_unnamed_negated_and_quoted_requests_never_select_named_tools(self):
        names = {"Fal___" + case[0] for case in CASES}
        for prompt in ("animate this product photo into a seamless loop", "make a 360 spin video of this product",
                       "make a karaoke lyrics video for my track", "music video for this audio",
                       "no Pixelcut, animate this product photo", "do not use PixVerse VibeMV for this lyrics video",
                       'generate a video with the title "Pixelcut looping video"',
                       'make a karaoke lyrics video with subtitle "PixVerse VibeMV"'):
            route = routing.route_intent(prompt)
            self.assertNotIn(route.tool, names, prompt)
            self.assertTrue(all(step.tool not in names for step in route.steps), prompt)
            for name in names:
                self.assertIsNotNone(routing.request_tool_blocker(prompt, name), prompt)
        self.assertEqual(routing.route_intent("animate this product photo").alias, "wan3_i2v")
        self.assertEqual(routing.route_intent("make a karaoke lyrics video from this song").alias, "mureka_lyrics_video")

    def test_explicit_unavailable_or_unsupported_control_has_no_fallback(self):
        for _, _, prompt, args in CASES:
            route = routing.route_intent(prompt, arguments=args, available_tools=set())
            self.assertEqual(route.status, "blocked")
            self.assertIsNone(route.tool)
        route = routing.route_intent(CASES[0][2], arguments={**CASES[0][3], "duration": 20})
        self.assertEqual(route.status, "blocked")
        self.assertIsNone(route.tool)

    def test_policy_inventory_has_no_default_exception_or_training_grant(self):
        front = yaml.safe_load((SKILLS_ROOT / "named-provider/SKILL.md").read_text().split("---", 2)[1])
        for verb, endpoint, _, _ in CASES:
            self.assertTrue(routing.TOOL_MAP[verb]["explicit_only"])
            self.assertEqual(routing.resolve_alias(verb), "Fal___" + verb)
            self.assertIn(verb, front["metadata"]["routing_tools"].split())
            self.assertIn("Fal___" + verb, front["metadata"]["gateway_tools"].split())
            for choice in routing.POLICY["capability_map"].values():
                self.assertNotEqual(choice["default"], verb)
                self.assertFalse(any(row["tool"] == verb for row in choice["exceptions"]))
            policy = routing.POLICY["providers"]["fal"]["model_policies"][endpoint]
            self.assertEqual(policy["license"], "service-terms")
            self.assertFalse(policy["training_eligible"])
            self.assertTrue(policy["explicit_only"])
            self.assertFalse(routing.training_eligible({"provider": "fal", "model": endpoint,
                "status": "succeeded", "training_eligible": True, "weights_license": "Apache-2.0"}))

    def test_verified_pricing_and_rounding_dry_run_billing_and_unknown_measurement(self):
        from server.billing_rates import named_fal_video_price_cents

        for resolution, cents in (("480p", 40), ("768p", 80), ("1080p", 160)):
            self.assertEqual(named_fal_video_price_cents("pixelcut_looping_video", {"resolution": resolution}), Decimal(cents))
        for resolution, cents in (("720p", 66), ("1080p", 99)):
            args = {**CASES[1][3], "resolution": resolution}
            self.assertEqual(named_fal_video_price_cents("pixverse_vibemv", args), Decimal(cents))
            self.assertEqual(routing.estimate_cost("Fal___pixverse_vibemv", args, list_price=True).total_cents,
                             int(Decimal(cents) * Decimal("1.3") + Decimal("0.5")))
            with patch.dict(os.environ, {"FAL_DRY_RUN": "true"}):
                self.assertEqual(cost_for("fal", "pixverse_vibemv", args).total_cents, 0)
            with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}):
                self.assertGreater(cost_for("fal", "pixverse_vibemv", args).total_cents, 0)
        quote = routing.estimate_cost("Fal___pixverse_vibemv", {})
        self.assertIsNone(quote.total_cents)
        self.assertIn("unknown", quote.description)

    def test_both_paid_video_tools_always_require_approval(self):
        for verb, _, _, _ in CASES:
            for name in (verb, "Fal___" + verb):
                for autonomous in (False, True):
                    with patch.dict(os.environ, {"RENDERHAUS_PREMIUM_VIDEO_APPROVAL": "false"}):
                        self.assertTrue(tool_needs_approval(name, autonomous))


class NamedFalApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_executor_cannot_dispatch_unnamed_or_invalid_requests(self):
        for verb, _, prompt, args in CASES:
            gateway = Gateway([gateway_tool(verb)])
            context = _context_from_request(StudioAgentRequest(prompt="animate this photo", autonomous=True, job_id="named"))
            executor = GatewayExecutor(context, [gateway])
            result = await executor.execute({"tool_name": "Fal___" + verb, "arguments": args, "call_id": "unnamed"}, approved=True)
            self.assertEqual(result["status"], "not_run")
            gateway.call_tool.assert_not_awaited()
            context.prompt = prompt
            invalid = {**args, "duration": 100} if verb == "pixelcut_looping_video" else {**args, "audio_duration_seconds": 2}
            result = await executor.execute({"tool_name": "Fal___" + verb, "arguments": invalid, "call_id": "invalid"})
            self.assertEqual(result["status"], "not_run")
            gateway.call_tool.assert_not_awaited()

    async def test_executor_discloses_cost_then_rejection_never_calls_gateway(self):
        for verb, endpoint, prompt, args in CASES:
            gateway = Gateway([gateway_tool(verb)])
            context = _context_from_request(StudioAgentRequest(prompt=prompt, autonomous=True, job_id="named"))
            executor = GatewayExecutor(context, [gateway])
            request = {"tool_name": "Fal___" + verb, "arguments": args, "call_id": verb}
            with self.assertRaises(ToolApprovalPending):
                await executor.execute(request)
            message = context.progress_events[-1].message
            self.assertIn(endpoint, message)
            self.assertIn("explicit request", message)
            self.assertIn("including platform fee", message)
            with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"RENDERHAUS_OUTCOME_DIR": directory}):
                result = await executor.execute(request, rejection="Skip this")
            self.assertEqual(result["status"], "rejected")
            gateway.call_tool.assert_not_awaited()

    async def test_native_deepagents_cost_interrupt_resume_approve_and_reject(self):
        for verb, endpoint, prompt, args in CASES:
            for decision in ("approve", "reject"):
                with self.subTest(verb=verb, decision=decision):
                    gateway = Gateway([gateway_tool(verb)])
                    request = StudioAgentRequest(prompt=prompt, autonomous=True, job_id="native-named", conversation_id=verb + decision)
                    studio = _context_from_request(request)
                    model = ScriptedModel([call("call_media_tool", {"tool_name": "Fal___" + verb, "arguments": args}, "named-submit")])
                    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"RENDERHAUS_OUTCOME_DIR": directory}):
                        with self.assertRaises(StudioAgentApprovalRequired) as paused:
                            await run_with_servers(request, studio, [gateway], model=model)
                        gateway.call_tool.assert_not_awaited()
                        approval = paused.exception.approvals[0]
                        self.assertEqual(approval.tool_name, "Fal___" + verb)
                        self.assertIn(endpoint, approval.description)
                        self.assertIn("Estimated cost $", approval.description)
                        resumed = request.model_copy(update={"session_items": json.loads(json.dumps(paused.exception.session_items)),
                            "resume_state": paused.exception.state,
                            "approval_decisions": [StudioApprovalDecision(call_id=approval.call_id, decision=decision, message="Skip this")]})
                        await run_with_servers(resumed, _context_from_request(resumed), [gateway], model=ScriptedModel([final()]))
                    self.assertEqual(gateway.call_tool.await_count, int(decision == "approve"))
                    if decision == "approve":
                        self.assertEqual(gateway.call_tool.await_args.args, ("Fal___" + verb, args))
