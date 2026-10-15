from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def job(tmp_path, monkeypatch):
    monkeypatch.setenv('RENDERHAUS_MEDIA_DIR', str(tmp_path))
    directory = tmp_path / 'ui-animation'
    directory.mkdir()
    return directory


def test_author_validate_package_and_patch_real_files(job):
    from providers.lottie.api import lottie_author, lottie_validate
    from providers.lottie.container import unpack_lottie

    result = lottie_author(job.name, scene={'layers': [
        {'name': 'Success badge', 'shape': 'ellipse', 'fill': '#168B52'},
    ]})
    assert result['ok'], result
    files = {Path(row['path']).suffix: row for row in result['outputs']}
    assert {'.json', '.lottie'} <= files.keys()
    for row in result['outputs']:
        data = Path(row['path']).read_bytes()
        assert row['bytes'] == len(data)
        assert row['sha256'] == hashlib.sha256(data).hexdigest()
    document = json.loads(Path(files['.json']['path']).read_text())
    assert unpack_lottie(Path(files['.lottie']['path']).read_bytes()) == document
    checked = lottie_validate(job.name, files['.json']['path'])
    assert checked['ok'], checked
    assert checked['source_sha256'] == files['.json']['sha256']
    assert result['metadata']['frame_count'] == 90
    assert result['metadata']['fps'] == 60
    assert result['metadata']['duration_seconds'] == 1.5
    assert set(result['usage']) == {'web', 'ios', 'android'}
    changed = lottie_author(job.name, input_path=files['.json']['path'], patch={'nm': 'Saved revision'})
    assert changed['ok'], changed
    assert json.loads(Path(changed['outputs'][0]['path']).read_text())['nm'] == 'Saved revision'
    assert json.loads(Path(files['.json']['path']).read_text())['nm'] != 'Saved revision'


@pytest.mark.parametrize('tool,kwargs', [
    ('lottie_author', {'input_path': '../outside.json'}),
    ('lottie_validate', {'input_path': '../outside.json'}),
    ('lottie_preview_render', {'input_path': '../outside.json'}),
    ('lottie_author', {'scene': {'layers': []}, 'name': '../escape'}),
])
def test_tools_fail_soft_on_unconfined_paths(job, tool, kwargs):
    from providers.lottie import api

    result = getattr(api, tool)(job.name, **kwargs)
    assert result['ok'] is False
    assert result['errors']
    assert result['outputs'] == []
    assert list(job.iterdir()) == []


def test_local_dispatch_free_policy_and_neutral_labels():
    from agent.deep_agent.routing import is_free_tool, resolve_alias, tool_parts
    from agent.deep_agent.runner import DISPATCH_TARGETS
    from agent.gateway_executor import APPROVAL_EXEMPT_TOOLS, LOCAL_MEDIA_TOOLS, tool_needs_approval
    from agent.studio_agent_next import _gateway_tool_parts, _title_for_gateway_tool
    from providers.catalog import get_provider
    from providers.registry import generate_schemas
    from server.billing_rates import cost_for

    assert 'Lottie' in DISPATCH_TARGETS['call_editor_tool']
    schemas = generate_schemas(get_provider('lottie'))
    assert {row['name'] for row in schemas} == {'lottie_author', 'lottie_validate', 'lottie_preview_render'}
    for row in schemas:
        name = 'Lottie___' + row['name']
        assert name == resolve_alias(row['name'])
        assert tool_parts(name) == ('lottie', row['name'])
        assert is_free_tool(name)
        assert name in LOCAL_MEDIA_TOOLS
        assert APPROVAL_EXEMPT_TOOLS == frozenset({'Remotion___export_nle_timeline'})
        assert not tool_needs_approval(name, False)
        assert not tool_needs_approval(name, True)
        assert cost_for('lottie', row['name'], {}).total_cents == 0
        label = _title_for_gateway_tool('Lottie', row['name']).lower()
        assert not any(word in label for word in ('lottie', 'vendor', 'free', 'fee', '$', 'provider'))
        assert _gateway_tool_parts(name)[2] == _title_for_gateway_tool('Lottie', row['name'])


def test_dispatch_contract_refuses_unknown_fields_before_handler(job):
    from providers.registry import dispatch

    with pytest.raises(ValueError, match='unsupported fields: command'):
        dispatch('lottie', 'lottie_author', {'job_id': job.name, 'scene': {'layers': []}, 'command': 'oops'})


