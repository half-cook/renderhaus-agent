from __future__ import annotations

import json
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import httpx


SOURCE = {
    "video_url": "https://media.example/source.mp4?signature=private",
    "source_duration_seconds": 10.0,
    "source_fps": 30.0,
    "source_width": 960,
    "source_height": 540,
}


class TopazContractTests(unittest.TestCase):
    def setUp(self):
        from providers.topaz import contracts

        self.contracts = contracts

    def test_default_upscale_serializes_only_official_fields(self):
        request = self.contracts.request_for("upscale_video", SOURCE)
        self.assertEqual(request.model, "Starlight Precise 2.6")
        self.assertEqual((request.output_width, request.output_height, request.output_fps), (1920, 1080, 30))
        self.assertEqual(request.output_duration, 10)
        self.assertEqual(request.fal_body(), {
            "video_url": SOURCE["video_url"], "upscale_factor": 2.0,
            "model": "Starlight Precise 2.6", "H264_output": True,
        })

    def test_target_resolution_preserves_portrait_aspect(self):
        source = {**SOURCE, "source_width": 1080, "source_height": 1920}
        request = self.contracts.request_for("upscale_video", {**source, "target_resolution": "4K"})
        self.assertEqual((request.output_width, request.output_height), (2160, 3840))
        self.assertEqual(request.fal_body()["upscale_factor"], 2)

    def test_target_resolution_ignores_float_roundoff_at_pixel_boundary(self):
        request = self.contracts.request_for("upscale_video", {
            **SOURCE, "source_width": 1064, "source_height": 1064, "target_resolution": "4K",
        })
        self.assertEqual((request.output_width, request.output_height), (2160, 2160))

    def test_optional_fal_upscale_fields_are_sent(self):
        request = self.contracts.request_for("upscale_video", {**SOURCE, "target_fps": 60, "softness": 1.5})
        self.assertEqual(request.output_fps, 60)
        self.assertEqual(request.fal_body()["target_fps"], 60)
        self.assertEqual(request.fal_body()["softness"], 1.5)

    def test_upscale_rejects_contradictory_or_oversized_output(self):
        for arguments in (
            {"upscale_factor": 3.0, "target_resolution": "1080p"},
            {"source_width": 3840, "source_height": 2160},
            {"source_width": 4096, "source_height": 2160, "upscale_factor": 1.0},
            {"source_width": 1000, "source_height": 1000, "upscale_factor": 4.0},
            {"target_resolution": "4K", "source_width": 320, "source_height": 180},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.contracts.request_for("upscale_video", {**SOURCE, **arguments})

    def test_boundary_contract_rejects_invalid_and_coerced_inputs(self):
        for arguments in (
            {"source_duration_seconds": 0.0}, {"source_duration_seconds": 300.1},
            {"source_duration_seconds": float("nan")}, {"source_fps": 0.0},
            {"source_width": True}, {"source_width": "960"}, {"source_height": 0},
            {"upscale_factor": 0.9}, {"upscale_factor": 4.1}, {"upscale_factor": "2"},
            {"target_fps": 61}, {"softness": 0.5}, {"H264_output": "true"},
            {"unknown_setting": True}, {"model": "Starlight Mini"},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.contracts.request_for("upscale_video", {**SOURCE, **arguments})

    def test_url_contract_rejects_local_and_credentialed_references(self):
        for url in (
            "http://media.example/a.mp4", "file:///tmp/a.mp4", "https://localhost/a.mp4",
            "https://127.0.0.1/a.mp4", "https://10.0.0.2/a.mp4", "https://[::1]/a.mp4",
            "https://user:password@media.example/a.mp4", "https://media.example/a.mp4#fragment",
            "https://media.example/a b.mp4", "renderhaus-asset://../../a",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.contracts.request_for("upscale_video", {**SOURCE, "video_url": url})

    def test_asset_handles_are_valid_preview_inputs(self):
        request = self.contracts.request_for("upscale_video", {**SOURCE, "video_url": "renderhaus-asset://asset_1"})
        self.assertEqual(request.video_url, "renderhaus-asset://asset_1")

    def test_apollo_default_and_chronos_direct_alias(self):
        default = self.contracts.request_for("interpolate_video", SOURCE)
        self.assertEqual(default.model, "Apollo")
        self.assertEqual(default.output_fps, 60)
        self.assertEqual(default.fal_body(), {
            "video_url": SOURCE["video_url"], "model": "Apollo", "target_fps": 60,
            "slowdown_factor": 1, "H264_output": True,
        })
        chronos = self.contracts.request_for("interpolate_video", {**SOURCE, "model": "chr-2"})
        self.assertEqual(chronos.model, "Chronos")
        self.assertEqual(self.contracts.configured_model("interpolate_video", {"model": "apo-8"}), "Apollo")
        self.assertEqual(self.contracts.configured_model("upscale_video", {"model": "slp-2.6"}), "Starlight Precise 2.6")

    def test_multiplier_and_slowdown_derive_fps_and_duration(self):
        request = self.contracts.request_for("interpolate_video", {**SOURCE, "fps_multiplier": 3.0, "slowdown_factor": 2})
        self.assertEqual(request.output_fps, 90)
        self.assertEqual(request.output_duration, 20)
        self.assertNotIn("fps_multiplier", request.fal_body())

    def test_interpolation_rejects_invalid_timing_or_oversized_input(self):
        for arguments in (
            {"target_fps": 60, "fps_multiplier": 2.0}, {"target_fps": 121},
            {"target_fps": 15}, {"fps_multiplier": 0.0}, {"fps_multiplier": 4.1},
            {"fps_multiplier": 1.01}, {"slowdown_factor": 9}, {"slowdown_factor": True},
            {"model": "Aion"}, {"source_width": 3841, "source_height": 2160},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.contracts.request_for("interpolate_video", {**SOURCE, **arguments})


class TopazAPITests(unittest.TestCase):
    def setUp(self):
        from providers.fal import api as fal_api
        from providers.topaz import api, contracts

        self.api, self.contracts, self.fal_api = api, contracts, fal_api
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": self.directory.name, "TOPAZ_DRY_RUN": "true", "FAL_DRY_RUN": "true"}).start()
        patch.dict(fal_api.ENDPOINT_CONTRACTS, {endpoint: contracts for endpoint in contracts.ENDPOINTS}).start()
        patch("server.billing_rates.topaz_price_cents", return_value=Decimal("120"), create=True).start()
        self.calls = []
        self.status_payload = {"status": "COMPLETED", "request_id": "req_123"}
        self.result_payload = {"video": {"url": "https://media.example/result.mp4?signature=output-private"}}
        client = httpx.Client

        def respond(request):
            self.calls.append(request)
            if request.method == "POST":
                return httpx.Response(200, json={"request_id": "req_123", "status": "IN_QUEUE"})
            if request.url.path.endswith("/status"):
                return httpx.Response(200, json=self.status_payload)
            return httpx.Response(200, json=self.result_payload)

        self.transport = httpx.MockTransport(respond)
        patch("providers.fal.queue.httpx.Client", side_effect=lambda **kw: client(transport=self.transport, **kw)).start()
        patch("providers.fal.queue.headers", return_value={"Content-Type": "application/json"}).start()

    def live(self):
        os.environ.update(TOPAZ_DRY_RUN="false", FAL_DRY_RUN="false")

    def test_dry_run_has_cost_preview_without_requests_or_artifacts(self):
        result = self.api.upscale_video(**SOURCE)
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["estimated_cost_usd"], 1.2)
        self.assertEqual(result["request_preview"]["H264_output"], True)
        self.assertEqual(result["capability_id"], "topaz_upscale")
        self.assertFalse(result["training_eligible"])
        self.assertEqual(self.calls, [])
        self.assertEqual(list(Path(self.directory.name).rglob("*.mp4")), [])

    def test_both_flags_must_be_false_to_submit(self):
        for topaz_flag, fal_flag in (("false", "true"), ("true", "false")):
            os.environ.update(TOPAZ_DRY_RUN=topaz_flag, FAL_DRY_RUN=fal_flag)
            self.assertEqual(self.api.upscale_video(**SOURCE)["status"], "dry_run")
        self.assertEqual(self.calls, [])

    def test_missing_dry_run_flags_default_to_safe_preview(self):
        os.environ.pop("TOPAZ_DRY_RUN")
        os.environ.pop("FAL_DRY_RUN")
        self.assertEqual(self.api.upscale_video(**SOURCE)["status"], "dry_run")
        self.assertEqual(self.calls, [])

    def test_validation_precedes_any_paid_request(self):
        self.live()
        with self.assertRaises(ValueError):
            self.api.upscale_video(**{**SOURCE, "source_duration_seconds": 0.0})
        self.assertEqual(self.calls, [])

    def test_unknown_cost_is_preview_only(self):
        with patch("server.billing_rates.topaz_price_cents", return_value=None):
            result = self.api.upscale_video(**SOURCE)
            self.assertIsNone(result["estimated_cost_usd"])
            self.assertIn("unknown", result["cost_estimate"])
            self.live()
            with self.assertRaisesRegex(ValueError, "unknown"):
                self.api.upscale_video(**SOURCE)
        self.assertEqual(self.calls, [])

    def test_asset_handles_cannot_be_sent_live(self):
        self.live()
        with self.assertRaisesRegex(ValueError, "resolve"):
            self.api.upscale_video(**{**SOURCE, "video_url": "renderhaus-asset://asset_1"})
        self.assertEqual(self.calls, [])

    def test_live_submission_uses_verified_endpoint_and_body(self):
        self.live()
        result = self.api.upscale_video(**SOURCE)
        self.assertEqual(result["job_id"], "topaz:upscale:req_123")
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["provider"], "topaz")
        self.assertEqual(str(self.calls[0].url), "https://queue.fal.run/topaz/upscale/video/generative")
        self.assertEqual(json.loads(self.calls[0].content), {
            "video_url": SOURCE["video_url"], "upscale_factor": 2.0,
            "model": "Starlight Precise 2.6", "H264_output": True,
        })
        for path in Path(self.directory.name).rglob("*.json"):
            self.assertNotIn("private", path.read_text())

    def test_chronos_identity_survives_metadata_loss(self):
        self.live()
        result = self.api.interpolate_video(**SOURCE, model="Chronos")
        self.assertEqual(result["job_id"], "topaz:chronos:req_123")
        for path in Path(self.directory.name).rglob("*.json"):
            path.unlink()
        polled = self.api.get_video_task(result["job_id"])
        self.assertEqual(polled["model"], "Chronos")
        self.assertEqual(polled["provider"], "topaz")
        self.assertEqual(polled["capability_id"], "topaz_interpolate")
        self.assertEqual(polled["status"], "succeeded")

    def test_apollo_submission_preserves_default_model(self):
        self.live()
        result = self.api.interpolate_video(**SOURCE)
        self.assertEqual(result["job_id"], "topaz:apollo:req_123")
        self.assertEqual(json.loads(self.calls[0].content)["model"], "Apollo")

    def test_dry_handles_never_become_live_when_flags_change(self):
        handle = self.api.interpolate_video(**SOURCE)["job_id"]
        self.live()
        result = self.api.get_video_task(handle, download=True)
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(self.calls, [])

    def test_poll_running_and_failed_never_resubmit(self):
        self.live()
        self.status_payload = {"status": "IN_PROGRESS", "request_id": "req_123"}
        self.assertEqual(self.api.get_video_task("topaz:apollo:req_123")["status"], "running")
        self.status_payload = {"status": "COMPLETED", "error": "processing failed"}
        self.assertEqual(self.api.get_video_task("topaz:apollo:req_123")["status"], "failed")
        self.assertTrue(all(request.method == "GET" for request in self.calls))

    def test_malformed_handles_are_rejected_without_network(self):
        self.live()
        for handle in ("topaz:other:req", "topaz:apollo:../../secret", "fal:apollo:req", "topaz:apollo:"):
            with self.subTest(handle=handle), self.assertRaises(ValueError):
                self.api.get_video_task(handle)
        self.assertEqual(self.calls, [])

    def test_signed_urls_are_absent_from_persisted_poll_metadata(self):
        self.live()
        self.api.get_video_task("topaz:upscale:req_123")
        for path in Path(self.directory.name).rglob("*.json"):
            self.assertNotIn("signature", path.read_text())
            self.assertNotIn("output-private", path.read_text())

    def test_invalid_download_is_rejected_and_deleted(self):
        self.live()
        with patch("providers.fal.api._download", side_effect=lambda url, path: path.write_bytes(b"not an MP4")):
            with self.assertRaisesRegex(RuntimeError, "MP4"):
                self.api.get_video_task("topaz:upscale:req_123", download=True)
        self.assertEqual(list(Path(self.directory.name).rglob("*.mp4")), [])

    def test_silent_video_container_is_accepted(self):
        self.live()

        def box(kind, body):
            return (len(body) + 8).to_bytes(4, "big") + kind + body

        data = box(b"ftyp", b"isom" + bytes(4) + b"isom")
        data += box(b"moov", box(b"trak", box(b"mdia", box(b"hdlr", bytes(8) + b"vide"))))
        data += box(b"mdat", b"encoded-video")
        with patch("providers.fal.api._download", side_effect=lambda url, path: path.write_bytes(data)), patch("providers.topaz.api.shutil.which", return_value=None):
            result = self.api.get_video_task("topaz:upscale:req_123", download=True)
        self.assertTrue(result["downloaded"])
        self.assertEqual(Path(result["output_path"]).read_bytes(), data)

    def test_model_listing_is_free_and_does_not_require_credentials(self):
        result = self.api.list_topaz_models()
        self.assertEqual({model["model"] for model in result["models"]}, {"Starlight Precise 2.6", "Apollo", "Chronos"})
        self.assertTrue(all(model["training_eligible"] is False for model in result["models"]))
        self.assertEqual({model["pricing_url"] for model in result["models"]}, {
            "https://fal.ai/models/topaz/upscale/video/generative",
            "https://fal.ai/models/topaz/interpolate/video",
        })
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
