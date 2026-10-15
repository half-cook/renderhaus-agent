"""Turn a bounded scene into native Lottie JSON without model calls."""

from __future__ import annotations

from copy import deepcopy

from providers.lottie.contracts import AnimationTrack, SceneSpec

EASING = {
    "linear": (0.0, 0.0, 1.0, 1.0),
    "ease-in": (0.42, 0.0, 1.0, 1.0),
    "ease-out": (0.0, 0.0, 0.58, 1.0),
    "ease-in-out": (0.42, 0.0, 0.58, 1.0),
}


def static(value: object) -> dict:
    return {"a": 0, "k": value}


def _color(value: str) -> list[float]:
    return [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)] + [1.0]


def _animated(track: AnimationTrack) -> dict:
    keys = []
    for index, key in enumerate(track.keyframes):
        value = list(key.value) if isinstance(key.value, list) else [key.value]
        if track.property in {"position", "scale"}:
            value.append(100 if track.property == "scale" else 0)
        entry = {"t": key.frame, "s": value}
        if index < len(track.keyframes) - 1:
            x1, y1, x2, y2 = EASING[key.easing]
            entry.update({"o": {"x": [x1], "y": [y1]}, "i": {"x": [x2], "y": [y2]}})
        keys.append(entry)
    return {"a": 1, "k": keys}


def author_document(scene: dict) -> dict:
    spec = SceneSpec.model_validate(scene)
    document = {"v": "5.12.2", "nm": spec.name, "fr": spec.fps, "ip": 0,
                "op": spec.frames, "w": spec.width, "h": spec.height,
                "ddd": 0, "assets": [], "layers": []}
    for index, layer in enumerate(spec.layers, 1):
        transform = {"a": static([0, 0, 0]), "p": static([*(layer.position or [spec.width / 2, spec.height / 2]), 0]),
                     "s": static([100, 100, 100]), "r": static(layer.rotation), "o": static(layer.opacity)}
        if layer.shape == "path":
            shapes = [{"ty": "sh", "nm": layer.name + " path", "ks": static(layer.path.model_dump())}]
        else:
            shapes = [{"ty": "rc" if layer.shape == "rectangle" else "el", "nm": layer.name + " geometry",
                       "p": static([0, 0]), "s": static(layer.size), "d": 1}]
            if layer.shape == "rectangle":
                shapes[0]["r"] = static(0)
        if layer.fill is not None:
            shapes.append({"ty": "fl", "nm": "Fill", "c": static(_color(layer.fill)), "o": static(100), "r": 1})
        if layer.stroke is not None:
            shapes.append({"ty": "st", "nm": "Stroke", "c": static(_color(layer.stroke)),
                           "o": static(100), "w": static(layer.stroke_width), "lc": 2, "lj": 2})
        for track in layer.animate:
            if track.property == "trim_end":
                shapes.append({"ty": "tm", "nm": "Path reveal", "s": static(0), "e": _animated(track), "o": static(0), "m": 1})
            else:
                key = {"position": "p", "scale": "s", "rotation": "r", "opacity": "o"}[track.property]
                transform[key] = _animated(track)
        document["layers"].append({"ty": 4, "ind": index, "nm": layer.name, "ddd": 0,
                                   "ip": 0, "op": spec.frames, "st": 0, "ks": transform, "shapes": shapes})
    if spec.background is not None:
        document["layers"].append({"ty": 4, "ind": len(spec.layers) + 1, "nm": "Background", "ddd": 0,
            "ip": 0, "op": spec.frames, "st": 0,
            "ks": {"a": static([0, 0, 0]), "p": static([spec.width / 2, spec.height / 2, 0]),
                   "s": static([100, 100, 100]), "r": static(0), "o": static(100)},
            "shapes": [{"ty": "rc", "p": static([0, 0]), "s": static([spec.width, spec.height]), "r": static(0)},
                       {"ty": "fl", "c": static(_color(spec.background)), "o": static(100), "r": 1}]})
    return document


def patch_document(document: dict, patch: dict) -> dict:
    from providers.lottie.validation import bounded_json

    for value in (document, patch):
        errors = bounded_json(value)
        if errors:
            raise ValueError("; ".join(errors))
    result = deepcopy(document)

    def merge(target: dict, changes: dict) -> None:
        for key, value in changes.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                merge(target[key], value)
            else:
                target[key] = deepcopy(value)

    merge(result, patch)
    errors = bounded_json(result)
    if errors:
        raise ValueError("; ".join(errors))
    return result
