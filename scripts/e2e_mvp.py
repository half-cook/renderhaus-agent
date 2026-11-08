#!/usr/bin/env python3
"""Reproduce the eight-second Seedance/fal + Fish + Remotion acceptance film.

Dry by default. --live authorizes two video generations, one narration and one
Remotion Lambda render. --resume reuses receipts; uncertain submissions never retry.
--live --resume --retry-assembly retries only a confirmed failed render, preserving sources.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers.fish_audio import api as fish
from providers.remotion import api as remotion
from providers.remotion.capabilities import validate_document
from providers.seedance import api as seedance
from providers.seedance.contracts import MODEL_25

NARRATION = "Across the dark, one light guides the way home."
SHOTS = (
    "Cinematic wide shot of a solitary white lighthouse on a rugged Atlantic cliff at blue hour. "
    "Its warm beacon sweeps across the dark ocean. Slow forward dolly, realistic wind and waves, "
    "consistent amber and navy palette. No people, no text, no logos. One uninterrupted shot.",
    "Cinematic close shot of the glowing amber Fresnel lens inside a white coastal lighthouse "
    "at blue hour, dark Atlantic ocean visible beyond the glass. Slow orbit around the lens, "
    "realistic warm reflections, amber and navy palette. No people, no text, no logos. One shot.",
)


def save(path: Path, value: dict) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def configure(out: Path, *, live: bool, secrets: bool) -> None:
    if secrets:
        from server.secrets import apply_secret_map, fetch_secret_map

        apply_secret_map(fetch_secret_map('renderhaus/app'))
    # Apply the explicit run mode after secrets; nested config cannot reload it.
    os.environ.update(RENDERHAUS_SECRETS_NAME='', RENDERHAUS_SECRETS_ARN='',
                      RENDERHAUS_MEDIA_DIR=str(out / 'media'),
                      SEEDANCE_TRANSPORT='fal', SEEDANCE_FAL_REGION='us',
                      SEEDANCE_MODEL=MODEL_25, FISH_AUDIO_MODEL=fish.DEFAULT_MODEL,
                      REMOTION_RENDER_BACKEND='lambda')
    for flag in ('SEEDANCE_DRY_RUN', 'FAL_DRY_RUN', 'FISH_AUDIO_DRY_RUN', 'REMOTION_DRY_RUN'):
        os.environ[flag] = 'false' if live else 'true'
    if live:
        if not os.getenv('FAL_KEY') or not (os.getenv('FISH_API_KEY') or os.getenv('FISH_AUDIO_API_KEY')):
            raise ValueError('Live run requires fal and Fish credentials; use --secrets to load them.')
        remotion.load_remotion_settings()
        if not shutil.which('ffprobe') or not shutil.which('ffmpeg'):
            raise ValueError('Live artifact verification requires ffprobe and ffmpeg.')


def timeline(videos: list[str], audio: str, duration: float, *, preview: bool) -> dict:
    return {
        'title': 'Keep the light', 'aspect_ratio': '16:9', 'output_filename': 'keep-the-light.mp4',
        **({'fps': 24, 'output_resolution': '720p'} if preview else {}),
        'visuals': [dict(kind='video', output_path=source, start_seconds=i * 4,
                         duration_seconds=4, volume=0, transition='fade')
                    for i, source in enumerate(videos)],
        'audio_tracks': [dict(output_path=audio, start_seconds=1, duration_seconds=duration,
                             volume=1, fade_in_seconds=0.05, fade_out_seconds=0.15)],
        'text_overlays': [dict(text='KEEP THE LIGHT', start_seconds=0.5, duration_seconds=2,
                               position='top', font_size=54),
                          dict(text='A WAY HOME', start_seconds=6, duration_seconds=1.8,
                               position='top', font_size=54)],
        'subtitles': [dict(text=NARRATION, start_seconds=1, duration_seconds=duration,
                           position='bottom', font_size=32, background_color='#00000099')],
    }


def submit_once(receipt: dict, path: Path, name: str, call, *, resume: bool = False) -> dict:
    if name in receipt['steps']:
        step = receipt['steps'][name]
        if step['status'] == 'submitting':
            raise ValueError(f'{name}: submission is uncertain; reconcile provider history before continuing.')
        return step
    if resume:
        raise ValueError(f'{name}: no saved submission; resume never regenerates source media.')
    receipt['steps'][name] = {'status': 'submitting'}
    save(path, receipt)
    result = call()
    # Only durable handles and local paths; never save signed URLs or credentials.
    step = {key: result[key] for key in ('status', 'job_id', 'render_id', 'bucket_name',
                                       'output_key', 'output_path') if result.get(key) is not None}
    if not (step.get('job_id') or step.get('render_id')):
        raise ValueError(f'{name}: provider returned no durable handle.')
    receipt['steps'][name] = step
    save(path, receipt)
    return step


def poll(call, *, deadline: float, label: str = 'provider') -> dict:
    previous_status = None
    while True:
        result = call()
        if result.get('status') != previous_status:
            previous_status = result.get('status')
            print(f'{label}: {previous_status}', file=sys.stderr, flush=True)
        if result.get('status') == 'succeeded':
            return result
        if result.get('status') in {'failed', 'error', 'cancelled', 'canceled', 'dry_run'}:
            raise ValueError('Saved provider job did not succeed; paid retries are disabled.')
        if time.monotonic() >= deadline:
            raise TimeoutError('Saved jobs remain resumable after the polling deadline.')
        time.sleep(min(5, max(0, deadline - time.monotonic())))


def probe(path: Path) -> dict:
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                             '-of', 'json', str(path)], check=True, capture_output=True,
                            text=True, timeout=30)
    return json.loads(result.stdout)


def frame_rate(video: dict) -> Fraction:
    try:
        rate = Fraction(video.get('avg_frame_rate') or video.get('r_frame_rate') or '0')
    except (ValueError, ZeroDivisionError, TypeError) as exc:
        raise ValueError('Video frame rate is missing or invalid.') from exc
    if not 0 < rate <= 240:
        raise ValueError('Video frame rate must be greater than zero and at most 240.')
    return rate


def verify_source(path: Path) -> Fraction:
    metadata = probe(path)
    video = next((s for s in metadata['streams'] if s.get('codec_type') == 'video'), {})
    rate = frame_rate(video)
    duration = float(video.get('duration') or metadata.get('format', {}).get('duration') or 0)
    if not math.isfinite(duration) or duration < 4 - 1 / float(rate) - 1e-6:
        raise ValueError('Source video is shorter than four seconds minus one frame; assembly was not submitted.')
    return rate


def verify(path: Path, *, narration_seconds: float = 7, expected_fps: Fraction | str | None = None) -> dict:
    metadata = probe(path)
    video = next(s for s in metadata['streams'] if s.get('codec_type') == 'video')
    audio = next((s for s in metadata['streams'] if s.get('codec_type') == 'audio'), None)
    if audio is None:
        raise ValueError('Final MP4 has no narration audio stream.')
    if video.get('codec_name') != 'h264' or audio.get('codec_name') != 'aac':
        raise ValueError('Final MP4 must contain H.264 video and AAC narration.')
    rate = frame_rate(video)
    if expected_fps is not None and rate != Fraction(expected_fps):
        raise ValueError('Final MP4 frame rate does not match the primary source video.')
    duration = float(metadata['format']['duration'])
    if abs(duration - 8) > 0.2 or video['width'] < 1280 or video['height'] < 720:
        raise ValueError('Final MP4 does not meet the eight-second, 720p acceptance target.')
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'null', '-'],
                   check=True, capture_output=True, timeout=60)
    pcm = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-ss', '1',
                          '-t', str(narration_seconds), '-map', '0:a:0', '-ac', '1',
                          '-ar', '8000', '-f', 's16le', '-'],
                         check=True, capture_output=True, timeout=30).stdout
    samples = [sample[0] for sample in struct.iter_unpack('<h', pcm)]
    if not samples or sum(sample * sample for sample in samples) / len(samples) < 32 ** 2:
        raise ValueError('Final MP4 narration is silent or inaudible.')
    return dict(width=video['width'], height=video['height'], fps=video['r_frame_rate'],
                duration_seconds=duration, sha256=hashlib.sha256(path.read_bytes()).hexdigest())


@contextmanager
def directory_lock(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    # Keep this inode: deleting it would let a second process lock a replacement.
    with (out / '.run.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('This output directory already has an active MVP run.') from exc
        yield


def retry_failed_assembly(receipt: dict, path: Path) -> None:
    previous = receipt['steps'].get('assembly', {})
    if previous.get('status') == 'submitting' or not previous.get('render_id') or not previous.get('bucket_name'):
        raise ValueError('Assembly submission is missing or uncertain; reconcile provider history before retrying.')
    progress = remotion.get_render_progress(previous['render_id'], previous['bucket_name'],
                                            previous.get('output_key'), download=False)
    if progress.get('status') != 'failed':
        raise ValueError('Assembly retry requires a definitively failed saved render; no new render was submitted.')
    receipt.setdefault('assembly_attempts', []).append({**previous, 'status': 'failed'})
    del receipt['steps']['assembly']
    save(path, receipt)


def run(out: Path, *, live: bool = False, resume: bool = False, secrets: bool = False,
        retry_assembly: bool = False,
        timeout_seconds: int = 1800) -> dict:
    if timeout_seconds <= 0 or resume and not live:
        raise ValueError('Use a positive timeout; --resume requires --live.')
    if retry_assembly and not (live and resume):
        raise ValueError('--retry-assembly requires --live --resume.')
    out = out.resolve()
    with directory_lock(out):
        return _run_locked(out, live=live, resume=resume, secrets=secrets, retry_assembly=retry_assembly,
                           timeout_seconds=timeout_seconds)


def _run_locked(out: Path, *, live: bool, resume: bool, secrets: bool, retry_assembly: bool,
                timeout_seconds: int) -> dict:
    path = out / 'receipt.json'
    if resume:
        receipt = json.loads(path.read_text())
        if receipt.get('version') != 1 or receipt.get('mode') != 'live':
            raise ValueError('Resume requires a live MVP receipt from this script.')
    else:
        if any(entry.name != '.run.lock' for entry in out.iterdir()):
            raise ValueError('Use an empty output directory, or --live --resume for saved jobs.')
        out.mkdir(parents=True, exist_ok=True)
        receipt = {'version': 1, 'mode': 'live' if live else 'dry_run', 'steps': {}}
    configure(out, live=live, secrets=secrets)
    save(path, receipt)
    if retry_assembly:
        retry_failed_assembly(receipt, path)
    deadline = time.monotonic() + timeout_seconds
    shots = [submit_once(receipt, path, f'video-{i + 1}', lambda prompt=prompt:
                         seedance.text_to_video(prompt, duration_seconds=4, aspect_ratio='16:9',
                                                resolution='720p', generate_audio=False), resume=resume)
             for i, prompt in enumerate(SHOTS)]
    voice = submit_once(receipt, path, 'narration', lambda: fish.generate_speech(NARRATION), resume=resume)
    if live:
        videos = []
        source_rates = []
        for index, shot in enumerate(shots):
            result = poll(lambda shot=shot: seedance.get_video_task(shot['job_id'], download=True),
                          deadline=deadline, label=f'video-{index + 1}')
            videos.append(result['output_path'])
            source_rates.append(verify_source(Path(result['output_path'])))
        audio = Path(voice['output_path'])
        duration = float(probe(audio)['format']['duration'])
        if not 0 < duration <= 7:
            raise ValueError('Narration does not fit the film; preserve source jobs and review the timing.')
    else:
        videos = [str(out / 'media' / f'preview-{i}.mp4') for i in (1, 2)]
        audio, duration = Path(voice['output_path']), 5
    arguments = timeline(videos, str(audio), duration, preview=not live)
    props = remotion.build_timeline_props(**{k: v for k, v in arguments.items() if k != 'output_filename'},
                                         measure_local=live)
    validate_document(props, 'lambda')
    save(out / 'timeline.json', props)
    rendered = submit_once(receipt, path, 'assembly', lambda: remotion.render_timeline(**arguments))
    if not live:
        result = {'status': 'dry_run', 'adapter_statuses': [s['status'] for s in [*shots, voice, rendered]],
                  'duration_seconds': props['renderConfig']['durationInFrames'] / props['renderConfig']['fps'],
                  'note': 'Adapters and timeline validated. No paid calls or video artifact.'}
    else:
        final = poll(lambda: remotion.get_render_progress(rendered['render_id'], rendered['bucket_name'],
                                                        rendered.get('output_key'), download=True),
                     deadline=deadline, label='assembly')
        shutil.copyfile(final['output_path'], out / 'final.mp4')
        result = {'status': 'completed', 'artifact': 'final.mp4',
                  **verify(out / 'final.mp4', narration_seconds=duration, expected_fps=source_rates[0]),
                  'source_resolution': final.get('source_resolution'), 'warnings': final.get('warnings', []),
                  'browser_e2e': 'pending: operator driver does not exercise Studio'}
    save(out / 'summary.json', result)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--retry-assembly', action='store_true',
                        help='With --live --resume, retry only a provider-confirmed failed assembly; never regenerate sources.')
    parser.add_argument('--secrets', action='store_true', help='Load renderhaus/app from AWS Secrets Manager.')
    parser.add_argument('--timeout-seconds', type=int, default=1800)
    args = parser.parse_args(argv)
    try:
        result = run(**vars(args))
    except Exception as exc:
        # Provider errors can contain signed URLs or request data. Receipts preserve recovery handles.
        result = {'status': 'failed', 'error_type': type(exc).__name__,
                  'reason': str(exc) if isinstance(exc, (ValueError, TimeoutError)) else
                  'Provider or verification failed. Inspect saved receipt; do not repeat paid submissions.'}
        print(json.dumps(result))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
