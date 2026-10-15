from __future__ import annotations

from pathlib import Path

from PIL import Image

from providers.ffmpeg.commands import Command, THREADS, _input
from providers.ffmpeg.sandbox import MAX_OUTPUT_BYTES, input_file, output_file


def build(directory: Path, source: Path, params: dict) -> list[Command]:
    if source.name != 'frame-000000.png':
        raise ValueError('Image sequence must start with frame-000000.png.')
    size = None
    total = 0
    for index in range(params['frame_count']):
        path = source.parent / f'frame-{index:06d}.png'
        path = input_file(directory, path.relative_to(directory).as_posix(), max_bytes=2*1024*1024)
        total += path.stat().st_size
        with Image.open(path) as image:
            if image.format != 'PNG' or image.mode not in ('RGB', 'RGBA'):
                raise ValueError('Image sequence requires RGB or RGBA PNG frames.')
            if not 1 <= image.width <= 512 or not 1 <= image.height <= 512:
                raise ValueError('Image sequence dimensions must fit within 512 by 512.')
            if size is None:
                size = image.size
            if size != image.size:
                raise ValueError('Image sequence dimensions must match.')
    if (params['frame_count']/params['sequence_fps'] > 20 or total > 16*1024*1024
            or size[0]*size[1]*params['frame_count'] > 40_000_000):
        raise ValueError('Image sequence exceeds 20 seconds, 16 MiB or 40 million pixels.')
    output = output_file(directory, 'animation-preview', '.' + params['preview_format'])
    pattern = _input(directory, source.parent / 'frame-%06d.png')
    argv = ['ffmpeg', '-nostdin', '-hide_banner', '-v', 'error', '-n',
            '-filter_threads', str(THREADS), '-filter_complex_threads', str(THREADS),
            '-threads', str(THREADS), '-protocol_whitelist', 'file,pipe',
            '-format_whitelist', 'image2', '-f', 'image2', '-framerate', str(params['sequence_fps']),
            '-start_number', '0', '-i', pattern, '-frames:v', str(params['frame_count']), '-an']
    if params['preview_format'] == 'mp4':
        width, height = size
        graph = (f'color=c=white:s={width}x{height}:r={params["sequence_fps"]}[bg];'
                 '[bg][0:v]overlay=shortest=1,format=rgb24,'
                 'pad=ceil(iw/2)*2:ceil(ih/2)*2:color=white,format=yuv420p[out]')
        argv += ['-filter_complex', graph, '-map', '[out]', '-c:v', 'libx264',
                 '-preset', 'veryfast', '-crf', '18', '-movflags', '+faststart']
    else:
        argv += ['-vf', 'split[a][b];[a]palettegen=reserve_transparent=1[p];[b][p]paletteuse=dither=none',
                 '-loop', '0']
    argv += ['-threads', str(THREADS), '-map_metadata', '-1', '-fs', str(MAX_OUTPUT_BYTES),
             './' + output.name]
    return [Command(argv, [output], {'frame_count': params['frame_count'],
                                    'fps': params['sequence_fps'], 'width': size[0], 'height': size[1]})]
