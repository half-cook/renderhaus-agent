"""Backend selection and model-provider readiness without creating clients."""

from __future__ import annotations

import os


def agent_backend() -> str:
    backend = os.getenv("RENDERHAUS_AGENT_BACKEND", "deepagents").strip().lower()
    if backend not in {"deepagents", "codex"}:
        raise ValueError("RENDERHAUS_AGENT_BACKEND must be deepagents or codex.")
    return backend


def deep_agent_model() -> str:
    model = os.getenv("RENDERHAUS_AGENT_MODEL") or os.getenv("AGENT_MODEL", "gpt-5.6-luna")
    model = model.strip()
    if model.startswith("openai/"):
        model = "openai:" + model.removeprefix("openai/")
    return model if ":" in model else "openai:" + model


def agent_configured() -> bool:
    if agent_backend() == "codex":
        return bool(os.getenv("OPENAI_API_KEY"))
    provider = deep_agent_model().split(":", 1)[0]
    key = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(provider)
    if key:
        return bool(os.getenv(key))
    # Bedrock uses the deployment's IAM chain; readiness never probes AWS.
    return provider in {"bedrock", "bedrock_converse"}
