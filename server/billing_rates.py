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
account-dependent (Mureka doesn't publish a flat per-song API rate), the
comment says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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


# -- Mureka (music) -------------------------------------------------------
# Mureka doesn't publish a flat per-song API rate (their own pricing is
# subscription-quota based); this is the low end of what third-party
# aggregators charge per song as a placeholder, scaled by the number of
# variants (`n`) requested. Needs a real number from your Mureka account.
MUREKA_COST_CENTS_PER_SONG = 3


def _mureka_cost(arguments: dict[str, Any]) -> GenerationCost:
    variants = arguments.get("n")
    count = int(variants) if isinstance(variants, (int, float)) and variants else 1
    return _with_fee(MUREKA_COST_CENTS_PER_SONG * max(1, count))


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


def cost_for(provider: str, tool: str, arguments: dict[str, Any]) -> GenerationCost:
    """Real cost (provider + disclosed fee) for one call to `provider`/`tool`.
    Called both before dispatch (to check affordability) and after success
    (to charge the same amount), so it must be a pure function of the
    request, not of anything the provider returns.
    """
    del tool  # cost doesn't currently vary by tool name within a provider
    if provider == "seedance":
        return _seedance_cost(arguments)
    if provider == "seedream":
        return _seedream_cost(arguments)
    if provider == "mureka":
        return _mureka_cost(arguments)
    if provider == "fish_audio":
        return _fish_audio_cost(arguments)
    if provider == "remotion":
        return _with_fee(REMOTION_COST_CENTS)
    return _with_fee(5)
