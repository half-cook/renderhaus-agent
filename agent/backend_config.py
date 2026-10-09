from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel


DEFAULT_DEEP_AGENT_MODEL = "anthropic:claude-haiku-5-5"
SUPPORTED_MODEL_PROVIDERS = ("openai", "anthropic", "bedrock", "bedrock_converse")
AGENT_ROLES = ("planner", "media", "audio", "editor", "general-purpose")
ADAPTIVE_MODELS = {"claude-haiku-5-5", "claude-opus-5-5", "claude-sonnet-5-5",
                   "claude-opus-5", "claude-sonnet-5", "claude-opus-4-8", "claude-opus-4-7",
                   "claude-opus-4-6", "claude-sonnet-4-6", "claude-fable-5", "claude-fable-5-1"}
ANTHROPIC_EFFORTS = ("low", "medium", "high", "xhigh", "max")


def agent_backend() -> str:
    backend = os.getenv("RENDERHAUS_AGENT_BACKEND", "deepagents").strip().lower()
    if backend not in {"deepagents", "codex"}:
        raise ValueError("RENDERHAUS_AGENT_BACKEND must be deepagents or codex.")
    return backend


def _role_variable(prefix: str, role: str | None) -> str:
    if role is not None and role not in AGENT_ROLES:
        raise ValueError("Unknown Deep Agent role.")
    return prefix + ("_" + role.upper().replace("-", "_") if role else "")


def deep_agent_model(role: str | None = None) -> str:
    model = (os.getenv(_role_variable("RENDERHAUS_AGENT_MODEL", role), "").strip()
             or os.getenv("RENDERHAUS_AGENT_MODEL", "").strip()
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


def configured_deep_agent_model(role: str | None = None) -> str | BaseChatModel:
    """Construct Anthropic with effort settings; retain Deep Agents profiles for other providers."""
    model = deep_agent_model(role)
    if not model.startswith("anthropic:"):
        return model
    effort_var = _role_variable("RENDERHAUS_AGENT_EFFORT", role)
    effort = (os.getenv(effort_var, "").strip().lower()
              or os.getenv("RENDERHAUS_AGENT_EFFORT", "").strip().lower()
              or ("low" if role in {"media", "audio", "editor"} else "medium"))
    if effort not in ANTHROPIC_EFFORTS:
        raise ValueError(effort_var + " must be " + ", ".join(ANTHROPIC_EFFORTS) + ".")
    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        raise RuntimeError("ANTHROPIC_API_KEY is required when an Anthropic agent model is selected.")
    from langchain.chat_models import init_chat_model

    # Haiku migration and effort contract read 2026-10-09:
    # https://platform.claude.com/docs/en/models/haiku-5-5/migration-guide
    settings = {}
    if model.split(":", 1)[1] in ADAPTIVE_MODELS:
        settings = {"thinking": {"type": "adaptive"}, "output_config": {"effort": effort}}
    return init_chat_model(model, **settings)



def agent_configured() -> bool:
    if agent_backend() == "codex":
        return bool(os.getenv("OPENAI_API_KEY", "").strip())
    provider = deep_agent_model().split(":", 1)[0]
    key = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(provider)
    if key:
        return bool(os.getenv(key, "").strip())
    return provider in {"bedrock", "bedrock_converse"}
