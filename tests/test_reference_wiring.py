from __future__ import annotations

import base64
import asyncio
import io
import json
from unittest.mock import patch

import pytest
from PIL import Image

from providers.catalog import get_provider
from providers.registry import dispatch, generate_schemas
from test_reference_shots import films as films, job as job


def sheet_b64():
    output = io.BytesIO()
    Image.new('RGB', (640, 360), 'red').save(output, format='PNG')
    return base64.b64encode(output.getvalue()).decode()


def test_contact_sheet_judge_is_discovered_separately_from_continuity():
    names = {row['name'] for row in generate_schemas(get_provider('gemini'))}
    assert 'judge_shots' in names
    assert 'judge_continuity' in names


def test_reference_analysis_routes_apart_from_raw_footage_and_continuity():
    from agent.deep_agent.routing import route_intent

    for prompt in ('Break this finished ad down shot by shot so we can remake it.',
                   'What is the pacing of this reference trailer?',
                   'Give me a shot list of this reference film.',
                   'How many cuts per minute is this TikTok?'):
        route = route_intent(prompt)
        assert route.skill == 'reference-shot-breakdown'
        assert route.alias == 'shot_breakdown'
        assert route.tool == 'Reference___shot_breakdown'
    assert route_intent('Find the moment where she talks about childhood in my raw footage.').skill == 'footage-memory'
    assert route_intent('Check shot continuity between these generated shots.').skill == 'continuity-qc'


def test_shot_judge_dry_run_is_incomplete_and_poll_reuses_the_rubric():
    with patch.dict('os.environ', {'GEMINI_DRY_RUN': 'true'}):
        result = dispatch('gemini', 'judge_shots', {
            'contact_sheet_b64': [sheet_b64()], 'shot_ids': [1, 2],
        })
        assert result['status'] == 'skipped'
        assert result['rubric'] == 'reference_shots'
        assert 'shots' not in result
        assert not result['training_eligible']
        polled = dispatch('gemini', 'get_task', {
            'job_id': result['job_id'], 'rubric': 'reference_shots', 'shot_ids': [1, 2],
        })
        assert polled['status'] == 'skipped'
        assert polled['rubric'] == 'reference_shots'


@pytest.mark.parametrize('changes', [
    {'contact_sheet_b64': ['invalid']}, {'shot_ids': [1, 1]},
    {'shot_ids': [True]}, {'shot_ids': []}, {'shot_ids': [0]},
])
def test_invalid_shot_judge_arguments_fail_before_transport(changes):
    args = {'contact_sheet_b64': [sheet_b64()], 'shot_ids': [1]}
    with patch('providers.gemini.api._request', side_effect=AssertionError('transport called')):
        with pytest.raises(ValueError):
            dispatch('gemini', 'judge_shots', {**args, **changes})


def test_mocked_shot_judge_submits_once_and_polls_without_retiming():
    from providers.gemini.api import INTERACTIONS_URL

    labels = {'shots': [{'shot_id': 1, 'shot_size': 'wide', 'category': 'product',
                         'camera_move': 'static', 'frame_description': 'A red object.',
                         'rhythm_role': 'hook'}]}
    queued = {'id': 'shot-job', 'model': 'gemini-3.8-flash', 'status': 'in_progress'}
    completed = {**queued, 'status': 'completed', 'steps': [
        {'type': 'model_output', 'content': [{'type': 'text', 'text': json.dumps(labels)}]},
    ]}
    with patch.dict('os.environ', {'GEMINI_DRY_RUN': 'false'}), patch(
        'providers.gemini.api._request', side_effect=[queued, completed],
    ) as request:
        submitted = dispatch('gemini', 'judge_shots', {
            'contact_sheet_b64': [sheet_b64()], 'shot_ids': [1],
        })
        assert submitted['status'] == 'running'
        result = dispatch('gemini', 'get_task', {
            'job_id': 'shot-job', 'rubric': 'reference_shots', 'shot_ids': [1],
        })
        assert result['shots'] == labels['shots']
        assert request.call_args_list[0].args[:2] == ('POST', INTERACTIONS_URL)
        assert request.call_args_list[1].args[:2] == ('GET', INTERACTIONS_URL + '/shot-job')
        body = request.call_args_list[0].args[4]
        assert body['background'] is True
        assert body['store'] is True
        assert 'start_seconds' not in body['response_format']['schema']['properties']


