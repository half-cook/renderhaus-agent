from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent.config import ROOT, load_local_env
from agent.service import (
    poll_music_generation,
    poll_video_generation,
    start_image_generation,
    start_music_generation,
    start_video_generation,
)
from agent.tracing import flush_langfuse, traced_operation
from agent.agentcore_client import agentcore_enabled
from web.assets import (
    get_asset,
    get_asset_for_user,
    init_assets_db,
    iter_asset_bytes,
    materialize_asset_path,
    presigned_content_url,
    register_existing_s3_object,
    register_output_file,
    register_upload,
    sign_content_url,
    verify_content_signature,
)
from web.auth import AuthUser, clerk_enabled, current_user_id, optional_user, publishable_key
from web.projects import (
    ProjectStore,
    add_artifact,
    merge_video_paths,
    probe_media_duration,
    public_project,
    remove_artifact,
    set_timeline_items,
    timeline_items_by_kind,
)


load_local_env()

STATIC_DIR = Path(__file__).with_name("static")
STATE_DIR = ROOT / ".renderhaus" / "web-jobs"
MEDIA_DIR = (ROOT / os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).resolve()
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MIN_VIDEO_SECONDS = 4
MAX_VIDEO_SECONDS = 12
TERMINAL_STATES = {"complete", "planned", "failed"}
PROVIDER_TERMINAL_STATES = {
    "succeeded",
    "failed",
    "cancelled",
    "canceled",
    "deleted",
    "timeouted",
    "timeout",
}
PUBLIC_JOB_FIELDS = {
    "id",
    "schema_version",
    "status",
    "phase",
    "media_type",
    "prompt",
    "vibe",
    "aspect_ratio",
    "duration_seconds",
    "reference_asset_id",
    "output_asset_id",
    "parent_id",
    "project_id",
    "created_at",
    "updated_at",
    "message",
    "media_url",
    "error",
    "traces",
    "progress",
}


class GenerationRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)
    media_type: Literal["video", "image", "music"] = "video"
    vibe: str = Field(default="quiet luxury", max_length=120)
    aspect_ratio: str = Field(default="16:9", pattern=r"^(16:9|9:16|1:1)$")
    duration_seconds: int = Field(default=10, ge=MIN_VIDEO_SECONDS, le=MAX_VIDEO_SECONDS)
    reference_asset_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    project_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class RefinementRequest(BaseModel):
    instruction: str = Field(min_length=3, max_length=2000)


class ProjectCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class ProjectUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class ProjectArtifactRequest(BaseModel):
    job_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class TimelineItemModel(BaseModel):
    id: str | None = None
    job_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    asset_id: str | None = None
    media_type: Literal["video", "image", "music"] = "video"
    label: str = Field(default="", max_length=120)
    duration_seconds: float | int | None = None


class TimelineUpdateRequest(BaseModel):
    items: list[TimelineItemModel] = Field(default_factory=list)


class JobStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def load(self) -> list[str]:
        self.directory.mkdir(parents=True, exist_ok=True)
        resumable: list[str] = []
        for path in self.directory.glob("*.json"):
            try:
                job = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(job, dict) or not isinstance(job.get("id"), str):
                continue
            job.setdefault("media_type", "video")
            job.setdefault("traces", [])
            job.setdefault("progress", 0)
            job.setdefault("user_id", "local")
            job.setdefault("output_asset_id", None)
            job.setdefault("project_id", None)
            if job.get("status") not in TERMINAL_STATES:
                if job.get("_provider_job_id") and job.get("media_type") in {
                    "video",
                    "music",
                }:
                    job.update(status="generating", phase="rendering")
                    resumable.append(job["id"])
                else:
                    job.update(
                        status="failed",
                        phase="failed",
                        error={
                            "code": "server_restarted",
                            "message": "The local server stopped before this render was submitted.",
                            "retryable": True,
                        },
                    )
            self._jobs[job["id"]] = job
        return resumable

    async def create(
        self,
        request: GenerationRequest,
        *,
        user_id: str,
        reference_path: str | None = None,
        reference_storage_key: str | None = None,
        parent_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        now = int(time.time())
        job = {
            "id": uuid.uuid4().hex,
            "schema_version": 2,
            "status": "queued",
            "phase": "queued",
            "media_type": request.media_type,
            "prompt": request.prompt,
            "vibe": request.vibe,
            "aspect_ratio": request.aspect_ratio,
            "duration_seconds": request.duration_seconds if request.media_type == "video" else None,
            "reference_asset_id": request.reference_asset_id,
            "output_asset_id": None,
            "user_id": user_id,
            "parent_id": parent_id,
            "project_id": project_id or request.project_id,
            "created_at": now,
            "updated_at": now,
            "message": (
                "Reading the idea and finding its musical direction."
                if request.media_type == "music"
                else "Reading the idea and finding its visual rhythm."
            ),
            "media_url": None,
            "error": None,
            "traces": [],
            "progress": 4,
            "_reference_path": reference_path,
            "_reference_storage_key": reference_storage_key,
            "_provider_job_id": None,
            "_output_path": None,
            "_error_detail": None,
        }
        await self.put(job)
        return job

    async def put(self, job: dict[str, Any]) -> None:
        async with self._lock:
            job["updated_at"] = int(time.time())
            self._jobs[job["id"]] = job
            self.directory.mkdir(parents=True, exist_ok=True)
            target = self.directory / f"{job['id']}.json"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(job, indent=2, sort_keys=True))
            temporary.replace(target)

    async def get(self, job_id: str) -> dict[str, Any] | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    async def recent_for_user(
        self,
        user_id: str,
        limit: int = 20,
        *,
        project_id: str | None = None,
        unassigned: bool = False,
    ) -> list[dict[str, Any]]:
        async with self._lock:
            jobs = []
            for job in self._jobs.values():
                if job.get("user_id") != user_id:
                    continue
                job_project = job.get("project_id")
                if project_id is not None and job_project != project_id:
                    continue
                if unassigned and job_project:
                    continue
                jobs.append(job)
            jobs.sort(key=lambda item: item.get("created_at", 0), reverse=True)
            return [dict(job) for job in jobs[:limit]]


