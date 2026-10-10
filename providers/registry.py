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
    "mureka": {
        "generate_song": "Music default Mureka V9.5 via fal. Use lyrics for lyrics-to-song, or prompt for prompt-to-song; prompt with lyrics supplies style. Paid audio requires approval unless autonomous. Poll get_music_task; save song_id and timed lyrics for lyrics-video. Dry-run is a preview; no training eligibility.",
        "generate_instrumental": "Music-bed default: Mureka V9.5 instrumental via fal. Exactly one of prompt or existing instrumental_id. Paid audio approval unless autonomous. Poll get_music_task with download=true; dry-run never produces audio.",
        "generate_lyrics_video": "Paid lyrics video via fal: exactly one of completed song_id or existing upload_audio_id. Song/upload IDs must belong to this transport. Layout/aspect and paired row or millisecond selection follow the schema. Always pause with cost approval, even autonomous. Poll get_video_task with download=true and verify saved MP4. No training eligibility.",
        "get_music_task": "Poll one saved Mureka music handle. Preserve song_id, duration_ms and timed lyrics_sections. download=true validates and persists completed audio; dry-run never creates artifacts.",
        "get_video_task": "Poll saved Mureka lyrics-video job via the shared fal queue. download=true validates saved MP4; no new generation. Dry-run handles stay previews.",
        "list_mureka_models": "Offline verified model and endpoint catalog; no generation or paid request.",
    },
    "topaz": {
        "upscale_video": "Finish existing video with Starlight Precise 2.6 through fal. Requires video_url and measured source_duration_seconds, source_fps, source_width and source_height. Choose target_resolution 1080p/4K or upscale_factor 1–4; default is 2x. Optional target_fps 16–60. H264_output defaults true. All paid submissions pause with cost, including autonomous runs. Unknown quotes block live submission. Default dry-run is a preview, not media. Poll get_video_task with download=true and inspect the saved MP4. Outputs are not training eligible.",
        "interpolate_video": "Finish existing video with Apollo by default; use Chronos for plain linear-motion FPS conversion unless the user names a model. Requires video_url and measured source_duration_seconds, source_fps, source_width and source_height. Choose target_fps 16–120 or fps_multiplier; default is 60 FPS. slowdown_factor 1–8 defaults 1; slow-motion prices remain unknown and live submission is blocked. All paid submissions pause with cost even in autonomous runs. Poll get_video_task with download=true. Dry-run previews are not media; outputs are not training eligible.",
        "get_video_task": "Poll the exact saved Topaz job_id once without resubmitting. download=true saves and validates the completed MP4. Dry-run handles remain previews across configuration changes. Output provenance retains Topaz and the selected model.",
        "list_topaz_models": "List verified finishing models, endpoint identifiers, service licences and documented price examples locally. Free, no credentials or network calls. Does not verify account access or live behavior.",
    },
    "heygen": {
        "create_avatar_video": "Make a presenter video using official HeyGen Avatar V and an existing eligible digital-twin look avatar_id. Require subjects, consent_confirmed=true and recorded consent_record_id for every face and voice. Supply script with voice_id or audio_url, language locale, resolution and aspect_ratio. duration_seconds is a measured audio length or script duration estimate, not a vendor render control. All paid video pauses with cost even in autonomous runs. API billing is separate from app plans; self-serve list price is $0.12/s; enterprise estimates remain unknown. Default dry-run produces no media. Live checks engine eligibility and accepted vendor consent. Poll get_video_status with download=true; completion requires the saved MP4. Outputs are not training eligible.",
        "get_video_status": "Poll the exact saved HeyGen job_id once. download=true saves completed MP4 media. Never submits another generation. Dry-run jobs stay previews even after configuration changes.",
        "list_avatars": "List one page of digital-twin looks for avatar_id discovery. Inspect supported_api_engines for avatar_v eligibility. Default dry-run returns no invented avatar IDs. No generation.",
        "list_voices": "List one page of HeyGen voice IDs and language metadata. Default dry-run returns no invented voice IDs. No generation or voice cloning.",
    },
    "sync": {
        "lipsync_video": "Put replacement audio on existing footage using sync-3 via fal by default. Requires measured video/audio durations, source fps, every face/voice subject and explicit consent_confirmed=true. Script only: create authorized ElevenLabs TTS first. All paid requests pause with a cost estimate even in autonomous runs. Large equal-length cut_off inputs require supplied silence/shot chunk boundaries plus ffmpeg and S3. Dry-run is an input preview. Poll get_video_task with download=true; never claim completion until the saved MP4 plays. No training eligibility.",
        "get_video_task": "Poll a saved Sync job or chunk manifest once; download=true persists completed MP4 media and provenance. Reuse the exact job_id, never submit another lip-sync job to check status. No paid generation. Dry-run never produces an artifact.",
    },
    "alibaba_modelstudio": {
        "edit_wan3_video": "Dry-run preview of Alibaba Model Studio Wan 3 editing. The preview licence allows only internal testing, research and evaluation, so customer live requests are blocked even with approval. Requires video_url, prompt, measured source_duration_seconds and source_fps. Default duration=-1 has unknown cost; explicit total output seconds quote input plus output. Outputs are not training eligible. A preview is not generated media.",
        "extend_wan3_video": "Dry-run preview of Alibaba Model Studio Wan 3 extension. Customer live use is blocked by its internal-evaluation preview licence, which spending approval cannot override. duration is TOTAL output length: a 5s source extended by 2s uses duration=7 and bills 12s. Default -1 has unknown cost. Uses adaptive ratio and prompt-based direction. Outputs are not training eligible.",
        "get_task": "Inspect a saved Model Studio task or dry-run handle without submitting work. Preview licensing currently blocks live task polling. In a permitted future workflow, download=true persists a completed MP4 and provenance. Reuse saved jobs instead of resubmitting; previews are not generated media.",
    },
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
        "act_two": "Performance transfer default Act-Two. Require character_uri (image/video), performance_uri, measured performance_duration_seconds 3-30, subjects and consent_confirmed=true for every face, voice and body. body_control and expression_intensity 1-5 are optional; character video requires body_control=false. Always pause with cost even autonomous. For long sources use approved shot/silence segments with source_duration_seconds, performance_start_seconds and boundary_kind; process sequentially then assemble through Remotion. Poll get_runway_task with download=true. Dry-run produces no media; outputs never enter training.",
        "text_to_video": "Create a Gen-4.5 video from text. Starts paid work unless dry-run. Poll get_runway_task with the returned job_id at least five seconds apart.",
        "image_to_video": "Animate a supplied image with Gen-4.5. Starts paid work unless dry-run. Poll get_runway_task with the returned job_id at least five seconds apart.",
        "video_to_video": "Edit an existing 2-30 second clip with Aleph 2.0 and a text instruction, optionally guided by a timed reference image. Supply the actual source duration for the cost estimate. Poll get_runway_task.",
        "text_to_image": "Create a Gen-4 image from text. Returns a queued task, not a finished image. Poll get_runway_task at least five seconds apart and save its completed image.",
        "image_to_image": "Generate a Gen-4 reference image using a source image and text instruction, optionally additional references. Returns a queued task. Poll get_runway_task and save its completed image.",
        "get_runway_task": "Poll an existing Runway job_id once. Never submit another generation to check status. Wait at least five seconds between calls. Completed media URLs expire and must be saved.",
        "list_runway_models": "List locally documented supported Runway models and limits. Free, no API request. This catalog does not verify account access or live model availability.",
    },
    "fal": {
        "pixelcut_looping_video": "Named-only Pixelcut loop from image_url. Requires an explicit Pixelcut request and named-provider skill. Optional prompt, integer duration 5-15, resolution 480p/768p/1080p, motion subtle/spin, include_audio=false. Always pause with cost, including autonomous runs. Default FAL_DRY_RUN=true previews inputs only. Poll get_video_task with download=true, then inspect the MP4 and loop seam. Outputs are not training eligible.",
        "pixverse_vibemv": "Named-only PixVerse VibeMV music video from audio_url and measured audio_duration_seconds 10-360. Requires an explicit PixVerse or VibeMV request and named-provider skill. Optional character image_url, Custom style with style_image_url, music_style, lyrics, aspect_ratio, resolution 720p/1080p, lip_sync_switch. Always pause with rounded audio-second cost, including autonomous runs. FAL_DRY_RUN defaults true. Poll get_video_task with download=true and play the saved MP4. Input music/lyrics rights and real face/voice consent required. Outputs are not training eligible.",
        "ideogram_edit": "Pixel-preserving text-only image edit exception via Ideogram 4.5; evidence is thin, compare A/B. Requires existing image_url. edit_precision=high restores unchanged pixels; mask_url is black-edit/white-preserve and requires source dimensions. At most 4 references or 3 with mask. Paid images pause unless autonomous. Poll get_video_task; every returned image persists. No training eligibility.",
        "recraft_text_to_vector": "Editable SVG/vector exception via Recraft V4.1 Pro. Describe style in prompt; optional named image_size, colors and background_color RGB palette. No style field. Paid images pause unless autonomous; provider price $0.30/image plus disclosed fee. Poll get_video_task; every SVG is content-type checked and sanitized before persistence. No training eligibility.",
        "mirelo_v2a": "Video-input SFX default Mirelo SFX 1.6 via fal. Required video_url, optional text_prompt, duration 1-60 seconds, num_samples 1-4, optional seed. Renderhaus defaults to one sample; samples 2-4 are dry-run only with cost unknown. Returns videos with generated audio tracks, not a separate audio file. Paid video requires cost approval even autonomous when premium_video_approval is enabled. Poll get_video_task with download=true and play the saved MP4. Commercial API; outputs are not training eligible.",
        "kling_motion_control": "Full-body performance transfer exception through fal Kling 3 Pro Motion Control. Require image_url, video_url, measured performance_duration_seconds 3-30, subjects and consent_confirmed=true for every face, voice and body. character_orientation defaults video; image orientation max 10s. keep_original_sound defaults true. Always pause with cost even autonomous. Poll get_video_task with download=true. Dry-run produces no media; outputs never enter training.",
        "text_to_video": "Generate a Wan VACE clip from text. Returns job_id; poll get_video_task with download=true until terminal.",
        "image_to_video": "Animate first_frame_url using Wan VACE. Returns job_id; poll get_video_task with download=true until terminal.",
        "reference_to_video": "Generate a Wan VACE clip guided by ref_image_urls for subject consistency. Returns job_id; poll get_video_task with download=true until terminal.",
        "video_to_video": "Edit video_url with Wan VACE. Choose freeform, inpainting, outpainting, reframe, depth, or pose. Inpainting needs one mask; outpainting needs expansion sides. Returns job_id; poll get_video_task with download=true until terminal.",
        "generate_wan3_t2v": "Generate Wan 3 text-to-video, 2 to 30 seconds at 480p/720p/1080p, with native audio by default. Always request approval with a cost estimate, including autonomous runs. Poll get_video_task with download=true. Closed weights and commercial hosted API; outputs are not training eligible.",
        "generate_wan3_i2v": "Animate start_image_url with Wan 3, optionally constrained by end_image_url. Real-person likeness references require real_face_refs=true and likeness_consent=true. Always request approval with cost, then poll get_video_task with download=true.",
        "generate_wan3_r2v": "Generate Wan 3 from up to 10 images, 5 videos totaling 15 seconds and 5 audio clips totaling 15 seconds. Supply measured reference_video_durations, reference_video_fps and reference_audio_durations alongside the matching URLs. Input video seconds also incur cost. Real-person likeness requires consent. Always request approval with cost, then poll get_video_task with download=true.",
        "vidu_q4_i2v": "Animate image_url with Vidu Q4 native audio at 540p through 4K for 3 to 16 seconds. Prompt is optional. Returns job_id; poll get_video_task with download=true until terminal. Hosted service terms apply; outputs are not training eligible.",
        "vidu_q4_r2v": "Generate Vidu Q4 video using an optional list of up to 12 reference images and 3 MP3 voice clips. Refer to images with [@reference_image_1] and voices with [reference_audio_1]. Audio defaults to false; set audio=true for dialogue and sound effects. Returns job_id; poll get_video_task with download=true until terminal. Outputs are not training eligible.",
        "get_video_task": "Poll an existing fal image or video job_id once. Image outputs always persist after content validation; SVGs are sanitized. download=true saves completed MP4s. Never submits another generation.",
        "list_fal_models": "List documented fal models, endpoints, licences and published pricing, including named-only Pixelcut and PixVerse VibeMV. Static catalog; no network or generation.",
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
        "text_to_video": "Submit Seedance 2.5 synthetic dialogue video through fal US-hosted endpoints by default. Paid video requires cost approval, including autonomous runs. Returns job_id; poll get_video_task with download=true until terminal. Outputs are not training eligible.",
        "image_to_video": "Animate a synthetic image with Seedance 2.5 and optional end frame. Real-person references are forbidden. A measured source_aspect_ratio is needed for a known cost estimate. Paid video requires approval; poll get_video_task for the finished MP4.",
        "reference_to_video": "Generate Seedance 2.5 synthetic-character video using up to 30 image, 10 video and 10 audio references. Require measured video durations/fps and audio durations. Real-person references are forbidden. Paid video requires approval with cost, including autonomous runs.",
        "edit_video": "Edit a synthetic source video using Seedance 2.5 via fal reference-to-video task=editing. Requires measured source duration/fps; source_aspect_ratio is needed for known cost. Source timing is preserved. Real-person inputs are forbidden. Paid video requires approval with cost, including autonomous runs.",
        "extend_video": "Continue a synthetic source clip using Seedance 2.5 via fal task=extension. Requires measured source duration/fps; source_aspect_ratio is needed for known cost. duration_seconds requests generated output duration, not a promised stitched timeline length. Real-person inputs are forbidden. Paid video requires cost approval, including autonomous runs.",
        "get_video_task": "Poll an existing Seedance task once. fal job handles reuse the fal queue poller. Never submits a generation. Call download=true after success to obtain the MP4.",
        "list_seedance_models": "List verified Seedance models, transports, and API sources offline. No credential or network request. BytePlus is unavailable to US customers and requires written platform authorization for live integration.",
    },
    "remotion": {
        "motion_carry_probe": "Free local post-render motion carry and rhythm QC for motion graphics, product demos, knowledge explainers and explicit HyperFrames films. Requires owned job_id and in-job MP4 input_path, optional exact timeline. No network or model calls. Default MOTION_CARRY_QC_DRY_RUN=true. Reports per-boundary scores, cadence, rests, audio peaks, sharp fast moves and possible subject exits with timestamps/fixes. A failed report gates delivery and requires an offered re-render. PROVISIONAL calibration; human visual review stays pending. Generative continuity uses local_qc instead.",
        "deliver_render": "Finish an existing local render or checksum matrix manifest using a named placeholder delivery preset. Uses fixed system ffmpeg ops, measured FPS/native geometry, loudness normalization and AAC faststart mux; never enlarges. Versioned campaign__sku__locale__aspect__v<n>.mp4 files never overwrite. Actual final-file QC must pass before a finished claim. Reports per-file failures verbatim. Free local worker job; Lambda refused. Respect REMOTION_DRY_RUN. Upload=true is refused; no S3/public/platform upload is available here.",
        "qc_deliverable": "Free technical QC of final local files or matrix manifest against a named preset/spec. Probes codec/profile/pix_fmt/resolution/SAR/FPS/duration/audio, decoded cadence, full black/freeze/silence intervals, loudness/true peak/clipping, faststart, size/naming/checksum, and actual frames/contact sheet. Failed or incomplete checks fail the report. Caption/price/legal pixel review is a planner vision pass, never inferred from geometry. Confined job directory, local worker only; Lambda refused. Dry-run does no media inspection.",
        "render_ad_variants": (
            "Local ad matrix from job_id, master_asset, brief and rows. Use stage=plan first, "
            "then render_first with returned plan_hash, inspect frames and expected strings, "
            "then human-approved render_batch bound to that hash. First/batch pause with count, "
            "aspects and cost even autonomous. No agent-supplied authorization. Lambda matrix "
            "orchestration is refused. Copy stays verbatim; outputs include checksum manifest."
        ),
        "import_nle_timeline": (
            "Import editor FCPXML 1.9–1.11 or OTIO JSON onto the current document/renderConfig "
            "assembly. Free, synchronous, no media retrieval or project writes. Returns a complete "
            "replacement timeline or a blocked report with unmatched/ambiguous media and unsupported "
            "edits. Match embedded asset IDs before unique filename/full source duration. "
            "Review before saving the returned assembly. EDL and AAF import are unsupported."
        ),
        "prepare_conversational_edit": (
            "Use for conversational transcript edits after proposing the cut, grade, and captions "
            "in plan_summary for required host approval. Always returns a side-effect-free dry_run "
            "preview with word-safe cuts, output-timed transcript/captions, timeline, render_arguments, "
            "and QC expectations. It never fetches media or starts a render. Use the separate paid "
            "render_timeline tool with render_arguments after preparation. Omit fps unless the user "
            "requests a timeline rate; the preview uses 30 fps while the final render measures its source."
        ),
        "render_timeline": (
            "Use after all source assets exist to execute a concrete edit decision list and make "
            "one assembled MP4. The caller must choose timing, B-roll layers, crop/motion, "
            "transitions, speed, titles, and audio fades, then poll get_render_progress. "
            "Sources may use url or output_path (a local provider result, no file:// prefix). "
            "Omit fps to preserve the primary video's measured frame rate; set it only for a "
            "user-requested timeline rate. Source metadata is measured before rendering: local media, "
            "fal.media subdomains, configured S3 bucket hosts, or REMOTION_LOCAL_MEDIA_HOSTS. "
            "Optional source_fps/source_bitrate carry prior measurements. video_bitrate is a target in bits/s with a source "
            "quality floor; automatic bitrate does not exceed the measured source maximum on smaller canvases, "
            "and unknown bitrate uses high-quality CRF18. Omit output_resolution to use the largest measured "
            "video short edge, capped at the aspect table. Explicit 720p/1080p/1440p/2160p scale that table; "
            "images-only or no measured video dimensions use the table. Results include width, height, source_resolution, "
            "upscaled, and warnings, including enlargement from fit, clip scale, and motion. "
            "Upscaling adds no detail; use the Topaz upscale skill before assembly for added detail. "
            "Local development selects REMOTION_RENDER_BACKEND=local; Lambda remains the default. "
            "Local assembly supports trims, fit, fades, timing, opacity, speed, audio mixing, "
            "allow-listed fitted text and positioned/scaled overlays. Motion, video grade and rotation "
            "require Lambda. New font/box props require overlay contract version 2 on Lambda; "
            "otherwise use the local backend or return the explicit unsupported-backend refusal."
        ),
        "get_render_progress": (
            "Use only after render_timeline returned a render id and bucket name (local sentinel for local). Poll once per call "
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
    if schema.get("name") == "render_timeline":
        for field in ("visuals", "audio_tracks"):
            for clip in args.get(field) or []:
                clip["url"] = "ci-smoke"
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
