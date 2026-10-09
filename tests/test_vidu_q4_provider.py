"""Offline contracts and billing checks for Vidu Q4. No provider HTTP traffic."""

from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from providers.catalog import get_provider
from providers.contracts import validate_tool_arguments
from providers.fal import api, queue, wan
from providers.registry import dispatch, generate_schemas
from server import billing_rates


I2V = "fal-ai/vidu/q4/image-to-video"
R2V = "fal-ai/vidu/q4/reference-to-video"
IMAGE = "https://media.example.test/product.png"
VOICE = "https://media.example.test/voice.mp3"
VIDEO = "https://media.example.test/result.mp4"
PROMO = {"540p": "3.15", "720p": "6.65", "1080p": "8.4", "2K": "13.3", "4K": "27.3"}
LIST = {"540p": "4.5", "720p": "9.5", "1080p": "12", "2K": "19", "4K": "39"}


class ViduProviderTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"FAL_DRY_RUN": "true"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        no_network = patch.object(
            queue, "request", side_effect=AssertionError("Provider HTTP called")
        )
        no_network.start()
        self.addCleanup(no_network.stop)

    def contracts(self):
        return importlib.import_module("providers.fal.vidu")

    def schemas(self):
        return {tool["name"]: tool for tool in generate_schemas(get_provider("fal"))}

    def assert_q4_metadata(self, output, endpoint):
        self.assertEqual(output["model"], endpoint)
        self.assertEqual(output["endpoint_id"], endpoint)
        self.assertIs(output["training_eligible"], False)
        self.assertEqual(output["weights_license"], "review-required")

    def test_fixed_endpoints_and_native_gateway_fields(self):
        self.assertEqual(self.contracts().TOOL_ENDPOINTS, {"vidu_q4_i2v": I2V, "vidu_q4_r2v": R2V})
        schemas = self.schemas()
        expected = {
            "vidu_q4_i2v": {
                "image_url",
                "prompt",
                "duration",
                "seed",
                "resolution",
                "enable_safety_checker",
            },
            "vidu_q4_r2v": {
                "prompt",
                "reference_image_urls",
                "reference_audio_urls",
                "duration",
                "seed",
                "aspect_ratio",
                "resolution",
                "audio",
                "enable_safety_checker",
            },
        }
        for tool, fields in expected.items():
            with self.subTest(tool=tool):
                schema = schemas[tool]["inputSchema"]
                self.assertEqual(set(schema["properties"]), fields)
                self.assertEqual(
                    schema["required"], ["image_url"] if tool.endswith("i2v") else ["prompt"]
                )
                self.assertEqual(schema["properties"]["duration"]["type"], "integer")
                self.assertIn("3 to 16", schema["properties"]["duration"]["description"])
                self.assertIn("4K", schema["properties"]["resolution"]["description"])
        for field in ("reference_image_urls", "reference_audio_urls"):
            self.assertEqual(
                schemas["vidu_q4_r2v"]["inputSchema"]["properties"][field]["items"]["type"],
                "string",
            )

    def test_native_payload_preserves_only_official_fields(self):
        contracts = self.contracts()
        for tool, expected_id, arguments in (
            (
                "vidu_q4_i2v",
                I2V,
                {
                    "image_url": IMAGE,
                    "prompt": "",
                    "duration": 16,
                    "resolution": "4K",
                    "seed": -42,
                    "enable_safety_checker": True,
                },
            ),
            (
                "vidu_q4_r2v",
                R2V,
                {
                    "prompt": "[@reference_image_1] speaks in [reference_audio_1]",
                    "reference_image_urls": [IMAGE],
                    "reference_audio_urls": [VOICE],
                    "duration": 3,
                    "resolution": "2K",
                    "aspect_ratio": "3:4",
                    "audio": True,
                    "seed": -42,
                    "enable_safety_checker": True,
                },
            ),
        ):
            with self.subTest(tool=tool):
                endpoint, body = contracts.request_body(tool, {**arguments, "unused": None})
                self.assertEqual(endpoint.id, expected_id)
                self.assertEqual(body, arguments)
                self.assertNotIn("model", body)
                self.assertNotIn("match_input_num_frames", body)

    def test_native_defaults_and_optional_references(self):
        contracts = self.contracts()
        _, image_body = contracts.request_body("vidu_q4_i2v", {"image_url": IMAGE})
        self.assertEqual(
            image_body,
            {
                "image_url": IMAGE,
                "prompt": "",
                "duration": 5,
                "resolution": "720p",
                "enable_safety_checker": True,
            },
        )
        _, ref_body = contracts.request_body("vidu_q4_r2v", {"prompt": "A person speaks"})
        self.assertEqual(
            ref_body,
            {
                "prompt": "A person speaks",
                "duration": 5,
                "resolution": "720p",
                "aspect_ratio": "16:9",
                "audio": False,
                "enable_safety_checker": True,
            },
        )
        for references in ({}, {"reference_image_urls": [], "reference_audio_urls": []}):
            self.assertEqual(
                dispatch("fal", "vidu_q4_r2v", {"prompt": "A scene", **references})["status"],
                "dry_run",
            )

    def test_default_dry_run_submit_and_poll_use_fixed_model_metadata(self):
        os.environ.pop("FAL_DRY_RUN")
        self.assertEqual(get_provider("fal").default_env["FAL_DRY_RUN"], "true")
        for tool, endpoint, args in (
            ("vidu_q4_i2v", I2V, {"image_url": IMAGE}),
            ("vidu_q4_r2v", R2V, {"prompt": "A scene"}),
        ):
            with self.subTest(tool=tool):
                output = dispatch("fal", tool, args)
                self.assertEqual(output["status"], "dry_run")
                self.assertEqual(output["mode"], tool)
                self.assertTrue(output["job_id"].startswith(endpoint + ":dry_"))
                self.assert_q4_metadata(output, endpoint)
                polled = api.get_video_task(output["job_id"], download=True)
                self.assertEqual(polled["status"], "dry_run")
                self.assert_q4_metadata(polled, endpoint)
                self.assertNotIn(IMAGE, json.dumps(output))

    def test_queue_handles_use_the_existing_app_root_and_reject_unknown_variants(self):
        for endpoint in (I2V, R2V):
            handle = endpoint + ":request_1"
            self.assertEqual(api._parse_job(handle), (endpoint, "request_1"))
            self.assertEqual(
                queue.request_url(endpoint, "request_1"),
                "https://queue.fal.run/fal-ai/vidu/requests/request_1",
            )
        for handle in (
            I2V + ":../escape",
            I2V + "/unknown:request_1",
            "fal-ai/vidu/q4:request_1",
            R2V + ":",
        ):
            with self.subTest(handle=handle), self.assertRaises(ValueError):
                api.get_video_task(handle)

    def test_shared_contract_validates_duration_prompt_lists_and_native_names(self):
        schemas = self.schemas()
        cases = [
            ("vidu_q4_i2v", {}, "image_url"),
            ("vidu_q4_i2v", {"image_url": IMAGE, "audio": True}, "audio"),
            ("vidu_q4_i2v", {"image_url": IMAGE, "generate_audio": True}, "generate_audio"),
            ("vidu_q4_i2v", {"image_url": IMAGE, "model": I2V}, "model"),
            ("vidu_q4_i2v", {"first_frame_url": IMAGE}, "first_frame_url"),
            ("vidu_q4_i2v", {"image_url": IMAGE, "prompt": "p" * 5001}, "prompt"),
            ("vidu_q4_i2v", {"image_url": "file:///tmp/image.png"}, "image_url"),
            ("vidu_q4_r2v", {"prompt": ""}, "prompt"),
            ("vidu_q4_r2v", {"prompt": "p" * 5001}, "prompt"),
            (
                "vidu_q4_r2v",
                {"prompt": "p", "reference_image_urls": [IMAGE] * 13},
                "reference_image_urls",
            ),
            (
                "vidu_q4_r2v",
                {"prompt": "p", "reference_audio_urls": [VOICE] * 4},
                "reference_audio_urls",
            ),
            ("vidu_q4_r2v", {"prompt": "p", "reference_audio_urls": [4]}, "reference_audio_urls"),
            (
                "vidu_q4_r2v",
                {"prompt": "p", "reference_image_urls": "not a list"},
                "reference_image_urls",
            ),
            (
                "vidu_q4_r2v",
                {"prompt": "p", "reference_audio_urls": ["file:///tmp/a.mp3"]},
                "reference_audio_urls",
            ),
            ("vidu_q4_r2v", {"prompt": "p", "audio": "true"}, "audio"),
            ("vidu_q4_r2v", {"prompt": "p", "aspect_ratio": "21:9"}, "aspect_ratio"),
        ]
        for duration in (True, 2, 17, 5.0, "5"):
            cases.append(("vidu_q4_i2v", {"image_url": IMAGE, "duration": duration}, "duration"))
        for resolution in ("580p", "4k", 720):
            cases.append(
                ("vidu_q4_i2v", {"image_url": IMAGE, "resolution": resolution}, "resolution")
            )
        for tool, arguments, field in cases:
            with (
                self.subTest(tool=tool, field=field, value=arguments),
                self.assertRaisesRegex(ValueError, field),
            ):
                validate_tool_arguments("fal", tool, arguments, schemas[tool]["inputSchema"])

    def test_documented_boundaries_and_unrestricted_integer_seed(self):
        for duration in (3, 16):
            for resolution in PROMO:
                for seed in (-1, 2**100):
                    result = api.vidu_q4_i2v(
                        IMAGE,
                        prompt="p" * 5000,
                        duration=duration,
                        resolution=resolution,
                        seed=seed,
                    )
                    self.assertEqual(result["status"], "dry_run")
        for ratio in ("16:9", "9:16", "4:3", "3:4", "1:1"):
            result = api.vidu_q4_r2v(
                "p" * 5000,
                reference_image_urls=[IMAGE] * 12,
                reference_audio_urls=[VOICE] * 3,
                aspect_ratio=ratio,
                audio=True,
            )
            self.assertEqual(result["status"], "dry_run")
        self.assertEqual(api.vidu_q4_i2v("data:image/webp;base64,AA")["status"], "dry_run")
        self.assertEqual(api.vidu_q4_r2v(" ")["status"], "dry_run")

    def test_static_catalog_has_q4_service_terms_and_time_bound_price(self):
        catalog = api.list_fal_models()
        models = {row["id"]: row for row in catalog["models"]}
        endpoints = {row["id"]: row for row in catalog["endpoints"]}
        for endpoint in (I2V, R2V):
            with self.subTest(endpoint=endpoint):
                self.assertIs(models[endpoint]["training_eligible"], False)
                self.assertEqual(models[endpoint]["weights_license"], "review-required")
                row = endpoints[endpoint]
                self.assert_q4_metadata(row, endpoint)
                self.assertEqual(row["price_unit"], "video_second")
                self.assertEqual(row["pricing_checked_at"], "2026-10-08")
                self.assertEqual(row["pricing_url"], "https://fal.ai/models/" + endpoint)
                self.assertEqual(row["promo_expires_on"], "2026-11-30")
                self.assertEqual(
                    row["usd_per_unit_by_resolution"],
                    {r: str(v / 100) for r, v in billing_rates.vidu_q4_rates().items()},
                )
                self.assertEqual(
                    row["list_usd_per_unit_by_resolution"],
                    {r: str(Decimal(v) / 100) for r, v in LIST.items()},
                )
        self.assertIs(models[wan.DEFAULT_MODEL]["training_eligible"], True)
        self.assertEqual(models[wan.DEFAULT_MODEL]["weights_license"], "Apache-2.0")

    def test_poll_boundary_preserves_q4_metadata_on_queued_failed_and_successful_jobs(self):
        with (
            tempfile.TemporaryDirectory(prefix="vidu-poll-") as directory,
            patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": directory}),
        ):
            for endpoint in (I2V, R2V):
                for payload, expected in (
                    ({"status": "IN_QUEUE", "queue_position": 2}, "queued"),
                    ({"status": "IN_PROGRESS"}, "running"),
                    ({"status": "COMPLETED", "error": "generation failed"}, "failed"),
                ):
                    with (
                        self.subTest(endpoint=endpoint, expected=expected),
                        patch.object(queue, "status", return_value=payload),
                        patch.object(queue, "result") as result,
                    ):
                        output = api._poll_video_task(
                            endpoint + ":request_1", endpoint, "request_1", download=False
                        )
                        self.assertEqual(output["status"], expected)
                        self.assert_q4_metadata(output, endpoint)
                        result.assert_not_called()
                with (
                    patch.object(queue, "status", return_value={"status": "COMPLETED"}),
                    patch.object(
                        queue, "result", return_value={"video": {"url": VIDEO}, "seed": 7}
                    ),
                ):
                    output = api._poll_video_task(
                        endpoint + ":request_1", endpoint, "request_1", download=False
                    )
                    self.assertEqual(output["status"], "succeeded")
                    self.assertEqual(output["video_url"], VIDEO)
                    self.assertEqual(output["seed"], 7)
                    self.assert_q4_metadata(output, endpoint)
                    self.assertIsNone(output["output_path"])
                    metadata = list(Path(directory).rglob("*.json"))
                    self.assertTrue(metadata)
                    self.assertTrue(
                        all(
                            json.loads(p.read_text())["training_eligible"] is False
                            for p in metadata
                        )
                    )

    def test_poll_boundary_provider_validation_error_keeps_q4_licensing(self):
        for endpoint in (I2V, R2V):
            for result in (
                {"error": "unsafe input", "error_type": "validation"},
                queue.FalAPIError(422, "invalid input"),
            ):
                options = (
                    {"side_effect": result}
                    if isinstance(result, Exception)
                    else {"return_value": result}
                )
                with (
                    self.subTest(endpoint=endpoint, result=result),
                    patch.object(queue, "status", return_value={"status": "COMPLETED"}),
                    patch.object(queue, "result", **options),
                ):
                    output = api._poll_video_task(
                        endpoint + ":request_1", endpoint, "request_1", download=False
                    )
                    self.assertEqual(output["status"], "failed")
                    self.assert_q4_metadata(output, endpoint)

    def test_committed_schema_matches_q4_contracts(self):
        committed = json.loads(Path("configs/gateway/fal.tools.json").read_text())
        self.assertEqual(committed, generate_schemas(get_provider("fal")))
        self.assertTrue({"vidu_q4_i2v", "vidu_q4_r2v"}.issubset({row["name"] for row in committed}))


class ViduBillingTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"FAL_DRY_RUN": "true"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        no_network = patch.object(
            queue, "request", side_effect=AssertionError("Provider HTTP called")
        )
        no_network.start()
        self.addCleanup(no_network.stop)

    def test_promo_rates_before_and_on_cutoff_then_list_rates(self):
        for day, expected in (
            (date(2026, 10, 8), PROMO),
            (date(2026, 11, 29), PROMO),
            (date(2026, 11, 30), PROMO),
            (date(2026, 12, 1), LIST),
        ):
            with self.subTest(day=day):
                rates = billing_rates.vidu_q4_rates(as_of=day)
                self.assertEqual(rates, {r: Decimal(v) for r, v in expected.items()})
                self.assertTrue(all(isinstance(v, Decimal) for v in rates.values()))

    def test_rate_clock_uses_utc_date(self):
        with patch.object(billing_rates, "datetime") as clock:
            clock.now.return_value = datetime(2026, 12, 1, tzinfo=timezone.utc)
            self.assertEqual(
                billing_rates.vidu_q4_rates(), {r: Decimal(v) for r, v in LIST.items()}
            )
            clock.now.assert_called_once_with(timezone.utc)

    def test_price_uses_native_seconds_and_no_audio_surcharge_without_media(self):
        for day, expected in ((date(2026, 11, 30), PROMO), (date(2026, 12, 1), LIST)):
            for resolution, rate in expected.items():
                for audio in (False, True):
                    for duration in (3, 16):
                        with self.subTest(
                            day=day, resolution=resolution, audio=audio, duration=duration
                        ):
                            price = billing_rates.vidu_q4_price_cents(
                                {"duration": duration, "resolution": resolution, "audio": audio},
                                as_of=day,
                            )
                            self.assertEqual(price, Decimal(rate) * duration)
                            self.assertIsInstance(price, Decimal)
        self.assertEqual(
            billing_rates.vidu_q4_price_cents({}, as_of=date(2026, 10, 8)), Decimal("33.25")
        )

    def test_quotes_validate_types_and_published_limits(self):
        for arguments in (
            {"duration": True},
            {"duration": "5"},
            {"duration": 5.0},
            {"duration": 2},
            {"duration": 17},
            {"resolution": "4k"},
            {"resolution": 720},
            {"audio": "false"},
            {"audio": 1},
            {"model": "fal-ai/wan-vace-14b"},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                billing_rates.vidu_q4_price_cents(arguments)

    def test_cost_for_includes_fee_for_both_tools_and_all_resolutions(self):
        promo_expected = {
            "540p": (16, 5),
            "720p": (33, 10),
            "1080p": (42, 13),
            "2K": (66, 20),
            "4K": (136, 41),
        }
        list_expected = {
            "540p": (22, 7),
            "720p": (48, 14),
            "1080p": (60, 18),
            "2K": (95, 28),
            "4K": (195, 58),
        }
        for day, expected in (
            (date(2026, 11, 29), promo_expected),
            (date(2026, 11, 30), promo_expected),
            (date(2026, 12, 1), list_expected),
        ):
            with (
                patch.object(billing_rates, "datetime") as clock,
                patch.dict(os.environ, {"FAL_DRY_RUN": "false"}),
            ):
                clock.now.return_value = datetime.combine(
                    day, datetime.min.time(), tzinfo=timezone.utc
                )
                for tool, model, args in (
                    ("vidu_q4_i2v", I2V, {"image_url": IMAGE}),
                    ("vidu_q4_r2v", R2V, {"prompt": "A scene", "audio": True}),
                ):
                    for resolution, (provider, fee) in expected.items():
                        with self.subTest(day=day, tool=tool, resolution=resolution):
                            quote = billing_rates.cost_for(
                                "fal",
                                tool,
                                {**args, "duration": 5, "resolution": resolution, "model": model},
                            )
                            self.assertEqual(
                                quote.public(),
                                {
                                    "provider_cents": provider,
                                    "fee_cents": fee,
                                    "total_cents": provider + fee,
                                },
                            )

    def test_dry_run_actual_charge_and_read_quotes_stay_zero(self):
        for tool, args in (
            ("vidu_q4_i2v", {"image_url": IMAGE}),
            ("vidu_q4_r2v", {"prompt": "A scene"}),
            ("get_video_task", {}),
            ("list_fal_models", {}),
        ):
            with self.subTest(tool=tool):
                self.assertEqual(
                    billing_rates.cost_for("fal", tool, args).public(),
                    {"provider_cents": 0, "fee_cents": 0, "total_cents": 0},
                )

    def test_cost_for_rejects_wrong_fixed_model_and_invalid_provider_fields(self):
        for args in (
            {"image_url": IMAGE, "model": R2V},
            {"image_url": IMAGE, "duration": 17},
            {"image_url": IMAGE, "audio": True},
            {"duration": 5},
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                billing_rates.cost_for("fal", "vidu_q4_i2v", args)


if __name__ == "__main__":
    unittest.main()
