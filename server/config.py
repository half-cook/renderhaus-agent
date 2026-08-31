from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from server.secrets import load_secrets_from_manager, secrets_locator


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.local"
GATEWAY_MCP_SERVER_NAME = "agentcore-gateway"


DEFAULT_ENV = {
    "AGENT_MODEL": "gpt-5.6-luna",
    "BYTEPLUS_BASE_URL": "https://ark.ap-southeast.bytepluses.com/api/v3",
    "SEEDANCE_MODEL": "seedance-1-5-pro-251215",
    "SEEDANCE_DRY_RUN": "true",
    "SEEDREAM_MODEL": "seedream-5-0-lite-260128",
    "SEEDREAM_DRY_RUN": "true",
    "FISH_AUDIO_DRY_RUN": "true",
    "FISH_AUDIO_MODEL": "s2.1-pro-free",
    "MUREKA_API_URL": "https://api.mureka.ai",
    "MUREKA_MODEL": "auto",
    "MUREKA_DRY_RUN": "true",
    "REMOTION_DRY_RUN": "true",
    "TIME_OUT_SECONDS": "300",
    "RENDERHAUS_MEDIA_DIR": ".renderhaus/media",
}


def load_local_env() -> None:
    """Load bootstrap .env, then AWS Secrets Manager, then defaults."""
    load_dotenv(ENV_FILE, override=False)
    if secrets_locator():
        load_secrets_from_manager(override=True)
    for key, value in DEFAULT_ENV.items():
        if not os.getenv(key):
            os.environ[key] = value


def agentcore_gateway_url() -> str:
    return (os.getenv("AGENTCORE_GATEWAY_URL") or "").strip()


def agentcore_gateway_headers() -> dict[str, str]:
    token = (os.getenv("AGENTCORE_GATEWAY_AUTH_TOKEN") or "").strip()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def require_agentcore_gateway_url() -> str:
    url = agentcore_gateway_url()
    if not url:
        raise ValueError(
            "AGENTCORE_GATEWAY_URL is required. Studio tools are only available through AgentCore Gateway."
        )
    return url


def mask_secret_status(name: str) -> str:
    return "set" if os.getenv(name) else "empty"
