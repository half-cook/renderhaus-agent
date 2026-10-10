from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import numpy as np


FIXTURES = Path(__file__).parent / "fixtures" / "motion_carry"


class MotionCarryTests(unittest.TestCase):
    def api(self):
        return importlib.import_module("providers.remotion.motion_carry")

    def test_static_identity_and_teleport_do_not_count_as_carry(self):
        api = self.api()
        frames = np.zeros((72, 48, 80, 3), dtype=np.uint8)
        frames[:, 16:32, 20:36] = [40, 180, 240]
        timeline = {"beats_s": [0, 1, 2, 3], "elements": [
            {"id": "product", "start_s": 0, "end_s": 3}]}
        report = api.analyse_frames(frames, 24, timeline=timeline)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(all(not b["passed"] for b in report["boundaries"]))
        frames[24:] = 0
        frames[24:, 16:32, 55:71] = [40, 180, 240]
        report = api.analyse_frames(frames, 24, timeline=timeline)
        self.assertFalse(report["boundaries"][0]["passed"])

    def test_invalid_arguments_refuse_before_media_io(self):
        from providers.catalog import get_provider
        from providers.contracts import validate_tool_arguments
        from providers.registry import generate_schemas

        schema = next(s["inputSchema"] for s in generate_schemas(get_provider("remotion"))
                      if s["name"] == "motion_carry_probe")
        valid = {"job_id": "job", "input_path": "film.mp4"}
        validate_tool_arguments("remotion", "motion_carry_probe", valid, schema)
        for extra in ({"input_path": "../secret"}, {"job_id": "../job"},
                      {"timeline": {"beats_s": [0, 2, 1]}},
                      {"timeline": {"beats_s": [0, float("nan"), 3]}},
                      {"timeline": {"elements": [{"id": "x", "start_s": 2, "end_s": 1}]}},
                      {"timeline": {"shell": "anything"}}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                validate_tool_arguments("remotion", "motion_carry_probe", {**valid, **extra}, schema)

    def test_fail_soft_and_dry_run_never_certify(self):
        api = self.api()
        with patch.dict(os.environ, {"MOTION_CARRY_QC_DRY_RUN": "true"}):
            report = api.motion_carry_probe("job", "missing.mp4")
        self.assertEqual(report["status"], "dry_run")
        self.assertFalse(report["passed"])
        with tempfile.TemporaryDirectory() as root:
            job = Path(root) / "job"
            job.mkdir()
            (job / "broken.mp4").write_bytes(b"invalid media")
            with patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": root,
                                        "MOTION_CARRY_QC_DRY_RUN": "false"}):
                report = api.motion_carry_probe("job", "broken.mp4")
            self.assertEqual(report["status"], "skipped")
            self.assertFalse(report["passed"])
            self.assertTrue(report["reason"])

    def test_free_tool_never_pauses_or_adds_cost(self):
        from agent.gateway_executor import tool_needs_approval
        from agent.deep_agent.routing import estimate_cost, is_free_tool
        from server.billing_rates import cost_for

        name = "Remotion___motion_carry_probe"
        self.assertTrue(is_free_tool(name))
        for autonomous in (False, True):
            self.assertFalse(tool_needs_approval(name, autonomous))
        self.assertEqual(estimate_cost(name, {}).total_cents, 0)
        self.assertEqual(cost_for("remotion", "motion_carry_probe", {}).total_cents, 0)

    def test_clean_loud_audio_is_not_clipping_but_flat_rail_audio_is(self):
        api = self.api()
        frames = np.zeros((72, 48, 80, 3), dtype=np.uint8)
        frames[:, 16:32, 20:36] = [40, 180, 240]
        t = np.arange(3*192000)/192000
        clean = .95*np.sin(2*np.pi*330*t)
        clipped = np.clip(1.8*np.sin(2*np.pi*330*t), -1, 1)
        for audio, expected in ((clean, True), (clipped, False)):
            report = api.analyse_frames(frames, 24, audio=audio)
            self.assertEqual(report["checks"]["clipped_audio"]["passed"], expected)

    def test_completed_reports_conform_to_the_published_schema(self):
        from jsonschema import validate, ValidationError
        api = self.api()
        frames = np.zeros((72, 48, 80, 3), dtype=np.uint8)
        frames[:, 16:32, 20:36] = [40, 180, 240]
        report = api.analyse_frames(frames, 24, timeline={"beats_s": [0, .8, 2, 3]})
        validate(report, api.REPORT_SCHEMA)
        report["checks"]["subject_exit"]["evidence"] = [{"time_s": -1}]
        with self.assertRaises(ValidationError):
            validate(report, api.REPORT_SCHEMA)

    def test_busy_worker_skips_probe_without_reading_media(self):
        api = self.api()
        with patch.dict(os.environ, {"MOTION_CARRY_QC_DRY_RUN": "false"}), patch.object(api, "probe_file") as probe:
            api.PROBE_SLOT.acquire()
            try:
                report = api.motion_carry_probe("job", "film.mp4")
            finally:
                api.PROBE_SLOT.release()
        self.assertEqual(report["status"], "skipped")
        self.assertIn("busy", report["reason"])
        probe.assert_not_called()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe absent")
class MotionFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = importlib.import_module("providers.remotion.motion_carry")
        cls.manifest = json.loads((FIXTURES / "manifest.json").read_text())
        cls.reports = {case["name"]: cls.api.probe_file(FIXTURES / case["file"], case.get("timeline"))
                       for case in cls.manifest["films"]}

    def test_carrying_beats_pass_and_slideshow_and_fade_replace_fail(self):
        positive = self.reports["carrying"]
        self.assertEqual(positive["status"], "passed", positive)
        for name in ("slideshow", "fade_replace"):
            report = self.reports[name]
            self.assertEqual(report["status"], "failed", report)
            self.assertLess(report["carry_score"], positive["carry_score"])
            self.assertTrue(any(not b["passed"] for b in report["boundaries"]))

    def test_each_rhythm_fault_has_timestamped_evidence_and_a_fix(self):
        for name in ("uniform_cadence", "no_rests", "clipped_audio", "unblurred_fast_move", "subject_exit"):
            with self.subTest(check=name):
                good = self.reports["carrying"]["checks"][name]
                bad = self.reports[name]["checks"][name]
                self.assertTrue(good["passed"], good)
                self.assertFalse(bad["passed"], bad)
                self.assertTrue(bad["evidence"], bad)
                self.assertTrue(bad["fix"])
                self.assertTrue(all("time_s" in e for e in bad["evidence"]))
        self.assertTrue(self.reports["blurred_fast_move"]["checks"]["unblurred_fast_move"]["passed"])
        self.assertTrue(self.reports["intentional_exit"]["checks"]["subject_exit"]["passed"])

    def test_video_only_detection_finds_slideshow_cuts_and_audio_onsets(self):
        report = self.api.probe_file(FIXTURES / "slideshow.mp4")
        self.assertEqual(report["boundary_source"], "video_and_audio")
        self.assertGreaterEqual(len(report["boundaries"]), 2)
        self.assertTrue(any(not b["passed"] for b in report["boundaries"]))

    def test_report_roundtrips_and_saved_checksum_changes_invalidate_it(self):
        with tempfile.TemporaryDirectory() as root:
            job = Path(root) / "job"
            job.mkdir()
            source = job / "film.mp4"
            shutil.copyfile(FIXTURES / "carrying.mp4", source)
            timeline = self.manifest["films"][0]["timeline"]
            with patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": root,
                                        "MOTION_CARRY_QC_DRY_RUN": "false"}):
                report = self.api.motion_carry_probe("job", "film.mp4", timeline)
                self.assertTrue(self.api.validate_report(report))
                self.assertEqual(json.loads(Path(report["report_path"]).read_text()), report)
                self.assertEqual(report["schema_version"], 1)
                self.assertTrue(report["calibration"]["provisional"])
                source.write_bytes(b"changed")
                self.assertFalse(self.api.validate_report(report))

    def test_calibration_cli_derives_separating_thresholds_and_records_scores(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "calibration.json"
            subprocess.run([str(Path(".venv/bin/python")), "scripts/calibrate_motion_carry.py",
                            "--manifest", str(FIXTURES / "manifest.json"), "--output", str(output)],
                           check=True, capture_output=True, timeout=90)
            config = json.loads(output.read_text())
            self.assertTrue(config["provisional"])
            self.assertEqual(config["method"], "midpoint of labelled class extrema")
            self.assertEqual(len(config["scores"]), len(self.manifest["films"]))
            self.assertTrue(all(row["separated"] for row in config["separation"].values()))


if __name__ == "__main__":
    unittest.main()
