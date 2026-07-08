from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env.local"
DEFAULT_MCP_CONFIG = ROOT / "configs" / "mcp.local.json"

_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*|ROOT)\}")

DEFAULT_ENV = {
    "AGENT_MODEL": "openai:gpt-4.1-mini",
    "BYTEPLUS_BASE_URL": "https://ark.ap-southeast.bytepluses.com/api/v3",
    "SEEDANCE_MODEL": "dreamina-seedance-2-0-fast-260128",
    "SEEDANCE_DRY_RUN": "true",
    "GEMINI_TTS_DRY_RUN": "true",
    "GEMINI_TTS_MODEL": "gemini-3.1-flash-tts-preview",
    "MUREKA_API_URL": "https://api.mureka.ai",
    "TIME_OUT_SECONDS": "300",
    "RENDERHAUS_MEDIA_DIR": ".renderhaus/media",
    "GPT_IMAGE_2_OUTPUT_DIR": ".renderhaus/media/images",
}


def load_local_env() -> None:
    load_dotenv(ENV_FILE, override=False)
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
    return _walk_expand(raw["mcpServers"])


def mask_secret_status(name: str) -> str:
    return "set" if os.getenv(name) else "empty"
