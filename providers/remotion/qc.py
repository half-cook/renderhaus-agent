from __future__ import annotations

from fractions import Fraction
import math
from pathlib import Path
import re

from providers.ffmpeg.api import execute
from providers.ffmpeg.sandbox import input_file, sha256_file


FILENAME = r"[A-Za-z0-9_-]+__[A-Za-z0-9_-]+__[A-Za-z0-9_-]+__(?:9x16|1x1|4x5|16x9|2p39x1)__v[1-9][0-9]*\.mp4"


def _rate(value) -> float | None:
    try:
        rate = float(Fraction(str(value)))
        return rate if math.isfinite(rate) and rate > 0 else None
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def inspect_file(job: Path, path: str, preset: dict, spec: dict) -> dict:
    source = input_file(job, path)
    checksum = sha256_file(source)
    checks = []
    warnings = ["Delivery preset is a placeholder; confirm the channel specification.",
                "Caption, legal-copy, price and editorial verification require a planner vision pass on the extracted frames."]
    metrics = {}

    def check(name, passed, detail, severity="error"):
        checks.append({"name": name, "severity": severity, "pass": bool(passed), "detail": str(detail)})

    def op(name, params=None):
        result = execute(name, job, str(source.relative_to(job)), params)
        if not result["ok"]:
            check(name, False, result.get("error", "Media measurement failed."))
            return None
        metrics[name] = {key: value for key, value in result["metrics"].items() if key != "timestamps_s"}
        return result

    probe = op("probe")
    if probe:
        data = probe["metrics"]
        video = next((s for s in data["streams"] if s.get("codec_type") == "video"), {})
        audio = next((s for s in data["streams"] if s.get("codec_type") == "audio"), {})
        fmt = data.get("format", {})
        duration = float(fmt.get("duration", 0))
        cadence = op("frame_cadence")
        fps = cadence["metrics"].get("cadence_fps") if cadence else _rate(video.get("avg_frame_rate"))
        width, height = video.get("width"), video.get("height")
        check("container", "mp4" in fmt.get("format_name", "").split(",") and source.suffix == ".mp4",
              f"Container {fmt.get('format_name')}; extension {source.suffix}.")
        for name, key, expected in (("video_codec", "codec_name", preset["video_codec"]),
                                    ("profile", "profile", preset["profile"]),
                                    ("pix_fmt", "pix_fmt", preset["pix_fmt"])):
            check(name, video.get(key) == expected, f"Expected {expected}; measured {video.get(key)}.")
        resolution_ok = (isinstance(width, int) and isinstance(height, int) and
                         2 <= width <= preset["max_width"] and 2 <= height <= preset["max_height"])
        resolution_ok = resolution_ok and all(video.get(key) == spec.get("expected_" + key, video.get(key))
                                             for key in ("width", "height"))
        check("resolution", resolution_ok, f"Measured {width}x{height}; expected "
              f"{spec.get('expected_width', 'native')}x{spec.get('expected_height', 'native')}; "
              f"maximum {preset['max_width']}x{preset['max_height']}.")
        check("sar", video.get("sample_aspect_ratio") == "1:1", f"SAR {video.get('sample_aspect_ratio')}.")
        check("fps", fps is not None and preset["fps"]["min"] <= fps <= preset["fps"]["max"]
              and math.isclose(fps, spec.get("expected_fps", fps), abs_tol=.001),
              f"Measured FPS {fps}; expected {spec.get('expected_fps', 'preserve')}.")
        tolerance_s = 1 / fps if fps else .001
        expected_duration = spec.get("expected_duration_s")
        check("duration", math.isfinite(duration) and 0 < duration <= 600 and
              (expected_duration is None or abs(duration - expected_duration) <= tolerance_s + .002),
              f"Duration {duration}s; expected {expected_duration if expected_duration is not None else 'unspecified'}; "
              f"tolerance one frame ({tolerance_s:.6f}s).")
        if cadence:
            values = metrics["frame_cadence"]
            check("cadence", values.get("cfr") is True, f"Decoded cadence {values}.")
            check("frame_count", fps is not None and abs(values.get("sample_count", -1000) - duration * fps) <= 1.1,
                  f"Decoded {values.get('sample_count')} frames; metadata duration {duration}s at {fps} FPS.")
        need_audio = spec.get("require_audio", True)
        check("audio_present", bool(audio) or not need_audio, "Audio stream present." if audio else "No audio stream.")
        if audio:
            check("audio_codec", audio.get("codec_name") == preset["audio"]["codec"],
                  f"Expected {preset['audio']['codec']}; measured {audio.get('codec_name')}.")
            check("sample_rate", str(audio.get("sample_rate")) == str(preset["audio"]["sample_rate"]),
                  f"Expected {preset['audio']['sample_rate']} Hz; measured {audio.get('sample_rate')}.")
            channels = audio.get("channels")
            check("channels", channels in preset["audio"]["channels"] and
                  channels == spec.get("audio_channels", channels) and
                  audio.get("channel_layout") in {1: {"mono"}, 2: {"stereo"}}.get(channels, set()),
                  f"Channels {channels}; layout {audio.get('channel_layout')}.")
            volume = op("volume_stats")
            if volume:
                peak = volume["metrics"].get("max_volume_db")
                mean = volume["metrics"].get("mean_volume_db")
                check("clipping", peak is not None and peak < -.1, f"Sample peak {peak} dBFS; ceiling -0.1.")
                check("audible", not need_audio or mean is not None and mean > -90, f"Mean volume {mean} dBFS.")
            target = preset.get("loudness")
            if target:
                settings = {key: spec.get(key, target[key]) for key in ("I", "TP", "LRA")}
                measured = op("measure_loudness", settings)
                if measured:
                    loudness = measured["metrics"]
                    value, peak = loudness.get("integrated_lufs"), loudness.get("true_peak_db")
                    tolerance = spec.get("tolerance_lu", target["tolerance_lu"])
                    check("loudness", duration >= 3 and value is not None and abs(value - settings["I"]) <= tolerance,
                          f"Integrated {value} LUFS; target {settings['I']} +/- {tolerance}. "
                          "Programme loudness; dialogue gating unavailable. Clips below 3s cannot be certified.")
                    check("true_peak", peak is not None and peak <= settings["TP"],
                          f"True peak {peak} dBTP; ceiling {settings['TP']}.")
            silence = op("detect_silence", {"noise": spec.get("noise", -50), "d": spec.get("silence_d", .5)})
            if silence:
                _interval_check(check, "silence", silence["metrics"], spec.get("allowed_silence", []), tolerance_s)
        for name, params in (("black", {"d": spec.get("black_d", .5), "pix_th": spec.get("pix_th", .1)}),
                             ("freeze", {"d": spec.get("freeze_d", .5), "n": spec.get("n", .001)})):
            detected = op("detect_" + name, params)
            if detected:
                _interval_check(check, name, detected["metrics"], spec.get("allowed_" + name, []), tolerance_s)
        if preset["faststart"]:
            fast = op("check_faststart")
            if fast:
                check("faststart", fast["metrics"]["faststart"], f"Atom order {fast['metrics']['atom_order']}.")
        sheet = op("contact_sheet", {"every_s": max(.1, duration / 5), "cols": 5, "rows": 1})
        timestamps = cadence["metrics"]["timestamps_s"] if cadence else []
        times = [timestamps[int((len(timestamps) - 1) * f)] if timestamps else
                 max(0, min(duration * f, duration - tolerance_s)) for f in (.05, .25, .5, .75, .95)]
        frames = op("extract_frames", {"times": times,
                                       "width": min(1920, max(16, width or 640))})
        check("contact_sheet", bool(sheet and sheet["outputs"]), "Contact sheet generated for visual review.")
        check("review_frames", bool(frames and len(frames["outputs"]) == 5), "Five sampled frames generated for visual review.")
        if spec.get("master_path"):
            comparison = op("ssim", {"reference_path": spec["master_path"]})
            if comparison:
                check("master_ssim", True, comparison["metrics"], "warn")
        if "overlay_boxes" in spec:
            safe = spec.get("safe_zone", {"top": .08, "bottom": .12, "side": .06})
            inside = bool(width and height) and all(
                box["x"] >= width * safe.get("side", .06) and
                box["x"] + box["width"] <= width * (1 - safe.get("side", .06)) and
                box["y"] >= height * safe.get("top", .08) and
                box["y"] + box["height"] <= height * (1 - safe.get("bottom", .12))
                for box in spec["overlay_boxes"])
            check("overlay_geometry", inside, "Declared overlay geometry only; rendered pixels require vision review.")
    else:
        video, audio, duration, fps, width, height, sheet, frames = {}, {}, None, None, None, None, None, None
    expected_name = spec.get("expected_filename")
    check("filename", source.name == expected_name if expected_name else bool(re.fullmatch(FILENAME, source.name)),
          f"Filename {source.name}; required campaign__sku__locale__aspect__v<n>.mp4 or exact approved intermediate name.")
    check("file_size", source.stat().st_size <= preset["max_file_bytes"],
          f"Bytes {source.stat().st_size}; maximum {preset['max_file_bytes']}.")
    check("checksum", sha256_file(source) == checksum and checksum == spec.get("expected_sha256", checksum),
          f"SHA-256 {checksum}; file remained unchanged during QC.")
    check("vision_review", not spec.get("require_vision", False),
          "Planner vision/OCR/editorial review pending. Geometry is the only deterministic safe-zone check.",
          "error" if spec.get("require_vision", False) else "warn")
    failures = [f"{c['name']}: {c['detail']}" for c in checks if not c["pass"] and c["severity"] == "error"]
    return {"file": str(source), "output_path": str(source), "sha256": checksum,
            "bytes": source.stat().st_size, "width": width, "height": height, "fps": fps,
            "duration_s": duration, "passed": not failures, "technical_passed": not failures,
            "audio_present": bool(audio),
            "checks": checks, "failures": failures, "metrics": metrics, "warnings": warnings,
            "visual_review": "pending", "contact_sheet": sheet["outputs"][0]["path"] if sheet else None,
            "review_frames": [o["path"] for o in frames["outputs"]] if frames else [],
            "review_assets": [{"output_path": o["path"], "sha256": o["sha256"], "bytes": o["bytes"]}
                              for result in (sheet, frames) if result for o in result["outputs"]]}


