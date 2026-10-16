from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from agent.deep_agent.runner import run_with_servers
from agent.errors import AgentRunLimitExceeded
from agent.studio_agent_next import StudioAgentRequest, _context_from_request, _validate_video_delivery
from server import run_billing, studio, studio_state
from server.studio_state import StudioRepository
from test_deep_agent import ScriptedModel, call
from test_delivery_host import DELIVERY, DELIVERY_PROMPT, QC, bound_report, tool_event


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    repo = StudioRepository(tmp_path / 'studio.sqlite3', tmp_path / 'media')
    repo.create_project('user:local', 'local', 'Delivery', project_id='untitled')
    conversation = repo.create_conversation('user:local', 'untitled', 'local')['id']
    repo.create_execution(workspace_id='user:local', project_id='untitled', user_id='local',
                          prompt=DELIVERY_PROMPT, conversation_id=conversation, execution_id='owned-job',
                          request={'prompt': DELIVERY_PROMPT})
    monkeypatch.setattr(studio, 'repository', repo)
    monkeypatch.setattr(studio_state, 'repository', repo)
    monkeypatch.setattr(studio, '_AGENT_TASKS', set())
    monkeypatch.setattr(studio, 'agent_configured', lambda: True)
    monkeypatch.setattr(run_billing, 'billing_applies', lambda *args: True)
    monkeypatch.setenv('AGENTCORE_DEV_URL', '')
    monkeypatch.setenv('RENDERHAUS_AGENT_BACKEND', 'deepagents')
    monkeypatch.setenv('RENDERHAUS_MEDIA_DIR', str(repo.media_root))
    monkeypatch.setenv('ORCHESTRATION_BILLING_ENABLED', 'true')
    root = repo.media_root / 'owned-job'
    root.mkdir()
    report = bound_report(root)
    asset = repo.register_bytes(workspace_id='user:local', project_id='untitled', user_id='local',
        content=Path(report['files'][0]['output_path']).read_bytes(), filename='report.mp4', kind='video')
    old = tool_event(DELIVERY, report, event_id='original-delivery')
    old.assets = [asset.public()]
    repo.append_tool_call(workspace_id='user:local', execution_id='owned-job', event=old.public())
    repo.save_agent_checkpoint('user:local', conversation, 'owned-job',
                              [{'role': 'user', 'content': DELIVERY_PROMPT}])
    repo.update_execution('user:local', 'owned-job', status='error', message='Paused at cap.', error_type='PausedAtCap')
    repo.adjust_balance('local', 1000, 'test_credit')
    repo.hold_run('local', 'owned-job', 125, conversation_id=conversation)
    repo.charge_usage('local', 20, 'orchestration', run_id='owned-job', line_kind='orchestration')
    run_billing.RunMeter(repo, 'local', 'owned-job')._pause()
    return repo, conversation, old


def test_http_json_cannot_set_internal_delivery_continuation():
    body = studio.AgentBody.model_validate({'prompt': DELIVERY_PROMPT, 'delivery_continuation': True,
                                            '_delivery_continuation': True})
    assert body._delivery_continuation is False
    assert 'delivery_continuation' not in body.model_dump()
    assert '_delivery_continuation' not in body.model_dump()
    assert '_delivery_continuation' not in studio.AgentBody.model_json_schema()['properties']


