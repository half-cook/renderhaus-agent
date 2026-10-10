from __future__ import annotations

from fractions import Fraction
import json
import math
from pathlib import Path
import re
import shutil
import statistics
import time

from providers.ffmpeg.commands import Command, FORMATS, THREADS, _ffmpeg_input, _input
from providers.ffmpeg.sandbox import MAX_OUTPUT_BYTES, input_file, output_file


PRESETS = json.loads((Path(__file__).parents[1] / "remotion" / "delivery_presets.json").read_text())
INTENTS = {name: (preset["max_width"], preset["max_height"], preset["crf"]) for name, preset in PRESETS.items()}
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_PASS1 = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
_MEASURED = dict(zip(("measured_I", "measured_TP", "measured_LRA", "measured_thresh", "offset"), _PASS1))


def _execute(directory, op, source, params=None):
    from providers.ffmpeg.api import execute

    result = execute(op, directory, _input(directory, source)[2:], params)
    if not result["ok"]:
        raise ValueError(result.get("error", "Required media inspection failed."))
    return result["metrics"]


def _media(directory, source, *, audio=False, video=False):
    metadata = _execute(directory, "probe", source)
    streams = metadata["streams"]
    durations = [float(item["duration"]) for item in [metadata["format"], *streams]
                 if item.get("duration") not in {None, "N/A"}]
    if not durations or any(not math.isfinite(d) or d <= 0 or d > 600 for d in durations):
        raise ValueError("Delivery inspection requires a known duration of at most 600 seconds; scans are never truncated.")
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if audio and a is None:
        raise ValueError("No audio stream is available for this operation.")
    if video and v is None:
        raise ValueError("A readable video stream is required for this operation.")
    return metadata, v, a, max(durations)


def _video_properties(video):
    width, height = video.get("width"), video.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or not 2 <= width <= 16384 or not 2 <= height <= 16384:
        raise ValueError("Valid measured video dimensions are required.")
    if video.get("sample_aspect_ratio") not in {None, "1:1", "0:1"}:
        raise ValueError("Delivery requires square source pixels; normalize anamorphic media before delivery.")
    rotations = [item["rotation"] for item in video.get("side_data_list", []) if "rotation" in item]
    rotations += [video.get("tags", {}).get("rotate", 0)]
    if any(float(rotation) % 360 for rotation in rotations):
        raise ValueError("Delivery requires an unrotated source; reframe the displayed source first.")
    try:
        fps = float(Fraction(video["avg_frame_rate"]))
    except (KeyError, ValueError, TypeError, ZeroDivisionError, OverflowError):
        raise ValueError("Delivery requires a valid measured source frame rate.") from None
    if not math.isfinite(fps) or not 1 <= fps <= 120:
        raise ValueError("Delivery supports source frame rates from 1 to 120 fps.")
    return width, height, fps


def _complete(result):
    if result.stdout_truncated or result.stderr_truncated:
        raise ValueError("Measurement logs were truncated; a complete result is required.")


def _loudnorm_filter(params):
    return f"loudnorm=I={params['I']:g}:TP={params['TP']:g}:LRA={params['LRA']:g}"


def _loudnorm_json(result):
    _complete(result)
    blocks = re.findall(r'\{\s*"input_i"[\s\S]*?\}', result.stderr.decode("utf-8", errors="replace"))
    if not blocks:
        raise ValueError("No complete loudnorm measurements were returned.")
    payload = json.loads(blocks[-1])
    for key in (*_PASS1, "output_i", "output_tp", "output_lra", "output_thresh"):
        try:
            value = float(payload[key])
        except (KeyError, ValueError, TypeError, OverflowError):
            raise ValueError("The audio did not produce valid loudnorm measurements.") from None
        if not math.isfinite(value):
            raise ValueError("No measurable audio loudness is available; the audio may be silent.")
        payload[key] = value
    if payload.get("normalization_type") not in {"linear", "dynamic"}:
        raise ValueError("Loudnorm did not report a valid normalization type.")
    return payload


def measure(directory, source, params):
    _, _, _, duration = _media(directory, source, audio=True)
    base = _ffmpeg_input(directory, source) + ["-nostats", "-map", "0:a:0", "-vn", "-sn", "-dn"]
    target = {key: params[key] for key in ("I", "TP", "LRA")}
    return [Command(base + ["-af", _loudnorm_filter(params) + ":print_format=json", "-f", "null", "-"],
                    metrics={"target": target, "source_duration": duration}, stderr_bytes=65536),
            Command(base + ["-af", "ebur128=peak=true:framelog=verbose", "-f", "null", "-"], stderr_bytes=65536)]


