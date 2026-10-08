"""A pinned, frame-based edit shared by OTIO, FCPXML, and CMX3600."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from providers.nle.timecode import FrameRate


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
        raise ValueError(f"{field} must be a non-empty string of at most 1000 characters.")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{field} must not contain control characters.")
    return value


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object.")
    return value


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array.")
    return value


def _safe_provenance(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _safe_provenance(item)
            for key, item in value.items()
            if not re.search(r"password|secret|token|cookie|authorization|api.?key", key, re.I)
        }
    if isinstance(value, list):
        return [_safe_provenance(item) for item in value]
    if isinstance(value, str):
        def strip_url(match: re.Match[str]) -> str:
            parsed = urlsplit(match.group(0))
            return urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", ""))
        return re.sub(r"https?://[^\s\"<>]+", strip_url, value, flags=re.I)
    return value


@dataclass(frozen=True, slots=True)
class Asset:
    id: str
    name: str
    kind: str
    source: str
    version_id: str
    checksum: str
    source_timecode: str
    source_start: int
    reel_name: str
    provenance: dict[str, Any]
    generated: bool
    duration: int
    has_audio: bool

    def metadata(self) -> dict[str, Any]:
        return {
            "assetId": self.id,
            "versionId": self.version_id,
            "checksum": self.checksum,
            "sourceTimecode": self.source_timecode,
            "reelName": self.reel_name,
            "provenance": self.provenance,
            "generated": self.generated,
            "sourceDurationFrames": self.duration,
        }


@dataclass(frozen=True, slots=True)
class Clip:
    id: str
    asset_id: str
    start: int
    duration: int
    source_in: int
    original_track_id: str
    fit: str
    volume: float


@dataclass(frozen=True, slots=True)
class Track:
    id: str
    name: str
    kind: str
    clips: tuple[Clip, ...]
    generated: bool = False
    original_track_id: str = ""
    locked: bool = False


@dataclass(frozen=True, slots=True)
class Timeline:
    id: str
    name: str
    rate: FrameRate
    start_timecode: str
    start_frame: int
    width: int
    height: int
    duration: int
    assets: tuple[Asset, ...]
    tracks: tuple[Track, ...]
    warnings: tuple[str, ...]


def _integer(value: Any, field: str, *, maximum: int = 16384) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{field} must be an integer between 1 and {maximum}.")
    return value


def _clip(raw: Any, track_id: str, assets: dict[str, Asset], rate: FrameRate) -> Clip:
    item = _object(raw, "track item")
    if item.get("type", "clip") != "clip":
        raise ValueError("NLE handoff supports media clips and gaps; bake titles before export.")
    clip_id = _text(item.get("id"), "clip.id")
    asset_id = _text(item.get("assetId"), "clip.assetId")
    if asset_id not in assets:
        raise ValueError(f"Clip {clip_id} references an unknown asset.")
    defaults = {
        "playbackRate": 1, "motion": "none", "transition": "cut", "fadeIn": 0,
        "fadeOut": 0, "opacity": 1, "scale": 1, "rotation": 0,
        "positionX": 0.5, "positionY": 0.5,
    }
    for field, default in defaults.items():
        if item.get(field, default) != default:
            raise ValueError(f"Clip {clip_id} has unsupported {field}; bake it before export.")
    if item.get("effects") or item.get("enabled", True) is not True:
        raise ValueError(f"Clip {clip_id} has effects or disabled state; bake it before export.")
    start, duration = rate.clip_range(item.get("start", 0), item.get("duration"))
    source_in = rate.seconds_to_frames(item.get("sourceIn", 0), "clip.sourceIn")
    if "sourceOut" in item:
        source_out = rate.seconds_to_frames(item["sourceOut"], "clip.sourceOut")
        if source_out != source_in + duration:
            raise ValueError(f"Clip {clip_id} sourceOut does not match its unretimed duration.")
    asset = assets[asset_id]
    if source_in + duration > asset.duration:
        raise ValueError(f"Clip {clip_id} extends beyond its pinned source media duration.")
    rate.timecode(asset.source_start + source_in + duration)
    fit = item.get("fit", "cover")
    if fit not in {"cover", "contain"}:
        raise ValueError(f"Clip {clip_id} fit must be cover or contain.")
    volume = item.get("volume", 1)
    if isinstance(volume, bool) or not isinstance(volume, (int, float)) or not 0 <= volume <= 1:
        raise ValueError(f"Clip {clip_id} volume must be between 0 and 1.")
    return Clip(clip_id, asset_id, start, duration, source_in, track_id, fit, float(volume))


def parse_snapshot(snapshot: dict[str, Any]) -> Timeline:
    """Validate a Remotion envelope and assign generated clips to new tracks once."""
    envelope = _object(snapshot, "timeline")
    document = _object(envelope.get("document"), "document")
    config = _object(envelope.get("renderConfig"), "renderConfig")
    rate = FrameRate.parse(config.get("fps"), config.get("dropFrame", False))
    start_timecode = _text(config.get("timecode", "00:00:00;00" if rate.drop_frame else "00:00:00:00"),
                           "renderConfig.timecode")
    start_frame = rate.parse_timecode(start_timecode)
    timeline_id = _text(document.get("id"), "document.id")
    name = _text(document.get("name"), "document.name")
    width = _integer(config.get("width"), "renderConfig.width")
    height = _integer(config.get("height"), "renderConfig.height")
    duration = _integer(config.get("durationInFrames"), "renderConfig.durationInFrames",
                        maximum=rate.frames_per_day - 1)
    rate.timecode(start_frame + duration)
    assets: dict[str, Asset] = {}
    versions: dict[str, tuple[Any, ...]] = {}
    for raw in _list(document.get("assets"), "document.assets"):
        raw = _object(raw, "asset")
        asset_id = _text(raw.get("id"), "asset.id")
        if asset_id in assets:
            raise ValueError("Asset IDs must be unique.")
        version = _text(raw.get("versionId"), "asset.versionId")
        if "://" in version:
            raise ValueError("asset.versionId must be a plain immutable identifier, not a media URL.")
        checksum = _text(raw.get("checksum"), "asset.checksum").removeprefix("sha256:").lower()
        if not re.fullmatch(r"[a-f0-9]{64}", checksum):
            raise ValueError("asset.checksum must be a SHA-256 checksum.")
        source_timecode = _text(raw.get("sourceTimecode"), "asset.sourceTimecode")
        source_start = rate.parse_timecode(source_timecode)
        kind = raw.get("kind")
        if kind not in {"video", "audio", "image"}:
            raise ValueError("asset.kind must be video, audio, or image.")
        if "fps" in raw and FrameRate.parse(raw["fps"]).value != rate.value:
            raise ValueError("Mixed source frame rates require conforming before NLE export.")
        provenance = _object(raw.get("provenance"), "asset.provenance")
        if not provenance:
            raise ValueError("asset.provenance must identify the pinned source or generation.")
        try:
            provenance = _safe_provenance(json.loads(json.dumps(provenance, allow_nan=False)))
        except (TypeError, ValueError) as exc:
            raise ValueError("asset.provenance must contain JSON values.") from exc
        generated = raw.get("generated")
        if not isinstance(generated, bool):
            raise ValueError("asset.generated must explicitly classify the immutable version.")
        if kind == "video" and "hasAudio" not in raw:
            raise ValueError("Video assets require explicit hasAudio source metadata.")
        has_audio = raw.get("hasAudio", kind == "audio")
        if not isinstance(has_audio, bool):
            raise ValueError("asset.hasAudio must be a boolean.")
        if kind == "image" and has_audio:
            raise ValueError("Still image assets cannot carry audio.")
        source_duration = rate.seconds_to_frames(raw.get("durationSec"), "asset.durationSec",
                                                positive=True)
        reel_name = _text(raw.get("reelName"), "asset.reelName")
        fingerprint = (checksum, kind, source_timecode, reel_name, generated, source_duration,
                       has_audio, json.dumps(provenance, sort_keys=True))
        if version in versions and versions[version] != fingerprint:
            raise ValueError("An immutable versionId must not identify conflicting source metadata.")
        versions[version] = fingerprint
        assets[asset_id] = Asset(
            asset_id, _text(raw.get("name", asset_id), "asset.name"), kind,
            _text(raw.get("url"), "asset.url"), version, checksum, source_timecode, source_start,
            reel_name, provenance, generated,
            source_duration, has_audio,
        )
    if not assets:
        raise ValueError("A handoff needs pinned media assets.")
    tracks: list[Track] = []
    generated_tracks: list[Track] = []
    track_ids: set[str] = set()
    clip_ids: set[str] = set()
    used_assets: set[str] = set()
    warnings: list[str] = []
    for raw in _list(document.get("tracks"), "document.tracks"):
        raw = _object(raw, "track")
        track_id = _text(raw.get("id"), "track.id")
        if track_id in track_ids:
            raise ValueError("Track IDs must be unique.")
        track_ids.add(track_id)
        kind = raw.get("kind")
        if kind not in {"video", "overlay", "audio"}:
            raise ValueError("NLE handoff supports video and audio tracks; bake titles before export.")
        if (raw.get("effects") or raw.get("muted") or raw.get("hidden")
                or raw.get("enabled", True) is not True):
            raise ValueError("Track effects and hidden or muted tracks require baking before export.")
        clips = sorted((_clip(item, track_id, assets, rate)
                        for item in _list(raw.get("items"), "track.items")),
                       key=lambda clip: (clip.start, clip.id))
        previous_end = 0
        for clip in clips:
            if clip.id in clip_ids:
                raise ValueError("Clip IDs must be unique.")
            clip_ids.add(clip.id)
            if clip.start < previous_end:
                raise ValueError("Overlapping clips in one source track need separate tracks.")
            previous_end = clip.start + clip.duration
            if previous_end > duration:
                raise ValueError("A clip extends beyond renderConfig.durationInFrames.")
            asset = assets[clip.asset_id]
            if kind == "audio" and not asset.has_audio:
                raise ValueError("An audio track needs audio-bearing source media.")
            if kind != "audio" and asset.kind == "audio":
                raise ValueError("A video track cannot reference audio-only source media.")
            used_assets.add(clip.asset_id)
            if clip.volume != 1:
                warnings.append("CMX3600 omits audio gain. FCPXML carries gain and OTIO stores it in metadata.")
        track_name = _text(raw.get("name", track_id), "track.name")
        normal = tuple(clip for clip in clips if not assets[clip.asset_id].generated)
        generated = tuple(clip for clip in clips if assets[clip.asset_id].generated)
        track_kind = "audio" if kind == "audio" else "video"
        tracks.append(Track(track_id, track_name, track_kind, normal, original_track_id=track_id,
                            locked=bool(raw.get("locked", False))))
        if generated:
            new_id = "renderhaus-generated-" + hashlib.sha256(track_id.encode()).hexdigest()[:16]
            generated_tracks.append(Track(new_id, f"Generated - {track_name}", track_kind,
                                          generated, True, track_id))
    if not used_assets:
        raise ValueError("A handoff needs at least one media clip.")
    ordered = tuple(track for kind in ("video", "audio")
                    for group in (tracks, generated_tracks) for track in group if track.kind == kind)
    if len({track.id for track in ordered}) != len(ordered):
        raise ValueError("Generated track IDs conflict with an existing track ID.")
    warnings.append("CMX3600 uses one EDL per track. Import each at its recorded track number.")
    return Timeline(timeline_id, name, rate, start_timecode, start_frame, width, height, duration,
                    tuple(asset for asset_id, asset in assets.items() if asset_id in used_assets),
                    ordered, tuple(dict.fromkeys(warnings)))
