from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel


DEFAULT_DEEP_AGENT_MODEL = "anthropic:claude-opus-5-5"
SUPPORTED_MODEL_PROVIDERS = ("openai", "anthropic", "bedrock", "bedrock_converse")
ANTHROPIC_EFFORTS = ("low", "medium", "high", "xhigh", "max")


def agent_backend() -> str:
    backend = os.getenv("RENDERHAUS_AGENT_BACKEND", "deepagents").strip().lower()
    if backend not in {"deepagents", "codex"}:
        raise ValueError("RENDERHAUS_AGENT_BACKEND must be deepagents or codex.")
    return backend


def deep_agent_model() -> str:
    model = (os.getenv("RENDERHAUS_AGENT_MODEL", "").strip()
             or os.getenv("AGENT_MODEL", "").strip() or DEFAULT_DEEP_AGENT_MODEL)
    if ":" in model:
        provider, model_id = model.split(":", 1)
    elif "/" in model:
        provider, model_id = model.split("/", 1)
    else:
        provider, model_id = "openai", model
    if provider not in SUPPORTED_MODEL_PROVIDERS:
        raise ValueError("Unsupported agent model provider. Supported prefixes: "
                         + ", ".join(SUPPORTED_MODEL_PROVIDERS) + ".")
    if not model_id.strip():
        raise ValueError("RENDERHAUS_AGENT_MODEL must include a nonempty model ID.")
    return provider + ":" + model_id.strip()


def configured_deep_agent_model() -> str | BaseChatModel:
    """Construct Anthropic with effort settings; retain Deep Agents profiles for other providers."""
    model = deep_agent_model()
    if not model.startswith("anthropic:"):
        return model
    effort = os.getenv("RENDERHAUS_AGENT_EFFORT", "").strip().lower() or "high"
    if effort not in ANTHROPIC_EFFORTS:
        raise ValueError("RENDERHAUS_AGENT_EFFORT must be " + ", ".join(ANTHROPIC_EFFORTS) + ".")
    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        raise RuntimeError("ANTHROPIC_API_KEY is required when an Anthropic agent model is selected.")
    from langchain.chat_models import init_chat_model

    # Official Opus 5.5 and effort docs verified 2026-10-08:
    # https://platform.claude.com/docs/en/models/opus-5-5/overview
    # https://platform.claude.com/docs/en/build-with-claude/effort
    return init_chat_model(model, thinking={"type": "adaptive"}, output_config={"effort": effort})


def agent_configured() -> bool:
    if agent_backend() == "codex":
        return bool(os.getenv("OPENAI_API_KEY", "").strip())
    provider = deep_agent_model().split(":", 1)[0]
    key = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(provider)
    if key:
        return bool(os.getenv(key, "").strip())
    return provider in {"bedrock", "bedrock_converse"}