def measure_metrics(results):
    payload = _loudnorm_json(results[0])
    _complete(results[1])
    summary = results[1].stderr.decode("utf-8", errors="replace").rsplit("Summary:", 1)
    if len(summary) != 2:
        raise ValueError("No complete EBU R128 summary was returned.")
    ebur128 = {}
    for key, label, unit in (("integrated_lufs", "I", "LUFS"), ("lra", "LRA", "LU"),
                             ("true_peak_db", "Peak", "dBFS")):
        found = re.search(rf"\b{label}:\s*({_NUMBER})\s+{unit}\b", summary[1])
        if not found:
            raise ValueError("The EBU R128 summary lacks finite audio measurements.")
        ebur128[key] = float(found.group(1))
    return {**{key: payload[key] for key in _PASS1}, "integrated_lufs": payload["input_i"],
            "true_peak_db": payload["input_tp"], "lra": payload["input_lra"], "ebur128": ebur128}


def _delivery_source(directory, source, *, require_audio):
    metadata, video, audio, duration = _media(directory, source, audio=require_audio, video=True)
    width, height, _ = _video_properties(video)
    audio_streams = [s for s in metadata["streams"] if s.get("codec_type") == "audio"]
    if len(audio_streams) > 1:
        raise ValueError("Delivery supports one audio stream; choose the intended mix before muxing.")
    if audio and (not isinstance(audio.get("channels"), int) or not 1 <= audio["channels"] <= 8):
        raise ValueError("AAC delivery requires a known supported channel count from 1 to 8.")
    cadence = _execute(directory, "frame_cadence", source)
    return metadata, video, audio, {
        "source_duration": duration, "source_fps": video["avg_frame_rate"], "source_cadence": cadence,
        "source_resolution": {"width": width, "height": height}, "width": width, "height": height,
        "source_audio": audio is not None, "source_channels": audio.get("channels") if audio else None,
        "source_audio_duration": float(audio.get("duration", duration)) if audio else None,
        "source_channel_layout": audio.get("channel_layout") if audio else None,
        "source_video_codec": video.get("codec_name"), "upscaled": False, "warnings": [],
    }


def _aac_args(params):
    return ["-c:a", "aac", "-b:a", f"{params['bitrate_kbps']}k", "-ar", "48000"]


def _mux_command(directory, source, params, metrics, *, audio_filter=None):
    output = output_file(directory, "delivery", ".mp4")
    argv = _ffmpeg_input(directory, source) + ["-nostats", "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy"]
    if audio_filter:
        argv += ["-af", audio_filter + f",atrim=duration={metrics['source_audio_duration']:g}"]
    argv += [*_aac_args(params), "-map_metadata", "-1", "-movflags", "+faststart", "-fs", str(MAX_OUTPUT_BYTES),
             "./" + output.name]
    return Command(argv, [output], metrics, stderr_bytes=65536)


def mux(directory, source, params):
    _, _, _, metrics = _delivery_source(directory, source, require_audio=True)
    return [_mux_command(directory, source, params, metrics)]


def normalize(directory, source, params):
    _, _, _, metrics = _delivery_source(directory, source, require_audio=True)
    target = {key: params[key] for key in ("I", "TP", "LRA")}
    before = _execute(directory, "measure_loudness", source, target)
    if any(abs(params[name] - before[field]) > .005 for name, field in _MEASURED.items()):
        raise ValueError("Supplied pass-one measurements do not match this source at the requested loudness targets.")
    metrics.update(target=target, before=before)
    audio_filter = _loudnorm_filter(params) + ":" + ":".join(f"{name}={params[name]:g}" for name in _MEASURED)
    audio_filter += ":linear=true:print_format=json"
    return [_mux_command(directory, source, params, metrics, audio_filter=audio_filter)]


def normalization_metrics(results):
    payload = _loudnorm_json(results[0])
    kind = payload["normalization_type"]
    return {"pass2": payload, "normalization_type": kind, "dynamic_fallback": kind == "dynamic"}


