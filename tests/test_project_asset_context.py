from __future__ import annotations

from contextlib import asynccontextmanager
import json
from unittest.mock import AsyncMock

from langchain_core.messages import ToolMessage
import pytest

from agent.studio_agent_next import StudioAgentOutput, StudioNode, StudioToolEvent, _media_input_arguments
from server import studio, studio_state
from server.studio_state import StudioRepository
from test_deep_agent import Gateway, ScriptedModel, call


@pytest.fixture
def repo(tmp_path, monkeypatch):
    repository = StudioRepository(tmp_path / 'studio.sqlite3', tmp_path / 'media')
    for workspace, project in [('user:local', 'project'), ('user:local', 'other'), ('user:foreign', 'project')]:
        repository.create_project(workspace, workspace.split(':')[1], project, project_id=project)
    monkeypatch.setattr(studio, 'repository', repository)
    monkeypatch.setattr(studio_state, 'repository', repository)
    monkeypatch.setenv('AGENTCORE_DEV_URL', '')
    monkeypatch.setenv('RENDERHAUS_AGENT_BACKEND', 'deepagents')
    monkeypatch.setenv('RENDERHAUS_MEDIA_DIR', str(repository.media_root))
    return repository


def save(repo, filename, kind='audio', workspace='user:local', project='project', asset_id=None):
    return repo.register_bytes(workspace_id=workspace, project_id=project, user_id=workspace.split(':')[1],
                               content=b'owned fixture for inventory discovery', filename=filename, kind=kind,
                               asset_id=asset_id)


def test_inventory_is_project_and_workspace_scoped_and_uses_current_versions(repo):
    old = save(repo, 'old-voice.mp3')
    current = save(repo, 'revised-voice.mp3', asset_id=old.asset_id)
    video = save(repo, 'cube.mp4', 'video')
    save(repo, 'private-other-project.mp3', project='other')
    save(repo, 'private-other-workspace.mp3', workspace='user:foreign')
    inventory = repo.list_project_assets('user:local', 'project')
    assert {asset['version_id'] for asset in inventory} == {current.version_id, video.version_id}
    assert all(asset['source_ref'] == 'renderhaus-asset://' + asset['version_id'] for asset in inventory)
    assert not any(key in asset for asset in inventory for key in ['storage_key', 'source', 'url', 'output_path'])
    assert len(repo.list_project_assets('user:local', 'project', limit=1)) == 1
    with pytest.raises(KeyError):
        repo.list_project_assets('user:unknown', 'project')


def test_inventory_has_a_fixed_metadata_bound(repo):
    for index in range(102):
        save(repo, f'voice-{index}.mp3')
    assert len(repo.list_project_assets('user:local', 'project', limit=1_000)) == 100


@pytest.mark.asyncio
async def test_local_runtime_finds_saved_media_and_keeps_selected_focus(repo, monkeypatch):
    voice = save(repo, 'existing-voice.mp3')
    video = save(repo, 'generated-hash.mp4', 'video')
    selected = save(repo, 'selected.png', 'image')
    foreign = save(repo, 'private.mp3', project='other')
    canvas = repo.get_canvas('user:local', 'project')['document']
    canvas['nodes'] = [None, {'data': 'legacy-invalid'}, {'data': {'output': {'versionId': []}}},
                       {'id': 'cube', 'data': {'title': 'Scene', 'config': {'prompt': 'Cyan glass cube'},
                                             'output': video.canvas()}}]
    repo.save_canvas('user:local', 'project', 'local', canvas)
    selected_node = StudioNode(id='selected', title='Selected focus', kind='image',
                               asset_id=selected.asset_id, version_id=selected.version_id)
    seen = {}

    def find_asset(messages, _):
        context = json.loads(next(message.text for message in reversed(messages) if isinstance(message, ToolMessage)))
        assets = {asset['version_id']: asset for asset in context['assets']}
        assert {voice.version_id, video.version_id, selected.version_id} <= assets.keys()
        assert foreign.version_id not in assets
        assert assets[video.version_id]['title'] == 'Scene'
        assert assets[video.version_id]['prompt'] == 'Cyan glass cube'
        assert assets[selected.version_id]['filename'] == 'Selected focus'
        assert 'Selected focus' in context['references'] and 'Cyan glass cube' not in context['references']
        seen['context'] = context
        return call('stage_media', {'asset_ref': assets[voice.version_id]['source_ref']}, 'stage')

    def finish(messages, _):
        staged = json.loads(next(message.text for message in reversed(messages) if isinstance(message, ToolMessage)))
        assert staged['status'] == 'staged'
        return call('StudioAgentOutput', {'title': 'Found saved media', 'summary': 'Available project media was found.',
                                        'markdown': '# Available media', 'filename': 'inventory.md'}, 'finish')

    model = ScriptedModel([call('read_studio_context', {}, 'context'), find_asset, finish])
    transport = Gateway(tools=[])

    @asynccontextmanager
    async def gateway(**kwargs):
        yield transport

    import agent.studio_agent_next as runtime
    monkeypatch.setattr(runtime, 'gateway_mcp_server', gateway)
    monkeypatch.setattr('agent.deep_agent.runner.configured_deep_agent_model', lambda role=None: model)
    original_runtime = studio.run_studio_agent_runtime

    async def inspect_request(request, **kwargs):
        assert request.nodes == [selected_node]
        assert kwargs['studio'].nodes == [selected_node]
        assert _media_input_arguments(kwargs['studio'].nodes) == {'image_url': 'renderhaus-asset://' + selected.version_id}
        return await original_runtime(request, **kwargs)

    monkeypatch.setattr(studio, 'run_studio_agent_runtime', inspect_request)
    result = await studio.run_studio_agent('Find the available saved audio and video; do not generate new media.',
                                           nodes=[selected_node], workspace_id='user:local', project_id='project',
                                           user_id='local', job_id='discovery',
                                           source_resolver=lambda version: str(repo.version_path('user:local', version)))
    assert result.final.title == 'Found saved media'
    assert seen['context']
    assert not model._steps
    transport.call_tool.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('declined', [False, True])
