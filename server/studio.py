"""Local studio: list Gateway tools and invoke them without the agent."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx
from ag_ui.core import RunErrorEvent
from ag_ui.encoder import EventEncoder
from agents.exceptions import MaxTurnsExceeded
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from agent.studio_agent import StudioNodeReference
from agent.studio_agent_next import (
    StudioAgentContext,
    StudioAgentOutput,
    StudioAgentRequest,
    StudioNode,
    StudioToolEvent,
    run_studio_agent as run_studio_agent_runtime,
    stream_studio_agent,
)
from providers.catalog import PROVIDERS, get_provider
from providers.registry import dispatch, load_committed_schemas
from server.auth import AuthUser, OptionalAuthUser, current_user_id, current_workspace_id
from server.config import ROOT
from server.studio_state import CanvasConflictError, StudioAssetKind, repository
from server.studio_options import LIVE_CHOICE_TOOLS, extract_choice_ids, static_field_options


router = APIRouter(prefix="/api/studio", tags=["studio"])
logger = logging.getLogger(__name__)

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

_AGENT_TASKS: set[asyncio.Task[None]] = set()
_PLAYBACK_TICKET_SECRET = secrets.token_bytes(32)
_PLAYBACK_TICKET_TTL_SECONDS = 15 * 60


class InvokeBody(BaseModel):
    provider: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    project_id: str = Field(default="untitled", min_length=1, max_length=120)
    asset_id: str | None = Field(default=None, max_length=120)
    source_version_ids: list[str] = Field(default_factory=list, max_length=32)


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


def _playback_secret() -> bytes:
    """Use a dedicated secret when configured, with a safe local fallback."""
    value = os.getenv("STUDIO_MEDIA_TICKET_SECRET") or os.getenv("CLERK_SECRET_KEY")
    return value.encode("utf-8") if value else _PLAYBACK_TICKET_SECRET


def _encode_playback_ticket(*, workspace_id: str, version_id: str, expires_at: int) -> str:
    payload = json.dumps(
        {"workspace": workspace_id, "version": version_id, "expires_at": expires_at},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=")
    signature = hmac.new(_playback_secret(), encoded, hashlib.sha256).digest()
    return f"{encoded.decode('ascii')}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"


def _playback_ticket_workspace(ticket: str, version_id: str) -> str | None:
    try:
        encoded, provided_signature = ticket.split(".", 1)
        expected_signature = base64.urlsafe_b64encode(
            hmac.new(_playback_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
        ).rstrip(b"=").decode("ascii")
        if not hmac.compare_digest(provided_signature, expected_signature):
            return None
        padding = "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded + padding))
        if payload.get("version") != version_id or int(payload.get("expires_at", 0)) < int(time.time()):
            return None
        workspace_id = payload.get("workspace")
        return workspace_id if isinstance(workspace_id, str) and workspace_id else None
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def collect_asset_sources(payload: Any) -> list[dict[str, str]]:
    """Extract provider media locations before they are ingested into managed storage."""
    found: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(kind: str, source: str, filename: str | None = None) -> None:
        if source in seen:
            return
        seen.add(source)
        asset = {"kind": kind, "source": source}
        if filename:
            asset["filename"] = filename
        found.append(asset)

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, str) and value:
                    mapped = URL_KEYS.get(key)
                    if mapped and value.startswith(("http://", "https://", "data:")):
                        add(mapped, value)
                    elif key == "output_path":
                        kind = _kind_from_suffix(value)
                        resolved = _resolved_media_file(Path(value))
                        if resolved and kind:
                            add(kind, str(resolved), Path(value).name)
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
    local_kinds = {
        item["kind"]
        for item in found
        if not item["source"].startswith(("http://", "https://", "data:"))
    }
    return [
        item
        for item in found
        if item["kind"] not in local_kinds
        or not item["source"].startswith(("http://", "https://", "data:"))
    ]


def _register_payload_assets(
    *,
    payload: Any,
    workspace_id: str,
    project_id: str | None,
    user_id: str,
    kind: StudioAssetKind | None = None,
    asset_id: str | None = None,
    execution_id: str | None = None,
    tool_call_id: str | None = None,
    source_version_ids: list[str] | None = None,
    relation_type: str = "derived_from",
) -> list[dict[str, Any]]:
    registered: list[dict[str, Any]] = []
    for candidate in collect_asset_sources(payload):
        candidate_kind = candidate["kind"]
        if kind and candidate_kind != kind:
            continue
        reference = repository.register_source(
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
            source=candidate["source"],
            kind=kind or candidate_kind,  # type: ignore[arg-type]
            filename=candidate.get("filename"),
            asset_id=asset_id if not registered else None,
            execution_id=execution_id,
            tool_call_id=tool_call_id,
            source_version_ids=source_version_ids,
            relation_type=relation_type,
        )
        registered.append(reference.public())
    return registered


_SKIP_ASSET_STATUSES = frozenset({"failed", "error", "queued", "running", "dry_run"})
_KIND_URL_KEYS = {"image": "image_url", "video": "video_url", "audio": "audio_url"}


def _hydrate_tool_event_assets(
    events: list[Any],
    *,
    workspace_id: str,
    project_id: str,
    user_id: str,
    execution_id: str,
) -> None:
    seen_sources: set[str] = set()
    for event in events:
        existing = list(getattr(event, "assets", None) or [])
        if existing:
            continue
        status = str(getattr(event, "status", "") or "").lower()
        if status in _SKIP_ASSET_STATUSES:
            continue
        payload = getattr(event, "result", None)
        if not isinstance(payload, dict):
            continue
        registered: list[dict[str, Any]] = []
        for candidate in collect_asset_sources(payload):
            source = candidate["source"]
            if source in seen_sources:
                continue
            seen_sources.add(source)
            kind = candidate["kind"]
            stub = (
                {_KIND_URL_KEYS[kind]: source}
                if source.startswith(("http://", "https://", "data:")) and kind in _KIND_URL_KEYS
                else {"output_path": source}
            )
            try:
                registered.extend(
                    _register_payload_assets(
                        payload=stub,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        user_id=user_id,
                        kind=kind,  # type: ignore[arg-type]
                        execution_id=execution_id,
                        tool_call_id=getattr(event, "id", None) or None,
                    )
                )
            except Exception:
                logger.exception(
                    "Failed to ingest agent media from %s (%s)",
                    getattr(event, "name", "tool"),
                    source[:180],
                )
        event.assets = registered


def _resolve_asset_handles(value: Any, workspace_id: str) -> Any:
    """Resolve transient agent/provider handles at the execution boundary."""
    if isinstance(value, dict):
        return {key: _resolve_asset_handles(item, workspace_id) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_asset_handles(item, workspace_id) for item in value]
    if isinstance(value, str) and value.startswith("renderhaus-asset://"):
        version_id = value.removeprefix("renderhaus-asset://")
        try:
            return str(repository.version_path(workspace_id, version_id))
        except (KeyError, FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Referenced asset version not found.") from exc
    return value


@router.get("/status")
async def studio_status() -> dict[str, Any]:
    return {
        "mode": "local",
        "agent": bool(os.getenv("OPENAI_API_KEY")),
        "dry_run": {
            "seedance": os.getenv("SEEDANCE_DRY_RUN", "true").lower() != "false",
            "seedream": os.getenv("SEEDREAM_DRY_RUN", os.getenv("SEEDANCE_DRY_RUN", "true")).lower()
            != "false",
            "mureka": os.getenv("MUREKA_DRY_RUN", "true").lower() != "false",
            "fish_audio": os.getenv("FISH_AUDIO_DRY_RUN", "true").lower() != "false",
        },
    }


class StudioProjectBody(BaseModel):
    name: str = Field(default="Untitled", min_length=1, max_length=120)
    project_id: str | None = Field(default=None, min_length=1, max_length=120)


class StudioCanvasBody(BaseModel):
    document: dict[str, Any]
    base_revision: int | None = Field(default=None, ge=1)


def _legacy_source(asset: dict[str, Any]) -> str | None:
    value = asset.get("url") or asset.get("content_url")
    if not isinstance(value, str) or not value:
        return None
    if value.startswith("/api/studio/media"):
        paths = parse_qs(urlparse(value).query).get("path") or []
        if not paths:
            return None
        resolved = _resolved_media_file(Path(unquote(paths[0])))
        return str(resolved) if resolved else None
    if value.startswith(("http://", "https://", "data:")):
        return value
    return None


def _normalize_canvas_document(
    document: dict[str, Any],
    *,
    workspace_id: str,
    project_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Migrate legacy URL/path media references to immutable version IDs."""
    normalized = json.loads(json.dumps(document))
    normalized["schemaVersion"] = 2
    adopted: dict[str, dict[str, Any]] = {}

    def normalize_asset(value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        version_id = value.get("versionId") or value.get("version_id")
        if isinstance(version_id, str) and version_id:
            reference = repository.get_version(workspace_id, version_id)
            if reference is None:
                raise ValueError("Canvas references an asset version outside this workspace.")
            return reference.canvas()
        source = _legacy_source(value)
        if not source:
            return None
        if source in adopted:
            return adopted[source]
        raw_kind = value.get("kind")
        kind = raw_kind if raw_kind in {"image", "video", "audio"} else _kind_from_suffix(source)
        if kind is None:
            return None
        reference = repository.register_source(
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
            source=source,
            kind=kind,
            filename=value.get("filename") if isinstance(value.get("filename"), str) else None,
        )
        adopted[source] = reference.canvas()
        return adopted[source]

    for node in normalized.get("nodes") or []:
        if not isinstance(node, dict) or not isinstance(node.get("data"), dict):
            continue
        data = node["data"]
        output = normalize_asset(data.get("output"))
        data["output"] = output
        variants = [
            migrated
            for value in data.get("variants") or []
            if (migrated := normalize_asset(value)) is not None
        ]
        if output and not any(item["versionId"] == output["versionId"] for item in variants):
            variants.insert(0, output)
        data["variants"] = variants
        config = data.get("config")
        if isinstance(config, dict):
            config.pop("path", None)
        def normalize_agent_payload(payload: dict[str, Any]) -> None:
            payload["assets"] = [
                migrated
                for value in payload.get("assets") or []
                if (migrated := normalize_asset(value)) is not None
            ]
            payload["primaryAsset"] = normalize_asset(payload.get("primaryAsset"))
            for event in payload.get("toolEvents") or payload.get("tool_events") or []:
                if not isinstance(event, dict):
                    continue
                event["assets"] = [
                    migrated
                    for value in event.get("assets") or []
                    if (migrated := normalize_asset(value)) is not None
                ]

        agent_result = data.get("agentResult")
        if isinstance(agent_result, dict):
            normalize_agent_payload(agent_result)
        agent_run = data.get("agentRun")
        if isinstance(agent_run, dict):
            normalize_agent_payload(agent_run)
    return normalized


@router.get("/projects")
async def studio_projects(auth: AuthUser) -> dict[str, Any]:
    workspace_id = current_workspace_id(auth)
    user_id = current_user_id(auth)
    return {"items": await asyncio.to_thread(repository.list_projects, workspace_id, user_id)}


@router.post("/projects", status_code=201)
async def create_studio_project(body: StudioProjectBody, auth: AuthUser) -> dict[str, Any]:
    workspace_id = current_workspace_id(auth)
    user_id = current_user_id(auth)
    try:
        return await asyncio.to_thread(
            repository.create_project,
            workspace_id,
            user_id,
            body.name,
            project_id=body.project_id,
        )
    except Exception as exc:
        logger.exception("Could not create Studio project")
        raise HTTPException(status_code=409, detail="Could not create project.") from exc


@router.get("/projects/{project_id}/canvas")
async def studio_canvas(project_id: str, auth: AuthUser) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(repository.get_canvas, current_workspace_id(auth), project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found.") from exc


@router.put("/projects/{project_id}/canvas")
async def save_studio_canvas(
    project_id: str,
    body: StudioCanvasBody,
    auth: AuthUser,
) -> dict[str, Any]:
    workspace_id = current_workspace_id(auth)
    user_id = current_user_id(auth)
    try:
        document = await asyncio.to_thread(
            _normalize_canvas_document,
            body.document,
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
        )
        return await asyncio.to_thread(
            repository.save_canvas,
            workspace_id,
            project_id,
            user_id,
            document,
            expected_revision=body.base_revision,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CanvasConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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


@router.post("/invoke")
async def invoke_tool(body: InvokeBody, auth: AuthUser) -> dict[str, Any]:
    workspace_id = current_workspace_id(auth)
    user_id = current_user_id(auth)
    try:
        await asyncio.to_thread(repository.require_project, workspace_id, body.project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found.") from exc
    cleaned = _tool_arguments(body.provider, body.tool, body.arguments)
    cleaned = _resolve_asset_handles(cleaned, workspace_id)
    try:
        result = await asyncio.to_thread(dispatch, body.provider, body.tool, cleaned)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface provider errors in the node
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    try:
        assets = await asyncio.to_thread(
            _register_payload_assets,
            payload=result,
            workspace_id=workspace_id,
            project_id=body.project_id,
            user_id=user_id,
            asset_id=body.asset_id,
            source_version_ids=body.source_version_ids,
        )
    except Exception as exc:  # noqa: BLE001 - provider output must become durable or fail visibly
        logger.exception("Could not ingest provider output for %s.%s", body.provider, body.tool)
        raise HTTPException(status_code=502, detail="Provider output could not be saved.") from exc
    return {
        "provider": body.provider,
        "tool": body.tool,
        "result": result,
        "assets": assets,
    }


@router.post("/upload")
async def studio_upload(
    auth: AuthUser,
    file: UploadFile = File(...),
    project_id: str = "untitled",
) -> dict[str, Any]:
    workspace_id = current_workspace_id(auth)
    user_id = current_user_id(auth)
    try:
        await asyncio.to_thread(repository.require_project, workspace_id, project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found.") from exc
    filename = file.filename or "upload.bin"
    kind = _kind_from_suffix(filename)
    if kind is None:
        raise HTTPException(status_code=415, detail="Use an image, video, or audio file.")
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="The file was empty.")
    reference = await asyncio.to_thread(
        repository.register_bytes,
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=user_id,
        content=payload,
        filename=filename,
        kind=kind,
        mime_type=file.content_type,
    )
    return reference.public()


@router.post("/assets/{version_id}/playback")
async def studio_asset_playback(version_id: str, auth: AuthUser) -> dict[str, Any]:
    """Mint a short-lived, asset-scoped URL for native media elements.

    HTML image/video/audio elements cannot attach the Clerk bearer token used by
    Studio's JSON client. The ticket keeps media private without exposing that
    bearer token in a URL.
    """
    workspace_id = current_workspace_id(auth)
    reference = await asyncio.to_thread(repository.get_version, workspace_id, version_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="Asset version not found.")
    expires_at = int(time.time()) + _PLAYBACK_TICKET_TTL_SECONDS
    ticket = _encode_playback_ticket(
        workspace_id=workspace_id,
        version_id=version_id,
        expires_at=expires_at,
    )
    return {
        "url": f"/api/studio/assets/{quote(version_id)}/content?ticket={quote(ticket)}",
        "expires_at": expires_at,
    }


@router.get("/assets/{version_id}/content")
async def studio_asset_content(
    version_id: str,
    auth: OptionalAuthUser,
    ticket: str | None = None,
) -> FileResponse:
    workspace_id = _playback_ticket_workspace(ticket, version_id) if ticket else None
    if workspace_id is None:
        workspace_id = current_workspace_id(auth)
    reference = await asyncio.to_thread(repository.get_version, workspace_id, version_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="Asset version not found.")
    try:
        path = await asyncio.to_thread(repository.version_path, workspace_id, version_id)
    except (KeyError, FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Asset content not found.") from exc
    return FileResponse(
        path,
        media_type=reference.mime_type,
        filename=reference.filename,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=300"},
    )


class AgentBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=8_000)
    project_id: str = Field(default="untitled", min_length=1, max_length=120)
    node_ids: list[str] = Field(default_factory=list, max_length=16)
    nodes: list["AgentNodeBody"] = Field(default_factory=list, max_length=16)


class AgentNodeBody(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=160)
    kind: str = Field(min_length=1, max_length=40)
    prompt: str = Field(default="", max_length=4_000)
    asset_id: str | None = Field(default=None, max_length=120)
    version_id: str | None = Field(default=None, max_length=120)
    # Legacy migration fields. New clients send only asset/version IDs.
    output_url: str | None = Field(default=None, max_length=12_000)
    local_path: str | None = Field(default=None, max_length=4_000)


AgentBody.model_rebuild()


def _agent_node_source(node: AgentNodeBody) -> str | None:
    if node.local_path:
        resolved = _resolved_media_file(Path(node.local_path))
        if resolved is not None:
            return str(resolved)
    output_url = node.output_url or ""
    if output_url.startswith("/api/studio/media"):
        values = parse_qs(urlparse(output_url).query).get("path") or []
        if values:
            resolved = _resolved_media_file(Path(values[0]))
            if resolved is not None:
                return str(resolved)
        return None
    if output_url.startswith(("https://", "http://", "data:")):
        return output_url
    return None


def _agent_references(body: AgentBody, workspace_id: str) -> list[StudioNodeReference]:
    references = [
        StudioNodeReference(
            id=node.id,
            title=node.title,
            kind=node.kind,
            prompt=node.prompt,
            source=_agent_node_source(node),
            asset_id=node.asset_id,
            version_id=node.version_id,
        )
        for node in body.nodes
    ]
    for reference in references:
        if reference.version_id and repository.get_version(workspace_id, reference.version_id) is None:
            raise HTTPException(status_code=404, detail="Referenced asset version not found.")
    known_ids = {node.id for node in references}
    references.extend(
        StudioNodeReference(id=node_id, title=node_id, kind="unknown")
        for node_id in body.node_ids
        if node_id not in known_ids
    )
    return references


def _agent_result(outcome: Any) -> dict[str, Any]:
    assets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in outcome.tool_events:
        for asset in event.assets:
            version_id = str(asset.get("version_id") or "")
            if version_id and version_id not in seen:
                seen.add(version_id)
                assets.append(asset)

    final = outcome.final
    return {
        "title": final.title,
        "summary": final.summary,
        "markdown": final.markdown,
        "filename": final.filename,
        "mime_type": "text/markdown;charset=utf-8",
        "tool_events": [event.public() for event in outcome.tool_events],
        "assets": assets,
        # The primary result is the latest successfully registered media, whatever
        # its kind. A video gets no special preference: an image-only or audio-only
        # request should lead with that image or audio on the canvas.
        "primary_asset": assets[-1] if assets else None,
    }


def _partial_agent_result(execution: dict[str, Any]) -> dict[str, Any]:
    calls = execution.get("tool_calls") or []
    assets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for call in calls:
        for asset in call.get("assets") or []:
            version_id = str(asset.get("version_id") or "")
            if version_id and version_id not in seen:
                seen.add(version_id)
                assets.append(asset)
    primary = assets[-1] if assets else None
    completed = [call for call in calls if call.get("status") not in {"failed", "error"}]
    markdown = "# Partial agent result\n\n"
    if completed:
        markdown += "Completed work:\n\n" + "\n".join(
            f"- {call.get('label')}: {call.get('summary')}" for call in completed
        )
    else:
        markdown += "No media tool completed before the run stopped."
    return {
        "title": "Recovered agent result" if assets else "Partial agent result",
        "summary": (
            "Completed media was recovered even though the manager did not finish its final reply."
            if assets
            else "The manager stopped before producing a final artifact."
        ),
        "markdown": markdown,
        "filename": primary.get("filename") if primary else "partial-agent-result.md",
        "mime_type": primary.get("mime_type") if primary else "text/markdown;charset=utf-8",
        "tool_events": calls,
        "assets": assets,
        "primary_asset": primary,
        "partial": True,
    }


class StudioAgentRun:
    def __init__(self, final: StudioAgentOutput, tool_events: list[Any]) -> None:
        self.final = final
        self.tool_events = tool_events


def _agentcore_dev_url() -> str:
    return (os.getenv("AGENTCORE_DEV_URL") or "").strip().rstrip("/")


def _studio_agent_request(
    prompt: str,
    nodes: list[StudioNodeReference] | None,
    *,
    job_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
) -> StudioAgentRequest:
    return StudioAgentRequest(
        prompt=prompt,
        nodes=[
            StudioNode(
                id=node.id,
                title=node.title,
                kind=node.kind,
                prompt=node.prompt,
                source=node.source,
                asset_id=node.asset_id,
                version_id=node.version_id,
            )
            for node in (nodes or [])
        ],
        job_id=job_id,
        workspace_id=workspace_id,
        project_id=project_id,
    )


def _events_from_payload(raw: list[Any]) -> list[StudioToolEvent]:
    events: list[StudioToolEvent] = []
    for item in raw:
        if isinstance(item, StudioToolEvent):
            events.append(item)
            continue
        if not isinstance(item, dict):
            continue
        events.append(
            StudioToolEvent(
                id=str(item.get("id") or ""),
                name=str(item.get("name") or ""),
                label=str(item.get("label") or item.get("name") or "tool"),
                status=str(item.get("status") or "unknown"),
                summary=str(item.get("summary") or ""),
                provider=item.get("provider") if isinstance(item.get("provider"), str) else None,
                provider_job_id=(
                    item.get("provider_job_id")
                    if isinstance(item.get("provider_job_id"), str)
                    else None
                ),
                assets=list(item.get("assets") or []),
                result=dict(item.get("result") or {}) if isinstance(item.get("result"), dict) else {},
            )
        )
    return events


async def _invoke_agentcore_runtime(url: str, request: StudioAgentRequest) -> StudioAgentRun:
    timeout = float(os.getenv("TIME_OUT_SECONDS") or 300)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            ping = await client.get(f"{url}/ping")
        except httpx.RequestError as exc:
            raise RuntimeError(
                "Local AgentCore runtime is not running. Start it with: agentcore dev --logs --port 8080"
            ) from exc
        if ping.status_code >= 400:
            raise RuntimeError(f"AgentCore runtime ping failed ({ping.status_code}).")
        response = await client.post(f"{url}/invocations", json=request.model_dump())
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"AgentCore runtime returned a non-JSON response ({response.status_code})."
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("AgentCore runtime returned an unexpected payload.")
    if response.status_code >= 400 or payload.get("status") == "failed":
        raise RuntimeError(
            str(payload.get("error") or f"AgentCore invocation failed ({response.status_code}).")
        )
    output = StudioAgentOutput.model_validate(payload.get("result") or payload)
    return StudioAgentRun(final=output, tool_events=_events_from_payload(payload.get("tool_events") or []))


async def run_studio_agent(
    prompt: str,
    *,
    nodes: list[StudioNodeReference] | None = None,
    asset_registrar: Any = None,
    source_resolver: Any = None,
    event_sink: Any = None,
    job_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    **_unused: Any,
) -> StudioAgentRun:
    request = _studio_agent_request(
        prompt,
        nodes,
        job_id=job_id,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    runtime_url = _agentcore_dev_url()
    if runtime_url:
        return await _invoke_agentcore_runtime(runtime_url, request)
    studio = StudioAgentContext(
        nodes=list(request.nodes),
        asset_registrar=asset_registrar,
        source_resolver=source_resolver,
        event_sink=event_sink,
        job_id=request.job_id,
        workspace_id=request.workspace_id,
        project_id=request.project_id,
    )
    output = await run_studio_agent_runtime(request, studio=studio)
    return StudioAgentRun(final=output, tool_events=list(studio.tool_events))


async def _run_studio_agent_job(
    job_id: str,
    prompt: str,
    references: list[StudioNodeReference],
    *,
    workspace_id: str,
    project_id: str,
    user_id: str,
) -> None:
    await asyncio.to_thread(
        repository.update_execution,
        workspace_id,
        job_id,
        status="running",
        message="Choosing tools and building the result.",
    )

    def register_assets(**kwargs: Any) -> list[dict[str, Any]]:
        return _register_payload_assets(
            payload=kwargs["result"],
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
            kind=kwargs.get("kind"),
            asset_id=kwargs.get("asset_id"),
            execution_id=job_id,
            tool_call_id=kwargs.get("tool_call_id"),
            source_version_ids=kwargs.get("source_version_ids") or [],
            relation_type=(
                "composed_from"
                if kwargs.get("label") == "Remotion video render"
                else "derived_from"
            ),
        )

    def resolve_source(version_id: str) -> str:
        return str(repository.version_path(workspace_id, version_id))

    def record_event(event: Any) -> None:
        payload = event.public()
        payload["result"] = event.result
        repository.append_tool_call(
            workspace_id=workspace_id,
            execution_id=job_id,
            event=payload,
        )

    try:
        outcome = await run_studio_agent(
            prompt,
            nodes=references,
            asset_registrar=register_assets,
            source_resolver=resolve_source,
            event_sink=record_event,
            job_id=job_id,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        await asyncio.to_thread(
            _hydrate_tool_event_assets,
            outcome.tool_events,
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
            execution_id=job_id,
        )
        for event in outcome.tool_events:
            record_event(event)
    except asyncio.CancelledError:
        execution = await asyncio.to_thread(repository.get_execution, workspace_id, job_id)
        await asyncio.to_thread(
            repository.update_execution,
            workspace_id,
            job_id,
            status="error",
            message="The agent job was interrupted before it finished.",
            result=_partial_agent_result(execution or {}),
            error_type="CancelledError",
        )
        raise
    except MaxTurnsExceeded as exc:
        logger.exception("Studio agent job %s reached its turn limit", job_id)
        execution = await asyncio.to_thread(repository.get_execution, workspace_id, job_id) or {}
        partial = _partial_agent_result(execution)
        recovered_render = any(
            call.get("name") == "render_remotion_video"
            and call.get("status") in {"succeeded", "success", "completed"}
            and call.get("assets")
            for call in execution.get("tool_calls") or []
        )
        await asyncio.to_thread(
            repository.update_execution,
            workspace_id,
            job_id,
            status="completed" if recovered_render else "error",
            message=(
                "Recovered the completed render after the manager reached its turn limit."
                if recovered_render
                else "The manager reached its turn limit; completed tool outputs were preserved."
            ),
            result=partial,
            error_type=type(exc).__name__,
        )
        return
    except Exception as exc:  # noqa: BLE001 - the full failure belongs in server logs
        logger.exception("Studio agent job %s failed", job_id)
        execution = await asyncio.to_thread(repository.get_execution, workspace_id, job_id) or {}
        await asyncio.to_thread(
            repository.update_execution,
            workspace_id,
            job_id,
            status="error",
            message=(
                f"The OpenAI agent could not finish this request ({type(exc).__name__}); "
                "completed tool outputs were preserved."
            ),
            result=_partial_agent_result(execution),
            error_type=type(exc).__name__,
        )
        return

    await asyncio.to_thread(
        repository.update_execution,
        workspace_id,
        job_id,
        status="completed",
        message=f"Added {outcome.final.title} to the canvas.",
        result=_agent_result(outcome),
    )


@router.post("/agent", status_code=202)
async def studio_agent(body: AgentBody, auth: AuthUser) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="The OpenAI agent is not configured.")
    workspace_id = current_workspace_id(auth)
    user_id = current_user_id(auth)
    try:
        await asyncio.to_thread(repository.require_project, workspace_id, body.project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found.") from exc
    references = await asyncio.to_thread(_agent_references, body, workspace_id)
    job = await asyncio.to_thread(
        repository.create_execution,
        workspace_id=workspace_id,
        project_id=body.project_id,
        user_id=user_id,
        prompt=body.prompt,
    )
    job_id = str(job["job_id"])
    task = asyncio.create_task(
        _run_studio_agent_job(
            job_id,
            body.prompt,
            references,
            workspace_id=workspace_id,
            project_id=body.project_id,
            user_id=user_id,
        ),
        name=f"studio-agent-{job_id}",
    )
    _AGENT_TASKS.add(task)
    task.add_done_callback(_AGENT_TASKS.discard)
    return job


@router.post("/agent/stream")
async def studio_agent_stream(body: AgentBody, auth: AuthUser) -> StreamingResponse:
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="The OpenAI agent is not configured.")
    if _agentcore_dev_url():
        raise HTTPException(
            status_code=501,
            detail="Live streaming is unavailable for the configured AgentCore runtime; use job polling.",
        )
    workspace_id = current_workspace_id(auth)
    user_id = current_user_id(auth)
    try:
        await asyncio.to_thread(repository.require_project, workspace_id, body.project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found.") from exc
    references = await asyncio.to_thread(_agent_references, body, workspace_id)
    job = await asyncio.to_thread(
        repository.create_execution,
        workspace_id=workspace_id,
        project_id=body.project_id,
        user_id=user_id,
        prompt=body.prompt,
    )
    job_id = str(job["job_id"])

    def register_assets(**kwargs: Any) -> list[dict[str, Any]]:
        return _register_payload_assets(
            payload=kwargs["result"],
            workspace_id=workspace_id,
            project_id=body.project_id,
            user_id=user_id,
            kind=kwargs.get("kind"),
            asset_id=kwargs.get("asset_id"),
            execution_id=job_id,
            tool_call_id=kwargs.get("tool_call_id"),
            source_version_ids=kwargs.get("source_version_ids") or [],
            relation_type=(
                "composed_from"
                if kwargs.get("label") == "Remotion video render"
                else "derived_from"
            ),
        )

    def resolve_source(version_id: str) -> str:
        return str(repository.version_path(workspace_id, version_id))

    loop = asyncio.get_running_loop()
    sink_tasks: set[asyncio.Task[None]] = set()
    sink_tail: asyncio.Task[None] | None = None

    def persist_event(event: Any) -> None:
        _hydrate_tool_event_assets(
            [event],
            workspace_id=workspace_id,
            project_id=body.project_id,
            user_id=user_id,
            execution_id=job_id,
        )
        payload = event.public() if hasattr(event, "public") else dict(event)
        if hasattr(event, "result"):
            payload["result"] = event.result
        repository.append_tool_call(
            workspace_id=workspace_id,
            execution_id=job_id,
            event=payload,
        )

    def record_event(event: Any) -> None:
        nonlocal sink_tail
        previous = sink_tail

        async def persist_in_order() -> None:
            if previous is not None:
                await previous
            await asyncio.to_thread(persist_event, event)

        task = loop.create_task(persist_in_order(), name=f"studio-tool-event-{job_id}")
        sink_tail = task
        sink_tasks.add(task)

        def finish_sink_task(completed: asyncio.Task[None]) -> None:
            sink_tasks.discard(completed)
            if completed.cancelled():
                return
            error = completed.exception()
            if error is not None:
                logger.error(
                    "Failed to persist a streamed tool event for job %s",
                    job_id,
                    exc_info=(type(error), error, error.__traceback__),
                )

        task.add_done_callback(finish_sink_task)

    async def flush_event_sink() -> None:
        pending = sink_tail
        if pending is not None:
            await pending

    request = _studio_agent_request(
        body.prompt,
        references,
        job_id=job_id,
        workspace_id=workspace_id,
        project_id=body.project_id,
    )

    async def event_generator():
        encoder = EventEncoder()
        await asyncio.to_thread(
            repository.update_execution,
            workspace_id,
            job_id,
            status="running",
            message="Agent started execution.",
        )
        try:
            async for event in stream_studio_agent(
                request,
                asset_registrar=register_assets,
                source_resolver=resolve_source,
                event_sink=record_event,
            ):
                if event.type == "STATE_SNAPSHOT":
                    await flush_event_sink()
                    snapshot = getattr(event, "snapshot", {})
                    persisted = await asyncio.to_thread(
                        repository.get_execution,
                        workspace_id,
                        job_id,
                    )
                    tool_events_raw = (
                        (persisted or {}).get("tool_calls")
                        or snapshot.get("tool_events")
                        or []
                    )
                    assets_list: list[dict[str, Any]] = []
                    seen: set[str] = set()
                    for te in tool_events_raw:
                        te_assets = te.assets if hasattr(te, "assets") else te.get("assets", [])
                        for ast in te_assets:
                            vid = str(ast.get("version_id") or "")
                            if vid and vid not in seen:
                                seen.add(vid)
                                assets_list.append(ast)
                    if not assets_list and snapshot.get("assets"):
                        for ast in snapshot["assets"]:
                            vid = str(ast.get("version_id") or "")
                            if vid and vid not in seen:
                                seen.add(vid)
                                assets_list.append(ast)

                    snapshot["assets"] = assets_list
                    snapshot["primary_asset"] = assets_list[-1] if assets_list else None
                    snapshot["tool_events"] = [
                        te.public() if hasattr(te, "public") else te for te in tool_events_raw
                    ]

                    await asyncio.to_thread(
                        repository.update_execution,
                        workspace_id,
                        job_id,
                        status="completed",
                        message=f"Added {snapshot.get('title', 'result')} to the canvas.",
                        result={
                            "title": snapshot.get("title", "Agent result"),
                            "summary": snapshot.get("summary", ""),
                            "markdown": snapshot.get("markdown", ""),
                            "filename": snapshot.get("filename", "agent-result.md"),
                            "tool_events": snapshot.get("tool_events", []),
                            "assets": snapshot.get("assets", []),
                            "primary_asset": snapshot.get("primary_asset"),
                        },
                    )
                elif event.type == "RUN_ERROR":
                    await flush_event_sink()
                    err_msg = getattr(event, "message", "The agent could not finish this request.")
                    await asyncio.to_thread(
                        repository.update_execution,
                        workspace_id,
                        job_id,
                        status="error",
                        message=err_msg,
                    )
                yield encoder.encode(event)
        except Exception as exc:
            logger.exception("Error during studio agent stream for job %s", job_id)
            err_event = RunErrorEvent(message=str(exc)[:400], code="STREAM_ERROR")
            await asyncio.to_thread(
                repository.update_execution,
                workspace_id,
                job_id,
                status="error",
                message=str(exc)[:400],
            )
            yield encoder.encode(err_event)
        finally:
            execution = await asyncio.to_thread(repository.get_execution, workspace_id, job_id)
            if execution and execution.get("status") in {"queued", "running"}:
                await asyncio.to_thread(
                    repository.update_execution,
                    workspace_id,
                    job_id,
                    status="error",
                    message="The client disconnected before the agent finished.",
                    error_type="StreamDisconnected",
                )
            if sink_tasks:
                await asyncio.gather(*list(sink_tasks), return_exceptions=True)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/agent")
async def studio_agent_jobs(auth: AuthUser, limit: int = 50) -> dict[str, Any]:
    items = await asyncio.to_thread(
        repository.list_executions,
        current_workspace_id(auth),
        limit=limit,
    )
    return {"items": items}


@router.get("/agent/{job_id}")
async def studio_agent_job(job_id: str, auth: AuthUser) -> dict[str, Any]:
    job = await asyncio.to_thread(repository.get_execution, current_workspace_id(auth), job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Agent job not found.")
    return job


@router.get("/media")
async def studio_media(path: str, auth: AuthUser) -> FileResponse:
    resolved = _resolved_media_file(Path(path))
    if resolved is None:
        raise HTTPException(status_code=404, detail="Media file not found.")
    mime, _ = mimetypes.guess_type(resolved.name)
    return FileResponse(resolved, media_type=mime or "application/octet-stream")
