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
    "Gemini": "gemini",
    "Mureka": "mureka",
    "Topaz": "topaz",
    "HeyGen": "heygen",
    "Sync": "sync",
    "OpenAI": "openai_images",
    "Kling": "kling",
    "Runway": "runway",
    "Fal": "fal",
    "Seedance": "seedance",
    "Seedream": "seedream",
    "ElevenLabs": "elevenlabs",
    "Remotion": "remotion",
    "Ffmpeg": "ffmpeg",
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
    execution_groups: tuple[tuple[str, ...], ...] = ()
    expected_output: str | None = None
    forbidden_tools: tuple[str, ...] = ()

    def public(self):
        payload = asdict(self)
        payload.pop("forbidden_tools")
        payload["steps"] = [step.public() for step in self.steps]
        return payload


_VIDEO_DELIVERABLE = r"\b(?:shots?|clips?|videos?|mp4)\b"
_VOICEOVER = r"\b(?:voice[ -]?over|narrat(?:ion|e|ed|ing|or)|tts|vo)\b"
_SPEECH_LABEL = r"(?:voice[ -]?over|narration|narrator|tts|vo|speech|dialogue)"
_NEGATED_NARRATION = (
    rf"\b(?:no|without)(?:[ -]+(?:any|an?|the))?[ -]+(?:spoken[ -]+)?{_SPEECH_LABEL}"
    rf"(?:[ ,]+(?:and|or|nor)?[ -]*{_SPEECH_LABEL})*\b|"
    rf"\b(?:do not|don't|never)\s+(?:(?:add|include|use|generate)\s+)?{_SPEECH_LABEL}\b|"
    r"\b(?:narration|voice[ -]?over)[ -]free\b|\bnot[ -]+narrated\b|"
    r"\b(?:do not|don't|never)\s+narrate\b"
)
_IMAGE_ALIASES = ("gpt_image25_t2i", "gpt_image25_edit", "recraft_v41_vector", "ideogram45_edit", "seedream_t2i")
_SPEECH_PRODUCTION_TOOLS = {
    "ElevenLabs___speech_to_speech_convert",
    "ElevenLabs___text_to_voice_create",
    "ElevenLabs___text_to_voice_design",
    "ElevenLabs___text_to_voice_remix",
    "ElevenLabs___dubbing_create",
    "ElevenLabs___dubbing_project_create",
    "ElevenLabs___dubbing_project_language_create",
}
_LIPSYNC_REQUEST = next(rule["pattern"] for rule in POLICY["rules"] if rule.get("capability") == "lipsync")
_KNOWLEDGE_REQUEST = next(rule["pattern"] for rule in POLICY["rules"] if rule["skill"] == "knowledge-explainer")
_PLAN_REVIEW_REQUEST = next(rule["pattern"] for rule in POLICY["rules"] if rule["skill"] == "plan-to-video")
_MODELSTUDIO_PREVIEW_WARNING = (
    "Alibaba preview terms permit internal testing, research and evaluation only until GA. "
    "Live customer use is blocked by the preview licence."
)
_FINISHING_CAPABILITIES = {"delivery_render", "loudness_qc", "deliverable_qc"}


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


def _narration_text(prompt: str) -> str:
    return re.sub(_NEGATED_NARRATION, " ", _instruction_text(prompt), flags=re.I)


def _knowledge_explainer_request(prompt: str) -> bool:
    text = _instruction_text(prompt)
    if not re.search(_KNOWLEDGE_REQUEST, text, re.I):
        return False
    if re.search(_VOICEOVER + r"|\b(?:dialogue|talking head|interview)\b", _narration_text(prompt), re.I):
        return False
    return bool(re.search(
        r"\bknowledge[ -]explainer\b|知识大赏|\b(?:silent|unnarrated|unvoiced)\b|"
        r"event[ -]foley|(?:sound effects?|sfx).*\b(?:synced|synchroni[sz]ed|only)\b|"
        r"\b(?:synced|synchroni[sz]ed)\b.*(?:sound effects?|sfx)|html.*seekable|seekable.*html",
        text, re.I,
    ) or re.search(_NEGATED_NARRATION, text, re.I))


def _audio_postprocess_request(prompt: str) -> bool:
    text = _instruction_text(prompt)
    sound = re.search(r"\b(?:foley|sfx|sound effects?|ambience)\b", text, re.I)
    action = re.search(r"\b(?:add|apply|make|create|generate|score|mix|layer|replace)\b", text, re.I)
    if not sound or not action:
        return False
    picture = re.search(r"\b(?:make|create|render|generate)\b[^.;!?]*?\b(?:explainer|video|short)\b", text, re.I)
    if picture and picture.end() <= sound.start():
        return False
    return bool(re.search(
        r"\b(?:an?|this|the|my|existing|attached|uploaded|rendered)\b(?:\s+[\w-]+){0,4}\s+(?:explainer|clip|video|short)\b",
        text, re.I,
    ))


def _video_voiceover(prompt: str) -> bool:
    return bool(re.search(_VIDEO_DELIVERABLE, _instruction_text(prompt), re.I)
                and re.search(_VOICEOVER, _narration_text(prompt), re.I)
                and not _knowledge_explainer_request(prompt))


