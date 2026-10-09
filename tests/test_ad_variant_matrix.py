from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from agent.gateway_executor import tool_needs_approval


TOOL = "Remotion___render_ad_variants"
ROOT = Path(__file__).resolve().parents[1]


class MatrixApprovalTests(unittest.TestCase):
    def test_reframe_only_quote_matches_normalized_first_group(self):
        from server.billing_rates import ad_matrix_estimate

        with patch.dict(os.environ, {"REMOTION_RENDER_BACKEND": "local", "REMOTION_LICENSE_RENDER_USD": "0.01"}):
            quote = ad_matrix_estimate({"stage": "render_first", "brief": {"reframe_only": True}, "rows": [
                {"variant_key": "a", "aspect": "9:16"},
                {"variant_key": "b", "sku": "master", "locale": "und", "aspect": "1:1"}]})
        self.assertEqual(quote["render_count"], 2)
        self.assertEqual(quote["estimated_license_usd"], .02)

    def test_plan_and_ffmpeg_are_free_and_render_stages_always_pause(self):
        for autonomous in (False, True):
            self.assertFalse(tool_needs_approval("Ffmpeg___ffmpeg_tool", autonomous))
            for stage, gated in (("plan", False), ("render_first", True), ("render_batch", True)):
                self.assertEqual(tool_needs_approval(TOOL, autonomous, {"stage": stage}), gated)

    def test_cost_quotes_are_known_for_both_backends(self):
        from server.billing_rates import ad_matrix_estimate

        args = {"stage": "render_batch", "rows": [
            {"sku": "A", "locale": "en", "aspect": "1:1"},
            {"sku": "B", "locale": "en", "aspect": "1:1"}], "brief": {}}
        with patch.dict(os.environ, {"REMOTION_RENDER_BACKEND": "local", "REMOTION_LICENSE_RENDER_USD": "0.01"}):
            quote = ad_matrix_estimate(args)
            self.assertEqual(quote["estimated_media_usd"], 0)
            self.assertEqual(quote["estimated_license_usd"], 0.01)
            self.assertEqual(quote["estimated_total_usd"], 0.01)
        with patch.dict(os.environ, {"REMOTION_RENDER_BACKEND": "lambda"}):
            self.assertGreater(ad_matrix_estimate(args)["estimated_total_usd"], 0)
        for value in ("NaN", "Infinity", "-1", "abc"):
            with patch.dict(os.environ, {"REMOTION_LICENSE_RENDER_USD": value}):
                with self.assertRaises(ValueError):
                    ad_matrix_estimate(args)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe absent")
class MatrixContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.media = Path(cls.temporary.name)
        cls.job = cls.media / "matrix"
        cls.job.mkdir()
        subprocess.run([
            "ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
            "color=c=0x234567:s=320x240:r=24:d=0.75", "-f", "lavfi", "-i",
            "sine=frequency=440:sample_rate=48000:duration=0.75", "-threads", "1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(cls.job / "master.mp4")], check=True, capture_output=True, timeout=30)
        Image.new("RGBA", (64, 32), (240, 30, 70, 180)).save(cls.job / "logo.png")
        Image.new("RGB", (64, 32), (240, 30, 70)).save(cls.job / "opaque.png")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.env = patch.dict(os.environ, {
            "RENDERHAUS_MEDIA_DIR": str(self.media), "REMOTION_RENDER_BACKEND": "local",
            "REMOTION_DRY_RUN": "false", "FFMPEG_DRY_RUN": "false", "REMOTION_LICENSE_RENDER_USD": "0.01"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.assertTrue((ROOT / "providers/remotion/ad_variants.py").is_file(), "matrix implementation missing")
        from providers.remotion import ad_variants
        self.matrix = ad_variants
        self.rows = [{"variant_key": f"ad_{sku}_{aspect.replace(':', 'x')}", "sku": sku,
                      "price_text": "$9.99", "cta_text": "Buy now", "logo_asset": "logo.png",
                      "legal_text": "Terms apply", "locale": "en-CA", "aspect": aspect}
                     for sku in ("A", "B", "C") for aspect in ("1:1", "4:5")]
        self.args = {"job_id": "matrix", "master_asset": "master.mp4", "rows": self.rows,
                     "brief": {"campaign": "demo", "legal_locales": ["en-CA"]}}

    def plan(self, **changes):
        return self.matrix.render_ad_variants(stage="plan", **{**self.args, **changes})

    def test_plan_keeps_copy_and_hashes_every_asset(self):
        self.rows[0]["price_text"] = " 9,99 € "
        result = self.plan()
        self.assertEqual(result["render_count"], 6)
        self.assertEqual(result["blocked"], [])
        self.assertEqual(result["planned"][0]["expected_strings"]["price_text"], " 9,99 € ")
        props = result["planned"][0]["timeline"]
        items = [i for t in props["document"]["tracks"] for i in t["items"] if i["type"] == "text"]
        self.assertIn(" 9,99 € ", [i["text"] for i in items])
        self.assertEqual(props["renderConfig"]["fps"], 24)
        self.assertEqual(props["renderConfig"]["resolution"]["source_resolution"], "320x240")
        self.assertEqual(result["plan_hash"], self.plan()["plan_hash"])
        changed = copy.deepcopy(self.rows)
        changed[0]["cta_text"] = "Shop now"
        self.assertNotEqual(result["plan_hash"], self.plan(rows=changed)["plan_hash"])
        logo = self.job / "logo.png"
        original = logo.read_bytes()
        try:
            Image.new("RGBA", (64, 32), (10, 20, 30, 180)).save(logo)
            self.assertNotEqual(result["plan_hash"], self.plan()["plan_hash"])
        finally:
            logo.write_bytes(original)

    def test_each_table_rule_blocks_before_render(self):
        changes = [
            ("missing column", lambda r: r[0].pop("sku")),
            ("empty copy", lambda r: r[0].update(cta_text=" ")),
            ("duplicate tuple", lambda r: r[1].update(aspect="1:1")),
            ("unsafe key", lambda r: r[0].update(variant_key="../escape")),
            ("unsafe sku", lambda r: r[0].update(sku="-vf\nattack")),
            ("unsafe locale", lambda r: r[0].update(locale="en/CA")),
            ("wrong aspect", lambda r: r[0].update(aspect="banana")),
            ("missing legal", lambda r: r[0].update(legal_text="")),
            ("missing logo", lambda r: r[0].update(logo_asset="absent.png")),
            ("no alpha", lambda r: r[0].update(logo_asset="opaque.png")),
            ("outside job", lambda r: r[0].update(logo_asset="../logo.png")),
            ("remote", lambda r: r[0].update(logo_asset="https://example.com/logo.png")),
            ("invalid time", lambda r: r[0].update(start_s=0.7, end_s=0.6)),
            ("NaN", lambda r: r[0].update(start_s=float("nan"))),
            ("overflow", lambda r: r[0].update(legal_text="M" * 500)),
        ]
        for label, mutate in changes:
            with self.subTest(rule=label):
                rows = copy.deepcopy(self.rows)
                mutate(rows)
                result = self.plan(rows=rows)
                self.assertTrue(result["blocked"], label)
                self.assertEqual(result["status"], "blocked")

    def test_master_contract_and_symlink_escape(self):
        outside = self.media / "outside.png"
        outside.write_bytes((self.job / "logo.png").read_bytes())
        link = self.job / "escape.png"
        link.symlink_to(outside)
        self.addCleanup(link.unlink)
        self.rows[0]["logo_asset"] = "escape.png"
        self.assertTrue(self.plan()["blocked"])
        self.rows[0]["logo_asset"] = "logo.png"
        self.assertTrue(self.plan(brief={"campaign": "demo", "fps": 30})["blocked"])
        self.assertTrue(self.plan(brief={"campaign": "demo", "source_width": 1920})["blocked"])

    def test_batch_rejects_unapproved_and_changed_hash(self):
        plan = self.plan()
        for stage in ("render_first", "render_batch"):
            result = self.matrix.render_ad_variants(stage=stage, plan_hash=plan["plan_hash"], **self.args)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("approval", result["reason"].lower())
        with self.matrix.authorize("render_batch", plan["plan_hash"], "operator:test"):
            result = self.matrix.render_ad_variants(stage="render_batch", plan_hash=plan["plan_hash"], **self.args)
            self.assertEqual(result["status"], "blocked")
            self.assertIn("first", result["reason"].lower())
        changed = copy.deepcopy(self.rows)
        changed[0]["price_text"] = "$8.99"
        with self.matrix.authorize("render_first", plan["plan_hash"], "operator:test"):
            result = self.matrix.render_ad_variants(stage="render_first", plan_hash=plan["plan_hash"],
                                                   **{**self.args, "rows": changed})
            self.assertEqual(result["status"], "blocked")

    def test_lambda_refuses_local_job_flow_without_network(self):
        with patch.dict(os.environ, {"REMOTION_RENDER_BACKEND": "lambda"}):
            result = self.plan()
            self.assertEqual(result["status"], "blocked")
            self.assertIn("local", result["reason"].lower())

    def test_legal_line_must_match_brief_and_long_names_stay_unique_and_usable(self):
        result = self.plan(brief={"campaign": "demo", "legal_by_locale": {"en-CA": "Required legal"}})
        self.assertTrue(result["blocked"])
        rows = copy.deepcopy(self.rows)
        for i, row in enumerate(rows):
            row.update(variant_key="v" * 39 + str(i), sku="s" * 39 + str(i // 2), locale="l" * 40)
        result = self.plan(rows=rows, brief={"campaign": "c" * 40, "output_resolution": "1080p",
                                            "allow_upscale": True})
        self.assertFalse(result["blocked"], result)
        names = [row["filename"] for row in result["planned"]]
        self.assertEqual(len(set(names)), 6)
        self.assertTrue(all(len(name) <= 90 for name in names))

    def test_campaign_cannot_generate_an_option_prefixed_media_filename(self):
        result = self.plan(brief={"campaign": "-sale"})
        self.assertFalse(result["blocked"], result)
        self.assertTrue(all(not row["filename"].startswith("-") for row in result["planned"]))

    def test_rotated_master_uses_displayed_source_dimensions(self):
        rotated = self.job / "rotated.mp4"
        help_text = subprocess.check_output(["ffmpeg", "-hide_banner", "-h", "full"],
                                           stderr=subprocess.STDOUT, timeout=30)
        rotation = ["-display_rotation", "90"] if b"-display_rotation" in help_text else []
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-n", *rotation, "-i",
            str(self.job / "master.mp4"), "-c", "copy",
            *([] if rotation else ["-metadata:s:v:0", "rotate=90"]), str(rotated)],
            check=True, capture_output=True, timeout=30)
        self.addCleanup(rotated.unlink)
        result = self.plan(master_asset="rotated.mp4", brief={"campaign": "rotated",
            "source_width": 240, "source_height": 320})
        self.assertFalse(result["blocked"], result)
        self.assertEqual(result["source_resolution"], "240x320")
        self.assertEqual(result["planned"][0]["timeline"]["renderConfig"]["resolution"]["source_resolution"], "240x320")

    def test_one_failed_variant_does_not_stop_others_and_cannot_blind_retry(self):
        args = {**self.args, "brief": {"campaign": "failure-demo"}}
        plan = self.matrix.render_ad_variants(stage="plan", **args)
        with self.matrix.authorize("render_first", plan["plan_hash"], "operator:test"):
            first = self.matrix.render_ad_variants(stage="render_first", plan_hash=plan["plan_hash"], **args)
        self.assertEqual(first["status"], "succeeded", first)
        render = self.matrix.api.render_timeline

        def maybe_fail(**render_args):
            if "__B__" in render_args["output_filename"]:
                return {"status": "failed", "error": "fixture codec failure"}
            return render(**render_args)

        with patch.object(self.matrix.api, "render_timeline", side_effect=maybe_fail) as calls:
            with self.matrix.authorize("render_batch", plan["plan_hash"], "operator:test"):
                batch = self.matrix.render_ad_variants(stage="render_batch", plan_hash=plan["plan_hash"], **args)
        self.assertEqual(batch["status"], "failed", batch)
        self.assertEqual(len(batch["failed"]), 2)
        self.assertEqual(len(batch["rendered"]), 4)
        self.assertEqual(calls.call_count, 4)
        with patch.object(self.matrix.api, "render_timeline") as retry:
            with self.matrix.authorize("render_batch", plan["plan_hash"], "operator:test"):
                repeated = self.matrix.render_ad_variants(stage="render_batch", plan_hash=plan["plan_hash"], **args)
        retry.assert_not_called()
        self.assertEqual(repeated["status"], "failed")
        self.assertTrue(all("blind retries" in failure["reasons"][0] for failure in repeated["failed"]))

    def test_real_six_variant_render_and_manifest(self):
        plan = self.plan()
        self.assertFalse(plan["blocked"])
        plan_hash = plan["plan_hash"]
        with self.matrix.authorize("render_first", plan_hash, "operator:test"):
            first = self.matrix.render_ad_variants(stage="render_first", plan_hash=plan_hash, **self.args)
        self.assertEqual(first["status"], "succeeded", first)
        self.assertEqual(len(first["rendered"]), 2)
        self.assertEqual(len(first["rendered"][0]["review_frames"]), 3)
        from server.studio import collect_asset_sources
        assets = collect_asset_sources(first)
        self.assertEqual(sum(a["kind"] == "image" for a in assets), 8, "Review frames and sheets must appear in Studio")
        with self.matrix.authorize("render_batch", plan_hash, "operator:test"):
            batch = self.matrix.render_ad_variants(stage="render_batch", plan_hash=plan_hash, **self.args)
        self.assertEqual(batch["status"], "succeeded", batch)
        self.assertEqual(len(batch["rendered"]), 6)
        manifest = json.loads(Path(batch["manifest_path"]).read_text())
        self.assertEqual(len(manifest), 6)
        for entry in manifest:
            path = Path(entry["file"])
            self.assertEqual(entry["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(entry["approved_by"], "operator:test")
            self.assertIsNone(entry["ocr_match"])
            measured = json.loads(subprocess.run([
                "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                check=True, capture_output=True, timeout=30).stdout)
            video = next(s for s in measured["streams"] if s["codec_type"] == "video")
            expected = (240, 240) if entry["aspect"] == "1:1" else (192, 240)
            self.assertEqual((video["width"], video["height"]), expected)
            self.assertEqual(video["avg_frame_rate"], "24/1")
            self.assertAlmostEqual(float(measured["format"]["duration"]), 0.75, delta=1/24)
        # A flat source is uniform. Visible text must introduce light pixels in the safe zone.
        with Image.open(first["rendered"][0]["review_frames"][1]) as source:
            frame = source.convert("RGB")
        self.assertGreater(sum(1 for r, g, b in zip(*[iter(frame.tobytes())] * 3) if min(r, g, b) > 180), 10)
        with self.matrix.authorize("render_batch", plan_hash, "operator:test"):
            again = self.matrix.render_ad_variants(stage="render_batch", plan_hash=plan_hash, **self.args)
        self.assertEqual([r["file"] for r in again["rendered"]], [r["file"] for r in batch["rendered"]])


if __name__ == "__main__":
    unittest.main()
