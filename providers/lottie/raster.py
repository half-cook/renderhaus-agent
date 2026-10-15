"""A deterministic native-Lottie raster subset for small transparent UI animations."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from PIL import Image, ImageDraw

Matrix = tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1, 0, 0, 1, 0, 0)
MAX_NODES = 20000
MAX_POINTS = 20000


def _refuse(reason: str):
    raise ValueError('not previewed: ' + reason)


def _number(value: Any) -> float:
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _refuse('properties require finite numeric values')
    if abs(value) > 1_000_000:
        _refuse('property values exceed the bounded preview range')
    return float(value)


def _vector(value: Any) -> list[float]:
    if not isinstance(value, list) or len(value) not in (2, 3, 4):
        _refuse('vector properties require two to four components')
    return [_number(item) for item in value]


def _mix(start, end, progress):
    if isinstance(start, list) and isinstance(end, list) and len(start) == len(end):
        return [_mix(a, b, progress(i)) for i, (a, b) in enumerate(zip(start, end))]
    if isinstance(start, list) or isinstance(end, list):
        _refuse('keyframe component counts must agree')
    amount = progress(0) if callable(progress) else progress
    return _number(start) + (_number(end) - _number(start)) * amount


def _component(value, index):
    if isinstance(value, list):
        return _number(value[min(index, len(value) - 1)])
    return _number(value)


def _ease(key, progress, index):
    outgoing = key.get('o', {'x': 0, 'y': 0})
    incoming = key.get('i', {'x': 1, 'y': 1})
    x1, y1 = (_component(outgoing.get(name), index) for name in ('x', 'y'))
    x2, y2 = (_component(incoming.get(name), index) for name in ('x', 'y'))
    if not 0 <= x1 <= 1 or not 0 <= x2 <= 1 or not -4 <= y1 <= 4 or not -4 <= y2 <= 4:
        _refuse('temporal easing exceeds supported control bounds')
    low, high = 0., 1.
    for _ in range(32):
        t = (low + high) / 2
        x = 3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t * t * x2 + t ** 3
        if x < progress:
            low = t
        else:
            high = t
    t = (low + high) / 2
    return 3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t * t * y2 + t ** 3


def _value(prop, frame, default=None):
    if prop is None:
        return default
    if not isinstance(prop, dict) or 'k' not in prop or prop.get('a', 0) not in (0, 1):
        _refuse('invalid native property')
    if set(prop) - {'a', 'k', 'ix', 'l'}:
        _refuse('expressions, slots, separated dimensions and unknown property features')
    if not prop.get('a', 0):
        return prop['k']
    keys = prop['k']
    if not isinstance(keys, list) or not 1 <= len(keys) <= 1000:
        _refuse('animated properties need a bounded keyframe list')
    for key in keys:
        if not isinstance(key, dict) or set(key) - {'t', 's', 'e', 'i', 'o', 'h', 'n'}:
            _refuse('spatial interpolation and unknown keyframe features')
    times = [_number(key.get('t')) for key in keys]
    if any(b <= a for a, b in zip(times, times[1:])):
        _refuse('keyframe times must increase')
    if frame <= times[0]:
        return keys[0].get('s')
    for index in range(len(keys) - 1):
        start, finish = keys[index:index + 2]
        if frame < times[index + 1]:
            if start.get('h') == 1:
                return start.get('s')
            progress = (frame - times[index]) / (times[index + 1] - times[index])
            end = start.get('e', finish.get('s'))
            return _mix(start.get('s'), end, lambda component: _ease(start, progress, component))
    return keys[-1].get('s', keys[-2].get('e') if len(keys) > 1 else None)


def _matmul(left: Matrix, right: Matrix) -> Matrix:
    a, b, c, d, e, f = left
    g, h, i, j, k, l = right
    return (a*g+c*h, b*g+d*h, a*i+c*j, b*i+d*j, a*k+c*l+e, b*k+d*l+f)


def _transform(ks, frame) -> tuple[Matrix, float]:
    if not isinstance(ks, dict) or set(ks) - {'a', 'p', 's', 'r', 'o', 'sk', 'sa', 'ty', 'nm', 'mn', 'ix', 'hd'}:
        _refuse('3D, separated position or unknown transform features')
    if _number(_value(ks.get('sk'), frame, 0)) or _number(_value(ks.get('sa'), frame, 0)):
        _refuse('skew transforms')
    anchor = _vector(_value(ks.get('a'), frame, [0, 0]))
    position = _vector(_value(ks.get('p'), frame, [0, 0]))
    scale = _vector(_value(ks.get('s'), frame, [100, 100]))
    if ((len(anchor) > 2 and anchor[2] != 0) or (len(position) > 2 and position[2] != 0)
            or (len(scale) > 2 and scale[2] != 100)):
        _refuse('3D transforms')
    angle = math.radians(_number(_value(ks.get('r'), frame, 0)))
    a, b = math.cos(angle) * scale[0] / 100, math.sin(angle) * scale[0] / 100
    c, d = -math.sin(angle) * scale[1] / 100, math.cos(angle) * scale[1] / 100
    opacity = _number(_value(ks.get('o'), frame, 100)) / 100
    if not 0 <= opacity <= 1:
        _refuse('opacity outside 0 to 100')
    return (a, b, c, d, position[0]-a*anchor[0]-c*anchor[1],
            position[1]-b*anchor[0]-d*anchor[1]), opacity


def _apply(matrix: Matrix, point):
    a, b, c, d, e, f = matrix
    x, y = point
    return (a*x+c*y+e, b*x+d*y+f)


def _alpha(image: Image.Image, opacity: float):
    if opacity != 1:
        image.putalpha(image.getchannel('A').point([round(value * opacity) for value in range(256)]))
    return image


def _color(style, frame):
    color = _vector(_value(style.get('c'), frame))
    if len(color) < 3 or any(not 0 <= component <= 1 for component in color):
        _refuse('fill and stroke colors must have normalized RGB components')
    opacity = _number(_value(style.get('o'), frame, 100)) / 100
    if not 0 <= opacity <= 1:
        _refuse('style opacity outside 0 to 100')
    return tuple(round(component * 255) for component in color[:3]) + (
        round(255 * opacity * (color[3] if len(color) > 3 else 1)),)


@dataclass(frozen=True)
class Geometry:
    points: list[tuple[float, float]]
    closed: bool


def _geometry(shape, frame) -> Geometry:
    kind = shape['ty']
    if kind == 'sh':
        prop = shape.get('ks')
        if not isinstance(prop, dict) or prop.get('a', 0) != 0:
            _refuse('animated Bezier path morphs')
        path = _value(prop, frame)
        if not isinstance(path, dict) or set(path) - {'v', 'i', 'o', 'c'}:
            _refuse('invalid native Bezier path')
        vertices, incoming, outgoing = (path.get(key) for key in ('v', 'i', 'o'))
        if (not isinstance(vertices, list) or not 2 <= len(vertices) <= 512
                or not isinstance(incoming, list) or not isinstance(outgoing, list)
                or len(vertices) != len(incoming) or len(vertices) != len(outgoing)
                or not isinstance(path.get('c'), bool)):
            _refuse('Bezier paths need 2 to 512 vertices and matching tangents')
        vertices = [_vector(v)[:2] for v in vertices]
        incoming = [_vector(v)[:2] for v in incoming]
        outgoing = [_vector(v)[:2] for v in outgoing]
        points = [tuple(vertices[0])]
        for index in range(len(vertices) if path['c'] else len(vertices) - 1):
            target = (index + 1) % len(vertices)
            p0, p3 = vertices[index], vertices[target]
            p1 = [p0[k] + outgoing[index][k] for k in range(2)]
            p2 = [p3[k] + incoming[target][k] for k in range(2)]
            steps = 1 if p0 == p1 and p2 == p3 else 24
            for step in range(1, steps + 1):
                t = step / steps
                points.append(tuple((1-t)**3*p0[k] + 3*(1-t)**2*t*p1[k]
                                    + 3*(1-t)*t*t*p2[k] + t**3*p3[k] for k in range(2)))
        return Geometry(points, path['c'])
    position = _vector(_value(shape.get('p'), frame, [0, 0]))
    size = _vector(_value(shape.get('s'), frame))
    if any(value <= 0 for value in size[:2]):
        _refuse('shape dimensions must be positive')
    x, y = position[:2]
    width, height = size[:2]
    if kind == 'el':
        points = [(x + width/2*math.cos(-math.pi/2+i*math.tau/96),
                   y + height/2*math.sin(-math.pi/2+i*math.tau/96)) for i in range(96)]
        return Geometry(points if shape.get('d', 1) != 3 else [points[0], *reversed(points[1:])], True)
    radius = max(0, min(_number(_value(shape.get('r'), frame, 0)), width/2, height/2))
    if radius == 0:
        points = [(x+width/2, y-height/2), (x+width/2, y+height/2),
                  (x-width/2, y+height/2), (x-width/2, y-height/2)]
        return Geometry(points if shape.get('d', 1) != 3 else [points[0], *reversed(points[1:])], True)
    points = []
    for cx, cy, start in [(x+width/2-radius, y+height/2-radius, 0),
                           (x-width/2+radius, y+height/2-radius, 90),
                           (x-width/2+radius, y-height/2+radius, 180),
                           (x+width/2-radius, y-height/2+radius, 270)]:
        for step in range(13):
            angle = math.radians(start + step*90/12)
            points.append((cx + radius*math.cos(angle), cy + radius*math.sin(angle)))
    points = [points[-1], *points[:-1]]
    return Geometry(points if shape.get('d', 1) != 3 else [points[0], *reversed(points[1:])], True)


def _trim(geometry: Geometry, start: float, end: float) -> Geometry:
    if not 0 <= start <= end <= 100:
        _refuse('trim paths require 0 <= start <= end <= 100')
    if start == 0 and end == 100:
        return geometry
    points = geometry.points
    if geometry.closed and points[-1] != points[0]:
        points = [*points, points[0]]
    distances = [math.dist(a, b) for a, b in zip(points, points[1:])]
    length = sum(distances)
    lower, upper = length*start/100, length*end/100
    result = []
    position = 0.
    for a, b, distance in zip(points, points[1:], distances):
        if distance and position <= upper and position + distance >= lower:
            for amount in (max(0., (lower-position)/distance), min(1., (upper-position)/distance)):
                point = tuple(a[k] + (b[k]-a[k])*amount for k in range(2))
                if not result or result[-1] != point:
                    result.append(point)
        position += distance
    return Geometry(result if start != end else [], False)


_SHAPE_FIELDS = {
    'rc': {'p', 's', 'r', 'd'}, 'el': {'p', 's', 'd'}, 'sh': {'ks', 'd'},
    'fl': {'c', 'o', 'r'}, 'st': {'c', 'o', 'w', 'lc', 'lj', 'ml', 'bm'},
    'tm': {'s', 'e', 'o', 'm'}, 'gr': {'it', 'np', 'cix', 'bm'},
    'tr': {'a', 'p', 's', 'r', 'o', 'sk', 'sa'},
}
_METADATA = {'ty', 'nm', 'mn', 'ix', 'hd'}


def _check_shapes(shapes):
    if not isinstance(shapes, list) or len(shapes) > 256:
        _refuse('shape lists must be bounded arrays')
    groups, geometry, styles = [], [], {}
    for index, shape in enumerate(shapes):
        if not isinstance(shape, dict) or shape.get('ty') not in _SHAPE_FIELDS:
            _refuse('unknown shape types, gradients, merge paths or repeaters')
        kind = shape['ty']
        if 'd' in shape and shape['d'] not in (1, 2, 3):
            _refuse('unknown shape direction')
        unknown = set(shape) - (_SHAPE_FIELDS[kind] | _METADATA)
        if unknown:
            _refuse(f"unsupported {kind} shape fields {','.join(sorted(unknown))}")
        if shape.get('bm', 0) != 0:
            _refuse('shape blend modes')
        if kind == 'gr':
            groups.append(shape)
            _check_shapes(shape.get('it'))
        elif kind in ('rc', 'el', 'sh'):
            geometry.append(shape)
            if styles:
                _refuse('geometry after style operators')
        else:
            if kind in styles:
                _refuse('multiple style or transform operators within a group')
            styles[kind] = shape
            if kind == 'tr' and index != len(shapes) - 1:
                _refuse('group transform must be the final operator')
    if len(geometry) > 1 or groups and (geometry or set(styles) - {'tr'}):
        _refuse('shared multi-path styles and mixed nested geometry')
    if 'tm' in styles and 'fl' in styles:
        _refuse('trim paths combined with a fill')
    if 'fl' in styles and styles['fl'].get('r', 1) != 1:
        _refuse('non-default fill rules')
    if 'st' in styles and (styles['st'].get('lj', 1) not in (1, 2, 3) or styles['st'].get('lc', 1) not in (1, 2, 3)):
        _refuse('unknown stroke cap or join type')
    if 'tm' in styles and styles['tm'].get('m', 1) != 1:
        _refuse('only individual single-path trim mode is supported')
    return groups, geometry, styles


def _inspect(document):
    if not isinstance(document, dict):
        _refuse('animation must be an object')
    if document.get('assets') or document.get('fonts') or document.get('chars') or document.get('slots'):
        _refuse('images, precompositions, fonts, text and slots')
    if set(document) - {'v', 'nm', 'w', 'h', 'ip', 'op', 'fr', 'ddd', 'assets', 'layers', 'markers', 'meta'}:
        _refuse('unknown top-level animation features')
    if document.get('ddd', 0):
        _refuse('3D animation')
    layers = document.get('layers')
    if not isinstance(layers, list) or len(layers) > 64:
        _refuse('animation needs at most 64 layers')
    nodes = 0
    def visit(value, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > MAX_NODES or depth > 24:
            _refuse('animation exceeds the bounded preview complexity')
        if isinstance(value, dict):
            for child in value.values():
                visit(child, depth+1)
        elif isinstance(value, list):
            for child in value:
                visit(child, depth+1)
    visit(document)
    indices = set()
    for layer in layers:
        if not isinstance(layer, dict) or layer.get('ty') not in (3, 4):
            _refuse('only native shape and null layers are supported')
        unsupported = set(layer) - {'ty', 'ind', 'nm', 'mn', 'ip', 'op', 'st', 'sr', 'ks', 'shapes',
                                    'parent', 'ddd', 'ao', 'bm', 'hd', 'ln', 'cl'}
        if unsupported:
            _refuse('layer features ' + ','.join(sorted(unsupported)))
        if layer.get('ddd', 0) or layer.get('ao', 0) or layer.get('bm', 0) or layer.get('sr', 1) != 1:
            _refuse('3D, auto-orientation, blend modes or time stretching')
        index = layer.get('ind')
        if not isinstance(index, int) or isinstance(index, bool) or index in indices:
            _refuse('layers need unique numeric indices')
        indices.add(index)
        if layer['ty'] == 4:
            _check_shapes(layer.get('shapes'))
    by_id = {layer['ind']: layer for layer in layers}
    for layer in layers:
        seen = {layer['ind']}
        while 'parent' in layer:
            index = layer['parent']
            if index in seen or index not in by_id:
                _refuse('missing or cyclic parent layers')
            seen.add(index)
            layer = by_id[index]
    return layers


def _stroke(draw, points, closed, width, color, cap, join, miter_limit):
    radius = width / 2
    if closed and points[-1] != points[0]:
        points = [*points, points[0]]
    segments = []
    for start, end in zip(points, points[1:]):
        length = math.dist(start, end)
        if not length:
            continue
        direction = ((end[0]-start[0])/length, (end[1]-start[1])/length)
        normal = (-direction[1]*radius, direction[0]*radius)
        segments.append((start, end, direction, normal))
        draw.polygon([(start[0]+normal[0], start[1]+normal[1]),
                      (end[0]+normal[0], end[1]+normal[1]),
                      (end[0]-normal[0], end[1]-normal[1]),
                      (start[0]-normal[0], start[1]-normal[1])], fill=color)
    if not segments:
        return
    pairs = list(zip(segments, segments[1:]))
    if closed:
        pairs.append((segments[-1], segments[0]))
    for previous, current in pairs:
        point = current[0]
        if join == 2:
            x, y = point
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color)
            continue
        u, v = previous[2], current[2]
        cross = u[0]*v[1]-u[1]*v[0]
        for sign in (-1, 1):
            a = (point[0]+sign*previous[3][0], point[1]+sign*previous[3][1])
            b = (point[0]+sign*current[3][0], point[1]+sign*current[3][1])
            polygon = [point, a, b]
            if join == 1 and abs(cross) > 1e-9:
                delta = (b[0]-a[0], b[1]-a[1])
                distance = (delta[0]*v[1]-delta[1]*v[0])/cross
                intersection = (a[0]+distance*u[0], a[1]+distance*u[1])
                if math.dist(point, intersection) <= miter_limit*radius:
                    polygon = [point, a, intersection, b]
            draw.polygon(polygon, fill=color)
    if not closed:
        for segment, sign, point in ((segments[0], -1, segments[0][0]),
                                     (segments[-1], 1, segments[-1][1])):
            x, y = point
            if cap == 2:
                draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color)
            elif cap == 3:
                extension = (sign*segment[2][0]*radius, sign*segment[2][1]*radius)
                normal = segment[3]
                draw.polygon([(x+normal[0], y+normal[1]), (x-normal[0], y-normal[1]),
                              (x-normal[0]+extension[0], y-normal[1]+extension[1]),
                              (x+normal[0]+extension[0], y+normal[1]+extension[1])], fill=color)


def _draw_group(shapes, frame, matrix, size):
    groups, geometry, styles = _check_shapes(shapes)
    transform, opacity = _transform(styles.get('tr', {}), frame)
    matrix = _matmul(matrix, transform)
    canvas = Image.new('RGBA', size)
    for group in reversed(groups):
        if not group.get('hd', False):
            canvas.alpha_composite(_draw_group(group['it'], frame, matrix, size))
    if geometry and not geometry[0].get('hd', False):
        path = _geometry(geometry[0], frame)
        if 'tm' in styles:
            trim = styles['tm']
            if _number(_value(trim.get('o'), frame, 0)):
                _refuse('trim offsets')
            path = _trim(path, _number(_value(trim.get('s'), frame, 0)),
                         _number(_value(trim.get('e'), frame, 100)))
        points = [_apply(matrix, point) for point in path.points]
        if len(points) > MAX_POINTS:
            _refuse('path exceeds the bounded preview point count')
        if points and 'fl' in styles and not styles['fl'].get('hd', False):
            fill = Image.new('RGBA', size)
            ImageDraw.Draw(fill).polygon(points, fill=_color(styles['fl'], frame))
            canvas.alpha_composite(fill)
        if len(points) >= 2 and 'st' in styles and not styles['st'].get('hd', False):
            stroke = styles['st']
            a, b, c, d, _, _ = matrix
            scale = math.hypot(a, b)
            if abs(scale-math.hypot(c, d)) > 1e-6 or abs(a*c+b*d) > 1e-6:
                _refuse('nonuniformly scaled strokes')
            width = _number(_value(stroke.get('w'), frame)) * scale
            if not 0 < width <= 1024:
                _refuse('stroke width outside supported preview range')
            color = _color(stroke, frame)
            image = Image.new('RGBA', size)
            draw = ImageDraw.Draw(image)
            miter_limit = _number(stroke.get('ml', 4))
            if not 1 <= miter_limit <= 100:
                _refuse('stroke miter limit outside 1 to 100')
            _stroke(draw, points, path.closed, width, color, stroke.get('lc', 1),
                    stroke.get('lj', 1), miter_limit)
            canvas.alpha_composite(image)
    return _alpha(canvas, opacity)


def render_frame(document: dict, frame: float, *, max_size: int = 256) -> Image.Image:
    """Rasterize one absolute frame, refusing any feature that would be dropped."""
    layers = _inspect(document)
    if isinstance(max_size, bool) or not isinstance(max_size, int) or not 32 <= max_size <= 512:
        raise ValueError('max_size must be an integer between 32 and 512.')
    width, height = _number(document.get('w')), _number(document.get('h'))
    if not 1 <= width <= 4096 or not 1 <= height <= 4096:
        _refuse('canvas dimensions exceed the bounded preview range')
    frame = _number(frame)
    if not _number(document.get('ip')) <= frame < _number(document.get('op')):
        raise ValueError('Frame must be within the animation in/out range.')
    scale = min(1., max_size/max(width, height))
    size = (max(1, round(width*scale)), max(1, round(height*scale)))
    canvas = Image.new('RGBA', size)
    by_id = {layer['ind']: layer for layer in layers}
    def transform(layer):
        local_frame = frame - _number(layer.get('st', 0))
        matrix, opacity = _transform(layer.get('ks', {}), local_frame)
        if 'parent' in layer:
            parent_matrix, _ = transform(by_id[layer['parent']])
            matrix = _matmul(parent_matrix, matrix)
        return matrix, opacity
    for layer in reversed(layers):
        if (layer.get('hd') or layer['ty'] == 3 or not
                _number(layer.get('ip', document['ip'])) <= frame < _number(layer.get('op', document['op']))):
            continue
        matrix, opacity = transform(layer)
        matrix = _matmul((scale, 0, 0, scale, 0, 0), matrix)
        rendered = _draw_group(layer.get('shapes'), frame-_number(layer.get('st', 0)), matrix, size)
        canvas.alpha_composite(_alpha(rendered, opacity))
    return canvas
