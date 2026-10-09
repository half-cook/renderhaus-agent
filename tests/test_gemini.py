from __future__ import annotations

import base64
import io
import json
import os
import unittest
from unittest.mock import patch

import httpx
from PIL import Image
from pydantic import ValidationError

from providers.gemini import api, contracts, tools

REAL_HTTPX_CLIENT = httpx.Client


def image_b64() -> str:
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def envelope(status="completed", judgement=None):
    return {
        "id": "interaction_123",
        "model": contracts.VERIFIED_MODEL,
        "status": status,
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            judgement
                            if judgement is not None
                            else {"same_shot_continuity": True, "confidence": 0.9, "issues": []}
                        ),
                    }
                ],
            }
        ],
        "usage": {"total_input_tokens": 100, "total_output_tokens": 30, "total_thought_tokens": 10},
    }


class GeminiTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "GEMINI_DRY_RUN": "false",
                "GEMINI_API_KEY": "test-secret",
                "GEMINI_VLM_MODEL": contracts.VERIFIED_MODEL,
                "GEMINI_VLM_TIMEOUT_SECONDS": "30",
                "GEMINI_VLM_MAX_RETRIES": "2",
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.frame = image_b64()

    def transport(self, handler):
        patcher = patch(
            "providers.gemini.api.httpx.Client",
            side_effect=lambda **kwargs: REAL_HTTPX_CLIENT(
                transport=httpx.MockTransport(handler), **kwargs
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_judgement_is_strict_and_frozen(self):
        result = contracts.GeminiJudgement(same_shot_continuity=True, confidence=1, issues=[])
        self.assertEqual(result.confidence, 1)
        with self.assertRaises(ValidationError):
            result.confidence = 0.2
        invalid = [
            dict(same_shot_continuity="yes", confidence=0.9, issues=[]),
            dict(same_shot_continuity=True, confidence=True, issues=[]),
            dict(same_shot_continuity=True, confidence=float("nan"), issues=[]),
            dict(same_shot_continuity=True, confidence=1.1, issues=[]),
            dict(same_shot_continuity=True, confidence=0.9, issues=[1]),
            dict(same_shot_continuity=True, confidence=0.9, issues=[], extra="bad"),
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                contracts.GeminiJudgement.model_validate(value)

    def test_fixed_rubric_has_hash(self):
        import hashlib

        self.assertEqual(
            contracts.RUBRIC_HASH, hashlib.sha256(contracts.RUBRIC.encode()).hexdigest()
        )
        for word in ["identity", "wardrobe", "props", "lighting", "location"]:
            self.assertIn(word, contracts.RUBRIC.lower())

    def test_dry_run_never_networks_even_with_key(self):
        with (
            patch.dict(os.environ, {"GEMINI_DRY_RUN": "true"}),
            patch("providers.gemini.api.httpx.Client") as client,
        ):
            result = tools.judge_continuity(self.frame, self.frame)
            self.assertEqual(result["status"], "skipped")
            self.assertTrue(result["dry_run"])
            self.assertNotIn("same_shot_continuity", result)
            polled = tools.get_task(result["job_id"])
            self.assertEqual(polled["status"], "skipped")
            client.assert_not_called()

    def test_default_is_dry_run(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("providers.gemini.api.httpx.Client") as client,
        ):
            self.assertTrue(contracts.GeminiSettings.from_env().dry_run)
            with self.assertRaisesRegex(api.GeminiError, "dry-run"):
                api.judge_pair(Image.new("RGB", (8, 8)), Image.new("RGB", (8, 8)))
            client.assert_not_called()

    def test_dry_run_job_cannot_become_live(self):
        with patch("providers.gemini.api.httpx.Client") as client:
            self.assertEqual(tools.get_task("gemini_dry_123")["status"], "skipped")
            client.assert_not_called()

    def test_submit_official_request_shape(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=envelope("in_progress"))

        self.transport(handler)
        result = tools.judge_continuity(self.frame, self.frame)
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["job_id"], "interaction_123")
        request = requests[0]
        self.assertEqual(str(request.url), api.INTERACTIONS_URL)
        self.assertEqual(request.headers["x-goog-api-key"], "test-secret")
        body = json.loads(request.content)
        self.assertEqual(
            set(body),
            {
                "model",
                "input",
                "background",
                "store",
                "service_tier",
                "response_format",
                "generation_config",
            },
        )
        self.assertEqual(body["input"][0], {"type": "text", "text": contracts.RUBRIC})
        self.assertEqual(
            body["input"][1], {"type": "image", "mime_type": "image/png", "data": self.frame}
        )
        self.assertEqual(
            body["generation_config"], {"max_output_tokens": 512, "thinking_level": "minimal"}
        )
        self.assertTrue(body["background"])
        self.assertTrue(body["store"])
        self.assertEqual(body["service_tier"], "standard")
        self.assertEqual(body["response_format"]["mime_type"], "application/json")

    def test_poll_valid_judgement_and_usage(self):
        self.transport(lambda request: httpx.Response(200, json=envelope()))
        result = tools.get_task("interaction_123")
        self.assertEqual(result["status"], "succeeded")
        self.assertTrue(result["same_shot_continuity"])
        self.assertEqual(result["usage"]["total_input_tokens"], 100)
        self.assertFalse(result["training_eligible"])

    def test_pending_poll_has_no_judgement(self):
        self.transport(lambda request: httpx.Response(200, json=envelope("in_progress")))
        result = tools.get_task("interaction_123")
        self.assertEqual(result["status"], "running")
        self.assertNotIn("same_shot_continuity", result)

    def test_client_encodes_frames_and_polls(self):
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(
                200, json=envelope("in_progress" if request.method == "POST" else "completed")
            )

        self.transport(handler)
        result = api.GeminiClient(contracts.GeminiSettings.from_env()).judge(
            Image.new("RGB", (8, 8)), Image.new("RGB", (8, 8))
        )
        self.assertTrue(result.same_shot_continuity)
        self.assertEqual([r.method for r in requests], ["POST", "GET"])

    def test_invalid_images_stop_before_network(self):
        for value in ["https://example.test/frame.png", "/tmp/frame.png", "abcd", "", "%%%"]:
            with self.subTest(value=value), patch("providers.gemini.api.httpx.Client") as client:
                with self.assertRaises(ValueError):
                    tools.judge_continuity(value, self.frame)
                client.assert_not_called()

    def test_non_png_jpeg_is_rejected(self):
        output = io.BytesIO()
        Image.new("RGB", (8, 8)).save(output, format="GIF")
        with self.assertRaises(ValueError):
            tools.judge_continuity(base64.b64encode(output.getvalue()).decode(), self.frame)

    def test_oversize_image_is_rejected(self):
        with (
            patch.object(contracts, "MAX_IMAGE_BYTES", 8),
            patch("providers.gemini.api.httpx.Client") as client,
        ):
            with self.assertRaises(ValueError):
                tools.judge_continuity(self.frame, self.frame)
            client.assert_not_called()

    def test_bad_job_ids_stop_before_network(self):
        for job in ["../oops", "foo/bar", "é", "", "foo?key=secret"]:
            with self.subTest(job=job), patch("providers.gemini.api.httpx.Client") as client:
                with self.assertRaises(ValueError):
                    tools.get_task(job)
                client.assert_not_called()

    def test_unverified_model_is_dry_run_only(self):
        with patch("providers.gemini.api.httpx.Client") as client:
            blocked = tools.judge_continuity(self.frame, self.frame, "unknown-model")
            self.assertEqual(blocked["status"], "skipped")
            self.assertIn("UNVERIFIED", blocked["reason"])
            client.assert_not_called()
        with patch.dict(os.environ, {"GEMINI_DRY_RUN": "true"}):
            preview = tools.judge_continuity(self.frame, self.frame, "unknown-model")
            self.assertEqual(preview["verification"], "UNVERIFIED")

    def test_bad_structured_response_fails_soft(self):
        for judgement in [
            {"same_shot_continuity": "yes", "confidence": 0.9, "issues": []},
            {"same_shot_continuity": True, "confidence": 0.9, "issues": [], "unexpected": 1},
        ]:
            self.transport(lambda request: httpx.Response(200, json=envelope(judgement=judgement)))
            result = tools.get_task("interaction_123")
            self.assertEqual(result["status"], "skipped")
            self.assertNotIn("same_shot_continuity", result)

    def test_http_failure_redacts_provider_payload(self):
        self.transport(
            lambda request: httpx.Response(
                401, json={"error": "test-secret signed-url https://secret"}
            )
        )
        result = tools.get_task("interaction_123")
        self.assertEqual(result["status"], "skipped")
        self.assertNotIn("test-secret", json.dumps(result))
        self.assertNotIn("https://secret", json.dumps(result))

    def test_get_retries_transient_failure(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(503 if len(calls) == 1 else 200, json=envelope())

        self.transport(handler)
        with patch("providers.gemini.api.time.sleep"):
            self.assertEqual(tools.get_task("interaction_123")["status"], "succeeded")
        self.assertEqual(len(calls), 2)

    def test_post_429_retries_but_500_does_not(self):
        for status, expected in [(429, 2), (500, 1)]:
            calls = []

            def handler(request):
                calls.append(request)
                return httpx.Response(
                    status if len(calls) == 1 else 200, json=envelope("in_progress")
                )

            self.transport(handler)
            with patch("providers.gemini.api.time.sleep"):
                result = tools.judge_continuity(self.frame, self.frame)
            self.assertEqual(len(calls), expected)
            self.assertEqual(result["status"], "running" if status == 429 else "skipped")

    def test_post_timeout_never_retries(self):
        calls = []

        def handler(request):
            calls.append(request)
            raise httpx.ReadTimeout("test-secret", request=request)

        self.transport(handler)
        result = tools.judge_continuity(self.frame, self.frame)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["status"], "skipped")
        self.assertNotIn("test-secret", json.dumps(result))

    def test_unknown_status_fails_soft(self):
        self.transport(lambda request: httpx.Response(200, json=envelope("failed")))
        self.assertEqual(tools.get_task("interaction_123")["status"], "skipped")

    def test_missing_api_key_fails_soft(self):
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": ""}),
            patch("providers.gemini.api.httpx.Client") as client,
        ):
            self.assertEqual(tools.judge_continuity(self.frame, self.frame)["status"], "skipped")
            client.assert_not_called()

    def test_deadline_bounds_client_polling(self):
        now = [0.0]
        def handler(request):
            now[0] = 31.0
            return httpx.Response(200, json=envelope("in_progress"))
        self.transport(handler)
        settings = contracts.GeminiSettings.from_env()
        with patch("providers.gemini.api.time.monotonic", side_effect=lambda: now[0]):
            with self.assertRaises(api.GeminiError):
                api.GeminiClient(settings).judge(Image.new("RGB", (8, 8)), Image.new("RGB", (8, 8)))

    def test_terminal_response_after_deadline_is_skipped(self):
        now = [0.0]
        def handler(request):
            now[0] = 31.0
            return httpx.Response(200, json=envelope())
        self.transport(handler)
        with patch("providers.gemini.api.time.monotonic", side_effect=lambda: now[0]):
            self.assertEqual(tools.get_task("interaction_123")["status"], "skipped")

    def test_poll_response_must_match_requested_job(self):
        payload = envelope()
        payload["id"] = "wrong_job"
        self.transport(lambda request: httpx.Response(200, json=payload))
        self.assertEqual(tools.get_task("interaction_123")["status"], "skipped")

    def test_response_byte_limit_and_redirect_are_skipped(self):
        self.transport(lambda request: httpx.Response(200, content=b"x" * (1024 * 1024 + 1)))
        self.assertEqual(tools.get_task("interaction_123")["status"], "skipped")
        self.transport(lambda request: httpx.Response(302, headers={"Location": "https://example.test/secret"}))
        self.assertEqual(tools.get_task("interaction_123")["status"], "skipped")

    def test_dry_run_export(self):
        with patch.dict(os.environ, {"GEMINI_DRY_RUN": "true"}):
            self.assertTrue(api.dry_run())

    def test_malformed_envelopes_fail_soft(self):
        invalid = [
            [],
            {"id": "interaction_123", "model": contracts.VERIFIED_MODEL, "status": []},
            {
                "id": "interaction_123",
                "model": contracts.VERIFIED_MODEL,
                "status": "completed",
                "steps": None,
            },
            {
                "id": "interaction_123",
                "model": contracts.VERIFIED_MODEL,
                "status": "completed",
                "steps": [{"type": "model_output", "content": None}],
            },
            {"id": "interaction_123", "model": "wrong-model", "status": "queued"},
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                self.transport(lambda request: httpx.Response(200, json=payload))
                self.assertEqual(tools.get_task("interaction_123")["status"], "skipped")

    def test_duplicate_judgement_keys_fail_soft(self):
        payload = envelope()
        payload["steps"][0]["content"][0]["text"] = (
            '{"same_shot_continuity":true,"confidence":0.1,"confidence":0.9,"issues":[]}'
        )
        self.transport(lambda request: httpx.Response(200, json=payload))
        self.assertEqual(tools.get_task("interaction_123")["status"], "skipped")

    def test_deep_json_fails_soft(self):
        nested = "[" * 1500 + "0" + "]" * 1500
        payload = envelope()
        payload["steps"][0]["content"][0]["text"] = nested
        self.transport(lambda request: httpx.Response(200, json=payload))
        self.assertEqual(tools.get_task("interaction_123")["status"], "skipped")
        self.transport(lambda request: httpx.Response(200, content=nested))
        self.assertEqual(tools.get_task("interaction_123")["status"], "skipped")

    def test_retry_limit_stops_transient_get(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(503, json={"error": "test-secret"})

        self.transport(handler)
        with patch("providers.gemini.api.time.sleep"):
            self.assertEqual(tools.get_task("interaction_123")["status"], "skipped")
        self.assertEqual(len(calls), 3)

    def test_bounded_issues_reject_long_or_many_items(self):
        for issues in [["x"] * 25, ["x" * 241], [""]]:
            with self.subTest(issues=issues), self.assertRaises(ValidationError):
                contracts.GeminiJudgement(same_shot_continuity=True, confidence=0.5, issues=issues)

    def test_dimensions_and_request_body_limits(self):
        with patch.object(contracts, "MAX_IMAGE_PIXELS", 10), self.assertRaises(ValueError):
            tools.judge_continuity(self.frame, self.frame)
        with patch.object(contracts, "MAX_BODY_BYTES", 100), self.assertRaises(ValueError):
            tools.judge_continuity(self.frame, self.frame)

    def test_jpeg_request_mime(self):
        output = io.BytesIO()
        Image.new("RGB", (8, 8)).save(output, format="JPEG")
        encoded = base64.b64encode(output.getvalue()).decode()
        part = contracts.image_part(encoded)
        self.assertEqual(part["mime_type"], "image/jpeg")

    def test_explicit_settings_cannot_disable_guard(self):
        with patch("providers.gemini.api.httpx.Client") as client:
            with self.assertRaisesRegex(api.GeminiError, "UNVERIFIED"):
                api.GeminiClient(contracts.GeminiSettings(model="unknown", dry_run=False)).judge(
                    None, None
                )
            client.assert_not_called()

    def test_gateway_export_names_match(self):
        self.assertEqual(set(tools.TOOL_HANDLERS), {"judge_continuity", "get_task"})
        self.assertEqual(tuple(tools.TOOL_HANDLERS), tools.GATEWAY_TOOLS)
        self.assertEqual(tools.GATEWAY_TOOLS, tools.GATEWAY_TOOL_NAMES)
