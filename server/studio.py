"""Local studio: list Gateway tools and invoke them without the agent."""

from __future__ import annotations

import asyncio
import mimetypes
import os
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from providers.catalog import PROVIDERS, get_provider
from providers.registry import dispatch, load_committed_schemas
from server.config import ROOT
from server.db import Transformation, get_session
from server.studio_options import LIVE_CHOICE_TOOLS, extract_choice_ids, static_field_options


router = APIRouter(prefix="/api/studio", tags=["studio"])

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".m4v"}
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".ogg", ".flac"}
URL_KEYS = {
    "image_url": "image",
    "video_url": "video",
    "audio_url": "audio",
    "mp3_url": "audio",
    "wav_url": "audio",
}


class InvokeBody(BaseModel):
    provider: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    # All three optional: poll calls (pollTool, e.g. get_video_task) hit this
    # same endpoint but must NOT go through the ledger below -- they'd either
    # collide with the submit call's idempotency key (returning the cached
    # submit response forever, never actually checking status) or need a
    # fresh key of their own, which would defeat the one-active-per-node
    # guard. Only submit calls set idempotency_key; poll calls send none.
    project_id: str | None = Field(default=None, min_length=1)
    node_id: uuid.UUID | None = None
    idempotency_key: str | None = Field(default=None, min_length=1)


def media_root() -> Path:
    raw = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser()
    path = raw if raw.is_absolute() else ROOT / raw
    return path.resolve()


def _kind_from_suffix(value: str) -> str | None:
    suffix = Path(value.split("?", 1)[0]).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    return None


def _resolved_media_file(path: Path) -> Path | None:
    root = media_root()
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return None
    if root not in resolved.parents and resolved != root:
        return None
    if not resolved.is_file() or resolved.stat().st_size == 0:
        return None
    return resolved


def _local_media_url(path: Path) -> str | None:
    resolved = _resolved_media_file(path)
    if resolved is None:
        return None
    return f"/api/studio/media?path={quote(str(resolved))}"


def collect_assets(payload: Any) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(kind: str, url: str) -> None:
        if url in seen:
            return
        seen.add(url)
        found.append({"kind": kind, "url": url})

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, str) and value:
                    mapped = URL_KEYS.get(key)
                    if mapped and value.startswith(("http://", "https://", "data:")):
                        add(mapped, value)
                    elif key == "output_path":
                        local = _local_media_url(Path(value))
                        kind = _kind_from_suffix(value)
                        if local and kind:
                            add(kind, local)
                    elif key == "url":
                        kind = _kind_from_suffix(value)
                        if kind and value.startswith(("http://", "https://", "data:")):
                            add(kind, value)
                elif isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(payload)
    preferred: dict[str, dict[str, str]] = {}
    for asset in found:
        current = preferred.get(asset["kind"])
        local = asset["url"].startswith("/api/studio/media")
        if current is None or (local and not current["url"].startswith("/api/studio/media")):
            preferred[asset["kind"]] = asset
    return list(preferred.values())


@router.get("/status")
async def studio_status() -> dict[str, Any]:
    return {
        "mode": "local",
        "agent": False,
        "dry_run": {
            "seedance": os.getenv("SEEDANCE_DRY_RUN", "true").lower() != "false",
            "seedream": os.getenv("SEEDREAM_DRY_RUN", os.getenv("SEEDANCE_DRY_RUN", "true")).lower()
            != "false",
            "mureka": os.getenv("MUREKA_DRY_RUN", "true").lower() != "false",
            "fish_audio": os.getenv("FISH_AUDIO_DRY_RUN", "true").lower() != "false",
        },
    }


@router.get("/options")
async def studio_options() -> dict[str, Any]:
    options = static_field_options()

    async def enrich(provider_id: str, tool_name: str, field: str) -> None:
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(dispatch, provider_id, tool_name, {}),
                timeout=3,
            )
        except Exception:  # noqa: BLE001 - live catalogs are optional for the form
            return
        ids = extract_choice_ids(result)
        if ids:
            previous = [str(value) for value in options[provider_id].get(field, [])]
            merged = list(ids)
            for value in previous:
                if value not in merged:
                    merged.append(value)
            options[provider_id][field] = merged

    try:
        await asyncio.wait_for(
            asyncio.gather(
                *[
                    enrich(provider_id, tool_name, field)
                    for provider_id, tool_name, field in LIVE_CHOICE_TOOLS
                ]
            ),
            timeout=3.5,
        )
    except TimeoutError:
        pass
    return {"providers": options}


@router.get("/tools")
async def list_tools() -> dict[str, Any]:
    providers = []
    for spec in PROVIDERS:
        tools = load_committed_schemas(spec)
        providers.append(
            {
                "id": spec.id,
                "name": spec.target_name,
                "function_name": spec.function_name,
                "tools": tools,
            }
        )
    return {"providers": providers}


