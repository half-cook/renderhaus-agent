from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import boto3

from providers.remotion import local
from providers.sync import contracts


ROOT = Path(__file__).resolve().parents[2]
INPUT_URL_TTL_SECONDS = 6 * 60 * 60


@dataclass(frozen=True)
class ChunkSpan:
    index: int
    start_seconds: float
    end_seconds: float

    @property
    def duration(self) -> float:
        return self.end_seconds - self.start_seconds

    def preview(self) -> dict[str, Any]:
        return {**asdict(self), "duration_seconds": self.duration}


@dataclass(frozen=True)
class PreparedChunk:
    index: int
    start_seconds: float
    end_seconds: float
    video_url: str
    audio_url: str


def plan_for(request: contracts.SyncRequest) -> tuple[ChunkSpan, ...]:
    cap = contracts.max_chunk_seconds()
    duration = request.output_duration
    boundaries = request.chunk_boundaries_seconds or []
    long_input = max(request.source_duration_seconds, request.audio_duration_seconds) > cap
    if long_input and (
        request.sync_mode != "cut_off"
        or not math.isclose(request.source_duration_seconds, request.audio_duration_seconds, abs_tol=1e-6, rel_tol=0)
    ):
        raise ValueError("A long input requires equal-length video/audio with sync_mode=cut_off for safe paired chunking.")
    if not boundaries and duration > cap:
        raise ValueError(
            "chunk_boundaries_seconds requires silence or shot timestamps when output exceeds "
            "SYNC_MAX_CHUNK_SECONDS. No automatic cuts or paid submission were made."
        )
    previous = 0.0
    for boundary in boundaries:
        if not math.isfinite(boundary) or not previous < boundary < duration:
            raise ValueError("chunk_boundaries_seconds must be sorted, unique internal timestamps.")
        previous = boundary
    points = [0.0, *boundaries, duration]
    spans = tuple(ChunkSpan(index, start, end) for index, (start, end) in enumerate(zip(points, points[1:])))
    if any(span.duration > cap for span in spans):
        raise ValueError("Every supplied chunk span must fit SYNC_MAX_CHUNK_SECONDS.")
    if len(spans) > 1 and (
        request.sync_mode != "cut_off"
        or not math.isclose(request.source_duration_seconds, request.audio_duration_seconds, abs_tol=1e-6, rel_tol=0)
    ):
        raise ValueError("Chunking requires equal-length video/audio and sync_mode=cut_off.")
    return spans


def media_root() -> Path:
    root = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser()
    return (root if root.is_absolute() else ROOT / root).resolve()


def _prerequisites(request: contracts.SyncRequest) -> str:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise ValueError("Sync chunking requires local ffmpeg and ffprobe before any paid submission.")
    bucket = os.getenv("AWS_S3_BUCKET", "").strip()
    if not bucket:
        raise ValueError("Sync chunking requires AWS_S3_BUCKET before any paid submission.")
    hosts = set(os.getenv("REMOTION_LOCAL_MEDIA_HOSTS", "").split(",")) - {""}
    for source in (request.video_url, request.audio_url):
        parsed = urlsplit(source)
        if (
            parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username
            or parsed.password or parsed.port not in {None, 443} or parsed.fragment
        ):
            raise ValueError(
                "Sync chunking sources require HTTPS on an exact REMOTION_LOCAL_MEDIA_HOSTS host. "
                "Resolve authorized Studio asset handles before chunking."
            )
    try:
        from server.projects import merge_video_paths
    except ImportError:
        raise ValueError("Sync chunking requires the server.projects concat/merge dependency before any paid submission.") from None
    if not callable(merge_video_paths):
        raise ValueError("Sync chunking requires a callable video concat/merge dependency.")
    return bucket


def _measurement(path: Path, kind: str) -> tuple[float, float | None]:
    try:
        probe = local._probe(path)
        stream = next(stream for stream in probe["streams"] if stream.get("codec_type") == kind)
        duration = float(stream.get("duration") or probe["format"]["duration"])
        fps = float(Fraction(stream.get("avg_frame_rate") or stream["r_frame_rate"])) if kind == "video" else None
    except (KeyError, StopIteration, TypeError, ValueError, ZeroDivisionError):
        raise ValueError("Sync inputs require a measured video frame rate and video/audio durations.") from None
    if not math.isfinite(duration) or duration <= 0 or (fps is not None and (not math.isfinite(fps) or fps <= 0)):
        raise ValueError("Sync inputs require positive finite measured video/audio properties.")
    return duration, fps


