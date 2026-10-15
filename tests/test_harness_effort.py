import pytest
from unittest.mock import patch

from agent.backend_config import configured_deep_agent_model


@pytest.mark.parametrize('role,effort', [(None, 'high'), ('planner', 'high'),
                         ('editor', 'medium'), ('media', 'low'), ('audio', 'low')])
def test_role_effort_defaults(monkeypatch, role, effort):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'offline-test')
    monkeypatch.delenv('RENDERHAUS_AGENT_EFFORT', raising=False)
    if role:
        monkeypatch.delenv('RENDERHAUS_AGENT_EFFORT_' + role.upper(), raising=False)
    with patch('langchain.chat_models.init_chat_model') as init:
        configured_deep_agent_model(role)
    assert init.call_args.kwargs['output_config']['effort'] == effort


def test_role_effort_override_wins(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'offline-test')
    monkeypatch.setenv('RENDERHAUS_AGENT_EFFORT', 'low')
    monkeypatch.setenv('RENDERHAUS_AGENT_EFFORT_EDITOR', 'high')
    with patch('langchain.chat_models.init_chat_model') as init:
        configured_deep_agent_model('editor')
    assert init.call_args.kwargs['output_config']['effort'] == 'high'
