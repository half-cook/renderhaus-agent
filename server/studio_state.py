"""Durable, workspace-scoped state for the Renderhaus Studio canvas.

SQLite is the local development adapter.  The schema deliberately mirrors the
Postgres shape used in production: logical assets, immutable asset versions,
provenance relations, executions, and tool calls are separate records.
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import shutil
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx

from server.config import ROOT


StudioAssetKind = Literal["image", "video", "audio"]
MAX_REMOTE_ASSET_BYTES = 250 * 1024 * 1024


class CanvasConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StudioAssetRef:
    asset_id: str
    version_id: str
    kind: StudioAssetKind
    filename: str
    mime_type: str
    size_bytes: int
    created_at: int

    def public(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "version_id": self.version_id,
            "kind": self.kind,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
        }

    def canvas(self) -> dict[str, Any]:
        """Camel-case representation stored in a React Flow document."""
        return {
            "assetId": self.asset_id,
            "versionId": self.version_id,
            "kind": self.kind,
            "filename": self.filename,
            "mimeType": self.mime_type,
            "sizeBytes": self.size_bytes,
            "createdAt": self.created_at,
        }


def _default_database_path() -> Path:
    configured = os.getenv("RENDERHAUS_STUDIO_DATABASE", ".renderhaus/studio.sqlite3")
    path = Path(configured).expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()


def _default_media_root() -> Path:
    configured = os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")
    path = Path(configured).expanduser()
    base = path if path.is_absolute() else ROOT / path
    return (base / "assets").resolve()


def _now() -> int:
    return int(time.time())


def _safe_filename(value: str, fallback: str) -> str:
    name = Path(value).name.strip().replace("\x00", "")
    return name[:180] or fallback


def _kind_for_mime_or_name(mime_type: str | None, filename: str) -> StudioAssetKind | None:
    mime = (mime_type or "").lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    suffix = Path(filename.split("?", 1)[0]).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "image"
    if suffix in {".mp4", ".webm", ".mov", ".m4v"}:
        return "video"
    if suffix in {".mp3", ".wav", ".m4a", ".ogg", ".flac"}:
        return "audio"
    return None


class StudioRepository:
    def __init__(self, database_path: Path | None = None, media_root: Path | None = None) -> None:
        self.database_path = (database_path or _default_database_path()).resolve()
        self.media_root = (media_root or _default_media_root()).resolve()
        self._lock = threading.RLock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        self.init()
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def init(self) -> None:
        with self._lock:
            if self._initialized:
                return
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self.media_root.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.database_path, timeout=30)
            try:
                connection.executescript(
                    """
                    PRAGMA journal_mode = WAL;
                    PRAGMA foreign_keys = ON;

                    CREATE TABLE IF NOT EXISTS workspaces (
                        id TEXT PRIMARY KEY,
                        owner_user_id TEXT NOT NULL,
                        created_at INTEGER NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS projects (
                        id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                        name TEXT NOT NULL,
                        created_by TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL,
                        PRIMARY KEY(workspace_id, id)
                    );
                    CREATE INDEX IF NOT EXISTS projects_workspace_updated
                        ON projects(workspace_id, updated_at DESC);

                    CREATE TABLE IF NOT EXISTS canvas_documents (
                        project_id TEXT NOT NULL,
                        workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                        revision INTEGER NOT NULL DEFAULT 1,
                        document_json TEXT NOT NULL,
                        updated_by TEXT NOT NULL,
                        updated_at INTEGER NOT NULL,
                        PRIMARY KEY(workspace_id, project_id),
                        FOREIGN KEY(workspace_id, project_id)
                            REFERENCES projects(workspace_id, id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS assets (
                        id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                        project_id TEXT,
                        kind TEXT NOT NULL CHECK(kind IN ('image', 'video', 'audio')),
                        name TEXT NOT NULL,
                        current_version_id TEXT,
                        created_by TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS assets_workspace_project
                        ON assets(workspace_id, project_id, updated_at DESC);

                    CREATE TABLE IF NOT EXISTS asset_versions (
                        id TEXT PRIMARY KEY,
                        asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
                        workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                        kind TEXT NOT NULL CHECK(kind IN ('image', 'video', 'audio')),
                        mime_type TEXT NOT NULL,
                        size_bytes INTEGER NOT NULL,
                        checksum TEXT NOT NULL,
                        storage_backend TEXT NOT NULL,
                        storage_key TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        created_by TEXT NOT NULL,
                        execution_id TEXT,
                        tool_call_id TEXT,
                        created_at INTEGER NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS versions_asset_created
                        ON asset_versions(asset_id, created_at DESC);
                    CREATE INDEX IF NOT EXISTS versions_workspace
                        ON asset_versions(workspace_id, created_at DESC);

                    CREATE TABLE IF NOT EXISTS asset_relations (
                        id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                        source_version_id TEXT NOT NULL REFERENCES asset_versions(id),
                        target_version_id TEXT NOT NULL REFERENCES asset_versions(id),
                        relation_type TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        UNIQUE(source_version_id, target_version_id, relation_type)
                    );

                    CREATE TABLE IF NOT EXISTS executions (
                        id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                        project_id TEXT,
                        created_by TEXT NOT NULL,
                        prompt TEXT NOT NULL,
                        status TEXT NOT NULL,
                        message TEXT NOT NULL,
                        result_json TEXT,
                        error_type TEXT,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS executions_workspace_updated
                        ON executions(workspace_id, updated_at DESC);

                    CREATE TABLE IF NOT EXISTS tool_calls (
                        id TEXT PRIMARY KEY,
                        execution_id TEXT NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
                        workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                        name TEXT NOT NULL,
                        label TEXT NOT NULL,
                        provider TEXT,
                        provider_job_id TEXT,
                        status TEXT NOT NULL,
                        summary TEXT NOT NULL,
                        result_json TEXT,
                        output_versions_json TEXT NOT NULL DEFAULT '[]',
                        created_at INTEGER NOT NULL,
                        completed_at INTEGER NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS tool_calls_execution_created
                        ON tool_calls(execution_id, created_at);
                    """
                )
                connection.commit()
            finally:
                connection.close()
            self._initialized = True

    def ensure_workspace(self, workspace_id: str, user_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO workspaces(id, owner_user_id, created_at) VALUES (?, ?, ?)",
                (workspace_id, user_id, _now()),
            )

    def list_projects(self, workspace_id: str, user_id: str) -> list[dict[str, Any]]:
        self.ensure_workspace(workspace_id, user_id)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, name, created_at, updated_at FROM projects "
                "WHERE workspace_id = ? ORDER BY updated_at DESC",
                (workspace_id,),
            ).fetchall()
        if not rows:
            self.create_project(workspace_id, user_id, "Untitled", project_id="untitled")
            return self.list_projects(workspace_id, user_id)
        return [dict(row) for row in rows]

    def create_project(
        self,
        workspace_id: str,
        user_id: str,
        name: str,
        *,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_workspace(workspace_id, user_id)
        resolved_id = project_id or uuid.uuid4().hex
        now = _now()
        empty_document = {
            "schemaVersion": 2,
            "projectName": name or "Untitled",
            "nodes": [],
            "edges": [],
            "viewport": {"x": 80, "y": 80, "zoom": 1},
        }
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id, name, created_at, updated_at FROM projects "
                "WHERE id = ? AND workspace_id = ?",
                (resolved_id, workspace_id),
            ).fetchone()
            if existing:
                return dict(existing)
            connection.execute(
                "INSERT OR IGNORE INTO projects(id, workspace_id, name, created_by, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (resolved_id, workspace_id, name or "Untitled", user_id, now, now),
            )
            connection.execute(
                "INSERT OR IGNORE INTO canvas_documents(project_id, workspace_id, revision, document_json, "
                "updated_by, updated_at) VALUES (?, ?, 1, ?, ?, ?)",
                (resolved_id, workspace_id, json.dumps(empty_document), user_id, now),
            )
            created = connection.execute(
                "SELECT id, name, created_at, updated_at FROM projects "
                "WHERE id = ? AND workspace_id = ?",
                (resolved_id, workspace_id),
            ).fetchone()
        if created is None:  # pragma: no cover - SQLite would have raised first
            raise RuntimeError("Project creation did not produce a project row")
        return dict(created)

    def require_project(self, workspace_id: str, project_id: str) -> sqlite3.Row:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ? AND workspace_id = ?",
                (project_id, workspace_id),
            ).fetchone()
        if row is None:
            raise KeyError("Project not found")
        return row

    def get_canvas(self, workspace_id: str, project_id: str) -> dict[str, Any]:
        self.require_project(workspace_id, project_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT revision, document_json, updated_at FROM canvas_documents "
                "WHERE project_id = ? AND workspace_id = ?",
                (project_id, workspace_id),
            ).fetchone()
        if row is None:
            raise KeyError("Canvas not found")
        return {
            "revision": int(row["revision"]),
            "document": json.loads(str(row["document_json"])),
            "updated_at": int(row["updated_at"]),
        }

    def save_canvas(
        self,
        workspace_id: str,
        project_id: str,
        user_id: str,
        document: dict[str, Any],
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        self.require_project(workspace_id, project_id)
        now = _now()
        name = str(document.get("projectName") or "Untitled")[:120]
        encoded = json.dumps(document, separators=(",", ":"), ensure_ascii=False)
        with self._connect() as connection:
            if expected_revision is None:
                cursor = connection.execute(
                    "UPDATE canvas_documents SET revision = revision + 1, document_json = ?, "
                    "updated_by = ?, updated_at = ? WHERE project_id = ? AND workspace_id = ?",
                    (encoded, user_id, now, project_id, workspace_id),
                )
            else:
                cursor = connection.execute(
                    "UPDATE canvas_documents SET revision = revision + 1, document_json = ?, "
                    "updated_by = ?, updated_at = ? WHERE project_id = ? AND workspace_id = ? "
                    "AND revision = ?",
                    (encoded, user_id, now, project_id, workspace_id, expected_revision),
                )
            if cursor.rowcount == 0:
                raise CanvasConflictError("Canvas changed in another session; reload before saving.")
            connection.execute(
                "UPDATE projects SET name = ?, updated_at = ? WHERE id = ? AND workspace_id = ?",
                (name, now, project_id, workspace_id),
            )
            row = connection.execute(
                "SELECT revision FROM canvas_documents WHERE project_id = ? AND workspace_id = ?",
                (project_id, workspace_id),
            ).fetchone()
        return {"revision": int(row["revision"]), "document": document, "updated_at": now}

    def _asset_ref(self, row: sqlite3.Row) -> StudioAssetRef:
        return StudioAssetRef(
            asset_id=str(row["asset_id"]),
            version_id=str(row["id"]),
            kind=str(row["kind"]),  # type: ignore[arg-type]
            filename=str(row["filename"]),
            mime_type=str(row["mime_type"]),
            size_bytes=int(row["size_bytes"]),
            created_at=int(row["created_at"]),
        )

    def get_version(self, workspace_id: str, version_id: str) -> StudioAssetRef | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, asset_id, kind, filename, mime_type, size_bytes, created_at "
                "FROM asset_versions WHERE id = ? AND workspace_id = ?",
                (version_id, workspace_id),
            ).fetchone()
        return self._asset_ref(row) if row else None

    def version_path(self, workspace_id: str, version_id: str) -> Path:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT storage_backend, storage_key FROM asset_versions "
                "WHERE id = ? AND workspace_id = ?",
                (version_id, workspace_id),
            ).fetchone()
        if row is None:
            raise KeyError("Asset version not found")
        if row["storage_backend"] != "local":
            raise ValueError(f"Unsupported Studio storage backend: {row['storage_backend']}")
        path = Path(str(row["storage_key"])).resolve()
        if self.media_root not in path.parents or not path.is_file():
            raise FileNotFoundError("Asset content is unavailable")
        return path

    def _record_version(
        self,
        *,
        workspace_id: str,
        project_id: str | None,
        user_id: str,
        source_path: Path,
        kind: StudioAssetKind,
        filename: str,
        mime_type: str,
        asset_id: str | None = None,
        execution_id: str | None = None,
        tool_call_id: str | None = None,
        source_version_ids: list[str] | None = None,
        relation_type: str = "derived_from",
    ) -> StudioAssetRef:
        source = source_path.resolve()
        if not source.is_file() or source.stat().st_size <= 0:
            raise FileNotFoundError(f"Asset output is missing: {source}")
        if project_id:
            self.require_project(workspace_id, project_id)
        resolved_asset_id = asset_id or uuid.uuid4().hex
        resolved_version_id = uuid.uuid4().hex
        now = _now()
        safe_name = _safe_filename(filename, f"{resolved_version_id}.bin")
        if asset_id:
            with self._connect() as connection:
                collision = connection.execute(
                    "SELECT workspace_id FROM assets WHERE id = ?",
                    (resolved_asset_id,),
                ).fetchone()
            if collision and str(collision["workspace_id"]) != workspace_id:
                resolved_asset_id = uuid.uuid4().hex
        destination = self.media_root / workspace_id.replace(":", "_") / resolved_asset_id / resolved_version_id / safe_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source != destination:
            shutil.copy2(source, destination)
        checksum = hashlib.sha256()
        with destination.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                checksum.update(chunk)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT kind FROM assets WHERE id = ? AND workspace_id = ?",
                (resolved_asset_id, workspace_id),
            ).fetchone()
            if existing and str(existing["kind"]) != kind:
                resolved_asset_id = uuid.uuid4().hex
                existing = None
                destination = self.media_root / workspace_id.replace(":", "_") / resolved_asset_id / resolved_version_id / safe_name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            if not existing:
                connection.execute(
                    "INSERT INTO assets(id, workspace_id, project_id, kind, name, current_version_id, "
                    "created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?)",
                    (
                        resolved_asset_id,
                        workspace_id,
                        project_id,
                        kind,
                        Path(safe_name).stem or kind.title(),
                        user_id,
                        now,
                        now,
                    ),
                )
            connection.execute(
                "INSERT INTO asset_versions(id, asset_id, workspace_id, kind, mime_type, size_bytes, "
                "checksum, storage_backend, storage_key, filename, created_by, execution_id, "
                "tool_call_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'local', ?, ?, ?, ?, ?, ?)",
                (
                    resolved_version_id,
                    resolved_asset_id,
                    workspace_id,
                    kind,
                    mime_type,
                    destination.stat().st_size,
                    checksum.hexdigest(),
                    str(destination),
                    safe_name,
                    user_id,
                    execution_id,
                    tool_call_id,
                    now,
                ),
            )
            connection.execute(
                "UPDATE assets SET current_version_id = ?, updated_at = ? "
                "WHERE id = ? AND workspace_id = ?",
                (resolved_version_id, now, resolved_asset_id, workspace_id),
            )
            for source_version_id in dict.fromkeys(source_version_ids or []):
                owned = connection.execute(
                    "SELECT 1 FROM asset_versions WHERE id = ? AND workspace_id = ?",
                    (source_version_id, workspace_id),
                ).fetchone()
                if owned:
                    connection.execute(
                        "INSERT OR IGNORE INTO asset_relations(id, workspace_id, source_version_id, "
                        "target_version_id, relation_type, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            uuid.uuid4().hex,
                            workspace_id,
                            source_version_id,
                            resolved_version_id,
                            relation_type,
                            now,
                        ),
                    )
        return StudioAssetRef(
            asset_id=resolved_asset_id,
            version_id=resolved_version_id,
            kind=kind,
            filename=safe_name,
            mime_type=mime_type,
            size_bytes=destination.stat().st_size,
            created_at=now,
        )

    def register_bytes(
        self,
        *,
        workspace_id: str,
        project_id: str | None,
        user_id: str,
        content: bytes,
        filename: str,
        kind: StudioAssetKind,
        mime_type: str | None = None,
        asset_id: str | None = None,
        execution_id: str | None = None,
        tool_call_id: str | None = None,
        source_version_ids: list[str] | None = None,
        relation_type: str = "derived_from",
    ) -> StudioAssetRef:
        if not content:
            raise ValueError("Asset content was empty")
        temporary = self.media_root / ".incoming" / f"{uuid.uuid4().hex}-{_safe_filename(filename, 'asset.bin')}"
        temporary.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(content)
        try:
            resolved_mime = mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
            return self._record_version(
                workspace_id=workspace_id,
                project_id=project_id,
                user_id=user_id,
                source_path=temporary,
                kind=kind,
                filename=filename,
                mime_type=resolved_mime,
                asset_id=asset_id,
                execution_id=execution_id,
                tool_call_id=tool_call_id,
                source_version_ids=source_version_ids,
                relation_type=relation_type,
            )
        finally:
            temporary.unlink(missing_ok=True)

    def register_file(
        self,
        *,
        workspace_id: str,
        project_id: str | None,
        user_id: str,
        path: str | Path,
        kind: StudioAssetKind | None = None,
        filename: str | None = None,
        asset_id: str | None = None,
        execution_id: str | None = None,
        tool_call_id: str | None = None,
        source_version_ids: list[str] | None = None,
        relation_type: str = "derived_from",
    ) -> StudioAssetRef:
        source = Path(path).expanduser().resolve()
        resolved_name = filename or source.name
        mime_type = mimetypes.guess_type(resolved_name)[0] or "application/octet-stream"
        resolved_kind = kind or _kind_for_mime_or_name(mime_type, resolved_name)
        if resolved_kind is None:
            raise ValueError(f"Unsupported media type: {resolved_name}")
        return self._record_version(
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
            source_path=source,
            kind=resolved_kind,
            filename=resolved_name,
            mime_type=mime_type,
            asset_id=asset_id,
            execution_id=execution_id,
            tool_call_id=tool_call_id,
            source_version_ids=source_version_ids,
            relation_type=relation_type,
        )

    def register_source(
        self,
        *,
        workspace_id: str,
        project_id: str | None,
        user_id: str,
        source: str,
        kind: StudioAssetKind | None = None,
        filename: str | None = None,
        asset_id: str | None = None,
        execution_id: str | None = None,
        tool_call_id: str | None = None,
        source_version_ids: list[str] | None = None,
        relation_type: str = "derived_from",
    ) -> StudioAssetRef:
        if source.startswith("data:"):
            header, encoded = source.split(",", 1)
            mime_type = header[5:].split(";", 1)[0] or "application/octet-stream"
            content = base64.b64decode(encoded) if ";base64" in header else encoded.encode()
            resolved_kind = kind or _kind_for_mime_or_name(mime_type, filename or "asset")
            if resolved_kind is None:
                raise ValueError("Unsupported data URL media type")
            extension = mimetypes.guess_extension(mime_type) or ".bin"
            return self.register_bytes(
                workspace_id=workspace_id,
                project_id=project_id,
                user_id=user_id,
                content=content,
                filename=filename or f"asset{extension}",
                kind=resolved_kind,
                mime_type=mime_type,
                asset_id=asset_id,
                execution_id=execution_id,
                tool_call_id=tool_call_id,
                source_version_ids=source_version_ids,
                relation_type=relation_type,
            )
        if source.startswith(("http://", "https://")):
            with httpx.stream("GET", source, follow_redirects=True, timeout=90) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0]
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_REMOTE_ASSET_BYTES:
                        raise ValueError("Remote asset exceeds the 250 MB ingest limit")
                    chunks.append(chunk)
            remote_name = filename or Path(httpx.URL(source).path).name or "asset.bin"
            resolved_kind = kind or _kind_for_mime_or_name(content_type, remote_name)
            if resolved_kind is None:
                raise ValueError(f"Unsupported remote media type: {content_type or remote_name}")
            return self.register_bytes(
                workspace_id=workspace_id,
                project_id=project_id,
                user_id=user_id,
                content=b"".join(chunks),
                filename=remote_name,
                kind=resolved_kind,
                mime_type=content_type or None,
                asset_id=asset_id,
                execution_id=execution_id,
                tool_call_id=tool_call_id,
                source_version_ids=source_version_ids,
                relation_type=relation_type,
            )
        return self.register_file(
            workspace_id=workspace_id,
            project_id=project_id,
            user_id=user_id,
            path=source,
            kind=kind,
            filename=filename,
            asset_id=asset_id,
            execution_id=execution_id,
            tool_call_id=tool_call_id,
            source_version_ids=source_version_ids,
            relation_type=relation_type,
        )

    def create_execution(
        self,
        *,
        workspace_id: str,
        project_id: str | None,
        user_id: str,
        prompt: str,
        execution_id: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_workspace(workspace_id, user_id)
        if project_id:
            self.require_project(workspace_id, project_id)
        resolved_id = execution_id or uuid.uuid4().hex
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO executions(id, workspace_id, project_id, created_by, prompt, status, "
                "message, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?)",
                (
                    resolved_id,
                    workspace_id,
                    project_id,
                    user_id,
                    prompt,
                    "Agent job queued.",
                    now,
                    now,
                ),
            )
        return self.get_execution(workspace_id, resolved_id)  # type: ignore[return-value]

    def update_execution(
        self,
        workspace_id: str,
        execution_id: str,
        *,
        status: str,
        message: str,
        result: dict[str, Any] | None = None,
        error_type: str | None = None,
    ) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE executions SET status = ?, message = ?, result_json = COALESCE(?, result_json), "
                "error_type = ?, updated_at = ? WHERE id = ? AND workspace_id = ?",
                (
                    status,
                    message,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    error_type,
                    _now(),
                    execution_id,
                    workspace_id,
                ),
            )
        if cursor.rowcount == 0:
            raise KeyError("Execution not found")

    def append_tool_call(
        self,
        *,
        workspace_id: str,
        execution_id: str,
        event: dict[str, Any],
    ) -> None:
        now = _now()
        with self._connect() as connection:
            owned = connection.execute(
                "SELECT 1 FROM executions WHERE id = ? AND workspace_id = ?",
                (execution_id, workspace_id),
            ).fetchone()
            if not owned:
                raise KeyError("Execution not found")
            connection.execute(
                "INSERT OR REPLACE INTO tool_calls(id, execution_id, workspace_id, name, label, "
                "provider, provider_job_id, status, summary, result_json, output_versions_json, "
                "created_at, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(event.get("id") or uuid.uuid4().hex),
                    execution_id,
                    workspace_id,
                    str(event.get("name") or "tool"),
                    str(event.get("label") or "Tool"),
                    event.get("provider"),
                    event.get("provider_job_id"),
                    str(event.get("status") or "completed"),
                    str(event.get("summary") or "")[:1000],
                    json.dumps(
                        {
                            "_format": "renderhaus.tool_call.v1",
                            "arguments": event.get("arguments") or {},
                            "result": event.get("result") or {},
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(event.get("assets") or [], ensure_ascii=False),
                    int(event.get("created_at") or now),
                    int(event.get("completed_at") or now),
                ),
            )
            connection.execute(
                "UPDATE executions SET updated_at = ? WHERE id = ? AND workspace_id = ?",
                (now, execution_id, workspace_id),
            )

    def _tool_calls(self, connection: sqlite3.Connection, execution_id: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT * FROM tool_calls WHERE execution_id = ? ORDER BY created_at, rowid",
            (execution_id,),
        ).fetchall()
        calls: list[dict[str, Any]] = []
        for row in rows:
            stored = json.loads(row["result_json"] or "{}")
            wrapped = (
                isinstance(stored, dict)
                and stored.get("_format") == "renderhaus.tool_call.v1"
            )
            arguments = stored.get("arguments") if wrapped else {}
            calls.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "label": row["label"],
                    "provider": row["provider"],
                    "provider_job_id": row["provider_job_id"],
                    "status": row["status"],
                    "summary": row["summary"],
                    "arguments": arguments if isinstance(arguments, dict) else {},
                    "assets": json.loads(row["output_versions_json"] or "[]"),
                    "created_at": row["created_at"],
                    "completed_at": row["completed_at"],
                }
            )
        return calls

    def get_execution(self, workspace_id: str, execution_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM executions WHERE id = ? AND workspace_id = ?",
                (execution_id, workspace_id),
            ).fetchone()
            if row is None:
                return None
            calls = self._tool_calls(connection, execution_id)
        result = json.loads(row["result_json"]) if row["result_json"] else None
        return {
            "job_id": row["id"],
            "project_id": row["project_id"],
            "prompt": row["prompt"],
            "status": row["status"],
            "message": row["message"],
            "result": result,
            "tool_calls": calls,
            "error_type": row["error_type"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_executions(
        self,
        workspace_id: str,
        *,
        limit: int = 50,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            capped_limit = max(1, min(limit, 100))
            if project_id:
                rows = connection.execute(
                    "SELECT id FROM executions WHERE workspace_id = ? AND project_id = ? "
                    "ORDER BY updated_at DESC, rowid DESC LIMIT ?",
                    (workspace_id, project_id, capped_limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id FROM executions WHERE workspace_id = ? "
                    "ORDER BY updated_at DESC, rowid DESC LIMIT ?",
                    (workspace_id, capped_limit),
                ).fetchall()
        return [
            execution
            for row in rows
            if (execution := self.get_execution(workspace_id, str(row["id"]))) is not None
        ]


repository = StudioRepository()