def _tool_arguments(provider: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    cleaned = {key: value for key, value in arguments.items() if value not in (None, "")}
    try:
        schema = next(
            (item for item in load_committed_schemas(get_provider(provider)) if item.get("name") == tool),
            None,
        )
    except Exception:  # noqa: BLE001 - fall back to the raw payload
        return cleaned
    allowed = set(((schema or {}).get("inputSchema") or {}).get("properties") or {})
    if not allowed:
        return cleaned
    return {key: value for key, value in cleaned.items() if key in allowed}


async def _dispatch_and_respond(body: InvokeBody, cleaned: dict[str, Any]) -> dict[str, Any]:
    try:
        result = await asyncio.to_thread(dispatch, body.provider, body.tool, cleaned)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface provider errors in the node
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "provider": body.provider,
        "tool": body.tool,
        "result": result,
        "assets": collect_assets(result),
    }


@router.post("/invoke")
async def invoke_tool(
    body: InvokeBody, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    cleaned = _tool_arguments(body.provider, body.tool, body.arguments)

    if body.idempotency_key is None:
        # Poll call (or any caller not opting into the ledger) -- unchanged
        # passthrough behaviour, exactly what ran before this endpoint had a
        # ledger at all.
        return await _dispatch_and_respond(body, cleaned)

    if body.project_id is None or body.node_id is None:
        raise HTTPException(
            status_code=400, detail="project_id and node_id are required with idempotency_key"
        )

    # Claim the slot. ON CONFLICT (idempotency_key) makes a resend of the same
    # click a no-op instead of a second billed call; the separate
    # tx_one_active_per_node partial unique index (not targeted by this ON
    # CONFLICT, so it still raises) is what stops a *different* click firing a
    # second generation on a node that already has one in flight.
    stmt = (
        pg_insert(Transformation)
        .values(
            project_id=body.project_id,
            node_id=body.node_id,
            provider=body.provider,
            tool=body.tool,
            request={"provider": body.provider, "tool": body.tool, "arguments": cleaned},
            idempotency_key=body.idempotency_key,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(Transformation)
    )
    try:
        tx = (await session.execute(stmt)).scalar_one_or_none()
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if "tx_one_active_per_node" in str(exc.orig):
            raise HTTPException(status_code=409, detail="node_already_generating") from exc
        raise

    if tx is None:
        # Idempotent replay: same key seen before. Return the cached result
        # rather than dispatching again.
        cached = (
            await session.execute(
                select(Transformation).where(
                    Transformation.idempotency_key == body.idempotency_key
                )
            )
        ).scalar_one()
        return {
            "provider": cached.provider,
            "tool": cached.tool,
            "result": cached.provider_response,
            "assets": collect_assets(cached.provider_response),
        }

    try:
        response = await _dispatch_and_respond(body, cleaned)
    except HTTPException as exc:
        await session.execute(
            update(Transformation)
            .where(Transformation.id == tx.id)
            .values(status="failed", provider_response={"error": exc.detail}, completed_at=func.now())
        )
        await session.commit()
        raise

    # "succeeded" here means the dispatch call itself succeeded -- for async
    # providers (video/music) the underlying job may still be rendering.
    # Tracking that to completion is a later increment; what this table
    # guarantees today is that the SUBMIT step is idempotent and audited.
    await session.execute(
        update(Transformation)
        .where(Transformation.id == tx.id)
        .values(status="succeeded", provider_response=response["result"], completed_at=func.now())
    )
    await session.commit()
    return response


@router.post("/upload")
async def studio_upload(file: UploadFile = File(...)) -> dict[str, str]:
    filename = file.filename or "upload.bin"
    kind = _kind_from_suffix(filename)
    if kind is None:
        raise HTTPException(status_code=415, detail="Use an image, video, or audio file.")
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="The file was empty.")
    folder = media_root() / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    stored = folder / f"{uuid.uuid4().hex}{Path(filename).suffix.lower()}"
    stored.write_bytes(payload)
    url = _local_media_url(stored)
    if url is None:
        raise HTTPException(status_code=500, detail="Could not store the upload.")
    return {"kind": kind, "url": url, "path": str(stored), "filename": filename}


class AgentBody(BaseModel):
    prompt: str = Field(min_length=1)
    node_ids: list[str] = Field(default_factory=list)


@router.post("/agent")
async def studio_agent(_body: AgentBody) -> dict[str, Any]:
    raise HTTPException(
        status_code=501,
        detail="The agent is not connected yet. Add nodes from the rail to build the graph.",
    )


@router.get("/media")
async def studio_media(path: str) -> FileResponse:
    resolved = _resolved_media_file(Path(path))
    if resolved is None:
        raise HTTPException(status_code=404, detail="Media file not found.")
    mime, _ = mimetypes.guess_type(resolved.name)
    return FileResponse(resolved, media_type=mime or "application/octet-stream")
