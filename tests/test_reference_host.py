from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock, patch

from agent.studio_agent_next import StudioAgentOutput


def test_reference_session_and_resume_stay_with_owned_studio_files(tmp_path):
    from server import studio as server
    from agent.gateway_executor import _local_reference_arguments

    media = tmp_path / 'media'
    source = tmp_path / 'reference.mp4'
    source.write_bytes(b'owned source bytes for staging')
    final = StudioAgentOutput(title='Analysis', summary='Visual review pending',
                              markdown='Measured report', filename='reference.md')

    async def local(request, *, studio):
        staged = _local_reference_arguments(studio, {
            'op': 'measure', 'job_id': 'owned-job', 'input_path': 'renderhaus-asset://version-1',
        })
        assert (media / 'owned-job' / staged['input_path']).read_bytes() == source.read_bytes()
        studio.session_items = [{'type': 'renderhaus_deepagents_session'}]
        studio.session_sink(studio.session_items)
        return final

    async def run():
        first = await server.run_studio_agent('Break this reference ad down shot by shot.',
            job_id='owned-job', source_resolver=lambda version: str(source),
            source_publisher=Mock(side_effect=AssertionError('Local references must not be published')))
        assert first.session_items[0]['execution_host'] == 'studio_reference'
        second = await server.run_studio_agent('Continue with the report.', job_id='owned-job',
            source_resolver=lambda version: str(source), session_items=first.session_items)
        assert second.final == final

    with patch.dict('os.environ', {'AGENTCORE_DEV_URL': 'https://runtime.example',
        'REFERENCE_SHOTS_DRY_RUN': 'false', 'RENDERHAUS_MEDIA_DIR': str(media)}), patch.object(
        server, 'run_studio_agent_runtime', side_effect=local,
    ), patch.object(server, '_invoke_agentcore_runtime', new_callable=AsyncMock,
                    side_effect=AssertionError('Reference execution cannot use the remote worker')):
        asyncio.run(run())


def test_other_requests_keep_the_configured_remote_runtime():
    from server import studio as server

    remote_result = object()
    with patch.dict('os.environ', {'AGENTCORE_DEV_URL': 'https://runtime.example'}), patch.object(
        server, '_invoke_agentcore_runtime', new_callable=AsyncMock, return_value=remote_result,
    ), patch.object(server, 'run_studio_agent_runtime', new_callable=AsyncMock,
                    side_effect=AssertionError('Unrelated remote requests stay remote')):
        assert asyncio.run(server.run_studio_agent('Generate a video.')) is remote_result
