"""Declarative logo choreography, local previews and probes of observed motion."""
from __future__ import annotations

import json
import math

import numpy as np
from PIL import Image

from providers.logo_animation.geometry import parse_svg, render_svg

STYLES = ('reveal', 'splash', 'loader', 'idle-hover')


def finite(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f'Expected a finite number in {low}..{high}.')
    return float(value)


def ease(progress: float, token: str) -> float:
    t = min(1, max(0, finite(progress, -100, 100)))
    if token == 'settle':
        return t*t*(3-2*t)
    if token == 'enter':
        return 1-(1-t)**3
    if token == 'linear':
        return t
    raise ValueError('Unknown easing token.')


def motion_spec(svg: str, *, duration_seconds=2, style='reveal', personality=None,
                idle_loop=False) -> dict:
    finite(duration_seconds, 1, 3)
    if style not in STYLES or not isinstance(idle_loop, bool):
        raise ValueError('Unknown motion style or invalid idle_loop.')
    personality = personality if personality is not None else ['precise', 'calm', 'confident']
    if not isinstance(personality, list) or not 1 <= len(personality) <= 3:
        raise ValueError('Provide one to three personality words.')
    import re
    if any(not isinstance(word, str) or not re.fullmatch(r'[A-Za-z][A-Za-z -]{0,31}', word) for word in personality):
        raise ValueError('Personality words require short plain text.')
    geometry = parse_svg(svg)
    duration = duration_seconds*1000
    count = len(geometry['parts'])
    timeline = [{'part': part['id'], 'start_ms': round(duration*(.15 + i/max(1, count-1)*.12), 3),
                 'end_ms': round(duration*(.72 + i/max(1, count-1)*.16), 3), 'easing': 'settle',
                 'paint': 'fill', 'draw_order': i} for i, part in enumerate(geometry['parts'])]
    spec = {'version': 1, 'duration_seconds': duration_seconds, 'style': style,
            'personality': personality, 'idle_loop': idle_loop, 'timeline': timeline,
            'principles': ['staging', 'anticipation', 'slow in/out', 'overlap', 'timing', 'appeal'],
            'easing_tokens': {'settle': '3t^2 - 2t^3', 'enter': '1 - (1-t)^3'},
            'final_frame': 'approved static vector; identity transform and opacity 1',
            'source_width': geometry['width'], 'source_height': geometry['height']}
    validate_motion_spec(spec)
    return spec


def validate_motion_spec(spec: dict) -> None:
    if not isinstance(spec, dict) or spec.get('version') != 1:
        raise ValueError('Motion specification version must be 1.')
    duration = finite(spec.get('duration_seconds'), 1, 3)*1000
    if spec.get('style') not in STYLES or not isinstance(spec.get('idle_loop'), bool):
        raise ValueError('Motion specification has invalid style or idle loop.')
    rows = spec.get('timeline')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
        raise ValueError('Motion specification requires 1..32 timeline rows.')
    parts = set()
    previous = -1
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'part', 'start_ms', 'end_ms', 'easing', 'paint', 'draw_order'}:
            raise ValueError('Motion timeline fields are invalid.')
        start = finite(row['start_ms'], 0, duration)
        end = finite(row['end_ms'], 0, duration)
        if end <= start or start < previous or row['part'] in parts or row['easing'] not in {'settle', 'enter'}:
            raise ValueError('Motion timeline must stage unique parts inside the duration.')
        if row['paint'] != 'fill' or row['draw_order'] != len(parts):
            raise ValueError('Automatic motion requires ordered filled outlines.')
        previous = start
        parts.add(row['part'])


def state_at(spec: dict, time_ms: float) -> list[dict]:
    states = []
    for row in spec['timeline']:
        t = min(1, max(0, (time_ms-row['start_ms'])/(row['end_ms']-row['start_ms'])))
        p = ease(t, row['easing'])
        if spec['style'] == 'loader':
            scale, opacity, y = 1 + .025*math.sin(p*math.tau)**2, 1, 0
        else:
            initial = .72 if spec['style'] == 'splash' else .96
            scale, opacity = initial+(1-initial)*p, p
            y = (1-p)*spec['source_height']*.035 if spec['style'] != 'splash' else 0
        if t == 1:
            scale, opacity, y = 1, 1, 0
        states.append({'part': row['part'], 'x': 0, 'y': y, 'scale': scale, 'opacity': opacity})
    return states


