"""Bounded pragmatic Lottie validation with explicit local-preview limitations.

Format references read 2026-10-14:
https://lottie.github.io/lottie-spec/latest/specs/shapes/
https://lottie.github.io/lottie-spec/latest/specs/properties/
"""

from __future__ import annotations

import json
import math
from pathlib import PurePosixPath

from providers.lottie.contracts import TARGETS

MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_NODES = 100000
MAX_DEPTH = 32
MAX_LAYERS = 128
MAX_KEYFRAMES = 4096
LAYER_TYPES = {0, 1, 2, 3, 4, 5, 6, 13}
SHAPE_TYPES = {"gr", "rc", "el", "sh", "fl", "st", "tr", "tm", "gf", "gs", "sr", "mm", "rp", "rd", "pb", "op", "zz", "tw"}
PREVIEW_SHAPES = {"gr", "rc", "el", "sh", "fl", "st", "tr", "tm"}
META = {"nm", "mn", "ix", "hd", "np", "cix"}


def bounded_json(value: object) -> list[str]:
    """Check structure before any recursive walk, copy or serialization."""
    stack = [(value, 0, False)]
    active = set()
    count = 0
    while stack:
        item, depth, leaving = stack.pop()
        if leaving:
            active.remove(id(item))
            continue
        count += 1
        if count > MAX_NODES:
            return [f"document must contain at most {MAX_NODES} JSON nodes"]
        if depth > MAX_DEPTH:
            return [f"document nesting must be at most {MAX_DEPTH}"]
        if isinstance(item, (dict, list)):
            if id(item) in active:
                return ["document contains a cyclic JSON reference"]
            active.add(id(item))
            stack.append((item, depth, True))
            if isinstance(item, dict):
                if any(not isinstance(key, str) for key in item):
                    return ["document JSON object keys must be strings"]
                stack.extend((child, depth + 1, False) for child in item.values())
            else:
                stack.extend((child, depth + 1, False) for child in item)
        elif type(item) in (int, float) and (abs(item) > 1e12 or isinstance(item, float) and not math.isfinite(item)):
            return ["document numbers must be finite and at most 1e12 in magnitude"]
        elif item is not None and not isinstance(item, (str, int, float, bool)):
            return ["document must contain only JSON values"]
    try:
        size = len(json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode())
    except (ValueError, TypeError, RecursionError):
        return ["document cannot be encoded as bounded JSON"]
    return [f"document must be at most {MAX_JSON_BYTES} bytes"] if size > MAX_JSON_BYTES else []


def _number(value: object) -> bool:
    return type(value) is int or type(value) is float and math.isfinite(value)


def _vector(value: object, sizes: tuple[int, ...]) -> bool:
    return isinstance(value, list) and len(value) in sizes and all(_number(n) for n in value)


