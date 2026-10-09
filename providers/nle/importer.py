"""Local FCPXML 1.9–1.11 and OTIO JSON import. Never dereference media.

Apple timing and story-element contracts, read 2026-10-09:
https://developer.apple.com/documentation/professional-video-applications/timing-attributes
https://developer.apple.com/documentation/professional-video-applications/document-type-definition
OTIO uses the already pinned Apache-2.0 dependency, without adapter plugins.
"""

from __future__ import annotations

import copy
import json
import math
import re
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

import opentimelineio as otio

from providers.nle.formats import _safe_name, _suffix
from providers.nle.timecode import FrameRate

MAX_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 64
MAX_NODES = 20000


class _LimitedTree(ET.TreeBuilder):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.nodes = 0

    def start(self, tag, attrs):
        self.depth += 1
        self.nodes += 1
        if self.depth > MAX_DEPTH or self.nodes > MAX_NODES:
            raise ValueError('Interchange structure exceeds the depth or element limit.')
        return super().start(tag, attrs)

    def end(self, tag):
        self.depth -= 1
        return super().end(tag)

    def doctype(self, name, pubid, system):
        if name != 'fcpxml' or pubid or system:
            raise ValueError('External XML declarations are forbidden.')


def _bounded(text: str, label: str) -> None:
    if not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError(f'{label} must contain 1 to {MAX_BYTES} UTF-8 bytes.')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON keys are forbidden.')
        result[key] = value
    return result


def _json(text: str) -> Any:
    _bounded(text, 'JSON')
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=lambda _: _invalid_number())
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('Malformed interchange JSON.') from exc
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > MAX_DEPTH or nodes > MAX_NODES:
            raise ValueError('Interchange structure exceeds the depth or element limit.')
        if isinstance(item, (dict, list)):
            pending.extend((child, depth + 1) for child in (item.values() if isinstance(item, dict) else item))
        elif isinstance(item, float) and not math.isfinite(item):
            _invalid_number()
    return value


def _invalid_number():
    raise ValueError('Interchange numbers must be finite.')


