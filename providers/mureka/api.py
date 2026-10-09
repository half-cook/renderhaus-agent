from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

import httpx

from providers.fal import queue
from providers.mureka import contracts

MUSIC_JOB = re.compile(r'mureka:music:(song|instrumental):([A-Za-z0-9_.-]{1,128}):([A-Za-z0-9_-]+)')
AUDIO_FORMATS = {
    '.mp3': ('audio/mpeg', {'mp3'}),
    '.wav': ('audio/wav', {'wav'}),
    '.flac': ('audio/flac', {'flac'}),
    '.ogg': ('audio/ogg', {'ogg'}),
    '.m4a': ('audio/mp4', {'mov', 'mp4', 'm4a', '3gp', '3g2', 'mj2'}),
}
AUDIO_MIME_EXTENSIONS = {
    'audio/mpeg': '.mp3', 'audio/mp3': '.mp3', 'audio/wav': '.wav', 'audio/x-wav': '.wav',
    'audio/wave': '.wav', 'audio/flac': '.flac', 'audio/x-flac': '.flac',
    'audio/ogg': '.ogg', 'application/ogg': '.ogg', 'audio/mp4': '.m4a', 'audio/x-m4a': '.m4a',
}


def dry_run() -> bool:
    return os.getenv('MUREKA_DRY_RUN', 'true').lower() != 'false' or queue.dry_run()


def _identity(tool: str, request_id: str, model: str) -> dict[str, Any]:
    endpoint = contracts.TOOL_ENDPOINTS[tool]
    video = tool == 'generate_lyrics_video'
    kind = 'song' if tool == 'generate_song' else 'instrumental'
    return {
        'job_id': f'{endpoint}:{request_id}' if video else f'mureka:music:{kind}:{model}:{request_id}',
        'provider': 'mureka', 'transport': 'fal', 'endpoint_id': endpoint, 'model': model,
        'mode': tool, 'capability_id': 'mureka_lyrics_video' if video else 'mureka_v95',
        **contracts.TRAINING_METADATA,
    }


