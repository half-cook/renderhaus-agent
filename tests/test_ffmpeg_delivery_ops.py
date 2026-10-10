from concurrent.futures import ThreadPoolExecutor
import math
from pathlib import Path
import shutil
import subprocess
import sys

from jsonschema import Draft202012Validator
import tempfile
import unittest
from unittest.mock import patch
from functools import wraps

from providers.ffmpeg.api import ffmpeg_tool, validate_arguments
from providers.ffmpeg.ops import tool_schema


NEW_OPS = ("measure_loudness", "loudnorm_mux_aac", "mux_aac", "transcode_h264", "detect_black",
           "detect_freeze", "detect_silence", "ssim")
MEASURED = {"measured_I": -22.0, "measured_TP": -19.0, "measured_LRA": 0.0,
            "measured_thresh": -32.0, "offset": 0.0}


def cases(names, rows):
    names = [name.strip() for name in names.split(',')]
    def decorate(function):
        @wraps(function)
        def run(self, **outer):
            for row in rows:
                values = row if len(names) > 1 else (row,)
                arguments = {**outer, **dict(zip(names, values))}
                with self.subTest(**arguments):
                    function(self, **arguments)
        return run
    return decorate


def call(op, params=None, source="source.mkv"):
    return ffmpeg_tool(op, "job-1", source, params)


def render_fixture(path, *args):
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args,
                    "-threads", "1", str(path)], check=True, capture_output=True,
                   stdin=subprocess.DEVNULL, timeout=25)
    return path




def pass2_params(measurement, **changes):
    return {"I": -14, "TP": -1.5, "LRA": 11,
            "measured_I": measurement["input_i"], "measured_TP": measurement["input_tp"],
            "measured_LRA": measurement["input_lra"], "measured_thresh": measurement["input_thresh"],
            "offset": measurement["target_offset"], **changes}


class FfmpegDeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.job = self.root / "job-1"
        self.job.mkdir()
        (self.job / "source.mkv").write_bytes(b"invalid media")
        environment = patch.dict("os.environ", {"RENDERHAUS_MEDIA_DIR": str(self.root), "FFMPEG_DRY_RUN": "false"})
        environment.start()
        self.addCleanup(environment.stop)

    def setenv(self, name, value):
        change = patch.dict("os.environ", {name: value})
        change.start()
        self.addCleanup(change.stop)

    def setattr(self, target, name, value):
        change = patch.object(target, name, value)
        change.start()
        self.addCleanup(change.stop)

    def create_media(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("Installed ffmpeg and ffprobe are required")
        return render_fixture(self.job / "source.mkv", "-f", "lavfi", "-i",
                              "testsrc2=size=160x90:rate=24:duration=6", "-f", "lavfi", "-i",
                              "sine=frequency=440:sample_rate=48000:duration=6",
                              "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-shortest")

    def assert_invalid_parameters(self, op, params):
        arguments = {"op": op, "job_id": "job-1", "input_path": "source.mkv", "params": params}
        self.assertTrue(list(Draft202012Validator(tool_schema()["inputSchema"]).iter_errors(arguments)))
        with self.assertRaises(ValueError):
            validate_arguments(arguments)

    @cases("op,params", [
        ("measure_loudness", {}), ("loudnorm_mux_aac", MEASURED), ("mux_aac", {}),
        ("transcode_h264", {"intent": "review-proxy"}), ("detect_black", {}),
        ("detect_freeze", {}), ("detect_silence", {}), ("ssim", {"reference_path": "master.mkv"}),
    ])
    def test_new_ops_validate_in_dry_run_without_media(self, op, params):
        self.setenv("FFMPEG_DRY_RUN", "true")
        result = call(op, params, "not-yet-rendered.mkv")
        assert result["ok"], result
        assert result["status"] == "dry_run"
        assert not result["outputs"]


    @cases("op,params", [
        ("measure_loudness", {"I": -31}), ("measure_loudness", {"TP": 1}),
        ("measure_loudness", {"LRA": 0}), ("mux_aac", {"bitrate_kbps": 63}),
        ("mux_aac", {"bitrate_kbps": 321}), ("detect_black", {"d": .09}),
        ("detect_black", {"pix_th": .51}), ("detect_freeze", {"n": -.01}),
        ("detect_freeze", {"n": .11}), ("detect_silence", {"noise": -61}),
        ("detect_silence", {"noise": -19}), ("transcode_h264", {"intent": "custom"}),
        ("loudnorm_mux_aac", {}), ("loudnorm_mux_aac", {k: v for k, v in MEASURED.items() if k != "offset"}),
        ("loudnorm_mux_aac", {**MEASURED, "measured_I": -100}), ("ssim", {}),
    ])
    def test_invalid_parameters_fail_schema_and_code(self, op, params):
        arguments = {"op": op, "job_id": "job-1", "input_path": "source.mkv", "params": params}
        assert list(Draft202012Validator(tool_schema()["inputSchema"]).iter_errors(arguments))
        with self.assertRaises(ValueError):
            validate_arguments(arguments)


    @cases("value", [math.nan, math.inf, -math.inf, True, "-14", 10**1000])
    @cases("op,key", [("measure_loudness", "I"), ("mux_aac", "bitrate_kbps"),
                                        ("detect_black", "pix_th"), ("detect_freeze", "n"),
                                        ("detect_silence", "noise")])
    def test_numeric_attacks_fail_schema_and_code(self, op, key, value):
        self.assert_invalid_parameters(op, {key: value})


    @cases("op", NEW_OPS)
    def test_free_form_options_are_refused(self, op):
        assert not call(op, {"args": "-i https://example.com/x; cat /etc/passwd"})["ok"]


    @cases("reference", ["../outside.mkv", "-i", "ref\n.mkv", "r\u0435f.mkv",
                                           "https://example.com/x", "file:source.mkv", "a/../../x"])
    def test_ssim_reference_lexical_attacks_fail_before_dispatch(self, reference):
        self.setenv("FFMPEG_DRY_RUN", "true")
        result = call("ssim", {"reference_path": reference})
        assert not result["ok"], result
        arguments = {"op": "ssim", "job_id": "job-1", "input_path": "source.mkv",
                     "params": {"reference_path": reference}}
        assert list(Draft202012Validator(tool_schema()["inputSchema"]).iter_errors(arguments))


    def test_ssim_reference_symlink_escape_fails_in_dry_run(self):
        job = self.job
        outside = job.parent / "outside.mkv"
        outside.write_bytes(b"outside")
        (job / "ref.mkv").symlink_to(outside)
        self.setenv("FFMPEG_DRY_RUN", "true")
        assert not call("ssim", {"reference_path": "ref.mkv"})["ok"]


    def test_probe_includes_codec_profile_and_audio_layout(self):
        self.create_media()
        result = call("probe")
        assert result["ok"], result
        video = next(s for s in result["metrics"]["streams"] if s["codec_type"] == "video")
        audio = next(s for s in result["metrics"]["streams"] if s["codec_type"] == "audio")
        assert video["profile"] in {"High", "Main", "Constrained Baseline"}
        assert "channel_layout" in audio
        assert audio["channel_layout"] in {None, "mono"}


    def test_measure_then_normalize_remeasures_aac_and_preserves_video(self):
        self.create_media()
        measured = call("measure_loudness")
        assert measured["ok"], measured
        metrics = measured["metrics"]
        assert metrics["integrated_lufs"] == metrics["input_i"]
        assert metrics["true_peak_db"] == metrics["input_tp"]
        assert metrics["lra"] == metrics["input_lra"]
        assert abs(metrics["ebur128"]["integrated_lufs"] - metrics["integrated_lufs"]) < .2
        finished = call("loudnorm_mux_aac", pass2_params(metrics))
        assert finished["ok"], finished
        assert abs(finished["metrics"]["after"]["integrated_lufs"] + 14) <= .5
        assert finished["metrics"]["after"]["true_peak_db"] <= -1.5
        assert finished["metrics"]["normalization_type"] in {"linear", "dynamic"}
        assert finished["metrics"]["dynamic_fallback"] == (finished["metrics"]["normalization_type"] == "dynamic")
        output = finished["outputs"][0]["path"]
        probe = call("probe", source=output)
        video = next(s for s in probe["metrics"]["streams"] if s["codec_type"] == "video")
        audio = next(s for s in probe["metrics"]["streams"] if s["codec_type"] == "audio")
        assert (video["width"], video["height"], video["r_frame_rate"]) == (160, 90, "24/1")
        assert audio["codec_name"] == "aac"
        assert audio["sample_rate"] == "48000"
        assert audio["channels"] == 1
        assert call("check_faststart", source=output)["metrics"]["faststart"]


    def test_normalization_rejects_stale_or_other_target_measurements(self):
        self.create_media()
        measured = call("measure_loudness")["metrics"]
        for changes in ({"measured_I": measured["input_i"] + 1}, {"offset": measured["target_offset"] + 2},
                        {"I": -5, "TP": -9}):
            result = call("loudnorm_mux_aac", pass2_params(measured, **changes))
            assert not result["ok"], result
            assert "match" in result["error"]
            assert not result["outputs"]


    @cases("silent", [False, True])
    def test_loudness_refuses_absent_or_silent_audio(self, silent):
        job = self.job
        args = ["-f", "lavfi", "-i", "color=red:size=160x90:rate=24:duration=4"]
        if silent:
            args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "4", "-c:a", "pcm_s16le"]
        args += ["-c:v", "libx264"]
        render_fixture(job / "source.mkv", *args)
        result = call("measure_loudness")
        assert not result["ok"], result
        assert "audio" in result["error"].lower() or "silent" in result["error"].lower()


    def test_mux_aac_preserves_stereo_layout_and_checks_faststart(self):
        job = self.job
        render_fixture(job / "source.mkv", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=25:duration=4",
                       "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=4",
                       "-af", "pan=stereo|c0=c0|c1=c0", "-c:v", "libx264", "-c:a", "pcm_s16le", "-shortest")
        result = call("mux_aac", {"bitrate_kbps": 128})
        assert result["ok"], result
        output = result["outputs"][0]["path"]
        probe = call("probe", source=output)
        audio = next(s for s in probe["metrics"]["streams"] if s["codec_type"] == "audio")
        assert (audio["sample_rate"], audio["channels"], audio["channel_layout"]) == ("48000", 2, "stereo")
        assert call("check_faststart", source=output)["metrics"]["faststart"]


    def test_detectors_report_real_segments_and_eof_tails(self):
        job = self.job
        render_fixture(job / "source.mkv", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24:duration=1",
                       "-f", "lavfi", "-i", "color=black:size=160x90:rate=24:duration=1",
                       "-f", "lavfi", "-i", "color=red:size=160x90:rate=24:duration=1",
                       "-f", "lavfi", "-i", "aevalsrc=if(lt(t\\,1)\\,0.1*sin(2*PI*440*t)\\,0):s=48000:d=3",
                       "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
                       "-map", "[v]", "-map", "3:a", "-c:v", "libx264", "-c:a", "pcm_s16le")
        expected = {"detect_black": [(1, 2)], "detect_freeze": [(1, 2), (2, 3)],
                    "detect_silence": [(1, 3)]}
        for op, spans in expected.items():
            result = call(op)
            assert result["ok"], result
            intervals = result["metrics"]["intervals"]
            assert len(intervals) == len(spans), result
            for interval, (start, end) in zip(intervals, spans):
                assert abs(interval["start_s"] - start) <= .05
                assert abs(interval["end_s"] - end) <= .05
                assert abs(interval["duration_s"] - (end - start)) <= .05


    def test_black_tail_reaches_media_end(self):
        job = self.job
        render_fixture(job / "source.mkv", "-f", "lavfi", "-i", "color=black:size=160x90:rate=24:duration=2",
                       "-c:v", "libx264")
        result = call("detect_black")
        assert result["ok"], result
        assert result["metrics"]["intervals"] == [{"start_s": 0.0, "end_s": 2.0, "duration_s": 2.0}]


    def test_ssim_compares_actual_first_and_last_frames_and_rejects_size_mismatch(self):
        job = self.job
        self.create_media()
        shutil.copyfile(job / "source.mkv", job / "reference.mkv")
        result = call("ssim", {"reference_path": "reference.mkv"})
        assert result["ok"], result
        assert result["metrics"]["first_frame_ssim"] == 1
        assert result["metrics"]["last_frame_ssim"] == 1
        render_fixture(job / "small.mkv", "-f", "lavfi", "-i", "testsrc2=size=80x46:rate=24:duration=6",
                       "-c:v", "libx264")
        mismatch = call("ssim", {"reference_path": "small.mkv"})
        assert not mismatch["ok"], mismatch
        assert "dimension" in mismatch["error"]


    @cases("intent", ["social-vertical", "social-feed", "web-1080p", "broadcast-proxy",
                                        "review-proxy", "email-720p", "podcast-streaming"])
    def test_h264_intents_preserve_native_small_dimensions_and_fps(self, intent):
        self.create_media()
        result = call("transcode_h264", {"intent": intent})
        assert result["ok"], result
        output = result["outputs"][0]["path"]
        probe = call("probe", source=output)
        video = next(s for s in probe["metrics"]["streams"] if s["codec_type"] == "video")
        assert (video["width"], video["height"], video["r_frame_rate"]) == (160, 90, "24/1")
        assert video["codec_name"] == "h264"
        assert video["pix_fmt"] == "yuv420p"
        assert call("check_faststart", source=output)["metrics"]["faststart"]


    def test_concurrent_muxes_do_not_overwrite(self):
        self.create_media()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: call("mux_aac"), range(4)))
        assert all(result["ok"] for result in results), results
        paths = [result["outputs"][0]["path"] for result in results]
        assert len(set(paths)) == 4
        assert all(Path(path).is_file() for path in paths)


    def test_frame_cadence_reads_full_real_timestamps(self):
        self.create_media()
        result = call("frame_cadence")
        assert result["ok"], result
        metrics = result["metrics"]
        assert metrics["sample_count"] == 144
        assert metrics["cfr"]
        assert abs(metrics["cadence_fps"] - 24) < .001
        assert metrics["first_frame_s"] == 0
        assert metrics["last_frame_s"] == 5.958


    def test_cadence_detects_variable_timestamps_even_with_nominal_rate(self):
        job = self.job
        render_fixture(job / "source.mkv", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24:duration=2",
                       "-vf", "setpts='if(lt(N,24),N/(24*TB),(24+(N-24)*2)/(24*TB))'",
                       "-fps_mode", "passthrough", "-c:v", "libx264")
        result = call("frame_cadence")
        assert result["ok"], result
        assert not result["metrics"]["cfr"]
        assert result["metrics"]["max_interval_s"] > result["metrics"]["min_interval_s"] * 1.5


    def test_normalization_reports_real_dynamic_fallback(self):
        job = self.job
        render_fixture(job / "source.mkv", "-f", "lavfi", "-i", "color=red:size=80x46:rate=5:duration=30",
                       "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=30",
                       "-af", "volume=if(lt(t\\,15)\\,0.4\\,1):eval=frame",
                       "-c:v", "libx264", "-c:a", "pcm_s16le", "-shortest")
        measured = call("measure_loudness", {"LRA": 1})
        assert measured["ok"], measured
        assert measured["metrics"]["input_lra"] > 1
        result = call("loudnorm_mux_aac", pass2_params(measured["metrics"], LRA=1))
        assert result["ok"], result
        assert result["metrics"]["normalization_type"] == "dynamic"
        assert result["metrics"]["dynamic_fallback"]
        assert "dynamic" in " ".join(result["warnings"]).lower()


    @cases("op", ["measure_loudness", "mux_aac", "transcode_h264", "detect_black",
                                   "detect_freeze", "detect_silence", "frame_cadence", "ssim"])
    def test_delivery_ops_refuse_sources_over_600_seconds(self, op):
        job = self.job
        render_fixture(job / "source.mkv", "-f", "lavfi", "-i", "color=red:size=16x16:rate=1:duration=601",
                       "-c:v", "libx264")
        params = {"intent": "review-proxy"} if op == "transcode_h264" else (
            {"reference_path": "source.mkv"} if op == "ssim" else {})
        result = call(op, params)
        assert not result["ok"], result
        assert "600" in result["error"]


    def test_review_transcode_caps_dimensions_without_upscale(self):
        job = self.job
        render_fixture(job / "source.mkv", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24:duration=1",
                       "-c:v", "libx264")
        result = call("transcode_h264", {"intent": "review-proxy"})
        assert result["ok"], result
        assert (result["metrics"]["width"], result["metrics"]["height"]) == (960, 540)
        assert not result["metrics"]["upscaled"]
        assert result["metrics"]["source_resolution"] == {"width": 1280, "height": 720}


    def test_transcode_refuses_partial_output_at_size_cap(self):
        self.create_media()
        from providers.ffmpeg import delivery

        self.setattr(delivery, "MAX_OUTPUT_BYTES", 2048)
        result = call("transcode_h264", {"intent": "review-proxy"})
        assert not result["ok"], result
        assert not result["outputs"]
        assert not list(self.job.glob("delivery-*.mp4"))


    @cases("op", ["detect_black", "detect_freeze", "detect_silence"])
    def test_detectors_refuse_truncated_logs(self, op):
        from providers.ffmpeg.api import ProcessResult
        from providers.ffmpeg.ops import OPS

        assert op in OPS
        with self.assertRaisesRegex(ValueError, "complete|truncated"):
            OPS[op].parse([ProcessResult(0, b"", b"", stderr_truncated=True)])


    def test_h264_missing_installed_encoder_returns_actionable_error(self):
        self.create_media()
        from providers.ffmpeg import api

        original = api._bounded_run

        def no_x264(argv, *args, **kwargs):
            if "-encoders" in argv:
                return api.ProcessResult(0, b"Encoders:\n V..... h264_fake Fake\n", b"")
            return original(argv, *args, **kwargs)

        self.setattr(api, "_bounded_run", no_x264)
        result = call("transcode_h264", {"intent": "review-proxy"})
        assert not result["ok"], result
        assert "libx264" in result["error"]

    def test_job_and_source_paths_reject_schema_and_code_attacks(self):
        self.setenv("FFMPEG_DRY_RUN", "true")
        validator = Draft202012Validator(tool_schema()["inputSchema"])
        for op in NEW_OPS:
            params = MEASURED if op == "loudnorm_mux_aac" else (
                {"intent": "review-proxy"} if op == "transcode_h264" else
                {"reference_path": "source.mkv"} if op == "ssim" else {})
            for field, values in (("job_id", ("../job", "-i", "job\n", "jоb")),
                                  ("input_path", ("../source.mkv", "-i", "source.mkv\n", "sоurce.mkv", "https://example.com/a"))):
                for value in values:
                    with self.subTest(op=op, field=field, value=value):
                        arguments = {"op": op, "job_id": "job-1", "input_path": "source.mkv", "params": params, field: value}
                        self.assertTrue(list(validator.iter_errors(arguments)))
                        with self.assertRaises(ValueError):
                            validate_arguments(arguments)

    def test_delivery_module_imports_without_api_import_order(self):
        process = subprocess.run([sys.executable, "-c", "from providers.ffmpeg.delivery import INTENTS; assert INTENTS"],
                                 cwd=Path(__file__).resolve().parents[1], stdin=subprocess.DEVNULL,
                                 capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr.decode())

    @cases("nominal", [None, "0/0", "0/1", "N/A"])
    def test_cadence_uses_decoded_timestamps_when_nominal_rate_is_unknown(self, nominal):
        from providers.ffmpeg.delivery import finish_cadence

        result = finish_cadence(self.job, self.job / "source.mkv", {}, [],
                                {"timestamps_s": [0.0, 0.5, 1.0], "nominal_frame_rate": nominal, "time_base": "1/1000"})
        self.assertTrue(result["cfr"])
        self.assertEqual(result["cadence_fps"], 2.0)

if __name__ == "__main__":
    unittest.main()