def _seconds(value: Any) -> Fraction:
    if isinstance(value, bool):
        raise ValueError('Invalid interchange time.')
    try:
        result = Fraction(str(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError('Invalid interchange time.') from exc
    if result < 0 or result > 86400:
        raise ValueError('Interchange times must be between zero and 24 hours.')
    return result


def _xml_time(value: str) -> Fraction:
    if not re.fullmatch(r'\d{1,19}(?:/\d{1,10})?s', value):
        raise ValueError('FCPXML times must be nonnegative rational seconds.')
    return _seconds(value[:-1])


def _basename(value: str) -> str:
    return PurePosixPath(unquote(urlsplit(value).path).replace('\\', '/')).name


def _xml_metadata(element: ET.Element) -> dict:
    return {item.get('key', '').removeprefix('com.renderhaus.'): item.get('value', '')
            for item in element.findall('./metadata/md') if item.get('key', '').startswith('com.renderhaus.')}


def _identity(resource: dict, clip: dict) -> dict:
    conflict = any(resource.get(key) and clip.get(key) and resource[key] != clip[key]
                   for key in ('assetId', 'versionId', 'checksum'))
    return {**resource, **clip, '_identity_conflict': conflict}


@dataclass
class _Import:
    current: dict
    rate: FrameRate
    assets: dict[str, dict]
    tracks: list[dict] = field(default_factory=list)
    unmatched: list[dict] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    matched_by: dict[str, int] = field(default_factory=lambda: {'asset_id': 0, 'version_id': 0, 'filename_duration': 0})
    clip_ids: set[str] = field(default_factory=set)

    @classmethod
    def create(cls, current: dict):
        if not isinstance(current, dict) or not isinstance(current.get('document'), dict) or not isinstance(current.get('renderConfig'), dict):
            raise ValueError('timeline_json requires a document/renderConfig envelope.')
        document, config = current['document'], current['renderConfig']
        rate = FrameRate.parse(config.get('fps'), config.get('dropFrame', False))
        if not isinstance(document.get('assets'), list) or not isinstance(document.get('tracks'), list):
            raise ValueError('The current assembly requires assets and tracks arrays.')
        assets = {}
        for asset in document['assets']:
            if (not isinstance(asset, dict) or not isinstance(asset.get('id'), str) or not asset['id']
                    or asset['id'] in assets or asset.get('kind') not in {'video', 'audio', 'image'}
                    or not isinstance(asset.get('url'), str)):
                raise ValueError('Existing assets require unique IDs, media kinds, and URLs.')
            _seconds(asset.get('durationSec'))
            assets[asset['id']] = asset
        return cls(copy.deepcopy(current), rate, assets)

    def frames(self, seconds: Fraction) -> int:
        value = seconds * self.rate.value
        nearest = round(value)
        if abs(value - nearest) > Fraction(1, 10000):
            raise ValueError('Subframe or mixed-rate edits must be conformed before import.')
        return nearest

    def match(self, metadata: dict, reference: str, duration: Fraction | None, kind: str) -> dict | None:
        asset_id, version = metadata.get('assetId'), metadata.get('versionId')
        if metadata.get('_identity_conflict'):
            self.unmatched.append({'reference': _basename(reference), 'asset_id': asset_id,
                                   'reason': 'Clip and media resource identities conflict.'})
            return None
        reason = 'No unique filename and full source duration match.'
        candidates = []
        method = 'filename_duration'
        if asset_id:
            method = 'asset_id'
            candidates = [self.assets[asset_id]] if asset_id in self.assets else []
            reason = 'Embedded asset ID is absent from the current project.'
        elif version:
            method = 'version_id'
            candidates = [a for a in self.assets.values() if a.get('versionId') == version]
            reason = 'Embedded version ID is absent or ambiguous in the current project.'
        elif duration is not None:
            name = _basename(reference)
            for asset in self.assets.values():
                names = {_basename(asset['url'])}
                if asset.get('checksum'):
                    names.add(f"{_safe_name(asset['id'])}-{asset['checksum'].removeprefix('sha256:')[:16]}{_suffix(asset['url'])}")
                if name in names and self.rate.seconds_to_frames(asset['durationSec'], 'asset.durationSec') == self.frames(duration):
                    candidates.append(asset)
        if len(candidates) == 1:
            asset = candidates[0]
            if version and asset.get('versionId') != version:
                reason = 'Embedded asset/version identities conflict.'
            elif kind == 'audio' and not asset.get('hasAudio', asset['kind'] == 'audio'):
                reason = 'Audio track refers to a source without audio.'
            elif kind == 'video' and asset['kind'] == 'audio':
                reason = 'Video track refers to audio-only media.'
            else:
                self.matched_by[method] += 1
                return asset
        self.unmatched.append({'reference': _basename(reference), 'asset_id': asset_id, 'reason': reason})
        return None

    def clip(self, track: dict, metadata: dict, asset: dict, start: Fraction,
             duration: Fraction, source_in: Fraction, *, fit='cover', volume=1.0) -> dict:
        if min(start, source_in) < 0 or duration <= 0:
            raise ValueError('Clip positions and source windows must be nonnegative with positive duration.')
        if fit not in {'cover', 'contain'} or not math.isfinite(volume) or not 0 <= volume <= 1:
            raise ValueError('Clip fit or volume is unsupported.')
        start_frame, length, source = (self.frames(value) for value in (start, duration, source_in))
        if source + length > self.rate.seconds_to_frames(asset['durationSec'], 'asset.durationSec'):
            raise ValueError('Imported clip extends beyond its existing source media.')
        clip_id = metadata.get('clipId') or f"nle-clip-{len(self.clip_ids) + 1}"
        if not isinstance(clip_id, str) or not clip_id:
            raise ValueError('Invalid clip identity.')
        if clip_id in self.clip_ids:
            # Editors commonly duplicate clips together with their identity metadata.
            clip_id = f'{clip_id}-copy-{len(self.clip_ids) + 1}'
        if clip_id in self.clip_ids:
            raise ValueError('Imported clip IDs conflict.')
        self.clip_ids.add(clip_id)
        seconds = lambda frames: float(Fraction(frames) / self.rate.value)
        clip = {'id': clip_id, 'type': 'clip', 'assetId': asset['id'], 'start': seconds(start_frame),
                'duration': seconds(length), 'sourceIn': seconds(source), 'fit': fit, 'volume': volume}
        clip['originalTrackId'] = metadata.get('originalTrackId') or track.get('originalTrackId') or track['id']
        track['items'].append(clip)
        return clip

    def finish(self, config: dict, markers: list[dict]) -> dict:
        ids = set()
        for track in self.tracks:
            if track['id'] in ids:
                raise ValueError('Imported track IDs conflict.')
            ids.add(track['id'])
            track['items'].sort(key=lambda clip: clip['start'])
            cursor = 0
            for clip in track['items']:
                if self.frames(_seconds(clip['start'])) < cursor:
                    self.unsupported.append('Overlapping clips require separate tracks.')
                cursor = self.frames(_seconds(clip['start'])) + self.frames(_seconds(clip['duration']))
                if cursor > config['durationInFrames']:
                    raise ValueError('Imported clip exceeds the sequence duration.')
        blocked = bool(self.unmatched or self.unsupported)
        result = self.current
        result['document'].update(tracks=self.tracks, markers=markers)
        result['renderConfig'].update(config)
        return {'status': 'blocked' if blocked else 'succeeded', 'timeline': None if blocked else result,
                'unmatched_media': self.unmatched, 'unsupported': list(dict.fromkeys(self.unsupported)),
                'warnings': self.warnings, 'matched_by': self.matched_by, 'training_eligible': False}


def _marker(name: str, start: Fraction, duration: Fraction, state: _Import, **extra) -> dict:
    if start < 0:
        raise ValueError('Marker starts before its container.')
    return {'name': name, 'start': float(Fraction(state.frames(start)) / state.rate.value),
            'duration': float(Fraction(state.frames(duration)) / state.rate.value), **extra}


def _fcpxml(text: str, state: _Import) -> dict:
    if re.search(r'<!ENTITY', text, re.I):
        raise ValueError('XML entity declarations are forbidden.')
    declarations = re.findall(r'<!DOCTYPE[^>]*>', text, re.I)
    if any(not re.fullmatch(r'<!DOCTYPE\s+fcpxml\s*>', declaration) for declaration in declarations):
        raise ValueError('Only the bare fcpxml DOCTYPE is allowed.')
    try:
        root = ET.fromstring(text, parser=ET.XMLParser(target=_LimitedTree()))
    except ET.ParseError as exc:
        raise ValueError('Malformed FCPXML.') from exc
    if root.tag != 'fcpxml' or root.get('version') not in {'1.9', '1.10', '1.11'}:
        raise ValueError('Only FCPXML versions 1.9, 1.10 and 1.11 are supported.')
    sequences = root.findall('.//project/sequence')
    if len(sequences) != 1:
        raise ValueError('Import exactly one project sequence at a time.')
    sequence = sequences[0]
    resources = {}
    for element in root.findall('./resources/*'):
        identity = element.get('id')
        if not identity or identity in resources:
            raise ValueError('FCPXML resource IDs must be present and unique.')
        resources[identity] = element
    format = resources.get(sequence.get('format'))
    if format is None or format.tag != 'format':
        raise ValueError('The sequence requires a format resource.')
    frame_duration = _xml_time(format.get('frameDuration', ''))
    if frame_duration == 0:
        raise ValueError('Frame duration must be positive.')
    fps = 1 / frame_duration
    df = sequence.get('tcFormat', 'NDF') == 'DF'
    if FrameRate.parse(str(fps), df) != state.rate:
        raise ValueError('Conform the edit to the current project frame rate and drop-frame mode.')
    tc_start = _xml_time(sequence.get('tcStart', '0s'))
    duration = _xml_time(sequence.get('duration', ''))
    config = {'fps': float(fps) if fps.denominator == 1 else str(fps), 'dropFrame': df,
              'timecode': state.rate.timecode(state.frames(tc_start)),
              'width': int(format.get('width', '0')), 'height': int(format.get('height', '0')),
              'durationInFrames': state.frames(duration)}
    if min(config['width'], config['height']) <= 0:
        raise ValueError('The sequence requires positive dimensions.')
    spine = sequence.find('spine')
    if spine is None:
        raise ValueError('The sequence requires a spine.')
    known = {}
    table = _xml_metadata(sequence).get('tracks')
    if table:
        entries = _json(table)
        if not isinstance(entries, list):
            raise ValueError('Invalid exported track table.')
        for entry in entries:
            if (not isinstance(entry, dict) or entry.get('kind') not in {'video', 'audio'}
                    or not isinstance(entry.get('id'), str) or not entry['id']
                    or not isinstance(entry.get('number'), int) or isinstance(entry['number'], bool)
                    or entry['number'] < 1 or not isinstance(entry.get('name'), str)):
                raise ValueError('Invalid exported track table entry.')
            lane = entry['number'] - 1 if entry['kind'] == 'video' else -entry['number']
            if lane in known:
                raise ValueError('Exported track lane numbers conflict.')
            known[lane] = {'id': entry['id'], 'name': entry['name'], 'kind': entry['kind'], 'items': [],
                           'generated': entry.get('generated', False), 'originalTrackId': entry.get('originalTrackId', entry['id']),
                           'locked': entry.get('locked', False)}
    lanes = dict(known)
    annotations = {'marker', 'chapter-marker'}
    markers = []
    allowed = {'asset-clip', 'gap', 'spine', 'metadata', 'md', 'note', 'adjust-conform', 'adjust-volume', *annotations}
    for element in spine.iter():
        if element.tag not in allowed:
            state.unsupported.append(f'Unsupported FCPXML element {element.tag}; bake or simplify it before import.')
        if element.tag == 'adjust-volume' and list(element):
            state.unsupported.append('Animated audio gain is unsupported.')
        if element.tag == 'adjust-conform' and element.get('type') not in {'fit', 'fill'}:
            state.unsupported.append('Unsupported conform mode.')

    def visit(parent, parent_record: Fraction, parent_source: Fraction, inherited_lane: int):
        for element in parent:
            if element.tag not in {'asset-clip', 'gap', 'spine'}:
                continue
            lane = int(element.get('lane', str(inherited_lane)))
            offset = _xml_time(element.get('offset', '0s'))
            record = parent_record + offset - parent_source
            source = _xml_time(element.get('start', '0s'))
            if element.tag == 'gap':
                markers.extend(_marker(m.get('value', ''), record + _xml_time(m.get('start', '0s')) - source,
                                       _xml_time(m.get('duration', '0s')), state,
                                       note=m.get('note', ''), type=m.tag)
                               for m in element if m.tag in annotations)
            if element.tag == 'asset-clip':
                metadata = _xml_metadata(element)
                resource = resources.get(element.get('ref'))
                if resource is None or resource.tag != 'asset':
                    raise ValueError('Clip references an absent asset resource.')
                rep = resource.find('media-rep[@kind="original-media"]')
                if rep is None:
                    rep = resource.find('media-rep')
                reference = rep.get('src', '') if rep is not None else resource.get('src', '')
                kind = 'audio' if element.get('srcEnable') == 'audio' or resource.get('hasVideo') == '0' else 'video'
                if kind == 'video' and element.get('enabled') == '0':
                    state.unsupported.append('Disabled video clips require baking or deletion.')
                track = lanes.get(lane)
                if track is None:
                    track = {'id': metadata.get('trackId') or f'nle-lane-{lane}',
                             'name': metadata.get('trackName') or f'Lane {lane}', 'kind': kind, 'items': [],
                             'originalTrackId': metadata.get('originalTrackId', ''),
                             'generated': metadata.get('generated') == 'true', 'locked': False}
                    lanes[lane] = track
                if track['kind'] != kind:
                    state.unsupported.append('Mixed audio and video in the same FCPXML lane.')
                identity = _identity(_xml_metadata(resource), metadata)
                asset = state.match(identity, reference, _xml_time(resource.get('duration')) if resource.get('duration') else None, kind)
                if asset:
                    source_in = source - _xml_time(resource.get('start', '0s'))
                    conform = element.find('adjust-conform')
                    fit = 'contain' if conform is not None and conform.get('type') == 'fit' else 'cover'
                    gain = element.find('adjust-volume')
                    volume = 1.0
                    if gain is not None:
                        amount = gain.get('amount', '')
                        if not re.fullmatch(r'-?\d+(?:\.\d+)?dB', amount):
                            raise ValueError('Unsupported audio gain.')
                        volume = 10 ** (float(amount[:-2]) / 20)
                    if element.get('enabled') == '0' or (kind == 'video' and element.get('srcEnable') == 'video' and asset.get('hasAudio')):
                        volume = 0
                    if not 0 <= volume <= 1:
                        state.unsupported.append('Audio gain above unity is unsupported.')
                    clip = state.clip(track, metadata, asset, record, _xml_time(element.get('duration', '')), source_in, fit=fit, volume=volume)
                    clip['markers'] = [_marker(m.get('value', ''), _xml_time(m.get('start', '0s')) - source,
                                               _xml_time(m.get('duration', '0s')), state,
                                               note=m.get('note', ''), type=m.tag)
                                       for m in element if m.tag in annotations]
            visit(element, record, source, lane)
    visit(spine, Fraction(0), tc_start, 0)
    state.tracks = [track for lane, track in sorted(lanes.items(), key=lambda pair: (pair[1]['kind'] == 'audio', pair[0] if pair[1]['kind'] != 'audio' else -pair[0]))]
    if not table:
        state.warnings.append('No exported track table; empty tracks cannot be recovered from this FCPXML.')
    return state.finish(config, markers)


def _otio(text: str, state: _Import) -> dict:
    _json(text)
    try:
        timeline = otio.core.deserialize_json_from_string(text)
    except (ValueError, RuntimeError) as exc:
        raise ValueError('Malformed or unsupported OTIO JSON schema.') from exc
    if not isinstance(timeline, otio.schema.Timeline):
        raise ValueError('OTIO import requires one Timeline.')
    meta = timeline.metadata.get('renderhaus', {})
    fps = timeline.global_start_time.rate if timeline.global_start_time else float(state.rate.value)
    if abs(fps - float(state.rate.value)) > 0.00001:
        raise ValueError('Conform OTIO to the current project frame rate.')
    def seconds(time):
        return _seconds(time.to_seconds())
    def markers(item, origin):
        return [_marker(m.name, seconds(m.marked_range.start_time) - origin,
                        seconds(m.marked_range.duration), state, color=m.color) for m in item.markers]
    tc_start = seconds(timeline.global_start_time) if timeline.global_start_time else Fraction(0)
    for index, track in enumerate(timeline.tracks):
        if not isinstance(track, otio.schema.Track) or track.source_range or track.effects or not track.enabled:
            state.unsupported.append('Nested, trimmed or effected OTIO tracks require flattening.')
            continue
        metadata = track.metadata.get('renderhaus', {})
        imported = {'id': metadata.get('trackId') or f'nle-track-{index + 1}', 'name': track.name,
                    'kind': 'audio' if track.kind == otio.schema.TrackKind.Audio else 'video', 'items': [],
                    'generated': bool(metadata.get('generated', False)), 'locked': bool(metadata.get('locked', False)),
                    'originalTrackId': metadata.get('originalTrackId', '')}
        imported['markers'] = markers(track, Fraction(0))
        state.tracks.append(imported)
        fades = {}
        for position, item in enumerate(track):
            if not isinstance(item, otio.schema.Transition):
                continue
            previous = track[position - 1] if position else None
            following = track[position + 1] if position + 1 < len(track) else None
            from_black = isinstance(previous, otio.schema.Gap) and isinstance(following, otio.schema.Clip)
            to_black = isinstance(previous, otio.schema.Clip) and isinstance(following, otio.schema.Gap)
            if item.transition_type != otio.schema.TransitionTypes.SMPTE_Dissolve or not (from_black or to_black):
                state.unsupported.append('OTIO clip-to-clip or custom transitions require baking; no cut approximation applied.')
                continue
            inside, outside = seconds(item.in_offset), seconds(item.out_offset)
            gap = previous if from_black else following
            if seconds(gap.duration()) < (inside if from_black else outside):
                raise ValueError('Transition extends beyond its gap.')
            fades.setdefault(position + 1 if from_black else position - 1, {})['in' if from_black else 'out'] = (inside, outside)
        for position, item in enumerate(track):
            if isinstance(item, otio.schema.Gap):
                continue
            if isinstance(item, otio.schema.Transition):
                continue
            if not isinstance(item, otio.schema.Clip) or item.effects:
                state.unsupported.append('Nested clips and OTIO effects or retimes require baking.')
                continue
            reference = item.media_reference
            if not isinstance(reference, otio.schema.ExternalReference) or item.source_range is None:
                state.unsupported.append('Only OTIO external media clips with explicit source ranges are supported.')
                continue
            if not item.enabled:
                state.unsupported.append('Disabled OTIO clips require baking.')
            available = reference.available_range
            metadata = _identity(reference.metadata.get('renderhaus', {}), item.metadata.get('renderhaus', {}))
            asset = state.match(metadata, reference.target_url, seconds(available.duration) if available else None, imported['kind'])
            if not asset:
                continue
            source_start = seconds(available.start_time) if available else Fraction(state.rate.parse_timecode(asset.get('sourceTimecode', state.rate.timecode(0)))) / state.rate.value
            start = seconds(item.range_in_parent().start_time)
            source = seconds(item.source_range.start_time)
            length = seconds(item.source_range.duration)
            fade = fades.get(position, {})
            if 'in' in fade:
                handle = fade['in'][0]
                start -= handle
                source -= handle
                length += handle
            if 'out' in fade:
                length += fade['out'][1]
            clip = state.clip(imported, metadata, asset, start, length, source - source_start,
                              fit=metadata.get('fit', 'cover'), volume=float(metadata.get('volume', 1)))
            for direction, offsets in fade.items():
                fade_length = sum(offsets)
                if fade_length > length:
                    raise ValueError('Transition is longer than its clip.')
                clip['fadeIn' if direction == 'in' else 'fadeOut'] = float(fade_length)
            clip['markers'] = markers(item, source)
    if timeline.tracks.source_range or timeline.tracks.effects:
        state.unsupported.append('Trimmed or effected OTIO stacks require flattening.')
    duration = state.frames(seconds(timeline.duration()))
    config = {'timecode': state.rate.timecode(state.frames(tc_start)), 'durationInFrames': duration,
              'width': int(meta.get('width', state.current['renderConfig'].get('width', 1920))),
              'height': int(meta.get('height', state.current['renderConfig'].get('height', 1080)))}
    return state.finish(config, markers(timeline.tracks, Fraction(0)))


def import_timeline(interchange_text: str, current: dict, format: str) -> dict:
    """Return a complete replacement assembly or a blocked report, without writes or media I/O."""
    _bounded(interchange_text, 'interchange_text')
    state = _Import.create(current)
    if format == 'fcpxml':
        return _fcpxml(interchange_text, state)
    if format == 'otio':
        return _otio(interchange_text, state)
    raise ValueError('format must be fcpxml or otio.')


def import_arguments(interchange_text: str, timeline_json: str, format: str) -> dict:
    return import_timeline(interchange_text, _json(timeline_json), format)
