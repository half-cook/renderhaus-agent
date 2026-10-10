"""Bounded fictional message tables and their deterministic frame/layout plan."""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import unicodedata
from typing import Any


MAX_MESSAGES = 40
MAX_TEXT = 500
MAX_INPUT_BYTES = 256 * 1024
MESSAGE_FIELDS = {'from', 'text', 'typingMs', 'delayMs', 'status', 'reaction'}
REACTIONS = {'', '❤️', '👍', '😂', '‼️', '❓'}
THEMES = {
    'generic': {'background': '#f3f0e9', 'sent': '#635d86', 'received': '#ded9ce', 'text': '#242332'},
    'slate': {'background': '#f5f5f7', 'sent': '#426ac3', 'received': '#e2e3e8', 'text': '#242332'},
    'moss': {'background': '#eef3ef', 'sent': '#477965', 'received': '#dce6df', 'text': '#242332'},
}
_THEME_ALIASES = {'imessage-style': 'slate', 'whatsapp-style': 'moss'}
_PHONE = re.compile(r'(?<!\w)(?:\+?\d[\d\s().-]{5,}\d)(?!\w)')
_MARKUP = re.compile(r'<\s*/?\s*[A-Za-z][^>]*>')
_IDENTITIES = re.compile(r'\b(?:Apple|Google|Microsoft|Amazon|Meta|OpenAI|Tesla|Elon Musk|'
                         r'Taylor Swift|Donald Trump|Joe Biden|Beyonc[eé])\b', re.I)
_IMPERSONATION = re.compile(r'\b(?:this is|i am|i\x27m|official|support|verified|ceo)\b', re.I)


def _number(value: Any, field: str, low: float, high: float, *, csv_value: bool = False) -> float:
    if csv_value and isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            raise ValueError(f'{field} must be numeric.') from None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high or not math.isfinite(value):
        raise ValueError(f'{field} must be a finite number from {low:g} to {high:g}.')
    return value


def _safety_view(value: str) -> str:
    """Ignore invisible format characters for safety checks, preserving supplied copy."""
    return ''.join(char for char in value if unicodedata.category(char) != 'Cf')


def _text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f'{field} must contain 1-{maximum} characters of nonempty verbatim text.')
    if _MARKUP.search(value) or any(unicodedata.category(c) == 'Cs' or
                                  (unicodedata.category(c) == 'Cc' and c not in '\n\t') or
                                  c in '\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069' for c in value):
        raise ValueError(f'{field} contains markup or unsafe control characters. Supply plain text.')
    if any(sum(c.isdecimal() for c in match.group()) >= 7 for match in _PHONE.finditer(_safety_view(value))):
        raise ValueError(f'{field} contains a real-looking phone number. Use a fictional label instead.')
    for cluster in graphemes(value):
        if '\u200d' not in cluster:
            continue
        parts = cluster.split('\u200d')
        if len(parts) > 4 or any(not part or not (0x1F000 <= ord(part[0]) <= 0x1FAFF or
                                                0x2600 <= ord(part[0]) <= 0x27FF) for part in parts):
            raise ValueError(f'{field} contains an unsupported joining sequence. Supply approved plain text or a supported emoji.')
    return value


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON field {key}.')
        result[key] = value
    return result


def message_rows(value: Any) -> tuple[list[dict], bool]:
    csv_value = False
    if isinstance(value, str):
        if len(value.encode('utf-8')) > MAX_INPUT_BYTES:
            raise ValueError('Messages input exceeds 256 KiB.')
        if value.lstrip().startswith('['):
            try:
                value = json.loads(value, object_pairs_hook=_json_pairs)
            except json.JSONDecodeError:
                raise ValueError('Messages JSON must be an array.') from None
        else:
            csv_value = True
            try:
                reader = csv.DictReader(io.StringIO(value), strict=True)
                fields = reader.fieldnames or []
                if len(set(fields)) != len(fields) or set(fields) - MESSAGE_FIELDS or not {'from', 'text'} <= set(fields):
                    raise ValueError('CSV needs unique from,text columns and only supported message columns.')
                value = []
                for row in reader:
                    if None in row or any(cell is None for cell in row.values()):
                        raise ValueError('CSV row has missing or extra cells.')
                    value.append(row)
                    if len(value) > MAX_MESSAGES:
                        break
            except csv.Error:
                raise ValueError('Malformed CSV quoting.') from None
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_MESSAGES:
        raise ValueError('Messages must contain 1-40 records.')
    return value, csv_value