def request_tool_blocker(prompt: str, name: str) -> str | None:
    if plan_text := _plan_review_instruction(prompt):
        prompt = plan_text
    if refusal := editing_request_refusal(prompt):
        return refusal
    if _knowledge_explainer_request(prompt) and (
        job_type(name) in {"tts", "voice_clone"} or name in _SPEECH_PRODUCTION_TOOLS
    ):
        return "A silent knowledge explainer uses on-screen graphics and event SFX; narration/TTS is excluded."
    if _video_voiceover(prompt) and job_type(name) in {"still_image", "image_edit"}:
        return "A shot or clip with voiceover uses video, TTS and assembly; image tools are excluded."
    if name.startswith("Seedream___") and not re.search(r"\bseedream\b", prompt, re.I):
        return "Seedream is explicit-only; request it by name. GPT Image 2.5 is the still-image default."
    return None


def editing_request_refusal(prompt: str) -> str | None:
    for refusal in POLICY.get("editing_refusals", []):
        if re.search(refusal["pattern"], prompt, re.IGNORECASE):
            return refusal["reason"]
    return None


def filter_request_tools(prompt: str, names: set[str]) -> set[str]:
    return {name for name in names if request_tool_blocker(prompt, name) is None}



def capability_constraints(constraints: dict, capability: str) -> dict:
    scoped = dict(constraints)
    if constraints["predicates"].get("lyrics_video"):
        workflow = {"lyrics_video"}
        if constraints["predicates"].get("lyrics_tts_first"):
            workflow.add("tts")
        if constraints["predicates"].get("lyrics_new_song"):
            workflow.add("music")
        routes = POLICY["explicit_routes"].get(scoped.get("provider"), {})
        if capability not in routes and workflow.intersection(routes):
            scoped["provider"] = next((p for p in scoped["provider_candidates"]
                                       if capability in POLICY["explicit_routes"].get(p, {})), None)
            scoped["model"] = None
        named = scoped.get("named_model")
        if named and capability not in POLICY["named_models"][named]["aliases"] and workflow.intersection(POLICY["named_models"][named]["aliases"]):
            scoped["named_model"] = None
        return scoped
    if capability == "lipsync" and scoped.get("provider") in {"elevenlabs", "fish_audio"}:
        scoped["provider"] = next((candidate for candidate in scoped["provider_candidates"]
                                   if capability in POLICY["explicit_routes"].get(candidate, {})), None)
        scoped["model"] = scoped["named_model"] = None
    if not any(constraints["predicates"].get(workflow) for workflow in
               ("video_voiceover", "knowledge_explainer", "plan_review")):
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
    if _knowledge_explainer_request(prompt):
        return None
    if any(rule.get("capability") in _FINISHING_CAPABILITIES and re.search(rule["pattern"], prompt, re.I)
           for rule in POLICY["rules"]):
        return None
    if any(rule.get("capability") == "ad_variant_matrix" and re.search(rule["pattern"], prompt, re.I)
           for rule in POLICY["rules"]):
        return None
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
    execution_groups = tuple(group for group in (
        tuple(step.alias for step in steps[:-1] if step.alias),
        tuple(step.alias for step in steps[-1:] if step.alias),
    ) if group)
    return replace(first, steps=tuple(steps), expected_output='assembled MP4',
                   execution_groups=execution_groups,
                   forbidden_tools=_IMAGE_ALIASES if voiceover else (),
                   status=incomplete.status if incomplete else first.status,
                   reason=incomplete.reason if incomplete else
                   'Start independent video and voiceover together; assemble after both finish.' if voiceover else
                   'Assemble the existing assets into the final MP4.')


def _delivery_preset(prompt: str, arguments: dict | None) -> str:
    if preset := (arguments or {}).get("preset"):
        return preset
    for preset in ("social-vertical", "social-feed", "web-1080p", "broadcast-proxy", "review-proxy", "email-720p", "podcast-streaming"):
        if re.search(rf"\b{re.escape(preset)}\b", prompt, re.I):
            return preset
    for pattern, preset in (
        (r"\bemail\b", "email-720p"),
        (r"\bproxy\b", "review-proxy"),
        (r"\btiktok\b|\breels\b|\b9:16\b|\bvertical\b", "social-vertical"),
        (r"\byoutube\b|\bweb\b", "web-1080p"),
    ):
        if re.search(pattern, prompt, re.I):
            return preset
    return "social-feed"


def _editing_workflow_route(prompt: str, constraints: dict, *, region: str | None,
                            available_tools: set[str] | None, arguments: dict | None) -> Route | None:
    workflow = next((row for row in POLICY.get("editing_workflows", [])
                     if re.search(row["pattern"], prompt, re.I)), None)
    if workflow is None:
        return None
    steps = []
    for step in workflow["steps"]:
        route = select_provider(step["capability"], region=region, available_tools=available_tools,
                                arguments=arguments, **constraints)
        if step["capability"] == "delivery_render":
            route = replace(route, required={"preset": _delivery_preset(prompt, arguments)})
        steps.append(replace(route, skill=step["skill"]))
    first = steps[0]
    incomplete = next((step for step in steps if step.status != "ready"), None)
    return replace(first, steps=tuple(steps), expected_output="QC-checked MP4",
                   execution_groups=tuple((step.alias,) for step in steps if step.alias),
                   tool=None if incomplete else first.tool,
                   dispatch_tool=None if incomplete else first.dispatch_tool,
                   status=incomplete.status if incomplete else first.status,
                   reason=incomplete.reason if incomplete else
                   "Complete matrix/reframe approval, delivery finishing, loudness and QC in order. Reuse integrated finishing evidence before reporting completion.")


