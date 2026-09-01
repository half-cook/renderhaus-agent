"""Dispatch Gateway tools and generate AgentCore tool schemas from provider APIs."""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable
from pathlib import Path
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from providers.catalog import PROVIDERS, ProviderSpec, get_provider
from providers.contracts import enrich_tool_schema, validate_tool_arguments


ROOT = Path(__file__).resolve().parents[1]
GATEWAY_SCHEMA_DIR = ROOT / "configs" / "gateway"
LEGACY_MUREKA_SCHEMA_PATH = ROOT / "configs" / "mureka_gateway_tools.json"
FORBIDDEN_TOOL_RE = re.compile(r"^(wait_for_.*|.*_and_wait)$")


TOOL_GUIDANCE: dict[str, dict[str, str]] = {
    "seedream": {
        "text_to_image": (
            "Use when the user needs a new still image from a text description. Do not use for "
            "editing an existing image; use image_to_image instead. Returns a generated image."
        ),
        "image_to_image": (
            "Use when the user supplied or referenced an existing image and wants it edited, "
            "restyled, or varied while preserving visual context. Returns a new image."
        ),
        "list_seedream_models": (
            "Use only when model selection or model availability is relevant; it does not generate "
            "media. Prefer the configured default for ordinary image requests."
        ),
    },
    "seedance": {
        "text_to_video": (
            "Use when the user needs a new video clip from text and no source image must be "
            "preserved. Returns a queued task id; follow with get_video_task until terminal."
        ),
        "image_to_video": (
            "Use when the user wants an existing image animated into a video clip. Requires an "
            "image URL and returns a queued task id; follow with get_video_task until terminal."
        ),
        "get_video_task": (
            "Use only after text_to_video or image_to_video returned a task id. Poll once per call "
            "until succeeded, failed, cancelled, or dry_run; it does not create a new video."
        ),
        "list_seedance_models": (
            "Use only when model selection or availability is relevant; it does not generate media. "
            "Prefer the configured default for ordinary video requests."
        ),
    },
    "remotion": {
        "render_timeline": (
            "Use after all source assets exist to execute a concrete edit decision list and make "
            "one assembled MP4. The caller must choose timing, B-roll layers, crop/motion, "
            "transitions, speed, titles, and audio fades, then poll get_render_progress."
        ),
        "get_render_progress": (
            "Use only after render_timeline returned a render id and bucket name. Poll once per call "
            "until succeeded, failed, cancelled, or dry_run; it does not start a new render."
        ),
    },
    "mureka": {
        "text_to_music": (
            "Use for a simple new music request when the user does not need a specialized Mureka "
            "workflow. Creates a song when lyrics are supplied, otherwise an instrumental."
        ),
        "create_instrumental": (
            "Use when the user needs original background music without vocals. Returns a queued "
            "task id; follow with query_music_task until terminal."
        ),
        "create_song": (
            "Use when the user already has lyrics and wants a fully produced vocal song. Returns a "
            "queued task id; follow with query_music_task until terminal."
        ),
        "create_song_from_prompt": (
            "Use when the user wants a complete vocal song from a concept but has no finished "
            "lyrics. Returns a queued task id; follow with query_music_task until terminal."
        ),
        "generate_lyrics": (
            "Use when the deliverable is song lyrics or when lyrics are needed before create_song. "
            "It produces text, not audio."
        ),
        "extend_lyrics": (
            "Use when existing lyrics need another verse, chorus, bridge, or continuation. It "
            "produces revised text, not audio."
        ),
        "query_music_task": (
            "Use only after a Mureka creation or editing tool returned a task id. Poll once per call "
            "until succeeded, failed, cancelled, or dry_run; request download on the final poll."
        ),
        "get_music_task": (
            "Alias for query_music_task. Use only to check an existing Mureka task id; it does not "
            "start new music generation."
        ),
        "extend_song": (
            "Use when an existing song or uploaded audio should continue beyond a specified time. "
            "Requires lyrics for the extension and a song or upload id."
        ),
        "region_edit_song": (
            "Use when only a specific time range of an existing song should be replaced. Requires "
            "start/end times plus a song or upload id."
        ),
        "remix_song": (
            "Use when an existing song or uploaded audio should be reinterpreted with a new style "
            "or production prompt while keeping it as the source."
        ),
        "stem_song": (
            "Use when the user needs an existing song separated into stems such as vocals and "
            "instrumental parts. Requires a song or upload id."
        ),
        "recognize_song": (
            "Use to identify or analyze what song is present in uploaded audio or an audio URL. It "
            "does not generate or edit music."
        ),
        "describe_song": (
            "Use to obtain a musical description of an existing Mureka song or uploaded audio for "
            "planning, tagging, or a later remix."
        ),
        "transcribe_song": (
            "Use to extract sung words or lyrics from an existing Mureka song or uploaded audio. It "
            "does not create new audio."
        ),
        "vocal_clone": (
            "Use only when the user explicitly wants a reusable vocal model made from an uploaded "
            "voice sample. Requires an upload id."
        ),
        "generate_track": (
            "Use to add or regenerate a specific musical track for an existing song, such as drums "
            "or bass. Requires a track type and a song or upload id."
        ),
        "generate_soundtrack": (
            "Use when the user needs music synchronized to an uploaded media file or a specified "
            "time range. Use create_instrumental for standalone background music."
        ),
        "generate_lyrics_video": (
            "Use when the user wants a lyric video from an existing Mureka song or uploaded audio. "
            "It is not the general multi-clip video editor."
        ),
        "upload_file": (
            "Use only when another Mureka operation requires an upload id and the source bytes are "
            "available as base64. It does not analyze or generate media by itself."
        ),
        "create_speech": (
            "Use when the user needs spoken narration or voiceover from text. Use song tools for "
            "singing and music tools for instrumental audio."
        ),
        "create_podcast": (
            "Use when the user wants a spoken podcast-style audio program from a script. Use "
            "create_speech for a single narration passage."
        ),
        "query_billing": (
            "Use only when the user explicitly asks about Mureka account billing or quota. It does "
            "not estimate Renderhaus-wide generation cost."
        ),
        "list_mureka_models": (
            "Use only when Mureka model selection or availability is relevant; it does not generate "
            "audio. Prefer the configured default for ordinary requests."
        ),
    },
}


