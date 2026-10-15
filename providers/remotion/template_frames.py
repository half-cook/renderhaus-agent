"""Deterministic raster drawing for validated Remotion template plans.

Font rasterization parity is unverified.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import time
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from providers.remotion.text import FONT_FILES
from providers.remotion.templates import fitted_font_size


MAX_VIDEO_BYTES = 128 * 1024 * 1024


def _round(value: float) -> int:
    return math.floor(value + .5)


def _pixel_box(rectangle: dict[str, float], width: int, height: int) -> tuple[int, int, int, int]:
    x, y = _round(rectangle['x'] * width), _round(rectangle['y'] * height)
    return x, y, _round(rectangle['width'] * width), _round(rectangle['height'] * height)


def _text_panel(image: Image.Image, rectangle: dict[str, float], lines: list[list[tuple[str, str]]],
                *, size: float, opacity: float = 1, measured_size: int | None = None) -> None:
    x, y, width, height = _pixel_box(rectangle, *image.size)
    panel = Image.new('RGBA', (width, height))
    draw = ImageDraw.Draw(panel)
    text_lines = [' '.join(word for word, _ in line) for line in lines]
    font_size = measured_size if measured_size is not None else fitted_font_size(text_lines, rectangle, *image.size, size)
    font = ImageFont.truetype(str(FONT_FILES['dejavu-sans-bold']), font_size)
    line_height = font_size * 1.35
    top = (height - len(lines) * line_height) / 2
    for index, words in enumerate(lines):
        text = ' '.join(word for word, _ in words)
        left = (width - font.getlength(text)) / 2
        for word, colour in words:
            draw.text((left, top + index * line_height), word, font=font, fill=colour,
                      stroke_width=0)
            left += font.getlength(word + ' ')
    if opacity != 1:
        panel.putalpha(panel.getchannel('A').point(lambda value: round(value * opacity)))
    image.paste(panel, (x, y), panel)


def _waveform(image: Image.Image, plan: dict[str, Any], frame: int) -> None:
    x, y, width, height = _pixel_box(plan['layout']['waveform'], *image.size)
    amplitudes, bars = plan['amplitudes'], plan['bars']
    values = [amplitudes[max(0, min(len(amplitudes) - 1, frame + index - bars // 2))]
              for index in range(bars)]
    draw = ImageDraw.Draw(image)
    colour = plan['accent_color']
    if plan['waveform'] == 'bars':
        step = width / bars
        for index, amplitude in enumerate(values):
            bar_height = max(1, amplitude * height)
            left = x + index * step + step * .15
            top = y + (height - bar_height) / 2
            draw.rectangle((left, top, left + step * .7, top + bar_height - 1), fill=colour)
    else:
        points = [(x + index * (width - 1) / (bars - 1),
                   y + height / 2 + (-1 if index % 2 else 1) * amplitude * (height - 2) / 2)
                  for index, amplitude in enumerate(values)]
        draw.line(points, fill=colour, width=max(1, _round(min(image.size) * .003)))


def render_template_frame(plan: dict[str, Any], frame: int) -> Image.Image:
    """Draw one frame from a boundary-validated internal template plan without media I/O."""
    width, height = plan['width'], plan['height']
    image = Image.new('RGB', (width, height), plan['background_color'])
    seconds = frame / plan['fps']
    name = plan['name']
    opacity = min(1, max(0, seconds / .35)) if name == 'youtube-intro-sting' else 1
    scale = .92 + .08 * opacity if name == 'youtube-intro-sting' else 1
    lines = [[(text, plan['text_color'])] for text in (plan['show_name'], plan['speaker_name']) if text]
    if lines:
        _text_panel(image, plan['layout']['identity'], lines,
                    size=min(width, height) * .052 * scale, opacity=opacity,
                    measured_size=max(1, math.floor(plan['typography']['identity'] * scale)) if 'typography' in plan else None)
    if name != 'podcast-audiogram':
        return image
    _waveform(image, plan, frame)
    current = next(((index, caption) for index, caption in enumerate(plan['captions'])
                    if caption['start'] <= seconds < caption['end']), None)
    if current:
        index, caption = current
        words = [(word['text'], plan['accent_color'] if word['start'] <= seconds < word['end']
                  else plan['text_color']) for word in caption['words']]
        lines = [words] if words else [[(line, plan['text_color'])] for line in caption['text'].split('\n')]
        _text_panel(image, plan['layout']['captions'], lines, size=min(width, height) * .07,
                    measured_size=plan['typography']['captions'][index] if 'typography' in plan else None)
    x, y, bar_width, bar_height = _pixel_box(plan['layout']['progress'], width, height)
    total_frames = math.ceil(plan['duration_seconds'] * plan['fps'] - 1e-9)
    progress = min(1, max(0, frame / max(1, total_frames - 1)))
    filled = _round(bar_width * progress)
    if filled:
        ImageDraw.Draw(image).rectangle((x, y, x + filled - 1, y + bar_height - 1),
                                       fill=plan['accent_color'])
    return image


def write_template_video(plan: dict[str, Any], directory: Path) -> Path:
    """Stream bounded RGB frames to an owned silent H.264 intermediate for local assembly."""
    binary = shutil.which('ffmpeg')
    if not binary:
        raise RuntimeError('Local template drawing requires ffmpeg on PATH.')
    target = directory / 'template-visual.mp4'
    if target.exists():
        raise FileExistsError('Template intermediate already exists.')
    timeout = max(1, float(os.getenv('REMOTION_RENDER_TIMEOUT_SECONDS', '1200')))
    deadline = time.monotonic() + timeout
    width, height, fps = plan['width'], plan['height'], plan['fps']
    frames = math.ceil(plan['duration_seconds'] * fps - 1e-9)
    command = [binary, '-hide_banner', '-nostdin', '-v', 'error', '-n',
               '-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', f'{width}x{height}',
               '-framerate', str(fps), '-i', 'pipe:0', '-an', '-frames:v', str(frames),
               '-c:v', 'libx264', '-threads', '2', '-preset', 'veryfast', '-crf', '18',
               '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-fs', str(MAX_VIDEO_BYTES), str(target)]
    process = None
    try:
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(command, cwd=directory, stdin=subprocess.PIPE,
                                       stdout=subprocess.DEVNULL, stderr=errors,
                                       env={'PATH': os.defpath, 'LANG': 'C', 'LC_ALL': 'C',
                                            'OMP_NUM_THREADS': '2'})
            assert process.stdin is not None
            descriptor = process.stdin.fileno()
            os.set_blocking(descriptor, False)
            for frame in range(frames):
                pixels = memoryview(render_template_frame(plan, frame).tobytes())
                while pixels:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired('ffmpeg template encode', timeout)
                    if not select.select([], [descriptor], [], min(remaining, 1))[1]:
                        continue
                    pixels = pixels[os.write(descriptor, pixels[:65536]):]
            process.stdin.close()
            code = process.wait(timeout=max(.01, deadline - time.monotonic()))
            if code or not target.is_file() or not 0 < target.stat().st_size <= MAX_VIDEO_BYTES:
                raise RuntimeError('Local template encode failed or exceeded its output limit.')
    except BaseException:
        if process is not None:
            if process.poll() is None:
                process.kill()
            if process.stdin is not None:
                process.stdin.close()
            process.wait(timeout=5)
        target.unlink(missing_ok=True)
        raise
    return target