def _submit(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from server.billing_rates import mureka_price_cents

    request = contracts.request_for(tool, arguments)
    body = request.fal_body()
    model = contracts.VIDEO_MODEL if tool == 'generate_lyrics_video' else body['model']
    verified = tool == 'generate_lyrics_video' or model == contracts.DEFAULT_MODEL
    cents = mureka_price_cents(tool, arguments) if verified else None
    quote = {'estimated_cost_usd': float(cents / 100) if cents is not None else None,
             'cost_estimate': 'unknown' if cents is None else f'${cents / 100:.3f} provider estimate before Renderhaus fee'}
    if dry_run() or not verified:
        return {
            **_identity(tool, 'dry_' + uuid.uuid4().hex, model), **quote,
            'status': 'dry_run', 'preview_only': True, 'request_preview': body,
            'verification': 'verified official fal schema, read 2026-10-09' if verified else 'UNVERIFIED configured model; live submission blocked',
            'note': 'Preview only. No paid request or generated artifact. MUREKA_DRY_RUN and FAL_DRY_RUN both must be false for verified live models.',
        }
    if cents is None:
        raise ValueError('Mureka cost estimate is unknown; live submission is blocked.')
    payload = queue.submit(contracts.TOOL_ENDPOINTS[tool], body)
    request_id = payload.get('request_id')
    if not isinstance(request_id, str) or not request_id:
        raise RuntimeError('fal did not return a Mureka request_id.')
    queue.request_url(contracts.TOOL_ENDPOINTS[tool], request_id)
    status = queue.mapped_status({'status': 'IN_QUEUE', **payload})
    return {**_identity(tool, request_id, model), **quote,
            'status': 'queued' if status == 'succeeded' else status,
            'error': payload.get('error'), 'error_type': payload.get('error_type'),
            'note': 'Poll the saved job_id. Request download=true to obtain and validate the completed artifact.'}


def generate_song(prompt: str | None = None, lyrics: str | None = None, styles: list[str] | None = None,
                  gender: str | None = None, model: str | None = None) -> dict:
    """Generate a Mureka V9.5 song from lyrics or prompt. Returns a queued handle, not completed audio."""
    return _submit('generate_song', locals())


def generate_instrumental(prompt: str | None = None, instrumental_id: str | None = None,
                          model: str | None = None) -> dict:
    """Generate Mureka instrumental music from prompt or an existing uploaded instrumental ID."""
    return _submit('generate_instrumental', locals())


def generate_lyrics_video(song_id: str | None = None, upload_audio_id: str | None = None,
                          layout: str = 'layout_1', aspect_ratio: str = '9:16',
                          background_id: str | None = None, cover_url: str | None = None,
                          title: str | None = None, lyrics_start_row: int | None = None,
                          lyrics_end_row: int | None = None, selection_start: int | None = None,
                          selection_end: int | None = None) -> dict:
    """Make a lyrics video from a Mureka song/upload ID. Paid video requires a separate cost approval."""
    return _submit('generate_lyrics_video', locals())


def _audio_format(audio: dict[str, Any]) -> tuple[str, str]:
    mime, filename = audio.get('content_type'), audio.get('file_name')
    extension = None
    if mime is not None:
        if not isinstance(mime, str):
            raise RuntimeError('Mureka audio content_type must identify a supported audio format.')
        extension = AUDIO_MIME_EXTENSIONS.get(mime.split(';', 1)[0].strip().lower())
        if extension is None:
            raise RuntimeError('Mureka audio content_type is unsupported or unknown.')
    if filename is not None:
        if not isinstance(filename, str):
            raise RuntimeError('Mureka audio file_name must be a string.')
        named_extension = Path(filename).suffix.lower()
        if named_extension not in AUDIO_FORMATS:
            raise RuntimeError('Mureka audio file_name has an unsupported or unknown extension.')
        if extension is not None and named_extension != extension:
            raise RuntimeError('Mureka audio MIME type and filename contradict one another.')
        extension = named_extension
    if extension is None:
        raise RuntimeError('Mureka audio format is unknown; supply documented content_type or file_name metadata.')
    return extension, AUDIO_FORMATS[extension][0]


def _audio_path(job_id: str, extension: str) -> Path:
    return Path(os.getenv('RENDERHAUS_MEDIA_DIR', '.renderhaus/media')).expanduser() / 'audio' / 'mureka' / (hashlib.sha256(job_id.encode()).hexdigest() + extension)


def _validate_audio(path: Path, extension: str) -> None:
    error = RuntimeError('Mureka returned invalid or truncated audio.')
    if shutil.which('ffprobe'):
        try:
            result = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)], capture_output=True, text=True, timeout=30, check=True)
            probe = json.loads(result.stdout)
            duration = float(probe['format']['duration'])
            formats = set(probe['format']['format_name'].split(','))
            streams = probe['streams']
            if (not math.isfinite(duration) or duration <= 0
                    or not formats & AUDIO_FORMATS[extension][1]
                    or not any(stream.get('codec_type') == 'audio' for stream in streams)):
                raise error
            return
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            raise error from None
    if extension != '.mp3':
        raise RuntimeError('ffprobe is required to validate non-MP3 Mureka audio.')
    data = path.read_bytes()
    offset = 0
    if data.startswith(b'ID3'):
        if len(data) < 10 or any(byte & 0x80 for byte in data[6:10]):
            raise error
        offset = 10 + sum(byte << shift for byte, shift in zip(data[6:10], (21, 14, 7, 0)))
        if data[5] & 0x10:
            offset += 10
    frames = 0
    while offset + 4 <= len(data):
        header = int.from_bytes(data[offset:offset + 4], 'big')
        version, layer, bitrate_index, rate_index = (header >> 19) & 3, (header >> 17) & 3, (header >> 12) & 15, (header >> 10) & 3
        if header >> 21 != 0x7FF or version == 1 or layer != 1 or bitrate_index in (0, 15) or rate_index == 3:
            break
        bitrates = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320) if version == 3 else (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
        sample_rate = (44100, 48000, 32000)[rate_index] // (1 if version == 3 else 2 if version == 2 else 4)
        size = (144000 if version == 3 else 72000) * bitrates[bitrate_index] // sample_rate + ((header >> 9) & 1)
        if offset + size > len(data):
            raise error
        offset += size
        frames += 1
    if frames < 2:
        raise error


def _download_audio(url: str, path: Path, extension: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.tmp', delete=False) as file:
            temporary = Path(file.name)
            with httpx.stream('GET', url, follow_redirects=True, timeout=120) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    file.write(chunk)
        _validate_audio(temporary, extension)
        temporary.replace(path)
    except httpx.HTTPError:
        raise RuntimeError('Mureka audio download failed at the HTTP boundary.') from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def get_music_task(job_id: str, download: bool = False) -> dict:
    """Poll the exact saved Mureka music job once. Optionally validate and persist completed audio."""
    contracts.PollRequest.model_validate(locals())
    match = MUSIC_JOB.fullmatch(job_id)
    if not match:
        raise ValueError('job_id must be the handle returned by a Mureka music submit tool.')
    kind, model, request_id = match.groups()
    tool = 'generate_song' if kind == 'song' else 'generate_instrumental'
    endpoint = contracts.TOOL_ENDPOINTS[tool]
    queue.request_url(endpoint, request_id)
    identity = _identity(tool, request_id, model)
    if dry_run() or request_id.startswith('dry_') or model != contracts.DEFAULT_MODEL:
        return {**identity, 'status': 'dry_run', 'preview_only': True, 'downloaded': False}
    payload = queue.status(endpoint, request_id)
    status = queue.mapped_status(payload)
    if status != 'succeeded':
        return {**identity, 'status': status, 'error': payload.get('error'), 'error_type': payload.get('error_type'), 'queue_position': payload.get('queue_position')}
    try:
        result = queue.result(endpoint, request_id)
    except queue.FalAPIError as exc:
        if exc.status_code not in {400, 422}:
            raise
        return {**identity, 'status': 'failed', 'error': str(exc)}
    if result.get('error') or result.get('error_type'):
        return {**identity, 'status': 'failed', 'error': result.get('error'), 'error_type': result.get('error_type')}
    audio = result.get('audio')
    url = audio.get('url') if isinstance(audio, dict) else None
    try:
        if not isinstance(url, str):
            raise ValueError('missing audio URL')
        contracts.validate_https(url)
    except ValueError:
        raise RuntimeError('Completed Mureka result did not contain a public HTTPS audio.url.') from None
    duration = result.get('duration')
    if duration is not None and (type(duration) is not int or duration <= 0):
        raise RuntimeError('Mureka audio duration must be positive milliseconds.')
    song_id = result.get('song_id')
    lyrics_sections = result.get('lyrics_sections')
    if song_id is not None and (not isinstance(song_id, str) or not song_id.strip()):
        raise RuntimeError('Mureka song_id must be a nonempty string.')
    if lyrics_sections is not None and not isinstance(lyrics_sections, list):
        raise RuntimeError('Mureka lyrics_sections must be an array.')
    extension, content_type = _audio_format(audio)
    path = _audio_path(job_id, extension)
    if download:
        if extension != '.mp3' and not shutil.which('ffprobe'):
            raise RuntimeError('ffprobe is required to validate non-MP3 Mureka audio.')
        if path.exists():
            _validate_audio(path, extension)
        else:
            _download_audio(url, path, extension)
    return {**identity, 'status': 'succeeded', 'audio_url': url, 'audio_content_type': content_type, 'song_id': song_id,
            'duration': duration, 'duration_ms': duration, 'duration_seconds': duration / 1000 if duration is not None else None,
            'lyrics_sections': lyrics_sections, 'downloaded': bool(download and path.exists()),
            'output_path': str(path) if download and path.exists() else None}


def get_video_task(job_id: str, download: bool = False) -> dict:
    """Poll the exact saved lyrics-video handle through fal without creating another job."""
    contracts.PollRequest.model_validate(locals())
    endpoint, separator, request_id = job_id.partition(':')
    if not separator or endpoint != contracts.VIDEO_ENDPOINT:
        raise ValueError('job_id must be the handle returned by Mureka lyrics-video submit.')
    queue.request_url(endpoint, request_id)
    identity = _identity('generate_lyrics_video', request_id, contracts.VIDEO_MODEL)
    if dry_run() or request_id.startswith('dry_'):
        return {**identity, 'status': 'dry_run', 'preview_only': True, 'downloaded': False}
    from providers.fal import api as fal_api
    from providers.topaz.api import _validate_mp4

    result = fal_api._poll_video_task(job_id, endpoint, request_id, download=download)
    if result.get('downloaded'):
        path = Path(result['output_path'])
        try:
            _validate_mp4(path)
        except RuntimeError:
            path.unlink(missing_ok=True)
            raise
    return {**result, **identity}


def list_mureka_models() -> dict:
    """List verified Mureka fal capabilities and commercial terms without credentials or HTTP."""
    return {
        'provider': 'mureka', 'transport': 'fal', 'dry_run': dry_run(), 'read_date': '2026-10-09',
        **contracts.TRAINING_METADATA,
        'models': [{
            'model': contracts.VIDEO_MODEL if tool == 'generate_lyrics_video' else contracts.DEFAULT_MODEL,
            'endpoint_id': endpoint, 'capability_id': 'mureka_lyrics_video' if tool == 'generate_lyrics_video' else 'mureka_v95',
            'api_url': f'https://fal.ai/models/{endpoint}/api', 'pricing_url': f'https://fal.ai/models/{endpoint}',
            **contracts.TRAINING_METADATA,
        } for tool, endpoint in contracts.TOOL_ENDPOINTS.items()],
        'note': 'Supplied audio and background IDs must already belong to the fal-hosted Mureka account. Upload preparation is not exposed by these tools.',
    }


TOOL_HANDLERS = {
    'generate_song': generate_song, 'generate_instrumental': generate_instrumental,
    'generate_lyrics_video': generate_lyrics_video, 'get_music_task': get_music_task,
    'get_video_task': get_video_task, 'list_mureka_models': list_mureka_models,
}