def _interval_check(check, name: str, metrics: dict, allowed: list[dict], tolerance: float) -> None:
    intervals = metrics["intervals"]
    covered = []
    for span in sorted(allowed, key=lambda item: item["start_s"]):
        if covered and span["start_s"] <= covered[-1]["end_s"] + 1e-9:
            covered[-1]["end_s"] = max(covered[-1]["end_s"], span["end_s"])
        else:
            covered.append(dict(span))
    unexpected = [interval for interval in intervals if not any(
        interval["start_s"] >= span["start_s"] - tolerance and
        interval["end_s"] <= span["end_s"] + tolerance for span in covered)]
    check(name, not unexpected, f"Unexpected {name} intervals {unexpected}; allowed {allowed}.")


def validate_file_report(job: Path, file: dict, preset: dict) -> bool:
    """Bind a complete saved technical report to the unchanged local artifact."""
    try:
        path = input_file(job, file.get("file"))
        if (file.get("output_path") != str(path) or file.get("passed") is not True or
                file.get("technical_passed") is not True or file.get("failures") or
                file.get("sha256") != sha256_file(path) or file.get("bytes") != path.stat().st_size):
            return False
        checks = file.get("checks")
        if not isinstance(checks, list) or not all(isinstance(c, dict) for c in checks):
            return False
        names = [c.get("name") for c in checks]
        required = {"container", "video_codec", "profile", "pix_fmt", "resolution", "sar", "fps", "duration",
                    "cadence", "frame_count", "audio_present", "black", "freeze", "faststart", "filename",
                    "file_size", "checksum", "vision_review", "contact_sheet", "review_frames"}
        if file.get("audio_present"):
            required |= {"audio_codec", "sample_rate", "channels", "clipping", "audible", "silence"}
            if preset.get("loudness"):
                required |= {"loudness", "true_peak"}
        images = file.get("review_assets")
        frames = file.get("review_frames")
        if not isinstance(images, list) or len(images) != 6 or not isinstance(frames, list) or len(frames) != 5:
            return False
        expected_images = [file.get("contact_sheet"), *frames]
        if len(set(expected_images)) != 6 or {image.get("output_path") for image in images} != set(expected_images):
            return False
        for image in images:
            image_path = input_file(job, image.get("output_path"))
            extension = ".jpg" if image.get("output_path") == file.get("contact_sheet") else ".png"
            if (image.get("output_path") != str(image_path) or image_path.suffix != extension or
                    image.get("sha256") != sha256_file(image_path) or image.get("bytes") != image_path.stat().st_size):
                return False
        return (required <= set(names) and len(names) == len(set(names)) and
                all(c.get("severity") == "error" and c.get("pass") is True
                    for c in checks if c.get("name") in required - {"vision_review"}) and
                not any(c.get("severity") == "error" and c.get("pass") is not True for c in checks))
    except (ValueError, OSError, TypeError, AttributeError):
        return False
