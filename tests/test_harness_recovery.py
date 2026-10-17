import pytest


def test_free_alternative_has_one_durable_attempt():
    from agent.deep_agent.recovery import RecoveryPolicy
    policy = RecoveryPolicy()
    result = policy.failure('root', 'Ffmpeg___ffmpeg_tool', {'status': 'failed', 'error': 'Invalid filter'})
    assert result['recovery']['automatic_retry'] == 'free_alternative_only'
    assert policy.authorize_retry('root', 'Remotion___qc_deliverable') is None
    restored = RecoveryPolicy(policy.snapshot())
    assert restored.authorize_retry('root', 'Remotion___qc_deliverable')


def test_paid_error_never_authorizes_automatic_retry():
    from agent.deep_agent.recovery import RecoveryPolicy
    policy = RecoveryPolicy()
    result = policy.failure('root', 'Seedance___text_to_video', {'status': 'failed', 'error': '503'})
    assert result['recovery']['requires_fresh_approval']
    assert policy.authorize_retry('root', 'Seedance___text_to_video')
    assert policy.needs_approval('Seedance___text_to_video')


def test_unknown_or_ambiguous_creation_is_not_retried():
    from agent.deep_agent.recovery import RecoveryPolicy
    policy = RecoveryPolicy()
    result = policy.failure('root', 'Sync___create_dialogue_edit', {'status': 'submission_unknown'})
    assert result['recovery']['next_action'] == 'reconcile_saved_job_or_ask_user'
    assert policy.authorize_retry('root', 'Remotion___qc_deliverable')
    assert policy.authorize_retry('unknown', 'Remotion___qc_deliverable')


def test_omitting_retry_metadata_cannot_restart_a_free_failure_chain():
    from agent.deep_agent.recovery import RecoveryPolicy
    policy = RecoveryPolicy(scope='turn')
    policy.failure('first', 'Ffmpeg___ffmpeg_tool', {'status': 'failed', 'error': 'Invalid filter'})
    assert policy.authorize_call('second', 'Remotion___qc_deliverable') is None
    policy.failure('second', 'Remotion___qc_deliverable', {'status': 'failed', 'error': 'Missing input'})
    restored = RecoveryPolicy(policy.snapshot(), scope='turn')
    assert restored.authorize_call('third', 'Ffmpeg___ffmpeg_tool')
    assert restored.authorize_call('fourth', 'Ffmpeg___ffmpeg_tool', 'second')


def test_a_successful_free_alternative_ends_the_failure_chain():
    from agent.deep_agent.recovery import RecoveryPolicy
    policy = RecoveryPolicy()
    policy.failure('first', 'Ffmpeg___ffmpeg_tool', {'status': 'failed', 'error': 'Invalid filter'})
    assert policy.authorize_call('second', 'Remotion___qc_deliverable') is None
    policy.success('second', 'Remotion___qc_deliverable')
    assert policy.authorize_call('unrelated', 'Ffmpeg___ffmpeg_tool') is None
    assert policy.authorize_call('retry', 'Ffmpeg___ffmpeg_tool', 'first')


@pytest.mark.asyncio
async def test_gateway_enforces_retry_limit_without_model_supplied_metadata(tmp_path, monkeypatch):
    from mcp import Tool
    from agent.gateway_executor import GatewayExecutor
    from agent.studio_agent_next import StudioAgentRequest, _context_from_request
    from test_deep_agent import Gateway

    monkeypatch.setenv('RENDERHAUS_OUTCOME_DIR', str(tmp_path))
    name = 'Fal___get_video_task'
    gateway = Gateway(tools=[Tool(name=name, description='Check a saved task', inputSchema={
        'type': 'object', 'properties': {'job_id': {'type': 'string'}}, 'required': ['job_id'],
    })], result={'status': 'failed', 'error': 'Task status unavailable'})
    request = StudioAgentRequest(prompt='Check the saved task.', job_id='free-retry')
    executor = GatewayExecutor(_context_from_request(request), [gateway], run_scope='turn')
    await executor.connect_tools()
    for index in range(3):
        result = await executor.execute({'tool_name': name, 'arguments': {'job_id': 'saved'},
                                         'call_id': str(index)}, approved=True)
    assert result['status'] == 'not_run'
    assert 'single free alternative' in result['reason']
    assert gateway.call_tool.await_count == 2


@pytest.mark.asyncio
async def test_autonomous_paid_retry_returns_to_native_approval(tmp_path, monkeypatch):
    from agent.deep_agent.runner import run_with_servers
    from agent.studio_agent_next import StudioAgentApprovalRequired, StudioAgentRequest, _context_from_request
    from test_deep_agent import Gateway, ScriptedModel, read_skill, image
    monkeypatch.setenv('RENDERHAUS_MEDIA_DIR', str(tmp_path))
    monkeypatch.setenv('RENDERHAUS_OUTCOME_DIR', str(tmp_path / 'outcomes'))
    gateway = Gateway(result={'status': 'failed', 'error': 'Temporary service failure'})
    request = StudioAgentRequest(prompt='Make a product still with Seedream', job_id='paid-retry', autonomous=True)
    model = ScriptedModel([read_skill(), image('initial'), image('retry')])
    with pytest.raises(StudioAgentApprovalRequired) as paused:
        await run_with_servers(request, _context_from_request(request), [gateway], model=model)
    gateway.call_tool.assert_awaited_once()
    assert paused.value.approvals[0].tool_name == 'Seedream___text_to_image'
