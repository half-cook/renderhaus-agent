"""Bounded template plans shared by the local compositor and Remotion composition."""
from __future__ import annotations

import copy
import math
import re
import struct
from typing import BinaryIO, TypedDict
import wave

from PIL import ImageFont

from providers.remotion.text import FONT_FILES

from providers.remotion.captions import srt_captions


class Rect(TypedDict):
    x: float
    y: float
    width: float
    height: float


class Word(TypedDict):
    text: str
    start: float
    end: float


SAFE_ZONES = {
    '9:16': (.08, .12, .76, .66),
    '1:1': (.07, .07, .86, .84),
    '4:5': (.08, .08, .80, .76),
    '16:9': (.05, .07, .90, .86),
}
END_SCREEN_ZONES = [
    {'x': .44, 'y': .15, 'width': .50, 'height': .28},
    {'x': .44, 'y': .55, 'width': .50, 'height': .28},
    {'x': .05, 'y': .36, 'width': .25, 'height': .44},
]
NAMES = ('podcast-audiogram', 'youtube-intro-sting', 'youtube-end-screen')
FIELDS = {'name', 'duration_seconds', 'words', 'captions_srt', 'amplitudes', 'waveform', 'bars',
          'smoothing', 'speaker_name', 'show_name', 'cover_url', 'logo_url', 'background_color',
          'accent_color', 'text_color', 'remove_fillers', 'correction_terms'}


