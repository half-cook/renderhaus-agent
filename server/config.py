from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from server.secrets import load_secrets_from_manager, secrets_locator


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.local"
GATEWAY_MCP_SERVER_NAME = "agentcore-gateway"


DEFAULT_ENV = {
    "BETA_CREDITS_ENABLED": "false",
    "BETA_GRANT_CENTS": "1000",
    "BETA_GLOBAL_CAP_CENTS": "50000",
    "BETA_WAVE_SIZE": "50",
    "BETA_WAVE_INDEX": "1",
    "BETA_DAILY_GRANT_LIMIT": "0",
    "BETA_VERIFICATION_DRY_RUN": "true",
    "OPENAI_IMAGES_DRY_RUN": "true",
    "OPENAI_IMAGES_MODEL": "gpt-image-2.5-sunburst",
    "KLING_BASE_URL": "https://api-singapore.klingai.com",
    "KLING_MODEL": "kling-3.0",
    "KLING_API_STYLE": "current",
    "KLING_DRY_RUN": "true",
    "BYTEPLUS_BASE_URL": "https://ark.ap-southeast.bytepluses.com/api/v3",
    "SEEDANCE_MODEL": "dreamina-seedance-2-5-260628",
    "SEEDANCE_DRY_RUN": "true",
    "RUNWAY_DRY_RUN": "true",
    "SEEDREAM_MODEL": "seedream-5-0-lite-260128",
    "SEEDREAM_DRY_RUN": "true",
    "FAL_DRY_RUN": "true",
    "FISH_AUDIO_DRY_RUN": "true",
    "FISH_AUDIO_MODEL": "s2.1-pro-free",
    "ELEVENLABS_DRY_RUN": "true",
    "ELEVENLABS_TTS_MODEL": "eleven_v4_turbo",
    "REMOTION_DRY_RUN": "true",
    "REMOTION_RENDER_BACKEND": "lambda",
    "REMOTION_LOCAL_MEDIA_HOSTS": "",
    "TIME_OUT_SECONDS": "300",
    "RENDERHAUS_MEDIA_DIR": ".renderhaus/media",
}


def load_local_env() -> None:
    """Load bootstrap .env, then AWS Secrets Manager, then defaults."""
    load_dotenv(ENV_FILE, override=False)
    if secrets_locator():
        load_secrets_from_manager(override=True)
    from agent.backend_config import DEFAULT_DEEP_AGENT_MODEL

    if not os.getenv("RENDERHAUS_AGENT_MODEL") and not os.getenv("AGENT_MODEL"):
        os.environ["RENDERHAUS_AGENT_MODEL"] = DEFAULT_DEEP_AGENT_MODEL
    for key, value in DEFAULT_ENV.items():
        if key not in os.environ or (not key.startswith("BETA_") and not os.getenv(key)):
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