def normalize(payload: dict) -> dict:
    allowed = {'messages', 'contact', 'theme', 'aspect', 'dramatization', 'music_ref',
               'send_sound_ref', 'receive_sound_ref', 'holdMs', 'platformTargetMs', 'sfx', 'warnings'}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise ValueError('Chat payload contains unsupported fields.')
    rows, csv_value = message_rows(payload.get('messages'))
    messages = []
    warnings = payload.get('warnings', [])
    if not isinstance(warnings, list) or len(warnings) > 50 or any(not isinstance(w, str) or len(w) > 300 for w in warnings):
        raise ValueError('Warnings must be bounded text.')
    warnings = list(warnings)
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) - MESSAGE_FIELDS:
            raise ValueError(f'Message {index} contains unsupported columns.')
        sender = row.get('from')
        if not isinstance(sender, str) or sender not in {'me', 'them'}:
            raise ValueError(f'Message {index} from must be me or them.')
        text = _text(row.get('text'), f'Message {index} text', MAX_TEXT)
        typing = row.get('typingMs')
        missing_typing = typing is None or typing == ''
        typing = min(1500, max(700, len(text) * 20)) if missing_typing and sender == 'them' else 0 if missing_typing else typing
        typing = _number(typing, 'typingMs', 0, 10000, csv_value=csv_value)
        delay = row.get('delayMs')
        delay = _number(600 if delay is None or delay == '' else delay, 'delayMs', 0, 30000, csv_value=csv_value)
        status, reaction = row.get('status', ''), row.get('reaction', '')
        if not isinstance(status, str) or status not in {'', 'sent', 'delivered', 'read'}:
            raise ValueError('status must be empty, sent, delivered or read.')
        if not isinstance(reaction, str) or reaction not in REACTIONS:
            raise ValueError('reaction must be empty or an allow-listed emoji.')
        if sender == 'me' and typing != 0 or sender == 'them' and status:
            raise ValueError('Typing is received-only; receipts are sent-only.')
        if _IDENTITIES.search(_safety_view(text)) and _IMPERSONATION.search(_safety_view(text)):
            warnings.append(f'Possible impersonation in message {index}; review fiction before rendering.')
        messages.append({'from': sender, 'text': text, 'typingMs': typing,
                         'delayMs': delay, 'status': status, 'reaction': reaction})
    contact = payload.get('contact', {'name': 'Friend', 'avatar': 'initials'})
    if isinstance(contact, str):
        contact = {'name': contact}
    if not isinstance(contact, dict) or set(contact) - {'name', 'avatar'}:
        raise ValueError('contact accepts fictional name and initials/placeholder avatar only.')
    name = _text(contact.get('name', 'Friend'), 'contact name', 40)
    avatar = contact.get('avatar', 'initials')
    if not isinstance(avatar, str) or avatar not in {'initials', 'placeholder'}:
        raise ValueError('Avatars must be generated initials or placeholder; photos are refused.')
    if _IDENTITIES.search(_safety_view(name)):
        warnings.append('Possible contact impersonation; use an invented fictional contact.')
    theme = payload.get('theme', 'generic')
    if not isinstance(theme, str):
        raise ValueError('theme must be a named preset.')
    theme = _THEME_ALIASES.get(theme.lower(), theme.lower())
    if theme not in THEMES:
        raise ValueError('Unknown theme. The enabled default is generic.')
    if theme != 'generic' and os.getenv('CHAT_STORY_LOOKALIKE_THEMES', 'off') != 'on':
        warnings.append('Requested lookalike appearance is not enabled; using generic. Legal sign-off is required before enabling it.')
        theme = 'generic'
    aspect = payload.get('aspect', '9:16')
    if not isinstance(aspect, str) or aspect not in {'9:16', '1:1', '4:5'}:
        raise ValueError('Chat aspect must be 9:16, 1:1 or 4:5.')
    result = {'messages': messages, 'contact': {'name': name, 'avatar': avatar}, 'theme': theme,
              'aspect': aspect, 'warnings': list(dict.fromkeys(warnings)),
              'holdMs': _number(payload.get('holdMs', 2000), 'holdMs', 500, 10000),
              'platformTargetMs': _number(payload.get('platformTargetMs', 60000), 'platformTargetMs', 1000, 600000)}
    for key, default in (('dramatization', False), ('sfx', True)):
        if type(payload.get(key, default)) is not bool:
            raise ValueError(f'{key} must be boolean.')
        result[key] = payload.get(key, default)
    for key in ('music_ref', 'send_sound_ref', 'receive_sound_ref'):
        value = payload.get(key, '')
        if not isinstance(value, str) or len(value) > 200 or (value and
                (value.startswith(('-', '~')) or re.search(r'[:\\\x00-\x1f]', value) or '..' in value.split('/'))):
            raise ValueError(f'{key} must be a safe local supplied audio reference.')
        result[key] = value
    return result