def is_forbidden_gateway_tool(name: str) -> bool:
    return bool(FORBIDDEN_TOOL_RE.match(name))


def schema_path(spec: ProviderSpec) -> Path:
    return GATEWAY_SCHEMA_DIR / f"{spec.id}.tools.json"


_STRING_TYPE_MAP = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "dict": dict,
    "list": list,
}


def _unwrap_optional(hint: Any) -> Any:
    origin = get_origin(hint)
    if origin in {Union, UnionType}:
        args = [arg for arg in get_args(hint) if arg is not type(None)]
        if len(args) == 1:
            return args[0]
    return hint


def _json_schema_for_hint(hint: Any) -> dict[str, Any]:
    if isinstance(hint, str):
        stripped = hint.replace(" ", "")
        if stripped.endswith("|None"):
            stripped = stripped[: -len("|None")]
        if stripped.startswith("Literal["):
            return {"type": "string"}
        if stripped.startswith("list["):
            return {"type": "array", "items": {"type": "object"}}
        if stripped.startswith("dict["):
            return {"type": "object"}
        hint = _STRING_TYPE_MAP.get(stripped, hint)
    hint = _unwrap_optional(hint)
    origin = get_origin(hint)
    args = get_args(hint)
    if origin is Literal:
        values = list(args)
        if values and all(isinstance(value, bool) for value in values):
            json_type = "boolean"
        elif values and all(
            isinstance(value, int) and not isinstance(value, bool) for value in values
        ):
            json_type = "integer"
        elif values and all(
            isinstance(value, (int, float)) and not isinstance(value, bool) for value in values
        ):
            json_type = "number"
        else:
            json_type = "string"
        # AgentCore Gateway Lambda schemas allow only type/properties/required/items/description.
        return {
            "type": json_type,
            "description": f"One of: {', '.join(str(value) for value in values)}.",
        }
    if origin is list:
        items = _json_schema_for_hint(args[0]) if args else {"type": "object"}
        return {"type": "array", "items": items}
    if origin is dict:
        return {"type": "object"}
    mapping = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        dict: "object",
        list: "array",
    }
    json_type = mapping.get(hint)
    if json_type:
        return {"type": json_type}
    return {"type": "string"}


