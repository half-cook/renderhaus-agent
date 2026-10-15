from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
import json
import math
from pathlib import Path
import re
import shutil
import time
import uuid

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pydantic import ValidationError

from providers.ffmpeg import api as media_api
from providers.ffmpeg.commands import FORMATS, THREADS
from providers.ffmpeg.sandbox import input_file, sha256_file, validate_input_path
from providers.reference_shots.contracts import (
    ContactSheet, Integrity, Measurements, MeasuredShot, PinnedFile, Player, Source, ThresholdResult,
)


MAX_EMBED_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 128 * 1024
MAX_FRAME_COUNT = 72000
GRAY_WIDTH, GRAY_HEIGHT = 64, 36
GRAY_FRAME_BYTES = GRAY_WIDTH * GRAY_HEIGHT
MAX_RAW_BYTES = (MAX_FRAME_COUNT + 1) * GRAY_FRAME_BYTES
MAX_BUNDLE_BYTES = 32 * 1024 * 1024
NEAR_ZERO_MOTION = .001
HIGH_MOTION = .04


@dataclass(frozen=True)
class Budget:
    deadline: float

    def remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("Reference analysis exceeded its hard deadline.")
        return remaining


def _run(argv: list[str], directory: Path, budget: Budget, *, diagnostics: bool = False) -> media_api.ProcessResult:
    process = media_api._bounded_run(argv, directory, budget.remaining(), stderr_bytes=65536)
    budget.remaining()
    if process.stdout_truncated or process.stderr_truncated:
        raise ValueError("Media inspection exceeded its bounded capture; incomplete measurements were rejected.")
    if process.returncode or (process.stderr.strip() and not diagnostics):
        raise ValueError("Media decoding failed or reported errors; incomplete measurements were rejected.")
    return process


def _binary(name: str) -> str:
    binary = shutil.which(name)
    if not binary:
        raise ValueError("Local media inspection binaries are unavailable on this host.")
    return binary


def _input_argv(directory: Path, source: Path, seek: float | None = None) -> list[str]:
    argv = [_binary("ffmpeg"), "-nostdin", "-hide_banner", "-v", "error", "-n", "-xerror",
            "-max_alloc", "67108864", "-filter_threads", str(THREADS),
            "-filter_complex_threads", str(THREADS), "-threads", str(THREADS),
            "-err_detect", "explode", "-protocol_whitelist", "file,pipe",
            "-format_whitelist", FORMATS]
    if seek is not None:
        argv += ["-ss", format(seek, ".12g"), "-accurate_seek"]
    return [*argv, "-i", "./" + source.relative_to(directory).as_posix()]


def _probe(directory: Path, source: Path, budget: Budget) -> dict:
    budget.remaining()
    result = media_api.execute("probe", directory, str(source))
    budget.remaining()
    if not result.get("ok"):
        raise ValueError("The reference film could not be probed as supported local media.")
    return result["metrics"]


