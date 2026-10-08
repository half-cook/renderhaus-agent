"""Wan VACE endpoint contracts and published pricing, checked 2026-10-08.

https://fal.ai/models/fal-ai/wan-vace-14b/api
https://fal.ai/models/fal-ai/wan-22-vace-fun-a14b/api
Each family also documents /inpainting, /outpainting, /reframe, /depth, /pose
at https://fal.ai/models/<endpoint-id>/api.

Weight licences:
https://github.com/ali-vilab/VACE
https://huggingface.co/alibaba-pai/Wan2.2-VACE-Fun-A14B
Hosted service terms: https://fal.ai/legal/terms-of-service
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from providers.contracts import ArgumentRule


MODELS = ("fal-ai/wan-vace-14b", "fal-ai/wan-22-vace-fun-a14b")
DEFAULT_MODEL = MODELS[0]
EDIT_MODES = ("freeform", "inpainting", "outpainting", "reframe", "depth", "pose")
RESOLUTIONS = ("auto", "240p", "360p", "480p", "580p", "720p")
ASPECT_RATIOS = ("auto", "16:9", "1:1", "9:16")
TRAINING_METADATA = {"training_eligible": True, "weights_license": "Apache-2.0"}
GENERATING_TOOLS = ("text_to_video", "image_to_video", "reference_to_video", "video_to_video")


@dataclass(frozen=True)
class Endpoint:
    id: str
    model: str
    mode: str
    optional_fields: frozenset[str]
    price_cents_per_video_second: dict[str, Decimal] | None

    @property
    def api_url(self) -> str:
        return f"https://fal.ai/models/{self.id}/api"


_MEDIA_FIELDS = frozenset({"first_frame_url", "last_frame_url"})
_MODE_FIELDS = {
    "freeform": _MEDIA_FIELDS
    | {"task", "video_url", "mask_video_url", "mask_image_url", "ref_image_urls", "preprocess"},
    "inpainting": _MEDIA_FIELDS
    | {"video_url", "mask_video_url", "mask_image_url", "ref_image_urls", "preprocess"},
    "outpainting": _MEDIA_FIELDS
    | {
        "video_url",
        "ref_image_urls",
        "expand_left",
        "expand_right",
        "expand_top",
        "expand_bottom",
        "expand_ratio",
    },
    "reframe": _MEDIA_FIELDS | {"video_url", "zoom_factor", "trim_borders"},
    "depth": _MEDIA_FIELDS | {"video_url", "ref_image_urls", "preprocess"},
    "pose": _MEDIA_FIELDS | {"video_url", "ref_image_urls", "preprocess"},
}
_RATES_21 = {"480p": Decimal("4"), "580p": Decimal("6"), "720p": Decimal("8")}
_RATES_22 = {"480p": Decimal("5"), "580p": Decimal("7.5"), "720p": Decimal("10")}
# Official per-model playground billing messages, 2026-10-08:
# https://fal.ai/models/fal-ai/wan-vace-14b (also each edit route)
# https://fal.ai/models/fal-ai/wan-22-vace-fun-a14b/depth (also inpainting/outpainting/reframe)
# These prices explicitly define video seconds at 16 frames per second.
# TODO: freeform 2.2 has pending compute-second pricing; zero is not a confirmed rate.
# TODO: 2.2 pose page says $0.10 at 720p but endpointBilling says $0.15/second.
# https://fal.ai/models/fal-ai/wan-22-vace-fun-a14b/pose
# TODO: auto/240p/360p pricing is not published. Do not interpolate a rate.
ENDPOINTS = {
    endpoint.id: endpoint
    for model in MODELS
    for mode in EDIT_MODES
    for endpoint in [
        Endpoint(
            id=model if mode == "freeform" else f"{model}/{mode}",
            model=model,
            mode=mode,
            optional_fields=frozenset(_MODE_FIELDS[mode]),
            price_cents_per_video_second=(
                _RATES_21
                if model == MODELS[0]
                else None
                if mode in {"freeform", "pose"}
                else _RATES_22
            ),
        )
    ]
}


COMMON_RULES = {
    "model": ArgumentRule(choices=MODELS),
    "num_frames": ArgumentRule(minimum=81, maximum=241),
    "frames_per_second": ArgumentRule(minimum=5, maximum=30),
    "resolution": ArgumentRule(choices=RESOLUTIONS),
    "aspect_ratio": ArgumentRule(choices=ASPECT_RATIOS),
}
ARGUMENT_RULES = {tool: dict(COMMON_RULES) for tool in GENERATING_TOOLS}
ARGUMENT_RULES["video_to_video"].update(
    {
        "edit_mode": ArgumentRule(choices=EDIT_MODES),
        "task": ArgumentRule(choices=EDIT_MODES[1:]),
        "expand_ratio": ArgumentRule(minimum=0, maximum=1),
    }
)


def endpoint_for(tool: str, arguments: dict[str, Any]) -> Endpoint:
    model = arguments.get("model", DEFAULT_MODEL)
    if model not in MODELS:
        raise ValueError(f"model must be one of {', '.join(MODELS)}.")
    mode = arguments.get("edit_mode", "depth") if tool == "video_to_video" else "freeform"
    endpoint_id = model if mode == "freeform" else f"{model}/{mode}"
    if endpoint_id not in ENDPOINTS:
        raise ValueError(f"Unsupported Wan VACE edit_mode: {mode}.")
    return ENDPOINTS[endpoint_id]


def validate_arguments(tool: str, arguments: dict[str, Any]) -> None:
    if tool not in GENERATING_TOOLS:
        return
    endpoint = endpoint_for(tool, arguments)
    if not str(arguments.get("prompt", "")).strip() and endpoint.mode != "reframe":
        raise ValueError("prompt must not be blank.")
    for field, value in arguments.items():
        if isinstance(value, (int, float)) and not math.isfinite(value):
            raise ValueError(f"{field} must be finite.")
        if field in set().union(*_MODE_FIELDS.values()) and field not in endpoint.optional_fields:
            raise ValueError(f"{field} is not supported by {endpoint.id}.")
        values = value if field == "ref_image_urls" else [value] if field.endswith("_url") else []
        for url in values:
            parsed = urlsplit(url)
            if not (
                (parsed.scheme in {"http", "https"} and parsed.netloc) or url.startswith("data:")
            ):
                raise ValueError(f"{field} requires a public HTTP(S) URL or data URI.")
    if tool == "reference_to_video" and not arguments.get("ref_image_urls"):
        raise ValueError("reference_to_video requires at least one reference image.")
    if tool == "video_to_video" and endpoint.mode == "freeform" and not arguments.get("task"):
        raise ValueError("Freeform video editing requires an explicit task; fal defaults to depth.")
    if (endpoint.mode == "inpainting" or arguments.get("task") == "inpainting") and not (
        arguments.get("mask_video_url") or arguments.get("mask_image_url")
    ):
        raise ValueError("inpainting requires mask_video_url or mask_image_url.")
    if (
        arguments.get("task")
        and arguments["task"] != "inpainting"
        and (arguments.get("mask_video_url") or arguments.get("mask_image_url"))
    ):
        raise ValueError("Use task=inpainting when supplying a freeform mask.")
    if arguments.get("mask_video_url") and arguments.get("mask_image_url"):
        raise ValueError("Choose one mask. fal documents differing precedence across endpoints.")
    if endpoint.mode == "outpainting" and not any(
        arguments.get(f"expand_{side}") for side in ("left", "right", "top", "bottom")
    ):
        raise ValueError("outpainting requires at least one expansion side.")


def request_body(tool: str, arguments: dict[str, Any]) -> tuple[Endpoint, dict[str, Any]]:
    endpoint = endpoint_for(tool, arguments)
    body = {
        key: value
        for key, value in arguments.items()
        if key not in {"model", "edit_mode"} and value is not None
    }
    # Reframe defaults match input length/fps; disable both so the quote matches num_frames.
    body.update(match_input_num_frames=False, match_input_frames_per_second=False)
    return endpoint, body


def price_cents(endpoint: Endpoint, resolution: str, num_frames: int) -> Decimal:
    rates = endpoint.price_cents_per_video_second or {}
    if resolution not in rates:
        raise ValueError(
            f"TODO: Confirm official fal pricing for {endpoint.id} at {resolution} before live use."
        )
    return rates[resolution] * Decimal(num_frames) / Decimal(16)
