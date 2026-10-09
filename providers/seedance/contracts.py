"""Seedance contracts verified from official APIs on 2026-10-09.

https://fal.ai/models/bytedance/seedance-2.5/us/reference-to-video/api
https://fal.ai/models/bytedance/seedance-2.5/us/image-to-video/api
https://fal.ai/models/bytedance/seedance-2.5/us/text-to-video/api
https://docs.byteplus.com/en/docs/modelark/create-video-generation-task-api
https://docs.byteplus.com/zh-CN/docs/modelark/create-video-generation-task-api?redirect=1
https://docs.byteplus.com/en/docs/modelark/seedance-2-5
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
import re
from typing import Any
from urllib.parse import urlsplit

from providers.contracts import ArgumentRule


MODEL_25 = "dreamina-seedance-2-5-260628"
MODEL_15 = "seedance-1-5-pro-251215"
GENERATING_TOOLS = ("text_to_video", "image_to_video", "reference_to_video", "edit_video", "extend_video")
RESOLUTIONS = ("480p", "720p", "1080p")
# Official BytePlus edit/extend limits, read 2026-10-09. Use the stricter source
# range on fal too; its generic references allow 1.8-30.2 seconds.
SOURCE_DURATION_LIMITS = {"edit_video": (4, 30), "extend_video": (2, 30)}
ASPECT_RATIOS = ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive")
FAL_ROUTES = {"text_to_video": "text-to-video", "image_to_video": "image-to-video",
              "reference_to_video": "reference-to-video", "edit_video": "reference-to-video",
              "extend_video": "reference-to-video"}
TRAINING_METADATA = {
    "training_eligible": False, "weights_license": "closed-weights", "license": "service-terms",
    "hosted_terms_url": "https://fal.ai/legal/terms-of-service",
}
BYTEPLUS_TERMS_URL = "https://docs.byteplus.com/en/docs/legal/docs-service-specific-terms"


@dataclass(frozen=True)
class Endpoint:
    id: str

    @property
    def model(self) -> str:
        return self.id

    @property
    def api_url(self) -> str:
        return f"https://fal.ai/models/{self.id}/api"


ENDPOINTS = {f"bytedance/seedance-2.5/{prefix}{route}": Endpoint(f"bytedance/seedance-2.5/{prefix}{route}")
             for prefix in ("", "us/") for route in set(FAL_ROUTES.values())}
_COMMON_RULES = {
    "duration_seconds": ArgumentRule(minimum=4, maximum=30),
    "aspect_ratio": ArgumentRule(choices=ASPECT_RATIOS),
    "resolution": ArgumentRule(choices=RESOLUTIONS),
    "service_tier": ArgumentRule(choices=("default", "flex")),
    "seed": ArgumentRule(minimum=0, maximum=2147483647),
    "prompt": ArgumentRule(pattern=r"[\s\S]{1,20000}", pattern_hint="1 to 20000 characters"),
}
ARGUMENT_RULES = {tool: dict(_COMMON_RULES) for tool in GENERATING_TOOLS}
ARGUMENT_RULES["edit_video"]["duration_seconds"] = ArgumentRule(choices=(-1,))
FIELD_DESCRIPTIONS = {
    "aspect_ratio": "Requested output aspect for text/reference generation and legacy BytePlus 1.5. Seedance 2.5 image animation, editing, and extension preserve the source aspect automatically; supply source_aspect_ratio for a known cost estimate.",
    "duration_seconds": "Output duration from 4 to 30 integer seconds per call. Edit uses -1 to preserve the measured source duration. Extension requests generated output seconds. Whether extension output includes the source or only the continuation is UNVERIFIED; never infer an appended increment or a final stitched length.",
    "real_face_refs": "True when a reference contains a real person's likeness. Seedance rejects these inputs; route generation to Wan with consent.",
    "user_supplied_real_person_refs": "True for user-supplied real-person photos or videos. These inputs are forbidden for Seedance, even with consent.",
    "reference_image_urls": "Up to 30 reference images. Refer to them as @Image1, @Image2 in the prompt.",
    "reference_video_urls": "Up to 10 reference videos, 1.8 to 30.2 seconds each and at most 30.2 seconds combined on fal.",
    "reference_audio_urls": "Up to 10 reference audio clips, 1.8 to 30.2 seconds each and at most 30.2 seconds combined on fal.",
    "reference_video_durations": "Measured seconds for each video URL. Required with video references; local validation and billing only.",
    "reference_video_fps": "Measured fps for each video URL. Each fal reference must be 24 to 60 fps; local only.",
    "reference_audio_durations": "Measured seconds for each audio URL. Required with audio references; local only.",
    "source_duration_seconds": "Measured source seconds, from 4 to 30 for editing or 2 to 30 for extension. fal bills these input seconds plus requested output seconds with the video-input discount; BytePlus video-input quotes remain unknown until its minimum token floor is verified. Local only.",
    "source_fps": "Measured source fps, from 24 to 60 on fal; local only.",
    "watermark": "BytePlus visible watermark, enabled by default. fal has no watermark request field; this argument is not sent to fal and does not guarantee a fal watermark.",
    "service_tier": "BytePlus default or flex for 1.5. Seedance 2.5 rejects flex. Not sent to fal.",
    "source_aspect_ratio": "Measured input aspect ratio, such as 16:9 or 1280:720. Required for a known cost estimate when the provider derives output aspect from the source; local only.",
    "model": "Optional configured model override. Seedance 1.5 is BytePlus only. Unknown models remain UNVERIFIED and dry-run only.",
}


def transport() -> str:
    selected = os.getenv("SEEDANCE_TRANSPORT", "fal")
    if selected not in {"fal", "byteplus"}:
        raise ValueError("SEEDANCE_TRANSPORT must be fal or byteplus.")
    return selected


def fal_region() -> str:
    selected = os.getenv("SEEDANCE_FAL_REGION", "us")
    if selected not in {"us", "global"}:
        raise ValueError("SEEDANCE_FAL_REGION must be us or global.")
    return selected


def configured_model(arguments: dict[str, Any]) -> str:
    return arguments.get("model") or os.getenv("SEEDANCE_MODEL") or MODEL_25


def effective_model(tool: str, arguments: dict[str, Any]) -> str:
    selected = configured_model(arguments)
    if transport() == "byteplus":
        return selected
    if selected == MODEL_15:
        raise ValueError("Seedance 1.5 requires SEEDANCE_TRANSPORT=byteplus.")
    if selected != MODEL_25:
        return selected
    prefix = "us/" if fal_region() == "us" else ""
    return f"bytedance/seedance-2.5/{prefix}{FAL_ROUTES[tool]}"


def verified_model(tool: str, arguments: dict[str, Any]) -> bool:
    model = effective_model(tool, arguments)
    if transport() == "fal":
        return model in ENDPOINTS and model.endswith("/" + FAL_ROUTES[tool])
    return model in {MODEL_25, MODEL_15}


def _media_reference(value: str, field: str, *, local_image: bool = False) -> None:
    parsed = urlsplit(value)
    if ((parsed.scheme in {"http", "https"} and parsed.netloc and not parsed.username and not parsed.password)
            or value.startswith("data:")):
        return
    if local_image and not parsed.scheme and value.strip():
        return
    raise ValueError(f"{field} requires an HTTP(S) URL or data URI without embedded credentials.")


def _measurements(arguments: dict[str, Any], kind: str) -> None:
    urls = arguments.get(f"reference_{kind}_urls") or []
    field = f"reference_{kind}_durations"
    durations = arguments.get(field) or []
    if len(durations) != len(urls):
        raise ValueError(f"{field} must have one measured duration per reference URL.")
    minimum, maximum = (2, 30) if transport() == "byteplus" else (1.8, 30.2)
    if any(not math.isfinite(value) or not minimum <= value <= maximum for value in durations):
        raise ValueError(f"{field} values must be {minimum} to {maximum} seconds.")
    if sum(durations) > maximum:
        raise ValueError(f"{field} combined duration must be at most {maximum} seconds.")
    if kind == "video":
        fps = arguments.get("reference_video_fps") or []
        if len(fps) != len(urls) or any(not math.isfinite(value) or not 24 <= value <= 60 for value in fps):
            raise ValueError("reference_video_fps requires one measured value from 24 to 60 per video.")


def validate_arguments(tool: str, arguments: dict[str, Any]) -> None:
    if tool not in GENERATING_TOOLS:
        return
    if arguments.get("real_face_refs") or arguments.get("user_supplied_real_person_refs"):
        raise ValueError("Seedance rejects real-person face references. Use Wan with likeness consent for generation; refuse unsupported editing or extension.")
    host = transport()
    model = effective_model(tool, arguments)
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", model) or ".." in model:
        raise ValueError("Invalid configured Seedance model identifier.")
    if configured_model(arguments) != MODEL_15 and arguments.get("service_tier") == "flex":
        raise ValueError("Seedance 2.5 does not support service_tier=flex.")
    if configured_model(arguments) == MODEL_15:
        if tool not in {"text_to_video", "image_to_video"}:
            raise ValueError("Seedance 1.5 supports text/image-to-video only.")
        if arguments.get("duration_seconds", 5) > 12:
            raise ValueError("Seedance 1.5 duration_seconds must be at most 12.")
    source_ratio = arguments.get("source_aspect_ratio")
    if source_ratio is not None:
        try:
            width, height = (float(part) for part in source_ratio.split(":"))
        except (ValueError, AttributeError) as exc:
            raise ValueError("source_aspect_ratio must be a measured WIDTH:HEIGHT ratio.") from exc
        if not all(math.isfinite(value) and value > 0 for value in (width, height)) or not 0.4 <= width / height <= 2.5:
            raise ValueError("source_aspect_ratio must be positive and within 0.4 to 2.5.")
    total = 1 if tool in {"edit_video", "extend_video"} else 0
    for kind, maximum in (("image", 30), ("video", 10), ("audio", 10)):
        field = f"reference_{kind}_urls"
        urls = arguments.get(field) or []
        total += len(urls)
        if len(urls) > maximum:
            raise ValueError(f"{field} accepts at most {maximum} references.")
        for value in urls:
            _media_reference(value, field)
    if total > 50:
        raise ValueError("Seedance references accept at most 50 total files.")
    _measurements(arguments, "video")
    _measurements(arguments, "audio")
    for field in ("image_path_or_url", "end_image_path_or_url"):
        if arguments.get(field):
            _media_reference(arguments[field], field, local_image=True)
    if tool in {"edit_video", "extend_video"}:
        _media_reference(arguments["video_url"], "video_url")
        duration = arguments["source_duration_seconds"]
        fps = arguments["source_fps"]
        minimum, maximum = SOURCE_DURATION_LIMITS[tool]
        if not math.isfinite(duration) or not minimum <= duration <= maximum:
            raise ValueError(f"source_duration_seconds must be measured and from {minimum} to {maximum}.")
        if not math.isfinite(fps) or not 24 <= fps <= 60:
            raise ValueError("source_fps must be measured and from 24 to 60.")
    if host == "byteplus" and configured_model(arguments) != MODEL_15 and arguments.get("reference_audio_urls"):
        if not (arguments.get("reference_image_urls") or arguments.get("reference_video_urls") or arguments.get("video_url")):
            raise ValueError("BytePlus audio references require image or video references.")


def byteplus_platform_blocker() -> str | None:
    region = os.getenv("RENDERHAUS_CUSTOMER_REGION", "").strip().lower()
    if region in {"us", "usa", "united states", "united-states", "united_states"}:
        return "BytePlus Seedance is unavailable to US customers or end users; use fal US-hosted endpoints."
    if not region:
        return "BytePlus customer region is unknown. Set RENDERHAUS_CUSTOMER_REGION to a permitted non-US region before live use."
    if os.getenv("SEEDANCE_BYTEPLUS_PLATFORM_AUTHORIZED", "false").lower() != "true":
        return "BytePlus requires written platform authorization for UGC integration or API resale."
    return None


def live_blocker(tool: str, arguments: dict[str, Any]) -> str | None:
    if not verified_model(tool, arguments):
        return "UNVERIFIED Seedance model/API identifier; dry-run only."
    if transport() == "byteplus":
        blocker = byteplus_platform_blocker()
        if blocker:
            return blocker
        if arguments.get("reference_video_urls") or tool in {"edit_video", "extend_video"}:
            return "UNVERIFIED BytePlus reference-video minimum billing floor; cost estimate unknown, dry-run only."
    return None


def output_aspect_ratio(tool: str, arguments: dict[str, Any]) -> str:
    if tool in {"edit_video", "extend_video"}:
        return "adaptive"
    if tool == "image_to_video" and (transport() == "fal" or configured_model(arguments) == MODEL_25):
        return "adaptive"
    return arguments.get("aspect_ratio", "16:9")


def request_body(tool: str, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    model = effective_model(tool, arguments)
    ratio = output_aspect_ratio(tool, arguments)
    duration = arguments.get("duration_seconds", -1 if tool == "edit_video" else 5)
    task = {"reference_to_video": "reference", "edit_video": "editing", "extend_video": "extension"}.get(tool)
    if transport() == "fal":
        body: dict[str, Any] = {
            "prompt": arguments["prompt"], "resolution": arguments.get("resolution", "720p"),
            "duration": "auto" if duration == -1 else str(duration),
            "aspect_ratio": "auto" if ratio == "adaptive" else ratio,
            "generate_audio": arguments.get("generate_audio", True),
        }
        if tool == "image_to_video":
            body["image_url"] = arguments["image_path_or_url"]
            if arguments.get("end_image_path_or_url"):
                body["end_image_url"] = arguments["end_image_path_or_url"]
        if task:
            body["task"] = task
            for kind in ("image", "video", "audio"):
                urls = arguments.get(f"reference_{kind}_urls") or []
                if kind == "video" and tool in {"edit_video", "extend_video"}:
                    urls = [arguments["video_url"], *urls]
                if urls:
                    body[f"{kind}_urls"] = urls
        if arguments.get("seed") is not None:
            body["seed"] = arguments["seed"]
        return model, body
    content = [{"type": "text", "text": arguments["prompt"]}]
    if tool == "image_to_video":
        content.append({"type": "image_url", "image_url": {"url": arguments["image_path_or_url"]}, "role": "first_frame"})
        if arguments.get("end_image_path_or_url"):
            content.append({"type": "image_url", "image_url": {"url": arguments["end_image_path_or_url"]}, "role": "last_frame"})
    for kind in ("image", "video", "audio"):
        urls = arguments.get(f"reference_{kind}_urls") or []
        if kind == "video" and tool in {"edit_video", "extend_video"}:
            urls = [arguments["video_url"], *urls]
        for url in urls:
            content.append({"type": f"{kind}_url", f"{kind}_url": {"url": url}, "role": f"reference_{kind}"})
    body = {
        "model": model, "content": content, "ratio": ratio,
        "duration": duration, "resolution": arguments.get("resolution", "720p"),
        "watermark": arguments.get("watermark", True), "generate_audio": arguments.get("generate_audio", True),
    }
    if task:
        body["omni_reference_task_type"] = {"reference": "reference", "editing": "edit", "extension": "extend"}[task]
    if arguments.get("service_tier") is not None:
        body["service_tier"] = arguments["service_tier"]
    if arguments.get("seed") is not None:
        body["seed"] = arguments["seed"]
    return model, body