def _video_info(probe: dict) -> tuple[dict, float, float]:
    video = next((stream for stream in probe["streams"] if stream.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("A reference film must contain a video stream.")
    try:
        duration = float(video.get("duration") or probe["format"].get("duration", 0))
        fps = float(Fraction(video.get("avg_frame_rate") or video.get("r_frame_rate", "0")))
        width, height = video["width"], video["height"]
        if (not math.isfinite(duration) or not 0 < duration <= 600
                or not math.isfinite(fps) or not 0 < fps <= 120
                or type(width) is not int or type(height) is not int
                or not 2 <= width <= 4096 or not 2 <= height <= 4096
                or width * height > 16 * 1024 * 1024 or duration * fps > MAX_FRAME_COUNT):
            raise ValueError
    except (ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError):
        raise ValueError("Reference films require a measured duration of at most 600 seconds, "
                         "at most 120 fps and bounded dimensions up to 4096 pixels.") from None
    return video, duration, fps


def _decode_complete(directory: Path, source: Path, duration: float, fps: float,
                     video: dict, budget: Budget) -> int:
    process = _run([*_input_argv(directory, source), "-map", "0:v:0", "-an", "-sn", "-dn",
                    "-frames:v", str(MAX_FRAME_COUNT + 1), "-fps_mode", "passthrough",
                    "-progress", "pipe:1", "-nostats", "-f", "null", "-"], directory, budget)
    progress = process.stdout.decode("ascii", errors="strict")
    frames = re.findall(r"^frame=(\d+)\s*$", progress, re.MULTILINE)
    times = re.findall(r"^out_time_us=(-?\d+)\s*$", progress, re.MULTILINE)
    if not frames or not times or not progress.rstrip().endswith("progress=end"):
        raise ValueError("The complete video decode did not produce a terminal measurement.")
    count, decoded_duration = int(frames[-1]), int(times[-1]) / 1_000_000
    if (not 0 < count <= MAX_FRAME_COUNT
            or abs(decoded_duration - duration) > max(.1, 2 / fps)):
        raise ValueError("Decoded video duration is incomplete or exceeds the measured film duration.")
    declared = video.get("nb_frames")
    if declared and declared != "N/A" and (not str(declared).isdigit() or int(declared) != count):
        raise ValueError("Decoded frame count does not match the complete video stream.")
    return count


def _scene_sweep(directory: Path, source: Path, duration: float, fps: float,
                 budget: Budget) -> tuple[list[ThresholdResult], ThresholdResult]:
    thresholds = [.2, .3, .4] if duration <= 120 else [.3]
    sweep = []
    for threshold in thresholds:
        budget.remaining()
        result = media_api.execute("detect_scenes", directory, str(source), {"T": threshold})
        budget.remaining()
        if not result.get("ok"):
            raise ValueError("Complete bounded scene detection failed; split overly dense films into shorter references.")
        values = result["metrics"].get("scene_times", [])
        if (not isinstance(values, list) or len(values) >= 60
                or any(not isinstance(value, (float, int)) or not math.isfinite(value)
                       or not 0 < value < duration for value in values)
                or any(right <= left for left, right in zip(values, values[1:]))):
            raise ValueError("Scene detection did not produce a complete increasing list of at most 59 cuts.")
        sweep.append(ThresholdResult(threshold=threshold, scene_times_s=values))
    groups = defaultdict(list)
    for item in sweep:
        signature = tuple(round(value * fps * 2) for value in item.scene_times_s)
        groups[signature].append(item)
    stable = max(groups.values(), key=lambda items: (
        len(items), -min(abs(item.threshold - .3) for item in items)))
    selected = min(stable, key=lambda item: abs(item.threshold - .3))
    return sweep, selected


def _motion(directory: Path, source: Path, scratch: Path, start: float, duration: float,
            budget: Budget) -> tuple[float | None, int, int]:
    try:
        _run([*_input_argv(directory, source, start), "-t", format(duration, ".12g"),
              "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", "scale=64:36:flags=area,format=gray",
              "-fps_mode", "passthrough", "-c:v", "rawvideo", "-threads", str(THREADS),
              "-f", "rawvideo", "-fs", str(MAX_RAW_BYTES),
              "./" + scratch.relative_to(directory).as_posix()], directory, budget)
        size = scratch.stat().st_size
        if not 0 < size < MAX_RAW_BYTES or size % GRAY_FRAME_BYTES:
            raise ValueError("Native-frame motion decoding was empty, truncated or exceeded its byte cap.")
        count = size // GRAY_FRAME_BYTES
        differences = []
        frames = np.memmap(scratch, dtype=np.uint8, mode="r", shape=(count, GRAY_FRAME_BYTES))
        try:
            for offset in range(0, count - 1, 256):
                budget.remaining()
                chunk = frames[offset:min(count, offset + 257)].astype(np.int16)
                differences.extend(np.abs(np.diff(chunk, axis=0)).mean(axis=1).tolist())
        finally:
            del frames
        if not differences:
            return None, 0, count
        return float(np.median(differences) / 255), count - 1, count
    finally:
        scratch.unlink(missing_ok=True)


def _frame(directory: Path, source: Path, target: Path, timestamp: float,
           start: float, end: float, fps: float, frame_count: int, budget: Budget) -> float:
    seek = start if frame_count == 1 else max(start, min(timestamp, end - 1 / fps - 1e-6))
    argv = _input_argv(directory, source, seek)
    argv[argv.index("-v") + 1] = "info"
    process = _run([*argv, "-map", "0:v:0", "-frames:v", "1",
          "-an", "-sn", "-dn", "-vf",
          "scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2,showinfo",
          "-threads", str(THREADS), "-fs", "1048576", "-update", "1",
          "./" + target.relative_to(directory).as_posix()], directory, budget, diagnostics=True)
    if not target.is_file() or not 0 < target.stat().st_size < 1024 * 1024:
        raise ValueError("A measured keyframe was missing or exceeded its bounded size.")
    matches = re.findall(r"^\[Parsed_showinfo_\d+ @ 0x[0-9a-fA-F]+\]\s+n:\s*\d+\s+"
                         r"pts:\s*-?\d+\s+pts_time:([0-9.eE+-]+)(?:\s|$)",
                         process.stderr.decode("utf-8", errors="replace"), re.MULTILINE)
    observed = seek + float(matches[0]) if matches else math.nan
    if not math.isfinite(observed) or not start - 1e-6 <= observed < end:
        raise ValueError("A short shot could not be sampled without crossing its measured cut; no report was exported.")
    return max(start, observed)


def _pin(directory: Path, path: Path) -> PinnedFile:
    return PinnedFile(path=path.relative_to(directory).as_posix(), sha256=sha256_file(path),
                      bytes=path.stat().st_size)


def _sheets(directory: Path, bundle: Path, shots: list[MeasuredShot],
            budget: Budget) -> list[ContactSheet]:
    records = []
    font = ImageFont.load_default(size=16)
    for offset in range(0, len(shots), 10):
        group = shots[offset:offset + 10]
        canvas = Image.new("RGB", (664, 40 + len(group) * 224), "#11151a")
        draw = ImageDraw.Draw(canvas)
        draw.text((12, 10), "Measured keyframes, 15% and 85% of each shot", fill="white", font=font)
        for row, shot in enumerate(group):
            budget.remaining()
            top = 40 + row * 224
            draw.text((12, top), f"Shot {shot.shot_id}    {shot.start_s:.2f}s to {shot.end_s:.2f}s",
                      fill="white", font=font)
            for column, timestamp in enumerate(shot.sampled_frame_times_s):
                frame = bundle / f"frame-{shot.shot_id:02}-{column}.png"
                try:
                    with Image.open(frame) as image:
                        image.load()
                        if image.size != (320, 180):
                            raise ValueError("Keyframe dimensions do not match the fixed sheet geometry.")
                        canvas.paste(image.convert("RGB"), (8 + column * 328, top + 22))
                    draw.text((12 + column * 328, top + 204),
                              f"{15 if column == 0 else 85}% target, frame {timestamp:.2f}s", fill="#b9c4d1", font=font)
                finally:
                    frame.unlink(missing_ok=True)
        path = bundle / f"contact-sheet-{offset // 10 + 1:02}.jpg"
        try:
            with path.open("xb") as output:
                canvas.save(output, format="JPEG", quality=84)
        finally:
            canvas.close()
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("A contact sheet exceeded its 2 MiB cap.")
        records.append(ContactSheet(**_pin(directory, path).model_dump(),
                                    shot_ids=[shot.shot_id for shot in group]))
    return records


def _player(directory: Path, source: Path, bundle: Path, probe: dict, source_record: Source,
            budget: Budget) -> Player:
    video, duration, _ = _video_info(probe)
    audio = [stream for stream in probe["streams"] if stream.get("codec_type") == "audio"]
    compatible = (source.suffix.lower() == ".mp4" and video.get("codec_name") == "h264"
                  and video.get("pix_fmt") == "yuv420p"
                  and all(stream.get("codec_name") in {"aac", "mp3"} for stream in audio)
                  and sum(stream.get("codec_type") == "video" for stream in probe["streams"]) == 1)
    if compatible and source_record.bytes <= MAX_EMBED_BYTES:
        return Player(**{key: getattr(source_record, key) for key in ("path", "sha256", "bytes")},
                      kind="source", duration_s=duration, width=source_record.width, height=source_record.height)
    output = bundle / "review-player.mp4"
    audio_bitrate = 32000 if audio else 0
    video_bitrate = min(500000, int(MAX_EMBED_BYTES * 8 * .82 / duration) - audio_bitrate)
    if video_bitrate < 30000:
        raise ValueError("A complete review player cannot fit within the 8 MiB media cap.")
    argv = [*_input_argv(directory, source), "-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn",
            "-vf", "scale=w='min(iw,640)':h='min(ih,360)':force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
            "-c:v", "libx264", "-profile:v", "main", "-pix_fmt", "yuv420p", "-preset", "veryfast",
            "-b:v", str(video_bitrate), "-maxrate", str(video_bitrate), "-bufsize", str(video_bitrate * 2),
            "-r", "24", "-c:a", "aac", "-b:a", "32k", "-ac", "1", "-threads", str(THREADS),
            "-map_metadata", "-1", "-movflags", "+faststart", "-fs", str(MAX_EMBED_BYTES),
            "./" + output.relative_to(directory).as_posix()]
    _run(argv, directory, budget)
    if not 0 < output.stat().st_size < MAX_EMBED_BYTES:
        raise ValueError("The review player exceeded its 8 MiB cap; incomplete media was rejected.")
    output_probe = _probe(directory, output, budget)
    output_video, measured_duration, fps = _video_info(output_probe)
    if abs(measured_duration - duration) > max(.1, 2 / source_record.fps):
        raise ValueError("The bounded review player does not cover the complete reference film.")
    _decode_complete(directory, output, measured_duration, fps, output_video, budget)
    return Player(**_pin(directory, output).model_dump(), kind="proxy", duration_s=measured_duration,
                  width=output_video["width"], height=output_video["height"])


def write_json(path: Path, payload: dict, limit: int = MAX_MANIFEST_BYTES) -> None:
    data = (json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    if len(data) > limit:
        raise ValueError("Reference report data exceeded its bounded size.")
    with path.open("xb") as output:
        output.write(data)


def new_bundle(directory: Path, prefix: str) -> Path:
    bundle = directory / f"reference-{prefix}-{uuid.uuid4().hex}"
    bundle.mkdir(mode=0o700)
    return bundle


def output_records(paths: list[Path]) -> list[dict]:
    records = []
    total = 0
    for path in paths:
        size = path.stat().st_size
        if not path.is_file() or not 0 < size <= 16 * 1024 * 1024:
            raise ValueError("A reference output was empty or exceeded its 16 MiB cap.")
        total += size
        if total > MAX_BUNDLE_BYTES:
            raise ValueError("Reference outputs exceeded their 32 MiB bundle cap.")
        records.append({"path": str(path), "filename": path.name, "sha256": sha256_file(path), "bytes": size})
    return records


def measure(directory: Path, input_path: str, budget: Budget) -> dict:
    source = input_file(directory, input_path)
    original = _pin(directory, source)
    probe = _probe(directory, source, budget)
    video, duration, fps = _video_info(probe)
    count = _decode_complete(directory, source, duration, fps, video, budget)
    source_record = Source(**original.model_dump(), duration_s=duration, fps=fps,
                           width=video["width"], height=video["height"], decoded_frames=count)
    sweep, selected = _scene_sweep(directory, source, duration, fps, budget)
    bundle = new_bundle(directory, "analysis")
    try:
        boundaries = [0., *selected.scene_times_s, duration]
        shots = []
        motion_frames = 0
        for shot_id, (start, end) in enumerate(zip(boundaries, boundaries[1:]), 1):
            motion, pairs, frames = _motion(directory, source, bundle / "motion.raw", start, end - start, budget)
            motion_frames += frames
            targets = [start + (end - start) * fraction for fraction in (.15, .85)]
            observed = [_frame(directory, source, bundle / f"frame-{shot_id:02}-{column}.png", timestamp,
                               start, end, fps, frames, budget) for column, timestamp in enumerate(targets)]
            shots.append(MeasuredShot(shot_id=shot_id, start_s=start, end_s=end, duration_s=end - start,
                                      median_frame_difference=motion, motion_frame_pairs=pairs,
                                      frame_times_s=targets, sampled_frame_times_s=observed))
        if motion_frames != count:
            raise ValueError("Per-shot native frames did not cover the complete decoded reference film.")
        sheets = _sheets(directory, bundle, shots, budget)
        player = _player(directory, source, bundle, probe, source_record, budget)
        warnings = ["Motion is a frame-difference measurement; subject action and camera motion are not separated."]
        if any(item.scene_times_s != selected.scene_times_s for item in sweep):
            warnings.append("Scene detection is sensitive to threshold; review the selected measured cuts against the reference film.")
        if any(shot.motion_frame_pairs == 0 for shot in shots):
            warnings.append("One-frame shots have unknown motion because no within-shot frame pair exists.")
        if player.kind == "proxy":
            warnings.append("The embedded player is a compressed review preview of the measured source.")
        manifest = Measurements(source=source_record, shots=shots, selected_threshold=selected.threshold,
                                threshold_sweep=sweep, contact_sheets=sheets, player=player, warnings=warnings)
        if _pin(directory, source) != original:
            raise ValueError("The source checksum changed during measurement.")
        analysis_path = bundle / "measurements.json"
        write_json(analysis_path, manifest.model_dump())
        digest = sha256_file(analysis_path)
        files = {item.path: PinnedFile(**item.model_dump(include={"path", "sha256", "bytes"}))
                 for item in [source_record, *sheets, player]}
        write_json(bundle / "integrity.json", Integrity(measurements_sha256=digest, files=list(files.values())).model_dump())
        from providers.reference_shots.report import export_report

        exported = export_report(directory, bundle, manifest, None, "unverified", budget)
        outputs = output_records([analysis_path, bundle / "integrity.json",
                                  *[directory / sheet.path for sheet in sheets],
                                  *([directory / player.path] if player.kind == "proxy" else []),
                                  *[Path(exported[key]) for key in ("shots_path", "csv_path", "report_path")]])
        budget.remaining()
        return {**exported, "ok": True, "status": "measured", "analysis_path": str(analysis_path),
                "measurements_sha256": digest, "shots": [shot.model_dump() for shot in shots],
                "contact_sheets": [{**sheet.model_dump(), "path": str(directory / sheet.path)} for sheet in sheets],
                "source": source_record.model_dump(), "outputs": outputs}
    except BaseException:
        shutil.rmtree(bundle, ignore_errors=True)
        raise


def load_measurements(job_dir: Path, input_path: str, expected_sha256: str = "") -> Measurements:
    """Load a complete pinned bundle. Sheet paths are relative to the validated job directory."""
    directory = Path(job_dir).resolve()
    path = input_file(directory, input_path, max_bytes=MAX_MANIFEST_BYTES)
    if path.name != "measurements.json" or not re.fullmatch(r"reference-analysis-[a-f0-9]{32}", path.parent.name):
        raise ValueError("Reports require the saved measurements.json from an owned analysis bundle.")
    integrity_path = input_file(directory, str(path.parent / "integrity.json"), max_bytes=MAX_MANIFEST_BYTES)
    try:
        integrity = Integrity.model_validate_json(integrity_path.read_bytes())
        digest = sha256_file(path)
        if digest != integrity.measurements_sha256 or (expected_sha256 and digest != expected_sha256):
            raise ValueError("The measurement manifest checksum no longer matches the pinned analysis.")
        manifest = Measurements.model_validate_json(path.read_bytes())
    except ValidationError:
        raise ValueError("The saved measurement manifest or its integrity index is invalid.") from None
    expected = {item.path: item for item in [manifest.source, *manifest.contact_sheets, manifest.player]}
    pinned = {item.path: item for item in integrity.files}
    if len(pinned) != len(integrity.files) or set(expected) != set(pinned):
        raise ValueError("The analysis checksum index does not cover every evidence file exactly once.")
    for relative, item in expected.items():
        if (item.sha256, item.bytes) != (pinned[relative].sha256, pinned[relative].bytes):
            raise ValueError("An evidence checksum no longer matches the pinned analysis.")
        evidence = input_file(directory, relative)
        if relative != manifest.source.path and not evidence.is_relative_to(path.parent):
            raise ValueError("Generated evidence must stay inside its owned analysis bundle.")
        if evidence.stat().st_size != item.bytes or sha256_file(evidence) != item.sha256:
            raise ValueError("An evidence checksum no longer matches the measured source or contact sheets.")
    if manifest.player.bytes > MAX_EMBED_BYTES or any(sheet.bytes > 2 * 1024 * 1024 for sheet in manifest.contact_sheets):
        raise ValueError("Saved review media exceeded its bounded embedding size.")
    validate_input_path(directory, manifest.source.path)
    return manifest
