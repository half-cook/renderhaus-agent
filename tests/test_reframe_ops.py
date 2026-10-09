from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from providers.ffmpeg import api
from providers.ffmpeg.ops import validate_params, tool_schema


class ReframeParamTests(unittest.TestCase):
    def test_new_ops_are_registered_with_finite_closed_contracts(self):
        schema = tool_schema()["inputSchema"]
        for op in ("reframe_crop", "reframe_pad_blur", "detect_scenes", "crop_plan_preview"):
            with self.subTest(op=op):
                self.assertIn(op, schema["properties"]["op"]["enum"])
        from jsonschema import validate, ValidationError
        base={"job_id":"job","input_path":"master.mp4","op":"reframe_crop"}
        validate({**base,"params":{"aspect":"9:16","allow_upscale":True}},schema)
        with self.assertRaises(ValidationError):
            validate({**base,"params":{"subject_box":{"x":0,"y":0,"width":-1,"height":2}}},schema)
        with self.assertRaises(ValidationError):
            validate({"subject_box": {"x": 1}}, schema["properties"]["params"])

    def test_adversarial_params_are_refused_before_media_or_binary_access(self):
        rows={
            "reframe_crop":[{"aspect":"9:16;exec"},{"crop_box":{"x":0,"y":0,"width":float("nan"),"height":8}},
                            {"subject_box":{"x":0,"y":0,"width":10**1000,"height":8}},
                            {"safe_zone":{"side":.5}},{"safe_zone":{"top":.49,"bottom":.49,"side":.49}},
                            {"anchor":"centre\n"},{"allow_upscale":1},{"args":"-i"},
                            {"crop_box":{"x":0,"y":0,"width":7,"height":8}},
                            {"subject_box":{"x":0,"y":0,"width":8,"height":8,"filtergraph":"-vf"}}],
            "reframe_pad_blur":[{"size":"100000x100000"},{"allow_upscale":"false"},{"blur":10**1000}],
            "detect_scenes":[{"T":.09},{"T":.61},{"T":math.inf},{"T":math.nan},{"T":True},{"T":"-vf"}],
            "crop_plan_preview":[{"source_width":1},{"source_height":16385},{"rotation":45},{"rotation":math.inf},
                                 {"source_width":math.nan},{"source_height":True},{"command":"curl"}],
        }
        for op,values in rows.items():
            for params in values:
                with self.subTest(op=op,params=params), self.assertRaises(ValueError):
                    validate_params(op,params)

    def test_geometry_preview_runs_without_ffmpeg_or_input_media(self):
        with tempfile.TemporaryDirectory() as tmp, patch("providers.ffmpeg.api.shutil.which",return_value=None):
            result=api.execute("crop_plan_preview",Path(tmp),"unused.mp4",
                               {"source_width":1920,"source_height":1080,"aspect":"9:16",
                                "allow_upscale":True,"safe_zone":{"top":0,"bottom":0,"side":0}})
        self.assertTrue(result["ok"],result)
        self.assertEqual((result["metrics"]["width"],result["metrics"]["height"]),(1080,1920))
        self.assertIsNone(result["ffmpeg_version"])
        self.assertEqual(result["outputs"],[])

    def test_scene_parser_never_claims_complete_from_truncated_logs(self):
        from providers.ffmpeg.ops import OPS
        spec=OPS.get("detect_scenes")
        self.assertIsNotNone(spec,"Scene op must exist")
        with self.assertRaises(ValueError):
            spec.parse([api.ProcessResult(0,b"",b"",stderr_truncated=True)])

    def test_scene_parser_ignores_timestamps_in_source_metadata(self):
        from providers.ffmpeg.ops import OPS

        log = (b"    COMMENT : pts_time:0.125\n"
               b"[Parsed_showinfo_1 @ 0x123abc] n: 0 pts: 6400 pts_time:0.5 duration:512\n"
               b"    COMMENT : pts_time:0.75\n")
        metrics = OPS["detect_scenes"].parse([api.ProcessResult(0, b"", log)])
        self.assertEqual(metrics["scene_times"], [.5])

    def test_scene_parser_ignores_metadata_when_no_scene_was_selected(self):
        from providers.ffmpeg.ops import OPS

        metrics = OPS["detect_scenes"].parse([
            api.ProcessResult(0, b"", b"    COMMENT : pts_time:0.5\n    COMMENT : pts_time:0.5\n")])
        self.assertEqual(metrics["scene_times"], [])

    def test_nested_probe_cannot_extend_parent_operation_deadline(self):
        from providers.ffmpeg.ops import OPS, Command, OpSpec
        def outer(directory, source, params):
            result = api.execute("test_inner", directory, source.name)
            if not result["ok"]:
                raise ValueError("Nested inspection exceeded the parent deadline.")
            return []
        def inner(directory, source, params):
            return [Command([sys.executable, "-c", "import time;time.sleep(.4)"])]
        with tempfile.TemporaryDirectory() as tmp, patch.dict(OPS, {
            "test_outer": OpSpec({}, outer, binary="python3", timeout_s=.05),
            "test_inner": OpSpec({}, inner, binary="python3", timeout_s=1),
        }):
            directory = Path(tmp)
            (directory / "source.mp4").write_bytes(b"media")
            started = time.monotonic()
            result = api.execute("test_outer", directory, "source.mp4")
            self.assertFalse(result["ok"], result)
            self.assertLess(time.monotonic() - started, .25)

    def test_invalid_measured_fps_is_refused_before_rendering(self):
        from providers.ffmpeg.ops import OPS

        spec, params = validate_params("reframe_crop", {"aspect": "1:1"})
        self.assertIs(spec, OPS["reframe_crop"])
        for fps in (None, "", "0/0", "0/1", "-24/1", "invalid"):
            video = {"avg_frame_rate": fps, "r_frame_rate": fps, "sample_aspect_ratio": "1:1"}
            with self.subTest(fps=fps), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                with patch("providers.ffmpeg.ops._source_metrics",
                           return_value=({"streams": [video]}, video, (320, 180), 1)):
                    with self.assertRaisesRegex(ValueError, "frame rate"):
                        spec.builder(directory, directory / "source.mp4", params)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),"ffmpeg/ffprobe absent")
class ReframeBinaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.job=Path(cls.tmp.name)
        cls.env=patch.dict(os.environ,{"FFMPEG_DRY_RUN":"false"})
        cls.env.start()
        cls.make("master.mp4","testsrc2=s=1920x1080:r=24000/1001:d=0.3",audio=True)
        cls.make("colour.mp4","color=c=red:s=320x180:r=24:d=0.5",audio=True)
        cls.make("edges.mp4", "color=c=red:s=320x180:r=24:d=0.5,"
                 "drawbox=x=0:y=0:w=40:h=180:c=yellow:t=fill,"
                 "drawbox=x=280:y=0:w=40:h=180:c=blue:t=fill", audio=True)
        cls.make("tiny.mp4", "color=c=red:s=160x90:r=24:d=0.2")
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-i",
                        str(cls.job / "tiny.mp4"), "-c", "copy", "-metadata", "comment=pts_time:0.1",
                        str(cls.job / "metadata.mkv")], check=True, capture_output=True, timeout=30)
        cls.make("anamorphic.mp4", "color=c=red:s=720x480:r=24:d=0.2,setsar=32/27")
        subprocess.run(["ffmpeg","-nostdin","-hide_banner","-v","error","-f","lavfi","-i",
                        "color=c=black:s=160x90:r=24:d=0.5","-f","lavfi","-i",
                        "color=c=white:s=160x90:r=24:d=0.5","-filter_complex","[0:v][1:v]concat=n=2:v=1:a=0[v]",
                        "-map","[v]","-c:v","libx264","-threads","1",str(cls.job/"scenes.mp4")],
                       check=True,capture_output=True,timeout=30)
        subprocess.run(["ffmpeg","-nostdin","-hide_banner","-v","error","-display_rotation:v:0","90","-i",str(cls.job/"master.mp4"),
                        "-c","copy",str(cls.job/"phone.mp4")],
                       check=True,capture_output=True,timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        cls.tmp.cleanup()

    @classmethod
    def make(cls,name,video,audio=False):
        argv=["ffmpeg","-nostdin","-hide_banner","-v","error","-f","lavfi","-i",video]
        if audio:
            argv += ["-f","lavfi","-i","sine=frequency=440:sample_rate=48000:duration=0.5"]
        argv += ["-c:v","libx264","-threads","1","-pix_fmt","yuv420p"]
        if audio:
            argv += ["-c:a","aac","-shortest"]
        subprocess.run([*argv,str(cls.job/name)],check=True,capture_output=True,timeout=30)

    def call(self,op,source="master.mp4",**params):
        result=api.execute(op,self.job,source,params)
        self.assertTrue(result["ok"],result)
        return result

    def probe(self,path):
        r=subprocess.run(["ffprobe","-hide_banner","-v","error","-show_streams","-show_format","-of","json",path],
                         check=True,capture_output=True,timeout=15)
        return json.loads(r.stdout)

    def test_explicit_1080p_portrait_has_exact_dims_square_pixels_same_fps_and_audio(self):
        r=self.call("reframe_crop",aspect="9:16",allow_upscale=True,safe_zone={"top":0,"bottom":0,"side":0})
        output=self.probe(r["outputs"][0]["path"])
        video=next(s for s in output["streams"] if s["codec_type"]=="video")
        self.assertEqual((video["width"],video["height"]),(1080,1920))
        self.assertEqual(video["sample_aspect_ratio"],"1:1")
        self.assertEqual(video["avg_frame_rate"],"24000/1001")
        self.assertTrue(any(s["codec_type"]=="audio" for s in output["streams"]))
        self.assertEqual(r["metrics"]["source_resolution"],"1920x1080")
        self.assertTrue(r["metrics"]["upscaled"])
        self.assertIn("no added detail"," ".join(r["warnings"]))
        self.assertEqual(video.get("tags",{}).get("rotate","0"),"0")

    def test_default_crop_never_upscales_and_all_aspects_open(self):
        for aspect,expected in [("9:16",(606,1076)),("1:1",(1080,1080)),("4:5",(864,1080)),
                                ("16:9",(1920,1080)),("2.39:1",(1920,804))]:
            with self.subTest(aspect=aspect):
                r=self.call("reframe_crop",aspect=aspect)
                video=next(s for s in self.probe(r["outputs"][0]["path"])["streams"] if s["codec_type"]=="video")
                self.assertEqual((video["width"],video["height"]),expected)
                self.assertFalse(r["metrics"]["upscaled"])

    def test_pad_preserves_foreground_edges_instead_of_cropping(self):
        r=self.call("reframe_pad_blur",source="edges.mp4",size="9:16",allow_upscale=True,
                    safe_zone={"top":0,"bottom":0,"side":0})
        path=r["outputs"][0]["path"]
        p=self.probe(path)
        v=next(s for s in p["streams"] if s["codec_type"]=="video")
        self.assertEqual((v["width"],v["height"]),(1080,1920))
        frame=subprocess.run(["ffmpeg","-nostdin","-hide_banner","-v","error","-i",path,
                              "-frames:v","1","-vf","crop=1080:606:0:656,scale=16:9","-pix_fmt","rgb24",
                              "-f","rawvideo","-"],check=True,capture_output=True,timeout=15).stdout
        self.assertEqual(len(frame),16*9*3)
        left, middle, right = (frame[(4*16+x)*3:(4*16+x)*3+3] for x in (0, 8, 15))
        self.assertGreater(left[0], 200)
        self.assertGreater(left[1], 200)
        self.assertLess(left[2], 40)
        self.assertGreater(middle[0], 200)
        self.assertLess(middle[1], 40)
        self.assertGreater(right[2], 200)
        self.assertLess(right[0], 40)

    def test_scene_detection_returns_cut_at_half_second_and_complete_shot_spans(self):
        r=self.call("detect_scenes",source="scenes.mp4",T=.3)
        self.assertEqual(len(r["metrics"]["scene_times"]),1)
        self.assertAlmostEqual(r["metrics"]["scene_times"][0],.5,places=3)
        self.assertEqual(r["metrics"]["shots"],[{"from_s":0,"to_s":.5},{"from_s":.5,"to_s":1}])

    def test_scene_detection_ignores_pts_time_in_real_source_metadata(self):
        result = self.call("detect_scenes", source="metadata.mkv")
        self.assertEqual(result["metrics"]["scene_times"], [])
        self.assertEqual(result["metrics"]["shots"], [
            {"from_s": 0, "to_s": result["metrics"]["source_duration"]}])

    def test_native_small_pad_and_crop_fallback_decode(self):
        for op, params in [("reframe_pad_blur", {"size": "9:16"}),
                           ("reframe_crop", {"aspect": "9:16", "subject_box": {
                               "x": 0, "y": 0, "width": 160, "height": 90}})]:
            with self.subTest(op=op):
                result = self.call(op, source="tiny.mp4", **params)
                video = next(s for s in self.probe(result["outputs"][0]["path"])["streams"]
                             if s["codec_type"] == "video")
                self.assertEqual((video["width"], video["height"]), (90, 160))
                self.assertFalse(result["metrics"]["upscaled"])

    def test_anamorphic_sources_are_refused_before_pixels_are_distorted(self):
        for op, params in [("reframe_crop", {"aspect": "16:9"}),
                           ("reframe_pad_blur", {"size": "16:9"})]:
            with self.subTest(op=op):
                result = api.execute(op, self.job, "anamorphic.mp4", params)
                self.assertFalse(result["ok"], result)
                self.assertIn("square", result["error"])
                self.assertEqual(result["outputs"], [])

    def test_rotated_phone_clip_is_not_reframed_twice(self):
        r=self.call("reframe_crop",source="phone.mp4",aspect="9:16")
        v=next(s for s in self.probe(r["outputs"][0]["path"])["streams"] if s["codec_type"]=="video")
        self.assertEqual((v["width"],v["height"]),(1080,1920))
        self.assertEqual(r["metrics"]["crop_box"],{"x":0,"y":0,"width":1080,"height":1920})
        self.assertFalse(v.get("side_data_list"),v.get("side_data_list"))

    def test_same_job_concurrent_renders_get_unique_outputs(self):
        def run(_):
            return self.call("reframe_crop",source="colour.mp4",aspect="1:1")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(run,range(2)))
        paths=[r["outputs"][0]["path"] for r in results]
        self.assertEqual(len(set(paths)),2)
        self.assertTrue(all(Path(p).is_file() for p in paths))


if __name__ == "__main__":
    unittest.main()
