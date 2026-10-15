from agent.gateway_executor import GatewayExecutor
from agent.studio_agent_next import StudioAgentRequest, _context_from_request


def test_ranked_suggestions_explain_default_and_exception():
    from agent.deep_agent.routing import ranked_suggestions
    rows = ranked_suggestions('Generate a video of a synthetic character saying "Hello"')
    assert rows[0]['rank'] == 1
    assert rows[0]['reason']
    assert any('default' in row['basis'] for row in rows)


def test_allowed_nondefault_requires_reason_and_keeps_explicit_only_hard():
    studio = _context_from_request(StudioAgentRequest(prompt='Generate a landscape video', job_id='hints'))
    executor = GatewayExecutor(studio, [])
    route = executor.media_selection('Seedance___text_to_video', {'prompt': 'Landscape'})
    assert executor.selection_blocker('Seedance___text_to_video', {'prompt': 'Landscape'}, route)
    assert executor.selection_blocker('Seedance___text_to_video', {'prompt': 'Landscape'}, route,
                                      routing_reason='This shot needs precise synthetic dialogue.') is None
    blocked = executor.selection_blocker('Kling___text_to_video', {'prompt': 'Landscape'}, route,
                                         routing_reason='I prefer this look.')
    assert blocked


def test_explicit_customer_request_cannot_be_overridden():
    studio = _context_from_request(StudioAgentRequest(prompt='Use Wan for a landscape video', job_id='hints'))
    executor = GatewayExecutor(studio, [])
    route = executor.media_selection('Seedance___text_to_video', {'prompt': 'Landscape'})
    assert executor.selection_blocker('Seedance___text_to_video', {'prompt': 'Landscape'}, route,
                                      routing_reason='I prefer this look.')
