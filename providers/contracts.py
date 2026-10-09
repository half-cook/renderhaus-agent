"""Central argument contracts shared by Gateway schemas and provider dispatch.

AgentCore's Lambda target schema dialect is intentionally small and does not preserve every JSON
Schema keyword. These contracts therefore serve two purposes: describe stable provider choices to
the model, and enforce the same rules immediately before the paid provider request.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from providers.runway.contracts import I2V_RATIOS, IMAGE_RATIOS, T2V_RATIOS
from providers.luma.catalog import (
    ASPECT_RATIOS as LUMA_RATIOS,
    DURATIONS as LUMA_DURATIONS,
    EDIT_STRENGTHS as LUMA_EDIT_STRENGTHS,
    EXTEND_RESOLUTIONS as LUMA_EXTEND_RESOLUTIONS,
    MODEL_IDS as LUMA_MODELS,
    RESOLUTIONS as LUMA_RESOLUTIONS,
)


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


SEEDREAM_RATIOS = ("1:1", "16:9", "9:16")
SEEDREAM_SIZES = ("1K", "2K", "3K")


def _rules_for_fields(
    tool_names: tuple[str, ...], rules: dict[str, ArgumentRule]
) -> dict[str, dict[str, ArgumentRule]]:
    return {tool_name: dict(rules) for tool_name in tool_names}


LUMA_VIDEO_ARGUMENT_RULES = {
    "model": ArgumentRule(choices=LUMA_MODELS),
    "aspect_ratio": ArgumentRule(choices=LUMA_RATIOS),
    "resolution": ArgumentRule(choices=LUMA_RESOLUTIONS),
    "prompt": ArgumentRule(
        pattern=r"[\s\S]{1,6000}", pattern_hint="Must contain 1 to 6000 characters"
    ),
}


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
        "act_two": {
            "performance_duration_seconds": ArgumentRule(minimum=3, maximum=30),
            "ratio": ArgumentRule(choices=I2V_RATIOS),
            "expression_intensity": ArgumentRule(minimum=1, maximum=5),
            "seed": ArgumentRule(minimum=0, maximum=4294967295),
            "performance_start_seconds": ArgumentRule(minimum=0),
            "source_duration_seconds": ArgumentRule(minimum=3),
            "body_control": ArgumentRule(pattern_hint="Gesture transfer requires a character image; false is required for character video"),
        },
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
    "luma": {
        "text_to_video": {
            **LUMA_VIDEO_ARGUMENT_RULES,
            "duration_seconds": ArgumentRule(choices=LUMA_DURATIONS),
        },
        "image_to_video": {
            **LUMA_VIDEO_ARGUMENT_RULES,
            "duration_seconds": ArgumentRule(choices=(5,)),
        },
        "extend_video": {
            "model": ArgumentRule(choices=LUMA_MODELS),
            "resolution": ArgumentRule(choices=LUMA_EXTEND_RESOLUTIONS),
            "direction": ArgumentRule(choices=("forward", "backward")),
            "generation_id": ArgumentRule(pattern=r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}", pattern_hint="Must be a generation UUID"),
            "prompt": ArgumentRule(pattern=r"[\s\S]{1,6000}", pattern_hint="Must contain 1 to 6000 characters"),
        },
        "modify_video": {
            "model": ArgumentRule(choices=LUMA_MODELS),
            "resolution": ArgumentRule(choices=LUMA_RESOLUTIONS),
            "source_duration_seconds": ArgumentRule(choices=LUMA_DURATIONS),
            "strength": ArgumentRule(choices=LUMA_EDIT_STRENGTHS),
            "source_generation_id": ArgumentRule(pattern=r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}", pattern_hint="Must be a generation UUID"),
            "prompt": ArgumentRule(pattern=r"[\s\S]{1,6000}", pattern_hint="Must contain 1 to 6000 characters"),
        },
        "get_video_task": {
            "job_id": ArgumentRule(pattern=r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}", pattern_hint="Must be a generation UUID"),
        },
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
        "import_nle_timeline": {"format": ArgumentRule(choices=("fcpxml", "otio"))},
        "render_timeline": {
            "aspect_ratio": ArgumentRule(choices=("16:9", "9:16", "1:1", "4:5", "2.39:1")),
            "fps": ArgumentRule(minimum=12, maximum=60),
            "video_bitrate": ArgumentRule(minimum=1),
        },
        "prepare_conversational_edit": {
            "aspect_ratio": ArgumentRule(choices=("16:9", "9:16", "1:1", "4:5", "2.39:1")),
            "fps": ArgumentRule(minimum=12, maximum=60),
            "grade": ArgumentRule(choices=("none", "neutral", "warm")),
        },
    },
}


_BOX_SCHEMA = {
    "type": "object",
    "properties": {name: {"type": "number"} for name in ("x", "y", "width", "height")},
    "required": ["x", "y", "width", "height"],
    "description": "Canvas pixel box. x/y nonnegative, width/height positive and at most 7680; must fit canvas.",
}


_VISUAL_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "description": "Allowed values: image, video."},
        "url": {
            "type": "string",
            "description": "HTTPS media URL, renderhaus-asset:// version handle, or local media path (no file://).",
        },
        "output_path": {"type": "string", "description": "Existing local media path returned by a provider, under RENDERHAUS_MEDIA_DIR; no file:// prefix. Use instead of url."},
        "duration_seconds": {"type": "number", "description": "Must be greater than 0."},
        "source_fps": {"type": "number", "description": "Optional measured source video frame rate. Local files and trusted HTTPS video hosts are measured automatically before rendering."},
        "source_bitrate": {"type": "integer", "description": "Optional measured source bitrate in bits per second. Local files and trusted HTTPS video hosts are measured automatically; unknown stream bitrate uses the conservative container bitrate."},
        "start_seconds": {"type": "number", "description": "Must be at least 0."},
        "source_in_seconds": {"type": "number", "description": "Must be at least 0."},
        "track": {"type": "integer", "description": "Allowed range: 0 to 8."},
        "transition": {
            "type": "string",
            "description": "Allowed values: cut, fade, dip_to_black.",
        },
        "fit": {"type": "string", "description": "Allowed values: cover, contain, pad_blur. Reframing is local/worker only; Lambda refuses pad_blur."},
        "position_x": {"type": "number", "description": "Allowed range: 0 to 1."},
        "position_y": {"type": "number", "description": "Allowed range: 0 to 1."},
        "scale": {"type": "number", "description": "Allowed range: 0.1 to 4."},
        "box": _BOX_SCHEMA,
        "pad_box": {**_BOX_SCHEMA, "description": "Foreground canvas box from a safe-zone crop plan. Requires fit=pad_blur; local/worker only."},
        "crop_box": {
            "type": "object", "required": ["x", "y", "width", "height"],
            "properties": {key: {"type": "integer"} for key in ("x", "y", "width", "height")},
            "description": "Static even-pixel crop in display-oriented source coordinates. Local/worker only; must fit the measured source.",
        },
        "reframe_size": {
            "type": "object", "required": ["width", "height"],
            "properties": {key: {"type": "integer"} for key in ("width", "height")},
            "description": "Validated crop-plan canvas in even pixels, 2..7680. Requires crop_box or pad_blur. Primary clips must agree.",
        },
        "allow_upscale": {"type": "boolean", "description": "Explicit permission to resample a reframe beyond available source pixels; reports no added detail. Default false."},
        "opacity": {"type": "number", "description": "Allowed range: 0 to 1."},
        "rotation_degrees": {
            "type": "number",
            "description": "Allowed range: -360 to 360.",
        },
        "playback_rate": {"type": "number", "description": "Allowed range: 0.25 to 4."},
        "volume": {"type": "number", "description": "Source video audio volume. Allowed range: 0 to 1. Use 0 when replacing the soundtrack."},
        "fade_in_seconds": {"type": "number", "description": "Must be at least 0."},
        "fade_out_seconds": {"type": "number", "description": "Must be at least 0."},
        "audio_fade_in_seconds": {"type": "number", "description": "Audio-only fade, independent of opacity. Must fit inside the clip duration."},
        "audio_fade_out_seconds": {"type": "number", "description": "Audio-only fade, independent of opacity. Must fit inside the clip duration."},
        "grade": {"type": "string", "description": "Media-only fixed color filter. Allowed values: none, neutral, warm."},
        "motion": {
            "type": "string",
            "description": "Allowed values: none, zoom_in, zoom_out, pan_left, pan_right.",
        },
    },
    "required": ["kind", "duration_seconds"],
}
_AUDIO_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "HTTPS media URL, renderhaus-asset:// version handle, or local media path (no file://).",
        },
        "output_path": {"type": "string", "description": "Existing local media path returned by a provider, under RENDERHAUS_MEDIA_DIR; no file:// prefix. Use instead of url."},
        "duration_seconds": {"type": "number", "description": "Must be greater than 0."},
        "start_seconds": {"type": "number", "description": "Position in the final video where this audio begins (0 starts immediately). Must be at least 0."},
        "source_in_seconds": {"type": "number", "description": "Seconds to skip inside the source music, independent of its position in the video. Must be at least 0."},
        "volume": {"type": "number", "description": "Allowed range: 0 to 1."},
        "fade_in_seconds": {"type": "number", "description": "Must be at least 0."},
        "fade_out_seconds": {"type": "number", "description": "Must be at least 0."},
    },
    "required": ["duration_seconds"],
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
        "box": _BOX_SCHEMA,
        "min_font_size": {"type": "integer", "description": "Allowed range: 16 to 180."},
        "max_font_size": {"type": "integer", "description": "Allowed range: 16 to 180."},
        "font_family": {"type": "string", "description": "Allowed values: dejavu-sans, dejavu-sans-bold."},
        "opacity": {"type": "number", "description": "Allowed range: 0 to 1."},
        "color": {"type": "string", "description": "CSS color."},
        "background_color": {"type": "string", "description": "CSS color or transparent."},
        "fade_in_seconds": {"type": "number", "description": "Must be at least 0."},
        "fade_out_seconds": {"type": "number", "description": "Must be at least 0."},
    },
    "required": ["text", "start_seconds", "duration_seconds"],
}
_TRANSCRIPT_WORD_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "start": {"type": "number", "description": "Finite source start in seconds, at least 0."},
        "end": {"type": "number", "description": "Finite source end in seconds. Words require end greater than start."},
        "type": {"type": "string", "description": "Allowed values: word, spacing, silence, audio_event. Defaults to word."},
    },
    "required": ["text", "start", "end"],
}
_TRANSCRIPT_SOURCE_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Unique immutable source identifier."},
        "url": {"type": "string", "description": "Existing media URL, local source, or renderhaus-asset:// version handle. Preparation never fetches media."},
        "duration_seconds": {"type": "number", "description": "Finite whole-source duration, greater than 0."},
        "words": {"type": "array", "items": _TRANSCRIPT_WORD_SCHEMA,
                  "description": "Ordered source transcript tokens. Timing must not overlap or extend past the source."},
        "metadata": {"type": "object", "description": "Optional original source metadata. It is not copied to the new output."},
    },
    "required": ["id", "url", "duration_seconds", "words"],
}
_TRANSCRIPT_SEGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "source_id": {"type": "string"},
        "first_word": {"type": "integer", "description": "Inclusive zero-based index into type=word tokens, with missing type treated as word."},
        "last_word": {"type": "integer", "description": "Inclusive zero-based index into type=word tokens."},
        "padding_seconds": {"type": "number", "description": "Desired boundary padding, 0.03 to 0.2 seconds. Defaults to 0.05. Snaps within safe frame boundaries."},
    },
    "required": ["source_id", "first_word", "last_word"],
}


def enrich_tool_schema(provider_id: str, tool: dict[str, Any]) -> dict[str, Any]:
    """Add provider choices and nested contracts without unsupported schema keywords."""
    enriched = deepcopy(tool)
    tool_name = str(enriched.get("name") or "")
    properties = (enriched.get("inputSchema") or {}).get("properties") or {}
    if provider_id == "gemini":
        from providers.gemini.contracts import FIELD_DESCRIPTIONS

        for name, description in FIELD_DESCRIPTIONS.items():
            if name in properties:
                properties[name]["description"] = description
    if provider_id == "mureka":
        from providers.mureka.contracts import FIELD_DESCRIPTIONS

        for field, description in FIELD_DESCRIPTIONS.items():
            if field in properties:
                properties[field]["description"] = description
    if provider_id == "topaz":
        from providers.topaz.contracts import FIELD_DESCRIPTIONS

        for field, description in FIELD_DESCRIPTIONS.items():
            if field in properties:
                properties[field]["description"] = description
    if provider_id == "sync":
        from providers.sync.contracts import FIELD_DESCRIPTIONS

        for field, description in FIELD_DESCRIPTIONS.items():
            if field in properties:
                properties[field]["description"] = description
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
        if isinstance(properties.get("output_resolution"), dict):
            properties["output_resolution"]["description"] = (
                "One of: source, 720p, 1080p, 1440p, 2160p. "
                "Default source uses the largest measured video short edge, capped at the aspect table. "
                "Explicit tiers scale that table relative to 1080p; 2.39:1 at 1080p stays 1920x804. "
                "Upscaling adds no detail; use the Topaz upscale skill before assembly for added detail."
            )
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
            properties["text_overlays"]["description"] = "Optional titles and graphics, rendered before subtitles."
        if isinstance(properties.get("subtitles"), dict):
            properties["subtitles"]["items"] = deepcopy(_TEXT_OVERLAY_SCHEMA)
            properties["subtitles"]["description"] = "Output-timed burn-in captions, rendered as the final track above all overlays."
    if provider_id == "remotion" and tool_name == "render_ad_variants":
        required = ("variant_key", "sku", "price_text", "cta_text", "logo_asset", "legal_text", "locale", "aspect")
        properties["rows"]["items"] = {
            "type": "object", "properties": {
                **{field: {"type": "string"} for field in required},
                "product_asset": {"type": "string"}, "vo_asset": {"type": "string"},
                "start_s": {"type": "number"}, "end_s": {"type": "number"}},
            "required": list(required),
        }
        properties["stage"]["description"] = "Allowed values: plan, render_first, render_batch. Plan is free. First and batch always need human approval, including autonomous runs."
        properties["rows"]["description"] = "1-100 rows. Nonempty required strings; verbatim price/CTA/legal. Unique sku/locale/aspect and variant_key. Assets confined to job directory."
        properties["brief"]["description"] = "campaign ASCII identifier; optional logo_alpha_required (default true), legal_locales, legal_by_locale, fps, source_width/source_height, output_resolution source or 720p/1080p/1440p/2160p, fit cover/contain. No custom shell or template code."
        properties["plan_hash"]["description"] = "Exact immutable SHA-256 returned by plan. Required for render stages; changes to copy/media invalidate approval. Approval is trusted host context, never an argument."
        properties["concurrency"]["description"] = "Integer 1-2 local renders. A failed variant does not stop the others."
    if provider_id == "remotion" and tool_name == "prepare_conversational_edit":
        properties["plan_summary"]["description"] = "Plain English cut, grade, and caption proposal shown in the required host approval card."
        properties["sources"]["items"] = deepcopy(_TRANSCRIPT_SOURCE_SCHEMA)
        properties["segments"]["items"] = deepcopy(_TRANSCRIPT_SEGMENT_SCHEMA)
        properties["segments"]["description"] = "Ordered kept ranges using inclusive indices into each source's filtered type=word tokens. Split ranges to discard fillers or silence. No arbitrary time cuts."
        properties["overlays"]["items"] = deepcopy(_TEXT_OVERLAY_SCHEMA)
        properties["overlays"]["description"] = "Optional output-timed titles and graphics, below subtitles."
    if provider_id == "remotion" and tool_name == "export_nle_timeline":
        properties["timeline_json"]["description"] = (
            "JSON Remotion envelope with document {id, name, assets, tracks} and renderConfig "
            "{fps, width, height, durationInFrames, timecode, dropFrame}. Every referenced asset "
            "requires id, kind, url, versionId, checksum (SHA-256), durationSec (whole source), "
            "sourceTimecode, reelName, non-empty provenance object, and generated boolean. "
            "Video assets also require explicit hasAudio boolean; audio media has audio. "
            "Tracks use the existing Remotion items with assetId, start, duration, sourceIn. "
            "Use exact rational fps 30000/1001 for 29.97 and dropFrame=true for DF timecodes. "
            "Export supports cuts and gaps; bake titles, effects, fades, and retimes first. "
            "Source media must be under Renderhaus media roots or on a configured S3 bucket host."
        )
        properties["output_filename"]["description"] = "ZIP download filename; directory components are removed."
    if provider_id == "remotion" and tool_name == "import_nle_timeline":
        properties["interchange_text"]["description"] = "FCPXML 1.9–1.11 text or OTIO JSON, up to 2 MiB. Media URLs are never opened."
        properties["timeline_json"]["description"] = "Current project document/renderConfig JSON envelope with existing assets (id, kind, url, durationSec) and tracks. Preserve versionId, checksum and sourceTimecode when known."
        properties["format"]["description"] = "Interchange format. Allowed values: fcpxml, otio. EDL, AAF and FCP7 XML are unsupported."
    if provider_id == "fal":
        from providers.fal import vidu, wan3, motion, mirelo, images

        for contract in (vidu, wan3, motion, mirelo, images):
            if tool_name in contract.TOOL_ENDPOINTS:
                for field, description in contract.FIELD_DESCRIPTIONS.items():
                    if field in properties:
                        properties[field]["description"] = description
        if tool_name == "recraft_text_to_vector":
            rgb = {"type": "object", "properties": {
                channel: {"type": "integer", "description": "Integer 0-255."} for channel in ("r", "g", "b")
            }, "required": ["r", "g", "b"]}
            properties["colors"]["items"] = deepcopy(rgb)
            properties["background_color"].update(deepcopy(rgb))
    if provider_id == "openai_images":
        from providers.openai_images.contracts import FIELD_DESCRIPTIONS

        for field, description in FIELD_DESCRIPTIONS.items():
            if field in properties:
                properties[field]["description"] = description
    if provider_id == "seedance":
        from providers.seedance import contracts

        for field, description in contracts.FIELD_DESCRIPTIONS.items():
            if field in properties:
                properties[field]["description"] = description
    if provider_id == "alibaba_modelstudio":
        from providers.alibaba_modelstudio import contracts

        for field, description in contracts.FIELD_DESCRIPTIONS.items():
            if field in properties:
                properties[field]["description"] = description
    if provider_id == "heygen":
        from providers.heygen.contracts import FIELD_DESCRIPTIONS

        for field, description in FIELD_DESCRIPTIONS.items():
            if field in properties:
                properties[field]["description"] = description
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


def _validate_schema(
    value: Any, schema: dict[str, Any], path: str, *, allow_empty_strings: bool = False
) -> None:
    json_type = str(schema.get("type") or "")
    if json_type and not _matches_type(value, json_type):
        raise ValueError(f"{path} must be {json_type}.")
    if json_type in {"number", "integer"} and not math.isfinite(value):
        raise ValueError(f"{path} must be finite.")
    if json_type == "object" and isinstance(value, dict):
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        unknown = sorted(set(value) - set(properties)) if "properties" in schema else []
        if unknown:
            raise ValueError(f"{path} contains unsupported fields: {', '.join(unknown)}.")
        missing = [name for name in required if name not in value or value[name] is None
                   or (value[name] == "" and not allow_empty_strings)]
        if missing:
            raise ValueError(f"{path} is missing required fields: {', '.join(missing)}.")
        for name, item in value.items():
            child = properties.get(name)
            if isinstance(child, dict):
                _validate_schema(item, child, f"{path}.{name}", allow_empty_strings=allow_empty_strings)
    elif json_type == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_schema(item, item_schema, f"{path}[{index}]", allow_empty_strings=allow_empty_strings)


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
    if provider_id == "ffmpeg":
        from providers.ffmpeg.api import validate_arguments

        validate_arguments(arguments)
    if provider_id == "remotion" and tool_name == "render_ad_variants":
        from providers.remotion.ad_variants import validate_arguments

        validate_arguments(arguments)
    if provider_id == "gemini":
        from providers.gemini.contracts import validate_arguments

        validate_arguments(tool_name, arguments)
    if provider_id == "mureka":
        from providers.mureka.contracts import validate_arguments

        validate_arguments(tool_name, arguments)
        return
    if provider_id == "topaz":
        from providers.topaz.contracts import validate_arguments

        validate_arguments(tool_name, arguments)
    if provider_id == "heygen":
        from providers.heygen.contracts import validate_arguments

        validate_arguments(tool_name, arguments)
    if provider_id == "sync":
        from providers.sync.contracts import validate_arguments

        validate_arguments(tool_name, arguments)
    if provider_id == "openai_images":
        from providers.openai_images.contracts import request_for

        request_for(tool_name, arguments)
    if provider_id == "seedance":
        from providers.seedance.contracts import validate_arguments

        validate_arguments(tool_name, arguments)
    if provider_id == "alibaba_modelstudio":
        from providers.alibaba_modelstudio.contracts import validate_arguments

        validate_arguments(tool_name, arguments)
    if provider_id == "runway":
        from providers.runway.contracts import validate_runway_arguments

        validate_runway_arguments(tool_name, arguments)
    if provider_id == "fal":
        from providers.fal import vidu, wan, wan3, motion, mirelo, images

        images.validate_arguments(tool_name, arguments)
        mirelo.validate_arguments(tool_name, arguments)
        motion.validate_arguments(tool_name, arguments)
        wan3.validate_arguments(tool_name, arguments)
        wan.validate_arguments(tool_name, arguments)
        vidu.validate_arguments(tool_name, arguments)
    if provider_id == "luma" and tool_name in {
        "text_to_video", "image_to_video", "extend_video", "modify_video"
    }:
        from providers.luma.api import validate_generation_arguments

        validate_generation_arguments(tool_name, arguments)
    if provider_id == "remotion" and tool_name == "prepare_conversational_edit":
        from providers.remotion.transcript import build_conversational_edit

        build_conversational_edit(**arguments)
    if provider_id == "remotion" and tool_name == "render_timeline":
        for field in ("visuals", "audio_tracks"):
            for index, clip in enumerate(arguments.get(field) or []):
                if bool(clip.get("url")) == bool(clip.get("output_path")):
                    raise ValueError(f"arguments.{field}[{index}] requires exactly one of url or output_path.")
        if not arguments.get("visuals"):
            raise ValueError("render_timeline requires at least one visual clip.")
        for index, clip in enumerate(arguments.get("visuals") or []):
            if "box" in clip:
                validate_box(clip["box"], f"arguments.visuals[{index}].box")
            if "pad_box" in clip:
                validate_box(clip["pad_box"], f"arguments.visuals[{index}].pad_box")
                if clip.get("fit") != "pad_blur":
                    raise ValueError("pad_box requires fit=pad_blur.")
            if "crop_box" in clip:
                validate_crop_box(clip["crop_box"], f"arguments.visuals[{index}].crop_box")
                if clip.get("fit", "cover") != "cover":
                    raise ValueError("crop_box requires fit=cover; use pad_blur without a crop to preserve the frame.")
            if "reframe_size" in clip:
                for name, value in clip["reframe_size"].items():
                    if not 2 <= value <= 7680 or value % 2:
                        raise ValueError(f"reframe_size.{name} must be an even integer from 2 to 7680.")
                if "crop_box" not in clip and clip.get("fit") != "pad_blur":
                    raise ValueError("reframe_size requires crop_box or fit=pad_blur.")
            if "crop_box" in clip or clip.get("fit") == "pad_blur":
                if clip["kind"] != "video" or clip.get("motion", "none") != "none" or clip.get("rotation_degrees", 0) != 0 or clip.get("scale", 1) != 1:
                    raise ValueError("Reframing requires video with static scale, motion and editorial rotation.")
            if clip["kind"] not in {"image", "video"}:
                raise ValueError(f"arguments.visuals[{index}].kind must be image or video.")
            if float(clip["duration_seconds"]) <= 0:
                raise ValueError(
                    f"arguments.visuals[{index}].duration_seconds must be greater than 0."
                )
            for field in ("start_seconds", "source_in_seconds"):
                if field in clip and float(clip[field]) < 0:
                    raise ValueError(f"arguments.visuals[{index}].{field} must be at least 0.")
            if "source_fps" in clip and not 0 < float(clip["source_fps"]) <= 240:
                raise ValueError(f"arguments.visuals[{index}].source_fps must be greater than 0 and at most 240.")
            if "source_bitrate" in clip and clip["source_bitrate"] <= 0:
                raise ValueError(f"arguments.visuals[{index}].source_bitrate must be positive.")
            choices = {
                "transition": {"cut", "fade", "dip_to_black"},
                "fit": {"cover", "contain", "pad_blur"},
                "motion": {"none", "zoom_in", "zoom_out", "pan_left", "pan_right"},
                "grade": {"none", "neutral", "warm"},
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
            for field in ("fade_in_seconds", "fade_out_seconds", "audio_fade_in_seconds", "audio_fade_out_seconds"):
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
        for field in ("text_overlays", "subtitles"):
            validate_remotion_text_items(arguments.get(field) or [], f"arguments.{field}")


def validate_crop_box(box: dict[str, Any], path: str) -> None:
    _validate_schema(box, _VISUAL_ITEM_SCHEMA["properties"]["crop_box"], path)
    for name, value in box.items():
        minimum = 0 if name in {"x", "y"} else 2
        if not minimum <= value <= 7680 or value % 2:
            raise ValueError(f"{path}.{name} must be an even integer from {minimum} to 7680.")


def validate_box(box: dict[str, Any], path: str) -> None:
    _validate_schema(box, _BOX_SCHEMA, path)
    if any(not 0 <= box[key] <= 7680 for key in ("x", "y")) or any(
        not 0 < box[key] <= 7680 for key in ("width", "height")
    ):
        raise ValueError(f"{path} requires nonnegative coordinates and positive dimensions up to 7680.")


def validate_remotion_text_items(items: list[dict[str, Any]], path: str) -> None:
    _validate_schema(items, {"type": "array", "items": _TEXT_OVERLAY_SCHEMA}, path)
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        if not item["text"].strip():
            raise ValueError(f"{item_path}.text must be non-empty.")
        if len(item["text"]) > 500 or "\x00" in item["text"]:
            raise ValueError(f"{item_path}.text allows at most 500 characters and no NUL.")
        if "box" in item:
            validate_box(item["box"], item_path + ".box")
        if item.get("font_family", "dejavu-sans") not in {"dejavu-sans", "dejavu-sans-bold"}:
            raise ValueError(f"{item_path}.font_family is not allow-listed.")
        for field in ("min_font_size", "max_font_size"):
            if field in item and not 16 <= item[field] <= 180:
                raise ValueError(f"{item_path}.{field} must be between 16 and 180.")
        if item.get("min_font_size", 16) > item.get("max_font_size", 180):
            raise ValueError(f"{item_path} minimum font size exceeds maximum.")
        if "opacity" in item and not 0 <= item["opacity"] <= 1:
            raise ValueError(f"{item_path}.opacity must be between 0 and 1.")
        if item["start_seconds"] < 0:
            raise ValueError(f"{item_path}.start_seconds must be at least 0.")
        duration = item["duration_seconds"]
        if duration <= 0:
            raise ValueError(f"{item_path}.duration_seconds must be greater than 0.")
        if "position" in item and item["position"] not in {"top", "center", "bottom"}:
            raise ValueError(f"{item_path}.position must be top, center, or bottom.")
        for field, (minimum, maximum) in {"font_size": (16, 180), "font_weight": (100, 900)}.items():
            if field in item and not minimum <= item[field] <= maximum:
                raise ValueError(f"{item_path}.{field} must be between {minimum} and {maximum}.")
        for field in ("fade_in_seconds", "fade_out_seconds"):
            if field in item and not 0 <= item[field] <= duration:
                raise ValueError(f"{item_path}.{field} must fit inside the text duration.")


def validate_remotion_timeline_arguments(arguments: dict[str, Any]) -> None:
    for field, item_schema in (("visuals", _VISUAL_ITEM_SCHEMA), ("audio_tracks", _AUDIO_ITEM_SCHEMA)):
        if arguments.get(field) is not None:
            _validate_schema(arguments[field], {"type": "array", "items": item_schema}, f"arguments.{field}")
    _validate_cross_fields("remotion", "render_timeline", arguments)


def validate_tool_arguments(
    provider_id: str,
    tool_name: str,
    arguments: dict[str, Any] | None,
    input_schema: dict[str, Any],
) -> dict[str, Any]:
    """Validate every Gateway call at the last boundary before provider I/O."""
    if provider_id == "fal":
        from providers.fal.images import validate_arguments

        validate_arguments(tool_name, arguments or {})
    if provider_id == "fal" and tool_name == "mirelo_v2a":
        from providers.fal.mirelo import validate_arguments

        validate_arguments(tool_name, arguments or {})
    if provider_id == "heygen":
        from providers.heygen.contracts import validate_arguments

        validate_arguments(tool_name, arguments or {})
    if provider_id == "sync":
        for field, value in (arguments or {}).items():
            if value is None and field not in {"model", "chunk_boundaries_seconds"}:
                raise ValueError(f"arguments.{field} cannot be null.")
    if provider_id == "openai_images":
        for field, value in (arguments or {}).items():
            if value is None and field not in {"model", "reference_image_urls", "mask_path_or_url", "output_compression"}:
                raise ValueError(f"arguments.{field} cannot be null.")
    if provider_id == "seedance":
        optional = {"model", "service_tier", "seed", "end_image_path_or_url", "source_aspect_ratio",
                    "reference_image_urls", "reference_video_urls", "reference_audio_urls",
                    "reference_video_durations", "reference_video_fps", "reference_audio_durations"}
        for field, value in (arguments or {}).items():
            if value is None and field not in optional:
                raise ValueError(f"arguments.{field} cannot be null.")
    if provider_id == "alibaba_modelstudio":
        optional = {"seed", "reference_image_urls", "reference_audio_urls", "reference_audio_durations"}
        for field, value in (arguments or {}).items():
            if value is None and field not in optional:
                raise ValueError(f"arguments.{field} cannot be null.")
    cleaned = {key: value for key, value in (arguments or {}).items() if value is not None}
    _validate_schema(cleaned, input_schema, "arguments",
                     allow_empty_strings=provider_id == "remotion" and tool_name == "prepare_conversational_edit")
    for field, rule in argument_rules(provider_id, tool_name).items():
        if field in cleaned:
            _validate_rule(f"arguments.{field}", cleaned[field], rule)
    _validate_cross_fields(provider_id, tool_name, cleaned)
    if provider_id == "fal":
        from providers.fal import wan3

        if (tool_name in wan3.GENERATING_TOOLS and "duration" in (arguments or {})
                and arguments["duration"] is None):
            # Wan smart duration differs from an omitted default duration.
            cleaned["duration"] = None
    return cleaned


def argument_rules(provider_id: str, tool_name: str) -> dict[str, ArgumentRule]:
    if provider_id == "topaz":
        from providers.topaz.contracts import ARGUMENT_RULES

        return ARGUMENT_RULES.get(tool_name, {})
    if provider_id == "seedance":
        from providers.seedance.contracts import ARGUMENT_RULES

        return ARGUMENT_RULES.get(tool_name, {})
    if provider_id == "alibaba_modelstudio":
        from providers.alibaba_modelstudio.contracts import ARGUMENT_RULES

        return ARGUMENT_RULES.get(tool_name, {})
    if provider_id == "fal":
        from providers.fal import vidu, wan, wan3, mirelo

        return {**wan.ARGUMENT_RULES, **vidu.ARGUMENT_RULES, **wan3.ARGUMENT_RULES, **mirelo.ARGUMENT_RULES}.get(tool_name, {})
    return TOOL_ARGUMENT_RULES.get(provider_id, {}).get(tool_name, {})
