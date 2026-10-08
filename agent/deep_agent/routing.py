"""Offline intent proposals and shared provider policy at the Gateway boundary."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path

POLICY = json.loads(Path(__file__).with_name("routing_policy.json").read_text())
TOOL_MAP = POLICY["tools"]
TARGET_PROVIDERS = {
    "Kling": "kling",
    "Runway": "runway",
    "Fal": "fal",
    "Seedance": "seedance",
    "Seedream": "seedream",
    "ElevenLabs": "elevenlabs",
    "Remotion": "remotion",
    "FishAudio": "fish_audio",
    "FishAudioProvider": "fish_audio",
    "Fish_Audio": "fish_audio",
    "Veo": "veo",
    "Luma": "luma",
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

    def public(self):
        return asdict(self)


def route_intent(prompt: str, *, region: str | None = None) -> Route:
    for rule in POLICY["rules"]:
        if not re.search(rule["pattern"], prompt, re.IGNORECASE):
            continue
        skill, abstract = rule["skill"], rule["abstract_tool"]
        entry = TOOL_MAP[abstract]
        pending = POLICY["pending_skills"].get(skill) or entry.get("reason")
        if pending:
            return Route(
                skill=skill,
                status=entry["status"] if entry["status"] != "ready" else "pending",
                reason=pending,
            )
        tool = entry["gateway_tool"]
        if tool:
            blocker = policy_blocker(tool, {}, region=region)
            if blocker:
                return Route(skill=skill, status="blocked", reason=blocker)
        dispatch = (
            None
            if not tool
            else "call_editor_tool"
            if tool.startswith("Remotion___")
            else (
                "call_audio_tool"
                if tool.startswith(("ElevenLabs___", "FishAudio___"))
                else "call_media_tool"
            )
        )
        return Route(
            skill,
            tool,
            dispatch,
            "ready",
            "Read the selected skill, then discover the exact schema.",
        )
    return Route()


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
    target, _, tool = name.partition("___")
    return enabled and target in POLICY["premium_targets"] and tool in POLICY["premium_video_tools"]


def effective_model(provider: str, tool: str, arguments: dict) -> str | None:
    policy = POLICY["providers"].get(provider, {})
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
    if policy["license"] not in {"Apache-2.0", "service-terms"}:
        return f"Provider {provider} licence is not approved for generation."
    region = region or os.getenv("RENDERHAUS_CUSTOMER_REGION")
    region = region.upper() if region else None
    if region in policy.get("blocked_regions", []):
        return f"Provider {provider} is blocked in region {region}."
    if policy["allowed_regions"] and region not in policy["allowed_regions"]:
        return f"Provider {provider} needs an allowed customer region before dispatch."
    model = effective_model(provider, tool, arguments)
    if model is not None and not isinstance(model, str):
        return f"Model for {provider} must be a string."
    if policy.get("models") and model not in policy["models"]:
        return f"Model {model} is not allowed for {provider}."
    model_policy = policy.get("model_policies", {}).get(model, {})
    if model_policy.get("enabled") is False or model_policy.get(
        "license", policy["license"]
    ) not in {"Apache-2.0", "service-terms"}:
        return f"Model {model} licence or access is not approved."
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


def estimate_cost(name: str, arguments: dict) -> CostEstimate:
    from server.billing_rates import cost_for

    if is_free_tool(name):
        return CostEstimate(0)
    blocker = policy_blocker(name, arguments)
    if blocker:
        return CostEstimate(None, blocker)
    provider, tool = tool_parts(name)
    model = effective_model(provider, tool, arguments)
    if model:
        arguments = {**arguments, "model": model}
    try:
        if provider not in POLICY["providers"] or provider in {
            "veo",
            "minimax_h3",
            "hunyuan",
        }:
            raise ValueError("No confirmed provider rate.")
        if provider == "remotion":
            raise ValueError("Remotion compute rate is a TODO placeholder.")
        if provider == "seedream" and arguments.get("size", "2K") != "1K":
            raise ValueError("Seedream Lite larger size tiers are unconfirmed.")
        if (
            provider == "kling"
            and (arguments.get("model") or os.getenv("KLING_MODEL")) == "kling-3.0-turbo"
        ):
            raise ValueError("Kling Turbo audio pricing is unconfirmed.")
        if provider == "fal":
            from providers.fal.wan import endpoint_for, price_cents

            price_cents(
                endpoint_for(tool, arguments),
                arguments.get("resolution", "720p"),
                arguments.get("num_frames", 81),
            )
        if provider == "elevenlabs":
            quotes = json.loads(os.getenv("ELEVENLABS_TOOL_COST_CENTS_JSON", "{}"))
            quote = quotes.get(tool) if isinstance(quotes, dict) else None
            if not isinstance(quote, int) or isinstance(quote, bool) or quote < 0:
                raise ValueError("Configure a confirmed ElevenLabs quote first.")
        if provider == "runway" and tool == "video_to_video":
            duration = arguments.get("video_duration_seconds")
            if isinstance(duration, float) and not duration.is_integer():
                raise ValueError("Fractional Aleph billing is unconfirmed.")
        return CostEstimate(cost_for(provider, tool, arguments).total_cents)
    except (ValueError, TypeError, KeyError) as exc:
        return CostEstimate(None, str(exc))