def test_preview_api_preserves_source_hash_and_raster_dimensions(job):
    from providers.lottie.api import lottie_author, lottie_preview_render

    authored = lottie_author(job.name, scene={'width': 128, 'height': 64, 'frames': 4,
        'layers': [{'name': 'Status dot', 'shape': 'ellipse', 'fill': '#168B52'}]})
    source = authored['outputs'][0]
    preview = lottie_preview_render(job.name, source['path'], max_size=64, formats=[])
    assert preview['ok'], preview
    assert preview['complete'] is True
    assert preview['source_sha256'] == source['sha256']
    assert preview['metadata']['width'] == 128
    assert preview['preview_metadata']['width'] == 64
    assert preview['preview_metadata']['height'] == 32
    assert preview['frame_files'] == 4
    assert len(preview['outputs']) == 3
    assert any(row['path'].endswith('.html') for row in preview['outputs'])


def test_job_symlink_cannot_alias_another_job(job):
    from providers.lottie.api import lottie_author, lottie_validate

    authored = lottie_author(job.name, scene={'layers': []})
    alias = job.parent / 'aliased-job'
    alias.symlink_to(job, target_is_directory=True)
    result = lottie_validate(alias.name, authored['outputs'][0]['path'])
    assert not result['ok']
    assert 'symlink' in ' '.join(result['errors'])


def test_real_editor_dispatch_requires_owned_job_and_never_calls_network(job):
    import asyncio
    from unittest.mock import patch

    from agent.gateway_executor import GatewayExecutor
    from agent.studio_agent_next import StudioAgentRequest, _context_from_request

    studio = _context_from_request(StudioAgentRequest(prompt='Make a Lottie success check',
        workspace_id='workspace', project_id='project', conversation_id='conversation', job_id=job.name))
    executor = GatewayExecutor(studio, [])

    async def run():
        with patch('socket.create_connection', side_effect=AssertionError('network forbidden')):
            blocked = await executor.execute({'tool_name': 'Lottie___lottie_author', 'call_id': 'wrong',
                'arguments': {'job_id': 'another-job', 'scene': {'layers': []}}})
            assert blocked['status'] == 'not_run'
            assert not (job.parent / 'another-job').exists()
            result = await executor.execute({'tool_name': 'Lottie___lottie_author', 'call_id': 'author',
                'arguments': {'job_id': job.name, 'scene': {'layers': [
                    {'name': 'Status dot', 'shape': 'ellipse', 'fill': '#168B52'}]}}})
            assert result['ok'], result
            checked = await executor.execute({'tool_name': 'Lottie___lottie_validate', 'call_id': 'validate',
                'arguments': {'job_id': job.name, 'input_path': result['outputs'][0]['path']}})
            assert checked['ok'], checked
        assert not executor.reservations
        assert not any(event.status == 'awaiting_approval' for event in studio.tool_events)

    asyncio.run(run())


def test_editor_stages_owned_svg_handles_and_keeps_provenance(job):
    import asyncio
    from unittest.mock import patch

    from agent.gateway_executor import GatewayExecutor
    from agent.studio_agent_next import StudioAgentRequest, _context_from_request

    source = job.parent / 'managed.svg'
    source.write_text('<svg viewBox="0 0 64 64"><path d="M 8 32 L 24 48 L 56 12" '
                      'fill="none" stroke="#168B52" stroke-width="4"/></svg>')
    studio = _context_from_request(StudioAgentRequest(prompt='Animate this SVG as a Lottie check',
        workspace_id='workspace', project_id='project', conversation_id='conversation', job_id=job.name))

    def resolve(version):
        assert version == 'owned-vector'
        return str(source)

    studio.source_resolver = resolve
    executor = GatewayExecutor(studio, [])

    async def run():
        with patch('socket.create_connection', side_effect=AssertionError('network forbidden')):
            result = await executor.execute({'tool_name': 'Lottie___lottie_author', 'call_id': 'svg',
                'arguments': {'job_id': job.name, 'svg_path': 'renderhaus-asset://owned-vector'}})
        assert result['ok'], result
        event = next(event for event in studio.tool_events if event.id == 'svg')
        assert event.source_version_ids == ['owned-vector']
        assert Path(event.arguments['svg_path']).is_relative_to(job)
        assert Path(event.arguments['svg_path']).read_bytes() == source.read_bytes()

    asyncio.run(run())


