"""Dispatch Gateway tools and generate AgentCore tool schemas from provider APIs."""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable
from pathlib import Path
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from providers.catalog import ProviderSpec, get_provider
from providers.contracts import enrich_tool_schema, validate_tool_arguments


ROOT = Path(__file__).resolve().parents[1]
GATEWAY_SCHEMA_DIR = ROOT / "configs" / "gateway"
FORBIDDEN_TOOL_RE = re.compile(r"^(wait_for_.*|.*_and_wait)$")


TOOL_GUIDANCE: dict[str, dict[str, str]] = {
    "kling": {
        "text_to_video": (
            "Use for a new Kling video from text, including native audio and multi-shot prompts. "
            "Returns a queued job_id; follow with get_video_task until terminal."
        ),
        "image_to_video": (
            "Use to animate an existing first frame, optionally with a last frame or elements. "
            "Returns a queued job_id; follow with get_video_task until terminal."
        ),
        "omni_video": (
            "Use for Kling Omni video with multiple reference images or elements. "
            "Returns a queued job_id; follow with get_video_task until terminal."
        ),
        "get_video_task": (
            "Use only with the exact job_id returned by a Kling generation tool. "
            "Poll once per call until succeeded, failed, or dry_run; download saves completed video. "
            "It does not create a new video."
        ),
        "list_kling_models": (
            "List documented Kling video models and capabilities without creating media. "
            "Use when model selection matters; prefer the configured default otherwise."
        ),
    },
    "runway": {
        "text_to_video": "Create a Gen-4.5 video from text. Starts paid work unless dry-run. Poll get_runway_task with the returned job_id at least five seconds apart.",
        "image_to_video": "Animate a supplied image with Gen-4.5. Starts paid work unless dry-run. Poll get_runway_task with the returned job_id at least five seconds apart.",
        "video_to_video": "Edit an existing 2-30 second clip with Aleph 2.0 and a text instruction, optionally guided by a timed reference image. Supply the actual source duration for the cost estimate. Poll get_runway_task.",
        "text_to_image": "Create a Gen-4 image from text. Returns a queued task, not a finished image. Poll get_runway_task at least five seconds apart and save its completed image.",
        "image_to_image": "Generate a Gen-4 reference image using a source image and text instruction, optionally additional references. Returns a queued task. Poll get_runway_task and save its completed image.",
        "get_runway_task": "Poll an existing Runway job_id once. Never submit another generation to check status. Wait at least five seconds between calls. Completed media URLs expire and must be saved.",
        "list_runway_models": "List locally documented supported Runway models and limits. Free, no API request. This catalog does not verify account access or live model availability.",
    },
    "fal": {
        "text_to_video": "Generate a Wan VACE clip from text. Returns job_id; poll get_video_task with download=true until terminal.",
        "image_to_video": "Animate first_frame_url using Wan VACE. Returns job_id; poll get_video_task with download=true until terminal.",
        "reference_to_video": "Generate a Wan VACE clip guided by ref_image_urls for subject consistency. Returns job_id; poll get_video_task with download=true until terminal.",
        "video_to_video": "Edit video_url with Wan VACE. Choose freeform, inpainting, outpainting, reframe, depth, or pose. Inpainting needs one mask; outpainting needs expansion sides. Returns job_id; poll get_video_task with download=true until terminal.",
        "generate_wan3_t2v": "Generate Wan 3 text-to-video, 2 to 30 seconds at 480p/720p/1080p, with native audio by default. Always request approval with a cost estimate, including autonomous runs. Poll get_video_task with download=true. Closed weights and commercial hosted API; outputs are not training eligible.",
        "generate_wan3_i2v": "Animate start_image_url with Wan 3, optionally constrained by end_image_url. Real-person likeness references require real_face_refs=true and likeness_consent=true. Always request approval with cost, then poll get_video_task with download=true.",
        "generate_wan3_r2v": "Generate Wan 3 from up to 10 images, 5 videos totaling 15 seconds and 5 audio clips totaling 15 seconds. Supply measured reference_video_durations, reference_video_fps and reference_audio_durations alongside the matching URLs. Input video seconds also incur cost. Real-person likeness requires consent. Always request approval with cost, then poll get_video_task with download=true.",
        "vidu_q4_i2v": "Animate image_url with Vidu Q4 native audio at 540p through 4K for 3 to 16 seconds. Prompt is optional. Returns job_id; poll get_video_task with download=true until terminal. Hosted service terms apply; outputs are not training eligible.",
        "vidu_q4_r2v": "Generate Vidu Q4 video using an optional list of up to 12 reference images and 3 MP3 voice clips. Refer to images with [@reference_image_1] and voices with [reference_audio_1]. Audio defaults to false; set audio=true for dialogue and sound effects. Returns job_id; poll get_video_task with download=true until terminal. Outputs are not training eligible.",
        "get_video_task": "Poll an existing fal job_id once. Fetch completed results and optionally download the MP4. Never submits another generation.",
        "list_fal_models": "List documented Wan VACE, Wan 3.0 and Vidu Q4 models, endpoints, licences, and published pricing. Static catalog; no network or generation.",
    },
    "luma": {
        "text_to_video": "Generate a Ray 3.2 clip from text. Returns a queued job_id; poll get_video_task until terminal. Outputs are not training eligible.",
        "image_to_video": "Animate a start image, end image, or both with Ray 3.2. Anchor clips are 5 seconds. Returns job_id; poll get_video_task. Outputs are not training eligible.",
        "extend_video": "Continue or prepend a completed Luma generation using its generation UUID. Returns job_id; poll get_video_task. Extend bills one 5-second block. Outputs are not training eligible.",
        "modify_video": "Restyle or edit an existing MP4 video with Ray 3.2. Supply exactly one video source and its measured 5s or 10s duration for pricing. Returns job_id; poll get_video_task. Outputs are not training eligible.",
        "get_video_task": "Poll a Luma generation UUID. Call with download=true to persist the completed MP4. Polling is free; processing maps to running, completed to succeeded. Do not resubmit while a job is pending.",
        "list_luma_models": "List documented Luma video models and their supported settings. This is an offline capability catalog, not an account access check. Ray 3.2 has no separate Flash identifier.",
    },
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
        "prepare_conversational_edit": (
            "Use for conversational transcript edits after proposing the cut, grade, and captions "
            "in plan_summary for required host approval. Always returns a side-effect-free dry_run "
            "preview with word-safe cuts, output-timed transcript/captions, timeline, render_arguments, "
            "and QC expectations. It never fetches media or starts a render. Use the separate paid "
            "render_timeline tool with render_arguments after preparation."
        ),
        "render_timeline": (
            "Use after all source assets exist to execute a concrete edit decision list and make "
            "one assembled MP4. The caller must choose timing, B-roll layers, crop/motion, "
            "transitions, speed, titles, and audio fades, then poll get_render_progress."
        ),
        "get_render_progress": (
            "Use only after render_timeline returned a render id and bucket name. Poll once per call "
            "until succeeded, failed, cancelled, or dry_run; it does not start a new render."
        ),
        "export_nle_timeline": (
            "Use for send to Resolve, give my editor a timeline, or export XML/EDL. Accepts a "
            "pinned Remotion document/renderConfig JSON snapshot with immutable asset version IDs, "
            "SHA-256 checksums, source timecodes, reel names, provenance, and generation flags. "
            "Returns an OTIO, FCPXML, per-track EDL and referenced-media ZIP. Generated clips "
            "occupy new tracks. Never calls Resolve or exports AAF."
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
    for name in ("video_url", "first_frame_url", "ref_image_urls"):
        if name in args:
            url = "https://example.com/ci-smoke.mp4" if name == "video_url" else "https://example.com/ci-smoke.png"
            args[name] = [url] if name == "ref_image_urls" else url
    for name, field_schema in props.items():
        if name in args and "UUID" in str(field_schema.get("description") or ""):
            args[name] = "d290f1ee-6c54-4b01-90e6-d701748f0851"
    if schema.get("name") == "image_to_video" and "last_frame_path_or_url" in props:
        args["image_path_or_url"] = "ci-smoke"
    if schema.get("name") == "modify_video":
        args["video_path_or_url"] = "ci-smoke"
    source_fields = {
        "extend_song": "song_id",
        "region_edit_song": "song_id",
        "remix_song": "song_id",
        "stem_song": "song_id",
        "recognize_song": "upload_audio_id",
        "describe_song": "song_id",
        "transcribe_song": "song_id",
        "generate_track": "song_id",
        "generate_soundtrack": "image_id",
        "generate_lyrics_video": "song_id",
    }
    source_field = source_fields.get(str(schema.get("name") or ""))
    if source_field and source_field in props:
        args[source_field] = "ci-smoke"
    if schema.get("name") == "region_edit_song":
        args["edit_end_ms"] = 2
    return args
