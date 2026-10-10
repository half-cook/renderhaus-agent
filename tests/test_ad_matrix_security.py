"""Persisted state must not bypass an approved matrix's artifact boundaries."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class MatrixPersistedStateTests(unittest.TestCase):
    def setUp(self):
        from providers.remotion import ad_variants
        self.matrix = ad_variants
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.job = self.root / "matrix"
        self.job.mkdir()
        self.plan_hash = "a" * 64
        self.directory = self.job / ("ad_matrix_" + self.plan_hash[:24])
        self.directory.mkdir()
        self.master = self.job / "master.mp4"
        self.master.write_bytes(b"approved-master-content")
        self.rows = [{"variant_key": "first", "sku": "A", "locale": "en-CA", "aspect": "1:1"},
                     {"variant_key": "second", "sku": "B", "locale": "en-CA", "aspect": "1:1"}]
        planned = [{**row, "row_index": index, "input_props_hash": str(index) * 64,
                    "filename": row["variant_key"] + ".mp4"} for index, row in enumerate(self.rows)]
        self.plan = {"planned": planned, "blocked": [], "plan_hash": self.plan_hash,
                     "render_count": 2, "warnings": [],
                     "asset_hashes": {"master.mp4": hashlib.sha256(self.master.read_bytes()).hexdigest()}}
        self.env = patch.dict(os.environ, {"RENDERHAUS_MEDIA_DIR": str(self.root),
                             "REMOTION_RENDER_BACKEND": "local", "REMOTION_DRY_RUN": "false"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.planner = patch.object(self.matrix, "_plan", return_value=self.plan)
        self.planner.start()
        self.addCleanup(self.planner.stop)

    def batch(self):
        with self.matrix.authorize("render_batch", self.plan_hash, "operator:test"):
            with patch.object(self.matrix, "_render", side_effect=RuntimeError("Invalid state reached rendering")):
                try:
                    return self.matrix.render_ad_variants(stage="render_batch", job_id="matrix",
                        master_asset="master.mp4", brief={"campaign": "demo"}, rows=self.rows,
                        plan_hash=self.plan_hash)
                except (ValueError, KeyError, TypeError) as exc:
                    self.fail(f"Invalid persisted state needs a structured blocked result, got {type(exc).__name__}")

    def entry(self, path):
        return {**self.plan["planned"][0], "file": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "approved_by": "operator:test"}

    def save(self, entries):
        (self.directory / "manifest.json").write_text(json.dumps(entries))

    def test_manifest_cannot_hash_an_outside_file_to_claim_first_render(self):
        outside = self.root / "outside.mp4"
        outside.write_bytes(b"unrelated-file")
        self.save([self.entry(outside)])
        result = self.batch()
        self.assertEqual(result["status"], "blocked", result)

    def test_manifest_entry_must_match_the_approved_plan_identity(self):
        first = self.directory / "first.mp4"
        first.write_bytes(b"old-plan-render")
        for changes in ({"input_props_hash": "f" * 64}, {"sha256": "f" * 64}, {"sku": "WRONG"},
                        {"locale": "fr-CA"}, {"aspect": "9:16"}, {"approved_by": ""}):
            with self.subTest(changes=changes):
                entry = copy.deepcopy(self.entry(first))
                entry.update(changes)
                self.save([entry])
                result = self.batch()
                self.assertEqual(result["status"], "blocked", result)

    def test_asset_change_after_plan_is_blocked_before_render_reads_it(self):
        safe_dir = self.matrix._safe_dir

        def change_asset(job, name):
            if name.startswith("ad_matrix_"):
                self.master.write_bytes(b"changed-after-approval")
            return safe_dir(job, name)

        with self.matrix.authorize("render_first", self.plan_hash, "operator:test"):
            with patch.object(self.matrix, "_safe_dir", side_effect=change_asset):
                with patch.object(self.matrix, "_render", side_effect=RuntimeError("Changed asset reached rendering")):
                    result = self.matrix.render_ad_variants(stage="render_first", job_id="matrix",
                        master_asset="master.mp4", brief={"campaign": "demo"}, rows=self.rows,
                        plan_hash=self.plan_hash)
        self.assertEqual(result["status"], "blocked", result)

    def test_corrupt_manifest_is_a_structured_blocker(self):
        for data in ("{bad-json", "{}", "[null]", '[{"variant_key":"first"}]'):
            with self.subTest(data=data):
                (self.directory / "manifest.json").write_text(data)
                result = self.batch()
                self.assertEqual(result["status"], "blocked", result)

    def test_worker_lock_refuses_fifo_without_opening_a_blocking_writer(self):
        lock = self.directory / "worker.lock"
        os.mkfifo(lock)
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            if path == lock:
                self.fail("Worker FIFO reached open; lock validation must refuse it first")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", guarded_open):
            result = self.batch()
        self.assertEqual(result["status"], "blocked", result)

    def test_manifest_read_is_bounded_before_json_decode(self):
        manifest = self.directory / "manifest.json"
        with manifest.open("wb") as target:
            target.truncate(8 * 1024 * 1024)
        original_read = Path.read_text

        def guarded_read(path, *args, **kwargs):
            if path == manifest:
                self.fail("Oversized manifest reached unbounded read_text")
            return original_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", guarded_read):
            result = self.batch()
        self.assertEqual(result["status"], "blocked", result)

    def test_technical_report_read_is_bounded_before_json_decode(self):
        first = self.directory / "first.mp4"
        first.write_bytes(b"approved-render")
        report = self.directory / "matrix-qc.json"
        with report.open("wb") as target:
            target.truncate(16 * 1024 * 1024 + 1)
        entry = self.entry(first)
        entry["matrix_qc"] = {"report_path": str(report), "sha256": "a" * 64}
        self.save([entry])
        original_read = Path.read_text

        def guarded_read(path, *args, **kwargs):
            if path == report:
                self.fail("Oversized QC report reached unbounded read_text")
            return original_read(path, *args, **kwargs)

        with patch.object(Path, "read_text", guarded_read):
            result = self.batch()
        self.assertEqual(result["status"], "blocked", result)


if __name__ == "__main__":
    unittest.main()