def _lyrics_capabilities(prompt: str) -> list[tuple[str, str]]:
    if not re.search(r"lyrics?[ -]?video|karaoke", prompt, re.I):
        return []
    capabilities = []
    if re.search(r"\b(?:tts|narration|voiceover)\b.*\bfirst\b", prompt, re.I):
        capabilities.append(("tts", "audio-bed"))
    elif re.search(r"\bsong you write\b|\b(?:write|generate|create|make)\s+(?:(?:a|an|new|original)\s+){0,3}song\b", prompt, re.I):
        capabilities.append(("music", "lyrics-video"))
    capabilities.append(("lyrics_video", "lyrics-video"))
    return capabilities


def _lyrics_route(prompt: str, constraints: dict, *, region: str | None,
                  available_tools: set[str] | None, arguments: dict | None) -> Route | None:
    capabilities = _lyrics_capabilities(prompt)
    if not capabilities:
        return None
    steps = []
    for capability, skill in capabilities:
        scoped = capability_constraints(constraints, capability)
        scoped["required"] = {key: value for key, value in constraints["required"].items()
                              if capability == "lyrics_video" and key in {"aspect_ratio", "duration_seconds"}}
        step = select_provider(capability, region=region, available_tools=available_tools,
                               arguments=arguments, **scoped)
        steps.append(replace(step, skill=skill))
    first = steps[0]
    incomplete = next((step for step in steps if step.status != "ready"), None)
    return replace(first, steps=tuple(steps) if len(steps) > 1 else (), expected_output="lyrics MP4",
                   status=incomplete.status if incomplete else first.status,
                   reason=incomplete.reason if incomplete else first.reason)