class _Validator:
    def __init__(self, document: dict, targets: tuple[str, ...]) -> None:
        self.document = document
        self.errors: list[str] = []
        self.not_previewed: list[str] = []
        self.compatibility: dict[str, list[str]] = {target: [] for target in targets}
        self.ip = document.get("ip", 0)
        self.op = document.get("op", 0)
        self.keyframes = 0
        self.checked_properties: set[int] = set()
        self.asset_ids: set[str] = set()
        self.asset_types: dict[str, str] = {}
        self.asset_edges: dict[str, list[str]] = {}

    def error(self, path: str, message: str) -> None:
        self.errors.append(f"{path} {message}")

    def unsupported(self, path: str, message: str) -> None:
        self.not_previewed.append(f"{path}: {message}")

    def compatibility_warning(self, path: str, message: str, targets: tuple[str, ...] = TARGETS) -> None:
        for target in targets:
            if target in self.compatibility:
                self.compatibility[target].append(f"{path}: {message}")

    def fields(self, value: dict, allowed: set[str], path: str) -> None:
        for name in sorted(set(value) - allowed - META):
            self.unsupported(f"{path}.{name}", "feature is not previewed")

    def scalar(self, value: object, path: str, low: float | None = None, high: float | None = None) -> bool:
        if not _number(value):
            self.error(path, "must be a finite number")
            return False
        if low is not None and value < low or high is not None and value > high:
            self.error(path, f"must be between {low} and {high}")
            return False
        return True

    def path_value(self, value: object, path: str) -> None:
        if not isinstance(value, dict):
            self.error(path, "must be a bezier path object")
            return
        self.fields(value, {"v", "i", "o", "c"}, path)
        points = [value.get(key) for key in ("v", "i", "o")]
        if (any(not isinstance(points_list, list) or not 2 <= len(points_list) <= 2048 for points_list in points)
                or len({len(points_list) for points_list in points if isinstance(points_list, list)}) != 1):
            self.error(path, "v, i and o must contain equal arrays of 2..2048 points")
            return
        for key, points_list in zip(("v", "i", "o"), points):
            for index, point in enumerate(points_list):
                if not _vector(point, (2,)) or any(abs(n) > 32768 for n in point):
                    self.error(f"{path}.{key}[{index}]", "must be an xy pair between -32768 and 32768")
        if type(value.get("c")) is not bool:
            self.error(path + ".c", "must be a boolean")

    def property_value(self, value: object, path: str, kind: str, animated: bool = False) -> None:
        if animated and not isinstance(value, list):
            self.error(path, "animated values must use arrays")
            return
        if kind == "any":
            if isinstance(value, dict) and {"v", "i", "o"}.issubset(value):
                self.path_value(value, path)
            elif not _number(value) and not (isinstance(value, list) and value and
                    (all(_number(n) for n in value) or all(isinstance(n, dict) for n in value))):
                self.error(path, "must be numeric values or bezier geometry")
        elif kind == "path":
            if animated and isinstance(value, list) and len(value) == 1:
                value = value[0]
            self.path_value(value, path)
        elif kind in {"vector", "size", "color"}:
            sizes = (3, 4) if kind == "color" else (2, 3)
            if not _vector(value, sizes):
                self.error(path, f"must be an array of {'3 or 4' if kind == 'color' else '2 or 3'} finite numbers")
            elif kind == "color" and any(not 0 <= n <= 1 for n in value):
                self.error(path, "color channels must be between 0 and 1")
            elif kind == "size" and any(n < 0 or n > 32768 for n in value):
                self.error(path, "size values must be between 0 and 32768")
        else:
            if isinstance(value, list) and len(value) == 1:
                value = value[0]
            if kind == "opacity":
                self.scalar(value, path, 0, 100)
            elif kind == "width":
                self.scalar(value, path, 0, 4096)
            else:
                self.scalar(value, path, -32768, 32768)

    def easing(self, value: object, path: str) -> None:
        if not isinstance(value, dict):
            self.error(path, "must be an easing handle object")
            return
        self.fields(value, {"x", "y"}, path)
        if isinstance(value.get("x"), list) and isinstance(value.get("y"), list) and len(value["x"]) != len(value["y"]):
            self.error(path, "easing x and y must have matching dimensions")
        for key in ("x", "y"):
            axis = value.get(key)
            axis = axis if isinstance(axis, list) else [axis]
            if not axis or len(axis) > 4 or any(not _number(n) for n in axis):
                self.error(path + "." + key, "must contain 1..4 finite easing numbers")
            elif key == "x" and any(not 0 <= n <= 1 for n in axis):
                self.error(path + ".x", "easing x must be between 0 and 1")
            elif key == "y" and any(abs(n) > 16 for n in axis):
                self.error(path + ".y", "easing y must be between -16 and 16")

    def prop(self, prop: object, path: str, kind: str = "scalar") -> None:
        if not isinstance(prop, dict):
            self.error(path, "must be a property object with a and k")
            return
        if id(prop) in self.checked_properties:
            return
        self.checked_properties.add(id(prop))
        if prop.get("s") is True and kind == "vector":
            self.fields(prop, {"s", "x", "y", "z"}, path)
            self.unsupported(path, "separated dimensions are not previewed")
            for axis in ("x", "y"):
                self.prop(prop.get(axis), path + "." + axis)
            if "z" in prop:
                self.prop(prop["z"], path + ".z")
            return
        self.fields(prop, {"a", "k", "x", "sid", "s"}, path)
        if "x" in prop:
            if not isinstance(prop["x"], str):
                self.error(path + ".x", "expression must be a string")
            self.unsupported(path, "expressions are not previewed")
            for target in self.compatibility:
                message = ("expressions require a compatible web player build" if target == "lottie-web"
                           else "expressions are unsupported in the selected native player")
                self.compatibility_warning(path, message, (target,))
        if "sid" in prop:
            slots = self.document.get("slots", {})
            if not isinstance(prop["sid"], str) or not isinstance(slots, dict) or prop["sid"] not in slots:
                self.error(path + ".sid", "must reference an existing slot")
            self.unsupported(path, "slot substitution is not previewed")
        if prop.get("s"):
            self.unsupported(path, "separated dimensions are not previewed")
        if type(prop.get("a")) is not int or prop["a"] not in (0, 1):
            self.error(path + ".a", "must be 0 or 1")
            return
        if "k" not in prop:
            self.error(path + ".k", "is required")
            return
        if prop["a"] == 0:
            self.property_value(prop["k"], path + ".k", kind)
            return
        keys = prop["k"]
        if not isinstance(keys, list) or not 1 <= len(keys) <= 4096:
            self.error(path + ".k", "must contain 1..4096 keyframes")
            return
        self.keyframes += len(keys)
        previous = None
        components = None
        for index, key in enumerate(keys):
            key_path = f"{path}.k[{index}]"
            if not isinstance(key, dict):
                self.error(key_path, "must be a keyframe object")
                continue
            self.fields(key, {"t", "s", "e", "i", "o", "h", "to", "ti"}, key_path)
            if "to" in key or "ti" in key:
                self.unsupported(key_path, "spatial interpolation tangents are not previewed")
            frame = key.get("t")
            if not self.scalar(frame, key_path + ".t"):
                continue
            if previous is not None and frame <= previous:
                self.error(key_path + ".t", "keyframes must be strictly increasing")
            previous = frame
            if _number(self.ip) and _number(self.op) and not self.ip <= frame <= self.op:
                self.error(key_path + ".t", "must fit within document ip..op")
            if "s" not in key and index < len(keys) - 1:
                self.error(key_path + ".s", "is required on nonterminal keyframes")
            for field in ("s", "e"):
                if field in key:
                    self.property_value(key[field], key_path + "." + field, kind, animated=True)
                    value = key[field]
                    if kind in {"vector", "size", "color"} and isinstance(value, list):
                        if components is None:
                            components = len(value)
                        elif len(value) != components:
                            self.error(key_path + "." + field,
                                       f"must preserve keyframe component count {components}")
            if key.get("h", 0) not in (0, 1) or type(key.get("h", 0)) is not int:
                self.error(key_path + ".h", "must be 0 or 1")
            for handle in ("o", "i"):
                if handle in key:
                    self.easing(key[handle], key_path + "." + handle)
                elif index < len(keys) - 1 and key.get("h", 0) == 0:
                    self.error(key_path + "." + handle, "is required for a non-hold interpolation segment")
            if kind == "path":
                self.unsupported(path, "animated path geometry is not previewed")

    def depth_values(self, prop: object, expected: float, path: str) -> None:
        if not isinstance(prop, dict):
            return
        keys = prop.get("k")
        values = [keys] if prop.get("a") == 0 else [key.get(field) for key in keys
                  if isinstance(key, dict) for field in ("s", "e")] if isinstance(keys, list) else []
        if any(isinstance(value, list) and len(value) == 3 and value[2] != expected for value in values):
            self.unsupported(path, "nondefault depth components are not previewed")

    def nonuniform_scale(self, transform: object) -> bool:
        if not isinstance(transform, dict) or not isinstance(transform.get("s"), dict):
            return False
        prop = transform["s"]
        keys = prop.get("k")
        if prop.get("a") == 0:
            return _vector(keys, (2, 3)) and keys[0] != keys[1]
        if not isinstance(keys, list):
            return False
        for key in keys:
            if not isinstance(key, dict):
                continue
            for field in ("s", "e"):
                value = key.get(field)
                if _vector(value, (2, 3)) and value[0] != value[1]:
                    return True
            for handle in ("o", "i"):
                value = key.get(handle)
                if isinstance(value, dict):
                    for axis in ("x", "y"):
                        component = value.get(axis)
                        if isinstance(component, list) and len(component) >= 2 and component[0] != component[1]:
                            return True
        return False

    def has_stroke(self, value: object) -> bool:
        if isinstance(value, dict):
            return value.get("ty") == "st" or any(self.has_stroke(child) for child in value.values())
        return isinstance(value, list) and any(self.has_stroke(child) for child in value)

    def transform(self, transform: object, path: str) -> None:
        if not isinstance(transform, dict):
            self.error(path, "must be a transform object")
            return
        self.fields(transform, {"ty", "a", "p", "s", "r", "o", "rx", "ry", "rz", "or", "sk", "sa"}, path)
        for field, kind in (("a", "vector"), ("p", "vector"), ("s", "vector"), ("r", "scalar"), ("o", "opacity")):
            if field in transform:
                self.prop(transform[field], path + "." + field, kind)
                if field in {"a", "p", "s"}:
                    self.depth_values(transform[field], 100 if field == "s" else 0, path + "." + field)
        for field in ("rx", "ry", "rz", "or", "sk", "sa"):
            if field in transform:
                self.unsupported(path + "." + field, "3D or skew transform is not previewed")

    def shapes(self, shapes: object, path: str) -> None:
        if not isinstance(shapes, list):
            self.error(path, "must be an array")
            return
        types = [shape.get("ty") for shape in shapes if isinstance(shape, dict)]
        seen_style = False
        for kind in types:
            if not isinstance(kind, str):
                continue
            if kind in {"fl", "st", "tm", "tr"}:
                seen_style = True
            elif seen_style and kind in {"rc", "el", "sh"}:
                self.unsupported(path, "geometry after styles is not previewed")
        if self.has_stroke(shapes) and any(isinstance(shape, dict) and shape.get("ty") == "tr"
                                          and self.nonuniform_scale(shape) for shape in shapes):
            self.unsupported(path, "nonuniform scaled strokes are not previewed")
        direct = sum(isinstance(kind, str) and kind in {"rc", "el", "sh"} for kind in types)
        if direct > 1 or direct and "gr" in types:
            self.unsupported(path, "mixed groups or multiple geometries in one style scope are not previewed")
        for kind in ("fl", "st", "tm", "tr"):
            if types.count(kind) > 1:
                self.unsupported(path, f"multiple {kind} operators in a style scope are not previewed")
        if "tr" in types and types[-1] != "tr":
            self.unsupported(path, "group transform must be last for preview")
        if "tm" in types and ("fl" in types or direct and "sh" not in types):
            self.unsupported(path, "trim preview requires one stroked path without fill")
        for index, shape in enumerate(shapes):
            p = f"{path}[{index}]"
            if not isinstance(shape, dict):
                self.error(p, "must be a shape object")
                continue
            ty = shape.get("ty")
            if not isinstance(ty, str) or ty not in SHAPE_TYPES:
                self.error(p, f"has unknown shape type {ty!r}")
                continue
            if ty not in PREVIEW_SHAPES:
                self.unsupported(p, f"shape type {ty} is not previewed")
                self.compatibility_warning(p, f"shape type {ty} needs target-player verification")
                continue
            allowed = {"ty"}
            if ty == "gr":
                allowed |= {"it", "bm"}
                self.shapes(shape.get("it"), p + ".it")
                if shape.get("bm", 0):
                    self.unsupported(p, "group blend modes are not previewed")
            elif ty == "tr":
                self.transform(shape, p)
                continue
            else:
                properties = {
                    "rc": {"p": "vector", "s": "size", "r": "width"},
                    "el": {"p": "vector", "s": "size"}, "sh": {"ks": "path"},
                    "fl": {"c": "color", "o": "opacity"},
                    "st": {"c": "color", "o": "opacity", "w": "width"},
                    "tm": {"s": "opacity", "e": "opacity", "o": "scalar"},
                }[ty]
                allowed |= set(properties)
                for field, kind in properties.items():
                    if field not in shape:
                        self.error(p + "." + field, "is required")
                    else:
                        self.prop(shape[field], p + "." + field, kind)
                allowed |= {"d"} if ty in {"rc", "el", "sh"} else set()
                if ty in {"rc", "el", "sh"} and shape.get("d", 1) != 1:
                    self.unsupported(p + ".d", "reversed path direction is not previewed")
                if ty == "fl":
                    allowed |= {"r", "bm"}
                    if shape.get("r", 1) != 1:
                        self.unsupported(p, "nondefault fill rule is not previewed")
                    if shape.get("bm", 0):
                        self.unsupported(p, "fill blend mode is not previewed")
                if ty == "st":
                    allowed |= {"lc", "lj", "ml", "bm", "d"}
                    if shape.get("lc", 1) not in (1, 2, 3) or shape.get("lj", 1) not in (1, 2, 3):
                        self.unsupported(p, "stroke cap or join is not previewed")
                    if shape.get("d"):
                        self.unsupported(p, "stroke dashes are not previewed")
                    if shape.get("bm", 0):
                        self.unsupported(p, "stroke blend mode is not previewed")
                if ty == "tm":
                    allowed |= {"m"}
                    if shape.get("m", 1) != 1 or shape.get("o") != {"a": 0, "k": 0}:
                        self.unsupported(p, "trim requires individual mode and zero offset for preview")
            self.fields(shape, allowed, p)

    def layers(self, layers: object, path: str, asset_id: str | None = None) -> None:
        if not isinstance(layers, list):
            self.error(path, "must be an array")
            return
        if len(layers) > MAX_LAYERS:
            self.error(path, f"must contain at most {MAX_LAYERS} layers")
            return
        indexes = set()
        parents = {}
        for index, layer in enumerate(layers):
            p = f"{path}[{index}]"
            if not isinstance(layer, dict):
                self.error(p, "must be a layer object")
                continue
            self.fields(layer, {"ty", "ind", "parent", "ddd", "ip", "op", "st", "sr", "ks", "shapes", "refId", "bm",
                                "ef", "masksProperties", "tt", "td", "tm", "t", "ao", "sw", "sh", "sc", "cl", "ln"}, p)
            ty = layer.get("ty")
            if type(ty) is not int or ty not in LAYER_TYPES:
                self.error(p + ".ty", f"has unknown layer type {ty!r}")
                continue
            if ty not in (3, 4):
                self.unsupported(p, f"layer type {ty} is not previewed")
            ind = layer.get("ind")
            if type(ind) is not int or ind < 0:
                self.error(p + ".ind", "must be a nonnegative integer")
            elif ind in indexes:
                self.error(p + ".ind", f"duplicates layer index {ind}")
            else:
                indexes.add(ind)
            if "parent" in layer:
                if type(layer["parent"]) is not int:
                    self.error(p + ".parent", "must be an integer")
                elif type(ind) is int and ind >= 0:
                    parents[ind] = layer["parent"]
            ip, op = layer.get("ip"), layer.get("op")
            if self.scalar(ip, p + ".ip") and self.scalar(op, p + ".op") and op <= ip:
                self.error(p + ".op", "must be greater than ip")
            if "ks" not in layer:
                self.error(p + ".ks", "is required")
            else:
                self.transform(layer["ks"], p + ".ks")
            if ty == 4:
                self.shapes(layer.get("shapes"), p + ".shapes")
            if ty in {0, 2}:
                ref = layer.get("refId")
                if not isinstance(ref, str) or ref not in self.asset_ids:
                    self.error(p + ".refId", f"has missing asset reference {ref!r}")
                else:
                    expected_type = "precomposition" if ty == 0 else "image"
                    if self.asset_types.get(ref) != expected_type:
                        self.error(p + ".refId", f"must reference a {expected_type} asset")
                    if isinstance(asset_id, str):
                        self.asset_edges.setdefault(asset_id, []).append(ref)
            for field, reason in (("ef", "effects"), ("masksProperties", "masks"), ("tt", "track mattes"),
                                  ("td", "track mattes"), ("tm", "time remapping"), ("t", "text")):
                if layer.get(field):
                    self.unsupported(p, f"{reason} are not previewed")
                    self.compatibility_warning(p, f"{reason} support varies by player; verify on each target")
            if layer.get("bm", 0):
                self.unsupported(p, "blend modes are not previewed")
                self.compatibility_warning(p, "blend mode support varies by target player")
            if layer.get("ddd", 0) or layer.get("ao", 0):
                self.unsupported(p, "3D or auto-orientation is not previewed")
            if layer.get("sr", 1) != 1 or layer.get("st", 0) != 0:
                self.unsupported(p, "layer time stretching or time offset is not previewed")
        layer_indexes = {layer.get("ind"): layer for layer in layers if isinstance(layer, dict) and type(layer.get("ind")) is int}
        for index, layer in enumerate(layers):
            if not isinstance(layer, dict) or not self.has_stroke(layer.get("shapes")):
                continue
            cursor = layer
            visited_scales: set[int] = set()
            while cursor is not None and id(cursor) not in visited_scales:
                visited_scales.add(id(cursor))
                if self.nonuniform_scale(cursor.get("ks")):
                    self.unsupported(f"{path}[{index}]", "nonuniform scaled strokes are not previewed")
                    break
                parent_index = cursor.get("parent")
                cursor = layer_indexes.get(parent_index) if type(parent_index) is int else None
        for ind, parent in parents.items():
            if parent not in indexes:
                self.error(path, f"layer {ind} has missing parent {parent}")
            visited = set()
            cursor = ind
            while cursor in parents:
                if cursor in visited:
                    self.error(path, f"parent cycle includes layer {cursor}")
                    break
                visited.add(cursor)
                cursor = parents[cursor]

    def assets(self, assets: object) -> None:
        if not isinstance(assets, list):
            self.error("assets", "must be an array")
            return
        if len(assets) > 128:
            self.error("assets", "must contain at most 128 assets")
            return
        for index, asset in enumerate(assets):
            p = f"assets[{index}]"
            if not isinstance(asset, dict):
                self.error(p, "must be an asset object")
                continue
            ident = asset.get("id")
            if not isinstance(ident, str) or not ident or len(ident) > 128:
                self.error(p + ".id", "must be a nonempty string of at most 128 characters")
            elif ident in self.asset_ids:
                self.error(p + ".id", f"duplicates asset id {ident!r}")
            else:
                self.asset_ids.add(ident)
                self.asset_types[ident] = "precomposition" if "layers" in asset else "image"
            if "layers" not in asset and "p" not in asset:
                self.error(p, "must contain precomposition layers or an image path")
            if "layers" in asset and "p" in asset:
                self.error(p, "cannot combine precomposition layers and an image path")
            self.fields(asset, {"id", "w", "h", "p", "u", "e", "layers", "fr"}, p)
            if "p" in asset or "u" in asset:
                for field in ("p", "u"):
                    value = asset.get(field, "")
                    if (not isinstance(value, str) or field == "p" and not value or ":" in value or "\\" in value or "\x00" in value
                            or PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts):
                        self.error(p + "." + field, "external, data and unconfined assets are forbidden")
                if asset.get("e", 0):
                    self.error(p + ".e", "embedded data assets are forbidden")
            self.unsupported(p, "image and precomposition assets are not previewed")
        for index, asset in enumerate(assets):
            if isinstance(asset, dict) and "layers" in asset:
                self.layers(asset["layers"], f"assets[{index}].layers", asset.get("id"))
        visited: set[str] = set()
        active: set[str] = set()

        def visit(ident: str) -> None:
            if ident in active:
                self.error("assets", f"asset cycle includes {ident!r}")
                return
            if ident in visited:
                return
            active.add(ident)
            for child in self.asset_edges.get(ident, []):
                visit(child)
            active.remove(ident)
            visited.add(ident)

        for ident in self.asset_edges:
            visit(ident)

    def remaining_properties(self, value: object, path: str = "document") -> None:
        if isinstance(value, dict):
            if "a" in value and "k" in value and id(value) not in self.checked_properties:
                self.prop(value, path, "any")
            for key, item in value.items():
                self.remaining_properties(item, path + "." + key)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                self.remaining_properties(item, f"{path}[{index}]")