store = JobStore(STATE_DIR)
projects = ProjectStore()
generation_slots = asyncio.Semaphore(2)


def _ensure_output_asset(job: dict[str, Any]) -> bool:
    """Register a legacy `_output_path` as an owned asset. Returns True if job mutated."""
    asset_id = job.get("output_asset_id")
    if isinstance(asset_id, str) and asset_id:
        return False
    output_path = job.get("_output_path")
    if not isinstance(output_path, str) or not output_path:
        return False
    try:
        _attach_output_asset(job, output_path)
    except (OSError, ValueError, FileNotFoundError):
        return False
    job["schema_version"] = max(int(job.get("schema_version") or 1), 2)
    return True


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    public = {key: job.get(key) for key in PUBLIC_JOB_FIELDS}
    asset_id = job.get("output_asset_id")
    if isinstance(asset_id, str) and asset_id:
        public["media_url"] = sign_content_url(asset_id)
        public["output_asset_id"] = asset_id
    else:
        public["media_url"] = None
        public["output_asset_id"] = None
    return public


async def _public_job_persisted(job: dict[str, Any]) -> dict[str, Any]:
    if _ensure_output_asset(job):
        await store.put(job)
    return _public_job(job)


def _require_owned_job(job: dict[str, Any] | None, user_id: str) -> dict[str, Any]:
    if not job or job.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Generation not found.")
    return job


def _require_owned_project(project: dict[str, Any] | None, user_id: str) -> dict[str, Any]:
    if not project or project.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


def _reference_asset_for_user(asset_id: str | None, user_id: str):
    if not asset_id:
        return None
    asset = get_asset_for_user(asset_id, user_id)
    if not asset or asset.kind != "upload":
        raise HTTPException(status_code=400, detail="Reference image no longer exists.")
    return asset


def _reference_path_for_user(asset_id: str | None, user_id: str) -> str | None:
    asset = _reference_asset_for_user(asset_id, user_id)
    if asset is None:
        return None
    try:
        path = materialize_asset_path(asset)
    except Exception:
        raise HTTPException(status_code=400, detail="Reference image no longer exists.")
    if not path.is_file():
        raise HTTPException(status_code=400, detail="Reference image no longer exists.")
    return str(path)


def _detect_image(content: bytes) -> tuple[str, str] | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return None


def _append_trace(
    job: dict[str, Any],
    *,
    title: str,
    detail: str = "",
    status: str = "done",
    kind: str = "status",
    trace_id: str | None = None,
) -> None:
    traces = list(job.get("traces") or [])
    entry_id = trace_id or f"{kind}-{uuid.uuid4().hex[:8]}"
    for index, existing in enumerate(traces):
        if existing.get("id") == entry_id:
            updated = dict(existing)
            updated.update(
                {
                    "title": title,
                    "detail": detail,
                    "status": status,
                    "kind": kind,
                    "at": int(time.time()),
                }
            )
            traces[index] = updated
            job["traces"] = traces
            return
    traces.append(
        {
            "id": entry_id,
            "kind": kind,
            "title": title,
            "detail": detail,
            "status": status,
            "at": int(time.time()),
        }
    )
    job["traces"] = traces


def _merge_agent_traces(job: dict[str, Any], result: dict[str, Any]) -> None:
    for trace in result.get("traces") or []:
        if not isinstance(trace, dict):
            continue
        _append_trace(
            job,
            title=str(trace.get("title") or "tool"),
            detail=str(trace.get("detail") or ""),
            status=str(trace.get("status") or "done"),
            kind=str(trace.get("kind") or "tool"),
            trace_id=str(trace.get("id") or f"tool-{uuid.uuid4().hex[:8]}"),
        )


