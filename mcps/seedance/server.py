from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP
from pydantic import BaseModel, Field


mcp = FastMCP("renderhaus-seedance")


class SeedanceTask(BaseModel):
    job_id: str
    status: Literal["dry_run", "queued"]
    provider: str = "byteplus-seedance"
    mode: str
    prompt: str
    duration_seconds: int
    aspect_ratio: str
    resolution: str
    estimated_cost_usd: float | None = None
    output_path: str | None = None
    note: str


def _media_dir() -> Path:
    path = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _dry_run() -> bool:
    return os.getenv("SEEDANCE_DRY_RUN", "true").lower() != "false"


def _task(
    *,
    mode: str,
    prompt: str,
    duration_seconds: int,
    aspect_ratio: str,
    resolution: str,
) -> dict:
    job_id = f"seedance_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    output_path = _media_dir() / "video" / f"{job_id}.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    status: Literal["dry_run", "queued"] = "dry_run" if _dry_run() else "queued"
    note = (
        "Dry run only. Set SEEDANCE_DRY_RUN=false after implementing the BytePlus task call."
        if _dry_run()
        else "Live mode is enabled, but the BytePlus API call is not implemented yet."
    )
    return SeedanceTask(
        job_id=job_id,
        status=status,
        mode=mode,
        prompt=prompt,
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        output_path=str(output_path),
        note=note,
    ).model_dump()


@mcp.tool()
def text_to_video(
    prompt: str = Field(description="Video prompt."),
    duration_seconds: int = Field(default=5, ge=4, le=15),
    aspect_ratio: str = Field(default="16:9"),
    resolution: str = Field(default="720p"),
) -> dict:
    """Create a Seedance text-to-video task. Currently dry-runs the provider call."""
    return _task(
        mode="text_to_video",
        prompt=prompt,
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
    )


@mcp.tool()
def image_to_video(
    image_path_or_url: str = Field(description="Reference image path or URL."),
    prompt: str = Field(description="Motion and style prompt."),
    duration_seconds: int = Field(default=5, ge=4, le=15),
    aspect_ratio: str = Field(default="16:9"),
    resolution: str = Field(default="720p"),
) -> dict:
    """Create a Seedance image-to-video task. Currently dry-runs the provider call."""
    return _task(
        mode="image_to_video",
        prompt=f"{prompt}\nReference image: {image_path_or_url}",
        duration_seconds=duration_seconds,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
    )


@mcp.tool()
def get_video_task(job_id: str) -> dict:
    """Return placeholder Seedance task status for local wiring tests."""
    return {
        "job_id": job_id,
        "status": "dry_run" if _dry_run() else "unknown",
        "provider": "byteplus-seedance",
        "note": "Status polling is scaffolded; live BytePlus retrieval is not implemented yet.",
    }


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
