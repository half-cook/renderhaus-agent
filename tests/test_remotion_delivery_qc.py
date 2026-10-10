from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


class DeliveryFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.job = self.root / "delivery-job"
        self.job.mkdir()
        env = patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": str(self.root),
            "REMOTION_RENDER_BACKEND": "local", "REMOTION_DRY_RUN": "false", "FFMPEG_DRY_RUN": "false"})
        env.start()
        self.addCleanup(env.stop)

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec("providers.remotion.delivery"),
                             "The final-file delivery and QC gate must exist")
        return importlib.import_module("providers.remotion.delivery")


class DeliveryContractTests(DeliveryFixture):
    def test_allowed_detector_intervals_cover_adjacent_shots(self):
        from providers.remotion.qc import _interval_check

        checks = []
        _interval_check(lambda name, passed, detail: checks.append(passed), "freeze",
                        {"intervals": [{"start_s": 1, "end_s": 3, "duration_s": 2}]},
                        [{"start_s": 1, "end_s": 2}, {"start_s": 2, "end_s": 3}], 1 / 24)
        self.assertEqual(checks, [True])

    def test_finished_claim_rejects_partial_forged_report(self):
        api = self.api()
        source = self.job / "final.mp4"
        source.write_bytes(b"not a measured render")
        file = {"file": str(source), "passed": True, "failures": [],
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "checks": [{"name": "checksum", "severity": "error", "pass": True}]}
        result = {"status": "succeeded", "passed": True, "failures": [], "job_id": "delivery-job",
                  "preset": "social-feed", "files": [file], "report_path": str(self.job / "report.json")}
        Path(result["report_path"]).write_text(json.dumps(result))
        self.assertFalse(api.validate_delivery_report(result))

    def test_gateway_exports_real_jobs_and_validates_before_execution(self):
        from providers.catalog import get_provider
        from providers.contracts import validate_tool_arguments
        from providers.registry import generate_schemas

        schemas = {s["name"]: s["inputSchema"] for s in generate_schemas(get_provider("remotion"))}
        self.assertTrue({"deliver_render", "qc_deliverable"} <= schemas.keys())
        for name in ("deliver_render", "qc_deliverable"):
            valid = {"job_id": "delivery-job", "input_path": "source.mov", "preset": "web-1080p"}
            validate_tool_arguments("remotion", name, valid, schemas[name])
            with self.assertRaises(ValueError):
                validate_tool_arguments("remotion", name, {**valid, "spec": {"expected_fps": float("inf")}}, schemas[name])

    def test_selector_spec_and_preset_boundaries(self):
        api = self.api()
        valid = {"job_id": "delivery-job", "input_path": "source.mov", "preset": "social-feed"}
        api.validate_arguments("qc_deliverable", valid)
        for extra in ({"input_path": ""}, {"manifest_path": "manifest.json"},
                      {"input_path": "../escape.mp4"}, {"job_id": "../escape"},
                      {"preset": "whatever"}, {"spec": {"args": "-i"}},
                      {"spec": {"expected_fps": float("nan")}},
                      {"spec": {"expected_width": 10**1000}},
                      {"spec": {"allowed_freeze": [{"start_s": 2, "end_s": 1}]}},
                      {"spec": {"master_path": "https://example.invalid/x"}}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                api.validate_arguments("qc_deliverable", {**valid, **extra})

    def test_delivery_combined_name_is_bounded_before_io(self):
        api = self.api()
        args = {"job_id": "delivery-job", "input_path": "missing.mov", "campaign": "A" * 40,
                "sku": "B" * 40, "locale": "C" * 40, "aspect": "2p39x1"}
        with self.assertRaises(ValueError):
            api.validate_arguments("deliver_render", args)

    def test_matrix_reuse_requires_its_saved_current_technical_report(self):
        from providers.remotion.ad_variants import _load_manifest

        directory = self.job / "matrix"
        directory.mkdir()
        artifact = directory / "variant.mp4"
        artifact.write_bytes(b"legacy review artifact")
        planned = {"variant_key": "A", "sku": "A", "locale": "en", "aspect": "16:9",
                   "input_props_hash": "a" * 64, "filename": artifact.name}
        entry = {**planned, "file": str(artifact), "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                 "approved_by": "operator:test"}
        manifest = directory / "manifest.json"
        manifest.write_text(json.dumps([entry]))
        with self.assertRaises(ValueError):
            _load_manifest(manifest, {"planned": [planned]}, directory)

    def test_defaults_validate_without_reading_missing_media(self):
        api = self.api()
        with patch.dict(os.environ, {"REMOTION_DRY_RUN": "true"}), patch(
                "providers.ffmpeg.api.execute", side_effect=AssertionError("Dry-run cannot inspect media")):
            result = api.deliver_render("delivery-job", input_path="missing.mp4")
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(result["passed"])

    def test_unsupported_backend_and_upload_refuse_before_io(self):
        api = self.api()
        for env in ({"REMOTION_RENDER_BACKEND": "lambda"},
                    {"AWS_LAMBDA_FUNCTION_NAME": "unit-test-lambda"}):
            with self.subTest(env=env), patch.dict(os.environ, env), patch(
                    "providers.ffmpeg.api.execute", side_effect=AssertionError("No media IO on Lambda")):
                result = api.qc_deliverable("delivery-job", input_path="missing.mp4")
            self.assertEqual(result["status"], "blocked")
            self.assertIn("local", result["reason"])
        result = api.deliver_render("delivery-job", input_path="missing.mp4", upload=True)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("upload", result["reason"].lower())

    def test_presets_are_bounded_data_and_never_assert_channel_certification(self):
        api = self.api()
        from providers.ffmpeg.delivery import INTENTS

        self.assertGreaterEqual(len(api.PRESETS), 7)
        for name, preset in api.PRESETS.items():
            with self.subTest(preset=name):
                self.assertTrue(preset["placeholder"])
                self.assertEqual(preset["container"], "mp4")
                self.assertEqual(preset["video_codec"], "h264")
                self.assertEqual(preset["fps"]["policy"], "preserve")
                self.assertLessEqual(preset["max_file_bytes"], 16 * 1024 * 1024)
                self.assertEqual(INTENTS[name], (preset["max_width"], preset["max_height"], preset["crf"]))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe absent")
class DeliveryRealBinaryTests(DeliveryFixture):
    def setUp(self):
        super().setUp()
        self.source = self.job / "source.mov"
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-n", "-f", "lavfi", "-i",
            "testsrc2=size=320x180:rate=24:duration=4", "-f", "lavfi", "-i",
            "sine=frequency=440:sample_rate=48000:duration=4", "-c:v", "libx264", "-threads", "1",
            "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-shortest", str(self.source)],
            check=True, capture_output=True, timeout=30)

    def deliver(self, **extra):
        return self.api().deliver_render("delivery-job", input_path="source.mov", preset="web-1080p",
            campaign="launch", sku="A", locale="en-CA", aspect="16x9", **extra)

    def test_delivery_measures_final_aac_and_writes_bound_reports(self):
        result = self.deliver()
        self.assertEqual(result["status"], "succeeded", result)
        self.assertTrue(result["passed"], result)
        file = result["files"][0]
        self.assertEqual((file["width"], file["height"]), (320, 180))
        self.assertIsNone(file["source_resolution"])
        self.assertEqual(file["input_resolution"], "320x180")
        self.assertRegex(Path(file["file"]).name, r"^launch__A__en-CA__16x9__v1\.mp4$")
        self.assertAlmostEqual(file["loudness"]["after"]["integrated_lufs"], -14, delta=.5)
        self.assertLessEqual(file["loudness"]["after"]["true_peak_db"], -1.5)
        self.assertEqual(hashlib.sha256(Path(file["file"]).read_bytes()).hexdigest(), file["sha256"])
        self.assertTrue(self.api().validate_delivery_report(result))
        report = json.loads(Path(result["report_path"]).read_text())
        self.assertTrue(report["passed"])
        from server.studio import collect_asset_sources

        assets = collect_asset_sources(result)
        self.assertEqual(sum(asset["kind"] == "video" for asset in assets), 1)
        self.assertEqual(sum(asset["kind"] == "image" for asset in assets), 6)
        Path(file["file"]).write_bytes(b"replaced")
        self.assertFalse(self.api().validate_delivery_report(result))

    def test_concurrent_delivery_versions_never_overwrite(self):
        api = self.api()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.deliver(), range(2)))
        self.assertTrue(all(r["passed"] for r in results), results)
        names = {Path(r["files"][0]["file"]).name for r in results}
        self.assertEqual(names, {"launch__A__en-CA__16x9__v1.mp4", "launch__A__en-CA__16x9__v2.mp4"})
        self.assertTrue(all(api.validate_delivery_report(r) for r in results))

    def test_qc_flags_wrong_fps_size_duration_loudness_and_naming(self):
        result = self.api().qc_deliverable("delivery-job", input_path="source.mov", preset="web-1080p",
            spec={"expected_width": 1920, "expected_height": 1080, "expected_fps": 30,
                  "expected_duration_s": 5})
        self.assertEqual(result["status"], "failed")
        file = result["files"][0]
        failed = {c["name"] for c in file["checks"] if not c["pass"]}
        self.assertTrue({"resolution", "fps", "duration", "loudness", "filename", "audio_codec"} <= failed)
        self.assertTrue(Path(result["report_path"]).is_file())

    def test_explicit_expected_filename_is_checked_even_when_convention_matches(self):
        name = "launch__A__en__16x9__v1.mp4"
        self.source.rename(self.job / name)
        result = self.api().qc_deliverable("delivery-job", input_path=name, preset="web-1080p",
                                          spec={"expected_filename": "another.mp4"})
        filename = next(c for c in result["files"][0]["checks"] if c["name"] == "filename")
        self.assertFalse(filename["pass"])

    def test_manifest_preserves_provenance_and_attaches_each_qc(self):
        row = {"variant_key": "A", "sku": "A", "locale": "en-CA", "aspect": "16:9",
               "file": str(self.source), "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
               "width": 320, "height": 180, "duration_s": 4, "source_resolution": "160x90",
               "upscaled": True, "warnings": ["upscaled from 160x90; no added detail"], "qc": {"delivery_qc": "pending"}}
        manifest = self.job / "manifest.json"
        manifest.write_text(json.dumps([row]))
        result = self.api().deliver_render("delivery-job", manifest_path="manifest.json", preset="web-1080p",
                                            campaign="launch")
        self.assertTrue(result["passed"], result)
        updated = json.loads(manifest.read_text())[0]
        self.assertTrue(updated["qc"]["passed"])
        self.assertEqual(updated["delivery"]["source_resolution"], "160x90")
        self.assertIn("upscaled from 160x90; no added detail", updated["delivery"]["warnings"])
        self.assertEqual(updated["file"], str(self.source))

    def test_manifest_corruption_never_produces_a_pass(self):
        for row in ({"file": "../outside.mp4"}, {"file": str(self.source), "sha256": "0" * 64},
                    {"file": str(self.source), "sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
                     "sku": "../bad", "locale": "en", "aspect": "16:9"}):
            with self.subTest(row=row):
                (self.job / "manifest.json").write_text(json.dumps([row]))
                result = self.api().deliver_render("delivery-job", manifest_path="manifest.json")
                self.assertFalse(result["passed"])
                self.assertNotEqual(result["status"], "succeeded")

    def test_detectors_fail_injected_black_freeze_silence_and_clipping(self):
        injected = self.job / "bad.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-n", "-f", "lavfi", "-i",
            "testsrc2=size=320x180:rate=24:duration=6", "-f", "lavfi", "-i",
            "aevalsrc=if(between(t\\,2\\,3)\\,0\\,2*sin(2*PI*440*t)):s=48000:d=6",
            "-vf", "drawbox=color=black:t=fill:enable='between(t,1,2)',tpad=stop_mode=clone:stop_duration=1",
            "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "7",
            "-movflags", "+faststart", str(injected)], check=True, capture_output=True, timeout=30)
        result = self.api().qc_deliverable("delivery-job", input_path="bad.mp4", preset="web-1080p")
        self.assertFalse(result["passed"])
        checks = {c["name"]: c for c in result["files"][0]["checks"]}
        for name in ("black", "freeze", "silence", "clipping"):
            self.assertIn(name, checks, "Each detector must produce a named pass/fail check")
            self.assertFalse(checks[name]["pass"], checks)

    def test_no_audio_cannot_be_finished(self):
        silent = self.job / "no-audio.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-n", "-i", str(self.source),
            "-map", "0:v:0", "-c:v", "copy", "-an", str(silent)], check=True, capture_output=True, timeout=30)
        result = self.api().deliver_render("delivery-job", input_path=silent.name, preset="web-1080p")
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["passed"])
        self.assertTrue(result["failures"])

    def test_dynamic_normalization_preserves_modulated_aac_duration(self):
        source = self.job / "modulated.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-n", "-f", "lavfi", "-i",
            "testsrc2=size=320x180:rate=24:duration=4", "-f", "lavfi", "-i",
            "aevalsrc=0.12*sin(2*PI*220*t)*(0.5+0.5*sin(2*PI*3*t)):s=48000:d=4",
            "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", str(source)], check=True, capture_output=True, timeout=30)
        result = self.api().deliver_render("delivery-job", input_path=source.name, preset="web-1080p")
        self.assertTrue(result["passed"], result["failures"])
        self.assertAlmostEqual(result["files"][0]["duration_s"], 4, delta=1 / 24)
        self.assertTrue(result["files"][0]["loudness"]["dynamic_fallback"])

    def test_vision_is_pending_and_requested_pixel_certification_fails(self):
        delivered = self.deliver()
        self.assertTrue(delivered["passed"], delivered)
        result = self.api().qc_deliverable("delivery-job", input_path=Path(delivered["files"][0]["file"]).name,
            preset="web-1080p", spec={"require_vision": True})
        self.assertFalse(result["passed"])
        self.assertEqual(result["files"][0]["visual_review"], "pending")

    def test_matrix_inspects_each_output_and_records_qc_failures(self):
        from providers.remotion import ad_variants

        plan = ad_variants._plan(self.job, self.source.name, [{"variant_key": "m", "aspect": "16:9"}],
                                {"campaign": "launch", "reframe_only": True})
        output = self.job / "matrix"
        output.mkdir()
        failure = {"passed": False, "failures": ["black: Unexpected black interval."],
                   "checks": [{"name": "black", "pass": False, "severity": "error", "detail": "Unexpected black interval."}]}
        with patch("providers.remotion.qc.inspect_file", return_value=failure):
            entry = ad_variants._render(plan["planned"][0], self.job, output, "operator", False)
        self.assertIn("technical_report", entry["qc"], "Every matrix artifact must have an actual QC report")
        self.assertFalse(entry["qc"]["technical_report"]["passed"])
        self.assertEqual(entry["delivery_status"], "failed")
        self.assertEqual(entry["qc"]["delivery_qc"], "failed")


if __name__ == "__main__":
    unittest.main()