def _agent_session_id(job: dict[str, Any]) -> str:
    return str(job.get("parent_id") or job.get("id") or uuid.uuid4().hex)


def _generation_kwargs(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": _agent_session_id(job),
        "user_id": str(job.get("user_id") or "local"),
        "reference_storage_key": (
            job.get("_reference_storage_key")
            if isinstance(job.get("_reference_storage_key"), str)
            else None
        ),
    }


def _generation_instruction(job: dict[str, Any]) -> str:
    reference = job.get("_reference_path")
    # When AgentCore owns MCP tools, the runtime materializes the S3 reference itself.
    if agentcore_enabled():
        reference_instruction = (
            "A reference image will be supplied by the runtime. "
            if job.get("_reference_storage_key")
            else "No reference image is supplied. "
        )
    else:
        reference_instruction = (
            f"Use this local reference image: {reference}. "
            if reference
            else "No reference image is supplied. "
        )
    media_type = job.get("media_type") or "video"
    if media_type == "image":
        return (
            f"Creative prompt: {job['prompt']}\n"
            f"Vibe: {job['vibe']}. Aspect ratio: {job['aspect_ratio']}. "
            f"{reference_instruction}"
            "Start exactly one image generation and return."
        )
    if media_type == "music":
        return (
            f"Creative prompt: {job['prompt']}\n"
            f"Vibe: {job['vibe']}. "
            "Generate an instrumental score unless the prompt explicitly includes lyrics. "
            "Start exactly one music generation and return."
        )
    return (
        f"Creative prompt: {job['prompt']}\n"
        f"Vibe: {job['vibe']}. Aspect ratio: {job['aspect_ratio']}. "
        f"Duration: {job['duration_seconds']} seconds. {reference_instruction}"
        "Generate native sound when supported. Start exactly one video generation and return."
    )


def _artifact_path(value: dict[str, Any]) -> str | None:
    output_path = value.get("output_path")
    if not isinstance(output_path, str):
        return None
    try:
        resolved = Path(output_path).expanduser().resolve()
        resolved.relative_to(MEDIA_DIR)
    except (OSError, ValueError):
        return None
    if resolved.is_file() and resolved.stat().st_size > 0:
        return str(resolved)
    return None


def _remote_storage(value: dict[str, Any]) -> dict[str, Any] | None:
    storage_key = value.get("storage_key")
    if not isinstance(storage_key, str) or not storage_key:
        return None
    mime_type = value.get("mime_type")
    size_bytes = value.get("size_bytes")
    checksum = value.get("checksum")
    filename = value.get("filename")
    if not isinstance(mime_type, str) or not isinstance(filename, str):
        return None
    if not isinstance(size_bytes, int) or not isinstance(checksum, str):
        return None
    asset_id = value.get("asset_id")
    return {
        "storage_key": storage_key,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
        "checksum": checksum,
        "filename": filename,
        "asset_id": asset_id if isinstance(asset_id, str) else None,
    }


def _start_artifact(result: dict[str, Any]) -> dict[str, Any] | None:
    for artifact in reversed(result.get("artifacts", [])):
        if isinstance(artifact, dict) and (
            isinstance(artifact.get("job_id"), str)
            or isinstance(artifact.get("output_path"), str)
            or isinstance(artifact.get("storage_key"), str)
        ):
            return artifact
    return None


def _media_kind(job: dict[str, Any]) -> Literal["video", "image", "music"]:
    media_type = job.get("media_type") or "video"
    if media_type == "image":
        return "image"
    if media_type == "music":
        return "music"
    return "video"


def _attach_output_asset(job: dict[str, Any], output_path: str) -> None:
    kind = _media_kind(job)
    user_id = str(job.get("user_id") or "local")
    asset = register_output_file(
        user_id=user_id,
        source_path=output_path,
        kind=kind,
    )
    # Keep the provider's local path for debugging; canonical bytes live in S3.
    job["_output_path"] = str(Path(output_path).expanduser().resolve())
    job["output_asset_id"] = asset.id
    job["_storage_key"] = asset.storage_key


def _attach_remote_output_asset(job: dict[str, Any], remote: dict[str, Any]) -> None:
    kind = _media_kind(job)
    user_id = str(job.get("user_id") or "local")
    asset = register_existing_s3_object(
        user_id=user_id,
        storage_key=str(remote["storage_key"]),
        kind=kind,
        mime_type=str(remote["mime_type"]),
        size_bytes=int(remote["size_bytes"]),
        checksum=str(remote["checksum"]),
        filename=str(remote["filename"]),
        asset_id=remote.get("asset_id"),
    )
    job["output_asset_id"] = asset.id
    job["_storage_key"] = asset.storage_key


