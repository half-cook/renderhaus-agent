"""Offline intent proposals and shared provider policy at the Gateway boundary."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict, replace, field
from pathlib import Path

POLICY = json.loads(Path(__file__).with_name("routing_policy.json").read_text())
TOOL_MAP = POLICY["tools"]
TARGET_PROVIDERS = {
    "Sync": "sync",
    "OpenAI": "openai_images",
    "Kling": "kling",
    "Runway": "runway",
    "Fal": "fal",
    "Seedance": "seedance",
    "Seedream": "seedream",
    "ElevenLabs": "elevenlabs",
    "Remotion": "remotion",
    "HyperFrames": "hyperframes",
    "FishAudio": "fish_audio",
    "FishAudioProvider": "fish_audio",
    "Fish_Audio": "fish_audio",
    "Veo": "veo",
    "Luma": "luma",
    "ModelStudio": "alibaba_modelstudio",
    "MiniMaxH3": "minimax_h3",
    "MiniMax": "minimax_h3",
    "Hunyuan": "hunyuan",
}


@dataclass(frozen=True)
class Route:
    skill: str | None = None
    tool: str | None = None
    dispatch_tool: str | None = None
    status: str = "unrouted"
    reason: str = "No media intent matched; ask or plan before dispatch."
    provider: str | None = None
    model: str | None = None
    alias: str | None = None
    basis: str = ""
    job_type: str | None = None
    required: dict = field(default_factory=dict)
    estimated_cost: dict | None = None
    disclosure: str = ""
    steps: tuple[Route, ...] = ()
    expected_output: str | None = None
    forbidden_tools: tuple[str, ...] = ()

    def public(self):
        payload = asdict(self)
        payload.pop("forbidden_tools")
        payload["steps"] = [step.public() for step in self.steps]
        return payload


_VIDEO_DELIVERABLE = r"\b(?:shots?|clips?|videos?|mp4)\b"
_VOICEOVER = r"\b(?:voice[ -]?over|narration|narrate|vo)\b"
_IMAGE_ALIASES = ("gpt_image25_t2i", "gpt_image25_edit", "recraft_v41_vector", "ideogram45_edit", "seedream_t2i")
_LIPSYNC_REQUEST = next(rule["pattern"] for rule in POLICY["rules"] if rule.get("capability") == "lipsync")


@dataclass(frozen=True)
class DeliverableDuration:
    seconds: int | float
    phrase: str


def deliverable_duration(prompt: str) -> DeliverableDuration | None:
    """Parse a deliverable length, excluding placement and onset times."""
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "seven": 7, "eight": 8, "nine": 9, "ten": 10, "thirty": 30, "sixty": 60}
    number = r"\d+(?:\.\d+)?|" + "|".join(words)
    pattern = rf"\b({number})[ -]*(seconds?|secs?|s|minutes?|mins?|m)\b"
    deliverable = r"(?:shot|clip|video|mp4|presenter|avatar|animation|film|trailer)"
    for match in re.finditer(pattern, prompt, re.I):
        before, after = prompt[:match.start()], prompt[match.end():]
        if re.search(r"\b(?:at|around|starting|start|after|before|from|offset|delay)(?:\s+(?:around|about|approximately|at))?\s*$", before, re.I):
            continue
        describes = re.match(rf"[ -]*(?:[\w-]+\s+){{0,4}}{deliverable}\b", after, re.I)
        describes = describes or re.search(rf"\b{deliverable}\b[^.;:!?]{{0,50}}\b(?:lasting|length(?: of)?|duration(?: of)?|for|long|is)\s*$", before, re.I)
        if not describes:
            continue
        value = words.get(match[1].lower())
        seconds = float(value if value is not None else match[1]) * (60 if match[2].lower().startswith('m') else 1)
        return DeliverableDuration(int(seconds) if seconds.is_integer() else seconds, match[0])
    return None


def _video_voiceover(prompt: str) -> bool:
    return bool(re.search(_VIDEO_DELIVERABLE, prompt, re.I) and re.search(_VOICEOVER, prompt, re.I))


def request_tool_blocker(prompt: str, name: str) -> str | None:
    if _video_voiceover(prompt) and job_type(name) in {"still_image", "image_edit"}:
        return "A shot or clip with voiceover uses video, TTS and assembly; image tools are excluded."
    if name.startswith("Seedream___") and not re.search(r"\bseedream\b", prompt, re.I):
        return "Seedream is explicit-only; request it by name. GPT Image 2.5 is the still-image default."
    return None


def filter_request_tools(prompt: str, names: set[str]) -> set[str]:
    return {name for name in names if request_tool_blocker(prompt, name) is None}



def capability_constraints(constraints: dict, capability: str) -> dict:
    scoped = dict(constraints)
    if capability == "lipsync" and scoped.get("provider") in {"elevenlabs", "fish_audio"}:
        scoped["provider"] = next((candidate for candidate in scoped["provider_candidates"]
                                   if capability in POLICY["explicit_routes"].get(candidate, {})), None)
        scoped["model"] = scoped["named_model"] = None
    if not constraints["predicates"].get("video_voiceover"):
        return scoped
    named = scoped.get("named_model")
    if named and capability not in POLICY["named_models"][named]["aliases"]:
        scoped["named_model"] = None
    if capability not in POLICY["explicit_routes"].get(scoped.get("provider"), {}):
        scoped["provider"] = next((candidate for candidate in scoped["provider_candidates"]
                                   if capability in POLICY["explicit_routes"].get(candidate, {})), None)
        scoped["model"] = None
    return scoped


def _video_capability(prompt: str, constraints: dict) -> tuple[str, str]:
    if re.search(r"\brefs\b|reference[ -]to[ -]video|multi.ref|\br2v\b", prompt, re.I):
        return "reference_video", "i2v"
    if (constraints["predicates"]["real_face_refs"] or constraints["required"].get("start_end_frame")
            or re.search(r"animat|image[ -]to[ -]video|\bi2v\b|\bstart frame\b|(?:from|using).*\b(?:image|photo|still)\b", prompt, re.I)):
        return "i2v", "i2v"
    return "t2v", "t2v"


def _delivery_route(prompt: str, constraints: dict, *, region: str | None,
                    available_tools: set[str] | None, arguments: dict | None) -> Route | None:
    voiceover = _video_voiceover(prompt)
    mp4_export = bool(re.search(r"(?:assemble|render|export|final).*\bmp4\b|assemble.*(?:video|clip)", prompt, re.I))
    if not voiceover and not mp4_export:
        return None
    if re.search(r"whiteboard|hyperframes|remotion|\botio\b|\bfcpxml\b|\bedl\b|(?:still|image).*animat", prompt, re.I):
        return None
    steps = []
    creates = bool(re.search(r"\b(?:make|create|generate)\b.*\b(?:shot|clip|video)\b", prompt, re.I))
    existing = bool(re.search(r"\b(?:referenced|existing|attached|uploaded)\b.*\b(?:clip|video|shot)\b", prompt, re.I))
    for capability, skill in ([_video_capability(prompt, constraints)] if creates and not existing else []) + ([('tts', 'audio-bed')] if voiceover else []) + [('motion_graphics', 'final-assembly')]:
        scoped = capability_constraints(constraints, capability)
        route = select_provider(capability, region=region, available_tools=available_tools,
                                arguments=arguments, **scoped)
        steps.append(replace(route, skill=skill))
    first = steps[0]
    incomplete = next((step for step in steps if step.status != 'ready'), None)
    return replace(first, steps=tuple(steps), expected_output='assembled MP4',
                   forbidden_tools=_IMAGE_ALIASES if voiceover else (),
                   status=incomplete.status if incomplete else first.status,
                   reason=incomplete.reason if incomplete else 'Generate video if needed, synthesize voiceover, then assemble the final MP4.')


def _licence_interim(alias: str) -> str | None:
    entry = TOOL_MAP.get(alias, {})
    policy = POLICY["providers"].get(entry.get("provider"), {})
    model = entry.get("model")
    if entry.get("gateway_tool") and entry.get("provider"):
        model = effective_model(entry["provider"], entry["gateway_tool"].split("___")[1], {})
    model_policy = policy.get("model_policies", {}).get(model, {})
    if model_policy.get("live_enabled") is not False:
        return None
    return next((row["interim"] for row in POLICY["capability_map"].values()
                 if row["default"] == alias), None)


def resolve_alias(alias: str) -> str | None:
    """Resolve a canonical choice through its declared interim, never a provider ladder."""
    entry = TOOL_MAP.get(alias, {})
    if entry.get("status") == "ready":
        if interim := _licence_interim(alias):
            return TOOL_MAP.get(interim, {}).get("gateway_tool")
        return entry.get("gateway_tool")
    if entry.get("status") != "pending":
        return None
    interim = entry.get("interim_alias")
    if interim is None:
        interim = next((row["interim"] for row in POLICY["capability_map"].values()
                        if row["default"] == alias), None)
    return TOOL_MAP.get(interim, {}).get("gateway_tool") if interim else None


def route_intent(prompt: str, *, region: str | None = None, tier: str | None = None,
                 confidential: bool = False, arguments: dict | None = None,
                 available_tools: set[str] | None = None, retry: bool = False) -> Route:
    constraints = intent_constraints(prompt, tier=tier, confidential=confidential, arguments=arguments)
    for pattern, alias in POLICY["retired_requests"].items():
        if re.search(pattern, prompt, re.I):
            return Route(alias=alias, status="retired", reason=TOOL_MAP[alias]["reason"],
                         disclosure=TOOL_MAP[alias]["reason"])
    lipsync = bool(re.search(_LIPSYNC_REQUEST, prompt, re.I))
    delivery = None if lipsync else _delivery_route(prompt, constraints, region=region, available_tools=available_tools, arguments=arguments)
    if delivery is not None:
        return delivery
    for rule in POLICY["rules"]:
        if not re.search(rule["pattern"], prompt, re.IGNORECASE):
            continue
        skill, alias = rule["skill"], rule["abstract_tool"]
        capability = rule.get("capability")
        if capability == "lipsync" and re.search(r"\b(?:tts|elevenlabs)\b.*\b(?:then|first)\b", prompt, re.I):
            continue
        if capability == "lipsync" and not constraints["provider"]:
            existing = ((arguments or {}).get("video_url") or (arguments or {}).get("source_video_url")
                        or re.search(r"footage|(?:existing|attached|uploaded|this|the)\s+(?:interview\s+)?(?:clip|video)", prompt, re.I))
            from_still = re.search(r"(?:from|using|with).*\b(?:image|photo|still)\b", prompt, re.I)
            generated = re.search(
                r"\b(?:generate|create|make)\b.*\b(?:talking|speaking)\b|"
                r"(?:cartoon|synthetic|fictional|foxes|mascot|illustrated).*(?:talk|say|dialogue|speak)", prompt, re.I,
            )
            if not existing and (from_still or generated):
                capability = "i2v" if from_still else "t2v"
                skill = capability
        if capability == "t2v" and re.search(r"\brefs\b|reference[ -]to[ -]video|multi.ref", prompt, re.I):
            capability, skill = "reference_video", "i2v"
        elif capability == "t2v" and re.search(r"animat|(?:image|photo|still).*(?:talk|speak)", prompt, re.I):
            capability, skill = "i2v", "i2v"
        if skill == "hyperframes":
            blocker = policy_blocker("HyperFrames___render_composition", {}, region=region)
            if available_tools is not None and "HyperFrames___render_composition" not in available_tools:
                blocker = "Requested HyperFrames renderer tool is unavailable in this session."
            if blocker:
                return Route(skill=skill, status="blocked", reason=blocker, disclosure=blocker)
        if constraints["predicates"]["real_face_refs"] and capability == "t2v":
            capability, skill = "i2v", "i2v"
        if capability == "t2v" and constraints["required"].get("start_end_frame"):
            capability, skill = "i2v", "i2v"
        if capability:
            scoped = capability_constraints(constraints, capability) if capability == "lipsync" else constraints
            route = select_provider(capability, arguments=arguments, available_tools=available_tools,
                                    region=region, retry=retry, **scoped)
            if constraints["provider"] in {"kling", "runway", "luma", "seedream", "fish_audio"} or (
                constraints["provider"] == "fal" and re.search(r"vidu|vace", prompt, re.I)
            ):
                skill = "named-provider"
            return replace(route, skill=skill)
        entry = TOOL_MAP[alias]
        if entry["status"] != "ready":
            return Route(skill=skill, alias=alias, status=entry["status"], reason=entry["reason"], disclosure=entry["reason"])
        tool = entry.get("gateway_tool")
        blocker = policy_blocker(tool, {}, region=region) if tool else None
        if available_tools is not None and tool and tool not in available_tools:
            blocker = f"Requested tool {tool} is unavailable in this session."
        if blocker:
            return Route(skill=skill, status="blocked", reason=blocker, disclosure=blocker)
        return Route(skill=skill, alias=alias, tool=tool, dispatch_tool=_dispatch(tool), status="ready",
                     reason="Read the selected skill, then discover the exact schema.", basis="default")
    return Route()


def _dispatch(tool: str | None) -> str | None:
    if not tool:
        return None
    if tool.startswith(("Remotion___", "HyperFrames___")):
        return "call_editor_tool"
    if tool.startswith(("ElevenLabs___", "FishAudio___")):
        return "call_audio_tool"
    return "call_media_tool"


def job_type(name: str | None) -> str | None:
    if name and name.endswith(("reference_to_video", "vidu_q4_r2v")):
        return "reference_video"
    for row in POLICY["capabilities"]:
        for job, tool in row["tools"].items():
            if tool == name:
                return {"image_edit": "image_edit", "reference": "reference_video", "image": "still_image"}.get(job, job)
    for capability, choice in POLICY["capability_map"].items():
        aliases = [choice["default"], choice["interim"]] + [ex["tool"] for ex in choice["exceptions"]]
        if any(alias and name in [TOOL_MAP.get(alias, {}).get("gateway_tool"), *TOOL_MAP.get(alias, {}).get("gateway_variants", [])] for alias in aliases):
            return capability
    if name == "FishAudio___generate_speech":
        return "tts"
    return None


def tool_variant(name: str) -> str | None:
    if any(name in entry.get("gateway_variants", []) for entry in TOOL_MAP.values()):
        return name
    if name.endswith(("reference_to_video", "vidu_q4_r2v")):
        return "reference"
    return {"still_image": "image"}.get(job_type(name), job_type(name))


def capability_table() -> list[dict]:
    rows = []
    for row in POLICY["capabilities"]:
        policy = POLICY["providers"][row["policy_ref"]]
        model_policy = policy.get("model_policies", {}).get(row["model"], {})
        rows.append({**row, "enabled": bool(policy["enabled"] and model_policy.get("enabled", True)),
                     "license": model_policy.get("license", policy["license"]),
                     "training_eligible": bool(policy["training_eligible"] and
                                               model_policy.get("training_eligible", False)),
                     "allowed_regions": policy["allowed_regions"],
                     "blocked_regions": policy.get("blocked_regions", []),
                     "model_allowed_regions": model_policy.get("allowed_regions", []),
                     "model_blocked_regions": model_policy.get("blocked_regions", []),
                     "price": _capability_price(row)})
    return rows


def _capability_price(row: dict):
    from server import billing_rates as rates

    price = row["price"]
    if price == "unknown":
        return price
    provider, model = row["provider"], row["model"]
    if provider == "fal":
        if model.startswith("alibaba/wan-3.0/"):
            values = {resolution: str(value) for resolution, value in rates.WAN3_CENTS_PER_SECOND.items()}
        elif model.startswith("fal-ai/vidu/q4/"):
            values = {resolution: str(value) for resolution, value in rates.vidu_q4_rates().items()}
        else:
            from providers.fal.wan import endpoint_for
            values = {}
            for mode in ("freeform", "depth", "pose", "inpainting", "outpainting", "reframe"):
                endpoint = endpoint_for("video_to_video", {"model": model, "edit_mode": mode})
                values[mode] = {resolution: str(value) for resolution, value in
                                (endpoint.price_cents_per_video_second or {}).items()} or "unknown"
    elif provider == "kling":
        values = {"audio" if audio else "silent": dict(table) for (rate_model, audio), table in
                  rates.KLING_RATES_USD_PER_SECOND.items() if rate_model == model}
    elif provider == "runway":
        values = rates.RUNWAY_IMAGE_CENTS.get(model, rates.RUNWAY_CENTS_PER_SECOND.get(model))
    elif provider == "seedance":
        values = {"fal_usd_per_million_tokens": {region: {resolution: str(rate) for resolution, rate in table.items()}
                                               for region, table in rates.SEEDANCE_FAL_USD_PER_M_TOKENS.items()},
                  "byteplus_usd_per_million_tokens": {str(video): {resolution: str(rate) for resolution, rate in table.items()}
                                                    for video, table in rates.SEEDANCE_BYTEPLUS_USD_PER_M_TOKENS.items()},
                  "fps": rates.SEEDANCE_FPS, "formula": "width * height * fps * duration / 1024"}
    elif provider == "seedream":
        values = {"1K": rates.SEEDREAM_COST_CENTS_BY_SIZE["1K"], "2K": "unknown", "3K": "unknown"}
    elif provider == "luma":
        values = {"generation": rates.LUMA_GENERATION_CENTS, "modify": rates.LUMA_EDIT_CENTS,
                  "extend": rates.LUMA_EXTEND_CENTS}
    elif provider == "alibaba_modelstudio":
        values = {region: {resolution: str(value) for resolution, value in table.items()}
                  for region, table in rates.MODELSTUDIO_CENTS_PER_SECOND.items()}
    elif provider == "sync":
        values = {"fal_cents_per_minute": str(rates.SYNC_FAL_CENTS_PER_MINUTE),
                  "direct_legacy_base_cents_per_second_at_25fps": str(rates.SYNC_DIRECT_BASE_CENTS_PER_SECOND_25FPS)}
    else:
        return "unknown"
    return {**price, "rates": values,
            "currency_unit": "USD/second" if provider == "kling" else "provider cents",
            "fee": "server.billing_rates._with_fee"}


def intent_constraints(prompt: str, *, tier: str | None = None, confidential: bool = False,
                       arguments: dict | None = None) -> dict:
    args = arguments or {}
    provider_candidates = [p for pattern, p in [
        (r"\bvidu\b|\bvace\b|\bfal\b|\bwan[ -]?2", "fal"), (r"\bseedance\b", "seedance"),
        (r"\bseedream\b", "seedream"), (r"\bkling\b", "kling"),
        (r"\bopenai\b|gpt[ -]image", "openai_images"),
        (r"\brunway\b|\baleph\b|gen.?4", "runway"), (r"\bluma\b|\bray.?3\b", "luma"),
        (r"\bfish\b", "fish_audio"), (r"\belevenlabs\b", "elevenlabs"),
        (r"\bsync[ -]?3\b|sync\.so|\b(?:use|using|via)\s+sync\b", "sync"),
        (r"model[ -]?studio|dashscope|alibaba", "alibaba_modelstudio"),
        (r"mini.?max", "minimax_h3"), (r"hunyuan", "hunyuan"),
    ] if re.search(pattern, prompt, re.I)]
    provider = next(iter(provider_candidates), None)
    required = {}
    for feature, pattern in {
        "native_audio": r"native audio|with audio|needs? audio",
        "start_end_frame": r"end frame|last frame|start.end.frame|first.*last frame",
        "multi_shot": r"multi.shot",
        "reference_elements": r"reference elements|element library|multi.ref|ref(?:erence)?[ -]to[ -]video|image ref(?:erences?)?",
        "voice_references": r"voice (?:clips?|ref(?:erences?)?)|audio ref(?:erences?)?",
    }.items():
        if re.search(pattern, prompt, re.I):
            required[feature] = True
    resolution = re.search(r"\b(480p|540p|580p|720p|1080p|2k|4k)\b", prompt, re.I)
    if resolution:
        required["max_resolution"] = resolution_value(resolution[1])
    duration = deliverable_duration(prompt)
    seconds = duration.seconds if duration else None
    if seconds is not None:
        required["duration_seconds"] = seconds
    extension = re.search(r"(?:extend|continue).*\bby\s+(\d+(?:\.\d+)?)\s*(seconds?|secs?|s)\b", prompt, re.I)
    if extension:
        added = float(extension[1])
        required["extension_seconds"] = int(added) if added.is_integer() else added
    supplied_duration = next((args[k] for k in ("duration", "duration_seconds", "video_duration_seconds", "source_duration_seconds") if args.get(k) is not None), seconds)
    real_face = bool(args.get("real_face_refs") or args.get("user_supplied_real_person_refs") or re.search(
        r"real[ -](?:person|human|actor)|my (?:ceo|face|selfie)|(?:photo|video).*(?:of me|of my|real person)|(?:user.supplied|uploaded).*(?:person|face)", prompt, re.I))
    dialogue_prompt = re.sub(r"(?:voice[ -]?over|narration|\bvo\b)\s*:?\s*[\'\"“].*?[\'\"”]", "", prompt, flags=re.I)
    dialogue = bool(re.search(r'["“][^"”]+["”]|\b(?:says?|saying|talking|talks?|dialogue|speaking)\b', dialogue_prompt, re.I))
    if re.search(r"\b(?:no|without) dialogue\b|\bnot talking\b|silent scene", prompt, re.I):
        dialogue = False
    video_sfx = bool(args.get("video_url") or args.get("source_video_url") or re.search(r"from (?:the|this).*?(?:video|clip)|video to audio|foley|synchroni[sz]ed|silent clip|picture.synced", prompt, re.I))
    if re.search(r"no video|without video", prompt, re.I):
        video_sfx = False
    predicates = {
        "dialogue": dialogue, "real_face_refs": real_face,
        "video_voiceover": _video_voiceover(prompt),
        "vector_output": bool(re.search(r"\bsvg\b|vector|editable.*illustrator", prompt, re.I)),
        "text_only_edit": bool(re.search(r"(?:change|replace).*only.*(?:text|headline)|fix.*typo|text.only.*edit", prompt, re.I)),
        "full_body_motion": bool(re.search(r"full.body|whole.body|\bdance\b|\bdancing\b", prompt, re.I)),
        "facial_performance": bool(re.search(r"facial|face.*acting|upper.body", prompt, re.I)),
        "duration_over_30s": isinstance(supplied_duration, (int, float)) and supplied_duration > 30,
        "presenter": bool(re.search(r"presenter|digital twin", prompt, re.I)),
        "text_only_sfx": not video_sfx,
        "explicit_html_template": bool(re.search(r"hyperframes|html.*template", prompt, re.I)),
        "linear_fps": bool(re.search(r"linear|simple pan", prompt, re.I)),
    }
    predicates.update({k: bool(args[k]) for k in predicates if k in args})
    predicates["real_face_refs"] = real_face
    model = None
    if provider == "fal":
        if re.search(r"vidu", prompt, re.I):
            reference = required.get("reference_elements") or required.get("voice_references") or args.get("reference_image_urls") or args.get("reference_audio_urls")
            model = POLICY["providers"]["fal"]["default_models"]["vidu_q4_r2v" if reference else "vidu_q4_i2v"]
        elif re.search(r"vace|\bwan[ -]?2", prompt, re.I):
            model = "fal-ai/wan-22-vace-fun-a14b" if re.search(r"wan[ -]?2\.2", prompt, re.I) else POLICY["providers"]["fal"]["default_model"]
    if re.search(r"kling.*(?:turbo|omni)", prompt, re.I):
        model = "kling-3.0-omni" if re.search("omni", prompt, re.I) else "kling-3.0-turbo"
    named_model = next((key for key, entry in POLICY["named_models"].items()
                        if re.search(entry["pattern"], prompt, re.I)), None)
    return {"provider": provider, "model": model, "named_model": named_model,
            "provider_candidates": provider_candidates, "required": required, "predicates": predicates}


def resolution_value(value: str) -> int:
    if "x" in value:
        parts = value.split("x")
        return max(int(part) for part in parts) if len(parts) == 2 and all(part.isdigit() for part in parts) else 0
    if ":" in value:
        parts = value.split(":")
        return min(int(part) for part in parts) if len(parts) == 2 and all(part.isdigit() for part in parts) else 0
    return {"4k": 2160, "1k": 1024, "2k": 2048, "3k": 3072}.get(
        value.lower(), int(value[:-1]) if value.lower().endswith("p") and value[:-1].isdigit() else 0,
    )


def _matches(when: str, predicates: dict) -> bool:
    return all(not predicates.get(term[1:], False) if term.startswith("!") else predicates.get(term, False)
               for term in when.split(" && "))


def select_provider(job: str, *, tier: str | None = None, required: dict | None = None,
                    arguments: dict | None = None, provider: str | None = None,
                    model: str | None = None, confidential: bool = False, retry: bool = False,
                    faithful: bool = False, region: str | None = None,
                    available_tools: set[str] | None = None, tool_variant: str | None = None,
                    predicates: dict | None = None, named_model: str | None = None,
                    provider_candidates: list[str] | None = None) -> Route:
    args, required = dict(arguments or {}), dict(required or {})
    detected = intent_constraints("", arguments=args)["predicates"]
    predicates = {**detected, **(predicates or {})}
    predicates["real_face_refs"] = detected["real_face_refs"] or predicates["real_face_refs"]
    capability = {"image": "still_image", "reference": "reference_video"}.get(job, job)
    if tool_variant in {"reference", "reference_video"}:
        capability = "reference_video"
    elif tool_variant == "image_edit":
        capability = "image_edit"
    if capability in {"still_image", "image_edit"} and predicates.get("video_voiceover"):
        reason = "A shot or clip with voiceover excludes image tools; use video, TTS and assembly."
        return Route(status="blocked", job_type=capability, reason=reason, disclosure=reason)
    if capability in {"tts", "voice_clone", "music", "sfx", "motion_graphics", "nle_handoff"}:
        required = {}
        if capability in {"motion_graphics", "nle_handoff"}:
            provider = model = named_model = None
    if capability not in POLICY["capability_map"]:
        return Route(status="blocked", reason=f"No capability map for {capability}.")
    choice = POLICY["capability_map"][capability]
    if provider and capability not in POLICY["explicit_routes"].get(provider, {}):
        provider = next((p for p in provider_candidates or []
                         if capability in POLICY["explicit_routes"].get(p, {})), provider)
    if named_model and capability not in POLICY["named_models"][named_model]["aliases"] and provider:
        named_model = None
    alias, basis = choice["default"], "default"
    if retry and capability in {"t2v", "i2v", "v2v_edit", "reference_video"}:
        alias = {"t2v": "wan_t2v", "i2v": "wan_i2v", "v2v_edit": "wan_vace_edit", "reference_video": "wan_reference"}[capability]
        model, basis = POLICY["providers"]["fal"]["default_model"], "training retry after artifact rejection"
    elif predicates["real_face_refs"] and capability in {"t2v", "i2v", "reference_video"}:
        alias, basis = choice["default"], "default; real-face references require Wan; Seedance and Omni blocked"
    elif named_model:
        alias = POLICY["named_models"][named_model]["aliases"].get(capability)
        if not alias:
            reason = f"Requested model {named_model} has no {capability} tool."
            return Route(status="blocked", reason=reason, disclosure=reason)
        model, basis = None, "explicit request"
    elif provider or model:
        if provider in {"minimax_h3", "hunyuan"}:
            return Route(status="blocked", reason=f"Provider {provider} is blocked.", disclosure=f"Provider {provider} is blocked.")
        aliases = POLICY["explicit_routes"].get(provider, {})
        alias = aliases.get(capability)
        if provider == "fal" and model and "vidu" in model:
            alias = "vidu_q4_r2v" if "reference" in model else "vidu_q4_i2v"
        elif provider == "fal" and model in {"fal-ai/wan-vace-14b", "fal-ai/wan-22-vace-fun-a14b"}:
            alias = {"t2v": "wan_t2v", "i2v": "wan_i2v", "reference_video": "wan_reference",
                     "v2v_edit": "wan_vace_edit"}.get(capability)
        if provider == "kling" and model == "kling-3.0-omni":
            alias = "kling_omni"
        if not alias:
            return Route(status="blocked", job_type=capability, reason=f"Requested provider {provider} has no built {capability} tool.")
        basis = f"explicit request; not the default for {capability}"
    else:
        exception = next((ex for ex in choice["exceptions"] if _matches(ex["when"], predicates)), None)
        if exception:
            alias, basis = exception["tool"], "exception: " + exception["reason"]
    entry = TOOL_MAP[alias]
    if basis == "default" and not provider and not model and not named_model:
        if interim := _licence_interim(alias):
            entry = TOOL_MAP[interim]
            basis = f"interim for {alias}; default is commercially licence-blocked"
    if entry.get("provider") == "seedance":
        if predicates["real_face_refs"]:
            reason = "Seedance prohibits real-person photo/video references. Wan edit/extend remains preview licence-blocked; no permitted automatic route is configured."
            return Route(alias=alias, basis=basis, status="blocked", job_type=capability,
                         reason=reason, disclosure=reason)
        if named_model == "seedance15":
            args["model"] = entry["model"]
        elif model is not None:
            args.setdefault("model", model)
        try:
            model = effective_model("seedance", entry["gateway_tool"].split("___")[1], args)
        except ValueError as exc:
            reason = str(exc)
            return Route(alias=alias, basis=basis, status="blocked", job_type=capability,
                         reason=reason, disclosure=reason)
    if entry.get("provider") == "seedance" and capability == "extend" and "extension_seconds" in required:
        reason = "Seedance appended-versus-combined extension semantics are UNVERIFIED. Specify a generated output duration of 4-30 seconds instead of an extension increment."
        return Route(alias=alias, basis=basis, status="blocked", job_type=capability,
                     reason=reason, disclosure=reason)
    if entry.get("provider") == "alibaba_modelstudio" and capability == "extend" and "extension_seconds" in required:
        source = args.get("source_duration_seconds")
        if isinstance(source, (int, float)) and not isinstance(source, bool):
            target = source + required["extension_seconds"]
            required["duration_seconds"] = int(target) if float(target).is_integer() else target
        else:
            required.pop("duration_seconds", None)
    if entry.get("provider") == "alibaba_modelstudio":
        if model is None:
            model = effective_model("alibaba_modelstudio", entry["gateway_tool"].split("___")[1], args)
    duration = required.get("duration_seconds") or next((args[k] for k in ("duration", "duration_seconds", "video_duration_seconds", "source_duration_seconds") if args.get(k) is not None), None)
    if entry.get("provider") == "alibaba_modelstudio" and not required.get("duration_seconds"):
        duration = args.get("duration")
    if (predicates["duration_over_30s"] or isinstance(duration, (int, float)) and duration > 30) and capability in {"t2v", "i2v", "reference_video", "performance_transfer"}:
        reason = "Duration exceeds 30 seconds; split into shots of at most 30 seconds before generation."
        return Route(alias=alias, basis=basis, status="blocked", job_type=capability, reason=reason, disclosure=reason)
    tool = entry.get("gateway_tool")
    if entry["status"] == "pending":
        interim = None if named_model else entry.get("interim_alias") or (choice["interim"] if alias == choice["default"] and not provider else None)
        if predicates["real_face_refs"] and capability in {"t2v", "i2v", "reference_video"}:
            interim = None
        if not interim:
            reason = entry["reason"]
            return Route(alias=alias, basis=basis, status="pending", reason=reason, job_type=capability,
                         provider=entry.get("provider"), model=entry.get("model"), required=required,
                         estimated_cost=CostEstimate(None, "Provider pending; official quote TODO.").public(),
                         disclosure=f"{basis}. {reason} Estimated cost unknown.")
        entry = TOOL_MAP[interim]
        tool = entry["gateway_tool"]
        basis = (basis + "; " if basis != "default" else "") + f"interim default until {alias} lands"
    if tool_variant in entry.get("gateway_variants", []):
        tool = tool_variant
    variant = {"still_image": "image", "reference_video": "reference"}.get(capability, capability)
    row = next((r for r in capability_table() if tool in r["tools"].values() and (model is None or r["model"] == model)), None)
    if model and row is None and any(tool in r["tools"].values() for r in POLICY["capabilities"]):
        return Route(alias=alias, status="blocked", reason=f"Model {model} does not support the selected tool.")
    if row:
        model = row["model"]
        for key, feature in [("generate_audio", "native_audio"), ("audio", "native_audio"), ("multi_shot", "multi_shot"),
                             ("shots", "multi_shot"), ("elements", "reference_elements"), ("reference_image_urls", "reference_elements"),
                             ("ref_image_urls", "reference_elements"), ("reference_video_urls", "reference_elements"),
                             ("reference_audio_urls", "voice_references"),
                             ("end_image_url", "start_end_frame"),
                             ("last_frame_url", "start_end_frame"), ("end_image_path_or_url", "start_end_frame"), ("last_frame_path_or_url", "start_end_frame")]:
            if args.get(key):
                required[feature] = True
        if required.get("voice_references"):
            required["native_audio"] = True
        resolution = args.get("resolution") or args.get("size") or args.get("ratio")
        if resolution:
            required["max_resolution"] = max(required.get("max_resolution", 0), resolution_value(resolution))
        if capability == "still_image" and not resolution and not provider:
            required["max_resolution"] = max(required.get("max_resolution", 0), resolution_value(POLICY["image_default_size"]))
        if capability == "v2v_edit":
            required.pop("multi_shot", None)
        controls = row["controls"].get(variant, [])
        limits = row["durations"].get(variant)
        values = row.get("duration_values", {}).get(variant)
        unsupported = any(row["jobs"].get(k, False) < value for k, value in required.items()
                          if k not in {"duration_seconds", "extension_seconds"})
        unsupported |= duration is not None and limits is not None and not limits[0] <= duration <= limits[1]
        unsupported |= bool(duration is not None and values and duration not in values)
        unsupported |= bool(row.get("duration_field") and duration is not None and type(duration) is not int)
        unsupported |= any(args.get(k) and resolution_value(args[k]) not in row["resolutions"] for k in ("resolution", "size") if k in controls and args.get(k) != "auto"
                           and not (row["provider"] == "openai_images" and k == "size"))
        audio_field = row.get("native_audio_field", "generate_audio")
        unsupported |= bool(required.get("native_audio") and audio_field is not None and audio_field not in controls)
        unsupported |= bool(required.get("start_end_frame") and not any(k in controls for k in ("last_frame_url", "end_image_url", "end_image_path_or_url", "last_frame_path_or_url")))
        unsupported |= bool(required.get("reference_elements") and not any(k in controls for k in ("elements", "ref_image_urls", "reference_image_urls", "reference_video_urls")))
        unsupported |= bool(required.get("voice_references") and "reference_audio_urls" not in controls)
        if row.get("frame_limits"):
            fps = args.get("frames_per_second", 16)
            frames = args.get("num_frames", round(duration * fps) + 1 if duration else 81)
            unsupported |= any(not low <= val <= high for val, (low, high) in ((fps, row["frame_limits"]["frames_per_second"]), (frames, row["frame_limits"]["num_frames"])))
        if unsupported:
            reason = f"{basis}. Selected {tool} cannot satisfy {capability} required capabilities {required}; no automatic provider fallback."
            return Route(alias=alias, basis=basis, status="blocked", job_type=capability, required=required, reason=reason, disclosure=reason)
        quote_args = {**args, "model": model}
        if duration and row["provider"] != "sync":
            key = row.get("duration_field") or ("source_duration_seconds" if row["provider"] == "sync" or tool.endswith("modify_video") else "video_duration_seconds" if tool.endswith("video_to_video") and row["provider"] == "runway" else "duration_seconds")
            if row["provider"] == "fal" and not row.get("duration_field"):
                quote_args["num_frames"] = args.get("num_frames", round(duration * args.get("frames_per_second", 16)) + 1)
            else:
                quote_args[key] = duration
        if required.get("native_audio") and audio_field:
            quote_args[audio_field] = True
        if required.get("max_resolution"):
            minimum = required["max_resolution"]
            value = min(v for v in row["resolutions"] if v >= minimum)
            if "resolution" in controls:
                quote_args["resolution"] = row.get("resolution_labels", {}).get(str(value), "4k" if value == 2160 else f"{value}p")
            elif "size" in controls:
                quote_args["size"] = args.get("size", f"{value // 1024}K")
            elif "ratio" in controls:
                quote_args["ratio"] = args.get("ratio", "1920:1080" if value == 1080 else "1280:720")
    else:
        provider_id, verb = tool_parts(tool) if tool else ("local", "embeddings")
        model = effective_model(provider_id, verb, args)
        quote_args = dict(args)
    if available_tools is not None and tool is not None and tool not in available_tools:
        reason = f"Selected tool {tool} is unavailable; no automatic provider fallback."
        return Route(alias=alias, basis=basis, status="blocked", reason=reason, disclosure=reason)
    blocker = policy_blocker(tool, quote_args, region=region) if tool else None
    if blocker:
        return Route(alias=alias, basis=basis, status="blocked", reason=blocker, disclosure=blocker)
    quote = estimate_cost(tool, quote_args, list_price=True) if tool else CostEstimate(0)
    provider_id = row["provider"] if row else tool_parts(tool)[0] if tool else "local"
    label = row["label"] if row else alias
    disclosure = f"Selected {label}. Provider {provider_id}; model {model or 'none'}. {basis}. {quote.description}"
    if provider_id == "alibaba_modelstudio":
        disclosure += " Dry-run preview only; live customer use is blocked by the preview licence."
    if predicates["real_face_refs"] and alias in {"wan3_t2v", "wan3_i2v", "wan3_r2v", "wan3_edit", "wan3_extend"}:
        required["real_face_refs"] = True
        disclosure += " Real-person likeness consent " + (
            "acknowledged." if args.get("likeness_consent") is True else "required before generation."
        )
    return Route(tool=tool, alias=alias, basis=basis, dispatch_tool=_dispatch(tool), status="ready", reason=basis,
                 provider=provider_id, model=model, job_type=capability, required=required,
                 estimated_cost=quote.public(), disclosure=disclosure)


def tool_parts(name: str) -> tuple[str, str]:
    target, _, tool = name.partition("___")
    return TARGET_PROVIDERS.get(target, target.lower()), tool


def is_free_tool(name: str) -> bool:
    provider, tool = tool_parts(name)
    if name == "x_amz_bedrock_agentcore_search":
        return True
    if tool in POLICY["free_tools"]:
        return True
    if provider == "elevenlabs":
        from providers.elevenlabs.catalog import CATALOG

        return CATALOG.get(tool, {}).get("effect") == "read"
    return False


def premium_video(name: str) -> bool:
    enabled = os.getenv("RENDERHAUS_PREMIUM_VIDEO_APPROVAL")
    enabled = POLICY["premium_video_approval"] if enabled is None else enabled.lower() != "false"
    return bool(enabled and name in POLICY["paid_video_tools"])


def effective_model(provider: str, tool: str, arguments: dict) -> str | None:
    policy = POLICY["providers"].get(provider, {})
    if provider == "seedance":
        if tool == "get_video_task":
            endpoint = str(arguments.get("job_id", "")).partition(":")[0]
            return endpoint if endpoint.startswith("bytedance/seedance-2.5/") else None
        if tool == "list_seedance_models":
            return None
        from providers.seedance.contracts import effective_model as seedance_model

        return seedance_model(tool, arguments)
    if provider == "elevenlabs" and tool.startswith(("text_to_speech_", "text_to_dialogue_")):
        return arguments.get("model_id") or os.getenv("ELEVENLABS_TTS_MODEL", "eleven_v4_turbo")
    if tool in policy.get("fixed_models", {}):
        return policy["fixed_models"][tool]
    model_env = policy.get("model_env", "") if tool != "omni_video" else ""
    return (
        arguments.get("model")
        or os.getenv(model_env)
        or policy.get("default_models", {}).get(tool)
        or policy.get("default_model")
    )


def policy_blocker(name: str, arguments: dict, *, region: str | None = None) -> str | None:
    if is_free_tool(name):
        return None
    provider, tool = tool_parts(name)
    policy = POLICY["providers"].get(provider)
    if policy is None or not policy["enabled"]:
        return f"Provider {provider} is blocked or pending in routing_policy.json."
    if provider == "hyperframes":
        from agent.hyperframes import enabled

        if not enabled():
            return "HyperFrames is disabled. Enable HYPERFRAMES_ENABLED for composition previews."
    if policy["license"] not in {"Apache-2.0", "service-terms"}:
        return f"Provider {provider} licence is not approved for generation."
    region = region or os.getenv("RENDERHAUS_CUSTOMER_REGION")
    region = region.upper() if region else None
    if region in policy.get("blocked_regions", []):
        return f"Provider {provider} is blocked in region {region}."
    if policy["allowed_regions"] and region not in policy["allowed_regions"]:
        return f"Provider {provider} needs an allowed customer region before dispatch."
    try:
        model = effective_model(provider, tool, arguments)
    except ValueError as exc:
        return str(exc)
    if provider == "seedance" and (arguments.get("real_face_refs") or arguments.get("user_supplied_real_person_refs")):
        return "Seedance prohibits real-person photo/video references, even with likeness consent."
    if tool in policy.get("fixed_models", {}) and arguments.get("model", model) != model:
        return f"Tool {name} has a fixed model {model}."
    if model is not None and not isinstance(model, str):
        return f"Model for {provider} must be a string."
    if policy.get("models") and model not in policy["models"]:
        return f"Model {model} is not allowed for {provider}."
    model_policy = policy.get("model_policies", {}).get(model, {})
    if model_policy.get("enabled") is False or model_policy.get(
        "license", policy["license"]
    ) not in {"Apache-2.0", "service-terms"}:
        return f"Model {model} licence or access is not approved."
    if provider == "alibaba_modelstudio":
        from providers.alibaba_modelstudio.config import live_blocker

        blocker = live_blocker()
        if blocker:
            return blocker
    if provider == "seedance":
        from providers.seedance.api import dry_run
        from providers.seedance.contracts import live_blocker

        if not dry_run():
            if blocker := live_blocker(tool, arguments):
                return blocker
    if provider == "sync":
        from providers.sync.api import dry_run
        from providers.sync.contracts import live_blocker

        if not dry_run():
            if blocker := live_blocker(arguments):
                return blocker
    if (
        region in model_policy.get("blocked_regions", [])
        or model_policy.get("allowed_regions")
        and region not in model_policy["allowed_regions"]
    ):
        return f"Model {model} is not allowed in customer region {region or 'unknown'}."
    return None


def training_eligible(asset: dict) -> bool:
    provider = str(asset.get("provider", "")).lower()
    policy = POLICY["providers"].get(provider, {})
    if not isinstance(asset.get("model"), str):
        return False
    model_policy = policy.get("model_policies", {}).get(asset.get("model"), {})
    return bool(
        policy.get("enabled")
        and policy.get("training_eligible")
        and policy.get("license") == "Apache-2.0"
        and model_policy.get("license") == "Apache-2.0"
        and model_policy.get("training_eligible") is True
        and model_policy.get("enabled", True)
        and asset.get("model") in policy.get("models", [])
        and asset.get("weights_license") == "Apache-2.0"
        and asset.get("training_eligible") is True
        and not asset.get("dry_run")
        and asset.get("status") == "succeeded"
        and policy_blocker(
            "Fal___text_to_video", {"model": asset.get("model")}, region=asset.get("region")
        )
        is None
    )


@dataclass(frozen=True)
class CostEstimate:
    total_cents: int | None
    reason: str = ""

    @property
    def description(self):
        if self.total_cents is None:
            return f"Estimated cost unknown. {self.reason}"
        return f"Estimated cost ${self.total_cents / 100:.2f} USD including platform fee."

    def public(self):
        return {**asdict(self), "description": self.description}


def estimate_cost(name: str, arguments: dict, *, list_price: bool = False) -> CostEstimate:
    from server.billing_rates import cost_for

    if is_free_tool(name):
        return CostEstimate(0)
    blocker = policy_blocker(name, arguments)
    if blocker:
        return CostEstimate(None, blocker)
    provider, tool = tool_parts(name)
    model = effective_model(provider, tool, arguments)
    if provider == "openai_images":
        return CostEstimate(None, "UNVERIFIED pre-call token count for selected size/quality and inputs. Official token rates are verified.")
    if model:
        arguments = {**arguments, "model": model}
    try:
        if provider not in POLICY["providers"] or provider in {
            "veo",
            "minimax_h3",
            "hunyuan",
        }:
            raise ValueError("No confirmed provider rate.")
        if provider == "hyperframes":
            raise ValueError("HyperFrames local compute pricing is unknown; isolated renderer not configured.")
        if provider == "remotion":
            if os.getenv("REMOTION_RENDER_BACKEND", "lambda") == "local":
                return CostEstimate(0, "Local ffmpeg uses operator compute; no provider charge.")
            raise ValueError("Remotion compute rate is a TODO placeholder.")
        if provider == "seedream" and arguments.get("size", "2K") != "1K":
            raise ValueError("Seedream Lite larger size tiers are unconfirmed.")
        if (
            provider == "kling"
            and (arguments.get("model") or os.getenv("KLING_MODEL")) == "kling-3.0-turbo"
        ):
            raise ValueError("Kling Turbo audio pricing is unconfirmed.")
        if provider == "fal" and tool in {"generate_wan3_t2v", "generate_wan3_i2v", "generate_wan3_r2v"}:
            from server.billing_rates import wan3_price_cents

            wan3_price_cents(arguments)
        elif provider == "fal" and tool in {"vidu_q4_i2v", "vidu_q4_r2v"}:
            from server.billing_rates import vidu_q4_price_cents

            vidu_q4_price_cents(arguments)
        elif provider == "fal":
            from providers.fal.wan import endpoint_for, price_cents

            price_cents(
                endpoint_for(tool, arguments),
                arguments.get("resolution", "720p"),
                arguments.get("num_frames", 81),
            )
        if provider == "elevenlabs":
            from server.billing_rates import elevenlabs_quote
            return CostEstimate(elevenlabs_quote(tool, arguments).total_cents)
        if provider == "runway" and tool == "video_to_video":
            duration = arguments.get("video_duration_seconds")
            if isinstance(duration, float) and not duration.is_integer():
                raise ValueError("Fractional Aleph billing is unconfirmed.")
        if list_price:
            if provider in {"runway", "kling", "luma"}:
                cost_for(provider, tool, arguments)
            return CostEstimate(_published_cost(provider, tool, arguments).total_cents)
        return CostEstimate(cost_for(provider, tool, arguments).total_cents)
    except (ValueError, TypeError, KeyError) as exc:
        return CostEstimate(None, str(exc))


def _published_cost(provider: str, tool: str, arguments: dict):
    from decimal import Decimal
    from math import ceil
    from server import billing_rates as rates

    if provider == "seedance":
        from math import ceil

        return rates._with_fee(ceil(rates.seedance_price_cents(tool, arguments)))
    if provider == "seedream":
        return rates._seedream_cost(arguments)
    if provider == "sync":
        cents = rates.sync_price_cents(arguments)
        return rates._with_fee(ceil(cents))
    if provider == "alibaba_modelstudio":
        cents = rates.modelstudio_price_cents(tool, arguments)
    elif provider == "fal" and tool in {"generate_wan3_t2v", "generate_wan3_i2v", "generate_wan3_r2v"}:
        cents = rates.wan3_price_cents(arguments)
    elif provider == "fal" and tool in {"vidu_q4_i2v", "vidu_q4_r2v"}:
        cents = rates.vidu_q4_price_cents(arguments)
    elif provider == "fal":
        from providers.fal.wan import endpoint_for, price_cents
        cents = price_cents(endpoint_for(tool, arguments), arguments.get("resolution", "720p"),
                            arguments.get("num_frames", 81))
    elif provider == "kling":
        model = "kling-3.0-omni" if tool == "omni_video" else arguments["model"]
        cents = Decimal(rates.KLING_RATES_USD_PER_SECOND[(model, arguments.get("generate_audio", False))][
            arguments.get("resolution", "720p")]) * arguments.get("duration_seconds", 5) * 100
    elif provider == "luma":
        if tool == "extend_video":
            cents = rates.LUMA_EXTEND_CENTS[arguments.get("resolution", "720p")]
        else:
            table = rates.LUMA_EDIT_CENTS if tool == "modify_video" else rates.LUMA_GENERATION_CENTS
            duration = arguments.get("source_duration_seconds") if tool == "modify_video" else arguments.get("duration_seconds", 5)
            if type(duration) is not int or tool == "image_to_video" and duration != 5:
                raise ValueError("Luma request has no documented price for these settings.")
            cents = table[arguments.get("resolution", "720p")][duration]
    elif provider == "runway":
        if tool in {"text_to_image", "image_to_image"}:
            from providers.runway.contracts import IMAGE_720_RATIOS, IMAGE_1080_RATIOS
            ratio = arguments.get("ratio", "1280:720")
            if ratio not in IMAGE_720_RATIOS + IMAGE_1080_RATIOS:
                raise ValueError("Runway image resolution pricing is unknown.")
            table = rates.RUNWAY_IMAGE_CENTS[arguments["model"]]
            cents = table["720p" if ratio in IMAGE_720_RATIOS else "1080p"] if isinstance(table, dict) else table
        else:
            duration = arguments.get("video_duration_seconds") if tool == "video_to_video" else arguments.get("duration_seconds", 5)
            cents = rates.RUNWAY_CENTS_PER_SECOND[arguments["model"]] * duration
    else:
        raise ValueError("No published capability price.")
    return rates._with_fee(round(cents))
