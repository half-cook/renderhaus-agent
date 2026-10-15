import pytest
from agent.backend_config import agent_max_tokens, configured_deep_agent_model
from agent.deep_agent.budget import model_envelope
from langchain_core.messages import HumanMessage, SystemMessage
import server.run_budget as rb


def test_defaults_and_override(monkeypatch):
    monkeypatch.delenv("RENDERHAUS_AGENT_MAX_TOKENS", raising=False)
    assert agent_max_tokens() == 16_000 and agent_max_tokens("media") == 8_000
    monkeypatch.setenv("RENDERHAUS_AGENT_MAX_TOKENS_EDITOR", "4096")
    assert agent_max_tokens("editor") == 4096
    monkeypatch.setenv("RENDERHAUS_AGENT_MAX_TOKENS", "10")
    with pytest.raises(ValueError):
        agent_max_tokens()


@pytest.mark.parametrize("role", [None, "planner", "media", "audio", "editor", "general-purpose"])
def test_first_planner_call_fits_default_cap(monkeypatch, role):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.delenv("RENDERHAUS_AGENT_MODEL", raising=False)
    model = configured_deep_agent_model(role)
    envelope = model_envelope(model, [[SystemMessage("x" * 30_000), HumanMessage("hi")]], {})
    cap = rb.default_cap_cents(rb.orchestration_estimate_cents())
    assert rb.orchestration_total_cents(envelope.cost_usd) < cap