def _attach_generation_output(job: dict[str, Any], payload: dict[str, Any]) -> None:
    remote = _remote_storage(payload)
    if remote:
        _attach_remote_output_asset(job, remote)
        return
    output_path = _artifact_path(payload)
    if not output_path:
        raise RuntimeError("Generation succeeded without a downloadable media file.")
    _attach_output_asset(job, output_path)


async def _poll_provider(job: dict[str, Any]) -> None:
    media_type = job.get("media_type") or "video"
    provider_job_id = job.get("_provider_job_id")
    if not isinstance(provider_job_id, str):
        raise RuntimeError(f"{media_type.capitalize()} generation did not return a job identifier.")

    poll_title = "Polling Mureka task" if media_type == "music" else "Polling Seedance task"
    ready_title = "Music ready" if media_type == "music" else "Video ready"
    ready_detail = (
        "Downloaded the finished track."
        if media_type == "music"
        else "Downloaded the finished MP4."
    )
    ready_message = "Your score is ready." if media_type == "music" else "Your film is ready."
    running_message = (
        "Composing melody, arrangement, and mix."
        if media_type == "music"
        else "Shaping the shots, motion, and sound."
    )
    poll_fn = poll_music_generation if media_type == "music" else poll_video_generation
    trace_id = "poll-music" if media_type == "music" else "poll-video"
    poll_kwargs = {
        "session_id": _agent_session_id(job),
        "user_id": str(job.get("user_id") or "local"),
    }

    poll_count = 0
    while True:
        result = await poll_fn(provider_job_id, **poll_kwargs)
        status = str(result.get("status", "unknown")).lower()
        poll_count += 1
        _append_trace(
            job,
            title=poll_title,
            detail=f"Provider status: {status}",
            status="running" if status not in PROVIDER_TERMINAL_STATES else "done",
            kind="tool",
            trace_id=trace_id,
        )
        if status == "succeeded":
            _attach_generation_output(job, result)
            job.update(
                status="complete",
                phase="complete",
                message=ready_message,
                progress=100,
            )
            _append_trace(
                job,
                title=ready_title,
                detail=ready_detail,
                status="done",
                kind="status",
                trace_id="complete",
            )
            return
        if status in PROVIDER_TERMINAL_STATES:
            raise RuntimeError(f"{media_type.capitalize()} generation ended with status {status}.")
        job.update(
            status="generating",
            phase="rendering",
            message=running_message,
            progress=min(92, 35 + poll_count * 4),
        )
        await store.put(job)
        await asyncio.sleep(5)


