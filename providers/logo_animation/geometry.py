"""Bounded local contour fitting and a deliberately small, inactive SVG dialect."""
from __future__ import annotations

from collections import defaultdict, deque
import math
from pathlib import Path
import re
import warnings
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw, UnidentifiedImageError

MAX_BYTES = 8 * 1024 * 1024
MAX_SIDE = 2048
MAX_PIXELS = 1024 * 1024
MAX_SEGMENTS = 256
SVG_NS = 'http://www.w3.org/2000/svg'
NUMBER = r'-?(?:\d+(?:\.\d*)?|\.\d+)'
TOKEN = re.compile(r'[MLQZ]|' + NUMBER)


def decode(path: Path) -> Image.Image:
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError('Logo input requires a regular file of at most 8 MiB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format not in {'PNG', 'JPEG'} or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('Logo input requires a single PNG or JPEG frame.')
                if max(image.size) > MAX_SIDE or image.width * image.height > MAX_PIXELS:
                    raise ValueError('Logo input exceeds 2048 pixels per side or 1048576 pixels total.')
                image.load()
                return image.convert('RGBA')
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError('Logo image cannot be safely decoded.') from exc


def foreground(image: Image.Image) -> np.ndarray:
    rgba = np.asarray(image)
    mask = rgba[:, :, 3] >= 128
    # A border-connected solid background is removed without deleting enclosed ink.
    if np.all(rgba[:, :, 3] >= 250):
        border = np.concatenate((rgba[0, :, :3], rgba[-1, :, :3], rgba[:, 0, :3], rgba[:, -1, :3]))
        background = np.median(border, axis=0)
        similar = np.max(np.abs(rgba[:, :, :3].astype(float) - background), axis=2) <= 24
        seen = np.zeros(mask.shape, dtype=bool)
        height, width = mask.shape
        queue = deque()
        for x in range(width):
            for y in (0, height - 1):
                if similar[y, x] and not seen[y, x]:
                    seen[y, x] = True
                    queue.append((x, y))
        for y in range(height):
            for x in (0, width - 1):
                if similar[y, x] and not seen[y, x]:
                    seen[y, x] = True
                    queue.append((x, y))
        while queue:
            x, y = queue.popleft()
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < width and 0 <= ny < height and similar[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    queue.append((nx, ny))
        mask &= ~seen
    if not mask.any():
        raise ValueError('Logo has no visible foreground after background removal.')
    return mask


def _contours(mask: np.ndarray) -> list[list[tuple[float, float]]]:
    height, width = mask.shape
    padded = np.pad(mask, 1)
    edges = defaultdict(list)
    sides = [mask & ~padded[:-2, 1:-1], mask & ~padded[1:-1, 2:],
             mask & ~padded[2:, 1:-1], mask & ~padded[1:-1, :-2]]
    count = sum(int(side.sum()) for side in sides)
    if count > 16000:
        raise ValueError('Logo boundary is too complex. Supply a cleaner, smaller source.')
    for side, boundary in enumerate(sides):
        for y, x in zip(*np.where(boundary)):
            x, y = int(x), int(y)
            start, end = (((x, y), (x + 1, y)), ((x + 1, y), (x + 1, y + 1)),
                          ((x + 1, y + 1), (x, y + 1)), ((x, y + 1), (x, y)))[side]
            edges[start].append(end)
    loops = []
    directions = {(1, 0): 0, (0, 1): 1, (-1, 0): 2, (0, -1): 3}
    remaining = count
    while edges:
        start = next(iter(edges))
        point = start
        loop = []
        previous = 0
        while True:
            loop.append(point)
            candidates = edges[point]
            def priority(end):
                direction = directions[(end[0] - point[0], end[1] - point[1])]
                return {1: 0, 0: 1, 3: 2, 2: 3}[(direction - previous) % 4]
            end = min(candidates, key=priority)
            previous = directions[(end[0] - point[0], end[1] - point[1])]
            candidates.remove(end)
            if not candidates:
                del edges[point]
            remaining -= 1
            point = end
            if point == start:
                break
            if remaining < 0 or point not in edges:
                raise ValueError('Logo boundary is not a closed contour.')
        if len(loop) >= 4:
            loops.append(loop)
        if len(loops) > 128:
            raise ValueError('Logo has too many separate contours.')
    return loops


def _rdp(points, epsilon):
    # Iterative Douglas-Peucker avoids recursion on adversarial zigzags.
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        a, b = points[start], points[end]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy)
        best, index = 0, start
        for i in range(start + 1, end):
            px, py = points[i][0] - a[0], points[i][1] - a[1]
            distance = abs(dx * py - dy * px) / length if length else math.hypot(px, py)
            if distance > best:
                best, index = distance, i
        if best > epsilon:
            keep.add(index)
            stack.extend(((start, index), (index, end)))
    return [points[i] for i in sorted(keep)]


def _simplify(loop):
    split = max(range(len(loop)), key=lambda i: math.dist(loop[0], loop[i]))
    return _rdp(loop[:split + 1], 1.1)[:-1] + _rdp(loop[split:] + [loop[0]], 1.1)[:-1]


def _f(value):
    return f'{value:.3f}'.rstrip('0').rstrip('.') if value else '0'


def _path(loops):
    commands = []
    for loop in loops:
        xs, ys = zip(*loop)
        cx, cy = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2
        rx, ry = (max(xs)-min(xs))/2, (max(ys)-min(ys))/2
        if rx >= 8 and ry >= 8 and max(abs(((x-cx)/rx)**2+((y-cy)/ry)**2-1) for x, y in loop) <= .12:
            commands.append('M ' + ' '.join(map(_f, (cx+rx, cy))))
            for index in range(8):
                middle = (index+.5)*math.pi/4
                end = (index+1)*math.pi/4
                control = (cx+rx*math.cos(middle)/math.cos(math.pi/8),
                           cy+ry*math.sin(middle)/math.cos(math.pi/8))
                endpoint = (cx+rx*math.cos(end), cy+ry*math.sin(end))
                commands.append('Q ' + ' '.join(map(_f, (*control, *endpoint))))
            commands.append('Z')
            continue
        points = _simplify(loop)
        if len(points) < 3:
            continue
        if len(points) <= 8:
            commands += ['M ' + ' '.join(map(_f, points[0]))]
            commands += ['L ' + ' '.join(map(_f, point)) for point in points[1:]]
        else:
            entries, exits = [], []
            for i, point in enumerate(points):
                prev, nxt = points[i - 1], points[(i + 1) % len(points)]
                entries.append(tuple(point[k] * .65 + prev[k] * .35 for k in (0, 1)))
                exits.append(tuple(point[k] * .65 + nxt[k] * .35 for k in (0, 1)))
            commands.append('M ' + ' '.join(map(_f, entries[0])))
            for i, point in enumerate(points):
                commands.append('Q ' + ' '.join(map(_f, (*point, *exits[i]))))
                commands.append('L ' + ' '.join(map(_f, entries[(i + 1) % len(points)])))
        commands.append('Z')
    return ' '.join(commands)


def vectorize_image(path: Path, palette_size: int = 4) -> tuple[str, dict]:
    image = decode(path)
    mask = foreground(image)
    rgb = np.asarray(image)[:, :, :3]
    pixels = Image.fromarray(rgb[mask].reshape(1, -1, 3)).quantize(colors=palette_size,
        method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    colours = pixels.getpalette()
    quantized = np.full(mask.shape, -1)
    quantized[mask] = np.asarray(pixels).reshape(-1)
    groups = []
    for index in sorted(set(np.asarray(pixels).reshape(-1).tolist())):
        colour_mask = quantized == index
        yy, xx = np.where(colour_mask)
        x0, y0, x1, y1 = int(xx.min()), int(yy.min()), int(xx.max()) + 1, int(yy.max()) + 1
        colour = '#' + ''.join(f'{c:02x}' for c in colours[index * 3:index * 3 + 3])
        rectangle = np.zeros(mask.shape, dtype=bool)
        rectangle[y0:y1, x0:x1] = True
        ellipse = Image.new('1', image.size)
        ImageDraw.Draw(ellipse).ellipse((x0, y0, x1 - 1, y1 - 1), fill=1)
        emask = np.asarray(ellipse, dtype=bool)
        if np.array_equal(rectangle, colour_mask):
            element = f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" fill="{colour}"/>'
        elif float((emask & colour_mask).sum() / (emask | colour_mask).sum()) >= .97:
            element = f'<ellipse cx="{_f((x0+x1)/2)}" cy="{_f((y0+y1)/2)}" rx="{_f((x1-x0)/2)}" ry="{_f((y1-y0)/2)}" fill="{colour}"/>'
        else:
            data = _path(_contours(colour_mask))
            if not data:
                raise ValueError('Logo detail is smaller than the fitting limit.')
            element = f'<path d="{data}" fill="{colour}" fill-rule="evenodd"/>'
        part = 'mark' if not groups else f'accent-{len(groups)}'
        groups.append(f'<g id="{part}">{element}</g>')
    svg = f'<svg xmlns="{SVG_NS}" width="{image.width}" height="{image.height}" viewBox="0 0 {image.width} {image.height}">' + ''.join(groups) + '</svg>'
    parse_svg(svg)
    return svg, {'parts': [{'id': 'mark' if i == 0 else f'accent-{i}', 'role': 'mark' if i == 0 else 'accent',
                           'paint': 'fill', 'draw_order': i} for i in range(len(groups))],
                 'source_width': image.width, 'source_height': image.height,
                 'warnings': ['Semantic roles are provisional palette groups. Confirm mark, wordmark and accents visually.',
                              'Filled outlines do not infer a stroke skeleton. Crossing draw-on requires manual structure.']}


def _numeric(value, low=0, high=2048):
    if not isinstance(value, str) or not re.fullmatch(NUMBER, value):
        raise ValueError('SVG coordinates must be finite decimal numbers.')
    number = float(value)
    if not low <= number <= high:
        raise ValueError('SVG coordinates exceed the bounded canvas.')
    return number


def path_loops(data: str, width: int, height: int):
    if len(data) > 60000 or re.sub(TOKEN, '', data).strip(' ,\t\r\n'):
        raise ValueError('SVG path supports only absolute M, L, Q and Z commands.')
    tokens = TOKEN.findall(data)
    loops, points = [], []
    i, segments = 0, 0
    while i < len(tokens):
        command = tokens[i]
        i += 1
        count = {'M': 2, 'L': 2, 'Q': 4, 'Z': 0}.get(command)
        if count is None or i + count > len(tokens):
            raise ValueError('SVG path has malformed commands.')
        values = [_numeric(t, 0, width if j % 2 == 0 else height) for j, t in enumerate(tokens[i:i+count])]
        i += count
        if command == 'M':
            if points:
                raise ValueError('SVG contours must close before starting another.')
            points = [tuple(values)]
        elif command == 'Z':
            if len(points) < 3:
                raise ValueError('SVG contour requires three points.')
            loops.append(points)
            points = []
        elif not points:
            raise ValueError('SVG path must start with M.')
        elif command == 'L':
            points.append(tuple(values))
        else:
            start = points[-1]
            cx, cy, ex, ey = values
            for step in range(1, 13):
                t = step / 12
                points.append(((1-t)**2*start[0] + 2*(1-t)*t*cx + t*t*ex,
                               (1-t)**2*start[1] + 2*(1-t)*t*cy + t*t*ey))
        segments += 1
        if segments > MAX_SEGMENTS:
            raise ValueError('SVG path exceeds the segment budget.')
    if points or not loops:
        raise ValueError('SVG paths require closed contours.')
    return loops


def parse_svg(svg: str) -> dict:
    if not isinstance(svg, str) or len(svg.encode()) > 128000 or '<!' in svg or '<?' in svg:
        raise ValueError('SVG contains unsupported declarations or exceeds 128000 bytes.')
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        raise ValueError('SVG XML is invalid.') from exc
    def tag(node):
        if node.tag.startswith('{') and not node.tag.startswith('{' + SVG_NS + '}'):
            raise ValueError('SVG namespace is unsupported.')
        return node.tag.split('}')[-1]
    if tag(root) != 'svg' or set(root.attrib) != {'width', 'height', 'viewBox'}:
        raise ValueError('SVG requires only width, height and viewBox.')
    width, height = _numeric(root.get('width'), 1), _numeric(root.get('height'), 1)
    if not width.is_integer() or not height.is_integer() or width * height > MAX_PIXELS:
        raise ValueError('SVG canvas exceeds the pixel budget.')
    if root.get('viewBox') != f'0 0 {int(width)} {int(height)}':
        raise ValueError('SVG viewBox must match the original canvas.')
    parts, ids, segments = [], set(), 0
    for group in root:
        if tag(group) != 'g' or set(group.attrib) != {'id'} or len(group) != 1:
            raise ValueError('SVG requires one safe shape per semantic group.')
        identifier = group.get('id')
        if not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', identifier) or identifier in ids:
            raise ValueError('SVG group ids must be unique safe names.')
        ids.add(identifier)
        element = group[0]
        name = tag(element)
        expected = {'rect': {'x', 'y', 'width', 'height', 'fill'},
                    'ellipse': {'cx', 'cy', 'rx', 'ry', 'fill'},
                    'path': {'d', 'fill', 'fill-rule'}}
        allowed = expected.get(name)
        if allowed is None or set(element.attrib) - allowed or allowed - set(element.attrib) - {'fill-rule'} or len(element):
            raise ValueError('SVG shape or attributes are outside the safe subset.')
        if (element.text or '').strip() or (element.tail or '').strip() or (group.text or '').strip():
            raise ValueError('SVG does not accept embedded text.')
        colour = element.get('fill')
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', colour):
            raise ValueError('SVG fills require RGB hex colors.')
        if name == 'path':
            if element.get('fill-rule', 'evenodd') != 'evenodd':
                raise ValueError('SVG paths require evenodd fill.')
            loops = path_loops(element.get('d'), width, height)
            segments += len(re.findall('[LQ]', element.get('d')))
        elif name == 'rect':
            x, y = _numeric(element.get('x')), _numeric(element.get('y'))
            w, h = _numeric(element.get('width'), .001), _numeric(element.get('height'), .001)
            if x + w > width or y + h > height:
                raise ValueError('SVG rectangle exceeds canvas.')
            loops = [[(x, y), (x+w, y), (x+w, y+h), (x, y+h)]]
            segments += 4
        else:
            cx, cy = _numeric(element.get('cx')), _numeric(element.get('cy'))
            rx, ry = _numeric(element.get('rx'), .001), _numeric(element.get('ry'), .001)
            if cx-rx < 0 or cy-ry < 0 or cx+rx > width or cy+ry > height:
                raise ValueError('SVG ellipse exceeds canvas.')
            loops = [[(cx+rx*math.cos(i*math.tau/192), cy+ry*math.sin(i*math.tau/192)) for i in range(192)]]
            segments += 4
        parts.append({'id': identifier, 'fill': colour, 'loops': loops, 'kind': name,
                      'd': element.get('d', '')})
    if not parts or len(parts) > 32 or segments > MAX_SEGMENTS:
        raise ValueError('SVG exceeds the 32-part or 256-segment budget.')
    return {'width': int(width), 'height': int(height), 'parts': parts, 'segments': segments}


def render_svg(svg: str, *, size=None, states=None) -> Image.Image:
    geometry = parse_svg(svg)
    width, height = size or (geometry['width'], geometry['height'])
    if max(width, height) > 2048 or width * height > 4_194_304:
        raise ValueError('Logo rasterization exceeds the canvas budget.')
    factor = 2
    image = Image.new('RGBA', (width*factor, height*factor))
    for index, part in enumerate(geometry['parts']):
        state = states[index] if states else {'x': 0, 'y': 0, 'scale': 1, 'opacity': 1}
        mask = np.zeros((height*factor, width*factor), dtype=bool)
        for loop in part['loops']:
            panel = Image.new('1', image.size)
            points = [(((x-geometry['width']/2)*state['scale'] + geometry['width']/2 + state['x']) * width/geometry['width']*factor,
                       ((y-geometry['height']/2)*state['scale'] + geometry['height']/2 + state['y']) * height/geometry['height']*factor)
                      for x, y in loop]
            ImageDraw.Draw(panel).polygon(points, fill=1)
            mask ^= np.asarray(panel, dtype=bool)
        alpha = Image.fromarray((mask * round(255*state['opacity'])).astype('uint8'))
        colour = Image.new('RGBA', image.size, part['fill'])
        colour.putalpha(alpha)
        image = Image.alpha_composite(image, colour)
    return image.resize((width, height), Image.Resampling.LANCZOS)


def _curve_tangent_jump(data: str) -> float:
    tokens = TOKEN.findall(data)
    cursor, start, previous, first = None, None, None, None
    maximum, i = 0.0, 0

    def join(left, right):
        if left is None or right is None or not (left[1] or right[1]):
            return 0.0
        a, b = left[0], right[0]
        length = math.hypot(*a)*math.hypot(*b)
        return math.degrees(math.acos(max(-1, min(1, (a[0]*b[0]+a[1]*b[1])/length)))) if length else 0.0

    while i < len(tokens):
        command = tokens[i]
        i += 1
        if command == 'M':
            cursor = start = (float(tokens[i]), float(tokens[i+1]))
            i += 2
            previous = first = None
            continue
        if command == 'Z':
            maximum = max(maximum, join(previous, first))
            cursor = start
            continue
        count = 4 if command == 'Q' else 2
        values = list(map(float, tokens[i:i+count]))
        i += count
        end = tuple(values[-2:])
        incoming = ((values[0]-cursor[0], values[1]-cursor[1]), command == 'Q')
        outgoing = ((end[0]-values[0], end[1]-values[1]), True) if command == 'Q' else incoming
        if math.hypot(*incoming[0]) > .0001:
            maximum = max(maximum, join(previous, incoming))
            if first is None:
                first = incoming
            previous = outgoing
        cursor = end
    return maximum


def audit_svg(svg: str, source: Path) -> dict:
    geometry = parse_svg(svg)
    image = decode(source)
    if image.size != (geometry['width'], geometry['height']):
        raise ValueError('SVG must preserve source dimensions.')
    source_mask = foreground(image)
    rendered = render_svg(svg)
    vector_mask = np.asarray(rendered.getchannel('A')) >= 128
    intersection = int((source_mask & vector_mask).sum())
    union = int((source_mask | vector_mask).sum())
    iou = intersection / max(1, union)
    tiny, lines, curves, tangent_jump = 0, 0, 0, 0.0
    for part in geometry['parts']:
        if part['kind'] != 'path':
            continue
        lines += part['d'].count('L')
        curves += part['d'].count('Q')
        tangent_jump = max(tangent_jump, _curve_tangent_jump(part['d']))
        for loop in part['loops']:
            tiny += sum(math.dist(a, b) <= 1.5 for a, b in zip(loop, loop[1:])) if not part['d'].count('Q') else 0
    smooth = geometry['segments'] <= MAX_SEGMENTS and tangent_jump <= 8 and not (lines > 24 and (tiny/max(1, lines) > .25 or curves == 0))
    return {'passed': smooth and iou >= .88, 'iou': round(iou, 6),
            'source_only_pixels': int((source_mask & ~vector_mask).sum()),
            'vector_only_pixels': int((vector_mask & ~source_mask).sum()),
            'smoothness': {'passed': smooth, 'segment_count': geometry['segments'], 'line_segments': lines,
                           'curve_segments': curves, 'tiny_segment_ratio': round(tiny/max(1, lines), 4),
                           'maximum_curve_tangent_jump_degrees': round(tangent_jump, 4)},
            'thresholds': {'minimum_iou': .88, 'maximum_segments': MAX_SEGMENTS,
                           'maximum_curve_tangent_jump_degrees': 8,
                           'maximum_tiny_segment_ratio_for_long_polylines': .25},
            'visual_review': 'pending; inspect overlay and curves at 200-400% before approval'}


def overlay_strip(svg: str, source: Path) -> Image.Image:
    image = decode(source)
    vector = render_svg(svg)
    base = Image.new('RGBA', image.size, 'white')
    original = Image.alpha_composite(base, image)
    static = Image.alpha_composite(base, vector)
    cyan = Image.new('RGBA', image.size, '#00bfcf')
    cyan.putalpha(vector.getchannel('A').point(lambda a: round(a*.5)))
    overlay = Image.alpha_composite(original, cyan)
    strip = Image.new('RGB', (image.width*3, image.height), 'white')
    for i, panel in enumerate((original, overlay, static)):
        strip.paste(panel.convert('RGB'), (i*image.width, 0))
    return strip
