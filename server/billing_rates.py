"""Real-dollar cost table for generation calls, in integer cents.

No credit abstraction: cost_for() returns what the provider actually
charges us plus a disclosed platform fee, both shown to the user. Every
call to POST /api/studio/invoke is a real generation request (the live
model/voice lists in the /options route go through a separate path and
are never charged); see its use in invoke_tool, server/studio.py.

Sourced from each provider's own published pricing where available
(BytePlus's own blog for Seedance's token formula and worked examples;
BytePlus/aggregator figures for Seedream; Fish Audio's own docs for its
per-character rate) as of 2026-08. These are list prices, not your
negotiated/actual invoiced rates -- swap in real numbers from your
provider dashboards or contracts when you have them. Nothing here was
fabricated to look precise; where a provider's real rate is genuinely
account-dependent, the comment says so. ElevenLabs write quotes must be configured
explicitly before enabling Stripe billing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import math
import os
from typing import Any

from providers.alibaba_modelstudio import contracts as modelstudio_contracts

# Flat percentage added on top of the provider's own cost. A tunable
# constant, not logic -- change PLATFORM_FEE_RATE to retune margin
# everywhere at once. MIN_FEE_CENTS keeps very cheap calls (e.g. a tiny
# TTS clip) from carrying a $0.00 fee that rounds away to nothing.
PLATFORM_FEE_RATE = 0.30
MIN_FEE_CENTS = 1


@dataclass(frozen=True)
class GenerationCost:
    provider_cents: int
    fee_cents: int

    @property
    def total_cents(self) -> int:
        return self.provider_cents + self.fee_cents

    def public(self) -> dict[str, int]:
        return {
            "provider_cents": self.provider_cents,
            "fee_cents": self.fee_cents,
            "total_cents": self.total_cents,
        }


def _with_fee(provider_cents: int) -> GenerationCost:
    fee = max(MIN_FEE_CENTS, round(provider_cents * PLATFORM_FEE_RATE))
    return GenerationCost(provider_cents=max(0, provider_cents), fee_cents=fee)


# -- Seedance (video) ---------------------------------------------------
# BytePlus's own worked example (1080p 16:9, 5s = $0.612, 10s = $1.224)
# reverse-engineers almost exactly to $0.0025 per 1,000 tokens at 24fps,
# tokens = width * height * fps * duration_seconds / 1024. Verified this
# formula against both of BytePlus's published numbers before using it --
# see the conversation this shipped in for the arithmetic.
# https://www.byteplus.com/en/blog/seedance-1-0-pro-guide-api-pricing
SEEDANCE_TOKEN_RATE_CENTS_PER_1K = 0.25  # $0.0025 = 0.25 cents
SEEDANCE_FPS = 24

# Matches studio/lib/canvas/story.ts's RESOLUTION_SHORT_SIDE -- same short
# side, so a node's on-canvas size and its billed cost agree on what
# "1080p" etc. actually mean.
RESOLUTION_SHORT_SIDE = {
    "480p": 480,
    "720p": 720,
    "1080p": 1080,
    "1K": 1024,
    "2K": 2048,
    "3K": 3072,
}


def _video_dimensions(resolution: str, aspect_ratio: str) -> tuple[int, int]:
    short_side = RESOLUTION_SHORT_SIDE.get(resolution, 720)
    try:
        rw_s, rh_s = aspect_ratio.split(":")
        rw, rh = float(rw_s), float(rh_s)
    except (ValueError, AttributeError):
        rw, rh = 16.0, 9.0  # "adaptive" or unrecognized -- assume 16:9
    is_portrait = rh > rw
    if is_portrait:
        width, height = short_side, round(short_side * rh / rw)
    else:
        width, height = round(short_side * rw / rh), short_side
    return width, height


def _seedance_cost(arguments: dict[str, Any]) -> GenerationCost:
    resolution = str(arguments.get("resolution") or "720p")
    aspect_ratio = str(arguments.get("aspect_ratio") or "16:9")
    duration = arguments.get("duration_seconds")
    duration_seconds = float(duration) if isinstance(duration, (int, float)) and duration else 5.0
    width, height = _video_dimensions(resolution, aspect_ratio)
    tokens = width * height * SEEDANCE_FPS * duration_seconds / 1024
    provider_cents = round(tokens / 1000 * SEEDANCE_TOKEN_RATE_CENTS_PER_1K)
    return _with_fee(provider_cents)


# -- Seedream (image) ----------------------------------------------------
# $0.035/image is Seedream 5.0 Lite's published rate (our default model,
# SEEDREAM_MODEL) and doesn't publicly vary by size -- Seedream 5.0 Pro's
# published pricing DOES step up at ~2.36MP (roughly our "2K"), so this
# applies that same shape to Lite as a reasoned estimate, not a confirmed
# Lite-specific tier. Worth confirming against a real invoice.
SEEDREAM_COST_CENTS_BY_SIZE = {"1K": 3.5, "2K": 5.0, "3K": 7.0}


def _seedream_cost(arguments: dict[str, Any]) -> GenerationCost:
    size = str(arguments.get("size") or "2K")
    provider_cents = round(SEEDREAM_COST_CENTS_BY_SIZE.get(size, 3.5))
    return _with_fee(provider_cents)


# Runway developer pricing verified 2026-10-08.
# https://docs.dev.runwayml.com/guides/pricing/
# One credit is $0.01. Default MP4 only; no professional-format surcharge.
RUNWAY_CENTS_PER_SECOND = {"gen4.5": 12, "aleph2": 28}
RUNWAY_IMAGE_CENTS = {"gen4_image": {"720p": 5, "1080p": 8}, "gen4_image_turbo": 2}


def _runway_cost(tool: str, arguments: dict[str, Any]) -> GenerationCost:
    from providers.runway.api import dry_run
    from providers.runway.contracts import IMAGE_720_RATIOS, IMAGE_1080_RATIOS

    if tool in {"get_runway_task", "list_runway_models"}:
        return GenerationCost(0, 0)
    if tool in {"text_to_video", "image_to_video", "video_to_video"}:
        edit = tool == "video_to_video"
        model = arguments.get("model") or ("aleph2" if edit else "gen4.5")
        if model != ("aleph2" if edit else "gen4.5"):
            raise ValueError("Unsupported Runway model for this video tool.")
        duration = arguments.get("video_duration_seconds") if edit else arguments.get("duration_seconds", 5)
        if (
            isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isfinite(duration)
            or not 2 <= duration <= (30 if edit else 10)
            or (not edit and not isinstance(duration, int))
        ):
            raise ValueError("Supply a valid Runway duration before quoting cost.")
        # Aleph preserves input duration. This quote uses the caller's measured duration.
        # TODO: reconcile fractional-second charging against a real task cost/invoice.
        cents = math.ceil(duration * RUNWAY_CENTS_PER_SECOND[model])
    elif tool in {"text_to_image", "image_to_image"}:
        model = arguments.get("model") or "gen4_image"
        ratio = arguments.get("ratio") or "1280:720"
        if ratio not in IMAGE_720_RATIOS + IMAGE_1080_RATIOS:
            # TODO: official pricing does not map legacy dimensions to resolution tiers.
            raise ValueError("Runway pricing is unconfirmed for these image dimensions.")
        if model == "gen4_image":
            cents = RUNWAY_IMAGE_CENTS[model]["720p" if ratio in IMAGE_720_RATIOS else "1080p"]
        elif model == "gen4_image_turbo" and tool == "image_to_image":
            cents = RUNWAY_IMAGE_CENTS[model]
        else:
            raise ValueError("Unsupported Runway model for this image tool.")
    else:
        raise ValueError("Unknown Runway tool. No fallback price is available.")
    return GenerationCost(0, 0) if dry_run() else _with_fee(cents)


# -- Fish Audio (voice) ---------------------------------------------------
# $15 per 1,000,000 UTF-8 bytes, from Fish Audio's own pricing docs --
# applies to the standard paid models. Our configured default,
# s2.1-pro-free, is a genuinely free tier (the name says so), so it's
# charged as $0 provider cost -- the platform fee's MIN_FEE_CENTS floor
# still applies, so it's not literally free to the user.
FISH_AUDIO_RATE_CENTS_PER_BYTE = 15 * 100 / 1_000_000  # $15/1M bytes, in cents
FISH_AUDIO_FREE_MODELS = {"s2.1-pro-free"}


def _fish_audio_cost(arguments: dict[str, Any]) -> GenerationCost:
    model = str(arguments.get("model") or "s2.1-pro-free")
    if model in FISH_AUDIO_FREE_MODELS:
        return _with_fee(0)
    text = str(arguments.get("text") or "")
    byte_count = len(text.encode("utf-8"))
    provider_cents = round(byte_count * FISH_AUDIO_RATE_CENTS_PER_BYTE)
    return _with_fee(provider_cents)


# -- Remotion (render) -----------------------------------------------------
# Lambda compute time, not a per-call API price -- no public per-unit rate
# to cite. Flat placeholder pending real Lambda billing data.
REMOTION_COST_CENTS = 8

# Official API list prices, USD/second, checked 2026-10-08.
# https://kling.ai/document-api/pricing/base/video
# Native audio prices exclude voice control; Omni prices exclude reference videos.
# TODO: Turbo lists only native-audio prices, but its current request schema has no
# audio control. Its default audio semantics remain unconfirmed, so do not quote it.
KLING_RATES_USD_PER_SECOND = {
    ("kling-3.0", False): {"720p": "0.084", "1080p": "0.112", "4k": "0.42"},
    ("kling-3.0", True): {"720p": "0.126", "1080p": "0.168", "4k": "0.42"},
    ("kling-3.0-omni", False): {"720p": "0.084", "1080p": "0.112", "4k": "0.42"},
    ("kling-3.0-omni", True): {"720p": "0.112", "1080p": "0.14", "4k": "0.42"},
}
KLING_GENERATION_TOOLS = frozenset({"text_to_video", "image_to_video", "omni_video"})
KLING_READ_TOOLS = frozenset({"get_video_task", "list_kling_models"})


def _kling_cost(tool: str, arguments: dict[str, Any]) -> GenerationCost:
    if tool in KLING_READ_TOOLS:
        return GenerationCost(0, 0)
    if tool not in KLING_GENERATION_TOOLS:
        raise ValueError("Unknown Kling tool.")
    model = arguments.get("model")
    if tool == "omni_video":
        model = "kling-3.0-omni"
    elif model is None or model == "":
        model = os.getenv("KLING_MODEL") or "kling-3.0"
    allowed_models = (
        {"kling-3.0-omni"} if tool == "omni_video" else {"kling-3.0", "kling-3.0-turbo"}
    )
    if not isinstance(model, str) or model not in allowed_models:
        raise ValueError("Unsupported Kling model for this tool.")
    resolution = arguments.get("resolution", "720p")
    audio = arguments.get("generate_audio", False)
    duration = arguments.get("duration_seconds", 5)
    if (
        not isinstance(resolution, str)
        or resolution not in {"720p", "1080p", "4k"}
        or not isinstance(audio, bool)
    ):
        raise ValueError("Invalid Kling resolution or generate_audio.")
    if not isinstance(duration, int) or isinstance(duration, bool) or not 3 <= duration <= 15:
        raise ValueError("Kling duration_seconds must be an integer from 3 to 15.")
    if os.getenv("KLING_DRY_RUN", "true").lower() != "false":
        return GenerationCost(0, 0)
    rates = KLING_RATES_USD_PER_SECOND.get((model, audio))
    if rates is None:
        raise ValueError("Kling Turbo pricing is unconfirmed for the documented API audio behavior.")
    provider_cents = round(Decimal(rates[resolution]) * duration * 100)
    return _with_fee(provider_cents)


# Status/download polls, not generations -- the canvas calls these
# immediately after dispatch and then every ~2.5s until the underlying job
# reaches a terminal state. Pricing them like a fresh call would charge one
# job repeatedly (and could exhaust the balance mid-poll, returning 402 for
# a job that was already paid for and completed on the provider's side).
POLLING_TOOLS = {"get_video_task", "query_music_task", "get_music_task", "get_render_progress"}

# SDR Ray 3.2 list prices, verified 2026-10-08 against the official API pricing reference.
# https://docs.agents.lumalabs.ai/guides/pricing/
# The marketing table at https://lumalabs.ai/api disagrees on some edit rates.
# This table follows the detailed API reference; confirm against invoices before rollout.
LUMA_GENERATION_CENTS = {
    "360p": {5: 6, 10: 18},
    "540p": {5: 15, 10: 45},
    "720p": {5: 30, 10: 90},
    "1080p": {5: 120, 10: 360},
}
LUMA_EDIT_CENTS = {
    "360p": {5: 54, 10: 108},
    "540p": {5: 72, 10: 144},
    "720p": {5: 108, 10: 216},
    "1080p": {5: 216, 10: 432},
}
LUMA_EXTEND_CENTS = {"540p": 15, "720p": 30, "1080p": 120}


# fal Q4 rates per video second, checked 2026-10-08 on these pricing pages:
# https://fal.ai/models/fal-ai/vidu/q4/image-to-video
# https://fal.ai/models/fal-ai/vidu/q4/reference-to-video
# Both pages list 30% off through November 30 with no R2V audio surcharge.
# The user bound the omitted year to 2026 and the cutoff to inclusive UTC dates.
VIDU_Q4_PROMO_EXPIRES_ON = date(2026, 11, 30)
VIDU_Q4_PROMO_CENTS_PER_SECOND = {
    "540p": Decimal("3.15"),
    "720p": Decimal("6.65"),
    "1080p": Decimal("8.4"),
    "2K": Decimal("13.3"),
    "4K": Decimal("27.3"),
}
VIDU_Q4_LIST_CENTS_PER_SECOND = {
    "540p": Decimal("4.5"),
    "720p": Decimal("9.5"),
    "1080p": Decimal("12"),
    "2K": Decimal("19"),
    "4K": Decimal("39"),
}


def vidu_q4_rates(*, as_of: date | None = None) -> dict[str, Decimal]:
    """Provider cents per video second, using the inclusive UTC promotion cutoff."""
    day = as_of if as_of is not None else datetime.now(timezone.utc).date()
    rates = (
        VIDU_Q4_PROMO_CENTS_PER_SECOND
        if day <= VIDU_Q4_PROMO_EXPIRES_ON
        else VIDU_Q4_LIST_CENTS_PER_SECOND
    )
    return dict(rates)


def vidu_q4_price_cents(arguments: dict[str, Any], *, as_of: date | None = None) -> Decimal:
    """Quote Q4 native settings without requiring media for an intent proposal."""
    from providers.fal.vidu import TOOL_ENDPOINTS

    duration = arguments.get("duration", 5)
    resolution = arguments.get("resolution", "720p")
    audio = arguments.get("audio", False)
    if not isinstance(duration, int) or isinstance(duration, bool) or not 3 <= duration <= 16:
        raise ValueError("Vidu Q4 duration must be an integer from 3 to 16.")
    rates = vidu_q4_rates(as_of=as_of)
    if not isinstance(resolution, str) or resolution not in rates:
        raise ValueError("Invalid Vidu Q4 resolution.")
    if not isinstance(audio, bool):
        raise ValueError("Vidu Q4 audio must be boolean.")
    if "model" in arguments and arguments["model"] not in TOOL_ENDPOINTS.values():
        raise ValueError("Unsupported Vidu Q4 model identity.")
    return rates[resolution] * duration


# Official fal Wan 3 pricing and reference-video billing, read 2026-10-09:
# https://fal.ai/wan-3
# https://fal.ai/models/alibaba/wan-3.0/reference-to-video/api
WAN3_CENTS_PER_SECOND = {"480p": Decimal("5"), "720p": Decimal("10"), "1080p": Decimal("20")}
WAN3_PRICING_URL = "https://fal.ai/wan-3"
WAN3_PRICING_READ_DATE = "2026-10-09"

MODELSTUDIO_CENTS_PER_SECOND = modelstudio_contracts.CENTS_PER_SECOND
MODELSTUDIO_PRICING_URL = modelstudio_contracts.PRICING_URL
MODELSTUDIO_PRICING_READ_DATE = "2026-10-09"

def modelstudio_price_cents(tool: str, arguments: dict[str, Any], *, region: str | None = None) -> Decimal:
    """Quote documented regional input-plus-output billing, before the platform fee."""
    from providers.alibaba_modelstudio import api, config, contracts

    configuration = config.settings()
    model = arguments.get("model", configuration.model)
    if model != configuration.model:
        raise ValueError("Model Studio quote model must match DASHSCOPE_MODEL.")
    cleaned = api._validated(tool, {key: value for key, value in arguments.items() if key != "model"})
    return contracts.price_cents(tool, cleaned, region=region or configuration.region, model=model)


def _modelstudio_cost(tool: str, arguments: dict[str, Any]) -> GenerationCost:
    from providers.alibaba_modelstudio import api, config

    if tool == "get_task":
        return GenerationCost(0, 0)
    if tool not in {"edit_wan3_video", "extend_wan3_video"}:
        raise ValueError("Unknown Model Studio tool.")
    configuration = config.settings()
    if arguments.get("model", configuration.model) != configuration.model:
        raise ValueError("Model Studio quote model must match DASHSCOPE_MODEL.")
    cleaned = api._validated(tool, {key: value for key, value in arguments.items() if key != "model"})
    if config.dry_run():
        return GenerationCost(0, 0)
    blocker = config.live_blocker()
    if blocker:
        raise ValueError(blocker)
    quote_arguments = {**cleaned, "model": configuration.model}
    return _with_fee(round(modelstudio_price_cents(tool, quote_arguments)))


def wan3_price_cents(arguments: dict[str, Any]) -> Decimal:
    """Quote output plus measured reference-video seconds without fetching media."""
    duration = arguments.get("duration", 5)
    if duration is None:
        raise ValueError("Wan 3 smart duration billing is unknown; choose an explicit duration.")
    if type(duration) is not int or not 2 <= duration <= 30:
        raise ValueError("Wan 3 duration must be an integer from 2 to 30.")
    resolution = arguments.get("resolution", "1080p")
    if not isinstance(resolution, str) or resolution not in WAN3_CENTS_PER_SECOND:
        raise ValueError("Invalid Wan 3 resolution.")
    if not isinstance(arguments.get("audio", True), bool):
        raise ValueError("Wan 3 audio must be boolean.")
    model = arguments.get("model")
    if model is not None and model not in {
        "alibaba/wan-3.0/text-to-video", "alibaba/wan-3.0/image-to-video",
        "alibaba/wan-3.0/reference-to-video",
    }:
        raise ValueError("Unsupported Wan 3 model identity.")
    videos = arguments.get("reference_video_urls") or []
    measurements = arguments.get("reference_video_durations") or []
    if not isinstance(videos, list) or not isinstance(measurements, list) or len(videos) > 5 or len(videos) != len(measurements):
        raise ValueError("Wan 3 reference video durations must match the reference videos.")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or
           not math.isfinite(value) or value <= 0 for value in measurements):
        raise ValueError("Wan 3 reference video durations must be finite positive seconds.")
    input_seconds = sum(Decimal(str(value)) for value in measurements)
    if input_seconds > 15:
        raise ValueError("Wan 3 reference videos must total at most 15 seconds.")
    return WAN3_CENTS_PER_SECOND[resolution] * (duration + input_seconds)


def _luma_cost(tool: str, arguments: dict[str, Any]) -> GenerationCost:
    if tool == "list_luma_models":
        return GenerationCost(0, 0)
    if tool not in {"text_to_video", "image_to_video", "extend_video", "modify_video"}:
        raise ValueError("Unknown Luma tool.")
    if arguments.get("model", "ray-3.2") not in {None, "ray-3.2"}:
        raise ValueError("Luma video model must be ray-3.2.")
    resolution = arguments.get("resolution") or "720p"
    duration = arguments.get("source_duration_seconds") if tool == "modify_video" else arguments.get("duration_seconds", 5)
    if tool == "extend_video":
        cents = LUMA_EXTEND_CENTS.get(resolution)
    else:
        # TODO: official API pricing does not specify edits of arbitrary source lengths <=18s.
        # Accept only the published 5s/10s tiers, verified from the MP4 before submission.
        rates = LUMA_EDIT_CENTS if tool == "modify_video" else LUMA_GENERATION_CENTS
        cents = rates.get(resolution, {}).get(duration) if type(duration) is int else None
        if tool == "image_to_video" and duration != 5:
            cents = None
    if cents is None:
        raise ValueError("Luma request has no documented price for these settings.")
    if os.getenv("LUMA_DRY_RUN", "true").lower() != "false":
        return GenerationCost(0, 0)
    return _with_fee(cents)


# fal published per-video-second rates checked 2026-10-08, using num_frames / 16:
# https://fal.ai/models/fal-ai/wan-vace-14b (480p $0.04, 580p $0.06, 720p $0.08)
# https://fal.ai/models/fal-ai/wan-22-vace-fun-a14b/depth
# (480p $0.05, 580p $0.075, 720p $0.10; same for inpainting/outpainting/reframe).
# TODO: Confirm Wan 2.2 freeform and pose pricing, and auto/240p/360p rates.
def _fal_cost(tool: str, arguments: dict[str, Any]) -> GenerationCost:
    from providers.fal import api, queue, vidu, wan, wan3

    if tool == "list_fal_models":
        return GenerationCost(0, 0)
    if tool not in wan.GENERATING_TOOLS + vidu.GENERATING_TOOLS + wan3.GENERATING_TOOLS:
        raise ValueError("Unknown fal generation tool.")
    from providers.registry import schema_from_callable
    from providers.contracts import validate_tool_arguments

    fixed_endpoints = {**vidu.TOOL_ENDPOINTS, **wan3.TOOL_ENDPOINTS}
    if tool in fixed_endpoints:
        if "model" in arguments and arguments["model"] != fixed_endpoints[tool]:
            raise ValueError("fal model must match the tool's fixed endpoint.")
        arguments = {key: value for key, value in arguments.items() if key != "model"}
    schema = schema_from_callable(tool, api.TOOL_HANDLERS[tool])["inputSchema"]
    cleaned = validate_tool_arguments("fal", tool, arguments, schema)
    if queue.dry_run():
        return GenerationCost(0, 0)
    if tool in vidu.TOOL_ENDPOINTS:
        return _with_fee(round(vidu_q4_price_cents(cleaned)))
    if tool in wan3.TOOL_ENDPOINTS:
        return _with_fee(round(wan3_price_cents(cleaned)))
    endpoint = wan.endpoint_for(tool, cleaned)
    cents = wan.price_cents(endpoint, cleaned.get("resolution", "720p"), cleaned.get("num_frames", 81))
    return _with_fee(round(cents))


def cost_for(provider: str, tool: str, arguments: dict[str, Any]) -> GenerationCost:
    """Real cost (provider + disclosed fee) for one call to `provider`/`tool`.
    Called both before dispatch (to check affordability) and after success
    (to charge the same amount), so it must be a pure function of the
    request, not of anything the provider returns.
    """
    if provider == "kling":
        return _kling_cost(tool, arguments)
    if provider == "alibaba_modelstudio":
        return _modelstudio_cost(tool, arguments)
    if tool in POLLING_TOOLS or (provider == "remotion" and tool in {
        "export_nle_timeline", "prepare_conversational_edit",
    }):
        return GenerationCost(provider_cents=0, fee_cents=0)
    if provider == "runway":
        return _runway_cost(tool, arguments)
    if provider == "fal":
        return _fal_cost(tool, arguments)
    if provider == "luma":
        return _luma_cost(tool, arguments)
    if provider == "seedance":
        return _seedance_cost(arguments)
    if provider == "seedream":
        return _seedream_cost(arguments)
    if provider == "elevenlabs":
        from providers.elevenlabs.catalog import CATALOG
        entry = CATALOG.get(tool)
        if entry is None:
            raise ValueError("Unknown ElevenLabs tool.")
        if entry["effect"] == "read" or not os.getenv("STRIPE_SECRET_KEY"):
            return GenerationCost(0, 0)
        # ponytail: per-call operator quotes until usage-based invoice reconciliation exists.
        # Never reuse Mureka's placeholder price for unrelated ElevenLabs operations.
        quotes = json.loads(os.getenv("ELEVENLABS_TOOL_COST_CENTS_JSON", "{}"))
        quote = quotes.get(tool)
        if not isinstance(quote, int) or isinstance(quote, bool) or quote < 0:
            raise ValueError("Configure an ElevenLabs tool quote in ELEVENLABS_TOOL_COST_CENTS_JSON before enabling billed calls.")
        return _with_fee(quote)
    if provider == "fish_audio":
        return _fish_audio_cost(arguments)
    if provider == "remotion":
        return _with_fee(REMOTION_COST_CENTS)
    return _with_fee(5)