async def _run_generation(job_id: str, *, resume: bool = False) -> None:
    async with generation_slots:
        job = await store.get(job_id)
        if not job:
            return
        media_type = job.get("media_type") or "video"
        session_id = job.get("parent_id") or job_id
        if media_type == "image":
            feature = "image-generation"
        elif media_type == "music":
            feature = "music-generation"
        else:
            feature = "video-generation"
        with traced_operation(
            feature,
            as_type="agent",
            input={
                "prompt": job.get("prompt"),
                "vibe": job.get("vibe"),
                "aspect_ratio": job.get("aspect_ratio"),
                "duration_seconds": job.get("duration_seconds"),
                "media_type": media_type,
                "resume": resume,
            },
            session_id=session_id,
            tags=["renderhaus", "web", feature],
            metadata={
                "feature": feature,
                "job_id": job_id,
                "parent_id": job.get("parent_id") or "",
                "media_type": media_type,
                "user_id": job.get("user_id") or "",
            },
            trace_name=feature,
        ) as observation:
            try:
                if not resume:
                    planning_message = (
                        "Finding the musical direction."
                        if media_type == "music"
                        else "Finding the visual direction."
                    )
                    job.update(
                        status="planning",
                        phase="planning",
                        message=planning_message,
                        progress=12,
                    )
                    _append_trace(
                        job,
                        title="Planning",
                        detail="Reading the prompt and choosing a generation path.",
                        status="running",
                        kind="status",
                        trace_id="planning",
                    )
                    await store.put(job)

                    agent_kwargs = _generation_kwargs(job)
                    instruction = _generation_instruction(job)
                    if media_type == "image":
                        result = await start_image_generation(instruction, **agent_kwargs)
                    elif media_type == "music":
                        result = await start_music_generation(
                            instruction,
                            session_id=agent_kwargs["session_id"],
                            user_id=agent_kwargs["user_id"],
                        )
                    else:
                        result = await start_video_generation(instruction, **agent_kwargs)

                    _append_trace(
                        job,
                        title="Planning",
                        detail="Agent finished selecting tools.",
                        status="done",
                        kind="status",
                        trace_id="planning",
                    )
                    _merge_agent_traces(job, result)
                    artifact = _start_artifact(result)
                    if not artifact:
                        raise RuntimeError(
                            "Generation did not return a structured job result."
                        )

                    if artifact.get("status") == "dry_run":
                        job.update(
                            status="planned",
                            phase="preview",
                            message=(
                                "The direction is ready. Turn on live rendering to create the asset."
                            ),
                            progress=100,
                        )
                        _append_trace(
                            job,
                            title="Dry run complete",
                            detail="Live generation is currently disabled.",
                            status="done",
                            kind="status",
                            trace_id="complete",
                        )
                        await store.put(job)
                        if observation is not None:
                            observation.update(output={"status": "planned", "mode": "dry_run"})
                        return

                    if media_type == "image":
                        _attach_generation_output(job, artifact)
                        job.update(
                            status="complete",
                            phase="complete",
                            message="Your image is ready.",
                            progress=100,
                        )
                        _append_trace(
                            job,
                            title="Image ready",
                            detail="Seedream finished generating the still.",
                            status="done",
                            kind="status",
                            trace_id="complete",
                        )
                        await store.put(job)
                        if observation is not None:
                            observation.update(
                                output={"status": "complete", "has_media": True}
                            )
                        return

                    job["_provider_job_id"] = artifact["job_id"]
                    rendering_message = (
                        "Composing melody, arrangement, and mix."
                        if media_type == "music"
                        else "Shaping the shots, motion, and sound."
                    )
                    rendering_detail = (
                        "Mureka task created. Waiting for the track."
                        if media_type == "music"
                        else "Seedance task created. Waiting for frames."
                    )
                    rendering_title = (
                        "Rendering music" if media_type == "music" else "Rendering video"
                    )
                    job.update(
                        status="generating",
                        phase="rendering",
                        message=rendering_message,
                        progress=32,
                    )
                    _append_trace(
                        job,
                        title=rendering_title,
                        detail=rendering_detail,
                        status="running",
                        kind="status",
                        trace_id="rendering",
                    )
                    await store.put(job)

                await _poll_provider(job)
                rendering_title = (
                    "Rendering music" if media_type == "music" else "Rendering video"
                )
                _append_trace(
                    job,
                    title=rendering_title,
                    detail="Provider finished.",
                    status="done",
                    kind="status",
                    trace_id="rendering",
                )
                if observation is not None:
                    observation.update(
                        output={
                            "status": job.get("status"),
                            "has_media": bool(job.get("output_asset_id")),
                        }
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                job.update(
                    status="failed",
                    phase="failed",
                    message="The render stopped before it finished.",
                    progress=100,
                    error={
                        "code": "generation_failed",
                        "message": "The render stopped before it finished.",
                        "retryable": True,
                    },
                    _error_detail=str(exc)[:2000],
                )
                _append_trace(
                    job,
                    title="Generation failed",
                    detail=str(exc)[:240],
                    status="error",
                    kind="status",
                    trace_id="failed",
                )
                if observation is not None:
                    observation.update(
                        level="ERROR",
                        status_message=str(exc)[:500],
                        output={"status": "failed"},
                    )
            await store.put(job)
            flush_langfuse()


def _start_task(app: FastAPI, job_id: str, *, resume: bool = False) -> None:
    task = asyncio.create_task(_run_generation(job_id, resume=resume), name=f"renderhaus-{job_id}")
    app.state.generation_tasks.add(task)
    task.add_done_callback(app.state.generation_tasks.discard)


@asynccontextmanager
async def lifespan(app: FastAPI):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    init_assets_db()
    await projects.load()
    app.state.generation_tasks = set()
    resumable = await store.load()
    for job_id in resumable:
        _start_task(app, job_id, resume=True)
    yield
    tasks = list(app.state.generation_tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    flush_langfuse()


app = FastAPI(title="Renderhaus", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.exception_handler(404)
async def not_found(request: Request, exc: HTTPException) -> Response:
    """Serve the branded page for browsers and keep JSON for the API surface."""
    wants_html = "text/html" in request.headers.get("accept", "")
    if request.url.path.startswith("/api/") or not wants_html:
        return JSONResponse({"detail": exc.detail}, status_code=404)
    return FileResponse(STATIC_DIR / "404.html", status_code=404)


@app.get("/api/config")
async def config() -> dict[str, Any]:
    return {
        "live_generation": os.getenv("SEEDANCE_DRY_RUN", "true").lower() == "false",
        "live_image_generation": (
            os.getenv("SEEDREAM_DRY_RUN", os.getenv("SEEDANCE_DRY_RUN", "true")).lower() == "false"
        ),
        "live_music_generation": os.getenv("MUREKA_DRY_RUN", "true").lower() == "false",
        "agent_ready": bool(os.getenv("OPENAI_API_KEY")),
        "langfuse_ready": bool(
            os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
        ),
        "clerk_enabled": clerk_enabled(),
        "clerk_publishable_key": publishable_key(),
        "video_model": os.getenv("SEEDANCE_MODEL", "seedance-1-5-pro-251215"),
        "image_model": os.getenv("SEEDREAM_MODEL", "seedream-5-0-lite-260128"),
        "music_model": os.getenv("MUREKA_MODEL", "auto"),
        "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
    }


@app.get("/api/me")
async def me(request: Request) -> dict[str, Any]:
    auth = optional_user(request)
    if auth is None or not auth.payload:
        return {"authenticated": False, "user_id": None if clerk_enabled() else "local"}
    return {
        "authenticated": True,
        "user_id": auth.payload.get("sub"),
        "session_id": auth.payload.get("sid"),
    }


@app.post("/api/uploads", status_code=201)
async def upload_reference(
    auth: AuthUser,
    file: UploadFile = File(...),
) -> dict[str, str]:
    user_id = current_user_id(auth)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Reference image is larger than 15 MB.")
    image_type = _detect_image(content)
    if not image_type:
        raise HTTPException(
            status_code=415, detail="Use a valid PNG, JPEG, or WebP reference image."
        )
    suffix, mime_type = image_type
    asset = register_upload(
        user_id=user_id,
        content=content,
        suffix=suffix,
        mime_type=mime_type,
        filename=file.filename or f"reference{suffix}",
    )
    return {"asset_id": asset.id, "name": asset.filename}


@app.post("/api/projects", status_code=201)
async def create_project(request: ProjectCreateRequest, auth: AuthUser) -> dict[str, Any]:
    user_id = current_user_id(auth)
    project = await projects.create(
        user_id=user_id,
        title=request.title,
        description=request.description,
    )
    return public_project(project)


@app.get("/api/projects")
async def list_projects(auth: AuthUser) -> dict[str, Any]:
    user_id = current_user_id(auth)
    items = [public_project(project) for project in await projects.list_for_user(user_id)]
    return {"items": items}


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str, auth: AuthUser) -> dict[str, Any]:
    user_id = current_user_id(auth)
    project = _require_owned_project(await projects.get(project_id), user_id)
    return public_project(project)


@app.patch("/api/projects/{project_id}")
async def update_project(
    project_id: str,
    request: ProjectUpdateRequest,
    auth: AuthUser,
) -> dict[str, Any]:
    user_id = current_user_id(auth)
    project = _require_owned_project(await projects.get(project_id), user_id)
    if request.title is not None:
        project["title"] = request.title.strip() or project["title"]
    if request.description is not None:
        project["description"] = request.description.strip()
    await projects.put(project)
    return public_project(project)


@app.delete("/api/projects/{project_id}", status_code=204)
async def delete_project(project_id: str, auth: AuthUser) -> Response:
    user_id = current_user_id(auth)
    _require_owned_project(await projects.get(project_id), user_id)
    await projects.delete(project_id)
    return Response(status_code=204)


@app.post("/api/projects/{project_id}/artifacts", status_code=200)
async def add_project_artifact(
    project_id: str,
    request: ProjectArtifactRequest,
    auth: AuthUser,
) -> dict[str, Any]:
    user_id = current_user_id(auth)
    project = _require_owned_project(await projects.get(project_id), user_id)
    job = _require_owned_job(await store.get(request.job_id), user_id)
    job["project_id"] = project_id
    add_artifact(project, job["id"])
    await store.put(job)
    await projects.put(project)
    return {
        "project": public_project(project),
        "job": await _public_job_persisted(job),
    }


@app.delete("/api/projects/{project_id}/artifacts/{job_id}", status_code=200)
async def remove_project_artifact(
    project_id: str,
    job_id: str,
    auth: AuthUser,
) -> dict[str, Any]:
    user_id = current_user_id(auth)
    project = _require_owned_project(await projects.get(project_id), user_id)
    job = await store.get(job_id)
    if job and job.get("user_id") == user_id and job.get("project_id") == project_id:
        job["project_id"] = None
        await store.put(job)
    remove_artifact(project, job_id)
    await projects.put(project)
    return {"project": public_project(project)}


@app.put("/api/projects/{project_id}/timeline")
async def update_project_timeline(
    project_id: str,
    request: TimelineUpdateRequest,
    auth: AuthUser,
) -> dict[str, Any]:
    user_id = current_user_id(auth)
    project = _require_owned_project(await projects.get(project_id), user_id)
    items: list[dict[str, Any]] = []
    for item in request.items:
        job = _require_owned_job(await store.get(item.job_id), user_id)
        if _ensure_output_asset(job):
            await store.put(job)
        payload = item.model_dump()
        payload["asset_id"] = job.get("output_asset_id") or item.asset_id
        payload["media_type"] = job.get("media_type") or item.media_type
        if not payload.get("label"):
            words = str(job.get("prompt") or "").strip().split()[:3]
            payload["label"] = " ".join(words).lower() or "clip"
        if payload.get("duration_seconds") is None:
            payload["duration_seconds"] = job.get("duration_seconds")
        items.append(payload)
        job["project_id"] = project_id
        add_artifact(project, job["id"])
        await store.put(job)
    set_timeline_items(project, items)
    await projects.put(project)
    return public_project(project)


@app.post("/api/projects/{project_id}/merge", status_code=202)
async def merge_project_timeline(project_id: str, auth: AuthUser) -> dict[str, Any]:
    """Merge video-track clips into a new independent video job.

    Source clips stay in the project library. The video track is replaced by
    the merged result; the music track is left untouched.
    """
    user_id = current_user_id(auth)
    project = _require_owned_project(await projects.get(project_id), user_id)
    video_items = timeline_items_by_kind(project, "video")
    music_items = timeline_items_by_kind(project, "music")
    if len(video_items) < 2:
        raise HTTPException(
            status_code=400,
            detail="Add at least two video clips to the V1 track before merging.",
        )

    clip_paths: list[Path] = []
    total_duration = 0.0
    for item in video_items:
        job = _require_owned_job(await store.get(item["job_id"]), user_id)
        if _ensure_output_asset(job):
            await store.put(job)
        asset_id = job.get("output_asset_id")
        if not isinstance(asset_id, str) or not asset_id:
            raise HTTPException(
                status_code=400,
                detail=f"Clip '{item.get('label') or item['job_id'][:8]}' has no finished media yet.",
            )
        asset = get_asset_for_user(asset_id, user_id)
        if not asset:
            raise HTTPException(status_code=400, detail="A timeline clip is missing.")
        try:
            clip_path = materialize_asset_path(asset)
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail="Could not load a timeline clip for merge.",
            ) from exc
        clip_paths.append(clip_path)
        item_duration = item.get("duration_seconds") or job.get("duration_seconds")
        if isinstance(item_duration, (int, float)) and item_duration > 0:
            total_duration += float(item_duration)

    output_path = MEDIA_DIR / "merges" / f"{project_id}-{uuid.uuid4().hex[:10]}.mp4"
    try:
        merge_video_paths(clip_paths, output_path=output_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:500]) from exc

    probed = probe_media_duration(output_path)
    duration_seconds = int(round(probed or total_duration or MAX_VIDEO_SECONDS))
    duration_seconds = max(MIN_VIDEO_SECONDS, min(duration_seconds, 600))

    asset = register_output_file(
        user_id=user_id,
        source_path=output_path,
        kind="video",
        mime_type="video/mp4",
    )
    prompt = f"Merged sequence · {len(clip_paths)} clips"
    generation = GenerationRequest(
        prompt=prompt,
        media_type="video",
        vibe="quiet luxury",
        aspect_ratio="16:9",
        duration_seconds=min(duration_seconds, MAX_VIDEO_SECONDS),
        project_id=project_id,
    )
    job = await store.create(generation, user_id=user_id, project_id=project_id)
    job.update(
        status="complete",
        phase="complete",
        progress=100,
        message="Merged into a new video. Source clips stay in the library.",
        output_asset_id=asset.id,
        media_url=None,
        duration_seconds=duration_seconds,
    )
    _append_trace(
        job,
        title="Merged video track",
        detail=f"Created a new clip from {len(clip_paths)} independent videos.",
        status="done",
        kind="status",
        trace_id="merged",
    )
    await store.put(job)

    # Video track becomes the new merged clip; music track is preserved as-is.
    set_timeline_items(
        project,
        [
            {
                "job_id": job["id"],
                "asset_id": asset.id,
                "media_type": "video",
                "label": "merged sequence",
                "duration_seconds": duration_seconds,
            },
            *music_items,
        ],
    )
    await projects.put(project)
    return {
        "project": public_project(project),
        "job": await _public_job_persisted(job),
    }