def _check_measurements(request: contracts.SyncRequest, video: Path, audio: Path, *, duration: float | None = None) -> None:
    video_seconds, fps = _measurement(video, "video")
    audio_seconds, _ = _measurement(audio, "audio")
    video_expected = request.source_duration_seconds if duration is None else duration
    audio_expected = request.audio_duration_seconds if duration is None else duration
    tolerance = max(0.05, 1 / request.source_fps)
    if (
        abs(video_seconds - video_expected) > tolerance
        or abs(audio_seconds - audio_expected) > tolerance
        or fps is None or abs(fps - request.source_fps) > max(0.05, request.source_fps * 0.005)
    ):
        raise ValueError("Declared Sync durations/fps do not match measured source or clipped media.")
    if duration is not None and max(video_seconds, audio_seconds) > contracts.max_chunk_seconds():
        raise ValueError("Measured clipped media exceeds SYNC_MAX_CHUNK_SECONDS.")
    if request.source_width is not None:
        probe = local._probe(video)
        stream = next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"), {})
        if (stream.get("width"), stream.get("height")) != (request.source_width, request.source_height):
            raise ValueError("Declared Sync dimensions do not match measured source or clipped media.")


def _split_pair(request: contracts.SyncRequest, span: ChunkSpan, video: Path, audio: Path, directory: Path) -> tuple[Path, Path]:
    video_clip = directory / f"chunk-{span.index:03d}.mp4"
    audio_clip = directory / f"chunk-{span.index:03d}.wav"
    common = [
        "ffmpeg", "-nostdin", "-y", "-v", "error", "-protocol_whitelist", "file,pipe",
        "-format_whitelist", local.FORMATS,
    ]
    trim = ["-ss", f"{span.start_seconds:g}", "-t", f"{span.duration:g}"]
    commands = [
        common + ["-i", str(video)] + trim + [
            "-map", "0:v:0", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", f"{request.source_fps:g}",
            "-movflags", "+faststart", str(video_clip),
        ],
        common + ["-i", str(audio)] + trim + [
            "-map", "0:a:0", "-vn", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(audio_clip),
        ],
    ]
    for command, output in zip(commands, (video_clip, audio_clip)):
        try:
            result = subprocess.run(command, capture_output=True, timeout=max(120, span.duration * 8), check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError("Sync chunk preprocessing could not finish a paired clip.") from None
        if result.returncode or not output.is_file() or not output.stat().st_size:
            raise ValueError("Sync chunk preprocessing did not produce nonempty paired media.")
    _check_measurements(request, video_clip, audio_clip, duration=span.duration)
    return video_clip, audio_clip


def prepare(request: contracts.SyncRequest, spans: tuple[ChunkSpan, ...]) -> list[PreparedChunk]:
    """Validate, split every paired clip, then upload every input before submitting work."""
    bucket = _prerequisites(request)
    root = media_root()
    root.mkdir(parents=True, exist_ok=True)
    roots = (ROOT / ".renderhaus", root)
    batch_id = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="sync-chunks-", dir=root) as scratch:
        directory = Path(scratch)
        video = local._source(request.video_url, directory=directory, index=0, media_roots=roots, source_root=ROOT)
        audio = local._source(request.audio_url, directory=directory, index=1, media_roots=roots, source_root=ROOT)
        _check_measurements(request, video, audio)
        clipped = [_split_pair(request, span, video, audio, directory) for span in spans]
        prepared = []
        try:
            client = boto3.client("s3", region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1")
            for span, (video_clip, audio_clip) in zip(spans, clipped):
                urls = []
                for path, content_type in ((video_clip, "video/mp4"), (audio_clip, "audio/wav")):
                    key = f"renderhaus-sync-inputs/{batch_id}/{path.name}"
                    client.upload_file(Filename=str(path), Bucket=bucket, Key=key, ExtraArgs={"ContentType": content_type})
                    url = client.generate_presigned_url(
                        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=INPUT_URL_TTL_SECONDS,
                    )
                    contracts.validate_media_reference(url, allow_asset=False)
                    urls.append(url)
                prepared.append(PreparedChunk(span.index, span.start_seconds, span.end_seconds, urls[0], urls[1]))
        except Exception:
            raise ValueError("Sync chunk input upload failed before any paid submission.") from None
    return prepared


def merge(paths: list[Path], *, output_path: Path) -> None:
    from server.projects import merge_video_paths

    temporary = output_path.with_name(f"{output_path.stem}.{uuid.uuid4().hex}.mp4")
    try:
        merge_video_paths(paths, output_path=temporary)
        if not temporary.is_file() or not temporary.stat().st_size:
            raise RuntimeError("Sync concatenation produced an empty final video.")
        temporary.replace(output_path)
    except RuntimeError as exc:
        if str(exc) == "Sync concatenation produced an empty final video.":
            raise
        raise RuntimeError("Sync child videos could not be concatenated.") from None
    finally:
        temporary.unlink(missing_ok=True)
