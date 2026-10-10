from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import time

from providers.ffmpeg.api import execute
from providers.ffmpeg.delivery import PRESETS
from providers.ffmpeg.ops import number, _validate_value
from providers.ffmpeg.sandbox import (input_file, job_directory, output_file, sha256_file,
                                      validate_input_path, validate_job_id, NAME_PATTERN)
from providers.remotion.qc import inspect_file, validate_file_report


MAX_JSON_BYTES = 16 * 1024 * 1024
_ID = r"[A-Za-z0-9_][A-Za-z0-9_-]{0,39}"
_ASPECTS = {"9:16": "9x16", "1:1": "1x1", "4:5": "4x5", "16:9": "16x9", "2.39:1": "2p39x1"}
_INTERVAL = {"type": "object", "properties": {k: number(0, 0, 600) for k in ("start_s", "end_s")},
             "required": ["start_s", "end_s"], "additionalProperties": False}
_BOX = {"type": "object", "properties": {k: number(0, 0 if k in {"x", "y"} else 1, 16384)
            for k in ("x", "y", "width", "height")},
        "required": ["x", "y", "width", "height"], "additionalProperties": False}
SPEC_PROPERTIES = {
    "expected_width": number(1920, 2, 16384, integer=True),
    "expected_height": number(1080, 2, 16384, integer=True),
    "expected_fps": number(24, .01, 240), "expected_duration_s": number(4, .01, 600),
    "expected_sha256": {"type": "string", "pattern": r"[a-f0-9]{64}"},
    "expected_filename": {"type": "string", "pattern": r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}"},
    "master_path": {"type": "string", "description": "Regular media file confined inside this job."},
    "audio_channels": {"type": "integer", "minimum": 1, "maximum": 2},
    "require_audio": {"type": "boolean"}, "require_vision": {"type": "boolean"},
    "I": number(-14, -30, -5), "TP": number(-1.5, -9, 0), "LRA": number(11, 1, 20),
    "tolerance_lu": number(.5, .1, 1), "noise": number(-50, -60, -20),
    "black_d": number(.5, .1, 5), "freeze_d": number(.5, .1, 5), "silence_d": number(.5, .1, 5),
    "pix_th": number(.1, 0, .5), "n": number(.001, 0, .1),
    **{"allowed_" + name: {"type": "array", "items": _INTERVAL, "minItems": 0, "maxItems": 60}
       for name in ("black", "freeze", "silence")},
    "overlay_boxes": {"type": "array", "items": _BOX, "minItems": 0, "maxItems": 60},
    "safe_zone": {"type": "object", "properties": {k: number(0, 0, .49) for k in ("top", "bottom", "side")},
                  "additionalProperties": False},
}


def validate_spec(spec: dict | None, directory: Path) -> dict:
    if spec is None:
        return {}
    if not isinstance(spec, dict) or set(spec) - SPEC_PROPERTIES.keys():
        raise ValueError("spec accepts only documented QC fields, never arguments or filtergraphs.")
    for name, value in spec.items():
        if name == "master_path":
            validate_input_path(directory, value, must_exist=False)
        else:
            _validate_value(name, value, SPEC_PROPERTIES[name])
        if name.startswith("allowed_"):
            for interval in value:
                if interval["start_s"] >= interval["end_s"]:
                    raise ValueError("Allowed intervals require start_s < end_s.")
    return dict(spec)


def _aspect(value: str) -> str:
    canonical = _ASPECTS.get(value, value)
    if canonical not in _ASPECTS.values():
        raise ValueError("aspect must use a supported aspect identifier.")
    return canonical


def _delivery_prefix(campaign: str, sku: str, locale: str, aspect: str) -> str:
    prefix = f"{campaign}__{sku}__{locale}__{_aspect(aspect)}__v"
    if not re.fullmatch(NAME_PATTERN, prefix + "9999.mp4"):
        raise ValueError("Combined delivery identifiers must leave room for a versioned filename of at most 128 ASCII characters.")
    return prefix


