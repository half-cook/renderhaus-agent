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
MUREKA_PURPOSES = (
    "reference",
    "melody",
    "instrumental",
    "voice",
    "audio",
    "remix",
    "soundtrack",
    "lyrics-video",
)


def _rules_for_fields(
    tool_names: tuple[str, ...], rules: dict[str, ArgumentRule]
) -> dict[str, dict[str, ArgumentRule]]:
    return {tool_name: dict(rules) for tool_name in tool_names}


TOOL_ARGUMENT_RULES: dict[str, dict[str, dict[str, ArgumentRule]]] = {
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
            "aspect_ratio": ArgumentRule(choices=("16:9", "9:16", "1:1")),
            "fps": ArgumentRule(minimum=12, maximum=60),
        }
    },
    "mureka": {
        "create_instrumental": {"n": ArgumentRule(minimum=1, maximum=3)},
        "create_song": {
            "n": ArgumentRule(minimum=1, maximum=3),
            "gender": ArgumentRule(choices=("male", "female")),
        },
        "create_song_from_prompt": {
            "n": ArgumentRule(minimum=1, maximum=3),
            "gender": ArgumentRule(choices=("male", "female")),
        },
        "extend_song": {"extend_at_ms": ArgumentRule(minimum=0)},
        "region_edit_song": {
            "edit_start_ms": ArgumentRule(minimum=0),
            "edit_end_ms": ArgumentRule(minimum=0),
        },
        "remix_song": {"n": ArgumentRule(minimum=1, maximum=3)},
        "generate_track": {
            "track_type": ArgumentRule(choices=("vocals", "accompaniment", "instrument"))
        },
        "generate_soundtrack": {
            "audio_start": ArgumentRule(minimum=0),
            "audio_end": ArgumentRule(minimum=0),
        },
        "generate_lyrics_video": {
            "aspect_ratio": ArgumentRule(choices=("16:9", "9:16", "1:1", "4:3", "3:4"))
        },
        "upload_file": {"purpose": ArgumentRule(choices=MUREKA_PURPOSES)},
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
        "start_seconds": {"type": "number", "description": "Must be at least 0."},
        "source_in_seconds": {"type": "number", "description": "Must be at least 0."},
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
    for field, rule in TOOL_ARGUMENT_RULES.get(provider_id, {}).get(tool_name, {}).items():
        schema = properties.get(field)
        if not isinstance(schema, dict):
            continue
        note = rule.description()
        existing = str(schema.get("description") or "").strip()
        if note and note not in existing:
            schema["description"] = f"{existing} {note}".strip()
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
    if rule.choices and value not in rule.choices:
        pattern_match = bool(
            rule.pattern and isinstance(value, str) and re.fullmatch(rule.pattern, value)
        )
        if not pattern_match:
            choices = ", ".join(str(choice) for choice in rule.choices)
            suffix = f" or {rule.pattern_hint.lower()}" if rule.pattern_hint else ""
            raise ValueError(f"{path} must be one of {choices}{suffix}.")
    elif rule.pattern and isinstance(value, str) and not re.fullmatch(rule.pattern, value):
        raise ValueError(f"{path} must match {rule.pattern_hint or rule.pattern}.")
    if rule.minimum is not None and float(value) < rule.minimum:
        raise ValueError(f"{path} must be at least {rule.minimum:g}.")
    if rule.maximum is not None and float(value) > rule.maximum:
        raise ValueError(f"{path} must be at most {rule.maximum:g}.")


def _require_any(arguments: dict[str, Any], fields: tuple[str, ...], tool_name: str) -> None:
    if not any(arguments.get(field) not in (None, "") for field in fields):
        raise ValueError(f"{tool_name} requires one of: {', '.join(fields)}.")


def _validate_cross_fields(provider_id: str, tool_name: str, arguments: dict[str, Any]) -> None:
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
    if provider_id != "mureka":
        return
    source_fields: dict[str, tuple[str, ...]] = {
        "extend_song": ("song_id", "upload_audio_id"),
        "region_edit_song": ("song_id", "upload_audio_id"),
        "remix_song": ("song_id", "upload_audio_id"),
        "stem_song": ("song_id", "upload_audio_id"),
        "recognize_song": ("upload_audio_id", "audio_url"),
        "describe_song": ("song_id", "upload_audio_id"),
        "transcribe_song": ("song_id", "upload_audio_id"),
        "generate_track": ("song_id", "upload_audio_id"),
        "generate_lyrics_video": ("song_id", "upload_audio_id"),
    }
    if tool_name in source_fields:
        _require_any(arguments, source_fields[tool_name], tool_name)
    if tool_name == "region_edit_song" and arguments["edit_end_ms"] <= arguments["edit_start_ms"]:
        raise ValueError("region_edit_song edit_end_ms must be greater than edit_start_ms.")
    if tool_name == "generate_soundtrack":
        start = arguments.get("audio_start")
        end = arguments.get("audio_end")
        if start is not None and end is not None and end <= start:
            raise ValueError("generate_soundtrack audio_end must be greater than audio_start.")


def validate_tool_arguments(
    provider_id: str,
    tool_name: str,
    arguments: dict[str, Any] | None,
    input_schema: dict[str, Any],
) -> dict[str, Any]:
    """Validate every Gateway call at the last boundary before provider I/O."""
    cleaned = {key: value for key, value in (arguments or {}).items() if value is not None}
    _validate_schema(cleaned, input_schema, "arguments")
    for field, rule in TOOL_ARGUMENT_RULES.get(provider_id, {}).get(tool_name, {}).items():
        if field in cleaned:
            _validate_rule(f"arguments.{field}", cleaned[field], rule)
    _validate_cross_fields(provider_id, tool_name, cleaned)
    return cleaned
