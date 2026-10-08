from __future__ import annotations

import base64
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from providers.luma import api


JOB_ID = "d290f1ee-6c54-4b01-90e6-d701748f0851"
SOURCE_ID = "3857feba-a9e5-4a33-9ad4-14d5d65c0b5e"
VIDEO_URL = "https://media.example.test/result.mp4"
HTTP_CLIENT = httpx.Client


def atom(kind: bytes, payload: bytes, extended: bool = False) -> bytes:
    if extended:
        return struct.pack(">I4sQ", 1, kind, 16 + len(payload)) + payload
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def mp4(duration_ms: int = 5000, version: int = 0, timescale: int = 1000) -> bytes:
    if version == 1:
        header = struct.pack(">B3sQQIQ", 1, b"\0\0\0", 0, 0, timescale, duration_ms)
    else:
        header = struct.pack(">B3sIIII", version, b"\0\0\0", 0, 0, timescale, duration_ms)
    return atom(b"ftyp", b"isom\0\0\0\0isom") + atom(b"moov", atom(b"mvhd", header))


def generation(state: str = "queued", job_id: str = JOB_ID) -> dict:
    return {
        "id": job_id,
        "model": "ray-3.2",
        "state": state,
        "output": [{"type": "video", "url": VIDEO_URL}] if state == "completed" else [],
        "failure_code": None,
        "failure_reason": None,
    }


class BrokenStream(httpx.SyncByteStream):
    def __iter__(self):
        yield b"partial"
        raise httpx.ReadError("connection dropped")


class LumaProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.media = Path(self.temporary.name)
        self.environment = patch.dict(
            os.environ,
            {
                "LUMA_DRY_RUN": "false",
                "LUMA_API_KEY": "test-key",
                "RENDERHAUS_MEDIA_DIR": str(self.media),
            },
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.requests: list[httpx.Request] = []

    def transport(self, handler=None) -> None:
        def respond(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if handler:
                return handler(request)
            if request.url.host == "media.example.test":
                return httpx.Response(200, content=mp4(), headers={"Content-Type": "video/mp4"})
            return httpx.Response(201 if request.method == "POST" else 200, json=generation())

        replacement = patch.object(
            api.httpx,
            "Client",
            side_effect=lambda **kwargs: HTTP_CLIENT(
                transport=httpx.MockTransport(respond),
                **kwargs,
            ),
        )
        replacement.start()
        self.addCleanup(replacement.stop)

    def request_body(self) -> dict:
        request = next(request for request in reversed(self.requests) if request.method == "POST")
        return json.loads(request.content)

    def source_file(self, content: bytes | None = None, name: str = "source.mp4") -> Path:
        path = self.media / name
        path.write_bytes(mp4() if content is None else content)
        return path

    def test_dry_run_defaults_and_never_accesses_credentials_files_or_http(self) -> None:
        os.environ.pop("LUMA_DRY_RUN")
        with (
            patch.object(api, "_headers", side_effect=AssertionError("credential access")),
            patch.object(api.httpx, "Client", side_effect=AssertionError("HTTP access")),
            patch.object(Path, "open", side_effect=AssertionError("file access")),
            patch.object(Path, "read_text", side_effect=AssertionError("file access")),
            patch.object(Path, "write_text", side_effect=AssertionError("file access")),
        ):
            results = [
                api.text_to_video("A river", resolution="360p", duration_seconds=10),
                api.image_to_video("A river", image_path_or_url="/missing/start.png"),
                api.image_to_video("A river", last_frame_path_or_url="/missing/end.png"),
                api.extend_video("Continue", SOURCE_ID),
                api.modify_video("Moonlight", 5, video_path_or_url="/missing/source.mp4"),
                api.modify_video("Moonlight", 10, source_generation_id=SOURCE_ID),
                api.get_video_task(JOB_ID),
            ]
        for result in results:
            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(result["provider"], "luma")
            self.assertEqual(result["model"], "ray-3.2")
            self.assertFalse(result["training_eligible"])
            self.assertIsNone(result["output_path"])
            self.assertIsNone(result["video_url"])
            self.assertFalse(result["downloaded"])
            self.assertIsNone(result["failure_code"])
            self.assertIsNone(result["failure_reason"])

    def test_only_case_insensitive_false_enables_live_mode(self) -> None:
        with patch.object(api.httpx, "Client", side_effect=AssertionError("HTTP access")):
            for value in ("true", "0", "", " false ", "typo"):
                with self.subTest(value=value), patch.dict(os.environ, {"LUMA_DRY_RUN": value}):
                    self.assertEqual(api.text_to_video("A river")["status"], "dry_run")
        self.transport()
        for value in ("false", "False", "FALSE"):
            with self.subTest(value=value), patch.dict(os.environ, {"LUMA_DRY_RUN": value}):
                self.assertEqual(api.text_to_video("A river")["status"], "queued")

    def test_invalid_direct_arguments_are_rejected_before_io_even_in_dry_mode(self) -> None:
        cases = [
            (api.text_to_video, {"prompt": ""}),
            (api.text_to_video, {"prompt": " "}),
            (api.text_to_video, {"prompt": "x" * 6001}),
            (api.text_to_video, {"prompt": "A river", "duration_seconds": 6}),
            (api.text_to_video, {"prompt": "A river", "duration_seconds": 5.0}),
            (api.text_to_video, {"prompt": "A river", "duration_seconds": True}),
            (api.text_to_video, {"prompt": "A river", "resolution": "480p"}),
            (api.text_to_video, {"prompt": "A river", "aspect_ratio": "adaptive"}),
            (api.text_to_video, {"prompt": "A river", "model": "ray-flash"}),
            (api.image_to_video, {"prompt": "A river"}),
            (api.image_to_video, {"prompt": "A river", "image_path_or_url": ""}),
            (
                api.image_to_video,
                {
                    "prompt": "A river",
                    "image_path_or_url": "https://example.test/a.png",
                    "duration_seconds": 10,
                },
            ),
            (
                api.image_to_video,
                {"prompt": "A river", "image_path_or_url": "https://user:pass@example.test/a.png"},
            ),
            (
                api.extend_video,
                {"prompt": "Continue", "generation_id": SOURCE_ID, "resolution": "360p"},
            ),
            (
                api.extend_video,
                {"prompt": "Continue", "generation_id": SOURCE_ID, "direction": "sideways"},
            ),
            (api.extend_video, {"prompt": "Continue", "generation_id": "../../task"}),
            (api.modify_video, {"prompt": "Edit", "source_duration_seconds": 5}),
            (
                api.modify_video,
                {
                    "prompt": "Edit",
                    "source_duration_seconds": 5,
                    "video_path_or_url": "source.mp4",
                    "source_generation_id": SOURCE_ID,
                },
            ),
            (
                api.modify_video,
                {"prompt": "Edit", "source_duration_seconds": 6, "video_path_or_url": "source.mp4"},
            ),
            (
                api.modify_video,
                {
                    "prompt": "Edit",
                    "source_duration_seconds": True,
                    "video_path_or_url": "source.mp4",
                },
            ),
            (
                api.modify_video,
                {
                    "prompt": "Edit",
                    "source_duration_seconds": 5,
                    "video_path_or_url": "source.mp4",
                    "strength": "flex",
                },
            ),
        ]
        with (
            patch.dict(os.environ, {"LUMA_DRY_RUN": "true"}),
            patch.object(api.httpx, "Client", side_effect=AssertionError("HTTP access")),
            patch.object(Path, "open", side_effect=AssertionError("file access")),
        ):
            for function, arguments in cases:
                with self.subTest(tool=function.__name__, arguments=arguments):
                    with self.assertRaises(ValueError):
                        function(**arguments)

    def test_text_request_uses_official_endpoint_bearer_and_sdr_options(self) -> None:
        self.transport()
        result = api.text_to_video("A river", 10, "9:16", "360p")
        self.assertEqual(str(self.requests[0].url), "https://agents.lumalabs.ai/v1/generations")
        self.assertEqual(self.requests[0].headers["Authorization"], "Bearer test-key")
        self.assertEqual(
            self.request_body(),
            {
                "model": "ray-3.2",
                "type": "video",
                "prompt": "A river",
                "aspect_ratio": "9:16",
                "video": {"resolution": "360p", "duration": "10s"},
            },
        )
        self.assertEqual(result["job_id"], JOB_ID)
        self.assertEqual(result["status"], "queued")
        self.assertFalse(result["training_eligible"])
        metadata = json.loads((self.media / "video/luma/.tasks" / f"{JOB_ID}.json").read_text())
        self.assertFalse(metadata["training_eligible"])
        self.assertEqual(metadata["duration_seconds"], 10)

    def test_image_request_supports_start_end_and_local_inline_images(self) -> None:
        self.transport()
        path = self.source_file(b"image bytes", "start.png")
        api.image_to_video("A river", str(path), "https://example.test/end.png")
        self.assertEqual(
            self.request_body()["video"],
            {
                "resolution": "720p",
                "duration": "5s",
                "start_frame": {
                    "data": base64.b64encode(b"image bytes").decode(),
                    "media_type": "image/png",
                },
                "end_frame": {"url": "https://example.test/end.png"},
            },
        )
        api.image_to_video("A river", last_frame_path_or_url="https://example.test/end.png")
        self.assertEqual(
            self.request_body()["video"],
            {
                "resolution": "720p",
                "duration": "5s",
                "end_frame": {"url": "https://example.test/end.png"},
            },
        )
        api.image_to_video("A river", image_path_or_url="data:image/png;base64,aW1hZ2U=")
        self.assertEqual(
            self.request_body()["video"]["start_frame"],
            {"data": "aW1hZ2U=", "media_type": "image/png"},
        )

    def test_extend_request_uses_single_prior_generation_without_duration_or_aspect(self) -> None:
        self.transport()
        for direction, frame in (("forward", "start_frame"), ("backward", "end_frame")):
            with self.subTest(direction=direction):
                result = api.extend_video("Continue", SOURCE_ID, direction, "540p")
                self.assertEqual(
                    self.request_body(),
                    {
                        "model": "ray-3.2",
                        "type": "video",
                        "prompt": "Continue",
                        "video": {"resolution": "540p", frame: {"generation_id": SOURCE_ID}},
                    },
                )
                self.assertEqual(result["duration_seconds"], 5)

    def test_bad_inline_images_and_oversize_inputs_never_submit(self) -> None:
        self.transport()
        for value in (
            "data:text/plain;base64,aW1hZ2U=",
            "data:image/png;base64,%%%",
            "data:image/png,raw",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                api.image_to_video("A river", image_path_or_url=value)
        image = self.source_file(b"image", "source.png")
        with patch.object(api, "MAX_IMAGE_BYTES", 4), self.assertRaises(ValueError):
            api.image_to_video("A river", image_path_or_url=str(image))
        video = self.source_file()
        with patch.object(api, "MAX_VIDEO_BYTES", 4), self.assertRaises(ValueError):
            api.modify_video("Edit", 5, str(video))
        with self.assertRaisesRegex(ValueError, "MP4 sources only"):
            api.modify_video("Edit", 5, str(self.source_file(name="source.webm")))
        self.assertEqual(self.requests, [])

    def test_modify_local_source_uses_inline_mp4_and_preserves_source_duration(self) -> None:
        self.transport()
        source = self.source_file(mp4(10000, version=1))
        result = api.modify_video("Moonlight", 10, str(source), resolution="1080p")
        body = self.request_body()
        self.assertEqual(body["type"], "video_edit")
        self.assertEqual(body["video"], {"resolution": "1080p", "edit": {"auto_controls": True}})
        self.assertEqual(body["source"]["media_type"], "video/mp4")
        self.assertEqual(base64.b64decode(body["source"]["data"]), source.read_bytes())
        self.assertNotIn("duration", body["video"])
        self.assertNotIn("aspect_ratio", body)
        self.assertEqual(result["source_duration_seconds"], 10)

    def test_modify_hosted_source_is_measured_before_submit_and_uses_strength(self) -> None:
        self.transport()
        api.modify_video("Moonlight", 5, VIDEO_URL, strength="flex_2")
        self.assertEqual([request.method for request in self.requests], ["GET", "POST"])
        self.assertEqual(
            self.request_body()["source"], {"url": VIDEO_URL, "media_type": "video/mp4"}
        )
        self.assertEqual(
            self.request_body()["video"], {"resolution": "720p", "edit": {"strength": "flex_2"}}
        )

    def test_modify_prior_generation_is_completed_and_measured_before_submit(self) -> None:
        def respond(request):
            if str(request.url).endswith(SOURCE_ID):
                return httpx.Response(200, json=generation("completed", SOURCE_ID))
            if request.url.host == "media.example.test":
                return httpx.Response(200, content=mp4())
            return httpx.Response(201, json=generation())

        self.transport(respond)
        api.modify_video("Moonlight", 5, source_generation_id=SOURCE_ID)
        self.assertEqual([request.method for request in self.requests], ["GET", "GET", "POST"])
        self.assertEqual(self.request_body()["source"], {"generation_id": SOURCE_ID})

    def test_modify_incomplete_source_generation_never_submits(self) -> None:
        self.transport(
            lambda request: httpx.Response(200, json=generation("processing", SOURCE_ID))
        )
        with self.assertRaisesRegex(ValueError, "completed source generation"):
            api.modify_video("Moonlight", 5, source_generation_id=SOURCE_ID)
        self.assertEqual([request.method for request in self.requests], ["GET"])

    def test_modify_duration_quote_mismatch_and_unpriced_lengths_never_submit(self) -> None:
        self.transport()
        for duration in (4900, 6000, 10000, 18001, 20000):
            with self.subTest(duration=duration):
                source = self.source_file(mp4(duration))
                with self.assertRaises(ValueError):
                    api.modify_video("Moonlight", 5, str(source))
        self.assertEqual(self.requests, [])

    def test_modify_allows_a_frame_of_encoding_duration_tolerance(self) -> None:
        self.transport()
        source = self.source_file(mp4(4960))
        self.assertEqual(api.modify_video("Moonlight", 5, str(source))["status"], "queued")

    def test_modify_mp4_parser_accepts_extended_atoms_and_rejects_bad_bounds(self) -> None:
        self.transport()
        ordinary = mp4()
        movie_header = struct.pack(">B3sIIII", 0, b"\0\0\0", 0, 0, 1000, 5000)
        extended = atom(b"ftyp", b"isom\0\0\0\0") + atom(
            b"moov", atom(b"mvhd", movie_header, True), True
        )
        self.assertEqual(
            api.modify_video("Edit", 5, str(self.source_file(extended)))["status"], "queued"
        )
        cases = [
            b"",
            b"not an mp4",
            ordinary[:-1],
            mp4(version=2),
            mp4(timescale=0),
            mp4(0),
            mp4(0xFFFFFFFF),
            atom(b"ftyp", b"isom\0\0\0\0"),
            atom(b"moov", atom(b"mvhd", movie_header)),
            atom(b"ftyp", b"isom\0\0\0\0") + atom(b"moov", atom(b"mvhd", b"\0\0\0\0")),
            ordinary + struct.pack(">I4sQ", 1, b"mdat", 15),
            ordinary + struct.pack(">I4s", 1, b"mdat"),
            ordinary + struct.pack(">I4s", 4, b"mdat"),
        ]
        before = len(self.requests)
        for index, content in enumerate(cases):
            with self.subTest(index=index):
                with self.assertRaises(ValueError):
                    api.modify_video("Edit", 5, str(self.source_file(content)))
        self.assertEqual(len(self.requests), before)

    def test_poll_normalizes_all_official_states_and_exposes_failures(self) -> None:
        state = "queued"

        def respond(request):
            payload = generation(state)
            if state == "failed":
                payload.update(
                    failure_code="generation_failed", failure_reason="Provider generation failed."
                )
            return httpx.Response(200, json=payload)

        self.transport(respond)
        for state, expected in (
            ("queued", "queued"),
            ("processing", "running"),
            ("completed", "succeeded"),
            ("failed", "failed"),
        ):
            with self.subTest(state=state):
                result = api.get_video_task(JOB_ID, download=False)
                self.assertEqual(result["status"], expected)
                self.assertFalse(result["training_eligible"])
                self.assertEqual(
                    str(self.requests[-1].url),
                    f"https://agents.lumalabs.ai/v1/generations/{JOB_ID}",
                )
                if state == "failed":
                    self.assertEqual(result["failure_code"], "generation_failed")
                    self.assertEqual(result["failure_reason"], "Provider generation failed.")
                if state != "completed":
                    self.assertIsNone(result["video_url"])

    def test_completed_poll_download_is_atomic_durable_and_idempotent(self) -> None:
        def respond(request):
            if request.url.host == "media.example.test":
                self.assertNotIn("Authorization", request.headers)
                return httpx.Response(200, content=mp4())
            return httpx.Response(200, json=generation("completed"))

        self.transport(respond)
        first = api.get_video_task(JOB_ID)
        second = api.get_video_task(JOB_ID)
        self.assertTrue(first["downloaded"])
        self.assertEqual(first["output_path"], second["output_path"])
        path = Path(first["output_path"])
        self.assertEqual(path.read_bytes(), mp4())
        self.assertEqual(
            len([request for request in self.requests if request.url.host == "media.example.test"]),
            1,
        )
        self.assertEqual(list(path.parent.glob("*.tmp")), [])
        metadata = json.loads((path.parent / ".tasks" / f"{JOB_ID}.json").read_text())
        self.assertEqual(metadata["status"], "succeeded")
        self.assertFalse(metadata["training_eligible"])

    def test_partial_empty_oversize_and_short_downloads_never_publish_a_video(self) -> None:
        replies = (
            lambda: httpx.Response(200, stream=BrokenStream()),
            lambda: httpx.Response(200, content=b""),
            lambda: httpx.Response(
                200, content=b"huge", headers={"Content-Length": str(api.MAX_VIDEO_BYTES + 1)}
            ),
            lambda: httpx.Response(200, content=b"short", headers={"Content-Length": "1000"}),
        )
        for reply in replies:
            with self.subTest(reply=reply):
                self.transport(
                    lambda request: (
                        reply()
                        if request.url.host == "media.example.test"
                        else httpx.Response(200, json=generation("completed"))
                    )
                )
                with self.assertRaises((httpx.ReadError, RuntimeError, ValueError)):
                    api.get_video_task(JOB_ID)
                self.assertFalse((self.media / "video/luma" / f"{JOB_ID}.mp4").exists())
                self.assertEqual(list((self.media / "video/luma").glob("*.tmp")), [])

    def test_streaming_download_limit_applies_without_a_content_length(self) -> None:
        self.transport(
            lambda request: (
                httpx.Response(200, stream=httpx.ByteStream(b"oversize"))
                if request.url.host == "media.example.test"
                else httpx.Response(200, json=generation("completed"))
            )
        )
        with patch.object(api, "MAX_VIDEO_BYTES", 4), self.assertRaises(ValueError):
            api.get_video_task(JOB_ID)
        directory = self.media / "video/luma"
        self.assertFalse((directory / f"{JOB_ID}.mp4").exists())
        self.assertEqual(list(directory.glob("*.tmp")), [])

    def test_generation_ids_cannot_escape_urls_or_files(self) -> None:
        with patch.object(api.httpx, "Client", side_effect=AssertionError("HTTP access")):
            for value in (
                "../task",
                "a/b",
                "https://example.test",
                "",
                JOB_ID.upper(),
                JOB_ID.replace("-", ""),
            ):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    api.get_video_task(value)

    def test_malformed_generation_results_fail_visibly(self) -> None:
        payloads = [
            [],
            {"state": "queued"},
            generation("unknown"),
            {**generation(), "id": "../task"},
            {**generation(), "model": "ray-2"},
            {**generation(), "failure_reason": {}},
            {**generation("completed"), "output": []},
            {**generation("completed"), "output": [{"type": "image", "url": VIDEO_URL}]},
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.transport(lambda request: httpx.Response(201, json=payload))
                with self.assertRaises(RuntimeError):
                    api.text_to_video("A river")

    def test_poll_different_generation_id_is_rejected(self) -> None:
        self.transport(lambda request: httpx.Response(200, json=generation(job_id=SOURCE_ID)))
        with self.assertRaisesRegex(RuntimeError, "different generation id"):
            api.get_video_task(JOB_ID, download=False)

    def test_http_network_and_invalid_json_errors_do_not_retry_posts(self) -> None:
        def network_error(request):
            raise httpx.ConnectError("offline", request=request)

        cases = (
            (
                lambda request: httpx.Response(401, json={"detail": "Unauthorized"}),
                "401.*Unauthorized",
            ),
            (
                lambda request: httpx.Response(500, text="Provider unavailable"),
                "500.*Provider unavailable",
            ),
            (lambda request: httpx.Response(201, content=b"invalid"), "invalid JSON"),
            (network_error, "request failed.*offline"),
        )
        for handler, message in cases:
            with self.subTest(message=message):
                self.transport(handler)
                before = len(self.requests)
                with self.assertRaisesRegex(RuntimeError, message):
                    api.text_to_video("A river")
                self.assertEqual(len(self.requests) - before, 1)

    def test_live_submit_requires_configured_api_key(self) -> None:
        self.transport()
        with patch.dict(os.environ, {"LUMA_API_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "LUMA_API_KEY"):
                api.text_to_video("A river")
        self.assertEqual(self.requests, [])

    def test_catalog_is_static_has_draft_tier_and_no_flash_model(self) -> None:
        with patch.object(api.httpx, "Client", side_effect=AssertionError("HTTP access")):
            catalog = api.list_luma_models()
        self.assertEqual([model["id"] for model in catalog["models"]], ["ray-3.2"])
        self.assertEqual(catalog["docs_verified_date"], "2026-10-08")
        self.assertEqual(catalog["models"][0]["draft_resolution"], "360p")
        self.assertIn("no separate Flash", catalog["note"])


if __name__ == "__main__":
    unittest.main()
