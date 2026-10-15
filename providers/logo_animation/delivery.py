"""Approval-gated logo plans for the existing local Remotion template mechanism."""
from __future__ import annotations

import hashlib
import json
import math
import re

from providers.ffmpeg.sandbox import job_directory
from providers.logo_animation.contracts import MotionOptions
from providers.logo_animation.motion import finite, motion_spec

FIELDS = {'name', 'logo_job_id', 'logo_path', 'svg_sha256', 'duration_seconds', 'style',
          'personality', 'idle_loop', 'background_color'}


def logo_template_plan(raw: dict, *, aspect_ratio: str, fps: float, width: int, height: int) -> dict:
    from providers.logo_animation.api import vector_bundle
    from providers.logo_animation.geometry import parse_svg

    if not isinstance(raw, dict) or set(raw) - FIELDS or raw.get('name') != 'logo-animation':
        raise ValueError('Logo template contains unsupported fields.')
    if not re.fullmatch(r'[0-9a-f]{64}', raw.get('svg_sha256', '')):
        raise ValueError('Logo template requires the approved SVG checksum.')
    options = MotionOptions.model_validate({key: raw[key] for key in MotionOptions.model_fields if key in raw}).model_dump()
    finite(fps, 12, 60)
    if int(fps) != fps or aspect_ratio not in {'16:9', '9:16', '1:1', '4:5', '2.39:1'}:
        raise ValueError('Logo template requires an integer frame rate and supported aspect.')
    if any(type(n) is not int or n < 2 or n > 2048 or n % 2 for n in (width, height)) or width*height > 4_194_304:
        raise ValueError('Logo canvas requires even dimensions up to 2048 and 4194304 pixels.')
    directory = job_directory(raw.get('logo_job_id'))
    svg, manifest = vector_bundle(directory, raw.get('logo_path'), approved=True)
    if manifest['svg_sha256'] != raw['svg_sha256']:
        raise ValueError('Logo template checksum differs from static vector approval.')
    spec = motion_spec(svg, **{key: options[key] for key in ('duration_seconds', 'style', 'personality', 'idle_loop')})
    geometry = parse_svg(svg)
    empty_box = {'x': .1, 'y': .1, 'width': .8, 'height': .8}
    return {'name': 'logo-animation', 'duration_seconds': options['duration_seconds'],
            'fps': int(fps), 'width': width, 'height': height, 'aspect_ratio': aspect_ratio,
            'background_color': options['background_color'], 'svg': svg, 'geometry': geometry,
            'motion_spec': spec, 'svg_sha256': manifest['svg_sha256'],
            'motion_spec_sha256': hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest(),
            'source_resolution': {'width': geometry['width'], 'height': geometry['height']},
            'layout': {key: empty_box.copy() for key in ('safe', 'art', 'waveform', 'captions', 'identity', 'progress')},
            'captions': [], 'correction_flags': [], 'warnings': [], 'typography': {'identity': 1, 'captions': []},
            'request': dict(raw)}


def validate_logo_arguments(arguments: dict) -> None:
    from providers.remotion.api import render_backend

    if render_backend() != 'local':
        raise ValueError('Logo animation requires the local worker. Lambda is refused to keep supplied logos private.')
    if any(arguments.get(field) for field in ('visuals', 'audio_tracks', 'text_overlays', 'subtitles', 'subtitles_srt')):
        raise ValueError('Logo template owns its composition. Custom media and overlays require a separate approved assembly.')
    raw = arguments['template']
    logo_template_plan(raw, aspect_ratio=arguments.get('aspect_ratio', '9:16'),
                       fps=arguments.get('fps') or 30, width=128, height=128)


def build_logo_props(title: str, raw: dict, *, aspect_ratio: str, fps: float,
                     output_resolution: str, video_bitrate: int | None) -> dict:
    from providers.logo_animation.api import vector_bundle
    from providers.logo_animation.geometry import parse_svg
    from providers.remotion.api import choose_canvas

    svg, _ = vector_bundle(job_directory(raw['logo_job_id']), raw['logo_path'], approved=True)
    geometry = parse_svg(svg)
    if output_resolution == 'source':
        ratio_width, ratio_height = {'16:9': (16, 9), '9:16': (9, 16), '1:1': (1, 1),
                                     '4:5': (4, 5), '2.39:1': (239, 100)}[aspect_ratio]
        unit = max(1, math.ceil(max(geometry['width']/ratio_width, geometry['height']/ratio_height)/2))*2
        width, height = ratio_width*unit, ratio_height*unit
    else:
        width, height = choose_canvas(aspect_ratio, [], output_resolution)
    plan = logo_template_plan(raw, aspect_ratio=aspect_ratio, fps=fps, width=width, height=height)
    upscaled = width*.7 > geometry['width'] or height*.7 > geometry['height']
    warnings = ([f'Canvas resampled from raster reference {geometry["width"]}x{geometry["height"]}; vector edges scale cleanly, no added source detail.'] if upscaled else [])
    return {'template': plan, 'document': {'id': 'agent-render', 'name': title[:160], 'assets': [], 'tracks': []},
            'renderConfig': {'width': width, 'height': height, 'fps': fps,
                'durationInFrames': math.ceil(plan['duration_seconds']*fps-1e-9),
                'videoBitrate': video_bitrate, 'crf': None if video_bitrate else 18,
                'resolution': {'width': width, 'height': height, 'source_resolution': plan['source_resolution'],
                               'upscaled': upscaled, 'warnings': warnings}}}