def _licence_interim(alias: str) -> str | None:
    entry = TOOL_MAP.get(alias, {})
    policy = POLICY["providers"].get(entry.get("provider"), {})
    model = entry.get("model")
    if entry.get("gateway_tool") and entry.get("provider"):
        model = effective_model(entry["provider"], entry["gateway_tool"].split("___")[1], {})
    model_policy = policy.get("model_policies", {}).get(model, {})
    if model_policy.get("live_enabled") is not False:
        return None
    return next((row.get("interim") for row in POLICY["capability_map"].values()
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
        interim = next((row.get("interim") for row in POLICY["capability_map"].values()
                        if row["default"] == alias), None)
    return TOOL_MAP.get(interim, {}).get("gateway_tool") if interim else None


def route_intent(prompt: str, *, region: str | None = None, tier: str | None = None,
                 confidential: bool = False, arguments: dict | None = None,
                 available_tools: set[str] | None = None, retry: bool = False) -> Route:
    if _plan_review_instruction(prompt) is not None:
        constraints = intent_constraints(prompt, tier=tier, confidential=confidential, arguments=arguments)
        route = select_provider("motion_graphics", region=region, available_tools=available_tools,
                                arguments=arguments, **capability_constraints(constraints, "motion_graphics"))
        return replace(route, skill="plan-to-video")
    for refusal in POLICY.get("editing_refusals", []):
        if re.search(refusal["pattern"], prompt, re.IGNORECASE):
            return Route(skill=refusal.get("skill", "remotion-ad-variant-matrix"), status="blocked",
                         reason=refusal["reason"], disclosure=refusal["reason"])
    if any(re.search(pattern, prompt, re.I) for pattern in POLICY.get("non_dispatch_requests", [])):
        return Route(reason="No media intent matched; answer the Remotion licensing question from the editing skill.")
    constraints = intent_constraints(prompt, tier=tier, confidential=confidential, arguments=arguments)
    for pattern, alias in POLICY["retired_requests"].items():
        if re.search(pattern, prompt, re.I):
            return Route(alias=alias, status="retired", reason=TOOL_MAP[alias]["reason"],
                         disclosure=TOOL_MAP[alias]["reason"])
    if editing_workflow := _editing_workflow_route(prompt, constraints, region=region, available_tools=available_tools, arguments=arguments):
        return editing_workflow
    if lyrics_route := _lyrics_route(prompt, constraints, region=region, available_tools=available_tools, arguments=arguments):
        return lyrics_route
    lipsync = bool(re.search(_LIPSYNC_REQUEST, prompt, re.I))
    delivery = None if lipsync else _delivery_route(prompt, constraints, region=region, available_tools=available_tools, arguments=arguments)
    if delivery is not None:
        return delivery
    knowledge_request = _knowledge_explainer_request(prompt)
    audio_postprocess = knowledge_request and _audio_postprocess_request(prompt)
    video_capabilities = {"t2v", "i2v", "reference_video"}
    explicit_video = bool(
        video_capabilities.intersection(POLICY["explicit_routes"].get(constraints["provider"], {}))
        or video_capabilities.intersection(POLICY["named_models"].get(constraints["named_model"], {}).get("aliases", {}))
    )
    for rule in POLICY["rules"]:
        if rule["skill"] == "plan-to-video":
            continue
        if rule["skill"] == "knowledge-explainer" and not knowledge_request:
            continue
        if knowledge_request and rule.get("capability") == "tts":
            continue
        if knowledge_request and explicit_video and not audio_postprocess and rule.get("capability") == "sfx":
            continue
        if knowledge_request and (audio_postprocess or explicit_video) and rule.get("capability") == "motion_graphics":
            continue
        if rule.get("capability") == "tts":
            rule_prompt = _narration_text(prompt)
        elif rule.get("capability") in {"still_image", "image_edit"} or rule["skill"] == "knowledge-explainer":
            rule_prompt = _instruction_text(prompt)
        else:
            rule_prompt = prompt
        if not re.search(rule["pattern"], rule_prompt, re.IGNORECASE):
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
            scoped = capability_constraints(constraints, capability) if capability == "lipsync" or knowledge_request else constraints
            route = select_provider(capability, arguments=arguments, available_tools=available_tools,
                                    region=region, retry=retry, **scoped)
            if capability == "delivery_render":
                route = replace(route, required={"preset": _delivery_preset(prompt, arguments)})
            if capability not in _FINISHING_CAPABILITIES | {"performance_transfer"} and (constraints["provider"] in {"kling", "runway", "luma", "seedream", "fish_audio", "alibaba_modelstudio"} or (
                constraints["provider"] == "fal" and re.search(r"vidu|vace", prompt, re.I)
            ) or constraints["named_model"] == "wan3" and capability in {"v2v_edit", "extend"}):
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
    if tool.startswith(("Remotion___", "HyperFrames___", "Ffmpeg___")):
        return "call_editor_tool"
    if tool.startswith(("ElevenLabs___", "FishAudio___", "Mureka___")):
        return "call_audio_tool"
    return "call_media_tool"


def job_type(name: str | None) -> str | None:
    if name and name.endswith(("reference_to_video", "vidu_q4_r2v")):
        return "reference_video"
    for row in POLICY["capabilities"]:
        for job, tool in row["tools"].items():
            if tool == name:
                return {"image_edit": "image_edit", "reference": "reference_video", "image": "still_image", "instrumental": "music"}.get(job, job)
    for capability, choice in POLICY["capability_map"].items():
        aliases = [choice["default"], choice.get("interim")] + [ex["tool"] for ex in choice["exceptions"]]
        if any(alias and name in [TOOL_MAP.get(alias, {}).get("gateway_tool"), *TOOL_MAP.get(alias, {}).get("gateway_variants", [])] for alias in aliases):
            return capability
    if name == "FishAudio___generate_speech":
        return "tts"
    for routes in POLICY["explicit_routes"].values():
        for capability, alias in routes.items():
            entry = TOOL_MAP[alias]
            if name in [entry.get("gateway_tool"), *entry.get("gateway_variants", [])]:
                return capability
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
    if "performance_transfer" in row["tools"]:
        return row["price"]
    from server import billing_rates as rates

    price = row["price"]
    if price == "unknown":
        return price
    provider, model = row["provider"], row["model"]
    if provider == "ffmpeg" or provider == "remotion" and all(is_free_tool(tool) for tool in row["tools"].values()):
        return {**price, "rates": {"cents_per_call": 0}, "currency_unit": "USD cents"}
    if provider == "remotion" and model == "ad-variant-timeline":
        try:
            quote = rates.ad_matrix_estimate({"rows": [{}]})
        except ValueError as exc:
            return {**price, "configuration_error": str(exc)}
        return {**price, "rates": quote, "currency_unit": "USD"}
    if provider == "mureka":
        values = {"lyrics_to_song_cents": str(rates.MUREKA_LYRICS_SONG_CENTS), "prompt_to_song_cents": str(rates.MUREKA_PROMPT_SONG_CENTS), "instrumental_cents": str(rates.MUREKA_INSTRUMENTAL_CENTS), "lyrics_video_cents": str(rates.MUREKA_LYRICS_VIDEO_CENTS)}
    elif provider == "fal":
        if model == "ideogram/v4.5/edit":
            values = {quality: str(value) for quality, value in rates.IDEOGRAM_CENTS_PER_IMAGE.items()}
        elif model == "fal-ai/recraft/v4.1/pro/text-to-vector":
            values = {"cents_per_image": str(rates.RECRAFT_VECTOR_CENTS_PER_IMAGE)}
        elif model == "mirelo-ai/sfx1.6/video-to-video":
            values = {"single_sample_cents_per_second": str(rates.MIRELO_CENTS_PER_SECOND),
                      "multi_sample": "unknown"}
        elif model.startswith("alibaba/wan-3.0/"):
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
    elif provider == "heygen":
        values = {"self_serve_cents_per_second": str(rates.HEYGEN_AVATAR_V_CENTS_PER_SECOND),
                  "enterprise": "unknown"}
    elif provider == "sync":
        values = {"fal_cents_per_minute": str(rates.SYNC_FAL_CENTS_PER_MINUTE),
                  "direct_legacy_base_cents_per_second_at_25fps": str(rates.SYNC_DIRECT_BASE_CENTS_PER_SECOND_25FPS)}
    elif provider == "topaz":
        values = {"upscale_cents_per_10_seconds": rates.TOPAZ_UPSCALE_CENTS_PER_10_SECONDS,
                  "interpolate_cents_per_new_frame": {key: str(value) for key, value in
                                                      rates.TOPAZ_INTERPOLATE_CENTS_PER_FRAME.items()}}
    else:
        return "unknown"
    return {**price, "rates": values,
            "currency_unit": "USD/second" if provider == "kling" else "provider cents",
            "fee": "server.billing_rates._with_fee"}


def _instruction_text(prompt: str) -> str:
    return re.sub(r"\"[^\"]*\"|“[^”]*”|(?<!\w)'[^']*'(?!\w)", "", prompt)


def _plan_review_instruction(prompt: str) -> str | None:
    text = _instruction_text(re.sub(r"```.*?(?:```|$)|~~~.*?(?:~~~|$)", "", prompt, flags=re.S))
    text = re.sub(r"(?m)^[ \t]*>.*$", "", text)
    if not re.search(_PLAN_REVIEW_REQUEST, text, re.I):
        return None
    return re.sub(r"\b(?:not|no|avoid|without|never|don't|do not)(?:\s+(?:use|using))?\s+hyperframes\b",
                  "", text, flags=re.I)


def _text_only_image_edit(prompt: str, arguments: dict) -> bool:
    text = _instruction_text(prompt)
    existing = bool(arguments.get("image_url") or arguments.get("image_path_or_url") or re.search(
        r"\b(?:this|the|my|existing|attached|uploaded|original)\s+(?:\w+\s+){0,3}(?:image|photo|banner|poster)\b", text, re.I))
    text_change = bool(arguments.get("text_only_edit") or re.search(
        r"\bonly\s+(?:change|replace|edit).*\b(?:text|headline)\b|(?:change|replace|edit).*\bonly\b.*(?:text|headline)|(?:change|replace|edit).*(?:text|headline).*\bonly\b|fix.*typo|text.only.*edit", text, re.I))
    visual_changes = re.finditer(r"\b(?:change|replace|remove|add|edit|restyle|relight|make)\s+(?:(?:the|a|an|its|that|this|entire|whole|original|all)\s+){0,3}(?:background|lighting|person|color|colour|product|composition|logo|object|subject)\b|\b(?:crop|rotate|resize|reframe)\b", text, re.I)
    mixed = any(not re.search(r"(?:don't|do not|not|never|without)\s*$", text[:match.start()], re.I)
                for match in visual_changes)
    negated = re.search(r"(?:don't|do not|not|never|without)\s+(?:change|replace|fix|edit)[^,;.!?]*\b(?:text|headline|typo)\b(?!\s+(?:placement|position|layout|font)\b)", text, re.I)
    new = re.search(r"\b(?:generate|create|make|design)\b.*\b(?:new|a|an)\b.*\b(?:image|poster|banner)\b", text, re.I)
    return bool(existing and text_change and not mixed and not negated and not new)


def intent_constraints(prompt: str, *, tier: str | None = None, confidential: bool = False,
                       arguments: dict | None = None) -> dict:
    args = arguments or {}
    plan_text = _plan_review_instruction(prompt)
    if plan_text is not None:
        prompt = plan_text
    excluded_names = re.compile(
        r"\b(?:not|no|avoid|without|never|don't|do not)(?:\s+use)?\s+"
        r"(heygen(?:\s+avatar\s+v)?|avatar[ -]v|sync(?:[ -]?3|\.so)?|ideogram(?:\s+4\.5)?|recraft(?:\s+v?4\.1)?)\b", re.IGNORECASE,
    )
    exclusions = [match[1].lower() for match in excluded_names.finditer(_instruction_text(prompt))]
    excluded_providers = sorted({"heygen" if name.startswith(("heygen", "avatar")) else "sync"
                                 for name in exclusions if name.startswith(("heygen", "avatar", "sync"))})
    excluded_aliases = [alias for name, alias in (("ideogram", "ideogram45_edit"), ("recraft", "recraft_v41_vector"))
                        if any(exclusion.startswith(name) for exclusion in exclusions)]
    provider_prompt = excluded_names.sub("", _instruction_text(prompt))
    provider_candidates = [p for pattern, p in [
        (r"\bvidu\b|\bvace\b|\bfal\b|\bwan[ -]?2", "fal"), (r"\bseedance\b", "seedance"),
        (r"\bseedream\b", "seedream"), (r"\bkling\b", "kling"),
        (r"\bopenai\b|gpt[ -]image", "openai_images"),
        (r"\brunway\b|\baleph\b|gen.?4", "runway"), (r"\bluma\b|\bray.?3\b", "luma"),
        (r"\bmureka\b", "mureka"), (r"\bfish\b", "fish_audio"), (r"\belevenlabs\b", "elevenlabs"),
        (r"\bgemini\b", "gemini"),
        (r"\bsync[ -]?3\b|sync\.so|\b(?:use|using|via)\s+sync\b", "sync"),
        (r"\bheygen\b|\bavatar[ -]v\b", "heygen"),
        (r"model[ -]?studio|dashscope|alibaba", "alibaba_modelstudio"),
        (r"mini.?max", "minimax_h3"), (r"hunyuan", "hunyuan"),
    ] if re.search(pattern, provider_prompt, re.I)]
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
    fps = re.search(r"(?:to|at)\s*(\d+)\s*fps\b", prompt, re.I)
    if fps and re.search(r"interpolat|smooth|convert|upscale", prompt, re.I):
        required["target_fps"] = int(fps[1])
    duration = deliverable_duration(prompt)
    seconds = duration.seconds if duration else None
    if seconds is not None:
        required["duration_seconds"] = seconds
    extension = re.search(r"(?:extend|continue).*\bby\s+(\d+(?:\.\d+)?)\s*(seconds?|secs?|s)\b", prompt, re.I)
    if extension:
        added = float(extension[1])
        required["extension_seconds"] = int(added) if added.is_integer() else added
    if re.search(r"lyrics?[ -]?video|karaoke", prompt, re.I):
        aspect = re.search(r"\b(16:9|9:16|3:4|4:3)\b", prompt)
        if aspect:
            required["aspect_ratio"] = aspect[1]
        elif re.search(r"vertical|portrait", prompt, re.I):
            required["aspect_ratio"] = "9:16"
        elif re.search(r"horizontal|landscape", prompt, re.I):
            required["aspect_ratio"] = "16:9"
    supplied_duration = next((args[k] for k in ("performance_duration_seconds", "duration", "duration_seconds", "video_duration_seconds", "source_duration_seconds") if args.get(k) is not None), seconds)
    real_face = bool(args.get("real_face_refs") or args.get("user_supplied_real_person_refs") or re.search(
        r"real[ -](?:person|human|actor)|my (?:ceo|face|selfie)|(?:photo|video).*(?:of me|of my|real person)|(?:user.supplied|uploaded).*(?:person|face)", prompt, re.I))
    dialogue_prompt = re.sub(r"(?:voice[ -]?over|narration|\bvo\b)\s*:?\s*[\'\"“].*?[\'\"”]", "", prompt, flags=re.I)
    dialogue = bool(re.search(r'["“][^"”]+["”]|\b(?:says?|saying|talking|talks?|dialogue|speaking)\b', dialogue_prompt, re.I))
    if re.search(r"\b(?:no|without) dialogue\b|\bnot talking\b|silent scene", prompt, re.I):
        dialogue = False
    knowledge_explainer = _knowledge_explainer_request(prompt)
    video_sfx = bool(args.get("video_url") or args.get("source_video_url") or re.search(r"(?:from|to|for|on) (?:the |this |my |an? )?(?:attached |uploaded )?(?:video|clip)|video to audio|foley|synchroni[sz]ed|silent clip|picture.synced", prompt, re.I))
    if not (args.get("video_url") or args.get("source_video_url")) and (
        re.search(r"no video|without video", prompt, re.I) or knowledge_explainer and args.get("text")
    ):
        video_sfx = False
    lyrics_capabilities = {capability for capability, _ in _lyrics_capabilities(prompt)}
    predicates = {
        "lyrics_video": "lyrics_video" in lyrics_capabilities,
        "lyrics_tts_first": "tts" in lyrics_capabilities,
        "lyrics_new_song": "music" in lyrics_capabilities,
        "instrumental_music": bool(re.search(r"music bed|instrumental|no vocals|without vocals", prompt, re.I)),
        "dialogue": dialogue, "real_face_refs": real_face,
        "video_voiceover": _video_voiceover(prompt),
        "knowledge_explainer": knowledge_explainer,
        "plan_review": plan_text is not None,
        "vector_output": bool(re.search(r"\bsvg\b|vector|editable.*illustrator", prompt, re.I)),
        "text_only_edit": _text_only_image_edit(prompt, args),
        "full_body_motion": bool(re.search(r"full.body|whole.body|\bdance\b|\bdancing\b", prompt, re.I)),
        "facial_performance": bool(re.search(r"facial|face.*acting|upper.body", prompt, re.I)),
        "duration_over_30s": isinstance(supplied_duration, (int, float)) and supplied_duration > 30,
        "presenter": bool(re.search(r"presenter|digital twin", prompt, re.I)),
        "text_only_sfx": not video_sfx,
        "linear_fps": bool(re.search(r"linear|simple pan", prompt, re.I)) and not bool(re.search(r"non[ -]?linear|not linear", prompt, re.I)),
    }
    predicates.update({k: bool(args[k]) for k in predicates if k in args})
    predicates["text_only_edit"] = _text_only_image_edit(prompt, args)
    predicates["real_face_refs"] = real_face
    predicates["explicit_hyperframes"] = bool(re.search(r"\bhyperframes\b", prompt, re.I))
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
                        if re.search(entry["pattern"], provider_prompt, re.I)), None)
    return {"provider": provider, "model": model, "named_model": named_model,
            "provider_candidates": provider_candidates, "excluded_providers": excluded_providers, "excluded_aliases": excluded_aliases,
            "required": required, "predicates": predicates}


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
                    provider_candidates: list[str] | None = None,
                    excluded_providers: list[str] | None = None,
                    excluded_aliases: list[str] | None = None) -> Route:
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
    if capability in {"tts", "voice_clone", "music", "sfx", "motion_graphics", "nle_handoff", "nle_import", "ad_variant_matrix", "media_inspection"} | _FINISHING_CAPABILITIES:
        required = {}
        if capability in {"motion_graphics", "nle_handoff", "nle_import", "ad_variant_matrix", "media_inspection"} | _FINISHING_CAPABILITIES:
            provider = model = named_model = None
    if capability not in POLICY["capability_map"]:
        return Route(status="blocked", reason=f"No capability map for {capability}.")
    choice = POLICY["capability_map"][capability]
    if capability == "continuity_qc" and choice["default"] == "gemini_vlm_judge":
        from agent.deep_agent.continuity_qc_vlm import default_vlm_enabled

        if not default_vlm_enabled():
            choice = {**choice, "default": "local_qc"}
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
    if entry.get("provider") == "topaz":
        from providers.topaz.contracts import configured_model

        verb = "upscale_video" if capability == "upscale" else "interpolate_video"
        model_args = dict(args)
        explicit_model = args.get("model") or model
        if named_model in {"topaz_apollo", "topaz_chronos", "topaz_starlight"}:
            explicit_model = POLICY["named_models"][named_model]["model"]
        if explicit_model:
            model_args["model"] = explicit_model
            basis = "explicit request"
        elif capability == "interpolate" and predicates["linear_fps"]:
            model_args["model"] = "Chronos"
            basis = "exception: Chronos for linear frame-rate conversion"
        try:
            model = configured_model(verb, model_args)
        except ValueError as exc:
            return Route(alias=alias, status="blocked", reason=str(exc), disclosure=str(exc))
    if alias in (excluded_aliases or []):
        reason = f"Requested model exclusion blocks {alias} for {capability}; no substitute was selected."
        return Route(alias=alias, status="blocked", job_type=capability, reason=reason, disclosure=reason)
    if entry.get("provider") in (excluded_providers or []):
        reason = f"Requested provider exclusion blocks {entry['provider']} for {capability}; no substitute was selected."
        return Route(alias=alias, status="blocked", job_type=capability, reason=reason, disclosure=reason)
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
    duration = required.get("duration_seconds") or next((args[k] for k in ("performance_duration_seconds", "duration", "duration_seconds", "video_duration_seconds", "source_duration_seconds") if args.get(k) is not None), None)
    if entry.get("provider") == "alibaba_modelstudio" and not required.get("duration_seconds"):
        duration = args.get("duration")
    if (predicates["duration_over_30s"] or isinstance(duration, (int, float)) and duration > 30) and capability in {"t2v", "i2v", "reference_video", "performance_transfer"}:
        reason = "Duration exceeds 30 seconds; split into shots of at most 30 seconds before generation."
        return Route(alias=alias, basis=basis, status="blocked", job_type=capability, reason=reason, disclosure=reason)
    tool = entry.get("gateway_tool")
    if entry["status"] == "pending":
        interim = None if named_model else entry.get("interim_alias") or (choice.get("interim") if alias == choice["default"] and not provider else None)
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
    if alias == "mureka_v95" and predicates.get("instrumental_music"):
        tool = "Mureka___generate_instrumental"
    if capability == "still_image" and predicates.get("vector_output") and alias != "recraft_v41_vector":
        reason = "Requested raster model cannot produce editable vector/SVG output; no automatic provider fallback."
        return Route(alias=alias, basis=basis, status="blocked", reason=reason, disclosure=reason)
    variant = {"still_image": "image", "reference_video": "reference"}.get(capability, capability)
    row = next((r for r in capability_table() if tool in r["tools"].values() and (model is None or r["model"] == model)), None)
    if model and row is None and any(tool in r["tools"].values() for r in POLICY["capabilities"]):
        return Route(alias=alias, status="blocked", reason=f"Model {model} does not support the selected tool.")
    if row:
        model = row["model"]
        if row["provider"] == "mureka":
            model = effective_model("mureka", tool.split("___")[1], args)
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
        if capability == "still_image" and alias != "recraft_v41_vector" and not resolution and not provider:
            required["max_resolution"] = max(required.get("max_resolution", 0), resolution_value(POLICY["image_default_size"]))
        if capability == "v2v_edit":
            required.pop("multi_shot", None)
        controls = row["controls"].get(variant, [])
        limits = row["durations"].get(variant)
        values = row.get("duration_values", {}).get(variant)
        unsupported = any(row["jobs"].get(k, False) < value for k, value in required.items()
                          if k not in {"duration_seconds", "extension_seconds", "target_fps", "aspect_ratio"})
        unsupported |= duration is not None and limits is not None and not limits[0] <= duration <= limits[1]
        unsupported |= bool(duration is not None and values and duration not in values)
        unsupported |= bool(row.get("duration_field") and row.get("duration_integer", True)
                            and duration is not None and type(duration) is not int)
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
        quote_args = dict(args) if tool == "Mureka___generate_lyrics_video" else {**args, "model": model}
        if duration and row["provider"] not in {"sync", "topaz", "mureka"}:
            key = row.get("duration_field") or ("performance_duration_seconds" if capability == "performance_transfer" else "source_duration_seconds" if row["provider"] == "sync" or tool.endswith("modify_video") else "video_duration_seconds" if tool.endswith("video_to_video") and row["provider"] == "runway" else "duration_seconds")
            if row["provider"] == "fal" and not row.get("duration_field") and capability != "performance_transfer":
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
    provider_id = row["provider"] if row else tool_parts(tool)[0] if tool else "local"
    blocker = policy_blocker(tool, quote_args, region=region) if tool else None
    if blocker:
        disclosure = blocker
        if provider_id == "alibaba_modelstudio":
            disclosure += " " + _MODELSTUDIO_PREVIEW_WARNING
        return Route(alias=alias, basis=basis, status="blocked", reason=blocker, disclosure=disclosure)
    quote = estimate_cost(tool, quote_args, list_price=True) if tool else CostEstimate(0)
    label = row["label"] if row else alias
    disclosure = f"Selected {label}. Provider {provider_id}; model {model or 'none'}. {basis}. {quote.description}"
    if provider_id == "gemini":
        disclosure += " Experimental continuity judge. Default promotion requires a committed passing eval. Background inputs are stored by the vendor."
    if provider_id == "alibaba_modelstudio":
        disclosure += " " + _MODELSTUDIO_PREVIEW_WARNING
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
    if provider == "gemini":
        return arguments.get("model") or os.getenv("GEMINI_VLM_MODEL", "gemini-3.8-flash")
    policy = POLICY["providers"].get(provider, {})
    if provider == "mureka":
        if tool == "generate_lyrics_video":
            return "mureka/api/generate/lyrics-video"
        if tool not in {"generate_song", "generate_instrumental"}:
            return None
        from providers.mureka.contracts import configured_model

        return configured_model(arguments)
    if provider == "topaz":
        if tool not in {"upscale_video", "interpolate_video"}:
            return None
        from providers.topaz.contracts import configured_model

        return configured_model(tool, arguments)
    if provider == "heygen":
        if tool != "create_avatar_video":
            return None
        from providers.heygen.contracts import configured_model

        return configured_model(arguments)
    if provider == "seedance":
        if tool == "get_video_task":
            endpoint = str(arguments.get("job_id", "")).partition(":")[0]
            return endpoint if endpoint.startswith("bytedance/seedance-2.5/") else None
        if tool == "list_seedance_models":
            return None
        from providers.seedance.contracts import effective_model as seedance_model

        return seedance_model(tool, arguments)
    if provider == "elevenlabs" and tool.startswith("text_to_speech_"):
        from server.billing_rates import elevenlabs_tts_model

        return elevenlabs_tts_model(arguments)
    if provider == "elevenlabs" and tool.startswith("text_to_dialogue_"):
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
    if provider == "gemini" and model not in policy["models"]:
        from providers.gemini.api import dry_run

        return None if dry_run() else "UNVERIFIED Gemini model; live use blocked and estimate unknown."
    if provider == "mureka" and model not in policy["models"]:
        from providers.mureka.api import dry_run

        return None if dry_run() else "UNVERIFIED Mureka model; live use is blocked and estimate unknown."
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
    if provider == "heygen":
        from providers.heygen.api import dry_run
        from providers.heygen.contracts import live_blocker

        if not dry_run(arguments):
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

    if name in {"Remotion___render_ad_variants", "ad_variant_matrix"}:
        return CostEstimate(cost_for("remotion", "render_ad_variants", arguments).total_cents)
    if is_free_tool(name):
        return CostEstimate(0)
    provider, tool = tool_parts(name)
    if provider == "elevenlabs" and tool.startswith("text_to_speech_"):
        effective_model(provider, tool, arguments)
    blocker = policy_blocker(name, arguments)
    if blocker:
        return CostEstimate(None, blocker)
    model = effective_model(provider, tool, arguments)
    if provider == "gemini":
        try:
            from server.billing_rates import gemini_quote

            return CostEstimate(gemini_quote(tool, arguments).total_cents)
        except ValueError as exc:
            return CostEstimate(None, str(exc))
    if provider in {"heygen", "topaz", "mureka"} or name in {"Runway___act_two", "Fal___kling_motion_control", "Fal___mirelo_v2a", "Fal___ideogram_edit", "Fal___recraft_text_to_vector"}:
        try:
            return CostEstimate(_published_cost(provider, tool, arguments).total_cents)
        except (ValueError, TypeError, KeyError) as exc:
            return CostEstimate(None, str(exc))
    if provider == "openai_images":
        from server.billing_rates import openai_images_estimate_cents

        try:
            return CostEstimate(openai_images_estimate_cents(tool, arguments),
                                "Per-image estimate ($0.20 default or operator quote); actual token usage is reported.")
        except (ValueError, TypeError, KeyError) as exc:
            return CostEstimate(None, f"OpenAI Images estimate unavailable for these inputs: {exc}")
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

    if provider == "mureka":
        cents = rates.mureka_price_cents(tool, arguments)
        if cents is None:
            raise ValueError("Mureka estimate unknown for invalid inputs or UNVERIFIED model.")
        return rates._with_fee(ceil(cents))
    if provider == "runway" and tool == "act_two":
        return rates._with_fee(ceil(rates.performance_price_cents(arguments)))
    if provider == "fal" and tool == "kling_motion_control":
        return rates._with_fee(ceil(rates.motion_control_price_cents(arguments)))
    if provider == "fal" and tool == "mirelo_v2a":
        cents = rates.mirelo_price_cents(arguments)
        if cents is None:
            raise ValueError("Mirelo multi-sample cost unknown; official billing TODO.")
        return rates._with_fee(ceil(cents))
    if provider == "fal" and tool in {"ideogram_edit", "recraft_text_to_vector"}:
        return rates._with_fee(ceil(rates.image_specialist_price_cents(tool, arguments)))
    if provider == "seedance":
        from math import ceil

        return rates._with_fee(ceil(rates.seedance_price_cents(tool, arguments)))
    if provider == "seedream":
        return rates._seedream_cost(arguments)
    if provider == "heygen":
        return rates._with_fee(ceil(rates.heygen_price_cents(arguments)))
    if provider == "topaz":
        cents = rates.topaz_price_cents(tool, arguments)
        if cents is None:
            raise ValueError("Topaz price unknown for these dimensions, FPS or slowdown; official quote TODO.")
        return rates._with_fee(ceil(cents))
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
