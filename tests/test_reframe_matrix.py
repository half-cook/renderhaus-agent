from __future__ import annotations

import copy
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from providers.remotion import ad_variants, local


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe absent")
class ReframeMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.job = cls.root / "reframe"
        cls.job.mkdir()
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
            "color=c=red:s=320x180:r=24:d=1,drawbox=x=160:y=0:w=160:h=180:color=blue:t=fill",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
            "-threads", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(cls.job / "master.mp4")], check=True, capture_output=True, timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        env = patch.dict(os.environ, {"REMOTION_RENDER_BACKEND": "local", "REMOTION_DRY_RUN": "false",
            "FFMPEG_DRY_RUN": "false", "RENDERHAUS_MEDIA_DIR": str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        self.args = {"job_id": "reframe", "master_asset": "master.mp4",
            "brief": {"campaign": self.id().split(".")[-1][:40], "reframe_only": True},
            "rows": [{"variant_key": "a_" + aspect.replace(":", "x").replace(".", "_"), "aspect": aspect}
                     for aspect in ("9:16", "1:1", "4:5", "16:9", "2.39:1")]}

    def plan(self, **changes):
        return ad_variants.render_ad_variants(stage="plan", **{**self.args, **changes})

    def test_finished_master_accepts_aspect_only_rows_and_binds_crop_plan(self):
        plan = self.plan()
        self.assertEqual(plan["status"], "planned", plan)
        self.assertEqual(plan["render_count"], 5)
        self.assertTrue(plan["candidate_set"])
        self.assertIn("editorial", plan["review_note"].lower())
        for row in plan["planned"]:
            self.assertFalse(row["render_arguments"]["text_overlays"])
            self.assertEqual(len(row["render_arguments"]["visuals"]), 1)
            crop = row["reframe_plan"][0]
            visual = row["render_arguments"]["visuals"][0]
            self.assertEqual(visual["crop_box"], crop["crop_box"])
            config = row["timeline"]["renderConfig"]
            self.assertEqual((config["width"], config["height"]), (crop["width"], crop["height"]))
            self.assertEqual(config["fps"], 24)
            self.assertFalse(config["resolution"]["upscaled"])

    def test_wide_planner_box_switches_to_safe_blurred_padding(self):
        rows = [{"variant_key": "wide", "aspect": "9:16", "subject_box":
                 {"x": 20, "y": 20, "width": 280, "height": 140}}]
        plan = self.plan(rows=rows)
        self.assertEqual(plan["status"], "planned", plan)
        row = plan["planned"][0]
        self.assertEqual(row["reframe_plan"][0]["mode"], "pad_blur")
        visual = row["render_arguments"]["visuals"][0]
        self.assertNotIn("crop_box", visual)
        self.assertEqual(visual["fit"], "pad_blur")
        self.assertEqual(visual["pad_box"], row["reframe_plan"][0]["foreground_box"])

    def test_scene_list_builds_static_consecutive_windows_and_canvas(self):
        rows = [{"variant_key": "cuts", "aspect": "1:1", "shots": [
            {"from_s": 0, "to_s": .5, "anchor": "left"},
            {"from_s": .5, "to_s": 1, "anchor": "right"}]}]
        plan = self.plan(rows=rows)
        self.assertEqual(plan["status"], "planned", plan)
        visuals = plan["planned"][0]["render_arguments"]["visuals"]
        self.assertEqual([v["duration_seconds"] for v in visuals], [.5, .5])
        self.assertEqual([v["source_in_seconds"] for v in visuals], [0, .5])
        self.assertEqual([v["start_seconds"] for v in visuals], [0, .5])
        self.assertEqual([v["crop_box"]["x"] for v in visuals], [0, 140])
        self.assertEqual(visuals[0]["reframe_size"], visuals[1]["reframe_size"])

    def test_scene_times_use_detect_scenes_result_without_detector(self):
        rows = [{"variant_key": "times", "aspect": "9:16", "scene_times": [.5]}]
        plan = self.plan(rows=rows)
        self.assertEqual(plan["status"], "planned", plan)
        self.assertEqual(len(plan["planned"][0]["reframe_plan"]), 2)

    def test_mixed_crop_and_padding_share_one_native_canvas(self):
        rows = [{"variant_key": "mixed", "aspect": "9:16", "shots": [
            {"from_s": 0, "to_s": .5}, {"from_s": .5, "to_s": 1,
             "subject_box": {"x": 0, "y": 0, "width": 320, "height": 180}}]}]
        plan = self.plan(rows=rows)
        self.assertEqual(plan["status"], "planned", plan)
        plans = plan["planned"][0]["reframe_plan"]
        self.assertEqual([p["mode"] for p in plans], ["crop", "pad_blur"])
        self.assertEqual((plans[0]["width"], plans[0]["height"]), (plans[1]["width"], plans[1]["height"]))

    def test_every_output_including_batch_has_a_contact_sheet_and_editorial_review(self):
        rows = [{"variant_key": "first", "sku": "A", "locale": "en", "aspect": "1:1"},
                {"variant_key": "batch", "sku": "B", "locale": "en", "aspect": "4:5"}]
        args = {**self.args, "rows": rows}
        plan = ad_variants.render_ad_variants(stage="plan", **args)
        self.assertEqual(plan["status"], "planned", plan)
        for stage in ("render_first", "render_batch"):
            with ad_variants.authorize(stage, plan["plan_hash"], "operator:test"):
                result = ad_variants.render_ad_variants(stage=stage, plan_hash=plan["plan_hash"], **args)
            self.assertEqual(result["status"], "succeeded", result)
        self.assertEqual(len(result["rendered"]), 2)
        for entry in result["rendered"]:
            self.assertEqual(entry["editorial_review"], "pending")
            self.assertTrue(Path(entry["contact_sheet"]).is_file())
            probe = local._probe(Path(entry["output_path"]))
            self.assertTrue(any(s["codec_type"] == "audio" for s in probe["streams"]))
            video = next(s for s in probe["streams"] if s["codec_type"] == "video")
            self.assertEqual(video["sample_aspect_ratio"], "1:1")
            self.assertEqual(video["avg_frame_rate"], "24/1")

    def test_reframe_params_are_validated_before_render(self):
        values = ({"subject_box": {"x": 0, "y": 0, "width": 321, "height": 180}},
                  {"safe_zone": {"top": float("nan")}}, {"safe_zone": {"side": .5}},
                  {"anchor": "shell"}, {"allow_upscale": "true"},
                  {"shots": [{"from_s": 0, "to_s": .4}, {"from_s": .5, "to_s": 1}]},
                  {"shots": [{"from_s": 0, "to_s": 1, "filtergraph": "movie=http"}]},
                  {"scene_times": [1]}, {"scene_times": [float("inf")]},
                  {"shots": [{"from_s": 0, "to_s": 1}], "scene_times": [.5]})
        for fields in values:
            with self.subTest(fields=fields):
                rows = [{"variant_key": "bad", "aspect": "9:16", **fields}]
                plan = self.plan(rows=rows)
                self.assertEqual(plan["status"], "blocked", plan)

    def test_reframe_geometry_is_part_of_approval_hash(self):
        rows = [{"variant_key": "approval", "aspect": "1:1", "anchor": "left"}]
        first = self.plan(rows=rows)
        self.assertEqual(first["status"], "planned", first)
        changed = copy.deepcopy(rows)
        changed[0]["anchor"] = "right"
        self.assertNotEqual(first["plan_hash"], self.plan(rows=changed)["plan_hash"])

    def test_explicit_contain_preserves_whole_master_with_padding(self):
        result = self.plan(rows=[{"variant_key": "contained", "aspect": "9:16"}],
                           brief={"campaign": "contained", "reframe_only": True, "fit": "contain"})
        self.assertEqual(result["status"], "planned", result)
        self.assertEqual(result["planned"][0]["reframe_plan"][0]["mode"], "pad_blur")
        invalid = self.plan(brief={"campaign": "invalid", "reframe_only": True, "fit": "filtergraph"})
        self.assertEqual(invalid["status"], "blocked", invalid)


if __name__ == "__main__":
    unittest.main()
