from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent.config import ROOT, load_local_env
from agent.service import poll_video_generation, start_video_generation
from agent.tracing import flush_langfuse, traced_operation


load_local_env()

STATIC_DIR = Path(__file__).with_name("static")
STATE_DIR = ROOT / ".renderhaus" / "web-jobs"
UPLOAD_DIR = ROOT / ".renderhaus" / "uploads"
MEDIA_DIR = (ROOT / os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).resolve()
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
TERMINAL_STATES = {"complete", "planned", "failed"}
PROVIDER_TERMINAL_STATES = {"succeeded", "failed", "cancelled", "canceled", "deleted"}
PUBLIC_JOB_FIELDS = {
    "id",
    "schema_version",
    "status",
    "phase",
    "prompt",
    "vibe",
    "aspect_ratio",
    "duration_seconds",
    "reference_asset_id",
    "parent_id",
    "created_at",
    "updated_at",
    "message",
    "media_url",
    "error",
}


class GenerationRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)
    vibe: str = Field(default="quiet luxury", max_length=120)
    aspect_ratio: str = Field(default="16:9", pattern=r"^(16:9|9:16|1:1)$")
    duration_seconds: int = Field(default=10, ge=4, le=15)
    reference_asset_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class RefinementRequest(BaseModel):
    instruction: str = Field(min_length=3, max_length=2000)


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
            if job.get("status") not in TERMINAL_STATES:
                if job.get("_provider_job_id"):
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
        reference_path: str | None = None,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        now = int(time.time())
        job = {
            "id": uuid.uuid4().hex,
            "schema_version": 1,
            "status": "queued",
            "phase": "queued",
            "prompt": request.prompt,
            "vibe": request.vibe,
            "aspect_ratio": request.aspect_ratio,
            "duration_seconds": request.duration_seconds,
            "reference_asset_id": request.reference_asset_id,
            "parent_id": parent_id,
            "created_at": now,
            "updated_at": now,
            "message": "Reading the idea and finding its visual rhythm.",
            "media_url": None,
            "error": None,
            "_reference_path": reference_path,
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

    async def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        async with self._lock:
            jobs = sorted(
                self._jobs.values(), key=lambda item: item.get("created_at", 0), reverse=True
            )
            return [dict(job) for job in jobs[:limit]]


store = JobStore(STATE_DIR)
generation_slots = asyncio.Semaphore(2)


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    public = {key: job.get(key) for key in PUBLIC_JOB_FIELDS}
    if job.get("_output_path"):
        public["media_url"] = f"/api/generations/{job['id']}/media"
    return public


def _asset_path(asset_id: str | None) -> str | None:
    if not asset_id:
        return None
    matches = list(UPLOAD_DIR.glob(f"{asset_id}.*"))
    if len(matches) != 1 or not matches[0].is_file():
        raise HTTPException(status_code=400, detail="Reference image no longer exists.")
    return str(matches[0].resolve())


def _detect_image(content: bytes) -> tuple[str, str] | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return None


def _generation_instruction(job: dict[str, Any]) -> str:
    reference = job.get("_reference_path")
    reference_instruction = (
        f"Use this local reference image: {reference}. "
        if reference
        else "No reference image is supplied. "
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


def _start_artifact(result: dict[str, Any]) -> dict[str, Any] | None:
    for artifact in reversed(result.get("artifacts", [])):
        if isinstance(artifact, dict) and isinstance(artifact.get("job_id"), str):
            return artifact
    return None


async def _poll_provider(job: dict[str, Any]) -> None:
    provider_job_id = job.get("_provider_job_id")
    if not isinstance(provider_job_id, str):
        raise RuntimeError("Video generation did not return a job identifier.")

    while True:
        result = await poll_video_generation(provider_job_id)
        status = str(result.get("status", "unknown")).lower()
        if status == "succeeded":
            output_path = _artifact_path(result)
            if not output_path:
                raise RuntimeError("Video generation succeeded without a downloadable media file.")
            job.update(
                status="complete",
                phase="complete",
                message="Your film is ready.",
                _output_path=output_path,
            )
            return
        if status in PROVIDER_TERMINAL_STATES:
            raise RuntimeError(f"Video generation ended with status {status}.")
        job.update(
            status="generating", phase="rendering", message="Shaping the shots, motion, and sound."
        )
        await store.put(job)
        await asyncio.sleep(5)


async def _run_generation(job_id: str, *, resume: bool = False) -> None:
    async with generation_slots:
        job = await store.get(job_id)
        if not job:
            return
        session_id = job.get("parent_id") or job_id
        with traced_operation(
            "video-generation",
            as_type="agent",
            input={
                "prompt": job.get("prompt"),
                "vibe": job.get("vibe"),
                "aspect_ratio": job.get("aspect_ratio"),
                "duration_seconds": job.get("duration_seconds"),
                "resume": resume,
            },
            session_id=session_id,
            tags=["renderhaus", "web", "video-generation"],
            metadata={
                "feature": "video-generation",
                "job_id": job_id,
                "parent_id": job.get("parent_id") or "",
            },
            trace_name="video-generation",
        ) as observation:
            try:
                if not resume:
                    job.update(
                        status="planning",
                        phase="planning",
                        message="Finding the film's visual rhythm.",
                    )
                    await store.put(job)
                    result = await start_video_generation(_generation_instruction(job))
                    artifact = _start_artifact(result)
                    if not artifact:
                        raise RuntimeError(
                            "Video generation did not return a structured job result."
                        )
                    if artifact.get("status") == "dry_run":
                        job.update(
                            status="planned",
                            phase="preview",
                            message=(
                                "The direction is ready. Turn on live rendering to create the MP4."
                            ),
                        )
                        await store.put(job)
                        if observation is not None:
                            observation.update(output={"status": "planned", "mode": "dry_run"})
                        return
                    job["_provider_job_id"] = artifact["job_id"]
                    job.update(
                        status="generating",
                        phase="rendering",
                        message="Shaping the shots, motion, and sound.",
                    )
                    await store.put(job)
                await _poll_provider(job)
                if observation is not None:
                    observation.update(
                        output={
                            "status": job.get("status"),
                            "has_media": bool(job.get("_output_path")),
                        }
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                job.update(
                    status="failed",
                    phase="failed",
                    message="The render stopped before it finished.",
                    error={
                        "code": "generation_failed",
                        "message": "The render stopped before it finished.",
                        "retryable": True,
                    },
                    _error_detail=str(exc)[:2000],
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
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
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


@app.get("/api/config")
async def config() -> dict[str, Any]:
    return {
        "live_generation": os.getenv("SEEDANCE_DRY_RUN", "true").lower() == "false",
        "agent_ready": bool(os.getenv("OPENAI_API_KEY")),
        "langfuse_ready": bool(
            os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
        ),
        "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
    }


@app.post("/api/uploads", status_code=201)
async def upload_reference(file: UploadFile = File(...)) -> dict[str, str]:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Reference image is larger than 15 MB.")
    image_type = _detect_image(content)
    if not image_type:
        raise HTTPException(
            status_code=415, detail="Use a valid PNG, JPEG, or WebP reference image."
        )
    suffix, _ = image_type
    asset_id = uuid.uuid4().hex
    (UPLOAD_DIR / f"{asset_id}{suffix}").write_bytes(content)
    return {"asset_id": asset_id, "name": file.filename or "reference"}


@app.post("/api/generations", status_code=202)
async def create_generation(request: GenerationRequest) -> dict[str, Any]:
    reference_path = _asset_path(request.reference_asset_id)
    job = await store.create(request, reference_path=reference_path)
    _start_task(app, job["id"])
    return _public_job(job)


@app.get("/api/generations")
async def list_generations() -> dict[str, Any]:
    return {"items": [_public_job(job) for job in await store.recent()]}


@app.get("/api/generations/{job_id}")
async def get_generation(job_id: str) -> dict[str, Any]:
    job = await store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Generation not found.")
    return _public_job(job)


@app.get("/api/generations/{job_id}/media")
async def get_generation_media(job_id: str) -> FileResponse:
    job = await store.get(job_id)
    if not job or not job.get("_output_path"):
        raise HTTPException(status_code=404, detail="Generated media not found.")
    try:
        path = Path(job["_output_path"]).resolve()
        path.relative_to(MEDIA_DIR)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="Generated media not found.")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Generated media not found.")
    return FileResponse(path, media_type="video/mp4")


@app.post("/api/generations/{job_id}/refine", status_code=202)
async def refine_generation(job_id: str, request: RefinementRequest) -> dict[str, Any]:
    original = await store.get(job_id)
    if not original:
        raise HTTPException(status_code=404, detail="Generation not found.")
    refinement_suffix = f"\nRefinement: {request.instruction}"
    base_prompt = original["prompt"][: 4000 - len(refinement_suffix)]
    generation = GenerationRequest(
        prompt=f"{base_prompt}{refinement_suffix}",
        vibe=original["vibe"],
        aspect_ratio=original["aspect_ratio"],
        duration_seconds=original["duration_seconds"],
        reference_asset_id=original.get("reference_asset_id"),
    )
    job = await store.create(
        generation,
        reference_path=original.get("_reference_path"),
        parent_id=job_id,
    )
    _start_task(app, job["id"])
    return _public_job(job)


def main() -> None:
    import uvicorn

    uvicorn.run("web.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
