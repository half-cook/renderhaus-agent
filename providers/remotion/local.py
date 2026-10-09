"""Explicit development backend for the shared Remotion timeline document.

Filter semantics verified against https://ffmpeg.org/ffmpeg-filters.html, read 2026-10-09.
"""
from __future__ import annotations

import ipaddress
import json
import os
from fractions import Fraction
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import urlsplit
import uuid

import httpx

from providers.remotion import mp4_probe
from providers.remotion.text import box_geometry, fit_text, font_path, number

MAX_MEDIA_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 384 * 1024 * 1024
FORMATS = 'mov,matroska,mp3,wav,aac,image2,png_pipe,jpeg_pipe,webp_pipe,ogg,flac'
_PROCESSES: dict[str, subprocess.Popen] = {}
_LOCK = threading.Lock()


def _output_root(media_roots: tuple[Path, ...]) -> Path:
    return media_roots[-1] / 'remotion' / 'local'


def _source(source: str, *, directory: Path, index: int,
            media_roots: tuple[Path, ...], source_root: Path,
            allowed_hosts: set[str] | None = None, deadline_seconds: float = 120) -> Path:
    parsed = urlsplit(source)
    if not parsed.scheme:
        path = Path(source).expanduser()
        path = (path if path.is_absolute() else source_root / path).resolve()
        if not any(path == root or root in path.parents for root in media_roots):
            raise ValueError('Local render sources must stay inside Renderhaus media roots.')
        if not path.is_file() or not 0 < path.stat().st_size <= MAX_MEDIA_BYTES:
            raise ValueError('Local render sources must be nonempty media files within the size limit.')
        return path
    hosts = (set(os.getenv('REMOTION_LOCAL_MEDIA_HOSTS', '').split(',')) - {''}
             if allowed_hosts is None else allowed_hosts)
    if (parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username
            or parsed.password or parsed.port not in {None, 443} or parsed.fragment):
        raise ValueError('Local remote sources require HTTPS on an exact REMOTION_LOCAL_MEDIA_HOSTS host.')
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Local remote media hosts must resolve to public addresses.')
    destination = directory / f'source-{index}.media'
    deadline = time.monotonic() + deadline_seconds
    try:
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
            with client.stream('GET', source) as response:
                if response.status_code != 200:
                    raise ValueError('Local remote media was unavailable; redirects are not followed.')
                size = 0
                with destination.open('wb') as target:
                    for chunk in response.iter_bytes(1024 * 1024):
                        if time.monotonic() > deadline:
                            raise ValueError('Local remote media download exceeded its deadline.')
                        size += len(chunk)
                        if size > MAX_MEDIA_BYTES:
                            raise ValueError('Local remote media exceeds the source size limit.')
                        target.write(chunk)
    except httpx.HTTPError:
        raise ValueError('Local remote media could not be downloaded.') from None
    if not destination.stat().st_size:
        raise ValueError('Local remote media is empty.')
    return destination


def _probe(path: Path) -> dict[str, Any]:
    if not shutil.which('ffprobe'):
        return mp4_probe.probe(path, max_bytes=MAX_MEDIA_BYTES)
    result = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
                             '-format_whitelist', FORMATS, '-show_streams', '-show_format',
                             '-of', 'json', str(path)], capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError('Local source/output is not a supported media container.')
    return json.loads(result.stdout)


def _audio_filter(label: str, item: dict[str, Any], *, rate: float = 1,
                  source_audio: bool = False) -> str:
    duration, start = float(item['duration']), float(item['start'])
    filters = ['asetpts=PTS-STARTPTS']
    remaining = rate
    while remaining < .5:
        filters.append('atempo=0.5')
        remaining /= .5
    while remaining > 2:
        filters.append('atempo=2')
        remaining /= 2
    if remaining != 1:
        filters.append(f'atempo={remaining:g}')
    filters += [f'atrim=duration={duration:g}', f'volume={item.get("volume", 1):g}']
    for field, kind in [('audioFadeIn' if source_audio else 'fadeIn', 'in'),
                        ('audioFadeOut' if source_audio else 'fadeOut', 'out')]:
        length = float(item.get(field, 0))
        if length:
            when = 0 if kind == 'in' else max(0, duration - length)
            filters.append(f'afade=t={kind}:st={when:g}:d={length:g}')
    filters += [f'adelay={round(start*1000)}:all=1', 'aresample=48000']
    return f'[{label}]' + ','.join(filters)


