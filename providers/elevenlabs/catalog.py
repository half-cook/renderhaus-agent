"""Project the pinned ElevenLabs OpenAPI into AgentCore's small tool-schema dialect.

Refresh openapi.json with scripts/update_elevenlabs_schema.py. Complex inputs stay JSON
strings because Gateway Lambda schemas cannot express unions, maps or recursive objects.
The dispatcher decodes and validates them against the complete upstream schema.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

SOURCE_URL = "https://api.elevenlabs.io/openapi.json"
SPEC = json.loads(Path(__file__).with_name("openapi.json").read_text())

FAMILY_GUIDANCE = {
    "music": "Create background scores, instrumental beds, songs with vocals, video soundtracks, composition plans or stems for an edit.",
    "text_to_speech": "Turn a written script into single-speaker narration, voiceover or spoken dialogue. Choose a voice_id from voices_search first.",
    "text_to_dialogue": "Create a multi-speaker conversation, character scene or podcast from text and a voice_id for each speaker.",
    "text_to_sound_effects": "Create Foley, ambience, transitions, impacts or looping sound effects from a text description; use music_compose for a musical score.",
    "speech_to_speech": "Change the voice of an existing recording while retaining its spoken content and performance; requires source audio and a target voice_id.",
    "audio_isolation": "Clean dialogue by removing background noise from existing audio; does not compose music or transcribe words.",
    "speech_to_text": "Transcribe existing audio/video into text, speaker labels and word timestamps for captions, subtitles or a transcript.",
    "forced_alignment": "Align a supplied transcript with existing audio to obtain word timing; use speech_to_text when the transcript is unknown.",
    "text_to_voice": "Design or remix a synthetic voice from a description and preview it before saving a reusable voice.",
    "voices": "Find, inspect or manage reusable voices and voice settings for narration, dialogue and dubbing. Cloning needs authorized voice samples.",
    "samples": "Inspect or manage the recorded samples attached to an existing voice; this does not generate a soundtrack.",
    "dubbing": "Translate and revoice existing audio/video into another language, edit speakers or segments, and retrieve dubbed audio and subtitles.",
    "studio": "Manage ElevenLabs long-form audio projects, chapters, podcasts and rendered snapshots. These are ElevenLabs projects, separate from the Renderhaus canvas.",
    "pronunciation_dictionaries": "Control how names, brands, abbreviations and unusual words are spoken using reusable pronunciation rules.",
    "history": "Find or retrieve previously generated speech to reuse audio without generating again; music and sound effects are not in speech history.",
    "models": "Discover available speech model IDs and capabilities before selecting a model; this is a read-only lookup.",
    "user": "Inspect the connected ElevenLabs account, subscription or remaining usage; does not create media.",
    "usage": "Inspect ElevenLabs usage and consumption for reporting or budget checks; does not create media.",
    "audio_native": "Manage an embedded audio player and narrated website content; use text_to_speech for ordinary Renderhaus voiceovers.",
    "speech_engine": "Manage reusable speech-generation configurations for consistent output across requests.",
    "conversational_ai": "Manage ElevenLabs conversational voice agents, knowledge bases, conversations, tests, phone integrations and analytics. Use only for an explicit voice-agent task, not ordinary media creation.",
    "workspace": "Administer the connected ElevenLabs workspace, members, groups, access and resources. Use only for an explicit account-administration request.",
    "service_accounts": "Manage service accounts and API-key access for the connected ElevenLabs workspace. Use only for an explicit credential-administration request.",
    "productions": "Manage human production orders and deliverables. Submitting an order may commission paid external work; use only when explicitly requested.",
    "flows": "Run or inspect ElevenLabs image, video, speech generations and reusable workflow templates; poll the matching generation or run ID before retrieving output.",
    "assets": "Upload, find or manage media stored in ElevenLabs for Flows workflows; these are separate from Renderhaus's owned assets.",
    "tokens": "Create a short-lived client token for an explicitly requested realtime ElevenLabs integration; ordinary Gateway generation uses the server-side key.",
}

INTENT = {
    "music_compose": "Use for a new song or background music from a prompt or composition plan. Set force_instrumental=true for a score without vocals and music_length_ms for the required duration (3000–600000 ms). Returns finished audio, not a pollable task.",
    "music_composition_plan_create": "Use to plan song structure, sections, lyrics, styles and timing before music_compose. Returns a composition plan, not playable audio.",
    "music_video_to_music": "Use when existing video should guide the soundtrack. Supply the video files in story order; optionally describe mood/style. Returns music aligned to those videos.",
    "music_separate_stems": "Use to separate an existing song into vocals and instrumental/stem tracks for mixing. Requires source music; does not compose a new song.",
    "voices_search": "Use before narration or dialogue to find an existing voice and its voice_id by name or filters. Returns voice metadata; does not synthesize audio.",
}


def resolve(schema: dict) -> dict:
    if isinstance(schema, bool):
        return {} if schema else {"not": {}}
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/components/schemas/"):
            raise ValueError(f"Unsupported upstream schema reference: {ref}")
        return {**SPEC["components"]["schemas"][ref.rsplit("/", 1)[-1]],
                **{k: v for k, v in schema.items() if k != "$ref"}}
    return schema


def nonnull(schema: dict) -> dict:
    schema = resolve(schema)
    variants = schema.get("anyOf", schema.get("oneOf", []))
    non_null = [s for s in variants if resolve(s).get("type") != "null"]
    if len(non_null) == 1:
        return {**nonnull(non_null[0]), **{k: v for k, v in schema.items() if k not in {"anyOf", "oneOf"}}}
    return schema


def compact_shape(schema: dict, depth: int = 0) -> Any:
    """A short input guide, not the validator (which retains every upstream constraint)."""
    schema = nonnull(schema)
    if depth >= 4:
        return schema.get("title") or schema.get("type") or "JSON value"
    if "enum" in schema:
        return schema["enum"]
    if schema.get("type") == "object":
        props = schema.get("properties", {})
        if not props:
            return {"<key>": compact_shape(schema.get("additionalProperties") or {}, depth + 1)}
        required = schema.get("required", [])
        return {k + (" (required)" if k in required else ""): compact_shape(v, depth + 1) for k, v in props.items()}
    if schema.get("type") == "array":
        return [compact_shape(schema.get("items", {}), depth + 1)]
    variants = schema.get("anyOf", schema.get("oneOf", []))
    if variants:
        return [compact_shape(v, depth + 1) for v in variants]
    return schema.get("type", "JSON value")


def field_schema(raw: dict) -> tuple[dict, bool, bool]:
    schema = nonnull(raw)
    kind = schema.get("type")
    item = nonnull(schema.get("items", {})) if kind == "array" else {}
    simple = kind in {"string", "number", "integer", "boolean"}
    simple_array = kind == "array" and item.get("type") in {"string", "number", "integer", "boolean"}
    binary = schema.get("format") == "binary" or item.get("format") == "binary"
    encoded = not (simple or simple_array)
    result = {"type": "string" if encoded else kind}
    if simple_array:
        result["items"] = {"type": item["type"]}
    notes = [str(schema.get("description") or "")]
    if binary:
        notes.append("File input: supply a Renderhaus source_ref (resolved to a signed storage URL), not a local path or base64.")
    if encoded:
        notes.append("JSON-encoded value. Shape: " + json.dumps(compact_shape(raw), ensure_ascii=False, separators=(",", ":")))
    for key in ("enum", "default", "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"):
        if key in schema:
            notes.append(f"{key}: {json.dumps(schema[key], ensure_ascii=False)}.")
    result["description"] = " ".join(filter(None, notes))[:12000]
    return result, encoded, binary


def build_catalog() -> dict[str, dict]:
    tools = {}
    for path, methods in SPEC["paths"].items():
        for method, operation in methods.items():
            if method not in {"get", "post", "put", "patch", "delete", "head", "options"}:
                continue
            groups = operation.get("x-fern-sdk-group-name") or ["documentation"]
            groups = [groups] if isinstance(groups, str) else groups
            action = operation.get("x-fern-sdk-method-name") or operation.get("operationId") or method
            name = re.sub(r"[^a-zA-Z0-9_]+", "_", "_".join([*groups, action])).lower()
            if len(name) > 64:
                name = name[:53] + "_" + hashlib.sha256(name.encode()).hexdigest()[:10]
            if name in tools:
                raise ValueError(f"Duplicate ElevenLabs tool name: {name}")
            props, required, bindings = {}, [], {}
            def add(field, raw, location, needed=False):
                projected, encoded, binary = field_schema(raw)
                exposed = field + ("_json" if encoded else "")
                if exposed in props:
                    exposed = location + "_" + exposed
                props[exposed] = projected
                bindings[exposed] = {"field": field, "location": location, "schema": raw,
                                     "json": encoded, "binary": binary}
                if needed:
                    required.append(exposed)
            for parameter in [*methods.get("parameters", []), *operation.get("parameters", [])]:
                if parameter["name"] == "xi-api-key":
                    continue
                add(parameter["name"].replace("-", "_"), parameter["schema"], parameter["in"], parameter.get("required", False))
                # Header spelling must remain intact on the wire.
                bindings[next(reversed(bindings))]["field"] = parameter["name"]
            body = operation.get("requestBody", {})
            content = body.get("content", {})
            content_type = next(iter(content), "")
            body_schema = content.get(content_type, {}).get("schema", {})
            resolved_body = nonnull(body_schema)
            if resolved_body.get("type") == "object" and "properties" in resolved_body:
                for field, raw in resolved_body["properties"].items():
                    add(field, raw, "body", field in resolved_body.get("required", []))
            elif content:
                add("body", body_schema, "whole_body", body.get("required", False))
            responses = {media for status, response in operation.get("responses", {}).items()
                         if status.startswith("2") for media in response.get("content", {})}
            family = groups[0]
            administrative = (method == "delete" or family in {"workspace", "service_accounts", "conversational_ai", "productions", "tokens"}
                              or (method not in {"get", "head"} and action in {"update", "share", "replicate_to_isolated_environment"}))
            effect = "administration" if administrative else "read" if method in {"get", "head", "options"} or action in {"get", "list", "search", "download", "get_audio"} else "write"
            base = INTENT.get(name) or FAMILY_GUIDANCE.get(family, "Use for the explicitly requested ElevenLabs API operation.")
            summary = " ".join(str(operation.get("description") or operation.get("summary") or action).split())
            outcome = ", ".join(sorted(responses)) or "operation acknowledgement"
            desc = f"ElevenLabs {operation.get('summary', action)}. {base} {summary[:700]}"
            required_hint = ", ".join(required) or "none"
            if name in {"music_compose", "music_stream", "music_compose_detailed", "music_compose_detailed_stream"}:
                required_hint = "exactly one of prompt OR composition_plan_json (individual fields are optional only to express this choice)"
            desc += " Required inputs: " + required_hint + f". Returns: {outcome}."
            if any(t.startswith(("audio/", "video/", "multipart/")) or "zip" in t for t in responses):
                desc += " Binary output is saved to private media storage and returned as a downloadable URL. HTTP streams are collected into completed files."
            if effect == "administration":
                desc += " Account/shared-resource action: require explicit approval, including in autonomous mode; never use as an incidental media-generation step."
            elif effect == "write":
                desc += " May consume ElevenLabs credits or change stored content; use only when the request requires this output."
            else:
                desc += " Read/retrieval operation; reuse existing outputs where possible."
            if operation.get("deprecated"):
                desc += " Deprecated upstream; prefer a current alternative when available."
            tools[name] = {"tool": {"name": name, "description": desc, "inputSchema": {"type": "object", "properties": props, "required": required}},
                           "path": path, "method": method.upper(), "bindings": bindings,
                           "body_schema": body_schema, "content_type": content_type, "effect": effect,
                           "operation_id": operation.get("operationId")}
    return tools


CATALOG = build_catalog()


def requires_approval(tool_name: str) -> bool:
    target, _, name = tool_name.partition("___")
    return target == "ElevenLabs" and CATALOG.get(name, {}).get("effect") == "administration"
