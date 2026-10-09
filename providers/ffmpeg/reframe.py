from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path


ASPECTS = json.loads((Path(__file__).parents[1] / "remotion/ad_layouts.json").read_text())
ASPECTS.setdefault("2.39:1", {"size": [1920, 804], "safe": dict(ASPECTS["16:9"]["safe"])})
MAX_DIMENSION = 16384
MAX_SHOTS = 60


def finite(value, name, low, high):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not low <= value <= high
            or (isinstance(value, float) and not math.isfinite(value))):
        raise ValueError(f"{name} must be a finite number between {low} and {high}.")
    return value


def display_size(width, height, rotation=0):
    for name, value in (("source_width", width), ("source_height", height)):
        finite(value, name, 2, MAX_DIMENSION)
        if not isinstance(value, int):
            raise ValueError(f"{name} must be an integer.")
    finite(rotation, "rotation", -360, 360)
    if rotation % 90:
        raise ValueError("rotation must be a multiple of 90 degrees.")
    return (height, width) if int(rotation / 90) % 2 else (width, height)


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    def json(self):
        return dict(x=self.x, y=self.y, width=self.width, height=self.height)


def validated_box(value, width, height, *, crop=False):
    if not isinstance(value, dict) or set(value) != {"x", "y", "width", "height"}:
        raise ValueError("A box requires exactly x, y, width and height in display-oriented pixels.")
    for name in value:
        finite(value[name], name, 0 if name in {"x", "y"} else 1, MAX_DIMENSION)
        if crop and (not isinstance(value[name], int) or value[name] % 2):
            raise ValueError("Crop coordinates and dimensions must be even integers.")
    box = Box(**value)
    if box.x + box.width > width or box.y + box.height > height:
        raise ValueError("The box must fit inside the displayed source frame.")
    return box


def validated_safe_zone(value):
    if not isinstance(value, dict) or set(value) - {"top", "bottom", "side"}:
        raise ValueError("safe_zone accepts only top, bottom and side fractions.")
    zone = {name: finite(value.get(name, 0), name, 0, .49) for name in ("top", "bottom", "side")}
    if 1 - zone["top"] - zone["bottom"] < .05 or 1 - 2 * zone["side"] < .05:
        raise ValueError("safe_zone must leave at least five percent of each canvas dimension.")
    return zone


def _even(value):
    return int(value) // 2 * 2


def _place(center, length, frame, subject_start=None, subject_length=None, before=0, after=0):
    low, high = 0, frame - length
    if subject_start is not None:
        low = max(low, subject_start + subject_length - length * (1 - after))
        high = min(high, subject_start - length * before)
    low, high = math.ceil(low / 2) * 2, _even(high)
    if low > high:
        return None
    return max(low, min(_even(center - length / 2), high))