def finish_delivery(directory, source, params, outputs, metrics):
    output = outputs[0]
    _, video, audio, duration = _media(directory, output, video=True, audio=metrics["source_audio"])
    width, height, fps = _video_properties(video)
    source_fps = float(Fraction(metrics["source_fps"]))
    if metrics["source_audio"]:
        if (audio.get("codec_name") != "aac" or audio.get("sample_rate") != "48000"
                or audio.get("channels") != metrics["source_channels"]
                or (metrics["source_channel_layout"] and audio.get("channel_layout") != metrics["source_channel_layout"])):
            raise ValueError("Delivery output violates audio codec, sample rate or channel preservation.")
    if ((width, height) != (metrics["width"], metrics["height"])
            or abs(duration - metrics["source_duration"]) > max(1 / source_fps, .03)
):
        raise ValueError("Delivery output is incomplete or violates dimensions, duration or cadence; size cap may have truncated it.")
    cadence = _execute(directory, "frame_cadence", output)
    before = metrics["source_cadence"]
    if (cadence["sample_count"] != before["sample_count"] or cadence["cfr"] != before["cfr"]
            or any(abs(a - b) > .002 for a, b in zip(cadence["timestamps_s"], before["timestamps_s"]))):
        raise ValueError("Delivery output changed decoded video frame cadence or frame count.")
    metrics["source_cadence"] = {key: value for key, value in before.items() if key != "timestamps_s"}
    cadence = {key: value for key, value in cadence.items() if key != "timestamps_s"}
    faststart = _execute(directory, "check_faststart", output)
    if not faststart["faststart"]:
        raise ValueError("Delivery output lacks required MP4 faststart.")
    return {"output_duration": duration, "output_cadence": cadence, "faststart": True,
            "output_video_codec": video.get("codec_name"), "output_audio_channels": audio.get("channels") if audio else None}


def finish_normalization(directory, source, params, outputs, metrics):
    final = finish_delivery(directory, source, params, outputs, metrics)
    after = _execute(directory, "measure_loudness", outputs[0], metrics["target"])
    warnings = list(metrics["warnings"])
    if metrics["dynamic_fallback"]:
        warnings.append("Loudnorm fell back to dynamic normalization; linear constraints were infeasible.")
    if metrics["source_duration"] < 3:
        warnings.append("Integrated loudness on clips shorter than 3 seconds is unreliable.")
    if abs(after["integrated_lufs"] - params["I"]) > .5 or after["true_peak_db"] > params["TP"]:
        warnings.append("Final AAC measurement misses the requested loudness or true-peak target; QC must review it.")
    return {**final, "after": after, "warnings": warnings}


def _encoder(directory):
    from providers.ffmpeg.api import _bounded_run, _EXECUTION_DEADLINE

    binary = shutil.which("ffmpeg")
    if binary is None:
        raise ValueError("The local worker requires an installed ffmpeg with libx264.")
    remaining = min(5, _EXECUTION_DEADLINE.get() - time.monotonic())
    if remaining <= 0:
        raise ValueError("Operation exceeded its hard timeout.")
    result = _bounded_run([binary, "-hide_banner", "-encoders"], directory, remaining, stderr_bytes=65536)
    _complete(result)
    if result.returncode or not re.search(r"^\s*V\S{5}\s+libx264\s", result.stdout.decode(), re.MULTILINE):
        raise ValueError("The installed local ffmpeg build lacks the libx264 encoder required for H.264 delivery.")


def transcode(directory, source, params):
    metadata, video, audio, metrics = _delivery_source(directory, source, require_audio=False)
    _encoder(directory)
    cap_width, cap_height, crf = INTENTS[params["intent"]]
    width, height = metrics["width"], metrics["height"]
    factor = min(1, cap_width / width, cap_height / height)
    fitted_width, fitted_height = max(2, math.floor(width * factor / 2) * 2), max(2, math.floor(height * factor / 2) * 2)
    metrics.update(width=fitted_width, height=fitted_height, intent=params["intent"])
    output = output_file(directory, "delivery", ".mp4")
    argv = _ffmpeg_input(directory, source) + ["-nostats", "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", f"scale={fitted_width}:{fitted_height}:flags=lanczos,setsar=1", "-c:v", "libx264", "-profile:v", "high",
        "-preset", "veryfast", "-pix_fmt", "yuv420p", "-threads", str(THREADS)]
    bitrate = video.get("bit_rate") or metadata["format"].get("bit_rate")
    if bitrate is not None:
        measured = int(bitrate)
        if not 0 < measured <= 200_000_000:
            raise ValueError("Source bitrate is outside the supported rendering range.")
        target = math.ceil(measured * 1.25)
        argv += ["-b:v", str(target), "-maxrate", str(target * 2), "-bufsize", str(target * 4)]
        metrics["video_bitrate"] = target
    else:
        argv += ["-crf", str(crf)]
    if audio:
        argv += _aac_args({"bitrate_kbps": PRESETS[params["intent"]]["audio"]["bitrate_kbps"]})
    argv += ["-fps_mode", "passthrough", "-map_metadata", "-1", "-movflags", "+faststart", "-fs", str(MAX_OUTPUT_BYTES),
             "./" + output.name]
    return [Command(argv, [output], metrics, stderr_bytes=65536)]