def _colour(value: str) -> str:
    names = {'white', 'black', 'red', 'green', 'blue', 'yellow', 'gray', 'grey', 'transparent'}
    if value in names:
        return 'black@0' if value == 'transparent' else value
    if re.fullmatch(r'#[0-9a-fA-F]{3}', value):
        return '0x' + ''.join(character * 2 for character in value[1:])
    if re.fullmatch(r'#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?', value):
        return '0x' + value[1:]
    raise ValueError('Local text colors require a hex color or an allow-listed color name.')


def _visual_layer(label: str, item: dict[str, Any], *, duration: float, fps: float) -> list[str]:
    opacity = number(item.get('opacity', 1), 'opacity', 0, 1)
    chain = [] if opacity == 1 else [f'colorchannelmixer=aa={opacity:g}']
    for field, direction in [('fadeIn', 'in'), ('fadeOut', 'out')]:
        length = number(item.get(field, 0), field, 0, duration)
        if length:
            frames = max(1, round((item['start'] + duration) * fps) - round(item['start'] * fps))
            when = 0 if direction == 'in' else max(0, (frames - 1) / fps - length)
            chain.append(f'fade=t={direction}:st={when:g}:d={length:g}:alpha=1')
    start = number(item['start'], 'start', 0, 600)
    chain.append(f'setpts=PTS+{start:g}/TB[{label}]')
    return chain


def _text_layer(item: dict[str, Any], directory: Path, index: int, *, width: int,
                height: int, frame_rate: str) -> tuple[str, dict[str, float]]:
    layout = fit_text(item, width, height)
    _, path = font_path(layout)
    font_name = f'font-{path.name}'
    if not (directory / font_name).exists():
        shutil.copyfile(path, directory / font_name)
    text_name = f'text-{index}.txt'
    (directory / text_name).write_text(item['text'], encoding='utf-8')
    box = layout['box']
    box_width, box_height = round(box['width']), round(box['height'])
    duration = number(item['duration'], 'text duration', 1 / 240, 600)
    chain = [f'color=c=black@0:s={box_width}x{box_height}:r={frame_rate}:d={duration:g}',
             'format=rgba']
    background = _colour(item.get('backgroundColor', 'transparent'))
    if background != 'black@0':
        chain.append(f'drawbox=x=0:y=0:w=iw:h=ih:color={background}:t=fill:replace=1')
    chain.append(f'drawtext=fontfile={font_name}:textfile={text_name}:expansion=none:'
                 f'fontsize={layout["fontSize"]}:fontcolor={_colour(item.get("color", "#ffffff"))}:'
                 'x=(w-text_w)/2:y=(h-text_h)/2:text_shaping=1')
    chain += _visual_layer(f'text{index}', item, duration=duration, fps=float(Fraction(frame_rate)))
    return ','.join(chain), box


