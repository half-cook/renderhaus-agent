"""Wan 3 edit and extend contracts checked against Alibaba docs on 2026-10-09.

https://www.alibabacloud.com/help/en/model-studio/wan3-video-generation-api-reference
https://www.alibabacloud.com/help/en/model-studio/wan3-video-generation-guide
https://www.alibabacloud.com/help/en/model-studio/wan3-0-video
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from providers.contracts import ArgumentRule
from providers.alibaba_modelstudio.config import DEFAULT_MODEL, PREVIEW_TERMS_URL


GENERATING_TOOLS = ("edit_wan3_video", "extend_wan3_video")
RESOLUTIONS = ("480p", "720p", "1080p")
ASPECT_RATIOS = ("adaptive", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9")
CENTS_PER_SECOND = {
    "us-east-1": {"480p": Decimal("4.1256"), "720p": Decimal("8.2513"), "1080p": Decimal("16.5025")},
    "ap-southeast-1": {"480p": Decimal("5"), "720p": Decimal("10"), "1080p": Decimal("20")},
}
PRICING_URL = "https://www.alibabacloud.com/help/en/model-studio/wan3-0-video"
TERMS_URL = "https://www.alibabacloud.com/help/en/legal/latest/alibaba-cloud-international-website-product-terms-of-service-v-3-8-0"
TRAINING_METADATA = {
    "training_eligible": False, "weights_license": "closed-weights", "license": "service-terms",
    "hosted_terms_url": TERMS_URL, "hosted_terms_section": "4.48",
    "preview_terms_url": PREVIEW_TERMS_URL, "live_use_blocked": True,
    "commercial_status": "blocked: preview licence permits internal testing, research and evaluation only",
}
DEFAULTS = {
    "duration": -1, "resolution": "1080p", "aspect_ratio": "adaptive", "audio": True,
    "prompt_extend": True, "watermark": False, "real_face_refs": False, "likeness_consent": False,
}
COMMON_RULES = {
    "duration": ArgumentRule(minimum=-1, maximum=30),
    "resolution": ArgumentRule(choices=RESOLUTIONS),
    "aspect_ratio": ArgumentRule(choices=ASPECT_RATIOS),
    "seed": ArgumentRule(minimum=-1, maximum=2147483647),
    "prompt": ArgumentRule(pattern=r"[\s\S]{1,20000}", pattern_hint="1 to 20000 characters including the edit or extend intent"),
    "source_duration_seconds": ArgumentRule(minimum=1, maximum=15),
    "source_fps": ArgumentRule(minimum=16),
}
ARGUMENT_RULES = {tool: dict(COMMON_RULES) for tool in GENERATING_TOOLS}
ARGUMENT_RULES["extend_wan3_video"]["direction"] = ArgumentRule(choices=("forward", "backward", "both"))
FIELD_DESCRIPTIONS = {
    "video_url": "Public HTTP(S) MP4/MOV source video URL without embedded credentials. Exactly one reference video is supported.",
    "prompt": "Edit or extend instruction. The adapter adds the required Video 1 intent to the prompt.",
    "source_duration_seconds": "Actual measured input video seconds from 1 to 15. Input seconds also incur cost; local field.",
    "source_fps": "Actual measured source frame rate, at least 16 fps; local field.",
    "duration": "Total output seconds from 2 to 30. Input plus output must be at most 30. Default -1 is smart duration with unknown cost, dry-run only. Extension output must exceed the source duration.",
    "direction": "Extend forward, backward, or both. Adds prompt text only; never a wire parameter.",
    "reference_image_urls": "Up to 10 public image references. No unpublished image input charge.",
    "reference_audio_urls": "Up to 5 public audio references totaling at most 15 seconds. Voice references require likeness_consent=true.",
    "reference_audio_durations": "Measured positive seconds for each audio reference, in matching order; local field.",
    "real_face_refs": "True when the source or references contain a real person's likeness; requires likeness_consent=true.",
    "likeness_consent": "Acknowledge the rights and consent for all referenced real likenesses and voices; local field.",
    "job_id": "Exact task UUID returned by a submit tool. Poll once per call; this never submits video work.",
    "download": "Save completed MP4 and provenance under RENDERHAUS_MEDIA_DIR. Defaults to true; cached downloads are reused.",
}


def validate_url(url: Any, field: str) -> str:
    if not isinstance(url, str) or url != url.strip() or any(character.isspace() for character in url):
        raise ValueError(f"{field} requires a public HTTP(S) URL.")
    parsed = urlsplit(url)
    if (parsed.scheme not in {"https", "http"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None or parsed.fragment):
        raise ValueError(f"{field} requires an HTTP(S) URL without credentials or fragments.")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{field} contains an invalid port.") from exc
    return url


def _positive_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{field} must be finite positive measured seconds or fps.")
    return value


def validate_arguments(tool: str, arguments: dict[str, Any]) -> None:
    if tool not in GENERATING_TOOLS:
        return
    args = {**DEFAULTS, **arguments}
    validate_url(args.get("video_url"), "video_url")
    prompt = args.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20000:
        raise ValueError("prompt must contain 1 to 20000 characters.")
    source = _positive_number(args.get("source_duration_seconds"), "source_duration_seconds")
    fps = _positive_number(args.get("source_fps"), "source_fps")
    if not 1 <= source <= 15 or fps < 16:
        raise ValueError("source_duration_seconds must be from 1 to 15 and source_fps must be at least 16.")
    duration = args["duration"]
    if type(duration) is not int or duration != -1 and not 2 <= duration <= 30:
        raise ValueError("duration must be -1 for a preview or an integer from 2 to 30.")
    if duration != -1 and Decimal(str(source)) + duration > 30:
        raise ValueError("Input plus output duration must be at most 30 seconds.")
    if args["resolution"] not in RESOLUTIONS or args["aspect_ratio"] not in ASPECT_RATIOS:
        raise ValueError("Invalid resolution or aspect_ratio.")
    for field in ("audio", "prompt_extend", "watermark", "real_face_refs", "likeness_consent"):
        if not isinstance(args[field], bool):
            raise ValueError(f"{field} must be boolean.")
    seed = args.get("seed")
    if seed is not None and (type(seed) is not int or not -1 <= seed <= 2147483647):
        raise ValueError("seed must be an integer from -1 to 2147483647.")
    for kind, maximum in (("image", 10), ("audio", 5)):
        field = f"reference_{kind}_urls"
        urls = args.get(field) or []
        if not isinstance(urls, list) or len(urls) > maximum:
            raise ValueError(f"{field} accepts at most {maximum} URLs.")
        for url in urls:
            validate_url(url, field)
    audios = args.get("reference_audio_urls") or []
    durations = args.get("reference_audio_durations") or []
    if not isinstance(durations, list) or len(durations) != len(audios):
        raise ValueError("reference_audio_durations requires one measured duration per reference URL.")
    for value in durations:
        _positive_number(value, "reference_audio_durations")
    if sum(Decimal(str(value)) for value in durations) > 15:
        raise ValueError("reference_audio_durations must total at most 15 seconds.")
    if (args["real_face_refs"] or audios) and not args["likeness_consent"]:
        raise ValueError("Real-person likeness and voice references require likeness_consent=true.")
    if tool == "extend_wan3_video":
        if args["aspect_ratio"] != "adaptive":
            raise ValueError("Extension aspect_ratio must be adaptive.")
        if args.get("direction", "forward") not in {"forward", "backward", "both"}:
            raise ValueError("direction must be forward, backward, or both.")
        if duration != -1 and duration <= source:
            raise ValueError("Extension duration is total output seconds and must exceed the source duration.")


def request_body(tool: str, arguments: dict[str, Any], model: str) -> dict[str, Any]:
    args = {**DEFAULTS, **arguments}
    prefix = "Edit Video 1" if tool == "edit_wan3_video" else f"Extend Video 1 {args.get('direction', 'forward')}"
    prompt = f"{prefix}: {args['prompt']}"
    if len(prompt) > 20000:
        raise ValueError("prompt plus edit or extend intent must be at most 20000 characters.")
    media = [{"type": "reference_video", "url": args["video_url"]}]
    for kind in ("image", "audio"):
        media.extend({"type": f"reference_{kind}", "url": url} for url in args.get(f"reference_{kind}_urls") or [])
    parameters = {name: args[name] for name in ("duration", "audio", "prompt_extend", "watermark")}
    seed = args.get("seed")
    parameters.update(resolution=args["resolution"].upper(), ratio=args["aspect_ratio"], seed=-1 if seed is None else seed)
    return {"model": model, "input": {"prompt": prompt, "media": media}, "parameters": parameters}


def price_cents(tool: str, arguments: dict[str, Any], *, region: str, model: str) -> Decimal:
    if tool not in GENERATING_TOOLS:
        raise ValueError("Unknown Model Studio generation tool.")
    if model != DEFAULT_MODEL:
        raise ValueError(f"UNVERIFIED Model Studio model {model}; price is unknown.")
    validate_arguments(tool, arguments)
    if arguments.get("duration", -1) == -1:
        raise ValueError("Model Studio smart duration cost is unknown; choose an explicit duration.")
    if region not in CENTS_PER_SECOND:
        raise ValueError("Unknown Model Studio pricing region.")
    seconds = Decimal(str(arguments["source_duration_seconds"])) + arguments["duration"]
    return CENTS_PER_SECOND[region][arguments.get("resolution", "1080p")] * seconds