def cadence(directory, source, params):
    _, video, _, duration = _media(directory, source, video=True)
    _video_properties(video)
    argv = ["ffprobe", "-hide_banner", "-v", "error", "-threads", str(THREADS), "-protocol_whitelist", "file,pipe",
            "-format_whitelist", FORMATS, "-select_streams", "v:0", "-show_frames", "-show_entries",
            "frame=best_effort_timestamp_time:frame_side_data=", "-of", "csv=p=0", _input(directory, source)]
    return [Command(argv, metrics={"source_duration": duration, "nominal_frame_rate": video.get("r_frame_rate"),
                                   "time_base": video.get("time_base")})]


def cadence_metrics(results):
    _complete(results[0])
    timestamps = []
    for line in results[0].stdout.decode("utf-8", errors="strict").splitlines():
        if not line.strip():
            continue
        value = line.split(",", 1)[0]
        if not re.fullmatch(_NUMBER, value):
            raise ValueError("Decoded video frames lack complete numeric timestamps.")
        timestamps.append(float(value))
    if len(timestamps) < 2:
        raise ValueError("At least two decoded video timestamps are required to verify cadence.")
    intervals = [b - a for a, b in zip(timestamps, timestamps[1:])]
    if any(not math.isfinite(d) or d <= 0 for d in intervals):
        raise ValueError("Decoded video timestamps are not strictly increasing.")
    median = statistics.median(intervals)
    cfr = max(abs(d - median) for d in intervals) <= max(.000002, median * .001)
    return {"sample_count": len(timestamps), "first_frame_s": timestamps[0], "last_frame_s": timestamps[-1],
            "min_interval_s": min(intervals), "max_interval_s": max(intervals), "cadence_fps": 1 / median,
            "cfr": cfr, "timestamps_s": [round(t - timestamps[0], 6) for t in timestamps]}


def finish_cadence(directory, source, params, outputs, metrics):
    timestamps = metrics["timestamps_s"]
    try:
        nominal = float(Fraction(metrics["nominal_frame_rate"]))
    except (ValueError, TypeError, ZeroDivisionError, OverflowError):
        nominal = 0
    ticks = [round((b - a) * 1_000_000) for a, b in zip(timestamps, timestamps[1:])]
    observed_tick = math.gcd(*ticks) / 1_000_000
    tolerance = max(.000002, min(.001, observed_tick) * 1.05)
    measured_interval = timestamps[-1] / (len(timestamps) - 1)
    candidates = [1 / nominal, measured_interval] if nominal > 0 else [measured_interval]
    deviations = [max(abs(t - index * interval) for index, t in enumerate(timestamps))
                  for interval in candidates]
    choice = next((index for index, deviation in enumerate(deviations) if deviation <= tolerance), len(candidates) - 1)
    return {"cfr": deviations[choice] <= tolerance, "cadence_fps": 1 / candidates[choice],
            "max_frame_deviation_s": deviations[choice], "timestamp_tolerance_s": tolerance}


def _detector(directory, source, params, kind):
    _, video, audio, duration = _media(directory, source, video=kind != "silence", audio=kind == "silence")
    stream = audio if kind == "silence" else video
    duration = float(stream.get("duration", duration))
    if kind == "black":
        graph, start, end = f"blackdetect=d={params['d']:g}:pix_th={params['pix_th']:g}", "lavfi.black_start", "lavfi.black_end"
    elif kind == "freeze":
        graph, start, end = f"freezedetect=n={params['n']:g}:d={params['d']:g}", "lavfi.freezedetect.freeze_start", "lavfi.freezedetect.freeze_end"
    else:
        graph, start, end = f"silencedetect=noise={params['noise']:g}dB:d={params['d']:g}", "lavfi.silence_start", "lavfi.silence_end"
    metadata_filter = "ametadata" if kind == "silence" else "metadata"
    graph = ("asetpts=PTS-STARTPTS," if kind == "silence" else "setpts=PTS-STARTPTS,") + graph
    graph += f",{metadata_filter}=mode=print:key={start}:file=-,{metadata_filter}=mode=print:key={end}:file=-"
    selection = ["-map", "0:a:0", "-vn", "-af"] if kind == "silence" else ["-map", "0:v:0", "-an", "-vf"]
    argv = _ffmpeg_input(directory, source) + ["-nostats", *selection, graph, "-f", "null", "-"]
    return [Command(argv, metrics={"source_duration": duration, "minimum_duration": params["d"]}, stderr_bytes=65536)]


