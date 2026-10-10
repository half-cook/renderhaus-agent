"""An op registry owns parameter bounds, fixed argv templates, and metric parsing.

FFmpeg CLI/filter reference https://ffmpeg.org/ffmpeg.html and
https://ffmpeg.org/ffmpeg-filters.html, read 2026-10-09.
"""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
import difflib
import json
import math
from pathlib import Path
import re
import struct
from typing import Any

from providers.ffmpeg.commands import Command, THREADS, FORMATS, _input, _ffmpeg_input
from providers.ffmpeg.sandbox import MAX_OUTPUT_BYTES, PATH_PATTERN, output_file, sha256_file


@dataclass(frozen=True)
class OpSpec:
    params: dict[str, dict[str, Any]]
    builder: Callable[[Path, Path, dict[str, Any]], list[Command]] | None = None
    parse: Callable[[list[Any]], dict[str, Any]] | None = None
    pure: Callable[[Path], dict[str, Any]] | None = None
    binary: str | None = None
    timeout_s: int = 30
    description: str = ""
    validate: Callable[[dict[str, Any]], None] | None = None
    compute: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    finalize: Callable[[Path, Path, dict, list[Path], dict], dict] | None = None


def number(default, minimum, maximum, *, integer=False):
    return {"type": "integer" if integer else "number", "default": default,
            "minimum": minimum, "maximum": maximum, "not": {"exclusiveMaximum": minimum},
            "description": f"Allowed range: {minimum} to {maximum}. Default {default}."}


def _probe(directory, source, params):
    return [Command(["ffprobe", "-hide_banner", "-v", "error", "-threads", str(THREADS),
                     "-protocol_whitelist", "file,pipe", "-format_whitelist", FORMATS,
                     "-show_entries", "stream=index,codec_name,codec_type,width,height,pix_fmt,"
                     "r_frame_rate,avg_frame_rate,duration,start_time,nb_frames,time_base,bit_rate,profile,channels,channel_layout,sample_rate,sample_aspect_ratio:"
                     "stream_tags=rotate:stream_side_data=rotation:"
                     "format=duration,size,bit_rate,format_name", "-of", "json", _input(directory, source)])]


def _probe_metrics(results):
    payload = json.loads(results[0].stdout)
    if not isinstance(payload, dict) or not payload.get("streams"):
        raise ValueError("Media probe did not return supported streams.")
    for stream in payload["streams"]:
        if stream.get("codec_type") == "audio":
            stream.setdefault("channel_layout", None)
    return {"streams": payload["streams"], "format": payload.get("format", {})}


def _extract(directory, source, params):
    commands = []
    for time_s in params["times"]:
        output = output_file(directory, "frame", ".png")
        argv = _ffmpeg_input(directory, source)
        argv += ["-ss", f"{time_s:g}", "-map", "0:v:0", "-frames:v", "1", "-an",
                 "-vf", f"scale={params['width']}:-1", "-threads", str(THREADS),
                 "-fs", str(MAX_OUTPUT_BYTES), "-update", "1", "./" + output.name]
        commands.append(Command(argv, [output]))
    return commands


def _contact(directory, source, params):
    output = output_file(directory, "contact", ".jpg")
    width, height = params["width"], params["height"]
    vf = (f"fps=1/{params['every_s']:g},scale={width}:{height}:force_original_aspect_ratio=decrease,"
          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
          f"tile={params['cols']}x{params['rows']}")
    duration = min(600, params["every_s"] * params["cols"] * params["rows"])
    argv = _ffmpeg_input(directory, source)
    argv += ["-t", f"{duration:g}", "-map", "0:v:0", "-vf", vf, "-frames:v", "1", "-an",
             "-q:v", "2", "-threads", str(THREADS), "-fs", str(MAX_OUTPUT_BYTES), "-update", "1",
             "./" + output.name]
    return [Command(argv, [output])]


def _volume(directory, source, params):
    return [Command(_ffmpeg_input(directory, source) + ["-t", "600", "-map", "0:a:0", "-vn",
                   "-af", "volumedetect", "-threads", str(THREADS), "-f", "null", "-"])]


