"""Render bounded real native-Lottie frames and portable local preview artifacts."""
from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import math
from pathlib import Path
import shutil
import tempfile
import time

from PIL import Image

from providers.ffmpeg.api import execute
from providers.lottie.raster import render_frame

MAX_HTML_BYTES = 16 * 1024 * 1024
MAX_FRAME_BYTES = 10 * 1024 * 1024


def _record(path: Path) -> dict:
    payload = path.read_bytes()
    if not 0 < len(payload) <= 16*1024*1024:
        raise ValueError('Preview artifact exceeds the 16 MiB output size limit.')
    return {'path': str(path), 'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)}


def _scrubber(name: str, frames: list[str], fps: float, first: float) -> str:
    title = html.escape(name[:200])
    payload = json.dumps(frames, separators=(',', ':'))
    return f'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Animation preview</title>
<style>body{{margin:2rem auto;padding:0 1rem;max-width:44rem;font:16px system-ui;color:#202124;background:#fafafa}}
.stage{{display:grid;place-items:center;min-height:280px;background:repeating-conic-gradient(#eee 0% 25%,#fff 0% 50%) 0/20px 20px}}
img{{max-width:100%;image-rendering:auto}}input{{width:100%}}button{{padding:.5rem 1rem}}output{{margin-left:1rem}}</style>
<h1>{title}</h1><div class="stage"><img id="frame-image" alt="Animation frame"></div>
<p><button id="play" type="button">Play</button><output id="position" aria-live="off"></output></p>
<label for="frame">Frame</label><input id="frame" type="range" min="0" max="{len(frames)-1}" step="1" value="0">
<p>This preview covers the supported vector subset. The animation file preserves its transparent background.
MP4 previews use a white background. GIF previews use a reduced color palette.</p>
<script>
'use strict';
const frames={payload};
const fps={fps!r}, first={first!r};
const image=document.getElementById('frame-image'), slider=document.getElementById('frame');
const label=document.getElementById('position'), button=document.getElementById('play');
let index=0, playing=false, last=0;
function show(n){{index=Math.max(0,Math.min(frames.length-1,Math.round(n)));slider.value=index;
image.src=frames[index];label.textContent='Frame '+(first+index)+' / '+(first+frames.length-1);}}
const pinned=Number(new URLSearchParams(location.search).get('frame') ?? first);
show(Number.isFinite(pinned)?pinned-first:0);
slider.addEventListener('input',()=>{{playing=false;button.textContent='Play';show(Number(slider.value));}});
button.addEventListener('click',()=>{{playing=!playing;button.textContent=playing?'Pause':'Play';last=0;}});
function tick(now){{if(playing){{if(!last)last=now;const count=Math.floor((now-last)*fps/1000);
if(count){{show((index+count)%frames.length);last+=count*1000/fps;}}}}requestAnimationFrame(tick);}}
requestAnimationFrame(tick);
</script></html>'''


def render_preview(document: dict, directory: Path, *, max_size: int = 256,
                   formats: tuple[str, ...] = ('mp4', 'gif')) -> dict:
    """Return checksummed frames, contact sheet, strip, self-contained scrubber and previews."""
    result = {'ok': False, 'outputs': [], 'not_previewed': [], 'errors': []}
    staging = None
    started = time.monotonic()
    try:
        directory = Path(directory).resolve()
        if not directory.is_dir():
            raise ValueError('Preview requires an existing job directory.')
        if not isinstance(formats, tuple) or set(formats) - {'mp4', 'gif'} or len(formats) != len(set(formats)):
            raise ValueError('Preview formats must be a tuple containing mp4 and/or gif once each.')
        first, last, fps = (document.get(key) for key in ('ip', 'op', 'fr'))
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
               for value in (first, last, fps)):
            raise ValueError('Preview needs finite in/out frames and fps.')
        count = math.ceil(last-first)
        if not 1 <= count <= 600:
            raise ValueError('Preview supports 1 to 600 complete frames.')
        if not 1 <= fps <= 120 or count/fps > 20:
            raise ValueError('Preview supports 1 to 120 fps and at most 20 seconds.')
        initial = render_frame(document, first, max_size=max_size)
        width, height = initial.size
        if count*width*height > 40_000_000:
            raise ValueError('Preview exceeds the 40 million pixel frame budget; reduce max_size or duration.')
        staging = Path(tempfile.mkdtemp(prefix='animation-preview-', dir=directory))
        outputs, inline, samples = [], [], []
        sample_indices = sorted(set(round(index*(count-1)/min(11, max(1, count-1)))
                                    for index in range(min(12, count))))
        frame_bytes = 0
        for index in range(count):
            if time.monotonic()-started > 30:
                raise ValueError('Preview rasterization exceeded its 30 second runtime limit.')
            image = initial if index == 0 else render_frame(document, first+index, max_size=max_size)
            data = io.BytesIO()
            image.save(data, format='PNG', optimize=False, compress_level=9)
            payload = data.getvalue()
            frame_bytes += len(payload)
            if frame_bytes > MAX_FRAME_BYTES:
                raise ValueError('Preview PNG frames exceed the 10 MiB embedded-frame size limit.')
            path = staging / f'frame-{index:06d}.png'
            path.write_bytes(payload)
            outputs.append(path)
            inline.append('data:image/png;base64,'+base64.b64encode(payload).decode('ascii'))
            if index in sample_indices:
                samples.append(image.copy())
        cols = min(4, len(samples))
        rows = math.ceil(len(samples)/cols)
        contact = Image.new('RGBA', (width*cols, height*rows))
        strip = Image.new('RGBA', (width*len(samples), height))
        for index, image in enumerate(samples):
            contact.paste(image, ((index % cols)*width, (index//cols)*height))
            strip.paste(image, (index*width, 0))
        for name, image in [('contact.png', contact), ('strip.png', strip)]:
            path = staging/name
            image.save(path, format='PNG', compress_level=9)
            outputs.append(path)
        scrubber = staging/'preview.html'
        content = _scrubber(str(document.get('nm', 'Animation preview')), inline, fps, first).encode('utf-8')
        if len(content) > MAX_HTML_BYTES:
            raise ValueError('Self-contained preview HTML exceeds the 16 MiB size limit.')
        scrubber.write_bytes(content)
        outputs.append(scrubber)
        metadata = {'width': width, 'height': height, 'frame_count': count, 'fps': fps,
                    'duration_seconds': count/fps, 'sample_frames': [first+index for index in sample_indices],
                    'mp4_background': 'white', 'gif_palette': 'quantized', 'transparent_json': True}
        errors = []
        for format_name in formats:
            encoded = execute('image_sequence_preview', staging, 'frame-000000.png',
                              {'frame_count': count, 'sequence_fps': fps, 'preview_format': format_name})
            if not encoded['ok']:
                errors.append(format_name + ': ' + encoded.get('error', 'Preview encoding failed.'))
            else:
                outputs.extend(Path(record['path']) for record in encoded['outputs'])
        records = [_record(path) for path in outputs]
        if sum(record['bytes'] for record in records) > 64*1024*1024:
            raise ValueError('Combined preview artifacts exceed the 64 MiB output limit.')
        result.update(ok=not errors, outputs=records, scrubber_path=str(scrubber),
                      metadata=metadata, errors=errors, status='incomplete' if errors else 'succeeded')
        return result
    except (ValueError, TypeError, OSError, KeyError, OverflowError) as exc:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        message = str(exc)
        result['errors'].append(message)
        if 'not previewed:' in message:
            result['not_previewed'].append(message.removeprefix('not previewed: '))
        result['status'] = 'not_previewed' if result['not_previewed'] else 'failed'
        return result