@pytest.mark.asyncio
async def test_native_approval_resume_preserves_trusted_continuation(recovery, monkeypatch):
    repo, conversation, _ = recovery
    job = repo.create_execution(workspace_id='user:local', project_id='untitled', user_id='local',
        prompt=DELIVERY_PROMPT, conversation_id=conversation,
        request={'prompt': DELIVERY_PROMPT, 'delivery_continuation': True})['job_id']
    repo.pause_execution('user:local', job, run_state='native-checkpoint', approvals=[
        {'call_id': 'approval', 'tool_name': 'Remotion___render_timeline', 'decision': 'approve'}])
    runner = AsyncMock()
    monkeypatch.setattr(studio, '_run_studio_agent_job', runner)
    await studio._resume_studio_agent_decision(job, repo.get_execution('user:local', job), True, None)
    await asyncio.gather(*list(studio._AGENT_TASKS))
    assert runner.call_args.kwargs['delivery_continuation'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('run_limit', [False, True])
async def test_real_cap_resume_restores_delivery_with_saved_session_without_reprocessing(recovery, monkeypatch, run_limit):
    repo, conversation, old = recovery

    async def runtime(request, *, studio):
        assert request.delivery_continuation is True
        assert request.session_items
        assert [event.id for event in studio.tool_events] == [old.id]
        if run_limit:
            raise AgentRunLimitExceeded()
        return await run_with_servers(request, studio, [], model=ScriptedModel([
            call('StudioAgentOutput', {'title': 'Existing delivery verified', 'summary': 'Saved delivery QC passed.',
                 'markdown': '# Saved delivery QC passed', 'filename': 'delivery.md'}, 'finish'),
        ]))

    monkeypatch.setattr(studio, 'run_studio_agent_runtime', runtime)
    with patch('providers.registry.dispatch') as dispatch:
        resumed = await studio.studio_agent_cap('owned-job', studio.AgentCapBody(action='raise', cap_cents=225), None)
        await asyncio.gather(*list(studio._AGENT_TASKS))
    dispatch.assert_not_called()
    execution = repo.get_execution('user:local', resumed['job_id'])
    assert execution['status'] == 'completed'
    assert execution['result']['primary_asset']['version_id'] == old.assets[0]['version_id']
    assert repo.execution_checkpoint('user:local', resumed['job_id'])['request']['delivery_continuation'] is True
    hold = repo.get_run_hold(resumed['job_id'])
    assert hold['state'] == 'released' and hold['status'] == 'done'
    assert hold['charged_cents'] == 20
    assert repo.get_run_hold('owned-job') is None


@pytest.mark.parametrize('defect', [None, 'output', 'review', 'report', 'render', 'finish', 'failed-qc'])
def test_continuation_rechecks_hashes_and_rejects_newer_work(recovery, defect):
    _, _, old = recovery
    request = StudioAgentRequest(prompt=DELIVERY_PROMPT, job_id='continued-job', delivery_continuation=True,
                                prior_tool_events=[old.public()])
    context = _context_from_request(request)
    file = old.result['files'][0]
    if defect == 'output':
        Path(file['output_path']).write_bytes(b'changed output')
    elif defect == 'review':
        Path(file['review_assets'][1]['output_path']).write_bytes(b'changed review')
    elif defect == 'report':
        Path(old.result['report_path']).unlink()
    elif defect == 'render':
        context.record_event(tool_event('Remotion___render_timeline', {'status': 'queued'}, event_id='new-render'))
    elif defect == 'finish':
        context.record_event(tool_event('Ffmpeg___ffmpeg_tool', {'status': 'succeeded'}, event_id='new-finish',
                                         arguments={'op': 'prelimit_mux_aac'}))
    elif defect == 'failed-qc':
        context.record_event(tool_event(QC, {'status': 'failed', 'failures': ['loudness: failed']}, event_id='new-qc'))
    assert _validate_video_delivery(request, context) is (defect is None)


@pytest.mark.asyncio
async def test_hydration_keeps_first_position_when_old_event_is_copied_after_new_finish(recovery, monkeypatch):
    repo, conversation, old = recovery
    finish = tool_event('Ffmpeg___ffmpeg_tool', {'status': 'succeeded'}, event_id='later-finish',
                        arguments={'op': 'prelimit_mux_aac'})
    later = repo.create_execution(workspace_id='user:local', project_id='untitled', user_id='local',
        prompt='Resume saved progress', conversation_id=conversation,
        request={'delivery_continuation': True})['job_id']
    for event in (finish, old):
        repo.append_tool_call(workspace_id='user:local', execution_id=later, event=event.public())
    repo.update_execution('user:local', later, status='error', message='Paused at cap.', error_type='PausedAtCap')
    new_job = repo.create_execution(workspace_id='user:local', project_id='untitled', user_id='local',
                                    prompt=DELIVERY_PROMPT, conversation_id=conversation)['job_id']

    async def runtime(request, *, studio):
        assert [event.id for event in studio.tool_events] == [old.id, finish.id]
        assert request.session_items
        assert not _validate_video_delivery(request, studio)
        raise AgentRunLimitExceeded()

    monkeypatch.setattr(studio, 'run_studio_agent_runtime', runtime)
    await studio._run_studio_agent_job(new_job, DELIVERY_PROMPT, [], conversation,
        workspace_id='user:local', project_id='untitled', user_id='local', delivery_continuation=True)
    assert repo.get_execution('user:local', new_job)['status'] == 'error'


@pytest.mark.asyncio
async def test_fresh_goal_with_saved_session_does_not_inherit_old_tool_assets(recovery, monkeypatch):
    repo, conversation, _ = recovery
    prompt = 'Generate a new image of a red mug.'
    job = repo.create_execution(workspace_id='user:local', project_id='untitled', user_id='local',
                                prompt=prompt, conversation_id=conversation)['job_id']

    async def runtime(request, *, studio):
        assert request.session_items
        assert request.delivery_continuation is False
        assert request.prior_tool_events == [] and studio.tool_events == []
        raise AgentRunLimitExceeded()

    monkeypatch.setattr(studio, 'run_studio_agent_runtime', runtime)
    await studio._run_studio_agent_job(job, prompt, [], conversation,
                                     workspace_id='user:local', project_id='untitled', user_id='local')
    execution = repo.get_execution('user:local', job)
    assert execution['status'] == 'error'
    assert execution['result']['assets'] == []


@pytest.mark.asyncio
@pytest.mark.parametrize('continuation', [True, False])
async def test_cap_partial_preserves_saved_artifact_only_for_trusted_continuation(recovery, monkeypatch, continuation):
    repo, conversation, old = recovery
    job = repo.create_execution(workspace_id='user:local', project_id='untitled', user_id='local',
                                prompt=DELIVERY_PROMPT, conversation_id=conversation)['job_id']

    async def runtime(request, *, studio):
        assert request.session_items and request.delivery_continuation is continuation
        raise run_billing.rb.RunPausedAtCap(run_billing.RunMeter(repo, 'local', request.job_id)._pause())

    monkeypatch.setattr(studio, 'run_studio_agent_runtime', runtime)
    with patch('providers.registry.dispatch') as dispatch:
        await studio._run_studio_agent_job(job, DELIVERY_PROMPT, [], conversation,
            workspace_id='user:local', project_id='untitled', user_id='local', delivery_continuation=continuation)
    dispatch.assert_not_called()
    execution = repo.get_execution('user:local', job)
    assert execution['status'] == 'error' and execution['error_type'] == 'PausedAtCap'
    result = execution['result']
    assert result['partial'] is True
    if continuation:
        assert result['assets'] == old.assets
        assert result['primary_asset'] == old.assets[0]
        assert [event['id'] for event in result['tool_events']] == [old.id]
        assert result['tool_events'][0]['status'] == 'succeeded'
        assert 'did not finish its final reply' in result['summary']
    else:
        assert result['assets'] == [] and result['tool_events'] == []
    hold = repo.get_run_hold(job)
    assert (hold['state'], hold['status'], hold['held_cents'], hold['charged_cents']) == ('held', 'paused_cap', 125, 20)


@pytest.mark.asyncio
@pytest.mark.parametrize('origin_flag', [None, False, 'true'])
async def test_fresh_goal_paused_before_first_call_cannot_resume_an_older_delivery(recovery, monkeypatch, origin_flag):
    repo, conversation, _ = recovery
    repo.release_run('owned-job', status='done')
    prompt = 'Deliver an unrelated new video of a red mug.'
    request = {'prompt': prompt}
    if origin_flag is not None:
        request['delivery_continuation'] = origin_flag
    origin = repo.create_execution(workspace_id='user:local', project_id='untitled', user_id='local',
        prompt=prompt, conversation_id=conversation, request=request)['job_id']
    repo.hold_run('local', origin, 125, conversation_id=conversation)
    run_billing.RunMeter(repo, 'local', origin)._pause()
    repo.update_execution('user:local', origin, status='error', message='Paused at cap.', error_type='PausedAtCap')

    async def runtime(request, *, studio):
        assert request.delivery_continuation is True and request.session_items
        assert request.nodes == [] and request.prior_tool_events == [] and studio.tool_events == []
        assert prompt in request.prompt and DELIVERY_PROMPT not in request.prompt
        raise AgentRunLimitExceeded()

    monkeypatch.setattr(studio, 'run_studio_agent_runtime', runtime)
    with patch('providers.registry.dispatch') as dispatch:
        resumed = await studio.studio_agent_cap(origin, studio.AgentCapBody(action='raise', cap_cents=225), None)
        await asyncio.gather(*list(studio._AGENT_TASKS))
    dispatch.assert_not_called()
    execution = repo.get_execution('user:local', resumed['job_id'])
    assert execution['status'] == 'error' and execution['result']['assets'] == []
    assert execution['result']['tool_events'] == []
    assert repo.get_run_hold(resumed['job_id'])['charged_cents'] == 0


@pytest.mark.asyncio
async def test_failed_motion_probe_survives_cap_resume_with_all_failures_and_report(recovery, monkeypatch):
    import json

    repo, _, old = recovery
    failures = ['no_rests: Add a held moment.', 'unblurred_fast_move: Add motion blur.', 'subject_exit: Reframe the subject.']
    report_path = repo.media_root / 'owned-job' / 'motion-carry.json'
    payload = {'job_id': 'owned-job', 'status': 'failed', 'passed': False,
               'failures': failures, 'report_path': str(report_path)}
    report_path.write_text(json.dumps(payload))
    probe = tool_event('Remotion___motion_carry_probe', payload, event_id='actual-motion-probe',
                       arguments={'job_id': 'owned-job'})
    repo.append_tool_call(workspace_id='user:local', execution_id='owned-job', event=probe.public())
    attempts = 0

    async def runtime(request, *, studio):
        nonlocal attempts
        attempts += 1
        assert [event.id for event in studio.tool_events] == [old.id, probe.id]
        if attempts == 1:
            raise run_billing.rb.RunPausedAtCap(run_billing.RunMeter(repo, 'local', request.job_id)._pause())
        return await run_with_servers(request, studio, [], model=ScriptedModel([
            call('StudioAgentOutput', {'title': 'Motion checked', 'summary': 'Motion checked.',
                 'markdown': '# Motion checked', 'filename': 'motion.md'}, 'finish'),
        ]))

    monkeypatch.setattr(studio, 'run_studio_agent_runtime', runtime)
    with patch('providers.registry.dispatch') as dispatch:
        first = await studio.studio_agent_cap('owned-job', studio.AgentCapBody(action='raise', cap_cents=225), None)
        await asyncio.gather(*list(studio._AGENT_TASKS))
        assert repo.get_execution('user:local', first['job_id'])['error_type'] == 'PausedAtCap'
        resumed = await studio.studio_agent_cap(first['job_id'], studio.AgentCapBody(action='raise', cap_cents=325), None)
        await asyncio.gather(*list(studio._AGENT_TASKS))
    dispatch.assert_not_called()
    execution = repo.get_execution('user:local', resumed['job_id'])
    assert execution['status'] == 'error' and execution['error_type'] == 'DeliverableIncomplete'
    assert execution['result']['partial'] is True
    for failure in [*failures, str(report_path)]:
        assert failure in execution['result']['markdown']
    assert 'No current saved passing motion report' not in execution['result']['markdown']
    assert repo.get_run_hold(resumed['job_id'])['state'] == 'released'