def batch_rows(source: str) -> list[dict]:
    """Load a bounded table of scripts, preserving invalid payloads for row isolation."""
    if not isinstance(source, str) or len(source.encode('utf-8')) > 2 * 1024 * 1024:
        raise ValueError('Batch input exceeds 2 MiB.')
    if source.lstrip().startswith('['):
        try:
            rows = json.loads(source, object_pairs_hook=_json_pairs)
        except json.JSONDecodeError:
            raise ValueError('Malformed batch JSON.') from None
    else:
        try:
            reader = csv.DictReader(io.StringIO(source), strict=True)
            fields = reader.fieldnames or []
            allowed = {'variant_key', 'messages', 'contact', 'theme', 'aspect', 'music_ref'}
            if len(set(fields)) != len(fields) or set(fields) - allowed or not {'variant_key', 'messages'} <= set(fields):
                raise ValueError('Batch CSV needs unique variant_key/messages columns and supported payload options.')
            rows = []
            for row in reader:
                if None in row or any(v is None for v in row.values()):
                    raise ValueError('Batch CSV has extra or missing cells.')
                rows.append({'variant_key': row['variant_key'],
                             'chat_story': {key: value for key, value in row.items() if key != 'variant_key' and value != ''}})
                if len(rows) > 50:
                    break
        except csv.Error:
            raise ValueError('Malformed batch CSV quoting.') from None
    if not isinstance(rows, list) or not 1 <= len(rows) <= 50:
        raise ValueError('Batch input must contain 1-50 script rows.')
    return rows


def graphemes(text: str) -> list[str]:
    """Keep combining marks, emoji modifiers, joiners and paired flags together."""
    clusters = []
    for char in text:
        code = ord(char)
        regional = 0x1F1E6 <= code <= 0x1F1FF
        previous_regional = clusters and all(0x1F1E6 <= ord(c) <= 0x1F1FF for c in clusters[-1])
        attach = (unicodedata.category(char) in {'Mn', 'Mc', 'Me'} or char == '\u200d' or
                  0x1F3FB <= code <= 0x1F3FF or 0xE0020 <= code <= 0xE007F or
                  clusters and clusters[-1].endswith('\u200d') or
                  regional and previous_regional and len(clusters[-1]) == 1)
        if clusters and attach and char != '\n' and clusters[-1] != '\n':
            clusters[-1] += char
        else:
            clusters.append(char)
    return clusters


def _lines(text: str, columns: int) -> list[str]:
    lines, line = [], []
    for char in graphemes(text):
        if char == '\n':
            lines.append(''.join(line))
            line = []
            continue
        line.append(char)
        if len(line) > columns:
            boundary = max((i + 1 for i, cluster in enumerate(line[:columns]) if cluster.isspace()), default=columns)
            lines.append(''.join(line[:boundary]))
            line = line[boundary:]
    return [*lines, ''.join(line)]