def _volume_metrics(results):
    tail = results[0].stderr.decode("utf-8", errors="replace")
    metrics = {}
    for name in ("mean_volume", "max_volume"):
        found = re.search(rf"\b{name}:\s*(-?(?:\d+(?:\.\d+)?|inf))\s+dB", tail)
        if not found:
            raise ValueError("No audio volume measurements were available.")
        value = float(found.group(1))
        metrics[name + "_db"] = value if math.isfinite(value) else None
    return metrics


def _sha256(source):
    return {"sha256": sha256_file(source), "bytes": source.stat().st_size}


def _faststart(source):
    atoms = []
    size = source.stat().st_size
    offset = 0
    with source.open("rb") as handle:
        while offset < size:
            if len(atoms) >= 4096 or size - offset < 8:
                raise ValueError("MP4 has a truncated or oversized atom table.")
            handle.seek(offset)
            atom_size, kind = struct.unpack(">I4s", handle.read(8))
            header_size = 8
            if atom_size == 1:
                extended = handle.read(8)
                if len(extended) != 8:
                    raise ValueError("MP4 has a truncated extended-size atom.")
                atom_size = struct.unpack(">Q", extended)[0]
                header_size = 16
            elif atom_size == 0:
                atom_size = size - offset
            if atom_size < header_size or offset + atom_size > size:
                raise ValueError("MP4 contains an invalid atom size.")
            name = kind.decode("ascii", errors="replace")
            if not re.fullmatch(r"[A-Za-z0-9 ]{4}", name):
                raise ValueError("MP4 contains an invalid atom type.")
            atoms.append(name)
            offset += atom_size
    if "moov" not in atoms or "mdat" not in atoms:
        raise ValueError("MP4 requires both moov and mdat atoms for a faststart check.")
    return {"faststart": atoms.index("moov") < atoms.index("mdat"), "atom_order": atoms}


def _sheet_geometry(params):
    if params["cols"] * params["width"] > 4096 or params["rows"] * params["height"] > 4096:
        raise ValueError("Contact sheets must fit within 4096 by 4096 pixels.")


def _geometry_preview(params):
    from providers.ffmpeg.reframe import crop_plan

    return crop_plan(params["source_width"], params["source_height"], params["aspect"],
                     subject_box=params["subject_box"], crop_box=params["crop_box"],
                     anchor=params["anchor"], safe_zone=params["safe_zone"],
                     rotation=params["rotation"], allow_upscale=params["allow_upscale"])


def _geometry_params(params):
    from providers.ffmpeg.reframe import display_size, validated_box, validated_safe_zone

    width, height = display_size(params.get("source_width", 16384), params.get("source_height", 16384),
                                 params.get("rotation", 0))
    for name in ("subject_box", "crop_box"):
        if params.get(name) is not None:
            validated_box(params[name], width, height, crop=name == "crop_box")
    if params.get("safe_zone") is not None:
        validated_safe_zone(params["safe_zone"])


def _source_metrics(directory, source):
    from providers.ffmpeg.api import execute
    from providers.remotion.api import _media_dimensions

    result = execute("probe", directory, _input(directory, source)[2:])
    if not result["ok"]:
        raise ValueError(result.get("error", "Source probe failed."))
    metrics = result["metrics"]
    video = next((s for s in metrics["streams"] if s.get("codec_type") == "video"), None)
    size = _media_dimensions(video or {})
    if size is None:
        raise ValueError("A readable video with valid display dimensions is required.")
    duration = float(metrics.get("format", {}).get("duration", video.get("duration", 0)))
    if not math.isfinite(duration) or not 0 < duration <= 600:
        raise ValueError("Reframing and scene detection require video of at most 600 seconds.")
    return metrics, video, size, duration