def test_mocked_shot_judge_rejects_model_timing_and_wrong_shot_ids():
    labels = {'shots': [{'shot_id': 2, 'shot_size': 'wide', 'category': 'product',
                         'camera_move': 'static', 'frame_description': 'An object.',
                         'rhythm_role': 'hook', 'duration_seconds': 1}]}
    completed = {'id': 'shot-job', 'model': 'gemini-3.8-flash', 'status': 'completed', 'steps': [
        {'type': 'model_output', 'content': [{'type': 'text', 'text': json.dumps(labels)}]},
    ]}
    with patch.dict('os.environ', {'GEMINI_DRY_RUN': 'false'}), patch(
        'providers.gemini.api._request', return_value=completed,
    ):
        result = dispatch('gemini', 'judge_shots', {
            'contact_sheet_b64': [sheet_b64()], 'shot_ids': [1],
        })
        assert result['status'] == 'skipped'
        assert 'shots' not in result


def test_shot_label_approval_rejection_and_unknown_cap_prevent_submission(tmp_path):
    asyncio.run(check_shot_label_approval(tmp_path))


async def check_shot_label_approval(tmp_path):
    from agent.deep_agent.runner import run_with_servers
    from agent.gateway_executor import GatewayExecutor
    from agent.studio_agent_next import (
        StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, _context_from_request,
    )
    from test_deep_agent import ScriptedModel, call, final

    args = {'contact_sheet_b64': [sheet_b64()], 'shot_ids': [1]}
    with patch.dict('os.environ', {'GEMINI_DRY_RUN': 'true', 'GEMINI_TOOL_COST_CENTS_JSON': '{}',
                                  'RENDERHAUS_OUTCOME_DIR': str(tmp_path)}), patch(
        'providers.gemini.api._request', side_effect=AssertionError('No provider call authorized'),
    ):
        request = StudioAgentRequest(prompt='Break down this reference ad shot by shot.',
                                     autonomous=False, job_id='reference-approval')
        studio = _context_from_request(request)
        with pytest.raises(StudioAgentApprovalRequired) as paused:
            await run_with_servers(request, studio, [], model=ScriptedModel([
                call('read_file', {'file_path': '/skills/reference-shot-breakdown/SKILL.md'}, 'skill'),
                call('call_media_tool', {'tool_name': 'Gemini___judge_shots', 'arguments': args}, 'judge'),
            ]))
        approval = paused.value.approvals[0]
        assert 'unknown' in approval.description.lower()
        assert not any(word in approval.description.lower() for word in ('gemini', 'platform fee'))
        request = request.model_copy(update={'session_items': studio.session_items,
            'resume_state': paused.value.state, 'approval_decisions': [
                StudioApprovalDecision(call_id=approval.call_id, decision='reject')]})
        studio = _context_from_request(request)
        await run_with_servers(request, studio, [], model=ScriptedModel([final()]))
        assert studio.tool_events[-1].status == 'rejected'
        capped = _context_from_request(StudioAgentRequest(
            prompt='Analyze this reference.', autonomous=True, job_id='reference-cap',
        ))
        with patch.dict('os.environ', {'RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS': '5'}):
            result = await GatewayExecutor(capped, []).execute({
                'tool_name': 'Gemini___judge_shots', 'arguments': args, 'call_id': 'cap-judge',
            }, approved=True)
        assert result['status'] == 'not_run'
        assert 'unknown' in result['reason'].lower()


def test_reference_review_requires_the_current_owned_job():
    from agent.gateway_executor import GatewayExecutor
    from agent.studio_agent_next import StudioAgentRequest, _context_from_request

    studio = _context_from_request(StudioAgentRequest(prompt='Analyze a reference.', job_id='owned'))
    args = {'reference': {'job_id': 'foreign', 'analysis_path': 'bundle/measurements.json',
                          'measurements_sha256': 'a' * 64}}
    result = GatewayExecutor(studio, []).selection_blocker('Gemini___judge_shots', args, None)
    assert 'trusted current Studio job' in result


def test_dry_run_owned_source_is_never_read_or_staged():
    from types import SimpleNamespace
    from agent.gateway_executor import _local_reference_arguments

    def forbidden_source(_):
        raise AssertionError('Dry-run must not read the asset')

    studio = SimpleNamespace(job_id='owned', source_resolver=forbidden_source)
    args = {'op': 'measure', 'job_id': 'owned', 'input_path': 'renderhaus-asset://video-v1'}
    with patch.dict('os.environ', {'REFERENCE_SHOTS_DRY_RUN': 'true'}):
        assert _local_reference_arguments(studio, args) == args