def test_owned_staging_validates_request_before_resolving_or_writing(job):
    from unittest.mock import Mock
    from providers.lottie.api import stage_owned_inputs

    resolver = Mock(side_effect=AssertionError('resolver must not run'))
    with pytest.raises(ValueError, match='exactly one'):
        stage_owned_inputs('lottie_author', {'job_id': job.name,
            'svg_path': 'renderhaus-asset://owned', 'scene': {'layers': []}}, resolver)
    resolver.assert_not_called()
    assert not list(job.iterdir())
    with pytest.raises(ValueError, match='owned Studio asset resolver'):
        stage_owned_inputs('lottie_author', {'job_id': job.name,
            'svg_path': 'renderhaus-asset://owned'}, None)


def test_owned_staging_preserves_resolver_authorization(job):
    from providers.lottie.api import stage_owned_inputs

    def denied(version):
        raise ValueError('Asset version is not owned by this workspace.')

    with pytest.raises(ValueError, match='not owned'):
        stage_owned_inputs('lottie_author', {'job_id': job.name,
            'svg_path': 'renderhaus-asset://foreign'}, denied)
    assert not list(job.iterdir())


def test_missing_owned_asset_fails_soft_in_editor(job):
    import asyncio
    from unittest.mock import Mock

    from agent.gateway_executor import GatewayExecutor
    from agent.studio_agent_next import StudioAgentRequest, _context_from_request

    studio = _context_from_request(StudioAgentRequest(prompt='Animate this SVG as a Lottie check',
        workspace_id='workspace', project_id='project', conversation_id='conversation', job_id=job.name))
    studio.source_resolver = Mock(side_effect=KeyError('foreign-or-missing-version'))
    result = asyncio.run(GatewayExecutor(studio, []).execute({
        'tool_name': 'Lottie___lottie_author', 'call_id': 'missing-svg',
        'arguments': {'job_id': job.name, 'svg_path': 'renderhaus-asset://foreign-or-missing-version'},
    }))
    assert result['status'] == 'not_run'
    assert 'could not be staged' in result['reason']
    assert 'foreign-or-missing-version' not in result['reason']
    assert not list(job.iterdir())


@pytest.mark.parametrize('gate', ['request', 'policy', 'selection', 'discovery', 'schema', 'rejection'])
def test_editor_rejections_do_not_stage_owned_assets(job, gate):
    import asyncio
    from unittest.mock import Mock, patch

    from agent.gateway_executor import GatewayExecutor
    from agent.studio_agent_next import StudioAgentRequest, _context_from_request

    source = job.parent / 'managed.svg'
    source.write_text('<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="4"/></svg>')
    studio = _context_from_request(StudioAgentRequest(prompt='Animate this SVG as a Lottie check',
        workspace_id='workspace', project_id='project', conversation_id='conversation', job_id=job.name))
    studio.source_resolver = Mock(return_value=str(source))
    executor = GatewayExecutor(studio, [])
    arguments = {'job_id': job.name, 'svg_path': 'renderhaus-asset://owned'}
    if gate == 'schema':
        arguments['name'] = 123

    async def run():
        with patch('agent.gateway_executor.request_tool_blocker', return_value='blocked' if gate == 'request' else None), \
             patch('agent.gateway_executor.policy_blocker', return_value='blocked' if gate == 'policy' else None), \
             patch.object(executor, 'selection_blocker', return_value='blocked' if gate == 'selection' else None):
            if gate == 'discovery':
                with patch.object(executor, 'available', return_value={}):
                    return await executor.execute({'tool_name': 'Lottie___lottie_author', 'call_id': gate,
                                                   'arguments': arguments})
            return await executor.execute({'tool_name': 'Lottie___lottie_author', 'call_id': gate,
                                           'arguments': arguments},
                                          rejection='Declined' if gate == 'rejection' else None)

    result = asyncio.run(run())
    assert result['status'] in {'not_run', 'failed', 'rejected'}
    studio.source_resolver.assert_not_called()
    assert not list(job.iterdir())