def _reframe(directory, source, params, *, pad=False):
    from fractions import Fraction

    from providers.ffmpeg.reframe import crop_plan

    metadata, video, size, duration = _source_metrics(directory, source)
    if video.get("sample_aspect_ratio") not in {None, "1:1", "0:1"}:
        raise ValueError("Reframing requires square source pixels (SAR 1:1); "
                         "normalize anamorphic media before crop/pad.")
    try:
        fps = float(Fraction(video.get("avg_frame_rate")))
    except (ValueError, TypeError, ZeroDivisionError, OverflowError):
        raise ValueError("Reframing requires a valid measured frame rate.") from None
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("Reframing requires a positive measured frame rate.")
    aspect = params["size"] if pad else params["aspect"]
    box = dict(x=0, y=0, width=size[0], height=size[1]) if pad else params["subject_box"]
    plan = crop_plan(*size, aspect, subject_box=box,
                     crop_box=None if pad else params["crop_box"],
                     anchor="center" if pad else params["anchor"],
                     safe_zone=params["safe_zone"], allow_upscale=params["allow_upscale"])
    if pad:
        plan.update(mode="pad_blur", crop_box=None)
    if video.get("avg_frame_rate") != video.get("r_frame_rate"):
        plan["warnings"].append("Frame-rate metadata suggests VFR; timestamps are preserved. "
                                "Use an explicit CFR timeline rate for delivery if required.")
    plan.update(source_duration=duration, source_fps=video.get("avg_frame_rate"),
                source_audio=any(s.get("codec_type") == "audio" for s in metadata["streams"]))
    output = output_file(directory, "reframe", ".mp4")
    width, height = plan["width"], plan["height"]
    argv = _ffmpeg_input(directory, source)
    if plan["mode"] == "crop":
        box = plan["crop_box"]
        vf = (f"crop={box['width']}:{box['height']}:{box['x']}:{box['y']},"
              f"scale={width}:{height}:flags=lanczos,setsar=1")
        argv += ["-vf", vf, "-map", "0:v:0"]
    else:
        box = plan["foreground_box"]
        graph = (f"[0:v:0]split[bg][fg];[bg]scale={width}:{height}:force_original_aspect_ratio=increase:"
                 f"flags=lanczos,crop={width}:{height},gblur=sigma=20[blur];"
                 f"[fg]scale={box['width']}:{box['height']}:flags=lanczos[front];"
                 f"[blur][front]overlay={box['x']}:{box['y']}:shortest=1,setsar=1[out]")
        argv += ["-filter_complex", graph, "-map", "[out]"]
    bitrate = video.get("bit_rate") or metadata.get("format", {}).get("bit_rate")
    quality = ["-crf", "18"]
    if bitrate is not None:
        measured = int(bitrate)
        if not 0 < measured <= 200_000_000:
            raise ValueError("Source bitrate is outside the supported rendering range.")
        target_bitrate = math.ceil(measured * max(1, width * height / (size[0] * size[1])) * 1.25)
        quality = ["-b:v", str(target_bitrate), "-maxrate", str(target_bitrate * 2),
                   "-bufsize", str(target_bitrate * 4)]
    argv += ["-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-threads", str(THREADS),
             "-pix_fmt", "yuv420p", *quality, "-c:a", "copy", "-fps_mode", "passthrough",
             "-map_metadata", "-1", "-metadata:s:v:0", "rotate=0", "-movflags", "+faststart",
             "-t", f"{duration:g}", "-fs", str(MAX_OUTPUT_BYTES), "./" + output.name]
    return [Command(argv, [output], plan)]


def _reframe_crop(directory, source, params):
    return _reframe(directory, source, params)


def _reframe_pad(directory, source, params):
    return _reframe(directory, source, params, pad=True)


def _scenes(directory, source, params):
    _, _, _, duration = _source_metrics(directory, source)
    graph = f"select=gt(scene\\,{params['T']:g}),showinfo"
    argv = _ffmpeg_input(directory, source)
    argv += ["-t", f"{duration:g}", "-map", "0:v:0", "-an", "-vf", graph,
             "-fps_mode", "vfr", "-threads", str(THREADS), "-f", "null", "-"]
    return [Command(argv, metrics={"source_duration": duration}, stderr_bytes=65536)]


def _scene_metrics(results):
    from providers.ffmpeg.reframe import MAX_SHOTS

    result = results[0]
    if result.stderr_truncated:
        raise ValueError("Scene detection exceeded its bounded log capture; no complete shot list is available.")
    log = result.stderr.decode("utf-8", errors="replace")
    times = [float(value) for value in re.findall(
        r"^\[Parsed_showinfo_\d+ @ 0x[0-9a-fA-F]+\]\s+n:\s*\d+\s+pts:\s*-?\d+\s+"
        r"pts_time:([0-9.eE+-]+)(?:\s|$)", log, re.MULTILINE)]
    if len(times) >= MAX_SHOTS:
        raise ValueError("Scene detection found more than 60 shots; split the source into shorter masters.")
    return {"scene_times": times}


