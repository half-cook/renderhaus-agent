import pytest

from langchain_core.messages import AIMessage

from agent.deep_agent.runner import run_with_servers
from agent.deep_agent.sandbox import JobSandbox
from agent.studio_agent_next import StudioAgentRequest, _context_from_request
from test_deep_agent import ScriptedModel, Gateway, call


@pytest.mark.asyncio
async def test_real_graph_inspects_views_and_grades_final_file(tmp_path, monkeypatch):
    monkeypatch.setenv('RENDERHAUS_MEDIA_DIR', str(tmp_path))
    directory = tmp_path / 'finish-test'
    sandbox = JobSandbox(directory)
    assert sandbox.execute('ffmpeg -v error -f lavfi -i color=c=blue:s=64x64:d=1 -c:v libx264 clip.mp4').exit_code == 0
    payload = {'title': 'Clip', 'summary': 'The clip was inspected.', 'markdown': '# Clip',
               'filename': 'clip.md', 'media_paths': ['/work/clip.mp4']}
    verdict = {'result': 'satisfied', 'explanation': 'The current file was measured and viewed; unrelated rubrics do not apply.',
               'criteria': [{'name': 'Inspect and view current output', 'passed': True}]}
    model = ScriptedModel([
        call('inspect_media', {'path': '/work/clip.mp4'}, 'inspect'),
        call('read_file', {'file_path': '/work/clip.mp4', 'offset': 0, 'limit': 1}, 'view'),
        call('StudioAgentOutput', payload, 'finish'),
        call('GraderResponse', verdict, 'grade'),
    ])
    request = StudioAgentRequest(prompt='Inspect this clip', job_id='finish-test')
    studio = _context_from_request(request)
    result = await run_with_servers(request, studio, [Gateway()], model=model)
    assert not model._steps
    assert 'incomplete' not in result.summary.lower()
    assert any(any(isinstance(block, dict) and block.get('type') == 'image' for block in msg.content)
               for messages, _ in model._seen for msg in messages if isinstance(msg.content, list))


@pytest.mark.asyncio
async def test_finish_gate_allows_only_two_repairs_then_reports_blocker(tmp_path, monkeypatch):
    monkeypatch.setenv('RENDERHAUS_MEDIA_DIR', str(tmp_path))
    payload = {'title': 'Clip', 'summary': 'Ready.', 'markdown': '# Clip',
               'filename': 'clip.md', 'media_paths': ['/work/missing.mp4']}
    model = ScriptedModel([call('StudioAgentOutput', payload, str(i)) for i in range(3)])
    request = StudioAgentRequest(prompt='Inspect this clip', job_id='finish-test')
    result = await run_with_servers(request, _context_from_request(request), [Gateway()], model=model)
    assert not model._steps
    assert result.summary.startswith('Incomplete.')


@pytest.mark.asyncio
async def test_shell_output_cannot_omit_paths_to_skip_inspection(tmp_path, monkeypatch):
    monkeypatch.setenv('RENDERHAUS_MEDIA_DIR', str(tmp_path))
    payload = {'title': 'Clip', 'summary': 'Ready.', 'markdown': '# Clip', 'filename': 'clip.md'}
    model = ScriptedModel([call('execute', {'command':
        'ffmpeg -v error -f lavfi -i color=c=blue:s=32x32:d=1 clip.mp4'}, 'render'),
        *[call('StudioAgentOutput', payload, str(i)) for i in range(3)]])
    request = StudioAgentRequest(prompt='Make a local clip.', job_id='omitted-shell-output')
    studio = _context_from_request(request)
    result = await run_with_servers(request, studio, [Gateway()], model=model)
    assert 'incomplete' in result.summary.lower()
    assert 'inspect_media' in result.markdown
    assert not model._steps
    assert not any(event.name == 'Local___artifact' for event in studio.tool_events)


@pytest.mark.asyncio
async def test_inspected_decoy_cannot_certify_a_different_linked_deliverable(tmp_path, monkeypatch):
    monkeypatch.setenv('RENDERHAUS_MEDIA_DIR', str(tmp_path))
    sandbox = JobSandbox(tmp_path / 'decoy')
    assert sandbox.execute('ffmpeg -v error -f lavfi -i color=c=blue:s=32x32:d=1 decoy.mp4 && cp decoy.mp4 final.mp4').exit_code == 0
    payload = {'title': 'Clip', 'summary': 'Ready.', 'markdown': '[Final](/work/final.mp4)',
               'filename': 'clip.md', 'media_paths': ['/work/decoy.mp4']}
    def finish_or_grade(_, tools):
        if 'GraderResponse' in tools:
            return call('GraderResponse', {'result': 'satisfied', 'explanation': 'Saw the decoy.',
                'criteria': [{'name': 'Viewed', 'passed': True}]}, 'grade')
        return call('StudioAgentOutput', payload, 'finish-again')
    model = ScriptedModel([call('inspect_media', {'path': '/work/decoy.mp4'}, 'inspect'),
        call('read_file', {'file_path': '/work/decoy.mp4', 'limit': 1}, 'view'),
        call('StudioAgentOutput', payload, 'finish'), finish_or_grade, finish_or_grade])
    request = StudioAgentRequest(prompt='Inspect the final clip.', job_id='decoy')
    result = await run_with_servers(request, _context_from_request(request), [Gateway()], model=model)
    assert result.summary.startswith('Incomplete.')


