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
    tier: str | None = None
    job_type: str | None = None
    required: dict = field(default_factory=dict)
    estimated_cost: dict | None = None
    disclosure: str = ""

    def public(self):
        return asdict(self)


def route_intent(prompt: str, *, region: str | None = None, tier: str | None = None,
                 confidential: bool = False, arguments: dict | None = None,
                 available_tools: set[str] | None = None, retry: bool = False) -> Route:
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
        if skill == "hyperframes":
            blocker = policy_blocker("HyperFrames___render_composition", {})
            if blocker:
                return Route(skill=skill, status="blocked", reason=blocker)
            if available_tools is not None and "HyperFrames___render_composition" not in available_tools:
                return Route(skill=skill, status="blocked", reason="Requested HyperFrames renderer tool is unavailable in this session.")
        tool = entry["gateway_tool"]
        job = job_type(tool) if tool else None
        if job:
            constraints = intent_constraints(prompt, tier=tier, confidential=confidential)
            if job == "t2v" and constraints["required"].get("start_end_frame"):
                job, skill = "i2v", "i2v"
            selection = select_provider(
                job, arguments=arguments, available_tools=available_tools, region=region,
                retry=retry, **constraints,
            )
            return replace(selection, skill=skill)
        if tool:
            if skill == "hyperframes" and available_tools is not None and tool not in available_tools:
                return Route(skill=skill, status="blocked", reason="Requested HyperFrames workflow tool is unavailable in this session.")
            blocker = policy_blocker(tool, {}, region=region)
            if blocker:
                return Route(skill=skill, status="blocked", reason=blocker)
        dispatch = (
            None
            if not tool
            else "call_editor_tool"
            if tool.startswith(("Remotion___", "HyperFrames___"))
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


def job_type(name: str | None) -> str | None:
    for row in POLICY["capabilities"]:
        for job, tool in row["tools"].items():
            if tool == name:
                return {"image_edit": "image", "reference": "i2v", "extend": "extend"}.get(job, job)
    return None


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
        values = {"cents_per_1000_tokens": rates.SEEDANCE_TOKEN_RATE_CENTS_PER_1K,
                  "fps": rates.SEEDANCE_FPS, "formula": "width * height * fps * duration / 1024"}
    elif provider == "seedream":
        values = {"1K": rates.SEEDREAM_COST_CENTS_BY_SIZE["1K"], "2K": "unknown", "3K": "unknown"}
    elif provider == "luma":
        values = {"generation": rates.LUMA_GENERATION_CENTS, "modify": rates.LUMA_EDIT_CENTS,
                  "extend": rates.LUMA_EXTEND_CENTS}
    else:
        return "unknown"
    return {**price, "rates": values,
            "currency_unit": "USD/second" if provider == "kling" else "provider cents",
            "fee": "server.billing_rates._with_fee"}


def intent_constraints(prompt: str, *, tier: str | None = None, confidential: bool = False) -> dict:
    provider = next((p for pattern, p in [
        (r"\bwan\b|\bfal\b|vace", "fal"), (r"seedance", "seedance"),
        (r"seedream", "seedream"), (r"kling", "kling"), (r"runway|aleph|gen.?4", "runway"),
        (r"luma|ray.?3", "luma"), (r"\bveo\b", "veo"),
        (r"mini.?max", "minimax_h3"), (r"hunyuan", "hunyuan"),
    ] if re.search(pattern, prompt, re.I)), None)
    requested_tier = next((value for value in ["draft", "standard", "premium"]
                           if re.search(rf"\b{value}\b", prompt, re.I)), None)
    if requested_tier is None and re.search(r"preview|cheap(?:est|ly)?|training", prompt, re.I):
        requested_tier = POLICY["ladder"]["preview_tier"]
    if requested_tier is None and re.search(r"highest quality|best quality", prompt, re.I):
        requested_tier = "premium"
    required = {}
    for feature, pattern in {
        "native_audio": r"native audio|with audio|needs? audio",
        "start_end_frame": r"end frame|last frame|start.end.frame|first.*last frame",
        "multi_shot": r"multi.shot",
        "reference_elements": r"reference elements|element library",
    }.items():
        if re.search(pattern, prompt, re.I):
            required[feature] = True
    resolution = re.search(r"\b(480p|580p|720p|1080p|4k)\b", prompt, re.I)
    if resolution:
        required["max_resolution"] = resolution_value(resolution[1])
    duration = re.search(r"\b(\d+)\s*(?:second|seconds|s)\b", prompt, re.I)
    if duration:
        required["duration_seconds"] = int(duration[1])
    faithful = bool(re.search(r"faithful|keep performance|plate edit|multi.shot", prompt, re.I))
    return {"provider": provider, "tier": requested_tier or tier, "required": required,
            "confidential": confidential or bool(re.search(r"\bconfidential\b", prompt, re.I)),
            "faithful": faithful}


def resolution_value(value: str) -> int:
    if ":" in value:
        parts = value.split(":")
        return min(int(part) for part in parts) if len(parts) == 2 and all(part.isdigit() for part in parts) else 0
    return {"4k": 2160, "1k": 1024, "2k": 2048, "3k": 3072}.get(
        value.lower(), int(value[:-1]) if value.lower().endswith("p") and value[:-1].isdigit() else 0,
    )


def select_provider(job: str, *, tier: str | None = None, required: dict | None = None,
                    arguments: dict | None = None, provider: str | None = None,
                    model: str | None = None, confidential: bool = False, retry: bool = False,
                    faithful: bool = False, region: str | None = None,
                    available_tools: set[str] | None = None, tool_variant: str | None = None) -> Route:
    args, required = dict(arguments or {}), dict(required or {})
    tier = tier or POLICY["ladder"]["default_tier"]
    if tier not in {"draft", "standard", "premium"}:
        return Route(status="blocked", reason="Unknown quality tier.")
    if confidential or retry:
        tier = "draft"
        if confidential and provider and provider != POLICY["ladder"]["confidential_provider"]:
            return Route(status="blocked", reason="Confidential projects permit Wan only.", disclosure="Confidential projects permit Wan only.")
        provider = POLICY["ladder"]["confidential_provider"]
        model = None
    elif job == "v2v_edit" and faithful and provider is None and tier != "draft":
        provider, tier = POLICY["ladder"]["faithful_edit_provider"], "premium"
    for key, feature in [("generate_audio", "native_audio"), ("multi_shot", "multi_shot"),
                         ("shots", "multi_shot"), ("elements", "reference_elements"),
                         ("last_frame_url", "start_end_frame"), ("end_image_path_or_url", "start_end_frame"),
                         ("last_frame_path_or_url", "start_end_frame")]:
        if args.get(key):
            required[feature] = True
    resolution = args.get("resolution") or args.get("size") or args.get("ratio")
    if resolution:
        required["max_resolution"] = max(required.get("max_resolution", 0), resolution_value(resolution))
    if job == "image" and not resolution and not provider and not required.get("max_resolution"):
        required["max_resolution"] = max(required.get("max_resolution", 0), resolution_value(POLICY["ladder"]["image_default_size"]))
    if job == "v2v_edit":
        required.pop("multi_shot", None)
    duration = required.get("duration_seconds") or args.get("duration_seconds") or args.get("video_duration_seconds") or args.get("source_duration_seconds")
    candidates, refusals = [], []
    variant = tool_variant or job
    for row in capability_table():
        if provider and row["provider"] != provider or model and row["model"] != model:
            continue
        tool = row["tools"].get(variant)
        if tool is None:
            continue
        if available_tools is not None and tool not in available_tools:
            continue
        if any(row["jobs"].get(key, False) < value for key, value in required.items() if key != "duration_seconds"):
            continue
        limits = row["durations"].get(variant)
        if duration and limits and not limits[0] <= duration <= limits[1]:
            continue
        values = row.get("duration_values", {}).get(variant)
        if duration and values and duration not in values:
            continue
        if row.get("frame_limits"):
            fps = args.get("frames_per_second", 16)
            frames = args.get("num_frames", round(duration * fps) + 1 if duration else 81)
            if any(not low <= value <= high for value, (low, high) in (
                (fps, row["frame_limits"]["frames_per_second"]),
                (frames, row["frame_limits"]["num_frames"]),
            )):
                continue
        controls = row["controls"].get(variant, [])
        if any(args.get(key) and resolution_value(args[key]) not in row["resolutions"]
               for key in ("resolution", "size") if key in controls and args.get(key) != "auto"):
            continue
        if required.get("native_audio") and "generate_audio" not in controls:
            continue
        if required.get("start_end_frame") and not any(key in controls for key in (
            "last_frame_url", "end_image_path_or_url", "last_frame_path_or_url",
        )):
            continue
        if required.get("reference_elements") and not any(key in controls for key in ("elements", "ref_image_urls")):
            continue
        if not provider:
            eligible = (POLICY["ladder"]["v2v_tiers"][tier] if job == "v2v_edit" else
                        POLICY["ladder"]["generation_tiers"][tier] if job in {"t2v", "i2v"} else None)
            if tier not in row["tiers"] or eligible is not None and row["provider"] not in eligible:
                continue
        quote_args = {**args, "model": row["model"]}
        if duration:
            key = "source_duration_seconds" if tool.endswith("modify_video") else "video_duration_seconds" if tool.endswith("video_to_video") and row["provider"] == "runway" else "duration_seconds"
            if row["provider"] == "fal":
                quote_args["num_frames"] = args.get("num_frames", round(duration * args.get("frames_per_second", 16)) + 1)
            else:
                quote_args[key] = duration
        if required.get("native_audio"):
            quote_args["generate_audio"] = True
        if required.get("max_resolution"):
            native = (args.get("size", "2K") if "size" in controls else
                      args.get("ratio", "1280:720") if "ratio" in controls else args.get("resolution", "720p"))
            minimum = max(required["max_resolution"], resolution_value(native))
            value = min(value for value in row["resolutions"] if value >= minimum)
            if "resolution" in controls:
                quote_args["resolution"] = "4k" if value == 2160 else f"{value}p"
            elif "size" in controls:
                quote_args["size"] = f"{value // 1024}K"
            elif "ratio" in controls:
                quote_args["ratio"] = "1920:1080" if value == 1080 else "1280:720"
        blocker = policy_blocker(tool, quote_args, region=region)
        if blocker:
            refusals.append(blocker)
            continue
        quote = estimate_cost(tool, quote_args, list_price=True)
        candidates.append((quote.total_cents is None, quote.total_cents or 0, row, tool, quote))
    if not candidates:
        reason = ("Confidential Wan-only constraint. " if confidential else "Wan reject retry. " if retry else "")
        reason += f"No enabled built provider satisfies {job}, {tier} tier and required capabilities {required}."
        if provider:
            reason += f" Requested provider {provider} refused."
        reason += " " + " ".join(dict.fromkeys(refusals))
        return Route(status="blocked", reason=reason.strip(), tier=tier, job_type=job,
                     required=required, disclosure=reason.strip())
    _, _, row, tool, quote = min(candidates, key=lambda candidate: candidate[:2])
    if tier not in row["tiers"]:
        tier = row["tiers"][0]
    reason = f"{tier} tier; capability filters {required or 'none'}; cheapest known price before unknown quotes."
    if provider:
        reason = f"{tier} tier; explicit provider or ladder constraint; capability filters {required or 'none'}."
    if confidential:
        reason += " Confidential project, Wan only."
    if retry:
        reason += " Automatic Wan retry after artifact rejection."
    disclosure = f"Selected {row['label']} ({row['model']}). {reason} {quote.description} Speed class {row['speed_class']} is typical, not a measured SLA."
    return Route(tool=tool, dispatch_tool="call_media_tool", status="ready", reason=reason,
                 provider=row["provider"], model=row["model"], tier=tier, job_type=job,
                 required=required, estimated_cost=quote.public(), disclosure=disclosure)


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


def estimate_cost(name: str, arguments: dict, *, list_price: bool = False) -> CostEstimate:
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
        if provider == "hyperframes":
            raise ValueError("HyperFrames local compute pricing is unknown; isolated renderer not configured.")
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
        if list_price:
            if provider in {"runway", "kling", "luma"}:
                cost_for(provider, tool, arguments)
            return CostEstimate(_published_cost(provider, tool, arguments).total_cents)
        return CostEstimate(cost_for(provider, tool, arguments).total_cents)
    except (ValueError, TypeError, KeyError) as exc:
        return CostEstimate(None, str(exc))


def _published_cost(provider: str, tool: str, arguments: dict):
    from decimal import Decimal
    from server import billing_rates as rates

    if provider == "seedance":
        return rates._seedance_cost(arguments)
    if provider == "seedream":
        return rates._seedream_cost(arguments)
    if provider == "fal":
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
        raise ValueError("No published ladder price.")
    return rates._with_fee(round(cents))
