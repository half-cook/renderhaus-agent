"""Canvas API routes — mounted under /v1 (see CLAUDE.md "Where things live").

Only /v1/health lands in M1. Everything else (projects, assets,
transformations) is M3+ per design/merge-doc.md §12.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from server.db.session import MissingEnvironmentError, database_url, get_engine

router = APIRouter(prefix="/v1", tags=["canvas"])

# CLAUDE.md "Environment": the health check must fail loudly if any of these
# is unset, rather than falling back silently to something that looks like an
# application bug later.
REQUIRED_R2_VARS = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")


def _missing_r2_vars() -> list[str]:
    return [name for name in REQUIRED_R2_VARS if not os.getenv(name)]


@router.get("/health")
async def health() -> dict[str, str]:
    try:
        database_url()
    except MissingEnvironmentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    missing_r2 = _missing_r2_vars()
    if missing_r2:
        raise HTTPException(
            status_code=503,
            detail=f"missing required environment variable(s): {', '.join(missing_r2)}",
        )

    engine = get_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
    except Exception as exc:  # noqa: BLE001 - surface the real DB error, not a generic 500
        raise HTTPException(status_code=503, detail=f"database unreachable: {exc}") from exc

    return {"status": "ok"}
