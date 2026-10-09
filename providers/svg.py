"""Persist passive SVG geometry only. Active content and external resources are removed."""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET


SVG_MIME = "image/svg+xml"
MAX_SVG_BYTES = 20 * 1024 * 1024
SVG_NS = "http://www.w3.org/2000/svg"
ELEMENTS = frozenset({
    "svg", "g", "defs", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "text", "tspan", "title", "desc", "linearGradient", "radialGradient", "stop", "clipPath",
    "mask", "pattern", "use",
})
ATTRIBUTES = frozenset({
    "id", "viewBox", "width", "height", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy",
    "r", "rx", "ry", "d", "points", "transform", "fill", "fill-rule", "fill-opacity",
    "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-miterlimit",
    "stroke-dasharray", "stroke-dashoffset", "stroke-opacity", "opacity", "clip-path",
    "clip-rule", "mask", "offset", "stop-color", "stop-opacity", "gradientUnits",
    "gradientTransform", "spreadMethod", "fx", "fy", "fr", "patternUnits",
    "patternContentUnits", "patternTransform", "preserveAspectRatio", "clipPathUnits",
    "maskUnits", "maskContentUnits", "font-family", "font-size", "font-weight", "font-style",
    "text-anchor", "dominant-baseline", "letter-spacing", "word-spacing", "dx", "dy",
    "rotate", "textLength", "lengthAdjust", "vector-effect", "href",
})
FRAGMENT = re.compile(r"#[A-Za-z_][\w.-]*\Z")
LOCAL_URL = re.compile(r"url\(\s*#[A-Za-z_][\w.-]*\s*\)", re.I)


def sanitize_svg(content: bytes) -> bytes:
    if not content or len(content) > MAX_SVG_BYTES:
        raise ValueError("SVG must be non-empty and at most 20 MiB.")
    try:
        document = content.decode("utf-8-sig")
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)", document, re.I):
            raise ValueError("SVG document types and entities are forbidden.")
        root = ET.fromstring(document)
    except (UnicodeDecodeError, ET.ParseError) as exc:
        raise ValueError("SVG must be valid UTF-8 XML.") from exc
    if root.tag not in {"svg", f"{{{SVG_NS}}}svg"}:
        raise ValueError("SVG must have an SVG root element.")
    stack = [(root, 0)]
    count = 0
    while stack:
        node, depth = stack.pop()
        count += 1
        if depth > 128 or count > 100000:
            raise ValueError("SVG exceeds the supported geometry complexity.")
        for key, value in list(node.attrib.items()):
            local = "href" if key == "{http://www.w3.org/1999/xlink}href" else key
            safe = local in ATTRIBUTES
            if local == "href":
                safe = safe and bool(FRAGMENT.fullmatch(value))
            without_local_urls = LOCAL_URL.sub("", value)
            if re.search(r"url\s*\(|javascript\s*:|data\s*:|https?\s*:|expression\s*\(|[\\\x00-\x1f]", without_local_urls, re.I):
                safe = False
            if not safe:
                del node.attrib[key]
        for child in list(node):
            tag = child.tag.removeprefix(f"{{{SVG_NS}}}")
            if tag not in ELEMENTS:
                node.remove(child)
            else:
                stack.append((child, depth + 1))
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
