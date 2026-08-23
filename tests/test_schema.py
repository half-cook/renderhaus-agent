"""M1 acceptance: the migration in alembic/versions/*_canvas_foundation_schema.py
produces a database that actually enforces design/merge-doc.md §3 — not just a
schema that autogenerate happened to produce.

Every test runs against a real Postgres connection (`db_connection`, from
tests/conftest.py) whose transaction is rolled back automatically on exit, so
nothing here needs manual cleanup.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


async def _insert_project(conn) -> str:
    result = await conn.execute(
        text("insert into projects (owner_id, document) values ('u', '{}'::jsonb) returning id")
    )
    return str(result.scalar_one())


async def test_malformed_node_id_is_rejected_by_the_database(db_connection):
    project_id = await _insert_project(db_connection)
    with pytest.raises(DBAPIError, match="ck_transformations_node_id_format"):
        await db_connection.execute(
            text(
                "insert into transformations "
                "(project_id, user_id, node_id, operation, provider, model_id, request) "
                "values (:project_id, 'u', 'not-a-valid-node-id', 'text_to_image', "
                "'seedream', 'm', '{}'::jsonb)"
            ),
            {"project_id": project_id},
        )


async def test_one_active_generation_per_node_is_enforced_by_the_database(db_connection):
    project_id = await _insert_project(db_connection)
    insert = text(
        "insert into transformations "
        "(project_id, user_id, node_id, operation, provider, model_id, request, status) "
        "values (:project_id, 'u', 'node_abc123456789', 'text_to_image', 'seedream', 'm', "
        "'{}'::jsonb, 'queued')"
    )
    await db_connection.execute(insert, {"project_id": project_id})
    with pytest.raises(DBAPIError, match="tx_one_active_per_node"):
        await db_connection.execute(insert, {"project_id": project_id})


async def test_null_node_id_does_not_conflict_with_itself(db_connection):
    # The partial unique index is on node_id where status in ('queued','running').
    # NULL != NULL in SQL, so two NULL node_ids must NOT collide — this is what
    # lets a future non-canvas transformation type (if any) skip the guard.
    project_id = await _insert_project(db_connection)
    insert = text(
        "insert into transformations "
        "(project_id, user_id, node_id, operation, provider, model_id, request, status) "
        "values (:project_id, 'u', NULL, 'text_to_image', 'seedream', 'm', '{}'::jsonb, 'queued')"
    )
    await db_connection.execute(insert, {"project_id": project_id})
    await db_connection.execute(insert, {"project_id": project_id})  # must not raise


async def test_asset_type_enum_rejects_an_invalid_value(db_connection):
    project_id = await _insert_project(db_connection)
    with pytest.raises(DBAPIError):
        await db_connection.execute(
            text(
                "insert into assets (project_id, type, storage_key, content_type) "
                "values (:project_id, 'not_a_real_type', 'k', 'image/png')"
            ),
            {"project_id": project_id},
        )


async def test_system_flags_seeded_with_generation_enabled(db_connection):
    result = await db_connection.execute(
        text("select value from system_flags where key = 'generation'")
    )
    row = result.scalar_one()
    assert row == {"enabled": True}


async def test_transformations_cascade_deletes_with_project(db_connection):
    project_id = await _insert_project(db_connection)
    await db_connection.execute(
        text(
            "insert into transformations "
            "(project_id, user_id, node_id, operation, provider, model_id, request) "
            "values (:project_id, 'u', 'node_abc123456789', 'text_to_image', 'seedream', 'm', "
            "'{}'::jsonb)"
        ),
        {"project_id": project_id},
    )
    await db_connection.execute(text("delete from projects where id = :id"), {"id": project_id})
    result = await db_connection.execute(
        text("select count(*) from transformations where project_id = :id"), {"id": project_id}
    )
    assert result.scalar_one() == 0
