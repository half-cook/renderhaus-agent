"""Allow-listed font measurement shared by local renders and Lambda props.

System fonts use the Bitstream Vera licence and public-domain DejaVu changes.
Source https://dejavu-fonts.github.io/License.html, read 2026-10-09.
"""
from __future__ import annotations

import math
from pathlib import Path
import unicodedata
from typing import Any

from PIL import ImageFont

FONT_FILES = {
    'dejavu-sans': Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
    'dejavu-sans-bold': Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
}


def number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if (isinstance(value, bool) or not isinstance(value, (float, int))
            or not math.isfinite(value) or not minimum <= value <= maximum):
        raise ValueError(f'{name} must be finite and between {minimum:g} and {maximum:g}.')
    return float(value)


def box_geometry(value: Any, width: int, height: int) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != {'x', 'y', 'width', 'height'}:
        raise ValueError('box must contain only x, y, width and height.')
    box = {name: number(value[name], f'box.{name}', 0 if name in {'x', 'y'} else 1,
                        width if name in {'x', 'width'} else height)
           for name in ('x', 'y', 'width', 'height')}
    if box['x'] + box['width'] > width or box['y'] + box['height'] > height:
        raise ValueError('Overlay box must stay inside the canvas.')
    return box


def font_path(item: dict[str, Any]) -> tuple[str, Path]:
    family = item.get('fontFamily') or ('dejavu-sans-bold' if item.get('fontWeight', 700) >= 600
                                      else 'dejavu-sans')
    if not isinstance(family, str) or family not in FONT_FILES:
        raise ValueError('Text requires an allow-listed font id, dejavu-sans or dejavu-sans-bold.')
    path = FONT_FILES[family]
    if not path.is_file():
        raise ValueError(f'Allow-listed system font {family} is unavailable on this render worker.')
    return family, path


def fit_text(item: dict[str, Any], width: int, height: int) -> dict[str, Any]:
    text = item.get('text')
    if not isinstance(text, str) or not text.strip() or len(text) > 500 or '\0' in text:
        raise ValueError('Text must contain 1 to 500 characters without NUL bytes.')
    family, path = font_path(item)
    minimum = number(item.get('minFontSize', 16), 'minFontSize', 16, 180)
    maximum = number(item.get('maxFontSize', item.get('fontSize', 64)), 'maxFontSize', 16, 180)
    if not minimum.is_integer() or not maximum.is_integer() or minimum > maximum:
        raise ValueError('Font size bounds must be integers with minFontSize <= maxFontSize.')
    if 'box' in item:
        box = box_geometry(item['box'], width, height)
    else:
        box = {'x': width * .06, 'y': height * .06, 'width': width * .88, 'height': height * .88}
    check_font = ImageFont.truetype(str(path), int(minimum))
    missing_mask = check_font.getmask('\uffff')
    missing = (missing_mask.size, bytes(missing_mask))
    for char in set(text):
        if char.isspace() or unicodedata.category(char) in {'Cf', 'Mn', 'Me'}:
            continue
        glyph = check_font.getmask(char)
        if (glyph.size, bytes(glyph)) == missing:
            raise ValueError(f'text_unsupported_glyph U+{ord(char):04X} in {family}.')
    lines = text.split('\n')
    for size in range(int(maximum), int(minimum) - 1, -1):
        font = ImageFont.truetype(str(path), size)
        measured_width = max(math.ceil(font.getlength(line)) for line in lines)
        ascent, descent = font.getmetrics()
        measured_height = (ascent + descent) * len(lines)
        if measured_width <= box['width'] and measured_height <= box['height']:
            if 'box' not in item:
                box['height'] = min(box['height'], measured_height + 24)
                position = item.get('position', 'center')
                if position == 'bottom':
                    box['y'] = height * .94 - box['height']
                elif position == 'center':
                    box['y'] = (height - box['height']) / 2
            return {'fontFamily': family, 'fontSize': size, 'minFontSize': int(minimum),
                    'maxFontSize': int(maximum), 'box': box,
                    'textFit': {'width': measured_width, 'height': measured_height,
                                'fontSize': size, 'overflow': False}}
    raise ValueError(f'text_overflow at minimum font size {minimum:g}; enlarge the box or revise the copy.')