def render_frame(svg: str, spec: dict, frame: int, fps: float, width: int, height: int,
                 background='#101820', *, static=False) -> Image.Image:
    states = None if static else state_at(spec, frame/fps*1000)
    geometry = parse_svg(svg)
    scale = min(width/geometry['width'], height/geometry['height'])*.7
    logo_size = (max(1, round(geometry['width']*scale)), max(1, round(geometry['height']*scale)))
    logo = render_svg(svg, size=logo_size, states=states)
    result = Image.new('RGBA', (width, height), background)
    result.alpha_composite(logo, ((width-logo.width)//2, (height-logo.height)//2))
    return result.convert('RGB')


def compare_final(reference: Image.Image, observed: Image.Image, *, compressed=False) -> dict:
    if reference.size != observed.size:
        return {'passed': False, 'failures': ['Final frame dimensions differ from the approved vector canvas.']}
    difference = np.abs(np.asarray(reference.convert('RGB'), dtype=float)-np.asarray(observed.convert('RGB'), dtype=float))
    mae = float(difference.mean())
    changed = float(np.any(difference > (16 if compressed else 0), axis=2).mean())
    passed = mae <= (2.5 if compressed else 0) and changed <= (.03 if compressed else 0)
    return {'passed': passed, 'mean_absolute_error': round(mae, 6), 'changed_pixel_ratio': round(changed, 6),
            'compression_tolerance': compressed,
            'failures': [] if passed else ['Final frame differs from the approved static vector.']}


def easing_probe(token: str, duration_ms: float, samples: list[dict]) -> dict:
    finite(duration_ms, 100, 3000)
    if not isinstance(samples, list) or not 3 <= len(samples) <= 1000:
        return {'passed': False, 'failures': ['Easing probe requires 3..1000 observed samples.']}
    errors, values, times = [], [], []
    for sample in samples:
        if set(sample) != {'time_ms', 'value'}:
            raise ValueError('Easing samples require exactly time_ms and value.')
        t = finite(sample['time_ms'], 0, duration_ms)
        value = finite(sample['value'], -2, 3)
        errors.append(abs(value - ease(t/duration_ms, token)))
        times.append(t)
        values.append(value)
    monotonic = all(b >= a-1e-6 for a, b in zip(values, values[1:]))
    endpoints = times[0] == 0 and times[-1] == duration_ms
    ordered = all(b > a for a, b in zip(times, times[1:]))
    maximum = max(errors)
    passed = maximum <= .02 and monotonic and endpoints and ordered and min(values) >= 0 and max(values) <= 1.02
    return {'passed': passed, 'max_error': maximum, 'monotonic': monotonic,
            'overshoot': max(0, max(values)-1), 'duration_ms': duration_ms,
            'failures': [] if passed else ['Observed easing does not match the declared token or duration.']}


def continuity_sweep(samples: list[dict]) -> dict:
    if not isinstance(samples, list) or not 3 <= len(samples) <= 10000:
        raise ValueError('Continuity sweep requires 3..10000 observed samples.')
    previous, counts, failures, maximum = {}, {}, [], {'position': 0, 'scale': 0, 'opacity': 0}
    for sample in samples:
        if set(sample) != {'part', 'time_ms', 'x', 'y', 'scale', 'opacity'} or not isinstance(sample['part'], str):
            raise ValueError('Continuity samples require part, time_ms, x, y, scale and opacity.')
        for key, low, high in (('time_ms', 0, 30000), ('x', -4096, 4096), ('y', -4096, 4096),
                              ('scale', 0, 4), ('opacity', 0, 1)):
            finite(sample[key], low, high)
        part = sample['part']
        counts[part] = counts.get(part, 0) + 1
        if part in previous:
            last = previous[part]
            dt = sample['time_ms']-last['time_ms']
            if not 0 < dt <= 50:
                failures.append('Continuity samples must advance by at most 50 ms per part.')
                continue
            deltas = {'position': math.hypot(sample['x']-last['x'], sample['y']-last['y']),
                      'scale': abs(sample['scale']-last['scale']), 'opacity': abs(sample['opacity']-last['opacity'])}
            for key, delta in deltas.items():
                maximum[key] = max(maximum[key], delta)
            if deltas['position'] > max(4, dt*.4) or deltas['scale'] > max(.08, dt*.004) or deltas['opacity'] > max(.12, dt*.006):
                failures.append(f'Continuity pop in {part} at {sample["time_ms"]} ms.')
        previous[part] = sample
    if not previous or any(count < 3 for count in counts.values()):
        failures.append('Continuity sweep requires at least three observations per part.')
    return {'passed': not failures, 'maximum_jumps': maximum, 'failures': list(dict.fromkeys(failures))}


def spec_markdown(spec: dict) -> str:
    rows = '\n'.join(f'| {row["part"]} | {row["start_ms"]} | {row["end_ms"]} | {row["easing"]} | {row["paint"]} |' for row in spec['timeline'])
    return f'''# Logo motion specification

Personality: {', '.join(spec['personality'])}.
Style: {spec['style']}. Reveal duration: {spec['duration_seconds']} seconds.
Principles: {', '.join(spec['principles'])}. The initial hold anticipates the reveal;
overlapping part windows stage the mark before secondary colours. Smooth easing lands at rest.

| Part | Start ms | End ms | Easing | Paint |
| --- | --- | --- | --- | --- |
{rows}

Easing tokens: settle = 3t² - 2t³; enter = 1 - (1-t)³.
Final frame: identity transform and opacity 1, matching the approved vector.
The optional preview idle loop is excluded from the finite MP4 final frame.
Filled outlines have no inferred stroke skeleton. Draw-on order follows groups;
manual review must identify wordmarks and crossing strokes before custom draw-on.
'''


def preview_html(svg: str, spec: dict, background='#101820') -> str:
    parse_svg(svg)
    validate_motion_spec(spec)
    payload = json.dumps(spec, separators=(',', ':'))
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Logo motion preview</title><style>
body{margin:0;background:''' + background + ''';color:white;font:16px system-ui;text-align:center}
main{min-height:65vh;display:grid;place-items:center}#logo-root{width:min(70vw,''' + str(round(spec['source_width']*.7)) + '''px)}
svg{width:100%;height:auto;overflow:visible}.atoms{display:flex;justify-content:center;gap:24px}.atoms img{width:64px}
button,input{margin:12px}button:focus-visible{outline:2px solid white}.atoms button{background:none;color:inherit;border:1px solid #64748b;padding:12px}
@media(prefers-reduced-motion:reduce){.atoms{display:none}}
</style><main><div id="logo-root">''' + svg + '''</div></main>
<button id="replay">Replay</button><button id="slow">Slow motion</button><label>Speed <input id="speed" type="range" min="0.1" max="2" step="0.1" value="1"></label>
<p>Staging · Anticipation · Slow in/out · Overlap · Timing</p><div class="atoms"></div>
<script>
const spec=''' + payload + ''';
const root=document.querySelector('#logo-root'), groups=[...root.querySelectorAll('g')];const staticSvg=root.querySelector('svg').cloneNode(true);
const reduced=matchMedia('(prefers-reduced-motion:reduce)');
const query=new URLSearchParams(location.search);let elapsed=0,previous=null,rate=1;
const duration=spec.duration_seconds*1000;
function paint(ms,final=false){groups.forEach((g,i)=>{const row=spec.timeline[i];const t=Math.min(1,Math.max(0,(ms-row.start_ms)/(row.end_ms-row.start_ms)));const p=t*t*(3-2*t);
let scale,opacity,y;if(spec.style==='loader'){scale=1+.025*Math.sin(p*Math.PI*2)**2;opacity=1;y=0}else{const initial=spec.style==='splash'?.72:.96;scale=initial+(1-initial)*p;opacity=p;y=spec.style==='splash'?0:(1-p)*spec.source_height*.035}
if(final||t===1){scale=1;opacity=1;y=0}g.setAttribute('opacity',String(opacity));g.setAttribute('transform',`translate(${spec.source_width/2} ${spec.source_height/2+y}) scale(${scale}) translate(${-spec.source_width/2} ${-spec.source_height/2})`);});window.__logoReady=true;}
function tick(now){if(previous!==null)elapsed+=(now-previous)*rate;previous=now;let ms=Math.min(duration,elapsed);paint(ms,reduced.matches);if(spec.idle_loop&&elapsed>duration&&!reduced.matches){const s=1+.015*(1-Math.cos((elapsed-duration)/600));root.style.transform=`scale(${s})`}requestAnimationFrame(tick)}
const fixed=query.has('t')||query.has('static');if(fixed||reduced.matches){paint(query.has('static')||reduced.matches?duration:Number(query.get('t')),query.has('static')||reduced.matches)}else{paint(0);requestAnimationFrame(tick)};
document.querySelector('#replay').onclick=()=>{elapsed=0;previous=null;root.style.transform='';if(fixed)paint(0)};
document.querySelector('#speed').oninput=e=>{rate=Number(e.target.value)};
document.querySelector('#slow').onclick=()=>{rate=rate===.25?1:.25;document.querySelector('#speed').value=String(rate)};
for(const [label,frames] of [['Hover',[{transform:'translateY(0)'},{transform:'translateY(-2px)'},{transform:'translateY(0)'}]],['Pulse',[{transform:'scale(1)'},{transform:'scale(1.03)'},{transform:'scale(1)'}]],['Press',[{transform:'scale(1)'},{transform:'scale(.98)'},{transform:'scale(1)'}]]]){const button=document.createElement('button');button.textContent=label;const img=document.createElement('img');img.alt='Logo '+label.toLowerCase();img.src='data:image/svg+xml;base64,'+btoa(new XMLSerializer().serializeToString(staticSvg));button.prepend(img);button.onclick=()=>{if(!reduced.matches)img.animate(frames,{duration:250,easing:'ease-out'})};document.querySelector('.atoms').append(button)}
</script></html>'''
