"""Convert a strict, self-contained SVG subset into native animated paths."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

from providers.lottie.authoring import author_document

_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_TOKEN = re.compile(rf"[A-Za-z]|{_NUMBER}")
_STYLE = {"fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "opacity"}
_GEOMETRY = {"svg": {"viewBox", "width", "height"}, "g": set(), "path": {"d"},
             "polyline": {"points"}, "polygon": {"points"}, "rect": {"x", "y", "width", "height"},
             "circle": {"cx", "cy", "r"}, "ellipse": {"cx", "cy", "rx", "ry"}}


def _number(value: str, context: str) -> float:
    if not re.fullmatch(_NUMBER, value):
        raise ValueError(f"{context} requires a plain finite number without units")
    result = float(value)
    if not math.isfinite(result) or abs(result) > 32768:
        raise ValueError(f"{context} must be finite and between -32768 and 32768")
    return result


def _numbers(value: str, context: str) -> list[float]:
    tokens = re.findall(_NUMBER, value)
    leftover = re.sub(_NUMBER, "", value)
    if leftover.strip(" \t\r\n,"):
        raise ValueError(f"{context} contains unsupported syntax")
    return [_number(token, context) for token in tokens]


def _path(source: str) -> dict:
    tokens = _TOKEN.findall(source)
    if _TOKEN.sub("", source).strip(" \t\r\n,"):
        raise ValueError("SVG path contains unsupported syntax")
    if len(tokens) > 16384:
        raise ValueError("SVG path contains too many commands")
    vertices: list[list[float]] = []
    incoming: list[list[float]] = []
    outgoing: list[list[float]] = []
    current = [0.0, 0.0]
    command = ""
    closed = False
    offset = 0
    arity = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "Q": 4}
    while offset < len(tokens):
        if tokens[offset].isalpha():
            command = tokens[offset]
            offset += 1
            if command.upper() == "Z":
                if not vertices or offset != len(tokens):
                    raise ValueError("SVG closepath must finish a nonempty single subpath")
                closed = True
                break
        upper = command.upper()
        if upper not in arity:
            raise ValueError(f"SVG path command {command!r} is unsupported; use M/L/H/V/C/Q/Z")
        count = arity[upper]
        if offset + count > len(tokens) or any(token.isalpha() for token in tokens[offset:offset + count]):
            raise ValueError(f"SVG path command {command} has incomplete coordinates")
        values = [_number(token, "SVG path") for token in tokens[offset:offset + count]]
        offset += count
        relative = command.islower()
        if not vertices and upper != "M":
            raise ValueError("SVG path must begin with moveto")
        if upper == "M" and vertices:
            raise ValueError("SVG multiple subpaths are unsupported; split into separate paths")

        def point(x: float, y: float) -> list[float]:
            return [x + current[0], y + current[1]] if relative else [x, y]

        if upper in {"M", "L"}:
            end = point(*values)
        elif upper == "H":
            end = [values[0] + current[0] if relative else values[0], current[1]]
        elif upper == "V":
            end = [current[0], values[0] + current[1] if relative else values[0]]
        else:
            end = point(*values[-2:])
        arrive = [0.0, 0.0]
        if upper == "C":
            first, second = point(*values[:2]), point(*values[2:4])
            outgoing[-1] = [first[i] - current[i] for i in (0, 1)]
            arrive = [second[i] - end[i] for i in (0, 1)]
        elif upper == "Q":
            control = point(*values[:2])
            outgoing[-1] = [(control[i] - current[i]) * 2 / 3 for i in (0, 1)]
            arrive = [(control[i] - end[i]) * 2 / 3 for i in (0, 1)]
        vertices.append(end)
        incoming.append(arrive)
        outgoing.append([0.0, 0.0])
        current = end
        if upper == "M":
            command = "l" if relative else "L"
        if len(vertices) > 2048:
            raise ValueError("SVG path must have at most 2048 vertices")
    if len(vertices) < 2:
        raise ValueError("SVG path requires at least two vertices")
    return {"v": vertices, "i": incoming, "o": outgoing, "c": closed}


def _color(value: str, context: str) -> str | None:
    if value == "none":
        return None
    if not re.fullmatch(r"#[0-9A-Fa-f]{3}(?:[0-9A-Fa-f]{3})?", value):
        raise ValueError(f"{context} requires none or a #RGB/#RRGGBB color")
    return "#" + "".join(char * 2 for char in value[1:]) if len(value) == 4 else value


def svg_document(source: bytes, *, name: str = "animation") -> dict:
    """Refuse unsupported SVG content instead of silently losing visual data."""
    if not isinstance(source, bytes) or len(source) > 1024 * 1024:
        raise ValueError("SVG input must be bytes of at most 1 MiB")
    try:
        text = source.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("SVG must use UTF-8") from exc
    if re.search(r"<!|&", text) or re.search(r"<\?(?!xml\s)", text, re.I):
        raise ValueError("SVG entities, DOCTYPE, declarations and processing instructions are forbidden")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"SVG XML is malformed: {exc}") from exc

    def tag_for(element: ET.Element) -> str:
        tag = element.tag
        if tag.startswith("{http://www.w3.org/2000/svg}"):
            return tag.split("}", 1)[1]
        if "{" in tag or ":" in tag:
            raise ValueError("SVG foreign namespaces are forbidden")
        return tag

    if tag_for(root) != "svg":
        raise ValueError("SVG root must be svg")
    if "viewBox" in root.attrib:
        viewport = _numbers(root.attrib["viewBox"], "SVG viewBox")
        if len(viewport) != 4:
            raise ValueError("SVG viewBox requires four numbers")
        left, top, width, height = viewport
    else:
        left = top = 0.0
        if "width" not in root.attrib or "height" not in root.attrib:
            raise ValueError("SVG requires viewBox or width and height")
        width = _number(root.attrib["width"], "SVG width")
        height = _number(root.attrib["height"], "SVG height")
    if width <= 0 or height <= 0:
        raise ValueError("SVG viewBox dimensions must be positive")
    if not width.is_integer() or not height.is_integer() or not 16 <= width <= 2048 or not 16 <= height <= 2048:
        raise ValueError("SVG viewport dimensions must be whole pixels between 16 and 2048")
    for attr, dimension in (("width", width), ("height", height)):
        if attr in root.attrib and _number(root.attrib[attr], "SVG " + attr) != dimension:
            raise ValueError("SVG viewport scaling is unsupported; width/height must match viewBox dimensions")
    layers = []
    caps = []
    joins = []
    stack = [(root, {"fill": "#000000", "stroke": "none", "stroke-width": "1", "stroke-linecap": "butt", "stroke-linejoin": "miter", "opacity": "1"}, 0)]
    count = 0
    while stack:
        element, inherited, depth = stack.pop()
        count += 1
        if count > 128 or depth > 16:
            raise ValueError("SVG supports at most 128 elements and nesting depth 16")
        tag = tag_for(element)
        if tag not in _GEOMETRY or tag == "svg" and element is not root:
            raise ValueError(f"SVG element {tag!r} is unsupported")
        unknown = set(element.attrib) - _GEOMETRY[tag] - _STYLE - {"id"}
        if unknown:
            raise ValueError(f"SVG {tag} unsupported attributes: {', '.join(sorted(unknown))}")
        if (element.text or "").strip() or (element.tail or "").strip():
            raise ValueError("SVG text content is unsupported; use outlined paths")
        style = inherited | {key: value for key, value in element.attrib.items() if key in _STYLE}
        if "opacity" in element.attrib:
            local_opacity = _number(element.attrib["opacity"], "SVG opacity")
            if not 0 <= local_opacity <= 1:
                raise ValueError("SVG opacity must be between 0 and 1")
            if element is not root and local_opacity != 1 and list(element):
                raise ValueError("SVG group opacity below one is unsupported; flatten the group")
            style["opacity"] = str(_number(inherited["opacity"], "SVG opacity") * local_opacity)
        if tag in {"svg", "g"}:
            if element is root and _number(style["opacity"], "SVG opacity") != 1:
                raise ValueError("SVG root opacity below one is unsupported; flatten the artwork")
            stack.extend((child, style, depth + 1) for child in reversed(list(element)))
            continue
        if list(element):
            raise ValueError(f"SVG {tag} must not contain child elements")
        if len(layers) >= 64:
            raise ValueError("SVG supports at most 64 drawable shapes")
        fill = _color(style["fill"], "SVG fill")
        stroke = _color(style["stroke"], "SVG stroke")
        if fill is None and stroke is None:
            raise ValueError("SVG shapes must have visible fill or stroke")
        stroke_width = _number(style["stroke-width"], "SVG stroke-width")
        if stroke_width <= 0 or stroke_width > 256:
            raise ValueError("SVG stroke-width must be positive and at most 256")
        cap = {"butt": 1, "round": 2}.get(style["stroke-linecap"])
        join = {"miter": 1, "round": 2}.get(style["stroke-linejoin"])
        if cap is None or join is None:
            raise ValueError("SVG stroke supports butt/round caps and miter/round joins")
        layer = {"name": element.attrib.get("id") or f"{tag} {len(layers) + 1}",
                 "position": [-left, -top], "fill": fill, "stroke": stroke,
                 "stroke_width": stroke_width, "opacity": _number(style["opacity"], "SVG opacity") * 100}
        attrs = element.attrib
        if tag == "path":
            layer.update({"shape": "path", "path": _path(attrs.get("d", ""))})
        elif tag in {"polyline", "polygon"}:
            values = _numbers(attrs.get("points", ""), "SVG points")
            if len(values) < 4 or len(values) % 2:
                raise ValueError("SVG points require at least two complete xy pairs")
            vertices = [values[i:i + 2] for i in range(0, len(values), 2)]
            layer.update({"shape": "path", "path": {"v": vertices, "i": [[0, 0] for _ in vertices],
                "o": [[0, 0] for _ in vertices], "c": tag == "polygon"}})
        elif tag == "rect":
            x, y = [_number(attrs.get(key, "0"), "SVG " + key) for key in ("x", "y")]
            size = [_number(attrs.get(key, "0"), "SVG " + key) for key in ("width", "height")]
            if any(value <= 0 for value in size):
                raise ValueError("SVG rectangle dimensions must be positive")
            layer.update({"shape": "rectangle", "size": size, "position": [x + size[0] / 2 - left, y + size[1] / 2 - top]})
        else:
            x, y = [_number(attrs.get(key, "0"), "SVG " + key) for key in ("cx", "cy")]
            radii = [_number(attrs.get(key, "0"), "SVG " + key) for key in (("r", "r") if tag == "circle" else ("rx", "ry"))]
            if any(value <= 0 for value in radii):
                raise ValueError("SVG ellipse radii must be positive")
            layer.update({"shape": "ellipse", "size": [2 * value for value in radii], "position": [x - left, y - top]})
        if layer["shape"] == "path" and stroke is not None and fill is None:
            layer["animate"] = [{"property": "trim_end", "keyframes": [{"frame": 0, "value": 0, "easing": "ease-in-out"}, {"frame": 60, "value": 100}]}]
        layers.append(layer)
        caps.append(cap)
        joins.append(join)
    document = author_document({"width": int(width), "height": int(height), "name": name, "layers": layers})
    for layer, cap, join in zip(document["layers"], caps, joins):
        for shape in layer["shapes"]:
            if shape["ty"] == "st":
                shape.update({"lc": cap, "lj": join})
    # SVG paints later elements on top; Lottie places the first layer on top.
    document["layers"].reverse()
    return document
