"""Project containers for generations, timelines, and merges."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from agent.config import ROOT

PROJECTS_DIR = ROOT / ".renderhaus" / "projects"
PUBLIC_PROJECT_FIELDS = {
    "id",
    "schema_version",
    "title",
    "description",
    "user_id",
    "created_at",
    "updated_at",
    "artifact_ids",
    "timeline",
}

# Normalize every clip to this before concat so mismatched providers still merge.
_MERGE_WIDTH = 1280
_MERGE_HEIGHT = 720
_MERGE_FPS = 24
_MERGE_SAMPLE_RATE = 44100


def _now() -> int:
    return int(time.time())


def _empty_timeline() -> dict[str, Any]:
    return {"items": []}


class ProjectStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or PROJECTS_DIR
        self._projects: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        for path in self.directory.glob("*.json"):
            try:
                project = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(project, dict) or not isinstance(project.get("id"), str):
                continue
            project.setdefault("schema_version", 1)
            project.setdefault("description", "")
            project.setdefault("artifact_ids", [])
            project.setdefault("timeline", _empty_timeline())
            if not isinstance(project["timeline"], dict):
                project["timeline"] = _empty_timeline()
            project["timeline"].setdefault("items", [])
            self._projects[project["id"]] = project

    async def create(
        self,
        *,
        user_id: str,
        title: str,
        description: str = "",
    ) -> dict[str, Any]:
        now = _now()
        project = {
            "id": uuid.uuid4().hex,
            "schema_version": 1,
            "title": title.strip() or "Untitled project",
            "description": description.strip(),
            "user_id": user_id,
            "created_at": now,
            "updated_at": now,
            "artifact_ids": [],
            "timeline": _empty_timeline(),
        }
        await self.put(project)
        return project

    async def put(self, project: dict[str, Any]) -> None:
        async with self._lock:
            project["updated_at"] = _now()
            self._projects[project["id"]] = project
            self.directory.mkdir(parents=True, exist_ok=True)
            target = self.directory / f"{project['id']}.json"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(project, indent=2, sort_keys=True))
            temporary.replace(target)

    async def get(self, project_id: str) -> dict[str, Any] | None:
        async with self._lock:
            project = self._projects.get(project_id)
            return dict(project) if project else None

    async def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        async with self._lock:
            projects = sorted(
                (
                    project
                    for project in self._projects.values()
                    if project.get("user_id") == user_id
                ),
                key=lambda item: item.get("updated_at", 0),
                reverse=True,
            )
            return [dict(project) for project in projects]

    async def delete(self, project_id: str) -> bool:
        async with self._lock:
            project = self._projects.pop(project_id, None)
            if not project:
                return False
            path = self.directory / f"{project_id}.json"
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return True


def public_project(project: dict[str, Any]) -> dict[str, Any]:
    public = {key: project.get(key) for key in PUBLIC_PROJECT_FIELDS}
    timeline = project.get("timeline") or _empty_timeline()
    items = timeline.get("items") if isinstance(timeline, dict) else []
    public["timeline"] = {"items": list(items or [])}
    public["artifact_ids"] = list(project.get("artifact_ids") or [])
    public["artifact_count"] = len(public["artifact_ids"])
    public["timeline_count"] = len(public["timeline"]["items"])
    return public


def add_artifact(project: dict[str, Any], job_id: str) -> bool:
    """Add a generation id to the project library. Returns True if changed."""
    artifacts = list(project.get("artifact_ids") or [])
    if job_id in artifacts:
        return False
    artifacts.append(job_id)
    project["artifact_ids"] = artifacts
    return True


def remove_artifact(project: dict[str, Any], job_id: str) -> bool:
    artifacts = list(project.get("artifact_ids") or [])
    if job_id not in artifacts:
        return False
    project["artifact_ids"] = [item for item in artifacts if item != job_id]
    timeline = project.get("timeline") or _empty_timeline()
    items = [
        item
        for item in (timeline.get("items") or [])
        if item.get("job_id") != job_id
    ]
    project["timeline"] = {"items": items}
    return True


def timeline_items_by_kind(
    project: dict[str, Any],
    media_type: str,
) -> list[dict[str, Any]]:
    timeline = project.get("timeline") or _empty_timeline()
    return [
        item
        for item in (timeline.get("items") or [])
        if item.get("media_type") == media_type
    ]


def set_timeline_items(
    project: dict[str, Any],
    items: list[dict[str, Any]],
) -> None:
    cleaned: list[dict[str, Any]] = []
    for raw in items:
        job_id = raw.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            continue
        media_type = raw.get("media_type") or "video"
        if media_type not in {"video", "music"}:
            # Images and other kinds stay in the library, not on the edit timeline.
            continue
        cleaned.append(
            {
                "id": raw.get("id") if isinstance(raw.get("id"), str) else uuid.uuid4().hex,
                "job_id": job_id,
                "asset_id": raw.get("asset_id") if isinstance(raw.get("asset_id"), str) else None,
                "media_type": media_type,
                "label": (raw.get("label") or "")[:120],
                "duration_seconds": raw.get("duration_seconds"),
            }
        )
    # Keep video clips ahead of music so order stays predictable across clients.
    videos = [item for item in cleaned if item["media_type"] == "video"]
    music = [item for item in cleaned if item["media_type"] == "music"]
    project["timeline"] = {"items": [*videos, *music]}
    for item in cleaned:
        add_artifact(project, item["job_id"])


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def probe_media_duration(path: Path) -> float | None:
    if not path.is_file() or not shutil.which("ffprobe"):
        return None
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        duration = float((result.stdout or "").strip())
    except ValueError:
        return None
    return duration if duration > 0 else None


def _has_audio_stream(path: Path) -> bool:
    if not shutil.which("ffprobe"):
        return True
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and "audio" in (result.stdout or "")


def merge_video_paths(
    paths: list[Path],
    *,
    output_path: Path,
) -> Path:
    """Concatenate video clips into a new file.

    Each input is normalized first so clips from different provider runs
    (fps, sample rate, missing audio) still concatenate cleanly. Source
    clips are never modified.
    """
    if len(paths) < 2:
        raise ValueError("Merge needs at least two clips.")
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg is not installed on this machine.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="renderhaus-merge-") as tmp:
        tmp_dir = Path(tmp)
        normalized: list[Path] = []
        for index, path in enumerate(paths):
            if not path.is_file():
                raise FileNotFoundError(f"Missing clip: {path}")
            normalized_path = tmp_dir / f"clip-{index:03d}.mp4"
            _normalize_clip(path, normalized_path)
            normalized.append(normalized_path)

        list_path = tmp_dir / "concat.txt"
        lines = []
        for path in normalized:
            escaped = str(path.resolve()).replace("'", r"'\''")
            lines.append(f"file '{escaped}'")
        list_path.write_text("\n".join(lines) + "\n")

        command = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not output_path.is_file():
            detail = (result.stderr or result.stdout or "ffmpeg failed").strip()
            raise RuntimeError(detail[-800:] or "ffmpeg failed to merge clips.")
    return output_path


def _normalize_clip(source: Path, destination: Path) -> None:
    """Re-encode one clip to a shared video/audio profile for concat."""
    has_audio = _has_audio_stream(source)
    video_filter = (
        f"scale={_MERGE_WIDTH}:{_MERGE_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={_MERGE_WIDTH}:{_MERGE_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
        f"fps={_MERGE_FPS},format=yuv420p,setsar=1"
    )
    if has_audio:
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-vf",
            video_filter,
            "-af",
            f"aformat=sample_rates={_MERGE_SAMPLE_RATE}:channel_layouts=stereo",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-ar",
            str(_MERGE_SAMPLE_RATE),
            "-ac",
            "2",
            "-shortest",
            str(destination),
        ]
    else:
        # Synthetic silence keeps concat demuxer stream maps consistent.
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout=stereo:sample_rate={_MERGE_SAMPLE_RATE}",
            "-vf",
            video_filter,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-ar",
            str(_MERGE_SAMPLE_RATE),
            "-ac",
            "2",
            "-shortest",
            str(destination),
        ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not destination.is_file():
        detail = (result.stderr or result.stdout or "ffmpeg normalize failed").strip()
        raise RuntimeError(detail[-800:] or "ffmpeg failed to normalize a clip.")

