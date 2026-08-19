from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from server.secrets import load_secrets_from_manager, secrets_locator


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.local"
DEFAULT_MCP_CONFIG = ROOT / "configs" / "mcp.local.json"
AGENTCORE_MCP_CONFIG = ROOT / "configs" / "mcp.agentcore.json"


def mcp_config_path() -> Path:
    override = (os.getenv("MCP_CONFIG") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if os.getenv("AGENTCORE_RUNTIME", "").lower() in {"1", "true", "yes"}:
        return AGENTCORE_MCP_CONFIG
    return DEFAULT_MCP_CONFIG

_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*|ROOT)\}")

DEFAULT_ENV = {
    "AGENT_MODEL": "gpt-4.1-mini",
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
    "TIME_OUT_SECONDS": "300",
    "RENDERHAUS_MEDIA_DIR": ".renderhaus/media",
    "GPT_IMAGE_2_OUTPUT_DIR": ".renderhaus/media/images",
}


def load_local_env() -> None:
    """Load bootstrap .env, then AWS Secrets Manager, then defaults."""
    load_dotenv(ENV_FILE, override=False)
    if secrets_locator():
        # Secrets Manager is the source of truth when configured.
        load_secrets_from_manager(override=True)
    for key, value in DEFAULT_ENV.items():
        if not os.getenv(key):
            os.environ[key] = value


def _expand(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name == "ROOT":
            return str(ROOT)
        return os.getenv(name, "")

    return _VAR_RE.sub(replace, value)


def _walk_expand(value: Any) -> Any:
    if isinstance(value, str):
        return _expand(value)
    if isinstance(value, list):
        return [_walk_expand(item) for item in value]
    if isinstance(value, dict):
        return {key: _walk_expand(item) for key, item in value.items()}
    return value


def load_mcp_servers(path: Path = DEFAULT_MCP_CONFIG) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text())
    servers = _walk_expand(raw["mcpServers"])
    return _maybe_attach_gateway(servers)


def _maybe_attach_gateway(servers: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Prefer AgentCore Gateway for Mureka when AGENTCORE_GATEWAY_URL is set."""
    gateway_url = (os.getenv("AGENTCORE_GATEWAY_URL") or "").strip()
    if not gateway_url:
        return servers
    updated = dict(servers)
    # Gateway exposes Mureka___* tools; drop local stdio mureka to avoid duplicates.
    updated.pop("mureka", None)
    headers: dict[str, str] = {}
    token = (os.getenv("AGENTCORE_GATEWAY_AUTH_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    updated["mureka-gateway"] = {
        "transport": "streamable_http",
        "url": gateway_url,
        **({"headers": headers} if headers else {}),
    }
    return updated


def mask_secret_status(name: str) -> str:
    return "set" if os.getenv(name) else "empty"
