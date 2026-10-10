from __future__ import annotations

import re

STAMP = r'(\d{2}):([0-5]\d):([0-5]\d),(\d{3})'
TIMING = re.compile(rf'^{STAMP} --> {STAMP}$')


def srt_captions(value: str | None, subtitles: list[dict] | None) -> list[dict] | None:
    if value is None:
        return subtitles
    if subtitles:
        raise ValueError('Choose subtitles or subtitles_srt, not both.')
    if not isinstance(value, str) or not value.strip() or len(value) > 60_000 or '\x00' in value:
        raise ValueError('subtitles_srt requires 1..60000 characters of inline numbered SRT.')
    result = []
    for block in re.split(r'\n[ \t]*\n', value.replace('\r\n', '\n').strip('\n')):
        lines = block.split('\n')
        match = TIMING.fullmatch(lines[1]) if len(lines) >= 3 else None
        if not lines[0].isascii() or not lines[0].isdigit() or match is None:
            raise ValueError('subtitles_srt requires numbered cues and HH:MM:SS,mmm --> HH:MM:SS,mmm timing.')
        numbers = [int(part) for part in match.groups()]
        start, end = [h * 3600 + m * 60 + s + ms / 1000
                      for h, m, s, ms in (numbers[:4], numbers[4:])]
        if not 0 <= start < end <= 600 or len(result) >= 100:
            raise ValueError('subtitles_srt allows at most 100 cues with increasing cue times inside 0..600 seconds.')
        result.append({'text': '\n'.join(lines[2:]), 'start_seconds': start,
                       'duration_seconds': end - start, 'position': 'bottom'})
    return result