def finite(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be a finite number in {minimum}..{maximum}.')
    return float(value)


def _text(value, name, maximum=96):
    if not isinstance(value, str) or len(value) > maximum or '\x00' in value:
        raise ValueError(f'{name} must be text of at most {maximum} characters.')
    return value


def group_captions(raw_words, *, duration, remove_fillers=False, correction_terms=()):
    finite(duration, 'duration', .01, 90)
    if not isinstance(remove_fillers, bool):
        raise ValueError('remove_fillers must be boolean.')
    if not isinstance(raw_words, list) or not 1 <= len(raw_words) <= 2000:
        raise ValueError('words requires 1..2000 verbatim timed words.')
    if not isinstance(correction_terms, (list, tuple)) or len(correction_terms) > 100:
        raise ValueError('correction_terms requires at most 100 names/jargon terms.')
    terms = {_text(term, 'correction_terms', 80).casefold() for term in correction_terms}
    words: list[Word] = []
    flags = []
    last = 0
    for index, raw in enumerate(raw_words):
        if not isinstance(raw, dict) or set(raw) != {'text', 'start', 'end'}:
            raise ValueError('Each word requires exactly text, start and end.')
        text = _text(raw['text'], 'word.text', 80)
        if not text.strip():
            raise ValueError('word.text cannot be empty.')
        start = finite(raw['start'], 'word.start', 0, duration)
        end = finite(raw['end'], 'word.end', 0, duration)
        if start < last or end <= start:
            raise ValueError('Words must be ordered, non-overlapping and complete inside the clip.')
        last = end
        token = text.strip('.,!?;:"').casefold()
        if token in terms or (index > 0 and text[:1].isupper()) or text.isupper():
            flags.append({'word_index': index, 'text': text})
        if remove_fillers and token in {'um', 'uh', 'erm', 'hmm'}:
            continue
        words.append({'text': text, 'start': start, 'end': end})
    if not words:
        raise ValueError('Filler removal leaves no caption words.')
    chunks = [words[index:index + 6] for index in range(0, len(words), 6)]
    if len(chunks) > 1 and len(chunks[-1]) == 1:
        chunks[-1].insert(0, chunks[-2].pop())
    captions = [{'text': ' '.join(word['text'] for word in chunk),
                 'start': chunk[0]['start'], 'end': chunk[-1]['end'], 'words': chunk}
                for chunk in chunks]
    return captions, flags


def layout_for_aspect(aspect_ratio: str) -> dict[str, Rect]:
    if aspect_ratio not in SAFE_ZONES:
        raise ValueError('Templates support 9:16, 1:1, 4:5 and 16:9.')
    x, y, width, height = SAFE_ZONES[aspect_ratio]

    def box(left, top, w, h):
        return {'x': x + left * width, 'y': y + top * height, 'width': w * width, 'height': h * height}

    return {'safe': box(0, 0, 1, 1), 'art': box(.23, .02, .54, .30),
            'identity': box(.02, .35, .96, .12), 'waveform': box(.02, .50, .96, .16),
            'captions': box(.02, .70, .96, .20), 'progress': box(.02, .96, .96, .02)}


def progress_at(frame: int, frames: int) -> float:
    return min(1, max(0, frame / max(1, frames - 1)))


def fitted_font_size(lines: list[str], box: Rect, width: int, height: int, maximum: float) -> int:
    minimum = max(1, math.floor(min(width, height) * .018))
    for size in range(max(minimum, math.floor(maximum)), minimum - 1, -1):
        font = ImageFont.truetype(str(FONT_FILES['dejavu-sans-bold']), size)
        if (all(font.getlength(line) <= box['width'] * width for line in lines)
                and len(lines) * size * 1.35 <= box['height'] * height):
            return size
    raise ValueError('text_overflow: caption or identity cannot fit above the minimum readable font size. Use shorter groups or corrected text.')


def pcm_amplitudes(source: BinaryIO, *, duration: float, fps: int, smoothing: float = .65) -> list[float]:
    finite(duration, 'duration', .01, 90)
    finite(fps, 'fps', 12, 60)
    finite(smoothing, 'smoothing', 0, .95)
    if not isinstance(fps, int):
        raise ValueError('Envelope fps must be an integer.')
    amplitudes = []
    previous = 0
    with wave.open(source, 'rb') as pcm:
        rate, channels = pcm.getframerate(), pcm.getnchannels()
        if pcm.getsampwidth() != 2 or channels not in {1, 2} or not 8000 <= rate <= 192000:
            raise ValueError('Amplitude analysis requires bounded 16-bit mono/stereo PCM WAV.')
        if abs(pcm.getnframes() / rate - duration) > max(1 / fps, .02):
            raise ValueError('PCM duration must match the selected clip, without padding missing audio.')
        for frame in range(math.ceil(duration * fps - 1e-9)):
            count = min(pcm.getnframes(), round((frame + 1) * rate / fps)) - pcm.tell()
            data = pcm.readframes(max(0, count))
            samples = struct.unpack('<' + 'h' * (len(data) // 2), data)
            energy = math.sqrt(sum((sample / 32768) ** 2 for sample in samples) / len(samples)) if samples else 0
            previous = smoothing * previous + (1 - smoothing) * energy
            amplitudes.append(round(previous, 6))
    return amplitudes


def template_plan(raw: dict, *, aspect_ratio: str, fps: float, width: int, height: int) -> dict:
    if not isinstance(raw, dict) or set(raw) - FIELDS:
        raise ValueError('template contains unsupported fields.')
    name = raw.get('name')
    if name not in NAMES:
        raise ValueError('Unknown template name.')
    duration = finite(raw.get('duration_seconds'), 'template.duration_seconds', .1, 90)
    finite(fps, 'template fps', 12, 60)
    if int(fps) != fps:
        raise ValueError('Template fps must be an integer.')
    layout = layout_for_aspect(aspect_ratio)
    for field in ('cover_url', 'logo_url'):
        if field in raw and (not _text(raw[field], field, 8192).strip() or name == 'podcast-audiogram' and field == 'logo_url'
                            or name != 'podcast-audiogram' and field == 'cover_url'):
            raise ValueError('Use cover_url for audiograms and logo_url for channel templates.')
    for field, default in (('background_color', '#101820'), ('accent_color', '#f5b642'), ('text_color', '#ffffff')):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', raw.get(field, default)):
            raise ValueError(f'{field} requires an RGB hex color.')
    bars = raw.get('bars', 32)
    if isinstance(bars, bool) or not isinstance(bars, int) or not 16 <= bars <= 64:
        raise ValueError('bars requires an integer in 16..64.')
    finite(raw.get('smoothing', .65), 'smoothing', 0, .95)
    if raw.get('waveform', 'bars') not in {'bars', 'line'}:
        raise ValueError('waveform must be bars or line.')
    captions, flags, warnings = [], [], []
    amplitudes = raw.get('amplitudes', [])
    if name == 'podcast-audiogram':
        if bool(raw.get('words')) == bool(raw.get('captions_srt')):
            raise ValueError('Audiograms require words or inline captions_srt, not both.')
        if raw.get('words'):
            captions, flags = group_captions(raw['words'], duration=duration,
                remove_fillers=raw.get('remove_fillers', False), correction_terms=raw.get('correction_terms', []))
        else:
            if raw.get('remove_fillers'):
                raise ValueError('Filler removal requires measured word timings.')
            cues = srt_captions(raw['captions_srt'], None)
            for cue in cues or []:
                if not cue['text'].strip():
                    raise ValueError('SRT captions require non-empty visible text.')
                end = cue['start_seconds'] + cue['duration_seconds']
                if end > duration:
                    raise ValueError('SRT captions must fit inside the selected clip.')
                captions.append({'text': cue['text'], 'start': cue['start_seconds'], 'end': end, 'words': []})
            if any(left['end'] > right['start'] for left, right in zip(captions, captions[1:])):
                raise ValueError('SRT cues must be ordered and non-overlapping.')
            warnings.append('SRT uses supplied cue timing; active-word highlighting requires measured word timings.')
        if not isinstance(amplitudes, list) or len(amplitudes) != math.ceil(duration * fps - 1e-9):
            raise ValueError('amplitudes requires one measured value per output frame.')
        for amplitude in amplitudes:
            finite(amplitude, 'amplitude', 0, 1)
    else:
        if any(field in raw for field in ('words', 'captions_srt', 'amplitudes', 'remove_fillers', 'correction_terms')):
            raise ValueError('Channel templates do not accept audiogram data.')
        if name == 'youtube-intro-sting':
            if not 3 <= duration <= 5:
                raise ValueError('Channel intro stings require 3..5 seconds.')
            layout.update(art={'x': .38, 'y': .18, 'width': .24, 'height': .36},
                          identity={'x': .12, 'y': .60, 'width': .76, 'height': .18})
        else:
            if aspect_ratio != '16:9' or duration != 20:
                raise ValueError('YouTube end screens require a 20-second 16:9 plate.')
            layout.update(art={'x': .08, 'y': .20, 'width': .16, 'height': .12},
                          identity={'x': .05, 'y': .06, 'width': .35, 'height': .12},
                          captions={'x': .05, 'y': .84, 'width': .34, 'height': .08})
            warnings.append('UNVERIFIED native element geometry. Reservations are Renderhaus layout choices; position native elements in YouTube Studio. Append to an upload of at least 25 seconds.')
    identity = [text for text in (raw.get('show_name', ''), raw.get('speaker_name', '')) if text]
    for text in identity:
        _text(text, 'identity')
    typography = {'identity': fitted_font_size(identity, layout['identity'], width, height, min(width, height) * .052),
                  'captions': [fitted_font_size(caption['text'].split('\n'), layout['captions'], width, height,
                                               min(width, height) * .07) for caption in captions]}
    return {'name': name, 'duration_seconds': duration, 'fps': int(fps), 'width': width, 'height': height,
            'aspect_ratio': aspect_ratio, 'layout': layout, 'captions': captions, 'correction_flags': flags,
            'typography': typography,
            'amplitudes': copy.deepcopy(amplitudes), 'waveform': raw.get('waveform', 'bars'), 'bars': bars,
            'smoothing': raw.get('smoothing', .65), 'speaker_name': _text(raw.get('speaker_name', ''), 'speaker_name', 64),
            'show_name': _text(raw.get('show_name', ''), 'show_name'),
            'background_color': raw.get('background_color', '#101820'),
            'accent_color': raw.get('accent_color', '#f5b642'), 'text_color': raw.get('text_color', '#ffffff'),
            'reserved_zones': copy.deepcopy(END_SCREEN_ZONES) if name == 'youtube-end-screen' else [],
            'warnings': warnings, 'request': {key: copy.deepcopy(value) for key, value in raw.items()
                                            if key not in {'cover_url', 'logo_url'}}}


def validate_plan(plan: dict, config: dict):
    canonical = template_plan(plan['request'], aspect_ratio=plan['aspect_ratio'], fps=config['fps'],
                              width=config['width'], height=config['height'])
    if plan != canonical or config['durationInFrames'] != math.ceil(plan['duration_seconds'] * config['fps'] - 1e-9):
        raise ValueError('Template plan must match its canonical geometry, timing and renderConfig.')


def validate_template_arguments(arguments: dict):
    from providers.contracts import validate_remotion_timeline_arguments
    from providers.remotion.api import choose_canvas

    raw = arguments['template']
    fps = arguments.get('fps') or 30
    aspect = arguments.get('aspect_ratio', '9:16')
    width, height = choose_canvas(aspect, [], arguments.get('output_resolution', 'source'))
    template_plan(raw, aspect_ratio=aspect, fps=fps, width=width, height=height)
    if any(arguments.get(field) for field in ('visuals', 'text_overlays', 'subtitles', 'subtitles_srt')):
        raise ValueError('Named templates own their safe layout. Use visuals=[] and template caption/art fields.')
    validate_remotion_timeline_arguments({'audio_tracks': arguments.get('audio_tracks')}, allow_empty_visuals=True)
    audio = arguments.get('audio_tracks') or []
    if len(audio) > 1 or raw['name'] == 'podcast-audiogram' and len(audio) != 1:
        raise ValueError('An audiogram requires exactly one source audio track; channel templates accept at most one.')
    for track in audio:
        if (track.get('start_seconds', 0) != 0 or track['duration_seconds'] != raw['duration_seconds']
                or track.get('volume', 1) != 1 or track.get('fade_in_seconds', 0) != 0
                or track.get('fade_out_seconds', 0) != 0):
            raise ValueError('Template source audio must span the selected clip at unity gain, without loudness changes or fades before QC.')


def template_document(title: str, plan: dict, audio_tracks: list[dict], art_url: str | None):
    duration = plan['duration_seconds']
    assets, tracks = [], []
    if art_url:
        box = plan['layout']['art']
        box = {key: value * (plan['width'] if key in {'x', 'width'} else plan['height']) for key, value in box.items()}
        assets.append({'id': 'template-art', 'kind': 'image', 'url': art_url})
        tracks.append({'id': 'template-art', 'kind': 'overlay', 'items': [{
            'id': 'template-art', 'type': 'clip', 'assetId': 'template-art', 'start': 0,
            'duration': duration, 'fit': 'contain', 'box': box, 'volume': 0,
            **({'motion': 'zoom_out', 'fadeIn': .35, 'fadeOut': .2}
               if plan['name'] == 'youtube-intro-sting' else {})}]})
    for track in audio_tracks:
        assets.append({'id': 'template-audio', 'kind': 'audio', 'url': track.get('url') or track['output_path']})
        tracks.append({'id': 'template-audio', 'kind': 'audio', 'items': [{
            'id': 'template-audio', 'type': 'clip', 'assetId': 'template-audio', 'start': 0,
            'duration': duration, 'sourceIn': track.get('source_in_seconds', 0), 'volume': 1,
            'fadeIn': 0, 'fadeOut': 0}]})
    return {'id': 'agent-render', 'name': (title or 'Renderhaus video')[:160], 'assets': assets, 'tracks': tracks}


def build_template_props(title: str, raw: dict, *, audio_tracks: list[dict], aspect_ratio: str,
                         fps: float, output_resolution: str, video_bitrate: int | None):
    from providers.remotion.api import choose_canvas

    width, height = choose_canvas(aspect_ratio, [], output_resolution)
    plan = template_plan(raw, aspect_ratio=aspect_ratio, fps=fps, width=width, height=height)
    return {'template': plan,
            'document': template_document(title, plan, audio_tracks, raw.get('cover_url') or raw.get('logo_url')),
            'renderConfig': {'fps': fps, 'width': width, 'height': height,
                'durationInFrames': math.ceil(plan['duration_seconds'] * fps - 1e-9),
                'videoBitrate': video_bitrate, 'crf': None if video_bitrate else 18,
                'resolution': {'width': width, 'height': height, 'source_resolution': None,
                               'upscaled': False, 'warnings': []}}}


def validate_template_document(props: dict):
    plan, config, document = props['template'], props['renderConfig'], props['document']
    validate_plan(plan, config)
    assets = {asset['id']: asset for asset in document['assets']}
    if len(assets) != len(document['assets']) or set(assets) - {'template-art', 'template-audio'}:
        raise ValueError('Template assets must contain only optional art and source audio.')
    audio = []
    for track in document['tracks']:
        if track['id'] == 'template-audio':
            for item in track['items']:
                audio.append({'url': assets['template-audio']['url'], 'duration_seconds': item['duration'],
                              'source_in_seconds': item.get('sourceIn', 0)})
    art_url = assets.get('template-art', {}).get('url')
    arguments = {'template': plan['request'], 'audio_tracks': audio, 'aspect_ratio': plan['aspect_ratio'], 'fps': config['fps']}
    validate_template_arguments(arguments)
    if document != template_document(document['name'], plan, audio, art_url):
        raise ValueError('Template document must preserve its canonical layout and source audio.')


def template_schema() -> dict:
    word = {'type': 'object', 'properties': {'text': {'type': 'string'}, 'start': {'type': 'number'},
                                          'end': {'type': 'number'}}, 'required': ['text', 'start', 'end']}
    return {'type': 'object', 'properties': {
        **{field: {'type': 'string'} for field in ('speaker_name', 'show_name', 'cover_url', 'logo_url',
            'background_color', 'accent_color', 'text_color', 'captions_srt')},
        'name': {'type': 'string', 'description': 'Allowed values: ' + ', '.join(NAMES) + '.'},
        'duration_seconds': {'type': 'number', 'description': 'Audiogram .1..90, intro 3..5, end screen exactly 20 seconds.'},
        'words': {'type': 'array', 'items': word, 'description': 'Verbatim measured words relative to the selected audio clip. 1..2000 words; no fabricated timings.'},
        'amplitudes': {'type': 'array', 'items': {'type': 'number'}, 'description': 'One measured amplitude in 0..1 per frame from audio_envelope. Already smoothed; never normalize the source audio.'},
        'waveform': {'type': 'string', 'description': 'Allowed values: bars, line.'},
        'bars': {'type': 'integer', 'description': '16..64, default 32.'},
        'smoothing': {'type': 'number', 'description': 'Analysis provenance in 0..0.95, default .65; envelope is already smoothed.'},
        'remove_fillers': {'type': 'boolean', 'description': 'Only true on explicit request. Removes caption um/uh/erm/hmm; never edits source audio.'},
        'correction_terms': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Up to 100 names/jargon to flag for transcript review.'},
    }, 'required': ['name', 'duration_seconds'], 'description': 'Bounded named template, no JSX or arbitrary rendering code. Use visuals=[] and exactly one unity-gain audio track for an audiogram.'}
