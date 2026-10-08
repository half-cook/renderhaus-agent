from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx

from providers.catalog import get_provider
from providers.kling import api
from providers.registry import dispatch, generate_schemas, load_committed_schemas


HTTP_CLIENT = httpx.Client
IMAGE = "https://media.example.test/frame.png"
ELEMENT = {"element_id": "123", "id": "hero", "element_type": "multi_image_elements"}


class KlingProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        environment = patch.dict(os.environ, {
            "RENDERHAUS_MEDIA_DIR": self.directory.name,
            "RENDERHAUS_SECRETS_NAME": "",
        }, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.requests: list[httpx.Request] = []
        self.response_handler = self.reject_network
        clients = patch.object(api.httpx, "Client", side_effect=self.make_client)
        clients.start()
        self.addCleanup(clients.stop)
        streams = patch.object(api.httpx, "stream", side_effect=AssertionError("Unexpected media request"))
        streams.start()
        self.addCleanup(streams.stop)

    def reject_network(self, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Unexpected API request {request.method} {request.url.path}")

    def make_client(self, *args, **kwargs) -> httpx.Client:
        return HTTP_CLIENT(transport=httpx.MockTransport(self.handle_request))

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response_handler(request)

    def enable_live(self, style: str = "current") -> None:
        os.environ.update({
            "KLING_DRY_RUN": "false", "KLING_API_STYLE": style,
            "KLING_API_KEY": "test-api-key", "KLING_ACCESS_KEY": "test-access-key",
            "KLING_SECRET_KEY": "test-secret-key",
        })

    def set_task(self, status: str, outputs: list[dict] | None = None) -> None:
        self.response_handler = lambda request: httpx.Response(200, json={
            "code": 0, "data": [{"id": "task-1", "status": status, "outputs": outputs or []}],
        })

    def test_dry_run_defaults_to_no_network_and_no_auth(self) -> None:
        results = [api.text_to_video("A bird"), api.image_to_video(IMAGE, "A bird"),
                   api.omni_video("A bird", reference_images=[IMAGE]),
                   api.get_video_task("current:text_to_video:task-1"), api.list_kling_models()]
        for result in results[:4]:
            self.assertEqual(result["status"], "dry_run")
        self.assertTrue(results[4]["models"])
        self.assertFalse(self.requests)
        self.assertFalse(list(Path(self.directory.name).rglob("*.mp4")))

    def test_only_explicit_false_enables_live_requests(self) -> None:
        for flag in ("true", "1", "0", "", "no"):
            with self.subTest(flag=flag), patch.dict(os.environ, {"KLING_DRY_RUN": flag}):
                self.assertEqual(api.text_to_video("A bird")["status"], "dry_run")
        self.assertFalse(self.requests)
        self.enable_live()
        self.response_handler = lambda request: httpx.Response(200, json={
            "code": 0, "data": {"id": "task-1", "status": "submitted"},
        })
        self.assertEqual(api.text_to_video("A bird")["status"], "queued")
        self.assertEqual(len(self.requests), 1)

    def test_gateway_rejects_invalid_arguments_before_http(self) -> None:
        self.enable_live()
        invalid = [{}, {"prompt": ""}, {"prompt": 2}, {"prompt": "x" * 3073},
                   {"prompt": "A bird", "duration_seconds": 2},
                   {"prompt": "A bird", "duration_seconds": 16},
                   {"prompt": "A bird", "duration_seconds": "5"},
                   {"prompt": "A bird", "duration_seconds": True},
                   {"prompt": "A bird", "generate_audio": "false"},
                   {"prompt": "A bird", "aspect_ratio": "4:3"},
                   {"prompt": "A bird", "resolution": "480p"},
                   {"prompt": "A bird", "model": "invented-model"},
                   {"prompt": "A bird", "watermark": True}]
        for arguments in invalid:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                dispatch("kling", "text_to_video", arguments)
        self.assertFalse(self.requests)

    def test_direct_tools_also_validate_before_http(self) -> None:
        self.enable_live()
        for call in (lambda: api.text_to_video("A bird", duration_seconds=True),
                     lambda: api.image_to_video("", "A bird"),
                     lambda: api.omni_video("A bird", end_image_path_or_url=IMAGE),
                     lambda: api.get_video_task("../../etc/passwd"),
                     lambda: api.get_video_task("current:text_to_video:task-1", download="yes")):
            with self.subTest(call=call), self.assertRaises(ValueError):
                call()
        self.assertFalse(self.requests)

    def test_current_text_request_uses_documented_settings_and_bearer_key(self) -> None:
        self.enable_live()
        self.response_handler = lambda request: httpx.Response(200, json={
            "code": 0, "data": {"id": "task-1", "status": "submitted"},
        })
        result = dispatch("kling", "text_to_video", {
            "prompt": "A bird", "duration_seconds": 15, "aspect_ratio": "9:16",
            "resolution": "4k", "generate_audio": True,
        })
        request = self.requests[0]
        self.assertEqual(request.url.path, "/text-to-video/kling-3.0")
        self.assertEqual(request.headers["Authorization"], "Bearer test-api-key")
        self.assertEqual(json.loads(request.content), {"prompt": "A bird", "settings": {
            "duration": 15, "aspect_ratio": "9:16", "resolution": "4k",
            "audio": "native", "multi_shot": False,
        }})
        self.assertEqual(result["job_id"], "current:text_to_video:task-1")
        self.assertEqual(result["status"], "queued")

    def test_current_first_last_frame_and_elements_serialization(self) -> None:
        style, model, path, body = api.prepare_request("image_to_video", {
            "image_path_or_url": IMAGE, "end_image_path_or_url": IMAGE + "?last=1",
            "prompt": "@hero moves", "elements": [ELEMENT], "generate_audio": True,
        })
        self.assertEqual((style, model, path), ("current", "kling-3.0", "/image-to-video/kling-3.0"))
        self.assertEqual(body["contents"], [
            {"type": "prompt", "text": "@hero moves"},
            {"type": "first_frame", "url": IMAGE},
            {"type": "last_frame", "url": IMAGE + "?last=1"},
            {"type": "element", "element_id": "123", "id": "hero"},
        ])
        self.assertEqual(body["settings"]["audio"], "native")
        self.assertNotIn("aspect_ratio", body["settings"])

    def test_submission_success_still_requires_polling_for_video_artifacts(self) -> None:
        self.enable_live()
        self.response_handler = lambda request: httpx.Response(200, json={
            "code": 0, "data": {"id": "task-1", "status": "succeeded"},
        })
        result = api.text_to_video("A bird")
        self.assertEqual(result["status"], "queued")
        self.assertNotIn("output_path", result)
        self.assertFalse(list(Path(self.directory.name).rglob("*.mp4")))

    def test_omni_reference_images_and_elements_share_a_documented_limit(self) -> None:
        _, model, path, body = api.prepare_request("omni_video", {
            "prompt": "@hero in @image_1", "reference_images": [IMAGE] * 6,
            "elements": [ELEMENT],
        })
        self.assertEqual((model, path), ("kling-3.0-omni", "/omni-video/kling-3.0-omni"))
        references = [item for item in body["contents"] if item["type"] == "refer_image"]
        self.assertEqual(len(references), 6)
        self.assertEqual(references[0], {"type": "refer_image", "url": IMAGE, "id": "image_1"})
        for args in ({"reference_images": [IMAGE] * 7, "elements": [ELEMENT]},
                     {"elements": [dict(ELEMENT, element_type="unknown")]},
                     {"elements": [ELEMENT, ELEMENT]},
                     {"reference_images": [IMAGE] * 5, "elements": [dict(ELEMENT, element_type="video_character_elements")]},
                     {"image_path_or_url": IMAGE, "elements": [dict(ELEMENT, id=f"person{i}") for i in range(4)]}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                api.prepare_request("omni_video", {"prompt": "A bird", **args})

    def test_multi_shot_prompt_and_documented_limits(self) -> None:
        shots = [{"prompt": "A bird takes off", "duration_seconds": 2},
                 {"prompt": "The bird lands", "duration_seconds": 3}]
        _, _, _, body = api.prepare_request("text_to_video", {
            "prompt": "A bird", "shots": shots, "multi_shot": True,
        })
        self.assertEqual(body["prompt"], "shot 1, 2, A bird takes off; shot 2, 3, The bird lands;")
        self.assertTrue(body["settings"]["multi_shot"])
        for args in ({"multi_shot": False, "shots": shots},
                     {"multi_shot": True, "shots": [{"prompt": "Bird", "duration_seconds": 0}]},
                     {"multi_shot": True, "shots": [{"prompt": "Bird", "duration_seconds": 4}]},
                     {"multi_shot": True, "shots": [{"prompt": "x" * 513, "duration_seconds": 5}]},
                     {"multi_shot": True, "duration_seconds": 7, "shots": [{"prompt": "Bird", "duration_seconds": 1}] * 7},
                     {"multi_shot": True, "shots": [{"prompt": "Bird", "duration_seconds": 5, "extra": 1}]}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                api.prepare_request("text_to_video", {"prompt": "A bird", **args})

    def test_turbo_omits_unsupported_settings_and_rejects_audio_or_4k(self) -> None:
        _, _, path, body = api.prepare_request("text_to_video", {
            "prompt": "A bird", "model": "kling-3.0-turbo",
        })
        self.assertEqual(path, "/text-to-video/kling-3.0-turbo")
        self.assertNotIn("audio", body["settings"])
        self.assertNotIn("multi_shot", body["settings"])
        for args in ({"generate_audio": True}, {"resolution": "4k"}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                api.prepare_request("text_to_video", {"prompt": "A bird", "model": "kling-3.0-turbo", **args})

    def test_legacy_text_request_and_first_last_frames_use_legacy_fields(self) -> None:
        with patch.dict(os.environ, {"KLING_API_STYLE": "legacy"}):
            style, _, path, body = api.prepare_request("text_to_video", {
                "prompt": "A bird", "resolution": "1080p", "generate_audio": True,
            })
            self.assertEqual((style, path), ("legacy", "/v1/videos/text2video"))
            self.assertEqual(body["model_name"], "kling-v3")
            self.assertEqual(body["duration"], "5")
            self.assertEqual(body["mode"], "pro")
            self.assertEqual(body["sound"], "on")
            _, _, path, body = api.prepare_request("image_to_video", {
                "prompt": "A bird", "image_path_or_url": IMAGE,
                "end_image_path_or_url": IMAGE + "?last=1",
            })
            self.assertEqual(path, "/v1/videos/image2video")
            self.assertEqual(body["image"], IMAGE)
            self.assertEqual(body["image_tail"], IMAGE + "?last=1")
            with self.assertRaises(ValueError):
                api.prepare_request("text_to_video", {"prompt": "x" * 2501})

    def test_legacy_multi_shot_and_omni_references_use_documented_lists(self) -> None:
        with patch.dict(os.environ, {"KLING_API_STYLE": "legacy"}):
            _, _, _, body = api.prepare_request("text_to_video", {
                "prompt": "A bird", "multi_shot": True, "shots": [
                    {"prompt": "Takes off", "duration_seconds": 2},
                    {"prompt": "Lands", "duration_seconds": 3},
                ],
            })
            self.assertEqual(body["shot_type"], "customize")
            self.assertEqual(body["multi_prompt"], [
                {"index": 1, "prompt": "Takes off", "duration": "2"},
                {"index": 2, "prompt": "Lands", "duration": "3"},
            ])
            self.assertNotIn("prompt", body)
            _, _, path, body = api.prepare_request("omni_video", {
                "prompt": "<<<element_1>>> in <<<image_1>>>", "reference_images": [IMAGE],
                "elements": [ELEMENT], "image_path_or_url": IMAGE,
                "end_image_path_or_url": IMAGE + "?last=1",
            })
            self.assertEqual(path, "/v1/videos/omni-video")
            self.assertEqual(body["model_name"], "kling-v3-omni")
            self.assertEqual(body["image_list"], [
                {"image_url": IMAGE},
                {"image_url": IMAGE, "type": "first_frame"},
                {"image_url": IMAGE + "?last=1", "type": "end_frame"},
            ])
            self.assertEqual(body["element_list"], [{"element_id": 123}])

    def test_jwt_signature_and_time_claims_independent_of_provider_helpers(self) -> None:
        token = api._signed_jwt("access-for-test", "secret-for-test", now=1700000000)
        header_segment, payload_segment, signature_segment = token.split(".")
        decode = lambda segment: base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
        self.assertEqual(json.loads(decode(header_segment)), {"alg": "HS256", "typ": "JWT"})
        self.assertEqual(json.loads(decode(payload_segment)), {
            "iss": "access-for-test", "exp": 1700001800, "nbf": 1699999995,
        })
        self.assertEqual(decode(signature_segment), hmac.new(
            b"secret-for-test", f"{header_segment}.{payload_segment}".encode(), hashlib.sha256,
        ).digest())

    def test_missing_credentials_do_not_submit(self) -> None:
        os.environ["KLING_DRY_RUN"] = "false"
        with self.assertRaisesRegex(RuntimeError, "KLING_API_KEY"):
            api.text_to_video("A bird")
        with patch.dict(os.environ, {"KLING_API_STYLE": "legacy"}):
            with self.assertRaisesRegex(RuntimeError, "KLING_ACCESS_KEY|KLING_SECRET_KEY"):
                api.text_to_video("A bird")
        self.assertFalse(self.requests)

    def test_auth_prefers_environment_credentials_to_secrets_manager(self) -> None:
        self.enable_live()
        with patch.dict(os.environ, {"RENDERHAUS_SECRETS_NAME": "test-secret-name"}), \
             patch.object(api.boto3, "client") as client:
            self.assertEqual(api._headers("current")["Authorization"], "Bearer test-api-key")
            token = api._headers("legacy")["Authorization"].split()[1]
            payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
            self.assertEqual(payload["iss"], "test-access-key")
        client.assert_not_called()

    def test_auth_loads_missing_secrets_and_keeps_explicit_environment_values(self) -> None:
        secret = Mock()
        secret.get_secret_value.return_value = {"SecretString": json.dumps({
            "KLING_API_KEY": "secret-manager-api-key", "KLING_ACCESS_KEY": "sm-access-key",
            "KLING_SECRET_KEY": "sm-secret-key",
        })}
        with patch.dict(os.environ, {"RENDERHAUS_SECRETS_NAME": "test-secret-name"}), \
             patch.object(api.boto3, "client", return_value=secret):
            self.assertEqual(api._headers("current")["Authorization"], "Bearer secret-manager-api-key")
            with patch.dict(os.environ, {"KLING_ACCESS_KEY": "explicit-access-key"}):
                token = api._headers("legacy")["Authorization"].split()[1]
                payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
                self.assertEqual(payload["iss"], "explicit-access-key")
                signature = base64.urlsafe_b64decode(token.split(".")[2] + "=")
                self.assertEqual(signature, hmac.new(
                    b"sm-secret-key", ".".join(token.split(".")[:2]).encode(), hashlib.sha256,
                ).digest())
        secret.get_secret_value.assert_called_with(SecretId="test-secret-name")

    def test_secrets_manager_errors_do_not_expose_secret_payloads(self) -> None:
        secret = Mock()
        secret.get_secret_value.side_effect = RuntimeError("secret-manager-api-key")
        with patch.dict(os.environ, {"RENDERHAUS_SECRETS_NAME": "test-secret-name"}), \
             patch.object(api.boto3, "client", return_value=secret):
            with self.assertRaises(RuntimeError) as failure:
                api._headers("current")
        self.assertNotIn("secret-manager-api-key", str(failure.exception))

    def test_local_reference_images_validate_dimensions_and_encode_without_network(self) -> None:
        path = Path(self.directory.name) / "frame.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 600, 400))
        result = api.image_to_video(str(path), "A bird")
        self.assertEqual(result["status"], "dry_run")
        for width, height in ((299, 400), (400, 299), (300, 1000)):
            path.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height))
            with self.subTest(width=width, height=height), self.assertRaises(ValueError):
                api.image_to_video(str(path), "A bird")
        path.write_bytes(b"not an image")
        with self.assertRaises(ValueError):
            api.image_to_video(str(path), "A bird")
        self.assertFalse(self.requests)

    def test_current_task_poll_matches_requested_id_and_maps_states(self) -> None:
        self.enable_live()
        for upstream, expected in (("submitted", "queued"), ("processing", "running"),
                                   ("failed", "failed"), ("succeeded", "succeeded")):
            outputs = [{"type": "video", "url": "https://media.example.test/video.mp4"}] if upstream == "succeeded" else []
            self.response_handler = lambda request, status=upstream, out=outputs: httpx.Response(200, json={
                "code": 0, "data": [{"id": "another-task", "status": "failed"},
                                      {"id": "task-1", "status": status, "outputs": out}],
            })
            with self.subTest(upstream=upstream):
                result = api.get_video_task("current:text_to_video:task-1")
                self.assertEqual(result["status"], expected)
                self.assertEqual(self.requests[-1].url.path, "/tasks")
                self.assertEqual(self.requests[-1].url.params["task_ids"], "task-1")
        self.assertFalse(list(Path(self.directory.name).rglob("*.mp4")))

    def test_legacy_job_id_routes_after_cold_start_even_with_current_default(self) -> None:
        self.enable_live()
        self.response_handler = lambda request: httpx.Response(200, json={
            "code": 0, "data": {"task_id": "task-1", "task_status": "processing"},
        })
        result = api.get_video_task("legacy:omni_video:task-1")
        self.assertEqual(result["status"], "running")
        self.assertEqual(self.requests[0].url.path, "/v1/videos/omni-video/task-1")
        self.assertEqual(len(self.requests[0].headers["Authorization"].split()[1].split(".")), 3)

    def test_completed_task_requires_a_video_and_requested_task(self) -> None:
        self.enable_live()
        for data in ([{"id": "task-1", "status": "succeeded", "outputs": []}],
                     [{"id": "other-task", "status": "processing"}], [], {}):
            self.response_handler = lambda request, value=data: httpx.Response(200, json={"code": 0, "data": value})
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                api.get_video_task("current:text_to_video:task-1", download=True)

    def test_poll_rejects_unknown_states_duplicate_ids_and_nonvideo_success(self) -> None:
        self.enable_live()
        cases = [
            [{"id": "task-1", "status": "mystery"}],
            [{"id": "task-1", "status": {"unexpected": "object"}}],
            [{"id": "task-1", "status": "submitted"}] * 2,
            [{"id": "task-1", "status": "succeeded", "outputs": [{"type": "audio", "url": IMAGE}]}],
            [{"id": "task-1", "status": "succeeded", "outputs": [{"type": "video"}]}],
            [{"id": "task-1", "status": "succeeded", "outputs": ["malformed"]}],
        ]
        for data in cases:
            self.response_handler = lambda request, value=data: httpx.Response(200, json={"code": 0, "data": value})
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                api.get_video_task("current:text_to_video:task-1")

    def test_completed_outputs_download_real_bytes_once_each(self) -> None:
        self.enable_live()
        urls = ["https://media.example.test/one.mp4", "https://media.example.test/two.mp4"]
        self.set_task("succeeded", [{"type": "video", "url": url} for url in urls])
        media_requests = []
        def media_handler(request):
            media_requests.append(request)
            self.assertNotIn("authorization", request.headers)
            return httpx.Response(200, content=b"video-" + request.url.path.encode())
        with HTTP_CLIENT(transport=httpx.MockTransport(media_handler)) as client, \
             patch.object(api.httpx, "stream", side_effect=client.stream):
            first = api.get_video_task("current:text_to_video:task-1", download=True)
            second = api.get_video_task("current:text_to_video:task-1", download=True)
        self.assertEqual(len(first["videos"]), 2)
        self.assertTrue(first["downloaded"])
        self.assertEqual(first["output_path"], first["videos"][0]["output_path"])
        self.assertEqual(first["videos"], second["videos"])
        self.assertEqual(len(media_requests), 2)
        for video, url in zip(first["videos"], urls, strict=True):
            self.assertEqual(Path(video["output_path"]).read_bytes(), b"video-" + httpx.URL(url).path.encode())

    def test_partial_download_never_leaves_a_completed_or_partial_artifact(self) -> None:
        self.enable_live()
        self.set_task("succeeded", [{"type": "video", "url": "https://media.example.test/video.mp4"}])
        class BrokenVideo(httpx.SyncByteStream):
            def __iter__(self):
                yield b"partial-video"
                raise httpx.ReadError("https://media.example.test/video.mp4?token=secret")
        with HTTP_CLIENT(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=BrokenVideo()),
        )) as client, patch.object(api.httpx, "stream", side_effect=client.stream):
            with self.assertRaises(RuntimeError) as failure:
                api.get_video_task("current:text_to_video:task-1", download=True)
        self.assertNotIn("token=secret", str(failure.exception))
        self.assertFalse(list(Path(self.directory.name).rglob("*.mp4")))
        self.assertFalse(list(Path(self.directory.name).rglob("*.part")))

    def test_empty_download_is_a_failure_without_a_completed_artifact(self) -> None:
        self.enable_live()
        self.set_task("succeeded", [{"type": "video", "url": "https://media.example.test/video.mp4"}])
        with HTTP_CLIENT(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b""),
        )) as client, patch.object(api.httpx, "stream", side_effect=client.stream):
            with self.assertRaisesRegex(RuntimeError, "empty"):
                api.get_video_task("current:text_to_video:task-1", download=True)
        self.assertFalse(list(Path(self.directory.name).rglob("*.mp4")))
        self.assertFalse(list(Path(self.directory.name).rglob("*.part")))

    def test_api_errors_invalid_json_and_missing_task_id_are_redacted(self) -> None:
        self.enable_live()
        failures = [httpx.Response(403, json={"code": 1001, "message": "test-api-key"}),
                    httpx.Response(200, json={"code": 1002, "message": "test-secret-key"}),
                    httpx.Response(200, content=b"not-json test-api-key"),
                    httpx.Response(200, json={"code": 0, "data": {}})]
        for response in failures:
            self.response_handler = lambda request, value=response: value
            with self.subTest(response=response), self.assertRaises(RuntimeError) as failure:
                api.text_to_video("A bird")
            self.assertNotIn("test-api-key", str(failure.exception))
            self.assertNotIn("test-secret-key", str(failure.exception))

    def test_transport_errors_do_not_expose_credentials_or_signed_urls(self) -> None:
        self.enable_live()
        def fail(request):
            raise httpx.ConnectError("test-api-key https://media.test/file?token=secret", request=request)
        self.response_handler = fail
        with self.assertRaises(RuntimeError) as failure:
            api.text_to_video("A bird")
        self.assertNotIn("test-api-key", str(failure.exception))
        self.assertNotIn("token=secret", str(failure.exception))

    def test_gateway_schema_matches_committed_tools_and_lambda_dispatches(self) -> None:
        from lambdas.handler import handler
        spec = get_provider("kling")
        schemas = generate_schemas(spec)
        self.assertEqual(schemas, load_committed_schemas(spec))
        self.assertEqual({tool["name"] for tool in schemas}, {
            "text_to_video", "image_to_video", "omni_video", "get_video_task", "list_kling_models",
        })
        context = SimpleNamespace(client_context=SimpleNamespace(custom={
            "bedrockAgentCoreToolName": "Kling___text_to_video",
        }))
        with patch.dict(os.environ, {"RENDERHAUS_PROVIDER": "kling"}):
            result = handler({"prompt": "A bird"}, context)
            self.assertEqual(result["status"], "dry_run")
            invalid = handler({"prompt": "A bird", "duration_seconds": 2}, context)
            self.assertEqual(invalid["error_type"], "ValueError")
        self.assertFalse(self.requests)

    def test_model_list_is_documented_catalog_without_remote_discovery(self) -> None:
        self.enable_live()
        result = dispatch("kling", "list_kling_models", {})
        self.assertEqual({model["id"] for model in result["models"]}, {
            "kling-3.0", "kling-3.0-turbo", "kling-3.0-omni",
        })
        self.assertFalse(self.requests)


if __name__ == "__main__":
    unittest.main()