def schema_from_callable(name: str, fn: Callable[..., Any]) -> dict[str, Any]:
    signature = inspect.signature(fn)
    try:
        hints = get_type_hints(fn)
    except Exception:  # noqa: BLE001 - fall back to annotations as written
        hints = getattr(fn, "__annotations__", {})
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param_name, param in signature.parameters.items():
        if param_name in {"self", "cls"} or param.kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            continue
        hint = hints.get(param_name, Any)
        properties[param_name] = _json_schema_for_hint(hint)
        if param.default is inspect.Parameter.empty:
            required.append(param_name)
    description = inspect.getdoc(fn) or f"{name} provider tool."
    description = description.strip().split("\n", 1)[0]
    schema: dict[str, Any] = {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
        },
    }
    if required:
        schema["inputSchema"]["required"] = required
    else:
        schema["inputSchema"]["required"] = []
    return schema


_GATEWAY_SCHEMA_KEYS = frozenset({"type", "properties", "required", "items", "description"})


def _sanitize_json_schema_object(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema
    enum_values = schema.get("enum")
    cleaned: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in _GATEWAY_SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            cleaned[key] = {
                name: _sanitize_json_schema_object(child) for name, child in value.items()
            }
        elif key == "items":
            cleaned[key] = _sanitize_json_schema_object(value)
        else:
            cleaned[key] = value
    if enum_values:
        choices = ", ".join(str(value) for value in enum_values)
        existing = str(cleaned.get("description") or "").strip()
        note = f"One of: {choices}."
        cleaned["description"] = f"{existing} {note}".strip() if existing else note
    return cleaned


def sanitize_gateway_json_schema(node: Any) -> Any:
    """Drop JSON Schema fields AgentCore Gateway Lambda targets reject (e.g. enum)."""
    if isinstance(node, list):
        return [sanitize_gateway_json_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    if "name" in node and "inputSchema" in node:
        return {
            "name": node["name"],
            "description": str(node.get("description") or ""),
            "inputSchema": _sanitize_json_schema_object(node["inputSchema"]),
        }
    return _sanitize_json_schema_object(node)


def gateway_tools(spec: ProviderSpec) -> tuple[str, ...]:
    module = __import__(spec.module_path, fromlist=["GATEWAY_TOOLS", "TOOL_HANDLERS"])
    names = getattr(module, "GATEWAY_TOOLS", None)
    if names is None:
        names = tuple(getattr(module, "TOOL_HANDLERS", {}))
    return tuple(names)


def generate_schemas(spec: ProviderSpec) -> list[dict[str, Any]]:
    module = __import__(
        spec.module_path, fromlist=["GATEWAY_SCHEMAS", "TOOL_HANDLERS", "GATEWAY_TOOLS"]
    )
    explicit = getattr(module, "GATEWAY_SCHEMAS", None)
    if explicit is not None:
        tools = [
            enrich_tool_schema(spec.id, sanitize_gateway_json_schema(tool)) for tool in explicit
        ]
        for tool in tools:
            guidance = TOOL_GUIDANCE.get(spec.id, {}).get(str(tool.get("name") or ""))
            if guidance:
                tool["description"] = guidance
        return tools
    handlers = getattr(module, "TOOL_HANDLERS")
    tools = []
    for name in gateway_tools(spec):
        if is_forbidden_gateway_tool(name):
            raise ValueError(
                f"{spec.id} Gateway tool {name!r} is a blocking wait helper. "
                "Keep wait_for_* / *_and_wait off Gateway; poll get_* instead."
            )
        handler = handlers.get(name)
        if handler is None:
            raise ValueError(f"{spec.id} GATEWAY_TOOLS lists {name!r} but TOOL_HANDLERS does not.")
        tool = enrich_tool_schema(
            spec.id,
            sanitize_gateway_json_schema(schema_from_callable(name, handler)),
        )
        guidance = TOOL_GUIDANCE.get(spec.id, {}).get(name)
        if guidance:
            tool["description"] = guidance
        tools.append(tool)
    return tools


def write_schemas(spec: ProviderSpec, tools: list[dict[str, Any]] | None = None) -> Path:
    GATEWAY_SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    payload = tools if tools is not None else generate_schemas(spec)
    path = schema_path(spec)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    if spec.id == "mureka":
        LEGACY_MUREKA_SCHEMA_PATH.write_text(path.read_text())
    return path


def load_committed_schemas(spec: ProviderSpec) -> list[dict[str, Any]]:
    path = schema_path(spec)
    if not path.exists():
        raise FileNotFoundError(f"Missing committed Gateway schema: {path}")
    tools = json.loads(path.read_text())
    if not isinstance(tools, list) or not tools:
        raise ValueError(f"{path} must be a non-empty list of tool schemas")
    return [enrich_tool_schema(spec.id, sanitize_gateway_json_schema(tool)) for tool in tools]


def dispatch(
    provider_id: str, tool_name: str, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    if is_forbidden_gateway_tool(tool_name):
        raise ValueError(
            f"{tool_name} is not a Gateway tool. Blocking wait helpers stay off Lambda; poll get_* instead."
        )
    spec = get_provider(provider_id)
    module = __import__(
        spec.module_path, fromlist=["TOOL_HANDLERS", "dispatch_tool", "GATEWAY_TOOLS"]
    )
    allowed = set(gateway_tools(spec))
    if tool_name not in allowed:
        raise ValueError(f"Unknown {provider_id} Gateway tool: {tool_name}")
    schema = next(tool for tool in generate_schemas(spec) if tool.get("name") == tool_name)
    cleaned = validate_tool_arguments(
        provider_id,
        tool_name,
        arguments,
        schema.get("inputSchema") or {},
    )
    dispatch_tool = getattr(module, "dispatch_tool", None)
    if callable(dispatch_tool):
        result = dispatch_tool(tool_name, cleaned)
    else:
        handler = getattr(module, "TOOL_HANDLERS")[tool_name]
        result = handler(**cleaned)
    if not isinstance(result, dict):
        return {"result": result}
    return result


def dummy_arguments(schema: dict[str, Any]) -> dict[str, Any]:
    props = (schema.get("inputSchema") or {}).get("properties") or {}
    required = (schema.get("inputSchema") or {}).get("required") or []

    def dummy_value(field_schema: dict[str, Any]) -> Any:
        description = str(field_schema.get("description") or "")
        allowed = re.search(r"Allowed values: ([^.]+)\.", description)
        json_type = field_schema.get("type", "string")
        if allowed:
            first = allowed.group(1).split(",", 1)[0].strip()
            if json_type == "integer":
                return int(first)
            if json_type == "number":
                return float(first)
            return first
        if json_type == "integer":
            return 1
        if json_type == "number":
            return 1.0
        if json_type == "boolean":
            return False
        if json_type == "array":
            item_schema = field_schema.get("items") or {"type": "object"}
            return [dummy_value(item_schema)]
        if json_type == "object":
            child_props = field_schema.get("properties") or {}
            child_required = field_schema.get("required") or []
            return {name: dummy_value(child_props[name]) for name in child_required}
        return "ci-smoke"

    args: dict[str, Any] = {}
    for name in required:
        args[name] = dummy_value(props.get(name) or {"type": "string"})
    source_fields = {
        "extend_song": "song_id",
        "region_edit_song": "song_id",
        "remix_song": "song_id",
        "stem_song": "song_id",
        "recognize_song": "upload_audio_id",
        "describe_song": "song_id",
        "transcribe_song": "song_id",
        "generate_track": "song_id",
        "generate_lyrics_video": "song_id",
    }
    source_field = source_fields.get(str(schema.get("name") or ""))
    if source_field and source_field in props:
        args[source_field] = "ci-smoke"
    if schema.get("name") == "region_edit_song":
        args["edit_end_ms"] = 2
    return args


def iter_providers() -> tuple[ProviderSpec, ...]:
    return PROVIDERS
