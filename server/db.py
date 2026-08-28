"""Postgres for studio: a transformation ledger with real idempotency.

One table, one file — see the plan at
/Users/bot/.claude/plans/jolly-sniffing-crane.md for why this exists and what
it deliberately doesn't do yet (no projects table, no auth, no storage
migration — those are later increments).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import Index, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, TIMESTAMP, UUID
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


tx_status_enum = ENUM("running", "succeeded", "failed", name="tx_status")


class Transformation(Base):
    __tablename__ = "transformations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    # text, not uuid: studio's default project id is the literal string
    # "untitled" until the user explicitly creates a project (studio/lib/canvas/store.ts) --
    # only node_id is guaranteed to be a real crypto.randomUUID().
    project_id: Mapped[str] = mapped_column(Text, nullable=False)
    node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    tool: Mapped[str] = mapped_column(Text, nullable=False)
    request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(tx_status_enum, nullable=False, server_default="running")
    provider_response: Mapped[dict | None] = mapped_column(JSONB)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[object] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[object | None] = mapped_column(TIMESTAMP(timezone=True))

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_transformations_idempotency_key"),
        # One active generation per node -- the actual double-click / double-charge
        # guard, enforced by the database. NULL-safe by construction: node_id is
        # not nullable here, unlike merge-doc.md's version.
        Index(
            "tx_one_active_per_node",
            "node_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )


class MissingEnvironmentError(RuntimeError):
    pass


def database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise MissingEnvironmentError("DATABASE_URL is not set")
    return url


def prepare_asyncpg_url(raw_url: str) -> tuple[str, dict]:
    """Translate libpq's `sslmode` query param into asyncpg's `ssl` connect arg.

    Neon (and most managed Postgres dashboards) hand out `?sslmode=require` --
    asyncpg has no `sslmode` kwarg and fails with an opaque TypeError if that
    reaches it unmodified. asyncpg accepts the same mode values directly via
    its own `ssl` kwarg, so translate rather than pass through.
    """
    url = make_url(raw_url)
    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    url = url.set(query=query)
    connect_args: dict = {}
    if sslmode and sslmode != "disable":
        connect_args["ssl"] = sslmode
    return url.render_as_string(hide_password=False), connect_args


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    url, connect_args = prepare_asyncpg_url(database_url())
    return create_async_engine(url, pool_pre_ping=True, connect_args=connect_args)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session