@app.post("/api/generations", status_code=202)
async def create_generation(request: GenerationRequest, auth: AuthUser) -> dict[str, Any]:
    user_id = current_user_id(auth)
    project_id = request.project_id
    if project_id:
        _require_owned_project(await projects.get(project_id), user_id)
    reference_asset = _reference_asset_for_user(request.reference_asset_id, user_id)
    reference_storage_key = reference_asset.storage_key if reference_asset else None
    reference_path = None
    if reference_asset and not agentcore_enabled():
        reference_path = _reference_path_for_user(request.reference_asset_id, user_id)
    job = await store.create(
        request,
        user_id=user_id,
        reference_path=reference_path,
        reference_storage_key=reference_storage_key,
        project_id=project_id,
    )
    if project_id:
        project = _require_owned_project(await projects.get(project_id), user_id)
        add_artifact(project, job["id"])
        await projects.put(project)
    _append_trace(
        job,
        title="Queued",
        detail=f"{request.media_type.capitalize()} generation accepted.",
        status="done",
        kind="status",
        trace_id="queued",
    )
    await store.put(job)
    _start_task(app, job["id"])
    return await _public_job_persisted(job)


@app.get("/api/generations")
async def list_generations(
    auth: AuthUser,
    project_id: str | None = None,
    unassigned: bool = False,
) -> dict[str, Any]:
    user_id = current_user_id(auth)
    if project_id:
        _require_owned_project(await projects.get(project_id), user_id)
    items = []
    for job in await store.recent_for_user(
        user_id,
        limit=50,
        project_id=project_id,
        unassigned=unassigned,
    ):
        items.append(await _public_job_persisted(job))
    return {"items": items}


