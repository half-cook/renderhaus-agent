from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from server.canvas.routes import router as canvas_router
from server.config import load_local_env
from server.db.session import get_engine, reset_engine_cache

# Loads .env.local for a local `pytest` run, same as server/app.py and
# alembic/env.py do — nothing here should hardcode a machine-specific
# connection string (an earlier draft hardcoded a local OS username and would
# have broken in CI's Postgres service, which uses a different one).
load_local_env()

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    raise RuntimeError(
        "TEST_DATABASE_URL is not set. Point it at a disposable database, never "
        "at DATABASE_URL's target — tests write rows. See .env.example."
    )

REQUIRED_R2_ENV = {
    "R2_ACCOUNT_ID": "test-account",
    "R2_ACCESS_KEY_ID": "test-key",
    "R2_SECRET_ACCESS_KEY": "test-secret",
    "R2_BUCKET": "test-bucket",
}


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch):
    """Every test starts from a clean slate: no leftover env vars, no cached engine.

    Without this, test order would matter — e.g. a passing health check would
    leave a cached engine that a later "DATABASE_URL unset" test never sees.
    """
    for name in ("DATABASE_URL", *REQUIRED_R2_ENV):
        monkeypatch.delenv(name, raising=False)
    reset_engine_cache()
    yield
    reset_engine_cache()


@pytest.fixture
def configured_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """DATABASE_URL + all four R2_* vars set, pointed at the test database."""
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    for name, value in REQUIRED_R2_ENV.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
async def canvas_client(configured_env: None):
    app = FastAPI()
    app.include_router(canvas_router)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def db_connection(configured_env: None):
    """A raw connection against the test database, auto-rolled-back on exit."""
    engine = get_engine()
    async with engine.connect() as conn:
        yield conn
    await engine.dispose()