def grade(result):
    criterion = {'name': 'Current file is inspected', 'passed': result == 'satisfied'}
    if result != 'satisfied':
        criterion['gap'] = 'Revise the file and finish again.'
    return call('GraderResponse', {'result': result, 'explanation': 'Current-file review.',
                'criteria': [criterion]}, 'grade-' + result)


@pytest.mark.asyncio
async def test_grader_cannot_publish_a_stale_finish_after_revision(tmp_path, monkeypatch):
    monkeypatch.setenv('RENDERHAUS_MEDIA_DIR', str(tmp_path))
    sandbox = JobSandbox(tmp_path / 'revision')
    assert sandbox.execute('ffmpeg -v error -f lavfi -i color=c=blue:s=32x32:d=1 clip.mp4').exit_code == 0
    payload = {'title': 'Clip', 'summary': 'Ready.', 'markdown': '# Clip', 'filename': 'clip.md',
               'media_paths': ['/work/clip.mp4']}
    model = ScriptedModel([call('inspect_media', {'path': '/work/clip.mp4'}, 'inspect'),
        call('read_file', {'file_path': '/work/clip.mp4', 'limit': 1}, 'view'),
        call('StudioAgentOutput', payload, 'finish'), grade('needs_revision'),
        call('execute', {'command': 'printf changed >> clip.mp4'}, 'change'),
        AIMessage(content='Ready.'), grade('satisfied')])
    request = StudioAgentRequest(prompt='Inspect the clip.', job_id='revision')
    studio = _context_from_request(request)
    result = await run_with_servers(request, studio, [Gateway()], model=model)
    assert result.summary.startswith('Incomplete.')
    assert not any(event.name == 'Local___artifact' for event in studio.tool_events)
    assert not model._steps


@pytest.mark.asyncio
async def test_new_turn_has_a_fresh_rubric_revision_allowance(tmp_path, monkeypatch):
    monkeypatch.setenv('RENDERHAUS_MEDIA_DIR', str(tmp_path))
    sandbox = JobSandbox(tmp_path / 'fresh-rubric')
    assert sandbox.execute('ffmpeg -v error -f lavfi -i color=c=blue:s=32x32:d=1 clip.mp4').exit_code == 0
    payload = {'title': 'Clip', 'summary': 'Ready.', 'markdown': '# Clip', 'filename': 'clip.md',
               'media_paths': ['/work/clip.mp4']}
    def steps(revisions):
        initial = [call('inspect_media', {'path': '/work/clip.mp4'}, 'inspect'),
                   call('read_file', {'file_path': '/work/clip.mp4', 'limit': 1}, 'view'),
                   call('StudioAgentOutput', payload, 'finish')]
        for index in range(revisions):
            initial += [grade('needs_revision'), call('StudioAgentOutput', payload, f'finish-{index}')]
        return [*initial, grade('satisfied')]
    request = StudioAgentRequest(prompt='Inspect the clip.', job_id='fresh-rubric', conversation_id='conversation')
    studio = _context_from_request(request)
    await run_with_servers(request, studio, [Gateway()], model=ScriptedModel(steps(2)))
    resumed = request.model_copy(update={'session_items': studio.session_items})
    model = ScriptedModel(steps(1))
    result = await run_with_servers(resumed, _context_from_request(resumed), [Gateway()], model=model)
    assert not model._steps
    assert result.summary == 'Ready.'


@pytest.mark.asyncio
async def test_grader_budget_stop_propagates_even_without_an_update_message(tmp_path, monkeypatch):
    from server import studio_state
    from server.run_budget import RunPausedAtCap
    from server.studio_state import StudioRepository

    monkeypatch.setenv('RENDERHAUS_MEDIA_DIR', str(tmp_path))
    repo = StudioRepository(tmp_path / 'credits.sqlite3', tmp_path)
    monkeypatch.setattr(studio_state, 'repository', repo)
    repo.adjust_balance('user', 10_000, 'test_credit')
    repo.hold_run('user', 'grader-cap', 5_000)
    sandbox = JobSandbox(tmp_path / 'grader-cap')
    assert sandbox.execute('ffmpeg -v error -f lavfi -i color=c=blue:s=32x32:d=1 clip.mp4').exit_code == 0
    payload = {'title': 'Clip', 'summary': 'Ready.', 'markdown': '# Clip', 'filename': 'clip.md',
               'media_paths': ['/work/clip.mp4']}
    def cap_at_grading(_, tools):
        assert 'GraderResponse' in tools
        pause = {'status': 'paused_cap', 'message': 'The next review exceeds the remaining cap.'}
        repo.set_run_pause('grader-cap', pause)
        raise RunPausedAtCap(pause)
    model = ScriptedModel([call('inspect_media', {'path': '/work/clip.mp4'}, 'inspect'),
        call('read_file', {'file_path': '/work/clip.mp4', 'limit': 1}, 'view'),
        call('StudioAgentOutput', payload, 'finish'), cap_at_grading])
    request = StudioAgentRequest(prompt='Inspect the clip.', job_id='grader-cap', user_id='user')
    studio = _context_from_request(request)
    with pytest.raises(RunPausedAtCap):
        await run_with_servers(request, studio, [Gateway()], model=model)
    assert repo.get_run_hold('grader-cap')['status'] == 'paused_cap'
    assert not any(event.name == 'Local___artifact' for event in studio.tool_events)