@app.get("/api/generations/{job_id}")
async def get_generation(job_id: str, auth: AuthUser) -> dict[str, Any]:
    user_id = current_user_id(auth)
    job = _require_owned_job(await store.get(job_id), user_id)
    return await _public_job_persisted(job)


@app.get("/api/generations/{job_id}/media", response_model=None)
async def get_generation_media(job_id: str, auth: AuthUser) -> RedirectResponse:
    """Compatibility redirect to a short-lived signed asset URL."""
    user_id = current_user_id(auth)
    job = _require_owned_job(await store.get(job_id), user_id)
    if _ensure_output_asset(job):
        await store.put(job)
    asset_id = job.get("output_asset_id")
    if not isinstance(asset_id, str) or not asset_id:
        raise HTTPException(status_code=404, detail="Generated media not found.")
    asset = get_asset_for_user(asset_id, user_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Generated media not found.")
    return RedirectResponse(url=sign_content_url(asset.id), status_code=307)


@app.get("/api/assets/{asset_id}/content", response_model=None)
async def get_asset_content(
    asset_id: str,
    exp: str | None = None,
    sig: str | None = None,
    proxy: bool = False,
) -> RedirectResponse | StreamingResponse:
    if not verify_content_signature(asset_id, exp, sig):
        raise HTTPException(status_code=401, detail="Invalid or expired media link.")
    asset = get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found.")
    # Same-origin proxy avoids canvas CORS tainting for filmstrip frame capture.
    if proxy:
        try:
            return StreamingResponse(
                iter_asset_bytes(asset),
                media_type=asset.mime_type or "application/octet-stream",
                headers={
                    "Content-Disposition": f'inline; filename="{asset.filename}"',
                    "Cache-Control": "private, max-age=60",
                },
            )
        except Exception as exc:
            raise HTTPException(status_code=404, detail="Asset not found.") from exc
    try:
        url = presigned_content_url(asset)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Asset not found.") from exc
    return RedirectResponse(url=url, status_code=307)


@app.post("/api/generations/{job_id}/refine", status_code=202)
async def refine_generation(
    job_id: str,
    request: RefinementRequest,
    auth: AuthUser,
) -> dict[str, Any]:
    user_id = current_user_id(auth)
    original = _require_owned_job(await store.get(job_id), user_id)
    refinement_suffix = f"\nRefinement: {request.instruction}"
    base_prompt = original["prompt"][: 4000 - len(refinement_suffix)]
    generation = GenerationRequest(
        prompt=f"{base_prompt}{refinement_suffix}",
        media_type=original.get("media_type") or "video",
        vibe=original["vibe"],
        aspect_ratio=original["aspect_ratio"],
        duration_seconds=min(original.get("duration_seconds") or 10, MAX_VIDEO_SECONDS),
        reference_asset_id=original.get("reference_asset_id"),
    )
    reference_asset = _reference_asset_for_user(original.get("reference_asset_id"), user_id)
    reference_storage_key = (
        original.get("_reference_storage_key")
        if isinstance(original.get("_reference_storage_key"), str)
        else (reference_asset.storage_key if reference_asset else None)
    )
    reference_path = None
    if reference_asset and not agentcore_enabled():
        reference_path = _reference_path_for_user(original.get("reference_asset_id"), user_id)
    project_id = original.get("project_id") if isinstance(original.get("project_id"), str) else None
    job = await store.create(
        generation,
        user_id=user_id,
        reference_path=reference_path,
        reference_storage_key=reference_storage_key,
        parent_id=job_id,
        project_id=project_id,
    )
    if project_id:
        project = await projects.get(project_id)
        if project and project.get("user_id") == user_id:
            add_artifact(project, job["id"])
            await projects.put(project)
    _append_trace(
        job,
        title="Queued refinement",
        detail=request.instruction[:240],
        status="done",
        kind="status",
        trace_id="queued",
    )
    await store.put(job)
    _start_task(app, job["id"])
    return await _public_job_persisted(job)


def main() -> None:
    import uvicorn

    uvicorn.run("web.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