def validate_arguments(tool_name: str, arguments: dict) -> None:
    fields = {"job_id", "input_path", "manifest_path", "preset", "spec"}
    if tool_name == "deliver_render":
        fields |= {"campaign", "sku", "locale", "aspect", "upload"}
    elif tool_name != "qc_deliverable":
        raise ValueError("Unknown delivery tool.")
    if set(arguments) - fields:
        raise ValueError("Unlisted delivery arguments refused.")
    job_id = validate_job_id(arguments.get("job_id"))
    root = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser().resolve()
    directory = (root / job_id).resolve()
    if directory == root or not directory.is_relative_to(root):
        raise ValueError("Delivery job directory must stay within the local media root.")
    selectors = [arguments.get(name, "") for name in ("input_path", "manifest_path")]
    if any(not isinstance(value, str) for value in selectors) or sum(bool(v) for v in selectors) != 1:
        raise ValueError("Supply exactly one input_path or manifest_path inside the job.")
    validate_input_path(directory, next(v for v in selectors if v), must_exist=False)
    if arguments.get("preset", "social-feed") not in PRESETS:
        raise ValueError("preset must be one of " + ", ".join(PRESETS) + ".")
    validate_spec(arguments.get("spec"), directory)
    if tool_name == "deliver_render":
        for name, default in (("campaign", "campaign"), ("sku", "master"), ("locale", "und")):
            if not isinstance(arguments.get(name, default), str) or not re.fullmatch(_ID, arguments.get(name, default)):
                raise ValueError(f"{name} must be a safe ASCII identifier, 1-40 characters.")
        _aspect(arguments.get("aspect", "16x9"))
        _delivery_prefix(arguments.get("campaign", "campaign"), arguments.get("sku", "master"),
                         arguments.get("locale", "und"), arguments.get("aspect", "16x9"))
        if type(arguments.get("upload", False)) is not bool:
            raise ValueError("upload must be a boolean.")


def _operation(job: Path, op: str, path: Path, params=None) -> dict:
    result = execute(op, job, str(path.relative_to(job)), params)
    if not result["ok"]:
        raise ValueError(result.get("error", f"{op} failed."))
    return result