def crop_plan(source_width, source_height, aspect, *, subject_box=None, crop_box=None,
              anchor="center", safe_zone=None, rotation=0, allow_upscale=False, target_size=None):
    width, height = display_size(source_width, source_height, rotation)
    if not isinstance(aspect, str) or aspect not in ASPECTS:
        raise ValueError("aspect must be one of " + ", ".join(ASPECTS) + ".")
    if anchor not in {"center", "top", "bottom", "left", "right"}:
        raise ValueError("anchor must be center, top, bottom, left or right.")
    if type(allow_upscale) is not bool:
        raise ValueError("allow_upscale must be a boolean.")
    safe = validated_safe_zone(ASPECTS[aspect]["safe"] if safe_zone is None else safe_zone)
    subject = validated_box(subject_box, width, height) if subject_box is not None else None
    nominal = tuple(ASPECTS[aspect]["size"])
    target = nominal if target_size is None else target_size
    if not isinstance(target, (list, tuple)) or len(target) != 2:
        raise ValueError("target_size requires width and height.")
    display_size(*target)
    target = tuple(_even(value) for value in target)
    ratio = nominal[0] / nominal[1]
    if abs(target[0] - target[1] * ratio) > 2 + 2 * ratio:
        raise ValueError("target_size must match the aspect table within even-pixel rounding.")
    crop_width = _even(min(width, height * ratio))
    crop_height = _even(min(height, width / ratio))
    center_x, center_y = width / 2, height / 2
    if subject:
        center_x, center_y = subject.x + subject.width / 2, subject.y + subject.height / 2
    elif anchor in {"left", "right"}:
        center_x = 0 if anchor == "left" else width
    elif anchor in {"top", "bottom"}:
        center_y = 0 if anchor == "top" else height
    x = _place(center_x, crop_width, width, subject.x if subject else None,
               subject.width if subject else None, safe["side"], safe["side"])
    y = _place(center_y, crop_height, height, subject.y if subject else None,
               subject.height if subject else None, safe["top"], safe["bottom"])
    window = Box(x, y, crop_width, crop_height) if x is not None and y is not None else None
    if crop_box is not None:
        window = validated_box(crop_box, width, height, crop=True)
        if abs(window.width / window.height - ratio) > 2 / min(window.width, window.height):
            raise ValueError("crop_box must match the target aspect within even-pixel rounding.")
        if subject and (subject.x < window.x + window.width * safe["side"]
                        or subject.x + subject.width > window.x + window.width * (1 - safe["side"])
                        or subject.y < window.y + window.height * safe["top"]
                        or subject.y + subject.height > window.y + window.height * (1 - safe["bottom"])):
            window = None
    if crop_width < 2 or crop_height < 2:
        window = None
    mode = "crop" if window else "pad_blur"
    warnings = []
    if mode == "pad_blur":
        warnings.append("Subject and safe zone cannot fit a static crop; keep the whole frame with blurred padding.")
    available = (window.width, window.height) if window else (width, height)
    if not allow_upscale:
        limit = min(1, available[0] / target[0], available[1] / target[1]) if window else min(1, min(width, height) / min(target))
        target = tuple(max(2, _even(value * limit)) for value in target)
    upscaled = bool(window and max(target[0] / window.width, target[1] / window.height) > 1 + 1e-9)
    inner_width, inner_height = target[0] * (1 - 2 * safe["side"]), target[1] * (1 - safe["top"] - safe["bottom"])
    fit = min(inner_width / width, inner_height / height, math.inf if allow_upscale else 1)
    foreground_width, foreground_height = max(2, _even(width * fit)), max(2, _even(height * fit))
    foreground = Box(_even(target[0] * safe["side"] + (inner_width - foreground_width) / 2),
                     _even(target[1] * safe["top"] + (inner_height - foreground_height) / 2),
                     foreground_width, foreground_height)
    if not window:
        upscaled = max(foreground_width / width, foreground_height / height) > 1 + 1e-9
    if upscaled:
        warnings.append(f"Video upscaled from {width}x{height} to {target[0]}x{target[1]} with no added detail. "
                        "Use the Topaz upscale skill before assembly for added detail.")
    if min(target) == 2:
        warnings.append("Tiny source requires even-pixel rounding; target aspect may be approximate.")
    return dict(mode=mode, crop_box=window.json() if window else None, width=target[0], height=target[1],
                foreground_box=foreground.json(), source_width=width, source_height=height,
                source_resolution=f"{width}x{height}", upscaled=upscaled, warnings=warnings, safe_zone=safe)


def shots_from_scenes(times, duration):
    finite(duration, "duration", .001, 600)
    if not isinstance(times, list) or len(times) >= MAX_SHOTS:
        raise ValueError("Scene times must be a list producing at most 60 shots.")
    previous = 0
    shots = []
    for cut in times:
        finite(cut, "scene time", 0, duration)
        if not previous < cut < duration:
            raise ValueError("Scene times must increase strictly inside the clip.")
        shots.append(dict(from_s=previous, to_s=cut))
        previous = cut
    return [*shots, dict(from_s=previous, to_s=duration)]