def _command(props: dict[str, Any], directory: Path, *, media_roots: tuple[Path, ...],
             source_root: Path, filename: str) -> tuple[list[str], float]:
    config, document = props['renderConfig'], props['document']
    fps, width, height = float(config['fps']), int(config['width']), int(config['height'])
    frame_rate = str(Fraction(fps).limit_denominator(100_000))
    duration = int(config['durationInFrames']) / fps
    if not 0 < duration <= 600 or len(document['assets']) > 60:
        raise ValueError('Local renders allow at most 600 seconds and 60 assets.')
    assets = {asset['id']: asset for asset in document['assets']}
    command = ['ffmpeg', '-hide_banner', '-nostdin', '-v', 'error', '-y',
               '-filter_complex_threads', '1', '-f', 'lavfi', '-i',
               f'color=c=black:s={width}x{height}:r={frame_rate}:d={duration:g}']
    filters: list[str] = []
    visual = '0:v'
    audio: list[str] = []
    count = 0
    text_count = 0
    total_bytes = 0
    for track in document['tracks']:
        for item in track['items']:
            if item['type'] == 'text':
                text_count += 1
                chain, box = _text_layer(item, directory, text_count, width=width,
                                        height=height, frame_rate=frame_rate)
                filters.append(chain)
                filters.append(f'[{visual}][text{text_count}]overlay=x={box["x"]:g}:y={box["y"]:g}'
                               ':eof_action=pass:repeatlast=0'
                               f':enable=between(t\\,{item["start"]:g}\\,'
                               f'{item["start"]+item["duration"]:g})[textout{text_count}]')
                visual = f'textout{text_count}'
                continue
            if item['type'] != 'clip':
                raise ValueError('Unsupported timeline item type; local supports clip and text items.')
            if (item.get('motion', 'none') != 'none' or item.get('grade', 'none') != 'none'
                    or item.get('rotation', 0) != 0):
                raise ValueError('Local assembly does not support motion/grade/rotation; use Lambda.')
            count += 1
            asset = assets[item['assetId']]
            source = _source(asset['url'], directory=directory, index=count,
                             media_roots=media_roots, source_root=source_root)
            total_bytes += source.stat().st_size
            if total_bytes > MAX_TOTAL_BYTES:
                raise ValueError('Local assembly source media exceeds the total size limit.')
            probe = _probe(source)
            kind = asset['kind']
            rate = float(item.get('playbackRate', 1))
            command += ['-protocol_whitelist', 'file,pipe', '-format_whitelist', FORMATS]
            if kind == 'image':
                command += ['-loop', '1', '-framerate', frame_rate]
            else:
                command += ['-ss', str(item.get('sourceIn', 0))]
            command += ['-t', str(float(item['duration']) * rate), '-i', str(source)]
            if kind != 'audio':
                fit = item.get('fit', 'cover')
                if fit not in {'cover', 'contain', 'pad_blur'}:
                    raise ValueError('Visual fit must be cover, contain or pad_blur.')
                px = number(item.get('positionX', .5), 'positionX', 0, 1)
                py = number(item.get('positionY', .5), 'positionY', 0, 1)
                box = box_geometry(item['box'], width, height) if 'box' in item else {
                    'x': 0, 'y': 0, 'width': width, 'height': height}
                scale = number(item.get('scale', 1), 'scale', .1, 4)
                target_width = max(2, round(box['width'] * scale / 2) * 2)
                target_height = max(2, round(box['height'] * scale / 2) * 2)
                x = box['x'] + (box['width'] - target_width) / 2
                y = box['y'] + (box['height'] - target_height) / 2
                chain = [f'[{count}:v]setpts=(PTS-STARTPTS)/{rate:g}',
                         f'fps={frame_rate}', 'format=rgba']
                crop = item.get('cropBox')
                if crop:
                    from providers.contracts import validate_crop_box
                    from providers.remotion.api import _media_dimensions

                    validate_crop_box(crop, 'timeline cropBox')
                    source_size = _media_dimensions(next(s for s in probe['streams'] if s.get('codec_type') == 'video'))
                    if source_size is None or crop['x'] + crop['width'] > source_size[0] or crop['y'] + crop['height'] > source_size[1]:
                        raise ValueError('cropBox must fit inside the measured display-oriented source.')
                    if fit != 'cover':
                        raise ValueError('cropBox requires fit=cover.')
                    if not item.get('allowUpscale', False) and (target_width > crop['width'] or target_height > crop['height']):
                        raise ValueError('Reframing beyond the crop pixels requires allow_upscale=true.')
                    chain.append(f'crop={crop["width"]}:{crop["height"]}:{crop["x"]}:{crop["y"]}:exact=1')
                if fit == 'cover':
                    chain += [f'scale={target_width}:{target_height}:force_original_aspect_ratio=increase:flags=lanczos',
                              f'crop={target_width}:{target_height}:x=(iw-ow)*{px:g}:y=(ih-oh)*{py:g}']
                elif fit == 'contain':
                    padding = 'black@0'
                    chain += [f'scale={target_width}:{target_height}:force_original_aspect_ratio=decrease:flags=lanczos',
                              f'pad={target_width}:{target_height}:x=(ow-iw)*{px:g}:y=(oh-ih)*{py:g}:color={padding}']
                else:
                    filters.append(','.join(chain) + f',split=2[fg{count}][bg{count}]')
                    filters.append(f'[bg{count}]scale={target_width}:{target_height}:force_original_aspect_ratio=increase:flags=lanczos,'
                                   f'crop={target_width}:{target_height},gblur=sigma=20[blur{count}]')
                    if 'padBox' in item:
                        pad = box_geometry(item['padBox'], width, height)
                        foreground_width, foreground_height = int(pad['width']), int(pad['height'])
                        foreground_x, foreground_y = f'{pad["x"]:g}', f'{pad["y"]:g}'
                        foreground_scale = f'scale={foreground_width}:{foreground_height}:flags=lanczos'
                    else:
                        foreground_scale = (f'scale={target_width}:{target_height}:force_original_aspect_ratio=decrease:'
                                            'force_divisible_by=2:flags=lanczos')
                        foreground_x, foreground_y = f'(W-w)*{px:g}', f'(H-h)*{py:g}'
                    filters.append(f'[fg{count}]{foreground_scale}[foreground{count}]')
                    chain = [f'[blur{count}][foreground{count}]overlay=x={foreground_x}:y={foreground_y}:shortest=1', 'format=rgba']
                if scale > 1 and 'box' in item:
                    chain += [f'crop={max(2, round(box["width"] / 2) * 2)}:{max(2, round(box["height"] / 2) * 2)}']
                    x, y = box['x'], box['y']
                chain += ['setsar=1', *_visual_layer(f'v{count}', item, duration=float(item['duration']), fps=fps)]
                filters.append(','.join(chain))
                filters.append(f'[{visual}][v{count}]overlay=x={x:g}:y={y:g}:eof_action=pass:repeatlast=0'
                               f':enable=between(t\\,{item["start"]:g}\\,'
                               f'{item["start"]+item["duration"]:g})[out{count}]')
                visual = f'out{count}'
            if kind == 'audio' or (kind == 'video' and item.get('volume', 1) > 0
                                   and any(s['codec_type'] == 'audio' for s in probe['streams'])):
                label = f'a{count}'
                filters.append(_audio_filter(f'{count}:a', item, rate=rate,
                                             source_audio=kind == 'video') + f'[{label}]')
                audio.append(label)
    filters.append(f'[{visual}]format=yuv420p[video]')
    if audio:
        labels = ''.join(f'[{label}]' for label in audio)
        filters.append(f'{labels}amix=inputs={len(audio)}:normalize=0,'
                       f'apad,atrim=duration={duration:g}[audio]')
    command += ['-filter_complex', ';'.join(filters), '-map', '[video]']
    if audio:
        command += ['-map', '[audio]', '-c:a', 'aac', '-ar', '48000']
    bitrate = config.get('videoBitrate')
    quality = ['-b:v', str(bitrate)] if bitrate else ['-crf', str(config.get('crf') or 18)]
    command += ['-c:v', 'libx264', '-threads', '2', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
                *quality, '-movflags', '+faststart', '-t', str(duration), '-progress',
                str(directory / 'progress.txt'), str(directory / filename)]
    return command, duration


