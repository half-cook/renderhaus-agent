"""Explicit local configuration applied after the production-shaped secret."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

from agent.backend_config import AGENT_ROLES, DEFAULT_DEEP_AGENT_MODEL


logger = logging.getLogger(__name__)
DRY_RUN_FLAGS = (
    "BETA_VERIFICATION_DRY_RUN",
    "ELEVENLABS_DRY_RUN",
    "FAL_DRY_RUN",
    "FFMPEG_DRY_RUN",
    "FISH_AUDIO_DRY_RUN",
    "FOOTAGE_MEMORY_DRY_RUN",
    "GEMINI_DRY_RUN",
    "GEMINI_TTS_DRY_RUN",
    "HEYGEN_DRY_RUN",
    "HEYGEN_VOICE_DRY_RUN",
    "HYPERFRAMES_DRY_RUN",
    "KLING_DRY_RUN",
    "LUMA_DRY_RUN",
    "MODELSTUDIO_DRY_RUN",
    "MOTION_CARRY_QC_DRY_RUN",
    "MUREKA_DRY_RUN",
    "OPENAI_IMAGES_DRY_RUN",
    "REMOTION_DRY_RUN",
    "RUNWAY_DRY_RUN",
    "SEEDANCE_DRY_RUN",
    "SEEDREAM_DRY_RUN",
    "SYNC_DRY_RUN",
    "TOPAZ_DRY_RUN",
)
LOCAL_ENDPOINTS = {
    "AGENTCORE_GATEWAY_URL": "http://127.0.0.1:8765/mcp",
    "AGENTCORE_GATEWAY_ALLOW_LOOPBACK_HTTP": "true",
    "APP_URL": "http://localhost:5174",
    "BETTER_AUTH_URL": "http://localhost:5174",
    "STUDIO_APP_URL": "http://localhost:5174",
    "STUDIO_API_ORIGIN": "http://127.0.0.1:8000",
    "NODE_ENV": "development",
    "REMOTION_RENDER_BACKEND": "local",
    "RENDERHAUS_MEDIA_DIR": ".renderhaus/media",
    "RENDERHAUS_STUDIO_DATABASE": ".renderhaus/studio.sqlite3",
    "RENDERHAUS_AGENT_BACKEND": "deepagents",
    "RENDERHAUS_DISABLE_AUTH": "false",
}
CLOUD_SETTINGS = (
    "AGENTCORE_GATEWAY_ID",
    "AGENTCORE_GATEWAY_AUTH_TOKEN",
    "AGENTCORE_RUNTIME_ARN",
    "AGENTCORE_RUNTIME",
    "AGENTCORE_DEV_URL",
    "AWS_S3_BUCKET",
    "PROVIDER_INPUT_BUCKET",
    "AWS_DYNAMODB_ASSETS_TABLE",
    "AWS_DYNAMODB_TABLE",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
)
PROCESS_KEYS = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "TMPDIR",
    "TMP",
    "TEMP",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
)
MODEL_SETTINGS = (
    "AGENT_MODEL",
    "RENDERHAUS_AGENT_MODEL",
    "RENDERHAUS_AGENT_EFFORT",
    *(
        f"RENDERHAUS_AGENT_{kind}_{role.upper().replace('-', '_')}"
        for role in AGENT_ROLES
        for kind in ("MODEL", "EFFORT")
    ),
)
CONTROL_KEYS = (
    "RENDERHAUS_LOCAL_PROFILE",
    "RENDERHAUS_LOCAL_LIVE_PROVIDERS",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_PROFILE",
    "RENDERHAUS_SECRETS_NAME",
    "RENDERHAUS_SECRETS_ARN",
    *MODEL_SETTINGS,
    *PROCESS_KEYS,
    "PYTHONPATH",
    "PYTHONHOME",
    "NODE_OPTIONS",
)


def capture_local_profile(env: Mapping[str, str]) -> dict[str, str | None] | None:
    """Capture user choices before a secret can overwrite or introduce them."""
    if env.get("RENDERHAUS_LOCAL_PROFILE") != "local":
        return None
    keys = set(CONTROL_KEYS) | {
        key for key in env if key.startswith("AWS_") and key not in CLOUD_SETTINGS
    }
    controls = {key: env.get(key) for key in keys}
    providers = {
        part.strip()
        for part in (controls["RENDERHAUS_LOCAL_LIVE_PROVIDERS"] or "").split(",")
        if part.strip()
    }
    if providers - {key.removesuffix("_DRY_RUN") for key in DRY_RUN_FLAGS}:
        raise ValueError("InvalidLocalProvider: use provider names listed in docs/LOCAL_RUN.md.")
    return controls


def apply_local_profile(controls: Mapping[str, str | None]) -> None:
    live = {
        part.strip()
        for part in (controls["RENDERHAUS_LOCAL_LIVE_PROVIDERS"] or "").split(",")
        if part.strip()
    }
    flags = set(DRY_RUN_FLAGS) | {key for key in os.environ if key.endswith("_DRY_RUN")}
    os.environ.update(
        {key: "false" if key.removesuffix("_DRY_RUN") in live else "true" for key in flags}
    )
    os.environ.update({key: "" for key in CLOUD_SETTINGS})
    os.environ.update({key: "" for key in os.environ if key.startswith("REMOTION_APP_")})
    os.environ.update(LOCAL_ENDPOINTS)
    keys = set(controls) | {
        key for key in os.environ if key.startswith("AWS_") and key not in CLOUD_SETTINGS
    }
    for key in keys:
        value = controls.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    os.environ["AWS_REGION"] = (
        controls["AWS_REGION"] or controls["AWS_DEFAULT_REGION"] or "us-east-1"
    )
    os.environ["RENDERHAUS_AGENT_MODEL"] = (
        controls["RENDERHAUS_AGENT_MODEL"] or controls["AGENT_MODEL"] or DEFAULT_DEEP_AGENT_MODEL
    )
    if live:
        logger.warning(
            "LOCAL LIVE providers enabled: %s. Paid requests are possible; existing approval and cost gates still apply.",
            ", ".join(sorted(live)),
        )


def dry_run_table(env: Mapping[str, str]) -> dict[str, bool]:
    return {key: env.get(key, "true").lower() != "false" for key in DRY_RUN_FLAGS}


def studio_environment(env: Mapping[str, str]) -> dict[str, str]:
    """Next middleware needs Clerk keys, but never agent, AWS, or provider credentials."""
    child = {key: env[key] for key in PROCESS_KEYS if key in env}
    child.update({key: LOCAL_ENDPOINTS[key] for key in ("STUDIO_API_ORIGIN", "NODE_ENV")})
    for key in ("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY", "CLERK_SECRET_KEY"):
        child[key] = env[key]
    return child