_BOX_PARAMS = {
    "type": ["object", "null"], "default": None,
    "properties": {key: number(0, 0 if key in {"x", "y"} else 1, 16384)
                   for key in ("x", "y", "width", "height")},
    "required": ["x", "y", "width", "height"], "additionalProperties": False,
    "description": "Optional box in displayed source pixels. x/y nonnegative, dimensions positive, within source. "
                   "crop_box requires even integers; subject_box is only a crop-centre hint, never detection.",
}
_SAFE_PARAMS = {
    "type": ["object", "null"], "default": None,
    "properties": {key: number(0, 0, .49) for key in ("top", "bottom", "side")},
    "additionalProperties": False, "description": "Safe-zone fraction overrides top,bottom,side; "
    "leave at least 5% inner width/height. Null uses configured aspect placeholders.",
}
_ASPECT_PARAM = {"type": "string", "enum": ["9:16", "1:1", "4:5", "16:9", "2.39:1"], "default": "9:16",
                 "description": "Target aspect enum. Nominal sizes come from the shared aspect table."}
_REFRAME_PARAMS = {
    "aspect": _ASPECT_PARAM, "subject_box": _BOX_PARAMS, "crop_box": _BOX_PARAMS,
    "safe_zone": _SAFE_PARAMS,
    "anchor": {"type": "string", "enum": ["center", "top", "bottom", "left", "right"], "default": "center",
               "description": "Static centre or edge anchor. A supplied subject box takes precedence."},
    "allow_upscale": {"type": "boolean", "default": False,
                      "description": "Allow crop/foreground resampling to table size; disclosed as no added detail."},
}


from providers.ffmpeg import delivery


_LOUDNESS_PARAMS = {"I": number(-14, -30, -5), "TP": number(-1.5, -9, 0), "LRA": number(11, 1, 20)}
_AAC_PARAMS = {"bitrate_kbps": number(192, 64, 320, integer=True)}
_MEASURED_PARAMS = {
    name: {**{key: value for key, value in number(0, lower, upper).items() if key != "default"},
           "description": f"Required pass-one {name} from this source at these targets; finite {lower} to {upper}."}
    for name, lower, upper in (("measured_I", -99, 0), ("measured_TP", -99, 99),
                               ("measured_LRA", 0, 99), ("measured_thresh", -99, 0), ("offset", -99, 99))
}


