"""Sandbox and real-binary contracts for the local free media inspection tool."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class FfmpegFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.job = self.root / "job-1"
        self.job.mkdir()
        self.source = self.job / "source.mp4"
        self.source.write_bytes(b"not-media")
        self.env = patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": str(self.root),
                                          "FFMPEG_DRY_RUN": "false"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec("providers.ffmpeg"),
                             "The sandboxed ffmpeg provider must exist")
        return importlib.import_module("providers.ffmpeg.api")

    def call(self, op="sha256", input_path="source.mp4", params=None, job_id="job-1"):
        return self.api().ffmpeg_tool(op, job_id, input_path, params)


class FfmpegToolTests(FfmpegFixture, unittest.TestCase):
    def test_sha256_returns_structured_inspection(self):
        result = self.call()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["op"], "sha256")
        self.assertEqual(result["metrics"]["sha256"], hashlib.sha256(b"not-media").hexdigest())
        self.assertEqual(result["outputs"], [])
        self.assertEqual(result["estimated_cost_usd"], 0)

    def test_unknown_op_refuses_and_names_a_nearby_allowed_op(self):
        result = self.call(op="extract_frame")
        self.assertFalse(result["ok"])
        self.assertIn("extract_frames", result["error"])

    def test_free_form_command_fields_are_refused(self):
        for op in ("probe", "extract_frames", "contact_sheet", "sha256", "check_faststart", "volume_stats"):
            with self.subTest(op=op):
                result = self.call(op=op, params={"args": "-i https://example.com/x -vf movie=/etc/passwd"})
                self.assertFalse(result["ok"])
                self.assertIn("args", result["error"])

    def test_job_ids_reject_injection_and_unicode(self):
        for value in ("../job-1", "-i", "job\n1", "job\u22121", "job/1", "", ".", ".."):
            with self.subTest(value=value):
                self.assertFalse(self.call(job_id=value)["ok"])

    def test_inputs_reject_traversal_urls_options_unicode_and_newlines(self):
        outside = self.root / "outside.mp4"
        outside.write_bytes(b"outside")
        for value in ("../outside.mp4", str(outside), "https://example.com/a", "file:source.mp4",
                      "source.mp4\n", "-source.mp4", "sourc\u0435.mp4", "a/../../outside.mp4"):
            with self.subTest(value=value):
                result = self.call(input_path=value)
                self.assertFalse(result["ok"], result)

    def test_symlink_escape_is_refused(self):
        outside = self.root / "outside.mp4"
        outside.write_bytes(b"outside")
        (self.job / "escape.mp4").symlink_to(outside)
        self.assertFalse(self.call(input_path="escape.mp4")["ok"])
        (self.root / "escape-job").symlink_to(self.root)
        self.assertFalse(self.call(job_id="escape-job")["ok"])

    def test_special_files_and_missing_inputs_are_refused(self):
        os.mkfifo(self.job / "fifo.mp4")
        for name in ("fifo.mp4", "missing.mp4", "."):
            with self.subTest(name=name):
                self.assertFalse(self.call(input_path=name)["ok"])

    def test_absolute_path_inside_job_and_internal_symlink_are_accepted(self):
        (self.job / "link.mp4").symlink_to(self.source)
        self.assertTrue(self.call(input_path=str(self.source))["ok"])
        self.assertTrue(self.call(input_path="link.mp4")["ok"])

    def test_default_dry_run_does_not_read_or_run_media(self):
        with patch.dict(os.environ, {"FFMPEG_DRY_RUN": "true"}):
            result = self.call(op="probe", input_path="not-created.mp4", job_id="ci-smoke")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["outputs"], [])

    def test_exported_contract_validates_before_dispatch_without_media_io(self):
        validator = getattr(self.api(), "validate_arguments", None)
        self.assertTrue(callable(validator), "Gateway pre-dispatch argument validator is required")
        args = {"op": "probe", "job_id": "ci-smoke", "input_path": "source.mp4"}
        validator(args)
        for changes in ({"op": "arbitrary"}, {"job_id": "../escape"},
                        {"input_path": "https://example.com/x"}, {"params": {"args": "-i"}}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    validator({**args, **changes})

    def test_all_op_params_have_table_driven_boundary_checks(self):
        cases = {
            "probe": [{"width": 2}],
            "extract_frames": [{"times": []}, {"times": list(range(21))}, {"times": [-1]},
                               {"times": [float("nan")]}, {"times": [float("inf")]},
                               {"times": [True]}, {"times": [10**1000]},
                               {"width": 1000000}, {"width": 10**1000}, {"width": "-i"}],
            "contact_sheet": [{"every_s": 0}, {"every_s": float("nan")}, {"cols": 0},
                              {"rows": 1000000}, {"cols": True}, {"width": 1000000}],
            "sha256": [{"overwrite": True}],
            "check_faststart": [{"command": "cat"}],
            "volume_stats": [{"filtergraph": "movie=http://example.com"}],
        }
        for op, rows in cases.items():
            for params in rows:
                with self.subTest(op=op, params=params):
                    self.assertFalse(self.call(op=op, params=params)["ok"])

    def test_full_json_schema_enforces_each_operations_parameter_contract(self):
        from jsonschema import validate, ValidationError
        from providers.ffmpeg.ops import tool_schema

        schema = tool_schema()["inputSchema"]
        base = {"job_id": "job-1", "input_path": "source.mp4"}
        validate({**base, "op": "extract_frames", "params": {"width": 1920}}, schema)
        for op, params in (("probe", {"width": 640}), ("sha256", {"args": "shell"}),
                           ("extract_frames", {"times": [-1]}),
                           ("contact_sheet", {"width": 1920})):
            with self.subTest(op=op, params=params), self.assertRaises(ValidationError):
                validate({**base, "op": op, "params": params}, schema)

    def test_registry_entry_can_add_an_op_with_bounded_enum_parameters(self):
        from providers.ffmpeg import ops
        spec = ops.OpSpec({"mode": {"type": "string", "enum": ["first", "last"], "default": "first"}},
                          pure=lambda source: {"bytes": source.stat().st_size})
        with patch.dict(ops.OPS, {"test_inspection": spec}):
            self.assertTrue(self.call(op="test_inspection", params={"mode": "last"})["ok"])
            for mode in ("http://example.com", "first; rm", True, "LAST"):
                with self.subTest(mode=mode):
                    self.assertFalse(self.call(op="test_inspection", params={"mode": mode})["ok"])

    def test_read_only_ops_do_not_invoke_a_binary(self):
        self.api()
        with patch("providers.ffmpeg.api._bounded_run", side_effect=AssertionError("No binary needed")):
            self.assertTrue(self.call(op="sha256")["ok"])

    def test_missing_binary_fails_soft_with_worker_guidance(self):
        self.api()
        with patch("providers.ffmpeg.api.shutil.which", return_value=None):
            result = self.call(op="probe")
        self.assertFalse(result["ok"])
        self.assertIn("local", result["error"])
        self.assertIn("ffprobe", result["error"])

    def test_faststart_reads_atom_order_without_ffmpeg(self):
        self.api()
        def atom(name, body=b""):
            return struct.pack(">I4s", len(body) + 8, name) + body
        for name, contents, expected in (
            ("fast.mp4", atom(b"ftyp") + atom(b"moov") + atom(b"mdat", b"x"), True),
            ("slow.mp4", atom(b"ftyp") + atom(b"mdat", b"x") + atom(b"moov"), False),
        ):
            with self.subTest(name=name):
                (self.job / name).write_bytes(contents)
                with patch("providers.ffmpeg.api.shutil.which", return_value=None):
                    result = self.call(op="check_faststart", input_path=name)
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["metrics"]["faststart"], expected)

    def test_faststart_rejects_truncated_or_bogus_atoms(self):
        for content in (b"bad", struct.pack(">I4s", 999999, b"moov"),
                        struct.pack(">I4s", 2, b"moov"), struct.pack(">I4s", 1, b"moov")):
            with self.subTest(content=content):
                self.source.write_bytes(content)
                self.assertFalse(self.call(op="check_faststart")["ok"])

    def test_process_scrubs_environment_disables_stdin_and_bounds_capture(self):
        api = self.api()
        with patch.dict(os.environ, {"FAKE_API_KEY": "not-a-real-secret", "HF_TOKEN": "fake-test-token"}):
            result = api._bounded_run(
                [sys.executable, "-c", "import os,sys,json; print(json.dumps(dict(os.environ))); "
                 "print(len(sys.stdin.read())); sys.stderr.write('x'*100000)"], self.job, 5)
        stdout = result.stdout.decode()
        self.assertNotIn("FAKE_API_KEY", stdout)
        self.assertNotIn("HF_TOKEN", stdout)
        self.assertTrue(stdout.rstrip().endswith("0"))
        self.assertLessEqual(len(result.stderr), 8192)
        huge = api._bounded_run([sys.executable, "-c", "print('x'*2000000)"], self.job, 5)
        self.assertLessEqual(len(huge.stdout), 1024 * 1024)
        self.assertTrue(huge.stdout_truncated)

    def test_process_timeout_is_hard(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.api()._bounded_run([sys.executable, "-c", "import time; time.sleep(3)"], self.job, .05)

    def test_process_waiting_for_capacity_obeys_the_same_deadline(self):
        api = self.api()
        import time
        import threading
        capacity = threading.Semaphore(0)
        started = time.monotonic()
        timer = threading.Timer(.25, capacity.release)
        timer.start()
        self.addCleanup(timer.cancel)
        try:
            with patch.object(api, "_PROCESS_LIMIT", capacity):
                with self.assertRaises(subprocess.TimeoutExpired):
                    api._bounded_run([sys.executable, "-c", "print('finished')"], self.job, .05)
            self.assertLess(time.monotonic() - started, .2)
        finally:
            timer.cancel()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg and ffprobe are absent")
class FfmpegRealBinaryTests(FfmpegFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=size=160x90:rate=24:duration=1", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=1", "-c:v", "libx264", "-threads", "1", "-c:a", "aac",
                        "-shortest", "-movflags", "+faststart", str(self.source)],
                       check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=15)

    def test_probe_measures_real_streams(self):
        result = self.call(op="probe")
        self.assertTrue(result["ok"], result)
        video = next(s for s in result["metrics"]["streams"] if s["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"]), (160, 90))
        self.assertEqual(video["avg_frame_rate"], "24/1")

    def test_extract_frames_and_contact_sheet_create_readable_hashed_outputs(self):
        for op, params, count in (("extract_frames", {"times": [.05, .5, .9], "width": 160}, 3),
                                  ("contact_sheet", {"every_s": .25, "cols": 3, "rows": 1,
                                                     "width": 160, "height": 90}, 1)):
            with self.subTest(op=op):
                result = self.call(op=op, params=params)
                self.assertTrue(result["ok"], result)
                self.assertEqual(len(result["outputs"]), count)
                for output in result["outputs"]:
                    path = Path(output["path"])
                    self.assertTrue(path.is_file())
                    self.assertIn(self.job, path.parents)
                    self.assertRegex(path.name, r"^[A-Za-z0-9_.-]+$")
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), output["sha256"])
                    self.assertEqual(path.stat().st_size, output["bytes"])
                    from PIL import Image
                    with Image.open(path) as im:
                        self.assertGreater(im.width, 0)

    def test_volume_stats_returns_measured_numeric_levels(self):
        result = self.call(op="volume_stats")
        self.assertTrue(result["ok"], result)
        self.assertLess(result["metrics"]["mean_volume_db"], -1)
        self.assertLessEqual(result["metrics"]["max_volume_db"], 0)

    def test_concurrent_outputs_do_not_overwrite_each_other(self):
        def run(_):
            return self.call(op="extract_frames", params={"times": [.2], "width": 160})
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(run, range(4)))
        self.assertTrue(all(result["ok"] for result in results), results)
        paths = [r["outputs"][0]["path"] for r in results]
        self.assertEqual(len(set(paths)), 4)
        self.assertTrue(all(Path(path).exists() for path in paths))

    def test_missing_requested_frame_fails_and_removes_partial_outputs(self):
        result = self.call(op="extract_frames", params={"times": [.2, 100], "width": 160})
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["outputs"], [])
        self.assertEqual(list(self.job.glob("frame-*.png")), [])

    def test_invalid_media_failure_tail_has_no_raw_path_or_secrets(self):
        self.source.write_bytes(b"not-media")
        result = self.call(op="probe")
        self.assertFalse(result["ok"])
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertLessEqual(len(result.get("error_tail", "")), 2048)


if __name__ == "__main__":
    unittest.main()