def black(directory, source, params):
    return _detector(directory, source, params, "black")


def freeze(directory, source, params):
    return _detector(directory, source, params, "freeze")


def silence(directory, source, params):
    return _detector(directory, source, params, "silence")


def interval_metrics(results):
    _complete(results[0])
    events = []
    for name, value in re.findall(rf"^lavfi\.(?:black_|silence_|freezedetect\.freeze_)(start|end)=({_NUMBER})$",
                                  results[0].stdout.decode("utf-8", errors="strict"), re.MULTILINE):
        events.append((name, float(value)))
    # Each metadata filter buffers its own stdout, so recover event order by timestamp.
    return {"interval_events": sorted(events, key=lambda event: (event[1], event[0] == "start"))}


def finish_intervals(directory, source, params, outputs, metrics):
    duration = metrics["source_duration"]
    pending = None
    intervals = []
    for event, value in metrics.pop("interval_events"):
        if not math.isfinite(value) or value < 0 or value > duration + .05:
            raise ValueError("Detector reported an invalid interval timestamp.")
        if event == "start":
            if pending is not None:
                raise ValueError("Detector returned an incomplete interval sequence.")
            pending = value
        else:
            if pending is None or value < pending:
                raise ValueError("Detector returned an incomplete interval sequence.")
            if value - pending >= params["d"] - .00001:
                intervals.append({"start_s": pending, "end_s": value, "duration_s": value - pending})
            pending = None
    if pending is not None and duration - pending >= params["d"] - .00001:
        intervals.append({"start_s": pending, "end_s": duration, "duration_s": duration - pending})
    return {"intervals": intervals}


def ssim(directory, source, params):
    reference = input_file(directory, params["reference_path"])
    _, video, _, duration = _media(directory, source, video=True)
    _, ref_video, _, ref_duration = _media(directory, reference, video=True)
    size = _video_properties(video)[:2]
    if size != _video_properties(ref_video)[:2]:
        raise ValueError("SSIM requires equal displayed frame dimensions; no automatic scaling is allowed.")
    frames = _execute(directory, "frame_cadence", source)
    reference_frames = _execute(directory, "frame_cadence", reference)
    if frames["sample_count"] != reference_frames["sample_count"]:
        raise ValueError("SSIM requires matching video frame counts; endpoints cannot certify retimed media.")
    commands = []
    for index, label in ((0, "first"), (frames["sample_count"] - 1, "last")):
        argv = _ffmpeg_input(directory, source)
        argv += ["-protocol_whitelist", "file,pipe", "-format_whitelist", FORMATS, "-i", _input(directory, reference)]
        graph = (f"[0:v:0]select=eq(n\\,{index}),setpts=PTS-STARTPTS[a];"
                 f"[1:v:0]select=eq(n\\,{index}),setpts=PTS-STARTPTS[b];[a][b]ssim[out]")
        argv += ["-nostats", "-filter_complex", graph, "-map", "[out]", "-frames:v", "1", "-an", "-f", "null", "-"]
        commands.append(Command(argv, metrics={"source_duration": duration, "reference_duration": ref_duration,
                                               f"{label}_frame_s": frames["timestamps_s"][index],
                                               f"reference_{label}_frame_s": reference_frames["timestamps_s"][index]},
                                stderr_bytes=65536))
    return commands


def ssim_metrics(results):
    metrics = {}
    for result, label in zip(results, ("first", "last")):
        _complete(result)
        scores = re.findall(rf"\bAll:({_NUMBER})\s", result.stderr.decode("utf-8", errors="replace"))
        if len(scores) != 1:
            raise ValueError("SSIM did not produce a complete single-frame comparison.")
        score = float(scores[0])
        if not math.isfinite(score) or not -1 <= score <= 1:
            raise ValueError("SSIM did not produce a finite bounded score.")
        metrics[f"{label}_frame_ssim"] = score
    return metrics
