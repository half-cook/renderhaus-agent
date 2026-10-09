from __future__ import annotations

import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

from providers.catalog import get_provider
from providers.registry import dispatch, generate_schemas
from providers.seedance import api
from providers.fal import api as fal_api
from server import billing_rates


class Seedance25ProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {
            "SEEDANCE_DRY_RUN": "true", "FAL_DRY_RUN": "true",
            "RENDERHAUS_MEDIA_DIR": self.temp.name, "RENDERHAUS_SECRETS_NAME": "",
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_default_is_us_fal_seedance25_with_preview(self) -> None:
        with patch("providers.fal.queue.submit") as submit:
            result = api.text_to_video("A synthetic robot says hello", duration_seconds=30)
        self.assertEqual(result["model"], "bytedance/seedance-2.5/us/text-to-video")
        self.assertEqual(result["request_preview"]["duration"], "30")
        self.assertTrue(result["request_preview"]["generate_audio"])
        self.assertFalse(result["training_eligible"])
        submit.assert_not_called()

    def test_contract_rejects_invalid_duration_instead_of_clamping(self) -> None:
        for duration in (3, 31, True):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                api.text_to_video("robot", duration_seconds=duration)

    def test_registry_and_direct_handlers_have_same_guard(self) -> None:
        for arguments in ({"duration_seconds": 31}, {"service_tier": "flex"}):
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    api.text_to_video("robot", **arguments)
                with self.assertRaises(ValueError):
                    dispatch("seedance", "text_to_video", {"prompt": "robot", **arguments})

    def test_real_person_inputs_never_reach_transport(self) -> None:
        for flag in ("real_face_refs", "user_supplied_real_person_refs"):
            with self.subTest(flag=flag), patch("providers.fal.queue.submit") as submit:
                with self.assertRaisesRegex(ValueError, "real.person|real.face|Real.person"):
                    api.image_to_video("https://example.test/person.png", "talk", **{flag: True})
                submit.assert_not_called()

    def test_real_person_guard_applies_to_reference_edit_and_extend(self) -> None:
        for tool, arguments in (
            ("reference_to_video", {"reference_image_urls": ["https://example.test/a.png"]}),
            ("edit_video", {"video_url": "https://example.test/a.mp4", "source_duration_seconds": 5, "source_fps": 24}),
            ("extend_video", {"video_url": "https://example.test/a.mp4", "source_duration_seconds": 5, "source_fps": 24}),
        ):
            with self.subTest(tool=tool), self.assertRaisesRegex(ValueError, "real.person|real.face|Real.person"):
                dispatch("seedance", tool, {"prompt": "robot", "real_face_refs": True, **arguments})

    def test_fal_dry_run_flag_also_gates_submission(self) -> None:
        with patch.dict(os.environ, {"SEEDANCE_DRY_RUN": "false"}), patch("providers.fal.queue.submit") as submit:
            result = api.text_to_video("robot")
        self.assertEqual(result["status"], "dry_run")
        submit.assert_not_called()

    def test_dry_handle_stays_dry_when_flags_are_disabled(self) -> None:
        result = api.text_to_video("robot")
        with patch.dict(os.environ, {"SEEDANCE_DRY_RUN": "false", "FAL_DRY_RUN": "false"}), patch("providers.fal.queue.status") as status:
            polled = fal_api.get_video_task(result["job_id"])
            wrapper = api.get_video_task(result["job_id"])
        self.assertEqual(polled["status"], "dry_run")
        self.assertEqual(wrapper["status"], "dry_run")
        status.assert_not_called()

