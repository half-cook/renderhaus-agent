from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.auth import require_auth
from server.studio_state import StudioRepository


@pytest.fixture
def artifact_app(tmp_path):
    from server import studio

    media = tmp_path / 'media'
    job = media / 'reference-job'
    job.mkdir(parents=True)
    repo = StudioRepository(tmp_path / 'studio.sqlite3', media)
    repo.create_execution(workspace_id='user:owner', project_id=None, user_id='owner',
                          prompt='Break down this reference', execution_id='reference-job')
    app = FastAPI()
    app.include_router(studio.router)
    app.dependency_overrides[require_auth] = lambda: SimpleNamespace(payload={'sub': 'owner'})
    with patch.object(studio, 'repository', repo), patch.dict('os.environ', {'RENDERHAUS_MEDIA_DIR': str(media)}), TestClient(app) as client:
        yield client, repo, job, app


def record_file(repo, path):
    content = path.read_bytes()
    repo.append_tool_call(workspace_id='user:owner', execution_id='reference-job', event={
        'id': 'analysis', 'name': 'Reference___shot_breakdown', 'status': 'completed',
        'result': {'outputs': [{'path': str(path), 'sha256': hashlib.sha256(content).hexdigest()}]},
    })


def test_reference_download_is_owned_checksummed_and_private(artifact_app):
    client, repo, job, app = artifact_app
    path = job / 'shots.csv'
    path.write_bytes(b'shot_id,duration_seconds\n1,1.00\n')
    record_file(repo, path)
    url = '/api/studio/executions/reference-job/reference-artifacts/analysis/shots.csv'
    response = client.get(url)
    assert response.status_code == 200
    assert response.content == path.read_bytes()
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['content-disposition'] == 'attachment; filename="shots.csv"'
    path.write_bytes(b'changed')
    assert client.get(url).status_code == 404
    record_file(repo, path)
    app.dependency_overrides[require_auth] = lambda: SimpleNamespace(payload={'sub': 'stranger'})
    assert client.get(url).status_code == 404


def test_reference_download_refuses_foreign_paths_and_unrecorded_files(artifact_app, tmp_path):
    client, repo, job, _ = artifact_app
    foreign = tmp_path / 'private.json'
    foreign.write_text('{}')
    record_file(repo, foreign)
    assert client.get('/api/studio/executions/reference-job/reference-artifacts/analysis/private.json').status_code == 404
    (job / 'unrecorded.html').write_text('<html></html>')
    assert client.get('/api/studio/executions/reference-job/reference-artifacts/analysis/unrecorded.html').status_code == 404
