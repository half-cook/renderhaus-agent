"""An op registry owns parameter bounds, fixed argv templates, and metric parsing.

FFmpeg CLI/filter reference https://ffmpeg.org/ffmpeg.html and
https://ffmpeg.org/ffmpeg-filters.html, read 2026-10-09.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import difflib
import json
import math
from pathlib import Path
import re
import struct
from typing import Any

from providers.ffmpeg.sandbox import MAX_OUTPUT_BYTES, output_file, sha256_file


FORMATS = "mov,matroska,mp3,wav,aac,image2,png_pipe,jpeg_pipe,webp_pipe,ogg,flac"
THREADS = 2


@dataclass(frozen=True)
class Command:
    argv: list[str]
    outputs: list[Path] = field(default_factory=list)


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


def number(default, minimum, maximum, *, integer=False):
    return {"type": "integer" if integer else "number", "default": default,
            "minimum": minimum, "maximum": maximum,
            "description": f"Allowed range: {minimum} to {maximum}. Default {default}."}


def _input(directory: Path, source: Path) -> str:
    return "./" + source.relative_to(directory).as_posix()


def _ffmpeg_input(directory: Path, source: Path) -> list[str]:
    return ["ffmpeg", "-nostdin", "-hide_banner", "-v", "info", "-n",
            "-filter_threads", str(THREADS), "-filter_complex_threads", str(THREADS),
            "-threads", str(THREADS), "-protocol_whitelist", "file,pipe",
            "-format_whitelist", FORMATS, "-i", _input(directory, source)]


def _probe(directory, source, params):
    return [Command(["ffprobe", "-hide_banner", "-v", "error", "-threads", str(THREADS),
                     "-protocol_whitelist", "file,pipe", "-format_whitelist", FORMATS,
                     "-show_entries", "stream=index,codec_name,codec_type,width,height,pix_fmt,"
                     "r_frame_rate,avg_frame_rate,duration,bit_rate,channels,sample_rate:"
                     "stream_tags=rotate:stream_side_data=rotation:"
                     "format=duration,size,bit_rate,format_name", "-of", "json", _input(directory, source)])]


def _probe_metrics(results):
    payload = json.loads(results[0].stdout)
    if not isinstance(payload, dict) or not payload.get("streams"):
        raise ValueError("Media probe did not return supported streams.")
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


OPS = {
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
        value = params.get(name, schema["default"])
        _validate_value(name, value, schema)
        validated[name] = value
    if spec.validate is not None:
        spec.validate(validated)
    return spec, validated


def tool_schema() -> dict:
    parameters = {}
    for op, spec in OPS.items():
        for name, schema in spec.params.items():
            common = parameters.setdefault(name, {"type": schema["type"], "description": ""})
            common["description"] += f"{op}: {schema.get('description', 'See the operation contract.')} "
            if "items" in schema:
                common["items"] = {"type": schema["items"]["type"]}
    return {
        "name": "ffmpeg_tool",
        "description": "Free local/worker media inspection. Fixed operations only; no commands, filtergraphs, "
                       "URLs or network access. Always execute on the machine containing job_id. "
                       "Missing binaries fail softly; Lambda hosts without ffmpeg cannot run binary ops.",
        "inputSchema": {
            "type": "object", "additionalProperties": False,
            "oneOf": [{"properties": {"op": {"enum": [name]}, "params": {
                "type": "object", "properties": spec.params, "additionalProperties": False}}}
                for name, spec in OPS.items()],
            "properties": {
                "op": {"type": "string", "enum": list(OPS),
                       "description": "Allowed values: " + ", ".join(OPS) + "."},
                "job_id": {"type": "string", "pattern": "^[A-Za-z0-9_][A-Za-z0-9_.-]{0,79}$",
                           "description": "Existing job directory under RENDERHAUS_MEDIA_DIR. ASCII id, 1 to 80 characters."},
                "input_path": {"type": "string", "description": "Readable regular file inside this job. "
                               "Relative path or confined absolute path. No URLs, traversal or option prefixes."},
                "params": {"type": "object", "properties": parameters, "additionalProperties": False,
                           "description": "Per-op parameters only. probe, sha256, check_faststart, volume_stats "
                                          "take no params. extract_frames uses times,width. contact_sheet uses "
                                          "every_s,cols,rows,width,height. Outputs never overwrite existing files."},
            }, "required": ["op", "job_id", "input_path"],
        },
    }
