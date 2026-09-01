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
import re
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx
from agents.exceptions import MaxTurnsExceeded
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from agent.studio_agent import StudioNodeReference
from agent.studio_agent_next import (
    MAX_AGENT_PROMPT_CHARS,
    StudioAgentApprovalRequired,
    StudioAgentContext,
    StudioAgentOutput,
    StudioAgentRequest,
    StudioApprovalDecision,
    StudioApprovalRequest,
    StudioNode,
    StudioProgressEvent,
    StudioToolEvent,
    run_studio_agent as run_studio_agent_runtime,
)
from providers.catalog import PROVIDERS, get_provider
from providers.registry import dispatch, load_committed_schemas
from server.assets import publish_provider_input_url
from server.auth import AuthUser, OptionalAuthUser, current_user_id, current_workspace_id
from server.billing_rates import cost_for
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
_RECENT_VIDEO_CONTEXT_PATTERN = re.compile(
    r"(?:\b(?:combine|merge|stitch|assemble|render|edit|join)\b.{0,80}"
    r"\b(?:videos?|clips?|shots?)\b)|"
    r"(?:\b(?:these|those|all|generated|previous|prior|existing)\b.{0,32}"
    r"\b(?:videos?|clips?|shots?)\b)",
    re.IGNORECASE,
)


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
        expected_signature = (
            base64.urlsafe_b64encode(
                hmac.new(_playback_secret(), encoded.encode("ascii"), hashlib.sha256).digest()
            )
            .rstrip(b"=")
            .decode("ascii")
        )
        if not hmac.compare_digest(provided_signature, expected_signature):
            return None
        padding = "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded + padding))
        if payload.get("version") != version_id or int(payload.get("expires_at", 0)) < int(
            time.time()
        ):
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
    """Resolve durable Studio handles to provider-reachable signed URLs."""
    if isinstance(value, dict):
        return {key: _resolve_asset_handles(item, workspace_id) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_asset_handles(item, workspace_id) for item in value]
    if isinstance(value, str) and value.startswith("renderhaus-asset://"):
        version_id = value.removeprefix("renderhaus-asset://")
        try:
            reference = repository.get_version(workspace_id, version_id)
            if reference is None:
                raise KeyError("Asset version not found")
            return publish_provider_input_url(
                source_path=repository.version_path(workspace_id, version_id),
                workspace_id=workspace_id,
                version_id=version_id,
                filename=reference.filename,
                mime_type=reference.mime_type,
            )
        except (KeyError, FileNotFoundError, ValueError) as exc:
            raise HTTPException(
                status_code=404, detail="Referenced asset version not found."
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
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


@router.get("/account")
async def studio_account(auth: AuthUser) -> dict[str, Any]:
    user_id = current_user_id(auth)
    balance = await asyncio.to_thread(repository.get_balance, user_id)
    ledger = await asyncio.to_thread(repository.list_ledger, user_id, limit=20)
    return {"balance_cents": balance, "recent_ledger": ledger}


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
        return await asyncio.to_thread(
            repository.get_canvas, current_workspace_id(auth), project_id
        )
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
            (
                item
                for item in load_committed_schemas(get_provider(provider))
                if item.get("name") == tool
            ),
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
    cost = cost_for(body.provider, body.tool, cleaned)
    balance = await asyncio.to_thread(repository.get_balance, user_id)
    if balance < cost.total_cents:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Not enough balance: this generation costs ${cost.total_cents / 100:.2f}, "
                f"you have ${balance / 100:.2f}."
            ),
        )
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
    # Charge only after the generation and asset registration both succeed.
    # Best-effort: the asset already exists and is being returned to the
    # user either way, so a billing hiccup here shouldn't turn into a
    # failed response for work that already happened.
    try:
        reference_id = assets[0]["version_id"] if assets else None
        await asyncio.to_thread(
            repository.adjust_balance,
            user_id,
            -cost.total_cents,
            "generation",
            reference_id=reference_id,
        )
    except Exception:  # noqa: BLE001 - never fail delivery over a billing edge case
        logger.exception(
            "Could not charge $%.2f to %s for %s.%s", cost.total_cents / 100, user_id, body.provider, body.tool
        )
    return {
        "provider": body.provider,
        "tool": body.tool,
        "result": result,
        "assets": assets,
        "cost": cost.public(),
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
    prompt: str = Field(min_length=1, max_length=MAX_AGENT_PROMPT_CHARS)
    project_id: str = Field(default="untitled", min_length=1, max_length=120)
    conversation_id: str | None = Field(default=None, max_length=120)
    node_ids: list[str] = Field(default_factory=list, max_length=16)
    nodes: list["AgentNodeBody"] = Field(default_factory=list, max_length=16)
    autonomous: bool = False


class AgentApprovalBody(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    message: str | None = Field(default=None, max_length=1_000)


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


class AgentConversationCreateBody(BaseModel):
    title: str = Field(default="New conversation", max_length=120)


class AgentConversationPatchBody(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    status: str | None = Field(default=None, pattern="^(active|archived)$")


@router.get("/projects/{project_id}/agent-conversations")
async def studio_agent_conversations(project_id: str, auth: AuthUser) -> dict[str, Any]:
    try:
        items = await asyncio.to_thread(
            repository.list_conversations,
            current_workspace_id(auth),
            project_id,
            current_user_id(auth),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found.") from exc
    return {"items": items}


@router.post("/projects/{project_id}/agent-conversations", status_code=201)
async def create_studio_agent_conversation(
    project_id: str,
    body: AgentConversationCreateBody,
    auth: AuthUser,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            repository.create_conversation,
            current_workspace_id(auth),
            project_id,
            current_user_id(auth),
            body.title,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Project not found.") from exc


@router.patch("/agent-conversations/{conversation_id}")
async def update_studio_agent_conversation(
    conversation_id: str,
    body: AgentConversationPatchBody,
    auth: AuthUser,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            repository.update_conversation,
            current_workspace_id(auth),
            conversation_id,
            title=body.title,
            status=body.status,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent conversation not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
        if (
            reference.version_id
            and repository.get_version(workspace_id, reference.version_id) is None
        ):
            raise HTTPException(status_code=404, detail="Referenced asset version not found.")
    known_ids = {node.id for node in references}
    references.extend(
        StudioNodeReference(id=node_id, title=node_id, kind="unknown")
        for node_id in body.node_ids
        if node_id not in known_ids
    )
    return references


def _recent_conversation_media_references(
    prompt: str,
    references: list[StudioNodeReference],
    *,
    workspace_id: str,
    conversation_id: str,
) -> list[StudioNodeReference]:
    """Recover the latest prior video set for deictic edit requests.

    Generated provider outputs are durable even when the customer did not place every
    artifact on the canvas. For requests such as "render these videos", attach the
    latest completed multi-clip set by version id so Remotion can consume local/S3
    media directly instead of polling old provider jobs and expiring URLs.
    """
    explicit_videos = [reference for reference in references if reference.kind == "video"]
    if len(explicit_videos) >= 2 or not _RECENT_VIDEO_CONTEXT_PATTERN.search(prompt):
        return references

    selected_versions = {reference.version_id for reference in references if reference.version_id}
    executions = repository.list_executions(
        workspace_id,
        conversation_id=conversation_id,
        limit=12,
    )
    for execution in executions:
        if execution.get("status") != "completed":
            continue
        calls = list(execution.get("tool_calls") or [])
        prompt_slots: dict[str, int] = {}
        jobs: dict[str, tuple[int, str]] = {}
        soundtrack_prompt = ""
        for call in calls:
            name = str(call.get("name") or "")
            arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
            result = call.get("result") if isinstance(call.get("result"), dict) else {}
            if name.endswith(("image_to_video", "text_to_video")):
                clip_prompt = " ".join(str(arguments.get("prompt") or "").split())[:4_000]
                prompt_key = clip_prompt.casefold()
                if prompt_key not in prompt_slots:
                    prompt_slots[prompt_key] = len(prompt_slots)
                job_id = str(result.get("job_id") or call.get("provider_job_id") or "")
                if job_id:
                    jobs[job_id] = (prompt_slots[prompt_key], clip_prompt)
            elif name.endswith(("create_instrumental", "text_to_music", "generate_soundtrack")):
                soundtrack_prompt = " ".join(
                    str(arguments.get("prompt") or arguments.get("description") or "").split()
                )[:4_000]

        video_by_slot: dict[int, StudioNodeReference] = {}
        audio_candidates: list[StudioNodeReference] = []
        fallback_slot = len(prompt_slots)
        for call in calls:
            arguments = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}
            result = call.get("result") if isinstance(call.get("result"), dict) else {}
            job_id = str(
                result.get("job_id") or arguments.get("job_id") or call.get("provider_job_id") or ""
            )
            for asset in call.get("assets") or []:
                if not isinstance(asset, dict):
                    continue
                version_id = str(asset.get("version_id") or "")
                asset_id = str(asset.get("asset_id") or "")
                kind = str(asset.get("kind") or "")
                if not version_id or not asset_id or version_id in selected_versions:
                    continue
                if kind == "video":
                    slot, clip_prompt = jobs.get(job_id, (fallback_slot, ""))
                    if job_id not in jobs:
                        fallback_slot += 1
                    video_by_slot[slot] = StudioNodeReference(
                        id=f"history-{version_id}",
                        title=f"Existing sequence clip {slot + 1}",
                        kind="video",
                        prompt=clip_prompt,
                        asset_id=asset_id,
                        version_id=version_id,
                    )
                elif kind == "audio":
                    audio_candidates.append(
                        StudioNodeReference(
                            id=f"history-{version_id}",
                            title="Existing sequence soundtrack",
                            kind="audio",
                            prompt=soundtrack_prompt,
                            asset_id=asset_id,
                            version_id=version_id,
                        )
                    )

        ordered_videos = [video_by_slot[slot] for slot in sorted(video_by_slot)]
        if len(ordered_videos) < 2:
            continue
        remaining = max(0, 16 - len(references))
        recovered = ordered_videos[:remaining]
        if audio_candidates and len(recovered) < remaining:
            recovered.append(audio_candidates[-1])
        return [*references, *recovered]
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


_MEDIA_CREATION_TOOLS = frozenset(
    {
        "text_to_image",
        "image_to_image",
        "text_to_video",
        "image_to_video",
        "render_timeline",
        "text_to_music",
        "create_instrumental",
        "create_song",
        "create_song_from_prompt",
        "extend_song",
        "region_edit_song",
        "remix_song",
        "stem_song",
        "vocal_clone",
        "generate_track",
        "generate_soundtrack",
        "generate_lyrics_video",
        "create_speech",
        "create_podcast",
    }
)
_FAILED_MEDIA_STATUSES = frozenset({"failed", "error", "cancelled", "canceled", "dry_run"})


def _media_generation_failed(outcome: Any, result: dict[str, Any]) -> bool:
    """Do not label an all-failed paid media attempt as a completed agent run."""
    if result.get("assets"):
        return False
    for event in getattr(outcome, "tool_events", []) or []:
        tool_name = str(getattr(event, "name", "") or "").rsplit("___", 1)[-1]
        status = str(getattr(event, "status", "") or "").lower()
        if tool_name in _MEDIA_CREATION_TOOLS and status in _FAILED_MEDIA_STATUSES:
            return True
    return False


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
    completed = [
        call
        for call in calls
        if str(call.get("status") or "").lower() in {"succeeded", "success", "completed"}
    ]
    markdown = "# Partial agent result\n\n"
    if completed:
        markdown += "Completed work:\n\n" + "\n".join(
            f"- {call.get('label')}: {call.get('summary')}" for call in completed
        )
    else:
        markdown += "No tool completed before the run stopped."
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
    def __init__(
        self,
        final: StudioAgentOutput,
        tool_events: list[Any],
        session_items: list[dict[str, Any]],
        progress_events: list[StudioProgressEvent] | None = None,
    ) -> None:
        self.final = final
        self.tool_events = tool_events
        self.session_items = session_items
        self.progress_events = list(progress_events or [])


def _agentcore_dev_url() -> str:
    return (os.getenv("AGENTCORE_DEV_URL") or "").strip().rstrip("/")


def _studio_agent_request(
    prompt: str,
    nodes: list[StudioNodeReference] | None,
    *,
    conversation_id: str | None = None,
    session_items: list[dict[str, Any]] | None = None,
    job_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    autonomous: bool = False,
    resume_state: str | None = None,
    approval_decisions: list[StudioApprovalDecision] | None = None,
    resume_tool_names: list[str] | None = None,
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
        conversation_id=conversation_id,
        session_items=list(session_items or []),
        job_id=job_id,
        workspace_id=workspace_id,
        project_id=project_id,
        autonomous=autonomous,
        resume_state=resume_state,
        approval_decisions=list(approval_decisions or []),
        resume_tool_names=list(resume_tool_names or []),
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
                arguments=(
                    dict(item.get("arguments") or {})
                    if isinstance(item.get("arguments"), dict)
                    else {}
                ),
                assets=list(item.get("assets") or []),
                result=dict(item.get("result") or {})
                if isinstance(item.get("result"), dict)
                else {},
            )
        )
    return events


def _progress_events_from_payload(raw: list[Any]) -> list[StudioProgressEvent]:
    events: list[StudioProgressEvent] = []
    for item in raw:
        if isinstance(item, StudioProgressEvent):
            events.append(item)
            continue
        if not isinstance(item, dict):
            continue
        events.append(
            StudioProgressEvent(
                id=str(item.get("id") or ""),
                type=str(item.get("type") or "STEP_STARTED"),
                title=str(item.get("title") or "Agent update"),
                message=str(item.get("message") or ""),
                status=str(item.get("status") or "running"),
                tool_call_id=(
                    item.get("tool_call_id") if isinstance(item.get("tool_call_id"), str) else None
                ),
                tool_call_name=(
                    item.get("tool_call_name")
                    if isinstance(item.get("tool_call_name"), str)
                    else None
                ),
                created_at=int(item.get("created_at") or time.time()),
            )
        )
    return events


async def _invoke_agentcore_runtime(
    url: str,
    request: StudioAgentRequest,
    progress_sink: Any = None,
) -> StudioAgentRun:
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
        async with client.stream(
            "POST",
            f"{url}/invocations",
            json=request.model_dump(),
            headers={"Accept": "text/event-stream"},
        ) as response:
            payload: Any = None
            if "text/event-stream" in response.headers.get("content-type", ""):
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        chunk = json.loads(line.removeprefix("data:").strip())
                    except json.JSONDecodeError:
                        continue
                    if isinstance(chunk, dict) and chunk.get("kind") == "progress":
                        events = _progress_events_from_payload([chunk.get("event")])
                        if progress_sink and events:
                            progress_sink(events[0])
                        continue
                    if isinstance(chunk, dict) and chunk.get("kind") == "result":
                        payload = chunk.get("payload")
                    elif isinstance(chunk, dict) and chunk.get("error"):
                        payload = {"status": "failed", **chunk}
            else:
                try:
                    payload = json.loads(await response.aread())
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise RuntimeError(
                        f"AgentCore runtime returned a non-JSON response ({response.status_code})."
                    ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("AgentCore runtime returned an unexpected payload.")
    if response.status_code >= 400 or payload.get("status") == "failed":
        raise RuntimeError(
            str(payload.get("error") or f"AgentCore invocation failed ({response.status_code}).")
        )
    if payload.get("status") == "awaiting_approval":
        approvals = [
            StudioApprovalRequest.model_validate(item) for item in payload.get("approvals") or []
        ]
        raise StudioAgentApprovalRequired(
            str(payload.get("run_state") or ""),
            approvals,
            list(payload.get("session_items") or []),
            _events_from_payload(payload.get("tool_events") or []),
        )
    output = StudioAgentOutput.model_validate(payload.get("result") or payload)
    return StudioAgentRun(
        final=output,
        tool_events=_events_from_payload(payload.get("tool_events") or []),
        session_items=list(payload.get("session_items") or []),
        progress_events=_progress_events_from_payload(payload.get("progress_events") or []),
    )


async def run_studio_agent(
    prompt: str,
    *,
    nodes: list[StudioNodeReference] | None = None,
    asset_registrar: Any = None,
    source_resolver: Any = None,
    source_publisher: Any = None,
    event_sink: Any = None,
    progress_sink: Any = None,
    job_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    conversation_id: str | None = None,
    session_items: list[dict[str, Any]] | None = None,
    autonomous: bool = False,
    resume_state: str | None = None,
    approval_decisions: list[StudioApprovalDecision] | None = None,
    resume_tool_names: list[str] | None = None,
    prior_tool_events: list[StudioToolEvent] | None = None,
    **_unused: Any,
) -> StudioAgentRun:
    request = _studio_agent_request(
        prompt,
        nodes,
        conversation_id=conversation_id,
        session_items=session_items,
        job_id=job_id,
        workspace_id=workspace_id,
        project_id=project_id,
        autonomous=autonomous,
        resume_state=resume_state,
        approval_decisions=approval_decisions,
        resume_tool_names=resume_tool_names,
    )
    runtime_url = _agentcore_dev_url()
    if runtime_url:
        if source_publisher:
            published_nodes: list[StudioNode] = []
            for node in request.nodes:
                published_source = node.source
                if node.version_id:
                    published_source = await asyncio.to_thread(source_publisher, node.version_id)
                published_nodes.append(node.model_copy(update={"source": published_source}))
            request = request.model_copy(update={"nodes": published_nodes})
        return await _invoke_agentcore_runtime(runtime_url, request, progress_sink)
    studio = StudioAgentContext(
        nodes=list(request.nodes),
        asset_registrar=asset_registrar,
        source_resolver=source_resolver,
        source_publisher=source_publisher,
        event_sink=event_sink,
        progress_sink=progress_sink,
        job_id=request.job_id,
        workspace_id=request.workspace_id,
        project_id=request.project_id,
        session_items=list(request.session_items),
        autonomous=request.autonomous,
    )
    studio.restore_events(list(prior_tool_events or []))
    output = await run_studio_agent_runtime(request, studio=studio)
    return StudioAgentRun(
        final=output,
        tool_events=list(studio.tool_events),
        session_items=list(studio.session_items),
        progress_events=list(studio.progress_events),
    )


async def _run_studio_agent_job(
    job_id: str,
    prompt: str,
    references: list[StudioNodeReference],
    conversation_id: str,
    *,
    workspace_id: str,
    project_id: str,
    user_id: str,
    autonomous: bool = False,
    resume_state: str | None = None,
    approval_decisions: list[StudioApprovalDecision] | None = None,
    prior_tool_events: list[StudioToolEvent] | None = None,
    resume_tool_names: list[str] | None = None,
) -> None:
    session_items = await asyncio.to_thread(
        repository.get_conversation_items, workspace_id, conversation_id
    )
    await asyncio.to_thread(
        repository.update_execution,
        workspace_id,
        job_id,
        status="running",
        message="Running.",
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

    published_inputs: dict[str, str] = {}

    def publish_source(version_id: str) -> str:
        cached = published_inputs.get(version_id)
        if cached:
            return cached
        reference = repository.get_version(workspace_id, version_id)
        if reference is None:
            raise ValueError(f"Referenced asset version {version_id!r} was not found.")
        url = publish_provider_input_url(
            source_path=repository.version_path(workspace_id, version_id),
            workspace_id=workspace_id,
            version_id=version_id,
            filename=reference.filename,
            mime_type=reference.mime_type,
        )
        published_inputs[version_id] = url
        return url

    def record_event(event: Any) -> None:
        payload = event.public()
        payload["result"] = event.result
        repository.append_tool_call(
            workspace_id=workspace_id,
            execution_id=job_id,
            event=payload,
        )

    def record_progress(event: Any) -> None:
        repository.append_agent_event(
            workspace_id=workspace_id,
            execution_id=job_id,
            event=event.public(),
        )
        if event.type not in {"RUN_FINISHED", "RUN_ERROR"} and event.message:
            repository.update_execution(
                workspace_id,
                job_id,
                status="running",
                message=event.message,
            )

    try:
        outcome = await run_studio_agent(
            prompt,
            nodes=references,
            conversation_id=conversation_id,
            session_items=session_items,
            asset_registrar=register_assets,
            source_resolver=resolve_source,
            source_publisher=publish_source,
            event_sink=record_event,
            progress_sink=record_progress,
            job_id=job_id,
            workspace_id=workspace_id,
            project_id=project_id,
            autonomous=autonomous,
            resume_state=resume_state,
            approval_decisions=approval_decisions,
            resume_tool_names=resume_tool_names,
            prior_tool_events=prior_tool_events,
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
        for event in getattr(outcome, "progress_events", []):
            record_progress(event)
        await asyncio.to_thread(
            repository.replace_conversation_items,
            workspace_id,
            conversation_id,
            getattr(outcome, "session_items", session_items),
        )
    except StudioAgentApprovalRequired as exc:
        if exc.tool_events:
            await asyncio.to_thread(
                _hydrate_tool_event_assets,
                exc.tool_events,
                workspace_id=workspace_id,
                project_id=project_id,
                user_id=user_id,
                execution_id=job_id,
            )
            for event in exc.tool_events:
                record_event(event)
        if exc.session_items:
            await asyncio.to_thread(
                repository.replace_conversation_items,
                workspace_id,
                conversation_id,
                exc.session_items,
            )
        await asyncio.to_thread(
            repository.pause_execution,
            workspace_id,
            job_id,
            run_state=exc.state,
            approvals=[approval.model_dump() for approval in exc.approvals],
        )
        return
    except asyncio.CancelledError:
        record_progress(
            StudioProgressEvent(
                id="run",
                type="RUN_ERROR",
                title="Agent interrupted",
                message="The agent job was interrupted before it finished.",
                status="failed",
            )
        )
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
        record_progress(
            StudioProgressEvent(
                id="run",
                type="RUN_FINISHED" if recovered_render else "RUN_ERROR",
                title="Recovered result" if recovered_render else "Agent stopped",
                message=(
                    "Recovered completed media after the manager reached its turn limit."
                    if recovered_render
                    else "The manager reached its turn limit."
                ),
                status="completed" if recovered_render else "failed",
            )
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
        record_progress(
            StudioProgressEvent(
                id="run",
                type="RUN_ERROR",
                title="Agent stopped",
                message=f"The agent could not finish ({type(exc).__name__}).",
                status="failed",
            )
        )
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

    result = _agent_result(outcome)
    if _media_generation_failed(outcome, result):
        message = "Media generation failed; no image, audio, video, or render was produced."
        record_progress(
            StudioProgressEvent(
                id="run",
                type="RUN_ERROR",
                title="Media generation failed",
                message=message,
                status="failed",
            )
        )
        await asyncio.to_thread(
            repository.update_execution,
            workspace_id,
            job_id,
            status="error",
            message=message,
            result=result,
            error_type="MediaGenerationFailed",
        )
        return

    record_progress(
        StudioProgressEvent(
            id="run",
            type="RUN_FINISHED",
            title="Agent finished",
            message=f"Completed {outcome.final.title}.",
            status="completed",
        )
    )
    await asyncio.to_thread(
        repository.update_execution,
        workspace_id,
        job_id,
        status="completed",
        message=f"Completed {outcome.final.title}.",
        result=result,
    )
    await asyncio.to_thread(repository.clear_execution_checkpoint, workspace_id, job_id)


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
    conversations = await asyncio.to_thread(
        repository.list_conversations, workspace_id, body.project_id, user_id
    )
    conversation = (
        await asyncio.to_thread(repository.get_conversation, workspace_id, body.conversation_id)
        if body.conversation_id
        else conversations[0]
    )
    if (
        conversation is None
        or conversation["project_id"] != body.project_id
        or conversation["status"] != "active"
    ):
        raise HTTPException(status_code=404, detail="Active agent conversation not found.")
    conversation_id = str(conversation["id"])
    references = await asyncio.to_thread(
        _recent_conversation_media_references,
        body.prompt,
        references,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
    )
    stored_request = _studio_agent_request(
        body.prompt,
        references,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        project_id=body.project_id,
        autonomous=body.autonomous,
    )
    try:
        job = await asyncio.to_thread(
            repository.create_execution,
            workspace_id=workspace_id,
            project_id=body.project_id,
            user_id=user_id,
            prompt=body.prompt,
            conversation_id=conversation_id,
            autonomous=body.autonomous,
            request=stored_request.model_dump(
                exclude={"session_items", "resume_state", "approval_decisions"}
            ),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent conversation not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    job_id = str(job["job_id"])
    task = asyncio.create_task(
        _run_studio_agent_job(
            job_id,
            body.prompt,
            references,
            conversation_id,
            workspace_id=workspace_id,
            project_id=body.project_id,
            user_id=user_id,
            autonomous=body.autonomous,
        ),
        name=f"studio-agent-{job_id}",
    )
    _AGENT_TASKS.add(task)
    task.add_done_callback(_AGENT_TASKS.discard)
    return job


@router.post("/agent/{job_id}/approvals/{call_id}")
async def decide_studio_agent_tool(
    job_id: str,
    call_id: str,
    body: AgentApprovalBody,
    auth: AuthUser,
) -> dict[str, Any]:
    workspace_id = current_workspace_id(auth)
    try:
        execution, ready = await asyncio.to_thread(
            repository.decide_execution_approval,
            workspace_id,
            job_id,
            call_id,
            decision=body.decision,
            message=body.message,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if not ready:
        return execution

    checkpoint = await asyncio.to_thread(repository.execution_checkpoint, workspace_id, job_id)
    if checkpoint is None or not checkpoint.get("run_state"):
        raise HTTPException(status_code=409, detail="The resumable agent checkpoint is missing.")
    request = StudioAgentRequest.model_validate(checkpoint.get("request") or {})
    decisions = [
        StudioApprovalDecision(
            call_id=str(item.get("call_id") or ""),
            decision=str(item.get("decision") or "reject"),
            message=item.get("message") if isinstance(item.get("message"), str) else None,
        )
        for item in checkpoint.get("approvals") or []
    ]
    references = [
        StudioNodeReference(
            id=node.id,
            title=node.title,
            kind=node.kind,
            prompt=node.prompt,
            source=node.source,
            asset_id=node.asset_id,
            version_id=node.version_id,
        )
        for node in request.nodes
    ]
    prior_tool_events = _events_from_payload(execution.get("tool_calls") or [])
    task = asyncio.create_task(
        _run_studio_agent_job(
            job_id,
            request.prompt,
            references,
            str(request.conversation_id or execution.get("conversation_id") or ""),
            workspace_id=workspace_id,
            project_id=str(request.project_id or execution.get("project_id") or "untitled"),
            user_id=current_user_id(auth),
            autonomous=bool(checkpoint.get("autonomous")),
            resume_state=str(checkpoint["run_state"]),
            approval_decisions=decisions,
            prior_tool_events=prior_tool_events,
            resume_tool_names=[
                str(item.get("tool_name") or "")
                for item in checkpoint.get("approvals") or []
                if item.get("tool_name")
            ],
        ),
        name=f"studio-agent-resume-{job_id}",
    )
    _AGENT_TASKS.add(task)
    task.add_done_callback(_AGENT_TASKS.discard)
    return execution


@router.get("/agent")
async def studio_agent_jobs(
    auth: AuthUser,
    limit: int = 50,
    project_id: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    items = await asyncio.to_thread(
        repository.list_executions,
        current_workspace_id(auth),
        limit=limit,
        project_id=project_id,
        conversation_id=conversation_id,
    )
    return {"items": items}


@router.get("/agent/{job_id}")
async def studio_agent_job(job_id: str, auth: AuthUser) -> dict[str, Any]:
    job = await asyncio.to_thread(repository.get_execution, current_workspace_id(auth), job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Agent job not found.")
    return job


@router.get("/agent/{job_id}/events")
async def studio_agent_job_events(
    job_id: str,
    request: Request,
    auth: AuthUser,
) -> StreamingResponse:
    """Stream persisted AG-UI-style snapshots for one workspace-owned run."""
    workspace_id = current_workspace_id(auth)
    initial = await asyncio.to_thread(repository.get_execution, workspace_id, job_id)
    if initial is None:
        raise HTTPException(status_code=404, detail="Agent job not found.")

    async def snapshots():
        previous = ""
        keepalive_at = time.monotonic()
        while True:
            if await request.is_disconnected():
                return
            job = await asyncio.to_thread(repository.get_execution, workspace_id, job_id)
            if job is None:
                return
            serialized = json.dumps(job, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if serialized != previous:
                previous = serialized
                yield f"event: snapshot\ndata: {serialized}\n\n"
                keepalive_at = time.monotonic()
            if job.get("status") in {"completed", "error", "failed", "awaiting_approval"}:
                return
            if time.monotonic() - keepalive_at >= 10:
                yield ": keep-alive\n\n"
                keepalive_at = time.monotonic()
            await asyncio.sleep(0.25)

    return StreamingResponse(
        snapshots(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/media")
async def studio_media(path: str, auth: AuthUser) -> FileResponse:
    resolved = _resolved_media_file(Path(path))
    if resolved is None:
        raise HTTPException(status_code=404, detail="Media file not found.")
    mime, _ = mimetypes.guess_type(resolved.name)
    return FileResponse(resolved, media_type=mime or "application/octet-stream")
