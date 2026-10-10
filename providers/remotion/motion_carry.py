"""Local, independently authored motion carry measurements. No model or network calls."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
from typing import TYPE_CHECKING

from jsonschema import validate, ValidationError
if TYPE_CHECKING:
    import numpy as np

from providers.ffmpeg.sandbox import (ID_PATTERN, PATH_PATTERN, input_file, job_directory,
                                      output_file, sha256_file, validate_job_id)


CALIBRATION_PATH = Path(__file__).with_name("motion_carry_calibration.json")
CHECKS = ("uniform_cadence", "no_rests", "clipped_audio", "unblurred_fast_move", "subject_exit")
FPS, WIDTH, HEIGHT, MAX_SECONDS = 12, 96, 54, 120
PROBE_SLOT = threading.BoundedSemaphore(1)
BOX_SCHEMA = {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1},
              "minItems": 4, "maxItems": 4}
TIMELINE_SCHEMA = {
    "type": "object", "additionalProperties": False, "properties": {
        "beats_s": {"type": "array", "maxItems": 200, "minItems": 2,
                    "items": {"type": "number", "minimum": 0, "maximum": MAX_SECONDS}},
        "elements": {"type": "array", "maxItems": 100, "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "start_s", "end_s"],
            "properties": {
                "id": {"type": "string", "minLength": 1, "maxLength": 80},
                "start_s": {"type": "number", "minimum": 0, "maximum": MAX_SECONDS},
                "end_s": {"type": "number", "minimum": 0, "maximum": MAX_SECONDS},
                "main_subject": {"type": "boolean"}, "intentional_exit": {"type": "boolean"},
                "keyframes": {"type": "array", "minItems": 1, "maxItems": 500, "items": {
                    "type": "object", "additionalProperties": False, "required": ["time_s", "box"],
                    "properties": {"time_s": {"type": "number", "minimum": 0, "maximum": MAX_SECONDS},
                                   "box": BOX_SCHEMA}}}}}}}}
ARG_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["job_id", "input_path"],
              "properties": {"job_id": {"type": "string", "pattern": ID_PATTERN},
                             "input_path": {"type": "string", "pattern": PATH_PATTERN},
                             "timeline": TIMELINE_SCHEMA}}
EVIDENCE_SCHEMA = {"type": "array", "minItems": 1, "maxItems": 2000, "items": {
    "type": "object", "required": ["time_s"], "properties": {
        "time_s": {"type": "number", "minimum": 0, "maximum": MAX_SECONDS}}}}
CHECK_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["passed", "status", "metric", "threshold", "evidence", "fix"], "properties": {
        "passed": {"type": ["boolean", "null"]}, "status": {"enum": ["passed", "failed", "skipped"]},
        "metric": {"type": "number", "minimum": 0}, "threshold": {"type": "number", "minimum": 0},
        "evidence": EVIDENCE_SCHEMA, "fix": {"type": "string"}}}
REPORT_SCHEMA = {"type": "object", "required": ["schema_version", "status", "passed", "failures", "boundaries", "checks", "visual_review"],
    "properties": {
        "schema_version": {"const": 1}, "status": {"enum": ["passed", "failed", "skipped", "dry_run"]},
        "passed": {"type": "boolean"}, "failures": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"}, "visual_review": {"const": "pending"},
        "duration_s": {"type": "number", "exclusiveMinimum": 0, "maximum": MAX_SECONDS},
        "carry_score": {"type": "number", "minimum": 0},
        "boundary_source": {"enum": ["timeline", "video_and_audio"]},
        "calibration": {"type": "object", "required": ["provisional", "sha256"], "properties": {
            "provisional": {"type": "boolean"}, "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}},
        "boundaries": {"type": "array", "maxItems": 198, "items": {
            "type": "object", "required": ["time_s", "carry_score", "passed", "reason", "fix", "tracked_boxes", "element_ids"],
            "properties": {"time_s": {"type": "number", "minimum": 0, "maximum": MAX_SECONDS},
                "carry_score": {"type": "number", "minimum": 0}, "passed": {"type": "boolean"},
                "reason": {"type": "string"}, "fix": {"type": "string"},
                "tracked_boxes": {"type": "array", "maxItems": 7, "items": BOX_SCHEMA},
                "element_ids": {"type": "array", "items": {"type": "string"}}}}},
        "checks": {"type": "object", "additionalProperties": False,
                   "properties": {name: CHECK_SCHEMA for name in CHECKS}}},
    "allOf": [
        {"if": {"properties": {"status": {"enum": ["passed", "failed"]}}}, "then": {
            "required": ["duration_s", "carry_score", "boundary_source", "calibration"],
            "properties": {"checks": {"required": list(CHECKS)}}}},
        {"if": {"properties": {"status": {"const": "passed"}}}, "then": {
            "properties": {"passed": {"const": True}, "failures": {"maxItems": 0}, "boundaries": {"minItems": 1}}},
         "else": {"properties": {"passed": {"const": False}}}},
        {"if": {"properties": {"status": {"const": "failed"}}}, "then": {
            "properties": {"failures": {"minItems": 1}}}}]}


def validate_arguments(arguments: dict) -> None:
    try:
        validate(arguments, ARG_SCHEMA)
        validate_job_id(arguments["job_id"])
        timeline = arguments.get("timeline") or {}
        beats = timeline.get("beats_s", [])
        if any(not math.isfinite(t) for t in beats) or any(a >= b for a, b in zip(beats, beats[1:])):
            raise ValueError("beats_s must be finite and strictly increasing.")
        ids = []
        for element in timeline.get("elements", []):
            ids.append(element["id"])
            start, end = element["start_s"], element["end_s"]
            if not (math.isfinite(start) and math.isfinite(end) and start < end):
                raise ValueError("Element start_s must precede end_s and both must be finite.")
            keys = element.get("keyframes", [])
            times = [k["time_s"] for k in keys]
            if any(not math.isfinite(t) or not start <= t <= end for t in times) or any(
                    a >= b for a, b in zip(times, times[1:])):
                raise ValueError("Keyframes must be ordered inside their element lifetime.")
            if any(not all(math.isfinite(v) for v in k["box"]) or min(k["box"][2:]) <= 0 for k in keys):
                raise ValueError("Keyframe boxes must have finite coordinates and positive size.")
        if len(set(ids)) != len(ids):
            raise ValueError("Element IDs must be unique.")
        if sum(bool(e.get("main_subject")) for e in timeline.get("elements", [])) > 1:
            raise ValueError("Declare at most one main_subject.")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Invalid motion carry arguments or timeline.") from exc


@dataclass
class Region:
    box: np.ndarray
    colour: np.ndarray
    shape: np.ndarray
    sharpness: float


def _regions(frame: np.ndarray) -> list[Region]:
    import numpy as np
    from PIL import Image

    h, w = frame.shape[:2]
    background = np.median(frame[[0, 0, h-1, h-1], [0, w-1, 0, w-1]], axis=0)
    distance = np.max(np.abs(frame.astype(float) - background), axis=2)
    if not distance.max():
        return []
    mask = distance > distance.max() / 4
    seen = np.zeros(mask.shape, dtype=bool)
    components = []
    for y, x in zip(*np.where(mask)):
        if seen[y, x]:
            continue
        stack, pixels = [(int(y), int(x))], []
        seen[y, x] = True
        while stack:
            row, col = stack.pop()
            pixels.append((row, col))
            for nr, nc in ((row-1, col), (row+1, col), (row, col-1), (row, col+1)):
                if 0 <= nr < h and 0 <= nc < w and mask[nr, nc] and not seen[nr, nc]:
                    seen[nr, nc] = True
                    stack.append((nr, nc))
        if len(pixels) >= 4:
            components.append(pixels)
    result = []
    for pixels in sorted(components, key=len, reverse=True)[:6]:
        ys, xs = np.array(pixels).T
        left, top, right, bottom = int(xs.min()), int(ys.min()), int(xs.max()+1), int(ys.max()+1)
        if right-left == w and bottom-top == h:
            continue
        crop = frame[max(0, top-1):min(h, bottom+1), max(0, left-1):min(w, right+1)].astype(float)
        sharpness = max(float(np.max(np.abs(np.diff(crop, axis=axis)))) for axis in (0, 1)) / 255
        shape = np.asarray(Image.fromarray(mask[top:bottom, left:right]).resize((16, 16)), dtype=float)
        box = np.array([left/w, top/h, (right-left)/w, (bottom-top)/h])
        result.append(Region(box, frame[ys, xs].mean(axis=0)/255, shape, sharpness))
    return result


def _similarity(a: Region, b: Region) -> float:
    import numpy as np

    return max(0, 1 - float(np.abs(a.colour-b.colour).mean()) - float(np.abs(a.shape-b.shape).mean()))


def _movement(a: Region, b: Region) -> float:
    import numpy as np

    return float(np.linalg.norm(a.box[:2] + a.box[2:]/2 - b.box[:2] - b.box[2:]/2)
                 + np.abs(a.box[2:]-b.box[2:]).mean())


def _box_at(element: dict, time_s: float) -> np.ndarray | None:
    import numpy as np

    keys = element.get("keyframes", [])
    if not keys:
        return None
    for before, after in zip(keys, keys[1:]):
        if before["time_s"] <= time_s <= after["time_s"]:
            weight = (time_s-before["time_s"])/(after["time_s"]-before["time_s"])
            return np.array(before["box"])*(1-weight)+np.array(after["box"])*weight
    return np.array(keys[0 if time_s < keys[0]["time_s"] else -1]["box"])


def _overlap(a: np.ndarray, b: np.ndarray) -> float:
    import numpy as np

    size = np.maximum(0, np.minimum(a[:2]+a[2:], b[:2]+b[2:])-np.maximum(a[:2], b[:2]))
    intersection = float(np.prod(size))
    return intersection / (float(np.prod(a[2:])+np.prod(b[2:]))-intersection)


def _carry(window: list[list[Region]]) -> tuple[float, list[list[float]]]:
    import numpy as np

    best, boxes = 0.0, []
    if not window or any(not regions for regions in window):
        return best, boxes
    for first in window[0]:
        track, similarities, steps = [first], [], []
        for regions in window[1:]:
            previous = track[-1]
            current = min(regions, key=lambda r: 1-_similarity(previous, r)+_movement(previous, r))
            similarities.append(_similarity(previous, current))
            steps.append(_movement(previous, current))
            track.append(current)
        maximum = max(steps, default=0)
        continuity = float(np.median(steps)) / maximum if maximum else 0
        transform = sum(steps)
        score = min(similarities, default=0) * continuity * transform
        if score > best:
            best, boxes = score, [r.box.tolist() for r in track]
    return best, boxes


def _runs(values: list[bool], fps: float) -> list[dict]:
    spans, start = [], None
    for i, value in enumerate([*values, False]):
        if value and start is None:
            start = i
        elif not value and start is not None:
            spans.append({"time_s": start/fps, "end_s": i/fps, "duration_s": (i-start)/fps})
            start = None
    return spans


def _audio_statistics(audio: np.ndarray | None, sample_rate: int, fps: float) -> dict:
    import numpy as np

    energy, peak, peak_time, rails = [], 0.0, 0.0, 0
    present = audio is not None and bool(audio.size)
    if present:
        channels = audio.shape[1] if audio.ndim == 2 else 1
        block = max(1, round(sample_rate/fps))
        for start in range(0, len(audio), block):
            samples = np.abs(audio[start:start+block])
            block_peak = float(samples.max())
            if block_peak > peak:
                peak, peak_time = block_peak, (start + int(np.argmax(samples)) // channels)/sample_rate
            rails += int(np.count_nonzero(samples >= 1))
            mono = samples.max(axis=1) if samples.ndim == 2 else samples
            energy.append(float(np.mean(mono**2)))
    rises = np.maximum(0, np.diff(energy))
    onset_times = [(i+1)/fps for i, rise in enumerate(rises)
                   if rise > np.median(rises)+4*np.median(np.abs(rises-np.median(rises))) and rise > 0]
    return {"audio_peak": peak, "audio_peak_time_s": peak_time, "audio_present": present,
            "audio_rail_fraction": rails/audio.size if present else 0, "audio_onsets_s": onset_times}


def measure_frames(frames: np.ndarray, fps: float, *, timeline: dict | None = None,
                   audio: np.ndarray | None = None, sample_rate: int = 192000) -> dict:
    import numpy as np

    if len(frames) < 3 or not np.isfinite(fps) or fps <= 0:
        raise ValueError("Too few frames or invalid frame rate.")
    duration = len(frames)/fps
    timeline = timeline or {}
    validate_arguments({"job_id": "measurement", "input_path": "film.mp4", "timeline": timeline})
    beats = timeline.get("beats_s")
    if beats and (abs(beats[0]) > 1/fps or abs(beats[-1]-duration) > 2/fps):
        raise ValueError("beats_s must cover the measured film from zero to duration.")
    if any(e["end_s"] > duration + 1/fps for e in timeline.get("elements", [])):
        raise ValueError("Element lifetime exceeds the measured film.")
    regions = [_regions(frame) for frame in frames]
    deltas = np.array([np.abs(after.astype(np.float32)-before).mean()/255
                       for before, after in zip(frames, frames[1:])])
    scene_times = [i/fps for i in range(1, len(frames)-1)
                   if deltas[i-1] > np.median(deltas) + 4*np.median(np.abs(deltas-np.median(deltas)))
                   and deltas[i-1] > max(deltas[i-2] if i > 1 else 0, deltas[i])]
    audio_stats = _audio_statistics(audio, sample_rate, fps)
    onset_times = audio_stats["audio_onsets_s"]
    if beats is None:
        candidates = sorted(set(scene_times + onset_times))
        boundaries = []
        for t in candidates:
            if 2/fps < t < duration-2/fps and (not boundaries or t-boundaries[-1] >= 4/fps):
                boundaries.append(t)
        beats = [0, *boundaries[:198], duration]
    boundaries = []
    for t in beats[1:-1]:
        index = round(t*fps)
        lo, hi = max(0, index-3), min(len(frames), index+4)
        score, boxes = _carry(regions[lo:hi])
        ids = [e["id"] for e in timeline.get("elements", []) if e["start_s"] <= lo/fps and e["end_s"] >= hi/fps
               and boxes and (not e.get("keyframes") or
                              all(_overlap(np.array(box), _box_at(e, (lo+j)/fps)) > 0 for j, box in enumerate(boxes)))]
        boundaries.append({"time_s": t, "carry_score": score, "tracked_boxes": boxes,
                           "window_start_s": lo/fps, "element_ids": ids})
    speeds, sharp_moves, exits = [], [], []
    previous = None
    for i, candidates in enumerate(regions):
        main = next((e for e in timeline.get("elements", []) if e.get("main_subject") and
                     e["start_s"] <= i/fps <= e["end_s"]), None)
        declared_box = _box_at(main, i/fps) if main else None
        if declared_box is not None:
            candidates = sorted(candidates, key=lambda r: _overlap(r.box, declared_box), reverse=True)
            candidates = [r for r in candidates if _overlap(r.box, declared_box) > 0]
        subject = candidates[0] if candidates else None
        speed = _movement(previous, subject)*fps if previous and subject else 0
        speeds.append(speed)
        sharp_moves.append(speed*subject.sharpness if subject else 0)
        intentional = bool(main and main.get("intentional_exit"))
        edge = subject and (subject.box[0] <= 0 or subject.box[1] <= 0 or
                            subject.box[0]+subject.box[2] >= 1 or subject.box[1]+subject.box[3] >= 1)
        exits.append(bool(edge and not intentional))
        previous = subject
    lengths = np.diff(beats)
    cadence = float(lengths.std()/lengths.mean()) if len(lengths) else 0
    return {"duration_s": duration, "boundaries": boundaries, "beat_times_s": beats,
            "boundary_source": "timeline" if timeline.get("beats_s") else "video_and_audio",
            "scene_times_s": scene_times, "audio_onsets_s": onset_times, "cadence_cv": cadence,
            "frame_deltas": deltas.tolist(), "speeds": speeds, "sharp_moves": sharp_moves,
            "exits": exits, **audio_stats,
            "tracked_fraction": sum(bool(r) for r in regions)/len(regions), "fps": fps}


def metrics(measured: dict, still_delta: float) -> dict:
    rests = _runs([d <= still_delta for d in measured["frame_deltas"]], measured["fps"])
    return {"carry": min((b["carry_score"] for b in measured["boundaries"]), default=0),
            "uniform_cadence": measured["cadence_cv"],
            "no_rests": max((s["duration_s"] for s in rests), default=0),
            "clipped_audio": max(0, measured["audio_peak"]-1) + measured["audio_rail_fraction"],
            "unblurred_fast_move": max(measured["sharp_moves"], default=0),
            "subject_exit": sum(measured["exits"])/len(measured["exits"])}


def _report(measured: dict, calibration: dict) -> dict:
    import numpy as np

    thresholds = calibration["thresholds"]
    values = metrics(measured, thresholds["still_delta"])
    fixes = {
        "uniform_cadence": "Vary the beat lengths around the listed cuts while preserving the approved copy.",
        "no_rests": "Add a held moment after the last reveal so its text and product can settle.",
        "clipped_audio": "Lower the source gain at the listed peak and re-export the soundtrack.",
        "unblurred_fast_move": "Add motion blur to the tracked move at this time, or slow that move.",
        "subject_exit": "Reframe the tracked subject at this time, or declare its planned exit in the timeline.",
    }
    checks = {}
    for name in CHECKS:
        high_pass = name in {"uniform_cadence", "no_rests"}
        passed = values[name] >= thresholds[name] if high_pass else values[name] <= thresholds[name]
        evidence = []
        if name == "uniform_cadence":
            evidence = [{"time_s": t, "beat_length_s": end-t} for t, end in zip(measured["beat_times_s"], measured["beat_times_s"][1:])]
        elif name == "no_rests":
            evidence = _runs([d <= thresholds["still_delta"] for d in measured["frame_deltas"]], measured["fps"])
            if not evidence:
                evidence = [{"time_s": 0, "end_s": measured["duration_s"], "detail": "No held frames detected."}]
        elif name == "clipped_audio":
            evidence = [{"time_s": measured["audio_peak_time_s"], "oversampled_peak": measured["audio_peak"],
                         "rail_contact_fraction": measured["audio_rail_fraction"],
                         "audio_present": measured["audio_present"]}]
        elif name == "unblurred_fast_move":
            index = int(np.argmax(measured["sharp_moves"]))
            evidence = [{"time_s": index/measured["fps"], "speed_times_sharpness": values[name]}]
        else:
            evidence = _runs(measured["exits"], measured["fps"]) or [{"time_s": 0, "detail": "No tracked edge contact."}]
        skipped = name == "uniform_cadence" and len(measured["beat_times_s"]) < 4
        skipped |= name in {"subject_exit", "unblurred_fast_move"} and measured["tracked_fraction"] == 0
        checks[name] = {"passed": None if skipped else bool(passed), "status": "skipped" if skipped else "passed" if passed else "failed",
                        "metric": values[name], "threshold": thresholds[name], "evidence": evidence,
                        "fix": (fixes[name] + f" Evidence starts at {evidence[0]['time_s']:.3f}s.") if not passed else ""}
    boundaries = []
    for b in measured["boundaries"]:
        passed = b["carry_score"] >= thresholds["carry"]
        name = b["element_ids"][0] if b["element_ids"] else "the visible tracked region"
        boundaries.append({**b, "passed": bool(passed), "what_carried": name if passed else None,
            "identity_source": "timeline candidates supported by pixel tracking" if b["element_ids"] else "pixel region tracking",
            "reason": "A visible region persists and transforms through the boundary." if passed else
                      "No continuously transforming visible region survived; static identity, a cut, or fade replacement is insufficient.",
            "fix": "" if passed else f"Carry {name} continuously across {b['time_s']:.3f}s."})
    failures = [f"carry at {b['time_s']:.3f}s: {b['fix']}" for b in boundaries if not b["passed"]]
    failures += [f"{name}: {check['fix']}" for name, check in checks.items() if check["passed"] is False]
    skipped = not boundaries or any(c["status"] == "skipped" for c in checks.values())
    status = "failed" if failures else "skipped" if skipped else "passed"
    return {"schema_version": 1, "status": status, "passed": status == "passed", "failures": failures,
            "reason": "Insufficient detected beats or trackable regions; supply exact timeline metadata." if skipped else "",
            "duration_s": measured["duration_s"], "carry_score": float(np.mean([b["carry_score"] for b in boundaries])) if boundaries else 0,
            "boundaries": boundaries, "checks": checks, "boundary_source": measured["boundary_source"],
            "audio_onsets_s": measured["audio_onsets_s"],
            "calibration": {"provisional": calibration["provisional"], "sha256": sha256_file(CALIBRATION_PATH)},
            "visual_review": "pending", "limitations": [
                "Foreground region tracking is heuristic; it does not identify people or read text.",
                "Low-contrast, occluded, full-frame or very brief motion can be unmeasurable at the sampled resolution.",
                "Edge contact is a possible unintended exit; exact intent requires timeline metadata and human review.",
                "Audio peak uses four-times oversampling; thresholds are provisional, not a broadcast loudness certification."]}


def analyse_frames(frames: np.ndarray, fps: float, *, timeline: dict | None = None,
                   audio: np.ndarray | None = None, sample_rate: int = 192000) -> dict:
    return _report(measure_frames(frames, fps, timeline=timeline, audio=audio, sample_rate=sample_rate),
                   json.loads(CALIBRATION_PATH.read_text()))


def _run(command: list[str], *, timeout: int = 45) -> bytes:
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    if result.returncode:
        raise ValueError("Local media measurement failed; input may be corrupt or unsupported.")
    return result.stdout


def decode(path: Path) -> tuple[np.ndarray, np.ndarray | None]:
    import numpy as np

    restrictions = ["-protocol_whitelist", "file,pipe", "-format_whitelist", "mov"]
    data = json.loads(_run(["ffprobe", "-v", "error", *restrictions, "-show_entries",
                           "format=duration:stream=codec_type,channels", "-of", "json", str(path)]))
    duration = float(data["format"]["duration"])
    if not math.isfinite(duration) or not 0 < duration <= MAX_SECONDS:
        raise ValueError(f"Motion carry analysis accepts films up to {MAX_SECONDS} seconds.")
    prefix = ["ffmpeg", "-nostdin", "-v", "error", *restrictions, "-i", str(path), "-t", str(duration)]
    raw = _run([*prefix, "-map", "0:v:0", "-vf", f"fps={FPS},scale={WIDTH}:{HEIGHT}", "-threads", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
    frames = np.frombuffer(raw, np.uint8).reshape((-1, HEIGHT, WIDTH, 3))
    audio = None
    if any(s.get("codec_type") == "audio" for s in data["streams"]):
        channels = next(s["channels"] for s in data["streams"] if s.get("codec_type") == "audio")
        if not 1 <= channels <= 2:
            raise ValueError("Audio measurement currently supports mono or stereo without downmixing.")
        with tempfile.TemporaryFile() as audio_file:
            result = subprocess.run([*prefix, "-map", "0:a:0", "-ar", "192000", "-threads", "1", "-f", "f32le", "pipe:1"],
                                    stdout=audio_file, stderr=subprocess.DEVNULL, timeout=45, check=False)
            size = audio_file.tell()
            if result.returncode or size > (MAX_SECONDS+1)*192000*channels*4 or size % (channels*4):
                raise ValueError("Local audio measurement failed or exceeded its size limit.")
            if size:
                # The map retains its handle after the anonymous temporary file closes.
                audio = np.memmap(audio_file, mode="r", dtype="<f4", shape=(size//(channels*4), channels))
    return frames, audio


def probe_file(path: Path, timeline: dict | None = None) -> dict:
    frames, audio = decode(path)
    return analyse_frames(frames, FPS, timeline=timeline, audio=audio)


def stage_local_render(job_id: str, result: dict, owned_render_ids: set[str]) -> dict:
    """Trusted host bridge from an owned local render poll into the job sandbox."""
    if (result.get("status") != "succeeded" or result.get("backend") != "local" or
            os.getenv("MOTION_CARRY_QC_DRY_RUN", "true").lower() not in {"0", "false", "no"}):
        return result
    try:
        validate_job_id(job_id)
        render_id = result["render_id"]
        if render_id not in owned_render_ids or not re.fullmatch(r"local-[0-9a-f]{32}", render_id):
            raise ValueError("The local render is not owned by this Studio execution.")
        root = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser().resolve()
        render_dir = root / "remotion" / "local" / render_id
        if render_dir.resolve() != render_dir:
            raise ValueError("Local render directory must not redirect outside its expected location.")
        source = input_file(render_dir, result["output_path"])
        if source.suffix.lower() != ".mp4":
            raise ValueError("The completed local render must be an MP4.")
        directory = root / job_id
        if directory.resolve() != directory:
            raise ValueError("Studio job directory must not redirect to another location.")
        directory.mkdir(exist_ok=True)
        directory = job_directory(job_id)
        checksum = sha256_file(source)
        destination = directory / f"motion-input-{checksum}.mp4"
        if destination.exists() or destination.is_symlink():
            destination = input_file(directory, str(destination))
            if sha256_file(destination) != checksum:
                raise ValueError("Previously staged local render changed.")
        else:
            temporary = output_file(directory, "motion-input", ".mp4")
            try:
                shutil.copyfile(source, temporary)
                if sha256_file(temporary) != checksum or sha256_file(source) != checksum:
                    raise ValueError("Local render changed while staging; poll again.")
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
        return {**result, "output_path": str(destination), "motion_carry_staged": True}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Staging failure cannot turn a completed render into a failed render.
        return {**result, "motion_carry_staging": "skipped", "motion_carry_reason": str(exc)[:200]}


def motion_carry_probe(job_id: str, input_path: str, timeline: dict | None = None) -> dict:
    """Score a local rendered MP4 for motion carry and five separate rhythm checks. Free; no network."""
    args = {"job_id": job_id, "input_path": input_path, "timeline": timeline or {}}
    validate_arguments(args)
    base = {"schema_version": 1, "job_id": job_id, "passed": False, "failures": [],
            "boundaries": [], "checks": {}, "visual_review": "pending"}
    if os.getenv("MOTION_CARRY_QC_DRY_RUN", "true").lower() not in {"0", "false", "no"}:
        return {**base, "status": "dry_run", "reason": "Local motion carry measurement is dry-run; no media was read."}
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return {**base, "status": "skipped", "reason": "Motion carry requires the local worker and its owned MP4; Lambda measurement is unavailable."}
    if not PROBE_SLOT.acquire(blocking=False):
        return {**base, "status": "skipped", "reason": "Local motion carry worker is busy; retry after its active probe finishes."}
    try:
        directory = job_directory(job_id)
        source = input_file(directory, input_path)
        if source.suffix.lower() != ".mp4":
            raise ValueError("Motion carry requires a rendered MP4 inside the job directory.")
        checksum = sha256_file(source)
        import hashlib

        timeline_hash = hashlib.sha256(json.dumps(timeline or {}, sort_keys=True, allow_nan=False).encode()).hexdigest()
        report = {**base, **probe_file(source, timeline), "input_path": str(source), "sha256": checksum,
                  "timeline_sha256": timeline_hash}
        if sha256_file(source) != checksum:
            raise ValueError("Input changed during the probe; rerun on the current artifact.")
        destination = output_file(directory, "motion-carry", ".json")
        report["report_path"] = str(destination)
        destination.write_text(json.dumps(report, allow_nan=False, indent=2) + "\n")
        return report
    except Exception as exc:
        return {**base, "status": "skipped", "reason": f"Motion carry measurement unavailable ({type(exc).__name__}): {str(exc)[:200]}"}
    finally:
        PROBE_SLOT.release()


def validate_report(report: dict, *, require_pass: bool = True) -> bool:
    try:
        validate(report, REPORT_SCHEMA)
        directory = job_directory(report["job_id"])
        saved = input_file(directory, report["report_path"])
        source = input_file(directory, report["input_path"])
        if json.loads(saved.read_text()) != report or sha256_file(source) != report["sha256"]:
            return False
        if report["calibration"]["sha256"] != sha256_file(CALIBRATION_PATH) or report["schema_version"] != 1:
            return False
        if report["calibration"]["provisional"] != json.loads(CALIBRATION_PATH.read_text())["provisional"]:
            return False
        if set(report["checks"]) != set(CHECKS) or not report["boundaries"]:
            return False
        passed = (all(b["passed"] is True for b in report["boundaries"]) and
                  all(c["passed"] is True and c["status"] == "passed" for c in report["checks"].values()) and not report["failures"])
        return report["status"] in {"passed", "failed", "skipped"} and (not require_pass or passed and report["passed"] is True and report["status"] == "passed")
    except (OSError, ValueError, KeyError, TypeError, ValidationError):
        return False
