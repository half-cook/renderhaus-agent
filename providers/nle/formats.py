"""OTIO, FCPXML 1.9, and per-track CMX3600 representations of a pinned edit."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import PurePosixPath
from typing import Any
from xml.etree import ElementTree as ET

import opentimelineio as otio

from providers.nle.model import Clip, Timeline, Track


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("._-")[:70] or "media"


def media_paths(timeline: Timeline) -> dict[str, str]:
    return {
        asset.id: str(PurePosixPath("media") / _safe_name(asset.version_id)
                      / f"{_safe_name(asset.id)}-{asset.checksum[:16]}{_suffix(asset.source)}")
        for asset in timeline.assets
    }


def _suffix(source: str) -> str:
    suffix = PurePosixPath(source.split("?", 1)[0]).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else ".bin"


def track_entries(timeline: Timeline) -> list[dict[str, Any]]:
    counts = {"video": 0, "audio": 0}
    entries: list[dict[str, Any]] = []
    for track in timeline.tracks:
        counts[track.kind] += 1
        number = counts[track.kind]
        prefix = "V" if track.kind == "video" else "A"
        entries.append({
            "id": track.id, "name": track.name, "kind": track.kind, "number": number,
            "generated": track.generated, "originalTrackId": track.original_track_id,
            "edl": f"edl/{prefix}{number:02}-{_safe_name(track.name)}.edl",
            "clipIds": [clip.id for clip in track.clips],
        })
    return entries


def otio_text(timeline: Timeline, paths: dict[str, str]) -> str:
    rate = float(timeline.rate.value)
    assets = {asset.id: asset for asset in timeline.assets}

    def time_range(start: int, duration: int) -> otio.opentime.TimeRange:
        return otio.opentime.TimeRange(otio.opentime.RationalTime(start, rate),
                                       otio.opentime.RationalTime(duration, rate))

    result = otio.schema.Timeline(
        name=timeline.name,
        global_start_time=otio.opentime.RationalTime(timeline.start_frame, rate),
        metadata={"renderhaus": {
            "projectId": timeline.id, "fps": str(timeline.rate.value),
            "dropFrame": timeline.rate.drop_frame, "timecode": timeline.start_timecode,
            "width": timeline.width, "height": timeline.height,
            "durationInFrames": timeline.duration, "warnings": list(timeline.warnings),
        }},
    )
    for track in timeline.tracks:
        exported = otio.schema.Track(
            name=track.name,
            kind=otio.schema.TrackKind.Audio if track.kind == "audio" else otio.schema.TrackKind.Video,
            metadata={"renderhaus": {
                "trackId": track.id, "generated": track.generated,
                "originalTrackId": track.original_track_id, "locked": track.locked,
            }},
        )
        cursor = 0
        for clip in track.clips:
            if clip.start > cursor:
                exported.append(otio.schema.Gap(source_range=time_range(0, clip.start - cursor)))
            asset = assets[clip.asset_id]
            reference = otio.schema.ExternalReference(
                target_url=paths[asset.id],
                available_range=time_range(asset.source_start, asset.duration),
                metadata={"renderhaus": asset.metadata()},
            )
            exported.append(otio.schema.Clip(
                name=asset.name, media_reference=reference,
                source_range=time_range(asset.source_start + clip.source_in, clip.duration),
                metadata={"renderhaus": {
                    **asset.metadata(), "clipId": clip.id, "originalTrackId": clip.original_track_id,
                    "recordStartFrame": clip.start, "sourceInFrames": clip.source_in,
                    "fit": clip.fit, "volume": clip.volume,
                }},
            ))
            cursor = clip.start + clip.duration
        if cursor < timeline.duration:
            exported.append(otio.schema.Gap(source_range=time_range(0, timeline.duration - cursor)))
        result.tracks.append(exported)
    return otio.adapters.write_to_string(result, adapter_name="otio_json")


def _metadata(parent: ET.Element, values: dict[str, Any]) -> None:
    metadata = ET.SubElement(parent, "metadata")
    for key, value in values.items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        elif isinstance(value, bool):
            value = "true" if value else "false"
        ET.SubElement(metadata, "md", {"key": f"com.renderhaus.{key}", "value": str(value)})


def fcpxml_text(timeline: Timeline, paths: dict[str, str]) -> str:
    root = ET.Element("fcpxml", {"version": "1.9"})
    resources = ET.SubElement(root, "resources")
    ET.SubElement(resources, "format", {
        "id": "r1", "name": "Renderhaus", "frameDuration": timeline.rate.xml_time(1),
        "width": str(timeline.width), "height": str(timeline.height),
    })
    assets = {asset.id: asset for asset in timeline.assets}
    references = {asset.id: f"r{index + 2}" for index, asset in enumerate(timeline.assets)}
    for asset in timeline.assets:
        attributes = {
            "id": references[asset.id], "name": asset.name,
            "start": timeline.rate.xml_time(asset.source_start),
            "duration": timeline.rate.xml_time(asset.duration),
            "hasVideo": "0" if asset.kind == "audio" else "1",
            "hasAudio": "1" if asset.has_audio else "0",
        }
        if asset.kind != "audio":
            attributes["format"] = "r1"
        if asset.has_audio:
            attributes.update(audioSources="1", audioChannels="2", audioRate="48000")
        element = ET.SubElement(resources, "asset", attributes)
        ET.SubElement(element, "media-rep", {"kind": "original-media", "src": paths[asset.id]})
        _metadata(element, asset.metadata())
    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", {"name": "Renderhaus handoff"})
    project = ET.SubElement(event, "project", {"name": timeline.name})
    sequence = ET.SubElement(project, "sequence", {
        "format": "r1", "duration": timeline.rate.xml_time(timeline.duration),
        "tcStart": timeline.rate.xml_time(timeline.start_frame),
        "tcFormat": "DF" if timeline.rate.drop_frame else "NDF",
        "audioLayout": "stereo", "audioRate": "48k",
    })
    spine = ET.SubElement(sequence, "spine")

    def clip_element(parent: ET.Element, clip: Clip, track: Track,
                     offset: int, lane: int | None = None) -> ET.Element:
        asset = assets[clip.asset_id]
        attributes = {
            "ref": references[asset.id], "name": asset.name,
            "offset": timeline.rate.xml_time(offset),
            "start": timeline.rate.xml_time(asset.source_start + clip.source_in),
            "duration": timeline.rate.xml_time(clip.duration),
            "srcEnable": "audio" if track.kind == "audio" else ("all" if asset.has_audio else "video"),
            "audioRole": "dialogue" if asset.has_audio else "",
        }
        if not asset.has_audio:
            attributes.pop("audioRole")
        if lane is not None:
            attributes["lane"] = str(lane)
        element = ET.SubElement(parent, "asset-clip", attributes)
        if track.kind != "audio":
            ET.SubElement(element, "adjust-conform", {"type": "fit" if clip.fit == "contain" else "fill"})
        if asset.has_audio and clip.volume != 1:
            gain = f"{20 * math.log10(clip.volume):.6f}dB" if clip.volume else "-96dB"
            ET.SubElement(element, "adjust-volume", {"amount": gain})
        return element

    video_tracks = [track for track in timeline.tracks if track.kind == "video"]
    audio_tracks = [track for track in timeline.tracks if track.kind == "audio"]
    anchors: list[tuple[int, int, int, ET.Element]] = []
    clip_metadata: list[tuple[ET.Element, Clip, Track]] = []
    cursor = 0

    def gap(start: int, end: int) -> None:
        local = timeline.start_frame + start
        element = ET.SubElement(spine, "gap", {
            "name": "Gap", "offset": timeline.rate.xml_time(local),
            "start": timeline.rate.xml_time(local), "duration": timeline.rate.xml_time(end - start),
        })
        anchors.append((start, end, local, element))

    if video_tracks:
        primary = video_tracks[0]
        for clip in primary.clips:
            if clip.start > cursor:
                gap(cursor, clip.start)
            element = clip_element(spine, clip, primary, timeline.start_frame + clip.start)
            local = assets[clip.asset_id].source_start + clip.source_in
            anchors.append((clip.start, clip.start + clip.duration, local, element))
            clip_metadata.append((element, clip, primary))
            cursor = clip.start + clip.duration
    if cursor < timeline.duration:
        gap(cursor, timeline.duration)
    connected_tracks = [(index, track) for index, track in enumerate(video_tracks) if index]
    connected_tracks.extend((-(index + 1), track) for index, track in enumerate(audio_tracks))
    for lane, track in connected_tracks:
        for clip in track.clips:
            start, _, local, parent = next(anchor for anchor in anchors
                                           if anchor[0] <= clip.start < anchor[1])
            element = clip_element(parent, clip, track, local + clip.start - start, lane)
            clip_metadata.append((element, clip, track))
    for element, clip, track in clip_metadata:
        _metadata(element, {
            **assets[clip.asset_id].metadata(), "clipId": clip.id, "trackId": track.id,
            "trackName": track.name, "originalTrackId": track.original_track_id,
            "recordStartFrame": clip.start,
        })
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + ET.tostring(
        root, encoding="unicode", short_empty_elements=True,
    ) + "\n"


def reel_aliases(timeline: Timeline) -> dict[str, str]:
    reels = sorted({asset.reel_name for asset in timeline.assets})
    aliases: dict[str, str] = {}
    used = {"BL", "AX"}
    for reel in reels:
        if re.fullmatch(r"[A-Za-z0-9_]{1,8}", reel) and reel.upper() not in used:
            aliases[reel] = reel
            used.add(reel.upper())
            continue
        for salt in range(10000):
            alias = "R" + hashlib.sha256(f"{reel}:{salt}".encode()).hexdigest()[:7].upper()
            if alias not in used:
                aliases[reel] = alias
                used.add(alias)
                break
        else:
            raise ValueError("Could not allocate a unique CMX3600 reel alias.")
    return aliases


def edl_texts(timeline: Timeline, paths: dict[str, str],
              aliases: dict[str, str]) -> dict[str, str]:
    assets = {asset.id: asset for asset in timeline.assets}
    result: dict[str, str] = {}
    for track, entry in zip(timeline.tracks, track_entries(timeline), strict=True):
        if len(track.clips) > 999:
            raise ValueError("A CMX3600 track supports at most 999 events.")
        lines = [
            f"TITLE: {timeline.name} - {track.name}",
            f"FCM: {'DROP FRAME' if timeline.rate.drop_frame else 'NON-DROP FRAME'}",
            f"* FRAME RATE: {timeline.rate.value}",
            f"* TRACK: {'V' if track.kind == 'video' else 'A'}{entry['number']}",
            f"* GENERATED TRACK: {'YES' if track.generated else 'NO'}", "",
        ]
        channel = "V" if track.kind == "video" else "A"
        for index, clip in enumerate(track.clips, start=1):
            asset = assets[clip.asset_id]
            source_in = asset.source_start + clip.source_in
            record_in = timeline.start_frame + clip.start
            lines.extend([
                f"{index:03}  {aliases[asset.reel_name]:<8} {channel:<4} C        "
                f"{timeline.rate.timecode(source_in)} {timeline.rate.timecode(source_in + clip.duration)} "
                f"{timeline.rate.timecode(record_in)} {timeline.rate.timecode(record_in + clip.duration)}",
                f"* FROM CLIP NAME: {asset.name}", f"* SOURCE FILE: {paths[asset.id]}",
                f"* ORIGINAL REEL: {asset.reel_name}", f"* VERSION ID: {asset.version_id}", "",
            ])
        result[entry["edl"]] = "\n".join(lines) + "\n"
    return result
