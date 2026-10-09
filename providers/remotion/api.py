"""Remotion Lambda provider API.

Gateway tools start a render and poll once. Blocking wait stays off Lambda.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import mimetypes
import os
import re
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal, TypedDict
from urllib.parse import unquote, urlparse

import boto3
from botocore.exceptions import ClientError
from remotion_lambda import Privacy, RemotionClient, RenderMediaParams, ValidStillImageFormats
from remotion_lambda.exception import RemotionException

from providers.contracts import validate_remotion_timeline_arguments
from providers.remotion.mp4_probe import UnsupportedContainer
from providers.remotion.transcript import build_conversational_edit


ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT_PATH = ROOT / ".renderhaus" / "remotion" / "deployment.json"
OUTPUT_DIR = ROOT / ".renderhaus" / "media" / "remotion"
COMPOSITION_ID = "RenderhausTimeline"
ASPECT_SIZES = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350), "2.39:1": (1920, 804)}
DEFAULT_FRAMES_PER_LAMBDA = 100
OutputResolution = Literal["source", "720p", "1080p", "1440p", "2160p"]
_RESOLUTION_TIERS = {"720p": 720, "1080p": 1080, "1440p": 1440, "2160p": 2160}
_UNKNOWN_RESOLUTION_WARNING = "Source resolution metadata is unavailable for this render; upscaling is unknown."
_UNKNOWN_DIMENSIONS_WARNING = "Video source dimensions could not be measured; the canvas may resize the source."
_UPSCALE_WARNING_PATTERN = (
    r"Video upscaled from [1-9]\d*x[1-9]\d* to [1-9]\d*x[1-9]\d* "
    r"with no added detail\. Use the Topaz upscale skill before assembly for added detail\."
)


@dataclass(frozen=True, slots=True)
class _VisualMetadata:
    fps: float | None
    bitrate: int | None
    size: tuple[int, int] | None
    container_bitrate: int | None


class _ResolutionReport(TypedDict):
    width: int | None
    height: int | None
    source_resolution: str | None
    upscaled: bool
    warnings: list[str]


def choose_canvas(aspect_ratio: str, source_sizes: list[tuple[int, int]],
                  output_resolution: OutputResolution = "source") -> tuple[int, int]:
    if aspect_ratio not in ASPECT_SIZES:
        raise ValueError(f"aspect_ratio must be one of {', '.join(ASPECT_SIZES)}.")
    if output_resolution not in {"source", *_RESOLUTION_TIERS}:
        raise ValueError("output_resolution must be source, 720p, 1080p, 1440p, or 2160p.")
    base = ASPECT_SIZES[aspect_ratio]
    if output_resolution == "source":
        short_edge = max((min(size) for size in source_sizes), default=min(base))
        scale = min(Fraction(1), Fraction(short_edge, min(base)))
    else:
        scale = Fraction(_RESOLUTION_TIERS[output_resolution], 1080)
    return tuple(max(2, dimension * scale.numerator // scale.denominator // 2 * 2)
                 for dimension in base)


def _media_dimensions(video: dict[str, Any]) -> tuple[int, int] | None:
    width, height = video.get("width"), video.get("height")
    if all(isinstance(value, int) and not isinstance(value, bool) and value > 0
           for value in (width, height)):
        rotation = next((entry["rotation"] for entry in video.get("side_data_list", [])
                         if isinstance(entry, dict) and "rotation" in entry),
                        (video.get("tags") or {}).get("rotate", 0))
        try:
            rotation = float(rotation)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(rotation) or not math.isclose(rotation / 90, round(rotation / 90), abs_tol=1e-6):
            return None
        return (height, width) if round(rotation / 90) % 2 else (width, height)
    return None


def _resolution_report(value: Any) -> _ResolutionReport:
    value = value if isinstance(value, dict) else {}
    size = _media_dimensions(value)
    source = value.get("source_resolution")
    if not isinstance(source, str) or not re.fullmatch(r"[1-9]\d*x[1-9]\d*", source):
        source = None
    upscaled = value.get("upscaled")
    warnings = value.get("warnings")
    warnings = [warning for warning in warnings if isinstance(warning, str)
                and (warning in {_UNKNOWN_RESOLUTION_WARNING, _UNKNOWN_DIMENSIONS_WARNING}
                     or re.fullmatch(_UPSCALE_WARNING_PATTERN, warning))] if isinstance(warnings, list) else []
    if not isinstance(upscaled, bool):
        upscaled = False
        if _UNKNOWN_RESOLUTION_WARNING not in warnings:
            warnings.append(_UNKNOWN_RESOLUTION_WARNING)
    return {"width": size[0] if size else None, "height": size[1] if size else None,
            "source_resolution": source, "upscaled": upscaled, "warnings": warnings}


def _resolution_key(render_id: str) -> str:
    return f"renderhaus-metadata/{render_id}/resolution.json"


@dataclass(frozen=True, slots=True)
class RemotionSettings:
    region: str
    function_name: str
    serve_url: str
    bucket_name: str


def dry_run() -> bool:
    return os.getenv("REMOTION_DRY_RUN", "true").lower() != "false"


def render_backend() -> str:
    backend = os.getenv("REMOTION_RENDER_BACKEND", "lambda").strip().lower()
    if backend not in {"lambda", "local"}:
        raise ValueError("REMOTION_RENDER_BACKEND must be lambda or local.")
    return backend


def _start_render(input_props: dict[str, Any], *, output_filename: str) -> dict[str, Any]:
    if render_backend() == "local":
        from providers.remotion.local import start_render

        return start_render(input_props, output_filename=output_filename,
                            media_roots=_allowed_local_roots(), source_root=ROOT)
    return _start_lambda_render(input_props, output_filename=output_filename)


def _on_lambda() -> bool:
    return bool(os.getenv("AWS_LAMBDA_FUNCTION_NAME"))


def load_remotion_settings() -> RemotionSettings:
    stored: dict[str, Any] = {}
    if DEPLOYMENT_PATH.is_file():
        value = json.loads(DEPLOYMENT_PATH.read_text())
        if isinstance(value, dict):
            stored = value

    def get(env_name: str, stored_name: str) -> str:
        return str(os.getenv(env_name) or stored.get(stored_name) or "").strip()

    settings = RemotionSettings(
        region=get("REMOTION_APP_REGION", "region"),
        function_name=get("REMOTION_APP_FUNCTION_NAME", "functionName"),
        serve_url=get("REMOTION_APP_SERVE_URL", "serveUrl"),
        bucket_name=get("REMOTION_APP_BUCKET_NAME", "bucketName"),
    )
    missing = [
        name
        for name, value in (
            ("REMOTION_APP_REGION", settings.region),
            ("REMOTION_APP_FUNCTION_NAME", settings.function_name),
            ("REMOTION_APP_SERVE_URL", settings.serve_url),
            ("REMOTION_APP_BUCKET_NAME", settings.bucket_name),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Remotion Lambda is not configured ({', '.join(missing)}).")
    return settings


def _safe_output_name(value: str) -> str:
    stem = Path(value).name.removesuffix(".mp4")
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-._") or "renderhaus-video"
    return f"{stem[:90]}.mp4"


def _allowed_local_roots() -> tuple[Path, ...]:
    media = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser()
    if not media.is_absolute():
        media = (ROOT / media).resolve()
    else:
        media = media.resolve()
    return (ROOT / ".renderhaus", media)


def _is_allowed_local(path: Path) -> bool:
    resolved = path.resolve()
    return any(root == resolved or root in resolved.parents for root in _allowed_local_roots())


def _uploaded_source_url(source: str, *, settings: RemotionSettings, s3) -> str:
    if source.startswith(("https://", "http://", "data:")):
        return source
    path = Path(source).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not _is_allowed_local(path) or not path.is_file() or path.stat().st_size <= 0:
        raise ValueError("Remotion sources must be existing media inside the Renderhaus workspace.")
    digest_builder = hashlib.sha256()
    with path.open("rb") as source_file:
        for chunk in iter(lambda: source_file.read(1024 * 1024), b""):
            digest_builder.update(chunk)
    digest = digest_builder.hexdigest()[:20]
    key = f"renderhaus-inputs/{digest}-{path.name}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    try:
        s3.head_object(Bucket=settings.bucket_name, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
            raise
        s3.upload_file(
            str(path),
            settings.bucket_name,
            key,
            ExtraArgs={"ContentType": content_type},
        )
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.bucket_name, "Key": key},
        ExpiresIn=6 * 60 * 60,
    )


def _prepare_input_props(
    input_props: dict[str, Any], *, settings: RemotionSettings, session: boto3.Session
) -> dict[str, Any]:
    prepared = copy.deepcopy(input_props)
    s3 = session.client("s3")
    document = prepared.get("document")
    if not isinstance(document, dict) or not isinstance(document.get("assets"), list):
        raise ValueError("Remotion input props must include a timeline document with assets.")
    for asset in document["assets"]:
        if not isinstance(asset, dict) or not isinstance(asset.get("url"), str):
            raise ValueError("Every Remotion timeline asset must have a source URL or local path.")
        asset["url"] = _uploaded_source_url(asset["url"], settings=settings, s3=s3)
    return prepared


def _visual_metadata(clip: dict[str, Any], *, measure_remote: bool = False,
                     measure_local: bool = True) -> _VisualMetadata:
    source_fps = clip.get("source_fps")
    source_bitrate = clip.get("source_bitrate")
    source = str(clip.get("url") or clip.get("output_path") or "")
    probe = None
    size = None
    container_bitrate = None
    if urlparse(source).scheme and measure_remote:
        from providers.remotion.local import _probe, _source

        _, _, bucket_hosts = _nle_storage()
        hosts = set(bucket_hosts)
        source_host = urlparse(source).hostname or ""
        if source_host == "fal.media" or source_host.endswith(".fal.media"):
            hosts.add(source_host)
        hosts.update(set(os.getenv("REMOTION_LOCAL_MEDIA_HOSTS", "").split(",")) - {""})
        if source_host in hosts or source_fps is None or source_bitrate is None:
            with tempfile.TemporaryDirectory(prefix="renderhaus-probe-") as temporary:
                path = _source(source, directory=Path(temporary), index=1, media_roots=_allowed_local_roots(),
                               source_root=ROOT, allowed_hosts=hosts, deadline_seconds=30)
                try:
                    probe = _probe(path)
                except UnsupportedContainer:
                    pass
    if not urlparse(source).scheme and measure_local:
        path = Path(source).expanduser()
        path = (path if path.is_absolute() else ROOT / path).resolve()
        if _is_allowed_local(path) and path.is_file():
            from providers.remotion.local import _probe

            try:
                probe = _probe(path)
            except UnsupportedContainer:
                pass
    if probe is not None:
        video = next((s for s in probe["streams"] if s.get("codec_type") == "video"), None)
        if video is None:
            raise ValueError("A video visual must contain a video stream.")
        size = _media_dimensions(video)
        rate = video.get("avg_frame_rate") or video.get("r_frame_rate")
        if rate and rate != "0/0":
            source_fps = float(Fraction(rate))
        source_bitrate = video.get("bit_rate") or probe.get("format", {}).get("bit_rate") or source_bitrate
        container_bitrate = int(probe.get("format", {}).get("bit_rate") or 0) or None
    if source_fps is not None:
        source_fps = float(source_fps)
        if not math.isfinite(source_fps) or not 0 < source_fps <= 240:
            raise ValueError("Measured source_fps must be greater than 0 and at most 240.")
    if source_bitrate is not None:
        source_bitrate = int(source_bitrate)
        if source_bitrate <= 0:
            raise ValueError("Measured source_bitrate must be a positive bitrate in bits per second.")
    return _VisualMetadata(source_fps, source_bitrate, size, container_bitrate)


def _overlay_box(value: Any, width: int, height: int) -> dict[str, float]:
    from providers.remotion.text import box_geometry

    return box_geometry(value, width, height)


def _refuse_lambda_reframe(items: list[dict[str, Any]]) -> None:
    if any({"crop_box", "cropBox", "pad_box", "padBox", "reframe_size", "reframeSize", "allow_upscale", "allowUpscale"}.intersection(item)
           or item.get("fit") == "pad_blur" for item in items):
        raise ValueError("Lambda reframing is not deployed; use the local/worker backend for crop_box and pad_blur.")


def _reframe_canvas(videos: list[dict[str, Any]], metadata: list[_VisualMetadata],
                    width: int, height: int, aspect: str) -> tuple[int, int]:
    primary = [clip for clip in videos if clip.get("track", 0) == 0]
    requested = [clip["reframe_size"] for clip in primary if "reframe_size" in clip]
    if requested:
        if len(requested) != len(primary) or any(size != requested[0] for size in requested):
            raise ValueError("All primary clips must use the same reframe_size canvas.")
        width, height = requested[0]["width"], requested[0]["height"]
        base_width, base_height = ASPECT_SIZES[aspect]
        if abs(width - height * base_width / base_height) > 2 + 2 * base_width / base_height:
            raise ValueError("reframe_size must match aspect_ratio after even-pixel rounding.")
    crop_scales = []
    for clip, measured in zip(videos, metadata, strict=True):
        crop = clip.get("crop_box")
        if crop and measured.size and (crop["x"] + crop["width"] > measured.size[0]
                                     or crop["y"] + crop["height"] > measured.size[1]):
            raise ValueError("crop_box must fit inside the measured display-oriented source.")
        if not crop and clip.get("fit") != "pad_blur":
            continue
        available = (crop["width"], crop["height"]) if crop else measured.size
        if available is None or clip.get("allow_upscale", False):
            continue
        pad = clip.get("pad_box")
        target = (pad["width"], pad["height"]) if pad else (width, height)
        ratios = (target[0] / available[0], target[1] / available[1])
        scale = max(ratios) if crop or pad else min(ratios)
        if scale > 1 + 1e-9:
            if requested:
                raise ValueError("reframe_size needs allow_upscale=true to exceed available source pixels.")
            crop_scales.append(1 / scale)
    if crop_scales:
        scale = min(crop_scales)
        width, height = (max(2, int(dimension * scale) // 2 * 2) for dimension in (width, height))
    return width, height


def build_timeline_props(
    title: str,
    visuals: list[dict[str, Any]],
    audio_tracks: list[dict[str, Any]] | None = None,
    text_overlays: list[dict[str, Any]] | None = None,
    aspect_ratio: str = "9:16",
    fps: float | None = None,
    subtitles: list[dict[str, Any]] | None = None,
    video_bitrate: int | None = None,
    output_resolution: OutputResolution = "source",
    *, measure_remote: bool = False, measure_local: bool = True,
) -> dict[str, Any]:
    validate_remotion_timeline_arguments({
        "visuals": visuals, "audio_tracks": audio_tracks,
        "text_overlays": text_overlays, "subtitles": subtitles,
    })
    choose_canvas(aspect_ratio, [], output_resolution)
    if not visuals:
        raise ValueError("At least one visual clip is required for a Remotion render.")
    videos = sorted((clip for clip in visuals if clip.get("kind") == "video"),
                    key=lambda clip: (clip.get("track", 0), clip.get("start_seconds", 0)))
    metadata = [_visual_metadata(clip, measure_remote=measure_remote, measure_local=measure_local)
                for clip in videos]
    if fps is None:
        if metadata and metadata[0].fps is None:
            raise ValueError("Download the primary video for ffprobe or supply measured source_fps; "
                             "set fps only when the user requests an explicit timeline rate.")
        fps = metadata[0].fps if metadata else 30
    if isinstance(fps, bool) or not math.isfinite(fps) or not 0 < fps <= 240:
        raise ValueError("Timeline fps must be greater than 0 and at most 240.")
    if video_bitrate is not None and (isinstance(video_bitrate, bool)
                                     or not isinstance(video_bitrate, int) or video_bitrate <= 0):
        raise ValueError("video_bitrate must be a positive integer in bits per second.")
    sizes = [measured.size for measured in metadata if measured.size is not None]
    width, height = choose_canvas(aspect_ratio, sizes, output_resolution)
    width, height = _reframe_canvas(videos, metadata, width, height, aspect_ratio)
    source_floor = max((measured.bitrate for measured in metadata if measured.bitrate is not None), default=0)
    base_width, base_height = ASPECT_SIZES[aspect_ratio]
    automatic_bitrate = math.ceil(source_floor * 1.25)
    if width * height < base_width * base_height:
        source_cap = max((max(measured.bitrate or 0, measured.container_bitrate or 0)
                          for measured in metadata), default=0)
        automatic_bitrate = min(automatic_bitrate, source_cap)
    video_bitrate = max(video_bitrate or 0, automatic_bitrate) or None
    largest_source = max(sizes, key=lambda size: (min(size), size[0] * size[1]), default=None)
    resolution: _ResolutionReport = {
        "width": width, "height": height,
        "source_resolution": f"{largest_source[0]}x{largest_source[1]}" if largest_source else None,
        "upscaled": False, "warnings": [],
    }
    for clip, measured in zip(videos, metadata, strict=True):
        if measured.size is None:
            warning = _UNKNOWN_DIMENSIONS_WARNING
        else:
            source_width, source_height = measured.size
            crop = clip.get("crop_box")
            available_width, available_height = (crop["width"], crop["height"]) if crop else measured.size
            pad = clip.get("pad_box")
            target = (pad["width"], pad["height"]) if pad else (width, height)
            ratios = (target[0] / available_width, target[1] / available_height)
            fit_scale = min(ratios) if clip.get("fit") in {"contain", "pad_blur"} and not pad else max(ratios)
            clip_scale = max(0.1, min(float(clip.get("scale", 1)), 4.0))
            motion_scale = 1.08 if clip.get("motion") in {"zoom_in", "zoom_out", "pan_left", "pan_right"} else 1
            if fit_scale * clip_scale * motion_scale <= 1 + 1e-9:
                continue
            resolution["upscaled"] = True
            warning = (f"Video upscaled from {source_width}x{source_height} to {width}x{height} "
                       "with no added detail. Use the Topaz upscale skill before assembly for added detail.")
        if warning not in resolution["warnings"]:
            resolution["warnings"].append(warning)
    assets: list[dict[str, Any]] = []
    visual_tracks: dict[int, list[dict[str, Any]]] = {}
    track_ends: dict[int, float] = {}
    for index, clip in enumerate(visuals):
        kind = str(clip.get("kind") or "image")
        if kind not in {"image", "video"}:
            raise ValueError("Each visual clip kind must be image or video.")
        url = str(clip.get("url") or clip.get("output_path") or "").strip()
        if not url:
            raise ValueError("Each visual clip needs a url or output_path.")
        duration = float(clip.get("duration_seconds") or 0)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Each visual clip needs duration_seconds greater than 0.")
        track = max(0, min(int(clip.get("track") or 0), 8))
        start = (
            float(clip["start_seconds"])
            if clip.get("start_seconds") is not None
            else track_ends.get(track, 0.0)
        )
        if start < 0:
            raise ValueError("Each visual clip start_seconds must be at least 0.")
        source_in = float(clip.get("source_in_seconds") or 0)
        transition = str(clip.get("transition") or "cut")
        if transition not in {"cut", "fade", "dip_to_black"}:
            raise ValueError("Visual transition must be cut, fade, or dip_to_black.")
        fit = str(clip.get("fit") or "cover")
        if fit not in {"cover", "contain", "pad_blur"}:
            raise ValueError("Visual fit must be cover, contain or pad_blur.")
        motion = str(clip.get("motion") or "none")
        if motion not in {"none", "zoom_in", "zoom_out", "pan_left", "pan_right"}:
            raise ValueError(
                "Visual motion must be none, zoom_in, zoom_out, pan_left, or pan_right."
            )
        opacity = max(0.0, min(float(clip.get("opacity", 1)), 1.0))
        scale = max(0.1, min(float(clip.get("scale", 1)), 4.0))
        playback_rate = max(0.25, min(float(clip.get("playback_rate", 1)), 4.0))
        default_fade = min(0.35, duration / 3) if transition != "cut" else 0.0
        asset_id = f"visual-{index + 1}"
        assets.append(
            {
                "id": asset_id,
                "name": f"{kind.title()} {index + 1}",
                "kind": kind,
                "url": url,
                "durationSec": duration,
            }
        )
        visual_tracks.setdefault(track, []).append(
            {
                "id": f"visual-clip-{index + 1}",
                "type": "clip",
                "assetId": asset_id,
                "start": start,
                "duration": duration,
                "sourceIn": source_in,
                "sourceOut": source_in + duration * playback_rate,
                "fit": fit,
                "positionX": max(0.0, min(float(clip.get("position_x", 0.5)), 1.0)),
                "positionY": max(0.0, min(float(clip.get("position_y", 0.5)), 1.0)),
                "scale": scale,
                "opacity": opacity,
                "rotation": max(-360.0, min(float(clip.get("rotation_degrees", 0)), 360.0)),
                "playbackRate": playback_rate,
                "volume": max(0.0, min(float(clip.get("volume", 1)), 1.0)),
                "fadeIn": max(0.0, min(float(clip.get("fade_in_seconds", default_fade)), duration)),
                "fadeOut": max(
                    0.0, min(float(clip.get("fade_out_seconds", default_fade)), duration)
                ),
                "motion": motion,
                "transition": transition,
                "grade": clip.get("grade", "none"),
                **({"box": _overlay_box(clip["box"], width, height)} if "box" in clip else {}),
                **({"cropBox": copy.deepcopy(clip["crop_box"])} if "crop_box" in clip else {}),
                **({"padBox": _overlay_box(clip["pad_box"], width, height)} if "pad_box" in clip else {}),
                **({"reframeSize": copy.deepcopy(clip["reframe_size"])} if "reframe_size" in clip else {}),
                **({"allowUpscale": clip["allow_upscale"]} if "allow_upscale" in clip else {}),
                **({"audioFadeIn": float(clip["audio_fade_in_seconds"])}
                   if "audio_fade_in_seconds" in clip else {}),
                **({"audioFadeOut": float(clip["audio_fade_out_seconds"])}
                   if "audio_fade_out_seconds" in clip else {}),
            }
        )
        track_ends[track] = max(track_ends.get(track, 0.0), start + duration)
    tracks: list[dict[str, Any]] = [
        {
            "id": f"video-{track + 1}",
            "kind": "video" if track == 0 else "overlay",
            "name": "Main video" if track == 0 else f"B-roll {track}",
            "items": items,
        }
        for track, items in sorted(visual_tracks.items())
    ]
    visual_duration = max(track_ends.values())
    for index, clip in enumerate(audio_tracks or []):
        url = str(clip.get("url") or clip.get("output_path") or "").strip()
        if not url:
            raise ValueError("Each audio clip needs a url or output_path.")
        duration = float(clip.get("duration_seconds") or 0)
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Each audio clip needs duration_seconds greater than 0.")
        start = float(clip.get("start_seconds") or 0)
        if start >= visual_duration:
            raise ValueError("Audio must start before the end of the visual sequence.")
        # Source duration must not extend the video into black frames.
        duration = min(duration, visual_duration - start)
        source_in = float(clip.get("source_in_seconds") or 0)
        volume = float(clip.get("volume") if clip.get("volume") is not None else 1)
        asset_id = f"audio-{index + 1}"
        assets.append(
            {
                "id": asset_id,
                "name": f"Audio {index + 1}",
                "kind": "audio",
                "url": url,
                "durationSec": duration,
            }
        )
        tracks.append(
            {
                "id": f"audio-track-{index + 1}",
                "kind": "audio",
                "name": f"Audio {index + 1}",
                "items": [
                    {
                        "id": f"audio-clip-{index + 1}",
                        "type": "clip",
                        "assetId": asset_id,
                        "start": start,
                        "duration": duration,
                        "sourceIn": source_in,
                        "sourceOut": source_in + duration,
                        "volume": volume,
                        "fadeIn": max(
                            0.0,
                            min(float(clip.get("fade_in_seconds") or 0), duration),
                        ),
                        "fadeOut": max(
                            0.0,
                            min(float(clip.get("fade_out_seconds", 0.75)), duration),
                        ),
                    }
                ],
            }
        )
    for track_id, name, item_prefix, items in (("titles-1", "Titles", "text", text_overlays),
                                              ("subtitles-1", "Subtitles", "subtitle", subtitles)):
        text_items: list[dict[str, Any]] = []
        for index, overlay in enumerate(items or []):
            duration = float(overlay["duration_seconds"])
            default_fade = 0.2 if item_prefix == "text" else 0
            fade_in = float(overlay.get("fade_in_seconds", default_fade))
            fade_out = float(overlay.get("fade_out_seconds", default_fade))
            fitted_contract = any(key in overlay for key in ("box", "min_font_size", "max_font_size", "font_family"))
            if item_prefix == "text" and not fitted_contract:
                fade_in = fade_in or 0.2
                fade_out = fade_out or 0.2
            text_items.append({
                "id": f"{item_prefix}-{index + 1}", "type": "text",
                "text": overlay["text"],
                "start": float(overlay["start_seconds"]), "duration": duration,
                "position": overlay.get("position", "center"),
                "fontSize": int(overlay.get("font_size", 64)),
                "color": str(overlay.get("color") or "#ffffff")[:32],
                "backgroundColor": str(overlay.get("background_color") or "transparent")[:32],
                "fontWeight": int(overlay.get("font_weight", 700)),
                "fadeIn": min(fade_in, duration),
                "fadeOut": min(fade_out, duration),
                **({"opacity": overlay["opacity"]} if "opacity" in overlay else {}),
            })
            if fitted_contract:
                from providers.remotion.text import fit_text

                fitted = dict(text_items[-1])
                for public, normalized in (("box", "box"), ("min_font_size", "minFontSize"),
                                           ("max_font_size", "maxFontSize"), ("font_family", "fontFamily")):
                    if public in overlay:
                        fitted[normalized] = overlay[public]
                text_items[-1].update(fit_text(fitted, width, height))
        if text_items:
            tracks.append({"id": track_id, "kind": "caption", "name": name, "items": text_items})
    return {
        "document": {
            "id": "agent-render",
            "name": (title or "Renderhaus video")[:160],
            "assets": assets,
            "tracks": tracks,
        },
        "renderConfig": {
            "fps": fps,
            "width": width,
            "height": height,
            "durationInFrames": max(1, math.ceil(visual_duration * fps - 1e-9)),
            "videoBitrate": video_bitrate,
            "crf": None if video_bitrate else 18,
            "resolution": resolution,
        },
    }


def _start_lambda_render(
    input_props: dict[str, Any],
    *,
    output_filename: str,
) -> dict[str, Any]:
    _refuse_lambda_reframe([item for track in input_props.get("document", {}).get("tracks", [])
                           for item in track.get("items", [])])
    new_fields = {"box", "fontFamily", "textFit", "minFontSize", "maxFontSize"}
    needs_v2 = any(new_fields.intersection(item)
                   for track in input_props.get("document", {}).get("tracks", [])
                   for item in track.get("items", []))
    if needs_v2 and os.getenv("REMOTION_OVERLAY_CONTRACT_VERSION", "1") != "2":
        raise ValueError("Lambda requires overlay contract version 2 with matching font assets; "
                         "use REMOTION_RENDER_BACKEND=local until that composition is deployed.")
    settings = load_remotion_settings()
    session = boto3.Session(region_name=settings.region)
    prepared = _prepare_input_props(input_props, settings=settings, session=session)
    client = RemotionClient(
        region=settings.region,
        serve_url=settings.serve_url,
        function_name=settings.function_name,
        session=session,
    )
    safe_name = _safe_output_name(output_filename)
    output_key = f"renderhaus-outputs/{uuid.uuid4().hex}/{safe_name}"
    response = client.render_media_on_lambda(
        RenderMediaParams(
            composition=COMPOSITION_ID,
            input_props=prepared,
            codec="h264",
            image_format=ValidStillImageFormats.JPEG,
            privacy=Privacy.PRIVATE,
            out_name=output_key,
            frames_per_lambda=max(
                20,
                int(os.getenv("REMOTION_FRAMES_PER_LAMBDA", str(DEFAULT_FRAMES_PER_LAMBDA))),
            ),
            max_retries=1,
            x264_preset="veryfast",
            force_fps=prepared["renderConfig"].get("fps"),
            video_bitrate=prepared["renderConfig"].get("videoBitrate"),
            crf=(None if prepared["renderConfig"].get("videoBitrate")
                 else prepared["renderConfig"].get("crf", 18)),
            jpeg_quality=100,
        )
    )
    if response is None:
        raise RuntimeError("Remotion Lambda did not return a render identifier.")
    resolution = _resolution_report(prepared["renderConfig"].get("resolution", prepared["renderConfig"]))
    try:
        session.client("s3").put_object(
            Bucket=response.bucket_name, Key=_resolution_key(response.render_id),
            Body=json.dumps(resolution).encode(), ContentType="application/json",
        )
    except Exception:
        resolution["warnings"].append("Resolution metadata could not be stored; later polls may report unknown source resolution.")
    return {
        "status": "queued",
        "render_id": response.render_id,
        "bucket_name": response.bucket_name,
        "output_key": f"renders/{response.render_id}/{output_key}",
        "filename": safe_name,
        "progress": 0.0,
        **resolution,
    }


def render_timeline(
    title: str,
    visuals: list[dict[str, Any]],
    audio_tracks: list[dict[str, Any]] | None = None,
    text_overlays: list[dict[str, Any]] | None = None,
    aspect_ratio: Literal["16:9", "9:16", "1:1", "4:5", "2.39:1"] = "9:16",
    fps: float | None = None,
    output_filename: str = "renderhaus-video.mp4",
    subtitles: list[dict[str, Any]] | None = None,
    video_bitrate: int | None = None,
    output_resolution: OutputResolution = "source",
) -> dict[str, Any]:
    """Compose generated image, video, and audio clips into one final MP4, then poll get_render_progress."""
    choose_canvas(str(aspect_ratio), [], output_resolution)
    if render_backend() == "lambda":
        _refuse_lambda_reframe(visuals)
    if dry_run():
        return {
            "status": "dry_run",
            "render_id": "dry-run",
            "bucket_name": "",
            "output_key": "",
            "filename": _safe_output_name(output_filename),
            "progress": 0.0,
            "note": "Dry run is enabled; set REMOTION_DRY_RUN=false to start the configured render backend.",
        }
    fitted_fields = {"box", "font_family", "min_font_size", "max_font_size"}
    needs_v2 = (any("box" in clip for clip in visuals)
                or any(fitted_fields.intersection(item) for item in [*(text_overlays or []), *(subtitles or [])]))
    if needs_v2 and render_backend() == "lambda" and os.getenv("REMOTION_OVERLAY_CONTRACT_VERSION", "1") != "2":
        raise ValueError("Lambda requires overlay contract version 2 with matching worker fonts and font assets; "
                         "use REMOTION_RENDER_BACKEND=local until that composition is deployed.")
    props = build_timeline_props(
        title,
        visuals,
        audio_tracks=audio_tracks,
        text_overlays=text_overlays,
        aspect_ratio=str(aspect_ratio),
        fps=fps,
        subtitles=subtitles,
        video_bitrate=video_bitrate,
        output_resolution=output_resolution,
        measure_remote=True,
    )
    return _start_render(props, output_filename=output_filename)


def prepare_conversational_edit(
    title: str,
    plan_summary: str,
    sources: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    overlays: list[dict[str, Any]] | None = None,
    grade: Literal["none", "neutral", "warm"] = "none",
    subtitles: bool = True,
    aspect_ratio: Literal["16:9", "9:16", "1:1", "4:5", "2.39:1"] = "9:16",
    fps: int | None = None,
) -> dict[str, Any]:
    """Prepare an approved word-range edit as a pure dry-run preview, without fetching or rendering media."""
    result = build_conversational_edit(
        title, plan_summary, sources, segments, overlays=overlays,
        grade=grade, subtitles=subtitles, aspect_ratio=aspect_ratio, fps=30 if fps is None else fps,
    )
    result["timeline"] = build_timeline_props(**result["render_arguments"], measure_local=False)
    if fps is None:
        result["render_arguments"].pop("fps")
        result["qc_expectations"]["preview_fps"] = 30
        result["qc_expectations"]["final_fps_policy"] = "primary_source"
    return result


def _progress_payload(
    *,
    render_id: str,
    bucket_name: str,
    output_key: str,
    progress: Any,
    completed_from_s3: bool,
    download: bool,
) -> dict[str, Any]:
    settings = load_remotion_settings()
    session = boto3.Session(region_name=settings.region)
    s3 = session.client("s3")
    try:
        receipt = s3.get_object(Bucket=bucket_name, Key=_resolution_key(render_id))
        resolution = _resolution_report(json.loads(receipt["Body"].read()))
    except Exception:
        resolution = _resolution_report(None)
    metadata = (getattr(progress, "renderMetadata", None) or {}) if progress else {}
    completed_dimensions = _media_dimensions(metadata.get("dimensions") or {}) if isinstance(metadata, dict) else None
    if completed_dimensions:
        resolution.update(width=completed_dimensions[0], height=completed_dimensions[1])
    done = completed_from_s3 or bool(progress and progress.done)
    failed = bool(progress and progress.fatalErrorEncountered)
    overall = (
        float(getattr(progress, "overallProgress", 0) or 0) if progress else (1.0 if done else 0.0)
    )
    if failed:
        messages = [
            str(item.get("message") or item) for item in (progress.errors[:3] if progress else [])
        ]
        return {
            "status": "failed",
            "render_id": render_id,
            "bucket_name": bucket_name,
            "progress": overall,
            "error": "Remotion render failed: " + "; ".join(messages),
            **resolution,
        }
    if not done:
        return {
            "status": "queued",
            "render_id": render_id,
            "bucket_name": bucket_name,
            "output_key": output_key,
            "progress": overall,
            **resolution,
        }
    out_key = output_key if completed_from_s3 else str((progress.outKey if progress else "") or "")
    if not out_key and progress and progress.outputFile:
        out_key = unquote(urlparse(str(progress.outputFile)).path.lstrip("/"))
    if not out_key:
        raise RuntimeError("Remotion completed but did not return an output object key.")
    url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name, "Key": out_key},
        ExpiresIn=6 * 60 * 60,
    )
    result: dict[str, Any] = {
        "status": "succeeded",
        "render_id": render_id,
        "bucket_name": bucket_name,
        "output_key": out_key,
        "url": url,
        "filename": Path(out_key).name,
        "progress": 1.0,
        **resolution,
    }
    should_download = download and not _on_lambda()
    if not completed_dimensions and not should_download:
        result["width"] = result["height"] = None
        result["warnings"].append("Rendered output dimensions could not be measured.")
    if should_download:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        destination = OUTPUT_DIR / f"{render_id}-{Path(out_key).name}"
        s3.download_file(bucket_name, out_key, str(destination))
        if not destination.is_file() or destination.stat().st_size <= 0:
            raise RuntimeError("The rendered MP4 could not be downloaded from S3.")
        result["output_path"] = str(destination)
        from providers.remotion.local import _probe

        try:
            video = next((stream for stream in _probe(destination)["streams"]
                          if stream.get("codec_type") == "video"), {})
            dimensions = _media_dimensions(video)
        except (OSError, ValueError, subprocess.SubprocessError):
            dimensions = None
        if dimensions:
            result.update(width=dimensions[0], height=dimensions[1])
        else:
            result["width"] = completed_dimensions[0] if completed_dimensions else None
            result["height"] = completed_dimensions[1] if completed_dimensions else None
            result["warnings"].append("Rendered output dimensions could not be measured.")
    return result


def get_render_progress(
    render_id: str,
    bucket_name: str,
    output_key: str | None = None,
    download: bool = True,
) -> dict[str, Any]:
    """Poll a Remotion render once. Repeat until status is succeeded, failed, or dry_run."""
    if dry_run():
        return {
            "status": "dry_run",
            "render_id": render_id,
            "bucket_name": bucket_name,
            "done": True,
            "progress": 1.0,
            "filename": "renderhaus-video.mp4",
            "note": "Dry run is enabled; set REMOTION_DRY_RUN=false to poll a live Remotion render.",
        }
    if render_id.startswith("local-"):
        from providers.remotion.local import get_progress

        return get_progress(render_id, media_roots=_allowed_local_roots())
    settings = load_remotion_settings()
    session = boto3.Session(region_name=settings.region)
    client = RemotionClient(
        region=settings.region,
        serve_url=settings.serve_url,
        function_name=settings.function_name,
        session=session,
    )
    s3 = session.client("s3")
    requested_key = str(output_key or "")
    progress = None
    completed_from_s3 = False
    try:
        progress = client.get_render_progress(render_id, bucket_name)
    except (ClientError, RemotionException):
        if requested_key:
            try:
                output = s3.head_object(Bucket=bucket_name, Key=requested_key)
            except ClientError as head_exc:
                if head_exc.response.get("Error", {}).get("Code") not in {
                    "404",
                    "NoSuchKey",
                    "NotFound",
                }:
                    raise
            else:
                if int(output.get("ContentLength") or 0) > 0:
                    completed_from_s3 = True
        if not completed_from_s3:
            raise
    return _progress_payload(
        render_id=render_id,
        bucket_name=bucket_name,
        output_key=requested_key,
        progress=progress,
        completed_from_s3=completed_from_s3,
        download=download,
    )


def render_timeline_and_wait(
    input_props: dict[str, Any],
    *,
    output_filename: str,
    timeout_seconds: float | None = None,
    poll_interval_seconds: float | None = None,
) -> dict[str, Any]:
    """Start a render and poll until it finishes. Local/smoke helper, not a Gateway tool."""
    if dry_run():
        return {
            "status": "dry_run",
            "render_id": "dry-run",
            "filename": _safe_output_name(output_filename),
            "progress": 1.0,
            "note": "Dry run is enabled; set REMOTION_DRY_RUN=false to render on Remotion Lambda.",
        }
    started = _start_render(input_props, output_filename=output_filename)
    timeout = timeout_seconds or float(os.getenv("REMOTION_RENDER_TIMEOUT_SECONDS", "1200"))
    interval = poll_interval_seconds or float(os.getenv("REMOTION_POLL_INTERVAL_SECONDS", "5"))
    deadline = time.monotonic() + max(1.0, timeout)
    last: dict[str, Any] = started
    while time.monotonic() < deadline:
        last = get_render_progress(
            started["render_id"],
            started["bucket_name"],
            output_key=started.get("output_key"),
            download=True,
        )
        if last.get("status") in {"succeeded", "failed", "dry_run"}:
            if last.get("status") == "failed":
                raise RuntimeError(str(last.get("error") or "Remotion render failed."))
            return last
        time.sleep(max(0.25, interval))
    raise TimeoutError(f"Remotion render {started['render_id']} did not finish in time.")


def _nle_storage() -> tuple[str, str, tuple[str, ...]]:
    stored: dict[str, Any] = {}
    if DEPLOYMENT_PATH.is_file():
        value = json.loads(DEPLOYMENT_PATH.read_text())
        if isinstance(value, dict):
            stored = value
    region = str(os.getenv("REMOTION_APP_REGION") or stored.get("region")
                 or os.getenv("AWS_REGION") or "us-east-1")
    bucket = str(os.getenv("REMOTION_APP_BUCKET_NAME") or stored.get("bucketName") or "")
    buckets = {bucket, os.getenv("PROVIDER_INPUT_BUCKET", ""), os.getenv("AWS_S3_BUCKET", "")}
    hosts = tuple(sorted({host for name in buckets if name for host in (
        f"{name}.s3.amazonaws.com", f"{name}.s3.{region}.amazonaws.com",
        f"{name}.s3-{region}.amazonaws.com",
    )}))
    return region, bucket, hosts


def export_nle_timeline(
    timeline_json: str,
    output_filename: str = "renderhaus-handoff.zip",
) -> dict[str, Any]:
    """Export a pinned Remotion snapshot as an OTIO, FCPXML, per-track EDL, and media ZIP."""
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(output_filename).name).strip("._-")
    safe_name = safe_name.removesuffix(".zip")[:90] or "renderhaus-handoff"
    safe_name += ".zip"
    if dry_run():
        return {
            "status": "dry_run", "filename": safe_name,
            "formats": ["otio", "fcpxml", "edl"],
            "note": "Dry run is enabled; no NLE archive or media copy was produced.",
        }
    if len(timeline_json.encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("The pinned NLE snapshot exceeds the 2 MiB input limit.")
    try:
        snapshot = json.loads(timeline_json)
    except json.JSONDecodeError as exc:
        raise ValueError("timeline_json must be a Remotion document/renderConfig JSON envelope.") from exc
    from providers.nle import build_handoff

    region, bucket, hosts = _nle_storage()
    if not _on_lambda():
        destination = ROOT / ".renderhaus" / "media" / "nle" / uuid.uuid4().hex / safe_name
        return build_handoff(snapshot, destination, media_roots=_allowed_local_roots(),
                             source_root=ROOT, allowed_media_hosts=hosts)
    if not bucket:
        raise RuntimeError("REMOTION_APP_BUCKET_NAME is required to deliver a Lambda NLE export.")
    with tempfile.TemporaryDirectory(prefix="renderhaus-nle-") as temporary:
        destination = Path(temporary) / safe_name
        result = build_handoff(snapshot, destination, media_roots=_allowed_local_roots(),
                               source_root=ROOT, allowed_media_hosts=hosts)
        s3 = boto3.Session(region_name=region).client("s3")
        key = f"renderhaus-outputs/nle/{uuid.uuid4().hex}/{safe_name}"
        s3.upload_file(str(destination), bucket, key, ExtraArgs={"ContentType": "application/zip"})
        result.pop("output_path")
        result.update({
            "bucket_name": bucket, "output_key": key,
            "url": s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key},
                                              ExpiresIn=6 * 60 * 60),
        })
        return result


def import_nle_timeline(
    interchange_text: str,
    timeline_json: str,
    format: str = "fcpxml",
) -> dict[str, Any]:
    """Import an editor's FCPXML or OTIO JSON onto existing project assets without media I/O."""
    from providers.nle.importer import import_arguments

    result = import_arguments(interchange_text, timeline_json, format)
    if dry_run() and result["status"] == "succeeded":
        result["status"] = "dry_run"
    result["note"] = "Replacement assembly only. Review the report before saving; no project or media was modified."
    return result


def render_ad_variants(stage: Literal["plan", "render_first", "render_batch"], job_id: str,
                       brief: dict, rows: list[dict], master_asset: str,
                       plan_hash: str = "", concurrency: int = 2) -> dict[str, Any]:
    """Plan retail variants for free; first/batch need human approval of the exact plan hash."""
    from providers.remotion.ad_variants import render_ad_variants as run_matrix

    return run_matrix(stage, job_id, brief, rows, master_asset, plan_hash, concurrency)


TOOL_HANDLERS = {
    "render_ad_variants": render_ad_variants,
    "import_nle_timeline": import_nle_timeline,
    "prepare_conversational_edit": prepare_conversational_edit,
    "render_timeline": render_timeline,
    "get_render_progress": get_render_progress,
    "export_nle_timeline": export_nle_timeline,
}

GATEWAY_TOOLS = (
    "render_ad_variants",
    "import_nle_timeline",
    "prepare_conversational_edit",
    "render_timeline",
    "get_render_progress",
    "export_nle_timeline",
)