def start_render(props: dict[str, Any], *, output_filename: str,
                 media_roots: tuple[Path, ...], source_root: Path) -> dict[str, Any]:
    from providers.remotion.api import _resolution_report

    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('Local assembly requires ffmpeg and ffprobe on PATH.')
    render_id = f'local-{uuid.uuid4().hex}'
    directory = _output_root(media_roots) / render_id
    directory.mkdir(parents=True)
    filename = re.sub(r'[^A-Za-z0-9._-]+', '-', Path(output_filename).stem).strip('._-')[:90]
    filename = (filename or 'renderhaus-video') + '.mp4'
    process: subprocess.Popen | None = None
    resolution = _resolution_report(props['renderConfig'].get('resolution', props['renderConfig']))
    try:
        timeout = max(1, float(os.getenv('REMOTION_RENDER_TIMEOUT_SECONDS', '1200')))
        command, duration = _command(props, directory, media_roots=media_roots,
                                     source_root=source_root, filename=filename)
        (directory / 'worker.json').write_text(json.dumps({'command': command, 'timeout': timeout}))
        process = subprocess.Popen([sys.executable, '-m', 'providers.remotion.local_worker', str(directory)],
                                   cwd=source_root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        with _LOCK:
            _PROCESSES[render_id] = process
        (directory / 'job.json').write_text(json.dumps({'filename': filename, 'pid': process.pid,
                                                       'duration': duration, 'fps': props['renderConfig']['fps'],
                                                       'resolution': resolution,
                                                       'timeout': timeout, 'started': time.time()}))
    except Exception:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            with _LOCK:
                _PROCESSES.pop(render_id, None)
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return {'status': 'queued', 'render_id': render_id, 'bucket_name': 'local', 'output_key': '',
            'filename': filename, 'progress': 0.0, 'backend': 'local', **resolution}


def get_progress(render_id: str, *, media_roots: tuple[Path, ...]) -> dict[str, Any]:
    from providers.remotion.api import _media_dimensions, _resolution_report

    if not re.fullmatch(r'local-[0-9a-f]{32}', render_id):
        raise ValueError('Invalid local render id.')
    directory = _output_root(media_roots) / render_id
    if not (directory / 'job.json').is_file():
        raise ValueError('Unknown local render id.')
    job = json.loads((directory / 'job.json').read_text())
    result: dict[str, Any] = {'render_id': render_id, 'bucket_name': 'local', 'backend': 'local',
                              'filename': job['filename'], 'progress': 0.0,
                              **_resolution_report(job.get('resolution'))}
    with _LOCK:
        process = _PROCESSES.get(render_id)
        code = process.poll() if process else None
        if process and code is not None:
            _PROCESSES.pop(render_id, None)
    terminal_file = directory / 'terminal.json'
    if terminal_file.is_file():
        terminal = json.loads(terminal_file.read_text())
        if terminal.get('exit_code') == 0:
            destination = directory / job['filename']
            if destination.is_file() and destination.stat().st_size > 0:
                try:
                    probe = _probe(destination)
                except (ValueError, OSError, subprocess.SubprocessError):
                    probe = {}
                actual = float(probe.get('format', {}).get('duration', 0))
                tolerance = max(.1, 2 / job['fps'])
                video = next((stream for stream in probe.get('streams', [])
                              if stream.get('codec_type') == 'video'), None)
                if video and actual > 0 and abs(actual - job['duration']) <= tolerance:
                    dimensions = _media_dimensions(video)
                    if dimensions:
                        result.update(width=dimensions[0], height=dimensions[1])
                    else:
                        result['width'] = result['height'] = None
                        result['warnings'].append('Rendered output dimensions could not be measured.')
                    return {**result, 'status': 'succeeded', 'output_path': str(destination),
                            'size_bytes': destination.stat().st_size, 'progress': 1.0}
            return {**result, 'status': 'failed', 'error': 'Local ffmpeg output is incomplete or invalid.'}
        return {**result, 'status': 'failed',
                'error': terminal.get('error', 'Local ffmpeg assembly failed; inspect local stderr.txt.')}
    if process is not None and code is None:
        return {**result, 'status': 'queued'}
    if process is None and time.time() - job['started'] < job['timeout']:
        try:
            os.kill(int(job['pid']), 0)
        except ProcessLookupError:
            pass
        else:
            return {**result, 'status': 'queued'}
    return {**result, 'status': 'failed', 'error': 'Local render worker ended without a terminal outcome.'}