OPS = {
    "measure_loudness": OpSpec(_LOUDNESS_PARAMS, delivery.measure, delivery.measure_metrics,
                               binary="ffmpeg", timeout_s=120, description="Measure complete loudnorm pass one and EBU R128 summary."),
    "loudnorm_mux_aac": OpSpec({**_LOUDNESS_PARAMS, **_AAC_PARAMS, **_MEASURED_PARAMS},
                               delivery.normalize, delivery.normalization_metrics, binary="ffmpeg", timeout_s=180,
                               finalize=delivery.finish_normalization,
                               description="Verify pass-one measurements, normalize audio, copy video and remeasure final AAC."),
    "mux_aac": OpSpec(_AAC_PARAMS, delivery.mux, binary="ffmpeg", timeout_s=120,
                      finalize=delivery.finish_delivery, description="Copy video and mux AAC at 48 kHz without changing channels."),
    "transcode_h264": OpSpec({"intent": {"type": "string", "enum": list(delivery.INTENTS),
                                       "description": "Fixed delivery intent; fit native dimensions without upscaling."}},
                             delivery.transcode, binary="ffmpeg", timeout_s=180, finalize=delivery.finish_delivery,
                             description="Encode a fixed H.264 High yuv420p intent with native cadence and faststart."),
    "frame_cadence": OpSpec({}, delivery.cadence, delivery.cadence_metrics, binary="ffprobe", timeout_s=120, finalize=delivery.finish_cadence,
                            description="Decode all video frame timestamps to verify cadence without trusting nominal rates."),
    "detect_black": OpSpec({"d": number(.5, .1, 5), "pix_th": number(.1, 0, .5)},
                           delivery.black, delivery.interval_metrics, binary="ffmpeg", timeout_s=120,
                           finalize=delivery.finish_intervals, description="Detect complete black intervals, including EOF tails."),
    "detect_freeze": OpSpec({"d": number(.5, .1, 5), "n": number(.001, 0, .1)},
                            delivery.freeze, delivery.interval_metrics, binary="ffmpeg", timeout_s=120,
                            finalize=delivery.finish_intervals, description="Detect complete frozen intervals, including EOF tails."),
    "detect_silence": OpSpec({"d": number(.5, .1, 5), "noise": number(-50, -60, -20)},
                             delivery.silence, delivery.interval_metrics, binary="ffmpeg", timeout_s=120,
                             finalize=delivery.finish_intervals, description="Detect complete silence intervals, including EOF tails."),
    "ssim": OpSpec({"reference_path": {"type": "string", "pattern": PATH_PATTERN, "maxLength": 1024,
                                       "description": "Required readable reference video confined to the same job directory."}},
                    delivery.ssim, delivery.ssim_metrics, binary="ffmpeg", timeout_s=180,
                    description="Compare first and last actual matching frames with equal dimensions; never scale."),
    "crop_plan_preview": OpSpec({
        **_REFRAME_PARAMS, "source_width": number(1920, 2, 16384, integer=True),
        "source_height": number(1080, 2, 16384, integer=True), "rotation": number(0, -360, 360),
    }, compute=_geometry_preview, validate=_geometry_params,
       description="Compute crop/pad geometry without reading media or running a binary."),
    "reframe_crop": OpSpec(_REFRAME_PARAMS, _reframe_crop, binary="ffmpeg", timeout_s=120,
                           validate=_geometry_params, description="Render a static crop or safe blurred-pad fallback."),
    "reframe_pad_blur": OpSpec({"size": _ASPECT_PARAM, "safe_zone": _SAFE_PARAMS,
                                "allow_upscale": _REFRAME_PARAMS["allow_upscale"]},
                               _reframe_pad, binary="ffmpeg", timeout_s=120, validate=_geometry_params,
                               description="Fit the whole frame over a blurred copy in an aspect canvas."),
    "detect_scenes": OpSpec({"T": number(.3, .1, .6)}, _scenes, _scene_metrics,
                           binary="ffmpeg", timeout_s=120, description="Detect bounded shot cuts with scene threshold T."),
    "probe": OpSpec({}, _probe, _probe_metrics, binary="ffprobe", description="Read streams and format JSON."),
    "extract_frames": OpSpec({
        "times": {"type": "array", "items": number(0, 0, 600), "minItems": 1, "maxItems": 20,
                  "default": [0], "description": "1 to 20 frame times, each 0 to 600 seconds. Default [0]."},
        "width": number(640, 16, 1920, integer=True),
    }, _extract, binary="ffmpeg", timeout_s=120, description="Write PNG frames at validated times."),
    "contact_sheet": OpSpec({
        "every_s": number(1, .1, 600), "cols": number(3, 1, 10, integer=True),
        "rows": number(1, 1, 10, integer=True), "width": number(320, 16, 640, integer=True),
        "height": number(180, 16, 640, integer=True),
    }, _contact, binary="ffmpeg", timeout_s=120, description="Write a fixed-grid JPEG contact sheet.",
       validate=_sheet_geometry),
    "sha256": OpSpec({}, pure=_sha256, description="Hash one local file without invoking ffmpeg."),
    "check_faststart": OpSpec({}, pure=_faststart, description="Read MP4 atoms and check moov before mdat."),
    "volume_stats": OpSpec({}, _volume, _volume_metrics, binary="ffmpeg", timeout_s=120,
                          description="Measure mean and maximum audio volume in dB."),
}


