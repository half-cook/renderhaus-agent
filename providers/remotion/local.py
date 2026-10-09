"""Explicit development backend for the shared Remotion timeline document.

Filter semantics verified against https://ffmpeg.org/ffmpeg-filters.html, read 2026-10-09.
System binary only; no FFmpeg or Remotion code is vendored.
"""
from __future__ import annotations

import ipaddress
import json
import os
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

MAX_MEDIA_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 384 * 1024 * 1024
FORMATS = 'mov,matroska,mp3,wav,aac,image2,png_pipe,jpeg_pipe,webp_pipe,ogg,flac'
_PROCESSES: dict[str, subprocess.Popen] = {}
_LOCK = threading.Lock()


def _output_root(media_roots: tuple[Path, ...]) -> Path:
    return media_roots[-1] / 'remotion' / 'local'


def _source(source: str, *, directory: Path, index: int,
            media_roots: tuple[Path, ...], source_root: Path) -> Path:
    parsed = urlsplit(source)
    if not parsed.scheme:
        path = Path(source).expanduser()
        path = (path if path.is_absolute() else source_root / path).resolve()
        if not any(path == root or root in path.parents for root in media_roots):
            raise ValueError('Local render sources must stay inside Renderhaus media roots.')
        if not path.is_file() or not 0 < path.stat().st_size <= MAX_MEDIA_BYTES:
            raise ValueError('Local render sources must be nonempty media files within the size limit.')
        return path
    hosts = set(os.getenv('REMOTION_LOCAL_MEDIA_HOSTS', '').split(',')) - {''}
    if (parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username
            or parsed.password or parsed.port not in {None, 443} or parsed.fragment):
        raise ValueError('Local remote sources require HTTPS on an exact REMOTION_LOCAL_MEDIA_HOSTS host.')
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Local remote media hosts must resolve to public addresses.')
    destination = directory / f'source-{index}.media'
    deadline = time.monotonic() + 120
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


def _command(props: dict[str, Any], directory: Path, *, media_roots: tuple[Path, ...],
             source_root: Path, filename: str) -> tuple[list[str], float]:
    config, document = props['renderConfig'], props['document']
    fps, width, height = int(config['fps']), int(config['width']), int(config['height'])
    duration = int(config['durationInFrames']) / fps
    if not 0 < duration <= 600 or len(document['assets']) > 60:
        raise ValueError('Local renders allow at most 600 seconds and 60 assets.')
    assets = {asset['id']: asset for asset in document['assets']}
    command = ['ffmpeg', '-hide_banner', '-nostdin', '-v', 'error', '-y',
               '-filter_complex_threads', '1', '-f', 'lavfi', '-i',
               f'color=c=black:s={width}x{height}:r={fps}:d={duration:g}']
    filters: list[str] = []
    visual = '0:v'
    audio: list[str] = []
    count = 0
    total_bytes = 0
    for track in document['tracks']:
        for item in track['items']:
            if item['type'] != 'clip':
                raise ValueError('Local assembly does not support titles/subtitles; use the Lambda backend.')
            if (item.get('motion', 'none') != 'none' or item.get('grade', 'none') != 'none'
                    or item.get('scale', 1) != 1 or item.get('rotation', 0) != 0):
                raise ValueError('Local assembly does not support motion/grade/scale/rotation; use Lambda.')
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
                command += ['-loop', '1', '-framerate', str(fps)]
            else:
                command += ['-ss', str(item.get('sourceIn', 0))]
            command += ['-t', str(float(item['duration']) * rate), '-i', str(source)]
            if kind != 'audio':
                fit = item.get('fit', 'cover')
                px, py = float(item.get('positionX', .5)), float(item.get('positionY', .5))
                resize = (f'scale={width}:{height}:force_original_aspect_ratio=increase,'
                          f'crop={width}:{height}:x=(iw-ow)*{px:g}:y=(ih-oh)*{py:g}'
                          if fit == 'cover' else
                          f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
                          f'pad={width}:{height}:x=(ow-iw)*{px:g}:y=(oh-ih)*{py:g}:color=black')
                chain = [f'[{count}:v]setpts=(PTS-STARTPTS)/{rate:g}',
                         f'fps={fps}', resize, 'setsar=1', 'format=rgba']
                opacity = float(item.get('opacity', 1))
                if opacity != 1:
                    chain += [f'colorchannelmixer=aa={opacity:g}']
                for field, direction in [('fadeIn', 'in'), ('fadeOut', 'out')]:
                    length = float(item.get(field, 0))
                    if length:
                        when = 0 if direction == 'in' else max(0, float(item['duration']) - length)
                        chain += [f'fade=t={direction}:st={when:g}:d={length:g}:alpha=1']
                chain += [f'setpts=PTS+{item["start"]:g}/TB[v{count}]']
                filters.append(','.join(chain))
                filters.append(f'[{visual}][v{count}]overlay=eof_action=pass:repeatlast=0'
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
    command += ['-c:v', 'libx264', '-threads', '2', '-preset', 'veryfast', '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart', '-t', str(duration), '-progress',
                str(directory / 'progress.txt'), str(directory / filename)]
    return command, duration


def start_render(props: dict[str, Any], *, output_filename: str,
                 media_roots: tuple[Path, ...], source_root: Path) -> dict[str, Any]:
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('Local assembly requires ffmpeg and ffprobe on PATH.')
    render_id = f'local-{uuid.uuid4().hex}'
    directory = _output_root(media_roots) / render_id
    directory.mkdir(parents=True)
    filename = re.sub(r'[^A-Za-z0-9._-]+', '-', Path(output_filename).stem).strip('._-')[:90]
    filename = (filename or 'renderhaus-video') + '.mp4'
    process: subprocess.Popen | None = None
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
            'filename': filename, 'progress': 0.0, 'backend': 'local'}


def get_progress(render_id: str, *, media_roots: tuple[Path, ...]) -> dict[str, Any]:
    if not re.fullmatch(r'local-[0-9a-f]{32}', render_id):
        raise ValueError('Invalid local render id.')
    directory = _output_root(media_roots) / render_id
    if not (directory / 'job.json').is_file():
        raise ValueError('Unknown local render id.')
    job = json.loads((directory / 'job.json').read_text())
    result: dict[str, Any] = {'render_id': render_id, 'bucket_name': 'local', 'backend': 'local',
                              'filename': job['filename'], 'progress': 0.0}
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
                except ValueError:
                    probe = {}
                actual = float(probe.get('format', {}).get('duration', 0))
                tolerance = max(.1, 2 / job['fps'])
                has_video = any(stream.get('codec_type') == 'video' for stream in probe.get('streams', []))
                if has_video and actual > 0 and abs(actual - job['duration']) <= tolerance:
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
