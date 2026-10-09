"""Prepare one approved shot/silence segment before a paid Act-Two submission."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from providers.remotion import local
from providers.runway.performance import ActTwoRequest


ROOT = Path(__file__).resolve().parents[2]


def _duration(path: Path) -> float:
    try:
        probe = local._probe(path)
        stream = next(s for s in probe["streams"] if s.get("codec_type") == "video")
        duration = float(stream.get("duration") or probe["format"]["duration"])
    except (KeyError, TypeError, ValueError, StopIteration):
        raise ValueError("Act-Two source requires a measurable video duration.") from None
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Act-Two source requires a positive finite video duration.")
    return duration


def split_file(request: ActTwoRequest, source: Path, output: Path) -> Path:
    duration = _duration(source)
    if request.source_duration_seconds is None or abs(duration - request.source_duration_seconds) > 0.1:
        raise ValueError("Declared Act-Two source duration differs from measured video.")
    command = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-protocol_whitelist", "file,pipe",
               "-format_whitelist", local.FORMATS, "-i", str(source),
               "-ss", str(request.performance_start_seconds), "-t", str(request.performance_duration_seconds),
               "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
               "-pix_fmt", "yuv420p", "-r", "24", "-c:a", "aac", "-movflags", "+faststart", str(output)]
    try:
        result = subprocess.run(command, capture_output=True, timeout=240, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("Act-Two source segment preprocessing failed before paid submission.") from None
    if result.returncode or not output.is_file() or not output.stat().st_size:
        raise ValueError("Act-Two preprocessing did not produce a nonempty video.")
    actual = _duration(output)
    if not 3 <= actual <= 30 or abs(actual - request.performance_duration_seconds) > 0.1:
        raise ValueError("Measured Act-Two segment must match the approved 3-30s length.")
    return output


def prepare(request: ActTwoRequest) -> str:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise ValueError("Act-Two chunking requires ffmpeg and ffprobe before paid submission.")
    root = Path(os.getenv("RENDERHAUS_MEDIA_DIR", str(ROOT / ".renderhaus/media"))).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="act-two-", dir=root) as scratch:
        directory = Path(scratch)
        source = local._source(request.performance_uri, directory=directory, index=0,
                               media_roots=(ROOT / ".renderhaus", root), source_root=ROOT)
        clip = split_file(request, source, directory / "performance.mp4")
        from providers.runway.inputs import publish_file

        return publish_file(clip, "performance.mp4", "video/mp4")