def _validate_value(field: str, value: Any, schema: dict[str, Any]) -> None:
    kind = schema["type"]
    if isinstance(kind, list):
        if value is None and "null" in kind:
            return
        kind = next(k for k in kind if k != "null")
    if kind == "object":
        if not isinstance(value, dict) or set(value) - schema["properties"].keys():
            raise ValueError(f"params.{field} requires only the documented object fields.")
        if set(schema.get("required", [])) - value.keys():
            raise ValueError(f"params.{field} is missing required box fields.")
        for key, item in value.items():
            _validate_value(f"{field}.{key}", item, schema["properties"][key])
        return
    if kind in {"integer", "number"}:
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or (kind == "integer" and not isinstance(value, int))
                or not schema["minimum"] <= value <= schema["maximum"]
                or (isinstance(value, float) and not math.isfinite(value))):
            raise ValueError(f"params.{field} must be a finite {kind} between "
                             f"{schema['minimum']} and {schema['maximum']}.")
    elif kind == "array":
        if not isinstance(value, list) or not schema["minItems"] <= len(value) <= schema["maxItems"]:
            raise ValueError(f"params.{field} requires 1 to 20 numeric times.")
        for index, item in enumerate(value):
            _validate_value(f"{field}[{index}]", item, schema["items"])
    elif kind == "string":
        if not isinstance(value, str) or not ("enum" in schema or "pattern" in schema):
            raise ValueError(f"params.{field} must use an allow-listed enum or identifier.")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError(f"params.{field} must use an allow-listed enum value.")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise ValueError(f"params.{field} must use an allow-listed identifier.")
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"params.{field} must be a boolean.")
    else:
        raise ValueError("Op registry has an unsupported parameter type.")


def validate_params(op: str, params: dict | None) -> tuple[OpSpec, dict]:
    if not isinstance(op, str) or op not in OPS:
        near = difflib.get_close_matches(str(op)[:80], OPS, n=1, cutoff=0)
        raise ValueError(f"Unlisted operation refused. Nearest allow-listed op is {near[0]}.")
    spec = OPS[op]
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError("params must be a JSON object of allow-listed parameters.")
    unknown = set(params) - spec.params.keys()
    if unknown:
        names = ", ".join(str(name)[:40] for name in sorted(unknown, key=str))
        raise ValueError(f"Unlisted params refused for {op}: {names}.")
    validated = {}
    for name, schema in spec.params.items():
        if name not in params and "default" not in schema:
            raise ValueError(f"params.{name} is required for {op}.")
        value = params[name] if name in params else schema["default"]
        _validate_value(name, value, schema)
        validated[name] = value
    if spec.validate is not None:
        spec.validate(validated)
    return spec, validated


def tool_schema() -> dict:
    parameters = {}
    for op, spec in OPS.items():
        for name, schema in spec.params.items():
            if name not in parameters:
                parameters[name] = {**deepcopy(schema), "description": ""}
            common = parameters[name]
            common["description"] += f"{op}: {schema.get('description', 'See the operation contract.')} "
    return {
        "name": "ffmpeg_tool",
        "description": "Free local/worker media inspection, delivery and fixed reframing. Fixed operations only; no commands, filtergraphs, "
                       "URLs or network access. Always execute on the machine containing job_id. "
                       "Missing binaries fail softly; Lambda hosts without ffmpeg cannot run binary ops.",
        "inputSchema": {
            "type": "object", "additionalProperties": False,
            "oneOf": [{"properties": {"op": {"enum": [name]}, "params": {
                "type": "object", "properties": spec.params, "additionalProperties": False,
                "required": [key for key, schema in spec.params.items() if "default" not in schema]}},
                **({"required": ["params"]} if any("default" not in s for s in spec.params.values()) else {})}
                for name, spec in OPS.items()],
            "properties": {
                "op": {"type": "string", "enum": list(OPS),
                       "description": "Allowed values: " + ", ".join(OPS) + "."},
                "job_id": {"type": "string", "pattern": r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,79}(?![\s\S])",
                           "description": "Existing job directory under RENDERHAUS_MEDIA_DIR. ASCII id, 1 to 80 characters."},
                "input_path": {"type": "string", "pattern": PATH_PATTERN, "maxLength": 1024, "description": "Readable regular file inside this job. "
                               "Relative path or confined absolute path. No URLs, traversal or option prefixes."},
                "params": {"type": "object", "properties": parameters, "additionalProperties": False,
                           "description": "Per-op parameters only. probe, sha256, check_faststart, volume_stats "
                                          "take no params. extract_frames uses times,width. contact_sheet uses "
                                          "every_s,cols,rows,width,height. Outputs never overwrite existing files."},
            }, "required": ["op", "job_id", "input_path"],
        },
    }
