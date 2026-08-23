"""Async engine/session factory for the node canvas.

`DATABASE_URL` is read lazily (not at import time) so tests can set it per-process
and so the health check's "fail loudly when unset" behaviour (CLAUDE.md, Environment)
is a real runtime check rather than an import-time crash that's hard to attribute.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


class MissingEnvironmentError(RuntimeError):
    """A required environment variable is unset. Never silently fall back — see CLAUDE.md."""


def database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise MissingEnvironmentError("DATABASE_URL is not set")
    return url


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    return create_async_engine(database_url(), pool_pre_ping=True)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


def reset_engine_cache() -> None:
    """Test-only: drop the cached engine so a new DATABASE_URL takes effect."""
    get_engine.cache_clear()
