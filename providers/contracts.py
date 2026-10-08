"""Central argument contracts shared by Gateway schemas and provider dispatch.

AgentCore's Lambda target schema dialect is intentionally small and does not preserve every JSON
Schema keyword. These contracts therefore serve two purposes: describe stable provider choices to
the model, and enforce the same rules immediately before the paid provider request.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from providers.runway.contracts import I2V_RATIOS, IMAGE_RATIOS, T2V_RATIOS


@dataclass(frozen=True, slots=True)
class ArgumentRule:
    choices: tuple[Any, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    pattern: str | None = None
    pattern_hint: str | None = None

    def description(self) -> str:
        parts: list[str] = []
        if self.choices:
            parts.append("Allowed values: " + ", ".join(str(value) for value in self.choices) + ".")
        if self.minimum is not None and self.maximum is not None:
            parts.append(f"Allowed range: {self.minimum:g} to {self.maximum:g}.")
        elif self.minimum is not None:
            parts.append(f"Must be at least {self.minimum:g}.")
        elif self.maximum is not None:
            parts.append(f"Must be at most {self.maximum:g}.")
        if self.pattern_hint:
            parts.append(self.pattern_hint.rstrip(".") + ".")
        return " ".join(parts)


SEEDANCE_RATIOS = ("adaptive", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9")
SEEDANCE_RESOLUTIONS = ("480p", "720p", "1080p")
SEEDREAM_RATIOS = ("1:1", "16:9", "9:16")
SEEDREAM_SIZES = ("1K", "2K", "3K")


def _rules_for_fields(
    tool_names: tuple[str, ...], rules: dict[str, ArgumentRule]
) -> dict[str, dict[str, ArgumentRule]]:
    return {tool_name: dict(rules) for tool_name in tool_names}


TOOL_ARGUMENT_RULES: dict[str, dict[str, dict[str, ArgumentRule]]] = {
    "kling": {
        **_rules_for_fields(
            ("text_to_video", "image_to_video"),
            {
                "duration_seconds": ArgumentRule(minimum=3, maximum=15),
                "aspect_ratio": ArgumentRule(choices=("16:9", "9:16", "1:1")),
                "resolution": ArgumentRule(choices=("720p", "1080p", "4k")),
                "model": ArgumentRule(choices=("kling-3.0", "kling-3.0-turbo")),
            },
        ),
        "omni_video": {
            "duration_seconds": ArgumentRule(minimum=3, maximum=15),
            "aspect_ratio": ArgumentRule(choices=("16:9", "9:16", "1:1")),
            "resolution": ArgumentRule(choices=("720p", "1080p", "4k")),
        },
    },
    "runway": {
        "text_to_video": {
            "model": ArgumentRule(choices=("gen4.5",)),
            "duration_seconds": ArgumentRule(minimum=2, maximum=10),
            "ratio": ArgumentRule(choices=T2V_RATIOS),
            "seed": ArgumentRule(minimum=0, maximum=4294967295),
        },
        "image_to_video": {
            "model": ArgumentRule(choices=("gen4.5",)),
            "duration_seconds": ArgumentRule(minimum=2, maximum=10),
            "ratio": ArgumentRule(choices=I2V_RATIOS),
            "seed": ArgumentRule(minimum=0, maximum=4294967295),
        },
        "video_to_video": {
            "model": ArgumentRule(choices=("aleph2",)),
            "video_duration_seconds": ArgumentRule(minimum=2, maximum=30),
            "reference_seconds": ArgumentRule(minimum=0, maximum=30),
            "seed": ArgumentRule(minimum=0, maximum=4294967295),
        },
        "text_to_image": {
            "model": ArgumentRule(choices=("gen4_image",)),
            "ratio": ArgumentRule(choices=IMAGE_RATIOS),
            "seed": ArgumentRule(minimum=0, maximum=4294967295),
        },
        "image_to_image": {
            "model": ArgumentRule(choices=("gen4_image", "gen4_image_turbo")),
            "ratio": ArgumentRule(choices=IMAGE_RATIOS),
            "seed": ArgumentRule(minimum=0, maximum=4294967295),
        },
    },
    "seedance": {
        **_rules_for_fields(
            ("text_to_video", "image_to_video"),
            {
                "duration_seconds": ArgumentRule(minimum=4, maximum=12),
                "aspect_ratio": ArgumentRule(choices=SEEDANCE_RATIOS),
                "resolution": ArgumentRule(choices=SEEDANCE_RESOLUTIONS),
                "service_tier": ArgumentRule(choices=("default", "flex")),
            },
        ),
    },
    "seedream": {
        **_rules_for_fields(
            ("text_to_image", "image_to_image"),
            {
                "aspect_ratio": ArgumentRule(choices=SEEDREAM_RATIOS),
                "size": ArgumentRule(
                    choices=SEEDREAM_SIZES,
                    pattern=r"^[1-9]\d{2,3}x[1-9]\d{2,3}$",
                    pattern_hint="Or use explicit WIDTHxHEIGHT dimensions",
                ),
                "response_format": ArgumentRule(choices=("url", "b64_json")),
            },
        ),
    },
    "remotion": {
        "render_timeline": {
            "aspect_ratio": ArgumentRule(choices=("16:9", "9:16", "1:1", "2.39:1")),
            "fps": ArgumentRule(minimum=12, maximum=60),
        }
    },
}


_VISUAL_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "description": "Allowed values: image, video."},
        "url": {
            "type": "string",
            "description": "HTTPS media URL or renderhaus-asset:// version handle.",
        },
        "duration_seconds": {"type": "number", "description": "Must be greater than 0."},
        "start_seconds": {"type": "number", "description": "Must be at least 0."},
        "source_in_seconds": {"type": "number", "description": "Must be at least 0."},
        "track": {"type": "integer", "description": "Allowed range: 0 to 8."},
        "transition": {
            "type": "string",
            "description": "Allowed values: cut, fade, dip_to_black.",
        },
        "fit": {"type": "string", "description": "Allowed values: cover, contain."},
        "position_x": {"type": "number", "description": "Allowed range: 0 to 1."},
        "position_y": {"type": "number", "description": "Allowed range: 0 to 1."},
        "scale": {"type": "number", "description": "Allowed range: 0.1 to 4."},
        "opacity": {"type": "number", "description": "Allowed range: 0 to 1."},
        "rotation_degrees": {
            "type": "number",
            "description": "Allowed range: -360 to 360.",
        },
        "playback_rate": {"type": "number", "description": "Allowed range: 0.25 to 4."},
        "volume": {"type": "number", "description": "Source video audio volume. Allowed range: 0 to 1. Use 0 when replacing the soundtrack."},
        "fade_in_seconds": {"type": "number", "description": "Must be at least 0."},
        "fade_out_seconds": {"type": "number", "description": "Must be at least 0."},
        "motion": {
            "type": "string",
            "description": "Allowed values: none, zoom_in, zoom_out, pan_left, pan_right.",
        },
    },
    "required": ["kind", "url", "duration_seconds"],
}
_AUDIO_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "HTTPS media URL or renderhaus-asset:// version handle.",
        },
        "duration_seconds": {"type": "number", "description": "Must be greater than 0."},
        "start_seconds": {"type": "number", "description": "Position in the final video where this audio begins (0 starts immediately). Must be at least 0."},
        "source_in_seconds": {"type": "number", "description": "Seconds to skip inside the source music, independent of its position in the video. Must be at least 0."},
        "volume": {"type": "number", "description": "Allowed range: 0 to 1."},
        "fade_in_seconds": {"type": "number", "description": "Must be at least 0."},
        "fade_out_seconds": {"type": "number", "description": "Must be at least 0."},
    },
    "required": ["url", "duration_seconds"],
}
_TEXT_OVERLAY_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "start_seconds": {"type": "number", "description": "Must be at least 0."},
        "duration_seconds": {"type": "number", "description": "Must be greater than 0."},
        "position": {
            "type": "string",
            "description": "Allowed values: top, center, bottom.",
        },
        "font_size": {"type": "integer", "description": "Allowed range: 16 to 180."},
        "font_weight": {"type": "integer", "description": "Allowed range: 100 to 900."},
        "color": {"type": "string", "description": "CSS color."},
        "background_color": {"type": "string", "description": "CSS color or transparent."},
        "fade_in_seconds": {"type": "number", "description": "Must be at least 0."},
        "fade_out_seconds": {"type": "number", "description": "Must be at least 0."},
    },
    "required": ["text", "start_seconds", "duration_seconds"],
}


def enrich_tool_schema(provider_id: str, tool: dict[str, Any]) -> dict[str, Any]:
    """Add provider choices and nested contracts without unsupported schema keywords."""
    enriched = deepcopy(tool)
    tool_name = str(enriched.get("name") or "")
    properties = (enriched.get("inputSchema") or {}).get("properties") or {}
    for field, rule in argument_rules(provider_id, tool_name).items():
        schema = properties.get(field)
        if not isinstance(schema, dict):
            continue
        note = rule.description()
        existing = str(schema.get("description") or "").strip()
        if note and note not in existing:
            schema["description"] = f"{existing} {note}".strip()
    if provider_id == "runway" and "reference_images" in properties:
        properties["reference_images"]["items"] = {
            "type": "object",
            "properties": {
                "uri": {"type": "string", "description": "HTTPS domain URL, runway upload URI, or base64 image data URI up to 5 MB."},
                "tag": {"type": "string", "description": "Optional reference name, 3-16 lowercase letters, digits, or underscores, starting with a letter."},
            },
            "required": ["uri"],
        }
        properties["reference_images"]["description"] = "Up to two additional references, for at most three images including image_path_or_url."
    if provider_id == "remotion" and tool_name == "render_timeline":
        if isinstance(properties.get("visuals"), dict):
            properties["visuals"]["items"] = deepcopy(_VISUAL_ITEM_SCHEMA)
            properties["visuals"]["description"] = "Ordered visual clips in the final timeline."
        if isinstance(properties.get("audio_tracks"), dict):
            properties["audio_tracks"]["items"] = deepcopy(_AUDIO_ITEM_SCHEMA)
            properties["audio_tracks"]["description"] = (
                "Optional music, ambience, and voice tracks."
            )
        if isinstance(properties.get("text_overlays"), dict):
            properties["text_overlays"]["items"] = deepcopy(_TEXT_OVERLAY_SCHEMA)
            properties["text_overlays"]["description"] = "Optional titles and captions."
    return enriched


def _matches_type(value: Any, json_type: str) -> bool:
    if json_type == "boolean":
        return isinstance(value, bool)
    if json_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if json_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if json_type == "string":
        return isinstance(value, str)
    if json_type == "array":
        return isinstance(value, list)
    if json_type == "object":
        return isinstance(value, dict)
    return True


def _validate_schema(value: Any, schema: dict[str, Any], path: str) -> None:
    json_type = str(schema.get("type") or "")
    if json_type and not _matches_type(value, json_type):
        raise ValueError(f"{path} must be {json_type}.")
    if json_type == "object" and isinstance(value, dict):
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        unknown = sorted(set(value) - set(properties))
        if unknown:
            raise ValueError(f"{path} contains unsupported fields: {', '.join(unknown)}.")
        missing = [name for name in required if name not in value or value[name] in (None, "")]
        if missing:
            raise ValueError(f"{path} is missing required fields: {', '.join(missing)}.")
        for name, item in value.items():
            child = properties.get(name)
            if isinstance(child, dict):
                _validate_schema(item, child, f"{path}.{name}")
    elif json_type == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_schema(item, item_schema, f"{path}[{index}]")


def _validate_rule(path: str, value: Any, rule: ArgumentRule) -> None:
    if rule.choices:
        if value not in rule.choices:
            pattern_match = bool(
                rule.pattern and isinstance(value, str) and re.fullmatch(rule.pattern, value)
            )
            if not pattern_match:
                choices = ", ".join(str(choice) for choice in rule.choices)
                suffix = f"; {rule.pattern_hint}" if rule.pattern_hint else ""
                raise ValueError(f"{path} must be one of {choices}{suffix}.")
    elif rule.pattern and isinstance(value, str) and not re.fullmatch(rule.pattern, value):
        raise ValueError(f"{path} must match {rule.pattern_hint or rule.pattern}.")
    if rule.minimum is not None and float(value) < rule.minimum:
        raise ValueError(f"{path} must be at least {rule.minimum:g}.")
    if rule.maximum is not None and float(value) > rule.maximum:
        raise ValueError(f"{path} must be at most {rule.maximum:g}.")


def _validate_cross_fields(provider_id: str, tool_name: str, arguments: dict[str, Any]) -> None:
    if provider_id == "runway":
        from providers.runway.contracts import validate_runway_arguments

        validate_runway_arguments(tool_name, arguments)
    if provider_id == "fal":
        from providers.fal.wan import validate_arguments

        validate_arguments(tool_name, arguments)
    if provider_id == "remotion" and tool_name == "render_timeline":
        if not arguments.get("visuals"):
            raise ValueError("render_timeline requires at least one visual clip.")
        for index, clip in enumerate(arguments.get("visuals") or []):
            if clip["kind"] not in {"image", "video"}:
                raise ValueError(f"arguments.visuals[{index}].kind must be image or video.")
            if float(clip["duration_seconds"]) <= 0:
                raise ValueError(
                    f"arguments.visuals[{index}].duration_seconds must be greater than 0."
                )
            for field in ("start_seconds", "source_in_seconds"):
                if field in clip and float(clip[field]) < 0:
                    raise ValueError(f"arguments.visuals[{index}].{field} must be at least 0.")
            choices = {
                "transition": {"cut", "fade", "dip_to_black"},
                "fit": {"cover", "contain"},
                "motion": {"none", "zoom_in", "zoom_out", "pan_left", "pan_right"},
            }
            for field, allowed in choices.items():
                if field in clip and clip[field] not in allowed:
                    raise ValueError(
                        f"arguments.visuals[{index}].{field} must be one of "
                        f"{', '.join(sorted(allowed))}."
                    )
            ranges = {
                "track": (0, 8),
                "position_x": (0, 1),
                "position_y": (0, 1),
                "scale": (0.1, 4),
                "opacity": (0, 1),
                "rotation_degrees": (-360, 360),
                "playback_rate": (0.25, 4),
                "volume": (0, 1),
            }
            for field, (minimum, maximum) in ranges.items():
                if field in clip and not minimum <= float(clip[field]) <= maximum:
                    raise ValueError(
                        f"arguments.visuals[{index}].{field} must be between "
                        f"{minimum:g} and {maximum:g}."
                    )
            for field in ("fade_in_seconds", "fade_out_seconds"):
                if field in clip and not 0 <= float(clip[field]) <= float(clip["duration_seconds"]):
                    raise ValueError(
                        f"arguments.visuals[{index}].{field} must fit inside the clip duration."
                    )
        for index, clip in enumerate(arguments.get("audio_tracks") or []):
            if float(clip["duration_seconds"]) <= 0:
                raise ValueError(
                    f"arguments.audio_tracks[{index}].duration_seconds must be greater than 0."
                )
            for field in ("start_seconds", "source_in_seconds"):
                if field in clip and float(clip[field]) < 0:
                    raise ValueError(f"arguments.audio_tracks[{index}].{field} must be at least 0.")
            if "volume" in clip and not 0 <= float(clip["volume"]) <= 1:
                raise ValueError(f"arguments.audio_tracks[{index}].volume must be between 0 and 1.")
            for field in ("fade_in_seconds", "fade_out_seconds"):
                if field in clip and not 0 <= float(clip[field]) <= float(clip["duration_seconds"]):
                    raise ValueError(
                        f"arguments.audio_tracks[{index}].{field} must fit inside the clip duration."
                    )
        for index, overlay in enumerate(arguments.get("text_overlays") or []):
            if float(overlay["start_seconds"]) < 0:
                raise ValueError(
                    f"arguments.text_overlays[{index}].start_seconds must be at least 0."
                )
            if float(overlay["duration_seconds"]) <= 0:
                raise ValueError(
                    f"arguments.text_overlays[{index}].duration_seconds must be greater than 0."
                )
            if "position" in overlay and overlay["position"] not in {"top", "center", "bottom"}:
                raise ValueError(
                    f"arguments.text_overlays[{index}].position must be top, center, or bottom."
                )


def validate_tool_arguments(
    provider_id: str,
    tool_name: str,
    arguments: dict[str, Any] | None,
    input_schema: dict[str, Any],
) -> dict[str, Any]:
    """Validate every Gateway call at the last boundary before provider I/O."""
    cleaned = {key: value for key, value in (arguments or {}).items() if value is not None}
    _validate_schema(cleaned, input_schema, "arguments")
    for field, rule in argument_rules(provider_id, tool_name).items():
        if field in cleaned:
            _validate_rule(f"arguments.{field}", cleaned[field], rule)
    _validate_cross_fields(provider_id, tool_name, cleaned)
    return cleaned


def argument_rules(provider_id: str, tool_name: str) -> dict[str, ArgumentRule]:
    if provider_id == "fal":
        from providers.fal.wan import ARGUMENT_RULES

        return ARGUMENT_RULES.get(tool_name, {})
    return TOOL_ARGUMENT_RULES.get(provider_id, {}).get(tool_name, {})