    def test_reference_measurements_are_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "duration|measured"):
            dispatch("seedance", "reference_to_video", {"prompt": "robot", "reference_video_urls": ["https://example.test/a.mp4"]})

    def test_reference_measurements_are_local_and_video_task_is_explicit(self) -> None:
        result = dispatch("seedance", "reference_to_video", {
            "prompt": "robot", "reference_video_urls": ["https://example.test/a.mp4"],
            "reference_video_durations": [5.0], "reference_video_fps": [24.0],
        })
        body = result["request_preview"]
        self.assertEqual(body["video_urls"], ["https://example.test/a.mp4"])
        self.assertNotIn("reference_video_durations", body)
        self.assertNotIn("reference_video_fps", body)
        self.assertNotIn("real_face_refs", body)
        self.assertNotIn("watermark", body)

    def test_reference_budgets_and_fps_are_validated_before_submit(self) -> None:
        base = {"prompt": "robot", "reference_video_urls": ["https://example.test/a.mp4"], "reference_video_durations": [5.0], "reference_video_fps": [24.0]}
        bad = (
            {"reference_video_durations": [1.7]}, {"reference_video_durations": [30.3]},
            {"reference_video_fps": [23.0]}, {"reference_video_fps": [61.0]},
            {"reference_image_urls": ["https://example.test/a.png"] * 31},
        )
        for update in bad:
            with self.subTest(update=update), self.assertRaises(ValueError):
                dispatch("seedance", "reference_to_video", {**base, **update})

    def test_byteplus_15_remains_selectable_and_bounded(self) -> None:
        with patch.dict(os.environ, {"SEEDANCE_TRANSPORT": "byteplus"}):
            result = api.text_to_video("robot", model="seedance-1-5-pro-251215", duration_seconds=12)
            self.assertEqual(result["model"], "seedance-1-5-pro-251215")
            self.assertTrue(result["request_preview"]["watermark"])
            with self.assertRaises(ValueError):
                api.text_to_video("robot", model="seedance-1-5-pro-251215", duration_seconds=13)
        with self.assertRaisesRegex(ValueError, "BytePlus|byteplus"):
            api.text_to_video("robot", model="seedance-1-5-pro-251215")

    def test_byteplus25_omits_service_tier(self) -> None:
        with patch.dict(os.environ, {"SEEDANCE_TRANSPORT": "byteplus"}):
            result = api.text_to_video("robot", duration_seconds=30)
        self.assertEqual(result["model"], "dreamina-seedance-2-5-260628")
        self.assertTrue(result["request_preview"]["watermark"])
        self.assertNotIn("service_tier", result["request_preview"])

    def test_global_fal_region_and_end_frame(self) -> None:
        with patch.dict(os.environ, {"SEEDANCE_FAL_REGION": "global"}):
            result = api.image_to_video("https://example.test/start.png", "robot", end_image_path_or_url="https://example.test/end.png")
        self.assertEqual(result["model"], "bytedance/seedance-2.5/image-to-video")
        self.assertEqual(result["request_preview"]["image_url"], "https://example.test/start.png")
        self.assertEqual(result["request_preview"]["end_image_url"], "https://example.test/end.png")

    def test_catalog_propagates_transport_credentials_and_defaults(self) -> None:
        spec = get_provider("seedance")
        self.assertEqual(spec.default_env["SEEDANCE_TRANSPORT"], "fal")
        self.assertEqual(spec.default_env["SEEDANCE_FAL_REGION"], "us")
        self.assertIn("FAL_KEY", spec.env_keys)
        self.assertIn("FAL_DRY_RUN", spec.env_keys)
        self.assertEqual(len(generate_schemas(spec)), 7)

    def test_seedance_prices_follow_fal_token_formula(self) -> None:
        cents = billing_rates.seedance_price_cents("text_to_video", {"duration_seconds": 5, "resolution": "720p", "aspect_ratio": "16:9"})
        expected = Decimal(1280 * 720 * 24 * 5) / Decimal(1024) / Decimal(1000) * Decimal("2.568")
        self.assertEqual(cents, expected)

    def test_seedance_video_reference_price_counts_input_and_discount(self) -> None:
        arguments = {"duration_seconds": 5, "resolution": "720p", "aspect_ratio": "16:9", "reference_video_urls": ["https://example.test/a.mp4"], "reference_video_durations": [5.0]}
        cents = billing_rates.seedance_price_cents("reference_to_video", arguments)
        expected = Decimal(1280 * 720 * 24 * 10) / Decimal(1024) / Decimal(1000) * Decimal("2.568") * Decimal("0.6")
        self.assertEqual(cents, expected)

    def test_dry_generation_is_free_but_receipt_discloses_estimate(self) -> None:
        result = api.text_to_video("robot")
        self.assertGreater(result["estimated_cost_usd"], 0)
        self.assertEqual(billing_rates.cost_for("seedance", "text_to_video", {"prompt": "robot"}).provider_cents, 0)


    def test_fal_wire_submission_and_shared_poll_download(self) -> None:
        with patch.dict(os.environ, {"SEEDANCE_DRY_RUN": "false", "FAL_DRY_RUN": "false"}), patch("providers.fal.queue.submit", return_value={"request_id": "fake-job", "status": "IN_QUEUE"}) as submit:
            result = dispatch("seedance", "text_to_video", {"prompt": "robot"})
        self.assertEqual(result["status"], "queued")
        endpoint, body = submit.call_args.args
        self.assertEqual(endpoint, "bytedance/seedance-2.5/us/text-to-video")
        self.assertEqual(body, {"prompt": "robot", "resolution": "720p", "duration": "5", "aspect_ratio": "16:9", "generate_audio": True})
        stream = MagicMock()
        stream.__enter__.return_value.iter_bytes.return_value = [b"fake-mp4-bytes"]
        with patch.dict(os.environ, {"SEEDANCE_DRY_RUN": "false", "FAL_DRY_RUN": "false"}), patch("providers.fal.queue.status", return_value={"status": "COMPLETED"}), patch("providers.fal.queue.result", return_value={"video": {"url": "https://example.test/video.mp4"}, "seed": 7}), patch("providers.fal.api.httpx.stream", return_value=stream):
            polled = api.get_video_task(result["job_id"], download=True)
        self.assertEqual(polled["status"], "succeeded")
        self.assertFalse(polled["training_eligible"])
        self.assertEqual(Path(polled["output_path"]).read_bytes(), b"fake-mp4-bytes")

    def test_fal_poll_seedance_flag_gates_nondry_handle(self) -> None:
        with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}), patch("providers.fal.queue.status") as status:
            result = fal_api.get_video_task("bytedance/seedance-2.5/us/text-to-video:fake-job")
        self.assertEqual(result["status"], "dry_run")
        status.assert_not_called()

    def test_queue_failed_result_is_observable(self) -> None:
        with patch.dict(os.environ, {"SEEDANCE_DRY_RUN": "false", "FAL_DRY_RUN": "false"}), patch("providers.fal.queue.status", return_value={"status": "COMPLETED"}), patch("providers.fal.queue.result", return_value={"error": "policy blocked"}):
            result = api.get_video_task("bytedance/seedance-2.5/us/reference-to-video:fake-job")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "policy blocked")

    def test_edit_and_extension_use_verified_tasks(self) -> None:
        arguments = {"video_url": "https://example.test/a.mp4", "prompt": "robot", "source_duration_seconds": 5, "source_fps": 24, "source_aspect_ratio": "16:9"}
        edited = api.edit_video(**arguments)
        extended = api.extend_video(**arguments, duration_seconds=6)
        self.assertEqual(edited["request_preview"]["task"], "editing")
        self.assertEqual(edited["request_preview"]["duration"], "auto")
        self.assertEqual(extended["request_preview"]["task"], "extension")
        self.assertEqual(extended["request_preview"]["duration"], "6")
        self.assertEqual(edited["request_preview"]["video_urls"], [arguments["video_url"]])
        self.assertEqual(extended["request_preview"]["aspect_ratio"], "auto")
        self.assertGreater(extended["estimated_cost_usd"], edited["estimated_cost_usd"])

    def test_source_aspect_ratio_needed_for_automatic_output_cost(self) -> None:
        for tool, arguments in (
            ("image_to_video", {"image_path_or_url": "https://example.test/a.png", "prompt": "robot"}),
            ("edit_video", {"video_url": "https://example.test/a.mp4", "prompt": "robot", "source_duration_seconds": 5, "source_fps": 24}),
        ):
            with self.subTest(tool=tool):
                dry = dispatch("seedance", tool, arguments)
                self.assertEqual(dry["cost_estimate"], "unknown")
                with patch.dict(os.environ, {"SEEDANCE_DRY_RUN": "false", "FAL_DRY_RUN": "false"}), patch("providers.fal.queue.submit") as submit, self.assertRaisesRegex(ValueError, "unknown"):
                    dispatch("seedance", tool, arguments)
                submit.assert_not_called()

    def test_byteplus_key_priority_with_synthetic_environment_only(self) -> None:
        with patch.dict(os.environ, {"BYTEPLUS_API_KEY": "test-primary", "ARK_API_KEY": "test-alias"}):
            self.assertEqual(api._api_key(), "test-primary")
        with patch.dict(os.environ, {"ARK_API_KEY": "test-alias"}):
            self.assertEqual(api._api_key(), "test-alias")

    def test_byteplus_unauthorized_integration_is_blocked_before_http(self) -> None:
        with patch.dict(os.environ, {"SEEDANCE_TRANSPORT": "byteplus", "SEEDANCE_DRY_RUN": "false", "RENDERHAUS_CUSTOMER_REGION": "CA"}), patch("providers.seedance.api.httpx.Client") as client, self.assertRaisesRegex(ValueError, "written platform authorization"):
            api.text_to_video("robot")
        client.assert_not_called()

    def test_authorized_byteplus_wire_request_and_poll(self) -> None:
        created_response = httpx.Response(200, json={"id": "byteplus-fake-job"})
        polled_response = httpx.Response(200, json={"status": "succeeded", "model": "dreamina-seedance-2-5-260628", "content": {"video_url": "https://example.test/video.mp4"}, "usage": {"completion_tokens": 1000}})
        fake_client = MagicMock()
        fake_client.__enter__.return_value.post.return_value = created_response
        fake_client.__enter__.return_value.get.return_value = polled_response
        settings = {"SEEDANCE_TRANSPORT": "byteplus", "SEEDANCE_DRY_RUN": "false", "SEEDANCE_BYTEPLUS_PLATFORM_AUTHORIZED": "true", "RENDERHAUS_CUSTOMER_REGION": "CA"}
        with patch.dict(os.environ, settings), patch("providers.seedance.api._headers", return_value={"Authorization": "Bearer test-only"}), patch("providers.seedance.api.httpx.Client", return_value=fake_client):
            created = api.text_to_video("robot", service_tier="default")
            polled = api.get_video_task(created["job_id"])
        body = fake_client.__enter__.return_value.post.call_args.kwargs["json"]
        self.assertEqual(body["model"], "dreamina-seedance-2-5-260628")
        self.assertTrue(body["watermark"])
        self.assertEqual(body["duration"], 5)
        self.assertEqual(body["service_tier"], "default")
        self.assertEqual(polled["status"], "succeeded")
        self.assertEqual(polled["usage"]["completion_tokens"], 1000)

    def test_byteplus_video_input_floor_unknown_and_live_blocked(self) -> None:
        settings = {"SEEDANCE_TRANSPORT": "byteplus", "SEEDANCE_BYTEPLUS_PLATFORM_AUTHORIZED": "true", "RENDERHAUS_CUSTOMER_REGION": "CA"}
        arguments = {"prompt": "robot", "reference_video_urls": ["https://example.test/a.mp4"], "reference_video_durations": [5.0], "reference_video_fps": [24.0]}
        with patch.dict(os.environ, settings):
            result = api.reference_to_video(**arguments)
            self.assertEqual(result["cost_estimate"], "unknown")
            with self.assertRaisesRegex(ValueError, "UNVERIFIED.*floor"):
                billing_rates.seedance_price_cents("reference_to_video", arguments)
            with patch.dict(os.environ, {"SEEDANCE_DRY_RUN": "false"}), patch("providers.seedance.api.httpx.Client") as client, self.assertRaisesRegex(ValueError, "UNVERIFIED.*floor"):
                api.reference_to_video(**arguments)
            client.assert_not_called()

    def test_unknown_model_stays_dry_without_transport_calls(self) -> None:
        with patch.dict(os.environ, {"SEEDANCE_MODEL": "bytedance/seedance-future/text-to-video", "SEEDANCE_DRY_RUN": "false", "FAL_DRY_RUN": "false"}), patch("providers.fal.queue.submit") as submit:
            result = api.text_to_video("robot")
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["verification_status"], "UNVERIFIED")
        self.assertEqual(result["cost_estimate"], "unknown")
        submit.assert_not_called()

    def test_null_required_scalars_are_rejected_before_transport(self) -> None:
        for field in ("duration_seconds", "generate_audio", "watermark", "aspect_ratio"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "cannot be null"):
                dispatch("seedance", "text_to_video", {"prompt": "robot", field: None})

    def test_model_endpoint_override_uses_actual_region_price(self) -> None:
        arguments = {"model": "bytedance/seedance-2.5/text-to-video", "duration_seconds": 5}
        cost = billing_rates.seedance_price_cents("text_to_video", arguments)
        expected = Decimal(1280 * 720 * 24 * 5) / Decimal(1024) / Decimal(1000) * Decimal("2.14")
        self.assertEqual(cost, expected)

    def test_live_integer_cents_round_up_and_poll_catalog_are_free(self) -> None:
        with patch.dict(os.environ, {"SEEDANCE_DRY_RUN": "false", "FAL_DRY_RUN": "false"}):
            cost = billing_rates.cost_for("seedance", "text_to_video", {"prompt": "robot"})
            self.assertEqual(cost.provider_cents, 278)
            self.assertEqual(billing_rates.cost_for("seedance", "get_video_task", {"job_id": "unused"}).total_cents, 0)
            self.assertEqual(billing_rates.cost_for("seedance", "list_seedance_models", {}).total_cents, 0)

    def test_byteplus_us_customers_blocked_even_with_authorization(self) -> None:
        settings = {"SEEDANCE_TRANSPORT": "byteplus", "SEEDANCE_DRY_RUN": "false", "SEEDANCE_BYTEPLUS_PLATFORM_AUTHORIZED": "true", "RENDERHAUS_CUSTOMER_REGION": "US"}
        with patch.dict(os.environ, settings), patch("providers.seedance.api.httpx.Client") as client, self.assertRaisesRegex(ValueError, "US customers"):
            api.text_to_video("robot")
        client.assert_not_called()

    def test_byteplus_requires_customer_region_for_live_calls(self) -> None:
        settings = {"SEEDANCE_TRANSPORT": "byteplus", "SEEDANCE_DRY_RUN": "false", "SEEDANCE_BYTEPLUS_PLATFORM_AUTHORIZED": "true"}
        with patch.dict(os.environ, settings), patch("providers.seedance.api.httpx.Client") as client, self.assertRaisesRegex(ValueError, "customer region"):
            api.text_to_video("robot")
        client.assert_not_called()

    def test_extension_accepts_documented_two_second_source(self) -> None:
        result = api.extend_video("https://example.test/source.mp4", "continue robot", source_duration_seconds=2, source_fps=24, source_aspect_ratio="16:9")
        self.assertEqual(result["status"], "dry_run")
        self.assertGreater(result["estimated_cost_usd"], 0)

    def test_source_aspect_invalid_or_nonfinite_is_rejected(self) -> None:
        for value in ("adaptive", "0:1", "nan:1", "999:1"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "source_aspect_ratio"):
                api.image_to_video("https://example.test/a.png", "robot", source_aspect_ratio=value)

    def test_byteplus_reference_tolerances_follow_direct_docs(self) -> None:
        arguments = {"prompt": "robot", "reference_video_urls": ["https://example.test/a.mp4"], "reference_video_fps": [24]}
        with patch.dict(os.environ, {"SEEDANCE_TRANSPORT": "byteplus"}):
            for seconds in (1.8, 30.2):
                with self.subTest(seconds=seconds), self.assertRaisesRegex(ValueError, "2 to 30"):
                    api.reference_to_video(**arguments, reference_video_durations=[seconds])

    def test_exact_endpoint_override_cannot_bypass_25_service_tier_guard(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not support"):
            api.text_to_video("robot", model="bytedance/seedance-2.5/us/text-to-video", service_tier="flex")


if __name__ == "__main__":
    unittest.main()