def test_approved_shot_review_dry_run_is_saved_as_incomplete(tmp_path):
    from agent.gateway_executor import GatewayExecutor
    from agent.studio_agent_next import StudioAgentRequest, _context_from_request

    async def run():
        studio = _context_from_request(StudioAgentRequest(prompt='Analyze reference shots.',
                                                         job_id='approved-reference'))
        result = await GatewayExecutor(studio, []).execute({
            'tool_name': 'Gemini___judge_shots', 'call_id': 'approved-review',
            'arguments': {'reference': {'job_id': studio.job_id,
                          'analysis_path': 'bundle/measurements.json', 'measurements_sha256': 'a' * 64}},
        }, approved=True)
        assert result['status'] == 'skipped'
        assert 'shots' not in result
        assert studio.tool_events[-1].status == 'skipped'
        rows = [json.loads(line) for line in (tmp_path / 'outcomes.jsonl').read_text().splitlines()]
        assert rows[-1]['ab_arm'] == 'gemini_shot_labels'

    with patch.dict('os.environ', {'GEMINI_DRY_RUN': 'true', 'RENDERHAUS_OUTCOME_DIR': str(tmp_path),
                                  'RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS': ''}), patch(
        'providers.gemini.api._request', side_effect=AssertionError('No provider call authorized'),
    ):
        asyncio.run(run())


def test_local_shot_poll_keeps_polling_the_same_transport(tmp_path):
    from unittest.mock import AsyncMock
    from agent.gateway_executor import GatewayExecutor
    from agent.studio_agent_next import StudioAgentRequest, _context_from_request

    labels = {'shots': [{'shot_id': 1, 'shot_size': 'wide', 'category': 'product',
                         'camera_move': 'static', 'frame_description': 'An object.',
                         'rhythm_role': 'hook'}]}
    running = {'id': 'shot-job', 'model': 'gemini-3.8-flash', 'status': 'in_progress'}
    done = {**running, 'status': 'completed', 'steps': [
        {'type': 'model_output', 'content': [{'type': 'text', 'text': json.dumps(labels)}]},
    ]}

    async def run():
        studio = _context_from_request(StudioAgentRequest(prompt='Analyze reference shots.', job_id='poll-reference'))
        result = await GatewayExecutor(studio, []).execute({
            'tool_name': 'Gemini___get_task', 'call_id': 'poll',
            'arguments': {'job_id': 'shot-job', 'rubric': 'reference_shots', 'shot_ids': [1]},
        }, approved=True)
        assert result['status'] == 'succeeded'
        assert result['shots'] == labels['shots']

    with patch.dict('os.environ', {'GEMINI_DRY_RUN': 'false', 'STUDIO_MEDIA_WAIT_SECONDS': '30',
                                  'RENDERHAUS_OUTCOME_DIR': str(tmp_path)}), patch(
        'providers.gemini.api._request', side_effect=[running, done],
    ), patch('agent.gateway_executor.asyncio.sleep', new_callable=AsyncMock):
        asyncio.run(run())


def test_owned_manifest_bridge_sends_only_pinned_contact_sheets(job):
    import hashlib
    from pathlib import Path

    measured = dispatch('reference_shots', 'shot_breakdown', {
        'op': 'measure', 'job_id': 'job', 'input_path': 'cuts.mp4',
    })
    labels = [{'shot_id': i, 'shot_size': 'wide', 'category': 'graphic',
               'camera_move': 'static', 'frame_description': 'A colour field.',
               'rhythm_role': 'build'} for i in (1, 2, 3)]
    done = {'id': 'owned-shot-job', 'model': 'gemini-3.8-flash', 'status': 'completed', 'steps': [
        {'type': 'model_output', 'content': [{'type': 'text', 'text': json.dumps({'shots': labels})}]},
    ]}
    with patch.dict('os.environ', {'GEMINI_DRY_RUN': 'false'}), patch(
        'providers.gemini.api._request', return_value=done,
    ) as request:
        result = dispatch('gemini', 'judge_shots', {'reference': {
            'job_id': 'job', 'analysis_path': measured['analysis_path'],
            'measurements_sha256': measured['measurements_sha256'],
        }})
        assert result['shots'] == labels
        body = request.call_args.args[4]
        images = [part for part in body['input'] if part['type'] == 'image']
        assert len(images) == len(measured['contact_sheets'])
        assert [hashlib.sha256(base64.b64decode(part['data'])).hexdigest() for part in images] == [
            sheet['sha256'] for sheet in measured['contact_sheets']]
        assert all(part['mime_type'] == 'image/jpeg' for part in images)
    report = dispatch('reference_shots', 'shot_breakdown', {
        'op': 'report', 'job_id': 'job', 'input_path': measured['analysis_path'],
        'params': {'labels': result['shots'], 'measurements_sha256': measured['measurements_sha256'],
                   'labels_provenance': 'simulated'},
    })
    assert report['status'] == 'incomplete'
    assert json.loads(Path(report['shots_path']).read_text())['semantic_review'] == 'pending_visual_review'
