"""Render validated chat plans with installed fonts and locally synthesized tones."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
import os
from pathlib import Path
import shutil
import struct
import tempfile
import time
import unicodedata
from typing import Any
import wave

from PIL import Image, ImageDraw, ImageFont

from providers.ffmpeg.api import _bounded_run
from providers.remotion.chat_story import graphemes


EMOJI_FONT = Path('/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf')
TEXT_FONT = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
MAX_FRAME_BYTES = 384 * 1024 * 1024


@dataclass(frozen=True)
class Palette:
    background: str
    chrome: str
    sent: str
    received: str
    sent_text: str
    text: str
    muted: str
    avatar: str


PALETTES = {
    'generic': Palette('#f3f0e9', '#ffffff', '#635d86', '#ded9ce', '#ffffff', '#242332', '#657286', '#dae3f3'),
    'slate': Palette('#f5f5f7', '#ffffff', '#426ac3', '#e2e3e8', '#ffffff', '#242332', '#627386', '#d5deeb'),
    'moss': Palette('#eef3ef', '#ffffff', '#477965', '#dce6df', '#ffffff', '#242332', '#64756c', '#d7e5dc'),
}


@lru_cache(maxsize=32)
def _font(size: int) -> ImageFont.FreeTypeFont:
    if not TEXT_FONT.is_file():
        raise ValueError('Chat-story rendering needs the installed DejaVu Sans font.')
    return ImageFont.truetype(str(TEXT_FONT), max(1, size))


@lru_cache(maxsize=2)
def _emoji_font(path: str) -> ImageFont.FreeTypeFont:
    if not Path(path).is_file():
        raise ValueError('Chat-story rendering needs the installed Noto emoji font.')
    return ImageFont.truetype(path, 109)


def _is_emoji(character: str) -> bool:
    codepoint = ord(character)
    return (0x1F000 <= codepoint <= 0x1FAFF or 0x2600 <= codepoint <= 0x27FF
            or codepoint in {0x203C, 0x2049, 0x231A, 0x231B, 0x23F0, 0x23F3, 0x2B50, 0x2B55})


def _runs(text: str) -> list[tuple[str, bool]]:
    runs: list[tuple[str, bool]] = []
    for cluster in graphemes(text):
        emoji = _is_emoji(cluster[0]) or (cluster[0] in '#*0123456789' and '\u20e3' in cluster)
        if not emoji and runs and not runs[-1][1]:
            runs[-1] = (runs[-1][0] + cluster, False)
        else:
            runs.append((cluster, emoji))
    return runs


def _rtl(text: str) -> bool:
    for character in text:
        direction = unicodedata.bidirectional(character)
        if direction in {'R', 'AL', 'L'}:
            return direction != 'L'
    return False


def _text(image: Image.Image, text: str, xy: tuple[float, float], *, size: int,
          fill: str, max_width: float | None = None) -> None:
    draw = ImageDraw.Draw(image)
    font = _font(size)
    runs = _runs(text)
    directions = {unicodedata.bidirectional(character) for character in text}
    if any(emoji for _, emoji in runs) and directions.intersection({'R', 'AL'}) and directions.intersection({'L', 'EN', 'AN'}):
        raise ValueError('Local chat-story rendering does not support mixed text direction with emoji. '
                         'Supply separately approved lines; the original text will not be reordered or rewritten.')
    rtl = _rtl(text)
    if rtl:
        runs.reverse()
    widths = [size * 1.25 if emoji else draw.textlength(run, font=font, direction='rtl' if rtl else 'ltr')
              for run, emoji in runs]
    x, y = xy
    if rtl and max_width is not None:
        x += max(0, max_width - sum(widths))
    for (run, emoji), run_width in zip(runs, widths, strict=True):
        if emoji:
            emoji_font = _emoji_font(str(EMOJI_FONT))
            glyph = Image.new('RGBA', (150, 140))
            ImageDraw.Draw(glyph).text((0, 0), run, font=emoji_font, embedded_color=True)
            bounds = glyph.getbbox()
            if bounds:
                glyph = glyph.crop(bounds)
                glyph.thumbnail((max(1, round(run_width)), max(1, round(size * 1.18))), Image.Resampling.LANCZOS)
                image.alpha_composite(glyph, (round(x), round(y)))
        else:
            draw.text((x, y), run, font=font, fill=fill,
                      direction='rtl' if rtl else 'ltr', anchor='lt')
        x += run_width


def scroll_offset(plan: dict[str, Any], frame: int) -> float:
    previous = 0.0
    for event in plan['scrollEvents']:
        if frame < event['frame']:
            break
        end = event.get('endFrame', event['frame'])
        if frame < end:
            progress = (frame - event['frame']) / max(1, end - event['frame'])
            return previous + (event['offset'] - previous) * progress
        previous = float(event['offset'])
    return previous


def _chrome(image: Image.Image, story: dict[str, Any], palette: Palette) -> None:
    plan, payload = story['plan'], story['payload']
    width, height = plan['width'], plan['height']
    scale = width / 1080
    draw = ImageDraw.Draw(image)
    header_end = min(plan['safeTop'] - 12 * scale, 226 * scale)
    draw.rectangle((0, 0, width, header_end), fill=palette.chrome)
    _text(image, '9:41', (64 * scale, 35 * scale), size=max(1, round(30 * scale)), fill=palette.text)
    for index in range(3):
        x = width - (98 - index * 19) * scale
        draw.rounded_rectangle((x, 40 * scale, x + 11 * scale, 57 * scale), radius=3 * scale, fill=palette.muted)
    radius, cx, cy = 34 * scale, width / 2, 110 * scale
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=palette.avatar)
    name = payload['contact']['name']
    initials = ''.join(graphemes(word)[0] for word in name.split()[:2]).upper() if payload['contact']['avatar'] == 'initials' else '•'
    _text(image, initials, (cx - 19 * scale, cy - 14 * scale), size=max(1, round(27 * scale)), fill=palette.text)
    name_font = max(1, round(plan.get('contactFontSize', 34 * scale)))
    name_width = sum(name_font * 1.25 if emoji else draw.textlength(run, font=_font(name_font))
                     for run, emoji in _runs(name))
    if name_width > width - 96 * scale:
        raise ValueError('Chat-story contact name exceeds the bounded header. Supply a shorter fictional name.')
    _text(image, name, ((width - name_width) / 2, 164 * scale), size=name_font, fill=palette.text)
    if payload.get('dramatization'):
        tag_y = header_end - 25 * scale if header_end >= 200 * scale else 110 * scale
        _text(image, 'Dramatization', (48 * scale, tag_y),
              size=max(1, round(21 * scale)), fill=palette.muted)
    draw.line((0, header_end, width, header_end), fill=palette.received, width=max(1, round(scale)))
    draw.rounded_rectangle((width * .38, height - 38 * scale, width * .62, height - 30 * scale),
                           radius=4 * scale, fill=palette.muted)


def draw_chat_frame(story: dict[str, Any], frame: int) -> Image.Image:
    """Draw the exact normalized lines and geometry without rewriting the script."""
    plan, payload = story['plan'], story['payload']
    width, height, fps = plan['width'], plan['height'], plan['fps']
    scale = width / 1080
    font_size = max(1, round(plan.get('fontSize', 38 * scale)))
    line_height = plan.get('lineHeight', 48 * scale)
    padding = plan.get('padding', 22 * scale)
    palette = PALETTES[payload['theme']]
    image = Image.new('RGBA', (width, height), palette.background)
    _chrome(image, story, palette)
    viewport = Image.new('RGBA', (width, height))
    scroll = scroll_offset(plan, frame)
    floor = height - plan['safeBottom']
    for bubble in plan['bubbles']:
        message = payload['messages'][bubble['index']]
        x, y, bw, bh = bubble['x'], bubble['y'] - scroll, bubble['width'], bubble['height']
        typing = bubble['typingStartFrame']
        if typing is not None and typing <= frame < bubble['startFrame']:
            dot_width, dot_height = 124 * scale, 58 * scale
            dot_y = min(max(plan['safeTop'], y), floor - dot_height)
            draw = ImageDraw.Draw(viewport)
            draw.rounded_rectangle((x, dot_y, x + dot_width, dot_y + dot_height),
                                   radius=24 * scale, fill=palette.received)
            phase = int(frame / max(1, fps * .18)) % 3
            for index in range(3):
                cx, cy = x + (34 + 28 * index) * scale, dot_y + dot_height / 2
                radius = (7 if index == phase else 5) * scale
                draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=palette.muted)
        if frame < bubble['startFrame'] or y + bh < plan['safeTop']:
            continue
        layer = Image.new('RGBA', (width, height))
        draw = ImageDraw.Draw(layer)
        sent = message['from'] == 'me'
        fill = palette.sent if sent else palette.received
        draw.rounded_rectangle((x, y, x + bw, y + bh), radius=26 * scale, fill=fill)
        if bubble['tail']:
            tail_x = x + bw if sent else x
            sign = 1 if sent else -1
            draw.polygon([(tail_x - sign * 16 * scale, y + bh - 24 * scale),
                          (tail_x + sign * 7 * scale, y + bh),
                          (tail_x - sign * 23 * scale, y + bh - 3 * scale)], fill=fill)
        for index, line in enumerate(bubble['lines']):
            _text(layer, line, (x + padding, y + padding + line_height * index),
                  size=font_size, fill=palette.sent_text if sent else palette.text,
                  max_width=bw - 2 * padding)
        pop_frames = max(1, round(fps * .16))
        progress = min(1, max(0, (frame - bubble['startFrame'] + 1) / pop_frames))
        if progress < 1:
            alpha = layer.getchannel('A').point(lambda value: round(value * progress))
            layer.putalpha(alpha)
            rectangle = (math.floor(x - 10 * scale), math.floor(y - 10 * scale),
                         math.ceil(x + bw + 10 * scale), math.ceil(y + bh + 10 * scale))
            cropped = layer.crop(rectangle)
            factor = .94 + .06 * (1 - (1 - progress) ** 3)
            cropped = cropped.resize((max(1, round(cropped.width * factor)),
                                      max(1, round(cropped.height * factor))), Image.Resampling.LANCZOS)
            layer = Image.new('RGBA', (width, height))
            origin_x = rectangle[2] - cropped.width if sent else rectangle[0]
            layer.alpha_composite(cropped, (origin_x, rectangle[3] - cropped.height))
        viewport.alpha_composite(layer)
        receipt = bubble['receiptFrame']
        if sent and receipt is not None and frame >= receipt and message['status']:
            label = message['status'].title()
            label_size = max(1, round(23 * scale))
            label_width = ImageDraw.Draw(viewport).textlength(label, font=_font(label_size))
            _text(viewport, label, (x + bw - label_width, y + bh + 10 * scale), size=label_size, fill=palette.muted)
        reaction = bubble['reactionFrame']
        if reaction is not None and frame >= reaction and message['reaction']:
            reaction_x = x + 8 * scale
            reaction_y = y + bh - 4 * scale
            draw = ImageDraw.Draw(viewport)
            draw.rounded_rectangle((reaction_x, reaction_y, reaction_x + 70 * scale, reaction_y + 52 * scale),
                                   radius=24 * scale, fill=palette.chrome, outline=palette.received,
                                   width=max(1, round(scale)))
            _text(viewport, message['reaction'], (reaction_x + 13 * scale, reaction_y + 9 * scale),
                  size=max(1, round(29 * scale)), fill=palette.text)
    image.alpha_composite(viewport.crop((0, round(plan['safeTop']), width, round(floor))),
                          (0, round(plan['safeTop'])))
    return image.convert('RGB')


def write_pop(path: Path, kind: str) -> None:
    frequency = {'send': 880, 'receive': 660}[kind]
    count = round(48000 * .12)
    samples = bytearray()
    for index in range(count):
        seconds = index / 48000
        envelope = min(1, index / 200) * math.exp(-35 * seconds)
        value = (math.sin(2 * math.pi * frequency * seconds)
                 + .3 * math.sin(2 * math.pi * frequency * 1.8 * seconds))
        samples.extend(struct.pack('<h', round(9000 * envelope * value)))
    with path.open('xb') as target, wave.open(target, 'wb') as audio:
        audio.setparams((1, 2, 48000, count, 'NONE', 'not compressed'))
        audio.writeframes(samples)


def _state_key(plan: dict[str, Any], frame: int) -> tuple:
    pop_frames = max(1, round(plan['fps'] * .16))
    bubbles = tuple((bubble['index'], min(pop_frames, frame - bubble['startFrame']),
                     bubble['reactionFrame'] is not None and frame >= bubble['reactionFrame'],
                     bubble['receiptFrame'] is not None and frame >= bubble['receiptFrame'])
                    for bubble in plan['bubbles'] if frame >= bubble['startFrame'])
    typing = tuple((bubble['index'], int(frame / max(1, plan['fps'] * .18)) % 3)
                   for bubble in plan['bubbles'] if bubble['typingStartFrame'] is not None
                   and bubble['typingStartFrame'] <= frame < bubble['startFrame'])
    return bubbles, typing, round(scroll_offset(plan, frame), 4)


def render_chat_visual(story: dict[str, Any], directory: Path) -> dict[str, str | None]:
    """Create a silent procedural master and synthetic pop sources inside this render."""
    plan = story['plan']
    if not shutil.which('ffmpeg'):
        raise RuntimeError('Local chat-story rendering requires ffmpeg on PATH.')
    if (plan['width'] * plan['height'] > 1080 * 1920 or plan['durationInFrames'] > 36_000):
        raise ValueError('Local chat stories allow at most a 1080x1920 canvas and 36000 frames.')
    visual = directory / 'chat-visual.mp4'
    if visual.exists() or visual.is_symlink():
        raise ValueError('Chat-story intermediates cannot overwrite existing files.')
    timeout = max(1, float(os.getenv('REMOTION_RENDER_TIMEOUT_SECONDS', '1200')))
    deadline = time.monotonic() + timeout
    with tempfile.TemporaryDirectory(prefix='chat-frames-', dir=directory) as temporary:
        frame_directory = Path(temporary)
        states: dict[tuple, Path] = {}
        total_bytes = 0
        for frame in range(plan['durationInFrames']):
            if time.monotonic() >= deadline:
                raise ValueError('Local chat-story frame preparation exceeded its deadline.')
            key = _state_key(plan, frame)
            target = frame_directory / f'frame-{frame:06d}.png'
            if key in states:
                os.link(states[key], target)
            else:
                draw_chat_frame(story, frame).save(target)
                states[key] = target
                total_bytes += target.stat().st_size
                if total_bytes > MAX_FRAME_BYTES:
                    raise ValueError('Chat-story frames exceed the 384 MiB intermediate limit.')
        result = _bounded_run([
            shutil.which('ffmpeg') or 'ffmpeg', '-hide_banner', '-nostdin', '-v', 'error',
            '-filter_complex_threads', '1', '-framerate', str(plan['fps']),
            '-protocol_whitelist', 'file,pipe', '-f', 'image2', '-i', str(frame_directory / 'frame-%06d.png'),
            '-frames:v', str(plan['durationInFrames']), '-c:v', 'libx264', '-threads', '2',
            '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart', '-fs', str(128 * 1024 * 1024), str(visual),
        ], directory, max(.001, deadline - time.monotonic()))
    if result.returncode or not visual.is_file() or not visual.stat().st_size:
        visual.unlink(missing_ok=True)
        raise ValueError('The local chat-story visual encode failed.')
    sources: dict[str, str | None] = {'visual_path': str(visual), 'send_path': None, 'receive_path': None}
    if story['payload'].get('sfx', True):
        for kind in ('send', 'receive'):
            if story['payload'].get(kind + '_sound_ref'):
                continue
            path = directory / f'chat-{kind}.wav'
            write_pop(path, kind)
            sources[kind + '_path'] = str(path)
    return sources