def plan(payload: dict, fps: int = 30) -> dict:
    payload = normalize(payload)
    if type(fps) is not int or not 1 <= fps <= 60:
        raise ValueError('Chat fps must be an integer from 1 to 60.')
    from providers.remotion.api import ASPECT_SIZES

    width, height = ASPECT_SIZES[payload['aspect']]
    font, line_height, padding = 38, 48, 22
    safe_top = 270 if payload['aspect'] == '9:16' else 190
    safe_bottom = 360 if payload['aspect'] == '9:16' else 130
    floor, max_width = height - safe_bottom, math.floor(width * .74)
    # The emoji font advances up to 1.25 em. Use that bound for every cluster,
    # including wide Latin capitals, so a line never crosses its bubble padding.
    columns = math.floor((max_width - 2 * padding) / (font * 1.25))
    contact_font = min(34, math.floor((width - 96) / (len(graphemes(payload['contact']['name'])) * 1.25)))
    if contact_font < 20:
        raise ValueError('Contact name exceeds the readable header; supply a shorter approved fictional name.')
    frame = lambda ms: math.ceil(ms * fps / 1000 - 1e-9)
    bubbles, cues, scroll = [], [], []
    cursor, y, previous_offset = 0, safe_top + 24, 0
    for index, message in enumerate(payload['messages']):
        gap_start = cursor
        cursor += frame(message['delayMs'])
        typing_start = cursor
        cursor += frame(message['typingMs'])
        start = cursor
        lines = _lines(message['text'], columns)
        bubble_height = len(lines) * line_height + padding * 2
        reserved = 52
        if bubble_height + reserved > floor - safe_top:
            raise ValueError(f'Message {index} exceeds the readable safe band; supply a shorter approved message.')
        offset = max(previous_offset, y + bubble_height + reserved - floor)
        if offset != previous_offset:
            scroll.append({'frame': gap_start, 'endFrame': start, 'offset': offset})
        tail = index == len(payload['messages']) - 1 or payload['messages'][index + 1]['from'] != message['from']
        bubbles.append({'index': index, **message, 'lines': lines, 'typingStartFrame': typing_start,
                        'startFrame': start, 'reactionFrame': start + frame(400) if message['reaction'] else None,
                        'receiptFrame': start + frame(300) if message['status'] and tail else None,
                        'x': width - 64 - max_width if message['from'] == 'me' else 64,
                        'y': y, 'width': max_width, 'height': bubble_height, 'scrollOffset': offset, 'tail': tail})
        cues.append({'frame': start, 'kind': 'send' if message['from'] == 'me' else 'receive'})
        previous_offset = offset
        y += bubble_height + reserved
        cursor += max(1, frame(250))
    duration = max(cursor + frame(payload['holdMs']), bubbles[-1]['startFrame'] + frame(400) + 1)
    if duration / fps > 600:
        raise ValueError('Chat duration exceeds the 600-second worker limit.')
    warnings = list(payload['warnings'])
    if duration * 1000 / fps > payload['platformTargetMs']:
        warnings.append(f'Computed duration {duration / fps:.2f}s exceeds platform target {payload["platformTargetMs"] / 1000:g}s.')
    return {'fps': fps, 'width': width, 'height': height, 'durationInFrames': duration,
            'durationSeconds': duration / fps, 'fontSize': font, 'contactFontSize': contact_font,
            'lineHeight': line_height, 'padding': padding,
            'safeTop': safe_top, 'safeBottom': safe_bottom, 'bubbles': bubbles, 'scrollEvents': scroll,
            'sfxCues': cues, 'warnings': warnings,
            'reviewFrames': [min(duration - 1, bubbles[0]['startFrame'] + frame(250)), duration // 2, duration - 1]}


def music_tracks(payload: dict, timing: dict) -> list[dict]:
    if not payload['music_ref']:
        return []
    end = timing['durationInFrames'] / timing['fps']
    intervals = [(cue['frame'] / timing['fps'], min(end, (cue['frame'] + math.ceil(.24 * timing['fps'])) / timing['fps']))
                 for cue in timing['sfxCues']] if payload['sfx'] else []
    points = sorted({0.0, end, *(point for interval in intervals for point in interval)})
    return [{'url': payload['music_ref'], 'start_seconds': a, 'source_in_seconds': a,
             'duration_seconds': b - a, 'volume': .07 if any(x <= a < y for x, y in intervals) else .18}
            for a, b in zip(points, points[1:]) if b > a]


def build_props(title: str, payload: dict, *, fps: int = 30, audio_tracks: list[dict] | None = None) -> dict:
    from providers.remotion.api import build_timeline_props

    payload = normalize(payload)
    timing = plan(payload, fps)
    audio = [*music_tracks(payload, timing), *(audio_tracks or [])]
    for cue in timing['sfxCues']:
        ref = payload['send_sound_ref' if cue['kind'] == 'send' else 'receive_sound_ref']
        if ref and payload['sfx']:
            audio.append({'url': ref, 'start_seconds': cue['frame'] / fps, 'duration_seconds': .12, 'volume': .5})
    # Reuse the normal audio contract and asset compiler, then replace its inert visual.
    props = build_timeline_props(title, [{'kind': 'image', 'url': 'chat-placeholder.png',
                                         'duration_seconds': timing['durationInFrames'] / fps}],
                                 audio_tracks=audio, aspect_ratio=payload['aspect'], fps=fps, measure_local=False)
    document = props['document']
    visual_assets = {asset['id'] for asset in document['assets'] if asset['kind'] != 'audio'}
    document['assets'] = [asset for asset in document['assets'] if asset['id'] not in visual_assets]
    by_url, replacements, unique_assets = {}, {}, []
    for asset in document['assets']:
        if asset['url'] in by_url:
            replacements[asset['id']] = by_url[asset['url']]
        else:
            by_url[asset['url']] = asset['id']
            unique_assets.append(asset)
    document['assets'] = unique_assets
    document['tracks'] = [track for track in document['tracks'] if track['kind'] == 'audio']
    for track in document['tracks']:
        for item in track['items']:
            item['assetId'] = replacements.get(item['assetId'], item['assetId'])
    document['chatStory'] = {'payload': payload, 'plan': timing}
    resolution = props['renderConfig']['resolution']
    resolution['warnings'] = list(dict.fromkeys([*resolution.get('warnings', []), *timing['warnings']]))
    return props


def validate_story_document(props: dict) -> None:
    story = props['document']['chatStory']
    if not isinstance(story, dict) or set(story) != {'payload', 'plan'}:
        raise ValueError('Chat document requires payload and its deterministic plan.')
    config = props['renderConfig']
    expected = plan(story['payload'], config['fps'])
    if normalize(story['payload']) != story['payload'] or expected != story['plan']:
        raise ValueError('Chat payload/plan changed; recompute from the validated message table.')
    if any(config[key] != expected[key] for key in ('fps', 'width', 'height', 'durationInFrames')):
        raise ValueError('Chat canvas and duration must match the deterministic plan.')
    if any(track['kind'] != 'audio' for track in props['document']['tracks']):
        raise ValueError('Chat documents cannot contain arbitrary visual tracks.')


def qc_allowances(story: dict) -> dict:
    """Declare intentional reading holds and pop-only silent gaps, never black frames."""
    timing, payload = story['plan'], story['payload']
    fps, end = timing['fps'], timing['durationSeconds']
    windows = []
    for bubble in timing['bubbles']:
        settled = (bubble['startFrame'] + max(1, round(fps * .16)) - 1) / fps
        windows.append((bubble['typingStartFrame'] / fps, min(end, settled)))
    windows.extend((event['frame'] / fps, event['endFrame'] / fps) for event in timing['scrollEvents'])

    def gaps(intervals: list[tuple[float, float]]) -> list[dict]:
        cursor, result = 0.0, []
        for start, stop in sorted(intervals):
            if start > cursor:
                result.append({'start_s': cursor, 'end_s': start})
            cursor = max(cursor, stop)
        if cursor < end:
            result.append({'start_s': cursor, 'end_s': end})
        return result

    silence = [] if payload['music_ref'] else gaps(
        [(cue['frame'] / fps, min(end, cue['frame'] / fps + .12)) for cue in timing['sfxCues']]
        if payload['sfx'] else [])
    # Small typing dots occupy little of the portrait frame; the general default
    # .001 threshold mistakes them for a freeze. Actual encoded samples verify 1e-6.
    return {'allowed_freeze': gaps(windows), 'allowed_silence': silence, 'n': .000001}