def validate_document(document: dict, targets: tuple[str, ...] = TARGETS) -> dict:
    """Return actionable errors and conservative target and preview reports."""
    targets = tuple(targets)
    errors = bounded_json(document)
    if not isinstance(document, dict):
        errors.append("document must be a JSON object")
    unknown = [target for target in targets if target not in TARGETS]
    if unknown:
        errors.append(f"unknown compatibility targets: {', '.join(str(item) for item in unknown)}")
    if errors:
        return {"ok": False, "errors": errors, "compatibility": {target: [] for target in targets if target in TARGETS},
                "not_previewed": [], "metadata": {}}
    validator = _Validator(document, targets)
    for key in ("v", "fr", "ip", "op", "w", "h", "nm", "assets", "layers"):
        if key not in document:
            validator.error(key, "is required")
    if not isinstance(document.get("v"), str) or not document["v"]:
        validator.error("v", "must be a nonempty version string")
    if not isinstance(document.get("nm"), str) or not document["nm"].strip():
        validator.error("nm", "must be a nonblank name")
    for key in ("w", "h"):
        if type(document.get(key)) is not int:
            validator.error(key, "must be an integer")
        elif not 16 <= document[key] <= 2048:
            validator.error(key, "must be between 16 and 2048")
    fps, ip, op = document.get("fr"), document.get("ip"), document.get("op")
    if not _number(fps) or not 1 <= fps <= 120:
        validator.error("fr", "must be between 1 and 120")
    timing_valid = _number(ip) and _number(op)
    metadata = {}
    if not timing_valid:
        validator.error("ip/op", "must be finite numbers")
    elif ip < 0:
        validator.error("ip", "must be nonnegative")
    elif op <= ip:
        validator.error("op", "must be greater than ip")
    elif op - ip > 3600:
        validator.error("op/ip", "frame count must be at most 3600")
    elif _number(fps) and fps > 0:
        if (op - ip) / fps > 120:
            validator.error("op/fr", "duration must be at most 120 seconds")
        metadata = {"width": document.get("w"), "height": document.get("h"), "fps": fps,
                    "frame_count": math.ceil(op - ip), "duration_seconds": (op - ip) / fps}
    validator.fields(document, {"v", "fr", "ip", "op", "w", "h", "nm", "ddd", "assets", "layers", "meta", "markers", "slots", "chars", "fonts"}, "document")
    for key in ("slots", "chars", "fonts"):
        if document.get(key):
            validator.unsupported("document." + key, "feature is not previewed")
    if document.get("ddd", 0):
        validator.unsupported("document.ddd", "3D compositions are not previewed")
    validator.assets(document.get("assets"))
    validator.layers(document.get("layers"), "layers")
    if isinstance(document.get("layers"), list) and len(document["layers"]) > 64:
        validator.unsupported("layers", "local preview supports at most 64 layers")
    validator.remaining_properties(document)
    if validator.keyframes > MAX_KEYFRAMES:
        validator.error("document", f"must contain at most {MAX_KEYFRAMES} keyframes")
    return {"ok": not validator.errors, "errors": list(dict.fromkeys(validator.errors)),
            "compatibility": validator.compatibility,
            "not_previewed": list(dict.fromkeys(validator.not_previewed)), "metadata": metadata}