def _write_json(path: Path, payload: object, *, replace=False) -> None:
    if path.is_symlink() or path.exists() and not path.is_file():
        raise ValueError("Reports and manifests must be regular files, never symlinks.")
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    if len(data.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("Delivery JSON exceeds the 16 MiB report/manifest cap.")
    temporary = output_file(path.parent, "delivery-state", ".json") if replace else path
    with temporary.open("x", encoding="utf-8") as target:
        target.write(data)
    if replace:
        temporary.replace(path)


@contextmanager
def _manifest_lock(job: Path):
    fd = os.open(job / "delivery.lock", os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, "a") as target:
        if not stat.S_ISREG(os.fstat(target.fileno()).st_mode):
            raise ValueError("Delivery lock must be a regular file.")
        deadline = time.monotonic() + 600
        while True:
            try:
                fcntl.flock(target, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ValueError("Delivery manifest is busy; inspect the current job.") from None
                time.sleep(.05)
        yield


def _entries(job: Path, input_path: str, manifest_path: str, *, final=False) -> tuple[list[dict], Path | None]:
    if input_path:
        return [{"file": str(input_file(job, input_path))}], None
    manifest = input_file(job, manifest_path)
    if (job / manifest_path).is_symlink() or manifest.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("Manifest must be a regular non-symlink JSON file of at most 16 MiB.")
    entries = json.loads(manifest.read_text())
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise ValueError("Manifest must contain 1-100 file entries.")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Manifest entries must be objects.")
        selected = entry.get("delivery", entry) if final else entry
        if not isinstance(selected, dict):
            raise ValueError("Manifest delivery entries must be objects.")
        source = input_file(job, selected.get("file"))
        if source in seen or selected.get("sha256") != sha256_file(source):
            raise ValueError("Manifest files must be unique and match their recorded SHA-256.")
        seen.add(source)
        for name in ("sku", "locale", "variant_key"):
            if name in entry and (not isinstance(entry[name], str) or not re.fullmatch(_ID, entry[name])):
                raise ValueError(f"Manifest {name} must be a safe ASCII identifier.")
        if "aspect" in entry:
            _aspect(entry["aspect"])
    return entries, manifest


def _named_copy(job: Path, source: Path, campaign: str, sku: str, locale: str, aspect: str) -> Path:
    prefix = _delivery_prefix(campaign, sku, locale, aspect)
    for version in range(1, 10000):
        destination = job / f"{prefix}{version}.mp4"
        try:
            fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            continue
        try:
            with os.fdopen(fd, "wb") as target, source.open("rb") as src:
                shutil.copyfileobj(src, target)
            return destination
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    raise ValueError("Delivery version limit reached; choose a new campaign identifier.")


def _finish(job: Path, entry: dict, preset_name: str, args: dict) -> dict:
    _delivery_prefix(args.get("campaign", "campaign"), entry.get("sku", args.get("sku", "master")),
                     entry.get("locale", args.get("locale", "und")), entry.get("aspect", args.get("aspect", "16x9")))
    source = input_file(job, entry["file"])
    original_hash = sha256_file(source)
    preset = PRESETS[preset_name]
    metadata = _operation(job, "probe", source)["metrics"]
    video = next((s for s in metadata["streams"] if s.get("codec_type") == "video"), {})
    if not video:
        raise ValueError("Delivery requires a finished video render.")
    input_resolution = f"{video.get('width')}x{video.get('height')}"
    fps = _operation(job, "frame_cadence", source)["metrics"].get("cadence_fps")
    duration = float(metadata.get("format", {}).get("duration", 0))
    if fps is None or not math.isfinite(duration) or not 0 < duration <= 600:
        raise ValueError("A measured video of at most 600 seconds with a positive FPS is required.")
    spec = dict(args.get("spec") or {})
    if spec.get("expected_sha256", original_hash) != original_hash:
        raise ValueError("Input does not match expected_sha256; delivery refused.")
    spec.setdefault("expected_duration_s", entry.get("duration_s", duration))
    spec.setdefault("expected_fps", fps)
    bitrate = preset["audio"]["bitrate_kbps"]
    target = preset.get("loudness")
    temporary_outputs = []
    current = source
    loudness = None
    try:
        compatible = (video.get("codec_name") == "h264" and video.get("profile") == "High" and
                      video.get("pix_fmt") == "yuv420p" and video.get("sample_aspect_ratio") == "1:1" and
                      video.get("width", 0) <= preset["max_width"] and video.get("height", 0) <= preset["max_height"])
        if not compatible or preset_name == "review-proxy":
            encoded = _operation(job, "transcode_h264", current, {"intent": preset_name})
            current = Path(encoded["outputs"][0]["path"])
            temporary_outputs.append(current)
        if target:
            settings = {key: spec.get(key, target[key]) for key in ("I", "TP", "LRA")}
            measured = _operation(job, "measure_loudness", current, settings)["metrics"]
            tolerance = spec.get("tolerance_lu", target["tolerance_lu"])
            within = (measured.get("integrated_lufs") is not None and measured.get("true_peak_db") is not None
                      and abs(measured["integrated_lufs"] - settings["I"]) <= tolerance
                      and measured["true_peak_db"] <= settings["TP"])
            if within:
                muxed = _operation(job, "mux_aac", current, {"bitrate_kbps": bitrate})
            else:
                params = {**settings, "bitrate_kbps": bitrate,
                    **{key: measured[value] for key, value in (("measured_I", "input_i"), ("measured_TP", "input_tp"),
                       ("measured_LRA", "input_lra"), ("measured_thresh", "input_thresh"), ("offset", "target_offset"))}}
                muxed = _operation(job, "loudnorm_mux_aac", current, params)
            current = Path(muxed["outputs"][0]["path"])
            temporary_outputs.append(current)
            after = _operation(job, "measure_loudness", current, settings)["metrics"]
            loudness = {"before": measured, "after": after, "target": settings,
                        "action": "none" if within else muxed["metrics"].get("normalization_type", "unknown"),
                        "dynamic_fallback": muxed["metrics"].get("dynamic_fallback", False)}
        else:
            muxed = _operation(job, "mux_aac", current, {"bitrate_kbps": bitrate})
            current = Path(muxed["outputs"][0]["path"])
            temporary_outputs.append(current)
        if sha256_file(source) != original_hash:
            raise ValueError("Input changed during delivery; no finished claim is valid.")
        destination = _named_copy(job, current, args.get("campaign", "campaign"), entry.get("sku", args.get("sku", "master")),
                                  entry.get("locale", args.get("locale", "und")), entry.get("aspect", args.get("aspect", "16x9")))
        final_metadata = _operation(job, "probe", destination)["metrics"]
        final_video = next(s for s in final_metadata["streams"] if s.get("codec_type") == "video")
        spec.setdefault("expected_width", final_video["width"])
        spec.setdefault("expected_height", final_video["height"])
        spec.pop("expected_sha256", None)
        spec.pop("expected_filename", None)
        result = inspect_file(job, destination.name, preset, spec)
        result.update(preset=preset_name, loudness=loudness, input_resolution=input_resolution,
                      source_resolution=entry.get("source_resolution"), upscaled=entry.get("upscaled", False))
        result["warnings"] = list(entry.get("warnings") or []) + result["warnings"]
        if result["source_resolution"] is None:
            result["warnings"].append("Original source_resolution is unknown; input dimensions do not prove native source detail.")
        if loudness and loudness["dynamic_fallback"]:
            result["warnings"].append("Linear loudness normalization was infeasible; FFmpeg used dynamic mode. Review the mix.")
        return result
    finally:
        for path in temporary_outputs:
            path.unlink(missing_ok=True)


def _run(tool_name: str, args: dict) -> dict:
    from providers.remotion import api

    base = {"status": "blocked", "passed": False, "files": [], "estimated_cost_usd": 0,
            "training_eligible": False, "license": "installed-ffmpeg-build-license"}
    try:
        validate_arguments(tool_name, args)
        if api.render_backend() != "local" or api._on_lambda():
            return {**base, "reason": "Delivery and QC require the local/worker host owning the job directory. Lambda is unsupported; render_timeline remains available."}
        if args.get("upload"):
            return {**base, "reason": "S3 upload is not available in this delivery job. Local QC reports are produced with upload=false; direct platform posting and public links are refused."}
        if api.dry_run():
            return {**base, "status": "dry_run", "warnings": ["Dry-run validates arguments only; no media was inspected or finished."]}
        job = job_directory(args["job_id"])
        with _manifest_lock(job):
            entries, manifest = _entries(job, args.get("input_path", ""), args.get("manifest_path", ""),
                                         final=tool_name == "qc_deliverable")
            files = []
            for entry in entries:
                try:
                    if tool_name == "deliver_render":
                        inspected = _finish(job, entry, args.get("preset", "social-feed"), args)
                        entry["delivery"] = {key: value for key, value in inspected.items()
                                             if key not in {"metrics", "checks", "review_frames", "contact_sheet"}}
                    else:
                        selected = entry.get("delivery", entry)
                        spec = dict(args.get("spec") or {})
                        if "sha256" in selected:
                            spec.setdefault("expected_sha256", selected["sha256"])
                        if "duration_s" in selected:
                            spec.setdefault("expected_duration_s", selected["duration_s"])
                        inspected = inspect_file(job, selected["file"], PRESETS[args.get("preset", "social-feed")], spec)
                        for key in ("source_resolution", "input_resolution", "upscaled"):
                            inspected[key] = selected.get(key, entry.get(key))
                        inspected["warnings"] = list(selected.get("warnings") or []) + inspected["warnings"]
                    entry["qc"] = inspected
                    if not inspected["passed"]:
                        entry["delivery_status"] = "failed"
                    else:
                        entry["delivery_status"] = "passed"
                    files.append(inspected)
                except (ValueError, OSError, KeyError, TypeError, StopIteration) as exc:
                    failed = {"file": entry.get("file"), "passed": False, "failures": [str(exc)], "checks": [
                        {"name": "processing", "severity": "error", "pass": False, "detail": str(exc)}]}
                    files.append(failed)
                    entry.update(qc=failed, delivery_status="failed")
            passed = bool(files) and all(file["passed"] for file in files)
            report = {**base, "status": "succeeded" if passed else "failed", "passed": passed, "files": files,
                      "preset": args.get("preset", "social-feed"), "job_id": args["job_id"],
                      "failures": [failure for file in files for failure in file.get("failures", [])]}
            report_path = output_file(job, "delivery-qc", ".json")
            report["report_path"] = str(report_path)
            _write_json(report_path, report)
            if manifest:
                _write_json(manifest, entries, replace=True)
                report["manifest_path"] = str(manifest)
            else:
                manifest = output_file(job, "delivery-manifest", ".json")
                _write_json(manifest, entries)
                report["manifest_path"] = str(manifest)
            return report
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return {**base, "reason": str(exc)}


def deliver_render(job_id: str, input_path: str = "", manifest_path: str = "", preset: str = "social-feed",
                   spec: dict | None = None, campaign: str = "campaign", sku: str = "master",
                   locale: str = "und", aspect: str = "16x9", upload: bool = False) -> dict:
    """Finish staged renders with a named preset, versioned filenames and final-file QC."""
    return _run("deliver_render", dict(job_id=job_id, input_path=input_path, manifest_path=manifest_path,
                preset=preset, spec=spec, campaign=campaign, sku=sku, locale=locale, aspect=aspect, upload=upload))


def qc_deliverable(job_id: str, input_path: str = "", manifest_path: str = "", preset: str = "social-feed",
                   spec: dict | None = None) -> dict:
    """Measure final local media against a delivery preset and write a pass/fail report."""
    return _run("qc_deliverable", dict(job_id=job_id, input_path=input_path, manifest_path=manifest_path,
                                       preset=preset, spec=spec))


def validate_delivery_report(result: dict) -> bool:
    """A finished claim needs stored reports and unchanged final files, including each check."""
    try:
        if result.get("status") != "succeeded" or result.get("passed") is not True or result.get("failures"):
            return False
        job = job_directory(result.get("job_id"))
        report_path = input_file(job, result.get("report_path"))
        if report_path.stat().st_size > MAX_JSON_BYTES:
            return False
        report = json.loads(report_path.read_text())
        if (report.get("status") != "succeeded" or report.get("passed") is not True or report.get("failures") or
                report.get("job_id") != result.get("job_id") or report.get("files") != result.get("files") or
                report.get("preset") != result.get("preset") or result.get("preset") not in PRESETS):
            return False
        files = report.get("files")
        if not isinstance(files, list) or not 1 <= len(files) <= 100:
            return False
        seen = set()
        for file in files:
            path = input_file(job, file.get("file"))
            if path in seen or not validate_file_report(job, file, PRESETS[result["preset"]]):
                return False
            seen.add(path)
        return True
    except (ValueError, OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return False
