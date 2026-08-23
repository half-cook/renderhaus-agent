"""M1 acceptance: /v1/health does a real SELECT 1 and fails loudly on missing config.

See CLAUDE.md "Environment": "Silent fallbacks here produce failures that look
like application bugs."
"""

from __future__ import annotations

import pytest

from tests.conftest import TEST_DATABASE_URL


async def test_health_ok_when_fully_configured(canvas_client):
    response = await canvas_client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_fails_loudly_without_database_url(monkeypatch, canvas_client):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    response = await canvas_client.get("/v1/health")
    assert response.status_code == 503
    assert "DATABASE_URL" in response.json()["detail"]


@pytest.mark.parametrize(
    "missing_var", ["R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"]
)
async def test_health_fails_loudly_without_each_r2_var(missing_var, monkeypatch, canvas_client):
    monkeypatch.delenv(missing_var, raising=False)
    response = await canvas_client.get("/v1/health")
    assert response.status_code == 503
    assert missing_var in response.json()["detail"]


async def test_health_fails_loudly_when_database_unreachable(monkeypatch, canvas_client):
    # Same host, a port nothing is listening on — a real "can't connect", not a
    # config-shaped error, so it must surface as 503 with the underlying cause,
    # not a generic 500.
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://bot@localhost:1/nonexistent")
    from server.db.session import reset_engine_cache

    reset_engine_cache()
    response = await canvas_client.get("/v1/health")
    assert response.status_code == 503
    assert "database unreachable" in response.json()["detail"]


def test_test_database_url_is_not_the_dev_database():
    # Guards against a copy-paste mistake pointing tests at renderhaus_canvas
    # (the dev DB) instead of renderhaus_canvas_test.
    assert TEST_DATABASE_URL.endswith("/renderhaus_canvas_test")