async def test_unmet_video_request_stays_incomplete_but_explicit_decline_is_a_reply(repo, monkeypatch, declined):
    conversation = repo.create_conversation('user:local', 'project', 'local')['id']
    prompt = 'Assemble a four-second MP4 from existing media; generate no new media.'
    job = repo.create_execution(workspace_id='user:local', project_id='project', user_id='local', prompt=prompt,
                                conversation_id=conversation, request={'prompt': prompt})['job_id']
    events = [StudioToolEvent(id='no', name='Fal___generate_wan3_t2v', label='Video', status='rejected',
                              summary='Declined.')] if declined else []
    outcome = studio.StudioAgentRun(
        final=StudioAgentOutput(title='Incomplete: source media not available', summary='Incomplete. No MP4 was saved.',
                                markdown='# Missing media', filename='result.md'), tool_events=events, session_items=[])
    monkeypatch.setattr(studio, 'run_studio_agent', AsyncMock(return_value=outcome))
    await studio._run_studio_agent_job(job, prompt, [], conversation,
                                     workspace_id='user:local', project_id='project', user_id='local')
    execution = repo.get_execution('user:local', job)
    assert execution['status'] == ('completed' if declined else 'error')
    if declined:
        assert execution['result']['title'] == 'Not now'
    else:
        assert execution['error_type'] == 'DeliverableIncomplete'
        assert execution['result']['partial'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('incomplete', [True, False])
async def test_saved_video_keeps_explicit_incomplete_status_but_allows_finished_with_warnings(repo, monkeypatch, incomplete):
    conversation = repo.create_conversation('user:local', 'project', 'local')['id']
    prompt = 'Assemble the existing video and voiceover, then save delivery QC.'
    job = repo.create_execution(workspace_id='user:local', project_id='project', user_id='local', prompt=prompt,
                                conversation_id=conversation, request={'prompt': prompt})['job_id']
    video = save(repo, 'assembled.mp4', 'video').public()
    summary = ('Incomplete. Loudness passed only against a custom target; it failed the default target.'
               if incomplete else 'Finished. Saved QC passed. Placeholder channel preset and editorial review warnings remain.')
    event = StudioToolEvent(id='qc', name='Remotion___qc_deliverable', label='QC', status='succeeded',
                            summary='QC passed.', assets=[video], result={'passed': True})
    outcome = studio.StudioAgentRun(
        final=StudioAgentOutput(title='Assembled video', summary=summary, markdown='# Result', filename='result.md'),
        tool_events=[event], session_items=[])
    monkeypatch.setattr(studio, 'run_studio_agent', AsyncMock(return_value=outcome))
    await studio._run_studio_agent_job(job, prompt, [], conversation,
                                     workspace_id='user:local', project_id='project', user_id='local')
    execution = repo.get_execution('user:local', job)
    assert execution['status'] == ('error' if incomplete else 'completed')
    assert execution['result']['assets'] == [video]
    assert execution['result']['summary'] == summary
    assert execution['tool_calls'][0]['status'] == 'succeeded'
    if incomplete:
        assert execution['error_type'] == 'DeliverableIncomplete'
        assert execution['result']['partial'] is True
