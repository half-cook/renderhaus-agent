"""Durable, workspace-scoped state for the Renderhaus Studio canvas.

SQLite is the local development adapter.  The schema deliberately mirrors the
Postgres shape used in production: logical assets, immutable asset versions,
provenance relations, executions, and tool calls are separate records.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
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

logger = logging.getLogger(__name__)


StudioAssetKind = Literal["image", "video", "audio"]
MAX_REMOTE_ASSET_BYTES = 250 * 1024 * 1024


class CanvasConflictError(RuntimeError):
    pass


class InsufficientBalanceError(ValueError):
    """Raised by charge_usage/adjust_balance when neither bucket can cover
    the cost. Subclasses ValueError so existing `except ValueError` call
    sites keep working; daily_remaining_cents/wallet_cents let a caller
    build a richer message when it wants to."""

    def __init__(self, message: str, *, daily_remaining_cents: int = 0, wallet_cents: int = 0) -> None:
        super().__init__(message)
        self.daily_remaining_cents = daily_remaining_cents
        self.wallet_cents = wallet_cents


@dataclass(frozen=True, slots=True)
class UsageCharge:
    daily_cents: int
    wallet_cents: int
    charge_date: str  # UTC 'YYYY-MM-DD' the daily_cents portion was deducted against

    @property
    def total_cents(self) -> int:
        return self.daily_cents + self.wallet_cents


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


def _today_utc() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


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

                    CREATE TABLE IF NOT EXISTS agent_conversations (
                        id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                        project_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'active'
                            CHECK(status IN ('active', 'archived')),
                        created_by TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL,
                        FOREIGN KEY(workspace_id, project_id)
                            REFERENCES projects(workspace_id, id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS agent_conversations_project_updated
                        ON agent_conversations(workspace_id, project_id, status, updated_at DESC);

                    CREATE TABLE IF NOT EXISTS agent_session_items (
                        conversation_id TEXT NOT NULL
                            REFERENCES agent_conversations(id) ON DELETE CASCADE,
                        sequence INTEGER NOT NULL,
                        item_json TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        PRIMARY KEY(conversation_id, sequence)
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
                        autonomous INTEGER NOT NULL DEFAULT 0,
                        request_json TEXT,
                        run_state_json TEXT,
                        approvals_json TEXT,
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

                    CREATE TABLE IF NOT EXISTS accounts (
                        user_id TEXT PRIMARY KEY,
                        balance_cents INTEGER NOT NULL DEFAULT 0,
                        stripe_customer_id TEXT,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS credit_ledger (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL REFERENCES accounts(user_id),
                        delta INTEGER NOT NULL,
                        reason TEXT NOT NULL,
                        reference_id TEXT,
                        created_at INTEGER NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS credit_ledger_user_created
                        ON credit_ledger(user_id, created_at DESC);
                    -- Idempotency for anything with a durable external reference
                    -- (a Stripe event id, an asset version id): a retried Stripe
                    -- webhook delivery reuses the same event id, so the second
                    -- INSERT collides here instead of crediting the balance
                    -- twice. NULL reference_id (most "generation" spends) never
                    -- conflicts -- SQLite treats every NULL as distinct.
                    CREATE UNIQUE INDEX IF NOT EXISTS credit_ledger_reference_unique
                        ON credit_ledger(reference_id) WHERE reference_id IS NOT NULL;

                    CREATE TABLE IF NOT EXISTS agent_events (
                        id TEXT NOT NULL,
                        execution_id TEXT NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
                        workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                        type TEXT NOT NULL,
                        title TEXT NOT NULL,
                        message TEXT NOT NULL,
                        status TEXT NOT NULL,
                        tool_call_id TEXT,
                        tool_call_name TEXT,
                        created_at INTEGER NOT NULL,
                        PRIMARY KEY(execution_id, id)
                    );
                    CREATE INDEX IF NOT EXISTS agent_events_execution_created
                        ON agent_events(execution_id, created_at);

                    -- One row per user with an active or past subscription.
                    -- Kept separate from `accounts` so every wallet-only code
                    -- path above (ensure_account, adjust_balance, the top-up
                    -- webhook) stays unaware subscriptions exist at all.
                    CREATE TABLE IF NOT EXISTS subscriptions (
                        user_id TEXT PRIMARY KEY REFERENCES accounts(user_id),
                        stripe_subscription_id TEXT,
                        plan_id TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'none'
                            CHECK(status IN ('active','past_due','canceled','none')),
                        monthly_budget_cents INTEGER NOT NULL DEFAULT 0,
                        daily_allowance_cents INTEGER NOT NULL DEFAULT 0,
                        daily_allowance_used_cents INTEGER NOT NULL DEFAULT 0,
                        daily_allowance_reset_date TEXT NOT NULL DEFAULT '',
                        current_period_end INTEGER,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL
                    );
                    CREATE UNIQUE INDEX IF NOT EXISTS subscriptions_stripe_subscription_unique
                        ON subscriptions(stripe_subscription_id) WHERE stripe_subscription_id IS NOT NULL;

                    -- Append-only log of subscription-covered spend. Kept
                    -- separate from credit_ledger: credit_ledger.delta always
                    -- mirrors an actual balance_cents change (that invariant
                    -- backs its Stripe-idempotency unique index), and daily
                    -- allowance spend never touches balance_cents.
                    CREATE TABLE IF NOT EXISTS usage_events (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL REFERENCES accounts(user_id),
                        daily_cents INTEGER NOT NULL,
                        wallet_cents INTEGER NOT NULL,
                        reason TEXT NOT NULL,
                        created_at INTEGER NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS usage_events_user_created
                        ON usage_events(user_id, created_at DESC);

                    -- A refund obligation recorded *before* it's applied, so
                    -- a failure partway through refund_usage (a transient
                    -- DB/contention issue, not a design case) leaves a row
                    -- flush_pending_refunds can find and finish later,
                    -- instead of the debit being silently lost the way a
                    -- pure best-effort call-and-log would lose it.
                    CREATE TABLE IF NOT EXISTS pending_refunds (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL REFERENCES accounts(user_id),
                        daily_cents INTEGER NOT NULL,
                        wallet_cents INTEGER NOT NULL,
                        charge_date TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        created_at INTEGER NOT NULL,
                        resolved_at INTEGER
                    );
                    CREATE INDEX IF NOT EXISTS pending_refunds_unresolved
                        ON pending_refunds(user_id) WHERE resolved_at IS NULL;

                    -- One in-flight subscription-checkout claim per user, so
                    -- two concurrent /subscribe calls (double-click, two
                    -- tabs) can't both create a Stripe subscription before
                    -- either webhook lands. created_at is a claim timestamp,
                    -- not a Stripe session id -- see claim_pending_subscription_checkout.
                    CREATE TABLE IF NOT EXISTS pending_subscription_checkouts (
                        user_id TEXT PRIMARY KEY REFERENCES accounts(user_id),
                        created_at INTEGER NOT NULL
                    );
                    """
                )
                execution_columns = {
                    str(row[1]) for row in connection.execute("PRAGMA table_info(executions)")
                }
                if "conversation_id" not in execution_columns:
                    connection.execute("ALTER TABLE executions ADD COLUMN conversation_id TEXT")
                if "turn_index" not in execution_columns:
                    connection.execute("ALTER TABLE executions ADD COLUMN turn_index INTEGER")
                if "autonomous" not in execution_columns:
                    connection.execute(
                        "ALTER TABLE executions ADD COLUMN autonomous INTEGER NOT NULL DEFAULT 0"
                    )
                if "request_json" not in execution_columns:
                    connection.execute("ALTER TABLE executions ADD COLUMN request_json TEXT")
                if "run_state_json" not in execution_columns:
                    connection.execute("ALTER TABLE executions ADD COLUMN run_state_json TEXT")
                if "approvals_json" not in execution_columns:
                    connection.execute("ALTER TABLE executions ADD COLUMN approvals_json TEXT")
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS executions_conversation_turn "
                    "ON executions(conversation_id, turn_index DESC)"
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

    @staticmethod
    def _conversation(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "project_id": str(row["project_id"]),
            "title": str(row["title"]),
            "status": str(row["status"]),
            "created_at": int(row["created_at"]),
            "updated_at": int(row["updated_at"]),
        }

    @staticmethod
    def _legacy_assistant_message(row: sqlite3.Row) -> str:
        result = json.loads(row["result_json"] or "{}")
        if not isinstance(result, dict):
            result = {}
        return str(
            result.get("markdown")
            or result.get("summary")
            or row["message"]
            or "The agent did not return a response."
        ).strip()

    def _ensure_default_conversation(
        self,
        connection: sqlite3.Connection,
        workspace_id: str,
        project_id: str,
        user_id: str,
    ) -> sqlite3.Row:
        existing = connection.execute(
            "SELECT * FROM agent_conversations WHERE workspace_id = ? AND project_id = ? "
            "AND status = 'active' ORDER BY updated_at DESC, rowid DESC LIMIT 1",
            (workspace_id, project_id),
        ).fetchone()
        if existing is not None:
            conversation_id = str(existing["id"])
        else:
            conversation_id = uuid.uuid4().hex
            now = _now()
            connection.execute(
                "INSERT INTO agent_conversations(id, workspace_id, project_id, title, status, "
                "created_by, created_at, updated_at) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)",
                (
                    conversation_id,
                    workspace_id,
                    project_id,
                    "Project conversation",
                    user_id,
                    now,
                    now,
                ),
            )

        legacy = connection.execute(
            "SELECT * FROM executions WHERE workspace_id = ? AND project_id = ? "
            "AND conversation_id IS NULL ORDER BY created_at, rowid",
            (workspace_id, project_id),
        ).fetchall()
        if legacy:
            next_turn = int(
                connection.execute(
                    "SELECT COALESCE(MAX(turn_index), 0) FROM executions WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()[0]
            )
            next_sequence = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sequence), -1) + 1 FROM agent_session_items "
                    "WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()[0]
            )
            for row in legacy:
                next_turn += 1
                connection.execute(
                    "UPDATE executions SET conversation_id = ?, turn_index = ? WHERE id = ?",
                    (conversation_id, next_turn, row["id"]),
                )
                prompt = str(row["prompt"] or "").strip()
                if row["status"] not in {"completed", "error"} or not prompt:
                    continue
                for item in (
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": self._legacy_assistant_message(row)},
                ):
                    connection.execute(
                        "INSERT INTO agent_session_items(conversation_id, sequence, item_json, "
                        "created_at) VALUES (?, ?, ?, ?)",
                        (
                            conversation_id,
                            next_sequence,
                            json.dumps(item, ensure_ascii=False),
                            int(row["updated_at"]),
                        ),
                    )
                    next_sequence += 1
            connection.execute(
                "UPDATE agent_conversations SET updated_at = ? WHERE id = ?",
                (max(int(row["updated_at"]) for row in legacy), conversation_id),
            )
        ensured = connection.execute(
            "SELECT * FROM agent_conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if ensured is None:  # pragma: no cover - the insert/select is atomic
            raise RuntimeError("Conversation creation did not produce a row")
        return ensured

    def list_conversations(
        self,
        workspace_id: str,
        project_id: str,
        user_id: str,
        *,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        self.ensure_workspace(workspace_id, user_id)
        self.require_project(workspace_id, project_id)
        with self._lock, self._connect() as connection:
            self._ensure_default_conversation(connection, workspace_id, project_id, user_id)
            query = "SELECT * FROM agent_conversations WHERE workspace_id = ? AND project_id = ?"
            parameters: list[Any] = [workspace_id, project_id]
            if not include_archived:
                query += " AND status = 'active'"
            query += " ORDER BY updated_at DESC, rowid DESC"
            rows = connection.execute(query, parameters).fetchall()
        return [self._conversation(row) for row in rows]

    def create_conversation(
        self,
        workspace_id: str,
        project_id: str,
        user_id: str,
        title: str = "New conversation",
    ) -> dict[str, Any]:
        self.ensure_workspace(workspace_id, user_id)
        self.require_project(workspace_id, project_id)
        conversation_id = uuid.uuid4().hex
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO agent_conversations(id, workspace_id, project_id, title, status, "
                "created_by, created_at, updated_at) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)",
                (
                    conversation_id,
                    workspace_id,
                    project_id,
                    title.strip()[:120] or "New conversation",
                    user_id,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM agent_conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        return self._conversation(row)

    def get_conversation(self, workspace_id: str, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM agent_conversations WHERE id = ? AND workspace_id = ?",
                (conversation_id, workspace_id),
            ).fetchone()
        return self._conversation(row) if row else None

    def update_conversation(
        self,
        workspace_id: str,
        conversation_id: str,
        *,
        title: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        if status is not None and status not in {"active", "archived"}:
            raise ValueError("Conversation status must be active or archived")
        updates = ["updated_at = ?"]
        values: list[Any] = [_now()]
        if title is not None:
            updates.append("title = ?")
            values.append(title.strip()[:120] or "New conversation")
        if status is not None:
            updates.append("status = ?")
            values.append(status)
        values.extend([conversation_id, workspace_id])
        with self._connect() as connection:
            cursor = connection.execute(
                f"UPDATE agent_conversations SET {', '.join(updates)} "
                "WHERE id = ? AND workspace_id = ?",
                values,
            )
            if cursor.rowcount == 0:
                raise KeyError("Conversation not found")
            row = connection.execute(
                "SELECT * FROM agent_conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        return self._conversation(row)

    def get_conversation_items(
        self, workspace_id: str, conversation_id: str
    ) -> list[dict[str, Any]]:
        if self.get_conversation(workspace_id, conversation_id) is None:
            raise KeyError("Conversation not found")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT item_json FROM agent_session_items WHERE conversation_id = ? "
                "ORDER BY sequence",
                (conversation_id,),
            ).fetchall()
        return [json.loads(str(row["item_json"])) for row in rows]

    def replace_conversation_items(
        self,
        workspace_id: str,
        conversation_id: str,
        items: list[dict[str, Any]],
    ) -> None:
        if self.get_conversation(workspace_id, conversation_id) is None:
            raise KeyError("Conversation not found")
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM agent_session_items WHERE conversation_id = ?", (conversation_id,)
            )
            connection.executemany(
                "INSERT INTO agent_session_items(conversation_id, sequence, item_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                [
                    (conversation_id, index, json.dumps(item, ensure_ascii=False), now)
                    for index, item in enumerate(items)
                ],
            )
            connection.execute(
                "UPDATE agent_conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )

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
                raise CanvasConflictError(
                    "Canvas changed in another session; reload before saving."
                )
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
        destination = (
            self.media_root
            / workspace_id.replace(":", "_")
            / resolved_asset_id
            / resolved_version_id
            / safe_name
        )
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
                destination = (
                    self.media_root
                    / workspace_id.replace(":", "_")
                    / resolved_asset_id
                    / resolved_version_id
                    / safe_name
                )
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
        temporary = (
            self.media_root
            / ".incoming"
            / f"{uuid.uuid4().hex}-{_safe_filename(filename, 'asset.bin')}"
        )
        temporary.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_bytes(content)
        try:
            resolved_mime = (
                mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
            )
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
        conversation_id: str | None = None,
        execution_id: str | None = None,
        autonomous: bool = False,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_workspace(workspace_id, user_id)
        if project_id:
            self.require_project(workspace_id, project_id)
        resolved_id = execution_id or uuid.uuid4().hex
        now = _now()
        with self._lock, self._connect() as connection:
            turn_index: int | None = None
            if conversation_id:
                conversation = connection.execute(
                    "SELECT status, title FROM agent_conversations WHERE id = ? AND workspace_id = ? "
                    "AND project_id = ?",
                    (conversation_id, workspace_id, project_id),
                ).fetchone()
                if conversation is None:
                    raise KeyError("Conversation not found")
                if conversation["status"] != "active":
                    raise ValueError("Archived conversations cannot accept new messages")
                active = connection.execute(
                    "SELECT 1 FROM executions WHERE conversation_id = ? "
                    "AND status IN ('queued', 'running', 'awaiting_approval') LIMIT 1",
                    (conversation_id,),
                ).fetchone()
                if active:
                    raise ValueError("This conversation already has an active agent run")
                turn_index = int(
                    connection.execute(
                        "SELECT COALESCE(MAX(turn_index), 0) + 1 FROM executions "
                        "WHERE conversation_id = ?",
                        (conversation_id,),
                    ).fetchone()[0]
                )
            connection.execute(
                "INSERT INTO executions(id, workspace_id, project_id, conversation_id, turn_index, "
                "created_by, prompt, status, message, autonomous, request_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)",
                (
                    resolved_id,
                    workspace_id,
                    project_id,
                    conversation_id,
                    turn_index,
                    user_id,
                    prompt,
                    "Agent job queued.",
                    1 if autonomous else 0,
                    json.dumps(request, ensure_ascii=False) if request is not None else None,
                    now,
                    now,
                ),
            )
            if conversation_id:
                title = str(conversation["title"])
                generated_title = " ".join(prompt.strip().split())[:60]
                connection.execute(
                    "UPDATE agent_conversations SET title = ?, updated_at = ? WHERE id = ?",
                    (
                        generated_title
                        if turn_index == 1
                        and title in {"New conversation", "Project conversation"}
                        and generated_title
                        else title,
                        now,
                        conversation_id,
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

    def pause_execution(
        self,
        workspace_id: str,
        execution_id: str,
        *,
        run_state: str,
        approvals: list[dict[str, Any]],
    ) -> None:
        if not run_state or not approvals:
            raise ValueError("A paused execution needs a run state and at least one approval.")
        now = _now()
        normalized = [{**item, "decision": None} for item in approvals]
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE executions SET status = 'awaiting_approval', message = ?, "
                "run_state_json = ?, approvals_json = ?, updated_at = ? "
                "WHERE id = ? AND workspace_id = ?",
                (
                    "Waiting for tool approval.",
                    run_state,
                    json.dumps(normalized, ensure_ascii=False),
                    now,
                    execution_id,
                    workspace_id,
                ),
            )
        if cursor.rowcount == 0:
            raise KeyError("Execution not found")

    def decide_execution_approval(
        self,
        workspace_id: str,
        execution_id: str,
        call_id: str,
        *,
        decision: str,
        message: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        if decision not in {"approve", "reject"}:
            raise ValueError("Approval decision must be approve or reject.")
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT status, approvals_json FROM executions WHERE id = ? AND workspace_id = ?",
                (execution_id, workspace_id),
            ).fetchone()
            if row is None:
                raise KeyError("Execution not found")
            if row["status"] != "awaiting_approval":
                raise ValueError("This execution is not waiting for approval.")
            approvals = json.loads(row["approvals_json"] or "[]")
            target = next(
                (item for item in approvals if str(item.get("call_id") or "") == call_id),
                None,
            )
            if target is None:
                raise KeyError("Approval request not found")
            if target.get("decision") is not None:
                raise ValueError("This tool call already has a decision.")
            target["decision"] = decision
            if message:
                target["message"] = message[:1_000]
            ready = bool(approvals) and all(item.get("decision") for item in approvals)
            connection.execute(
                "UPDATE executions SET status = ?, message = ?, approvals_json = ?, updated_at = ? "
                "WHERE id = ? AND workspace_id = ?",
                (
                    "queued" if ready else "awaiting_approval",
                    "Resuming the agent." if ready else "Waiting for tool approval.",
                    json.dumps(approvals, ensure_ascii=False),
                    _now(),
                    execution_id,
                    workspace_id,
                ),
            )
        execution = self.get_execution(workspace_id, execution_id)
        if execution is None:
            raise KeyError("Execution not found")
        return execution, ready

    def execution_checkpoint(
        self,
        workspace_id: str,
        execution_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT request_json, run_state_json, approvals_json, autonomous "
                "FROM executions WHERE id = ? AND workspace_id = ?",
                (execution_id, workspace_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "request": json.loads(row["request_json"] or "{}"),
            "run_state": str(row["run_state_json"] or ""),
            "approvals": json.loads(row["approvals_json"] or "[]"),
            "autonomous": bool(row["autonomous"]),
        }

    def clear_execution_checkpoint(self, workspace_id: str, execution_id: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE executions SET run_state_json = NULL, approvals_json = NULL "
                "WHERE id = ? AND workspace_id = ?",
                (execution_id, workspace_id),
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

    def _tool_calls(
        self, connection: sqlite3.Connection, execution_id: str
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT * FROM tool_calls WHERE execution_id = ? ORDER BY created_at, rowid",
            (execution_id,),
        ).fetchall()
        calls: list[dict[str, Any]] = []
        for row in rows:
            stored = json.loads(row["result_json"] or "{}")
            wrapped = (
                isinstance(stored, dict) and stored.get("_format") == "renderhaus.tool_call.v1"
            )
            arguments = stored.get("arguments") if wrapped else {}
            result = stored.get("result") if wrapped else stored
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
                    "result": result if isinstance(result, dict) else {},
                    "assets": json.loads(row["output_versions_json"] or "[]"),
                    "created_at": row["created_at"],
                    "completed_at": row["completed_at"],
                }
            )
        return calls

    def append_agent_event(
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
                "INSERT OR REPLACE INTO agent_events(id, execution_id, workspace_id, type, "
                "title, message, status, tool_call_id, tool_call_name, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(event.get("id") or uuid.uuid4().hex),
                    execution_id,
                    workspace_id,
                    str(event.get("type") or "STEP_STARTED"),
                    str(event.get("title") or "Agent update")[:200],
                    str(event.get("message") or "")[:2_000],
                    str(event.get("status") or "running"),
                    event.get("tool_call_id"),
                    event.get("tool_call_name"),
                    int(event.get("created_at") or now),
                ),
            )
            connection.execute(
                "UPDATE executions SET updated_at = ? WHERE id = ? AND workspace_id = ?",
                (now, execution_id, workspace_id),
            )

    def _agent_events(
        self, connection: sqlite3.Connection, execution_id: str
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT * FROM agent_events WHERE execution_id = ? ORDER BY created_at, rowid",
            (execution_id,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "type": row["type"],
                "title": row["title"],
                "message": row["message"],
                "status": row["status"],
                "tool_call_id": row["tool_call_id"],
                "tool_call_name": row["tool_call_name"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def get_execution(self, workspace_id: str, execution_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM executions WHERE id = ? AND workspace_id = ?",
                (execution_id, workspace_id),
            ).fetchone()
            if row is None:
                return None
            calls = self._tool_calls(connection, execution_id)
            events = self._agent_events(connection, execution_id)
        result = json.loads(row["result_json"]) if row["result_json"] else None
        approvals = json.loads(row["approvals_json"] or "[]")
        return {
            "job_id": row["id"],
            "project_id": row["project_id"],
            "conversation_id": row["conversation_id"],
            "turn_index": row["turn_index"],
            "prompt": row["prompt"],
            "status": row["status"],
            "message": row["message"],
            "autonomous": bool(row["autonomous"]),
            "approvals": approvals if isinstance(approvals, list) else [],
            "result": result,
            "tool_calls": calls,
            "events": events,
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
        conversation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            capped_limit = max(1, min(limit, 100))
            if conversation_id:
                rows = connection.execute(
                    "SELECT id FROM executions WHERE workspace_id = ? AND conversation_id = ? "
                    "ORDER BY turn_index DESC, updated_at DESC, rowid DESC LIMIT ?",
                    (workspace_id, conversation_id, capped_limit),
                ).fetchall()
            elif project_id:
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

    # -- Credits ----------------------------------------------------------
    # Scoped to user_id, not workspace_id: workspace_id can be an org (see
    # current_workspace_id in server/auth.py), and shared org billing is a
    # separate feature this doesn't build. Whoever clicks Generate spends
    # from their own personal balance, in any workspace.

    def ensure_account(self, user_id: str) -> None:
        now = _now()
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO accounts(user_id, balance_cents, created_at, updated_at) "
                "VALUES (?, 0, ?, ?)",
                (user_id, now, now),
            )

    def get_balance(self, user_id: str) -> int:
        self.ensure_account(user_id)
        self.flush_pending_refunds(user_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT balance_cents FROM accounts WHERE user_id = ?", (user_id,)
            ).fetchone()
        return int(row["balance_cents"]) if row else 0

    def _apply_balance_delta(self, connection: sqlite3.Connection, user_id: str, delta: int, now: int) -> None:
        """The atomic check-and-apply at the heart of adjust_balance and
        charge_usage's wallet leg. The UPDATE's WHERE clause makes it
        atomic against concurrent requests -- no separate read-then-write
        that a race could slip between."""
        cursor = connection.execute(
            "UPDATE accounts SET balance_cents = balance_cents + ?, updated_at = ? "
            "WHERE user_id = ? AND balance_cents + ? >= 0",
            (delta, now, user_id, delta),
        )
        if cursor.rowcount == 0:
            raise ValueError("Insufficient balance.")

    def adjust_balance(
        self,
        user_id: str,
        delta: int,
        reason: str,
        *,
        reference_id: str | None = None,
    ) -> int:
        """Apply `delta` (positive = grant/purchase, negative = spend) and
        log it to the ledger. Raises ValueError instead of ever letting a
        spend take the balance negative.

        When `reference_id` has already been recorded (e.g. a Stripe webhook
        redelivering the same event id), the ledger INSERT below raises
        sqlite3.IntegrityError against credit_ledger_reference_unique. That
        propagates out of the `with` block, so sqlite3 rolls back the UPDATE
        above along with it -- the balance ends up unchanged, and this
        reports it as a successful no-op instead of double-applying delta.
        """
        self.ensure_account(user_id)
        now = _now()
        try:
            with self._connect() as connection:
                self._apply_balance_delta(connection, user_id, delta, now)
                connection.execute(
                    "INSERT INTO credit_ledger(id, user_id, delta, reason, reference_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (uuid.uuid4().hex, user_id, delta, reason, reference_id, now),
                )
                row = connection.execute(
                    "SELECT balance_cents FROM accounts WHERE user_id = ?", (user_id,)
                ).fetchone()
            return int(row["balance_cents"])
        except sqlite3.IntegrityError:
            return self.get_balance(user_id)

    def charge_usage(self, user_id: str, cost_cents: int, reason: str) -> UsageCharge:
        """Debit `cost_cents`, drawing first from today's subscription daily
        allowance (if any active subscription), then covering any remainder
        from the top-up wallet. Raises InsufficientBalanceError if neither
        bucket can fully cover the cost -- nothing is written in that case.
        With no active subscription this degenerates to exactly
        adjust_balance(-cost_cents)'s existing behavior (same ValueError,
        same ledger row) -- the compatibility guarantee for every current
        top-up-only user.

        The daily-allowance leg uses optimistic compare-and-swap rather than
        a lock: this database is shared by two separate OS processes (the
        FastAPI server and the AgentCore agent runtime), so only a CAS retry
        against the stored row -- the same pattern save_canvas already uses
        for its `revision` column -- protects the read-compute-write
        sequence below from a concurrent charge on the same subscription.
        """
        self.ensure_account(user_id)
        self.flush_pending_refunds(user_id)
        today = _today_utc()
        with self._connect() as connection:
            sub = connection.execute(
                "SELECT status FROM subscriptions WHERE user_id = ?", (user_id,)
            ).fetchone()
        if not sub or sub["status"] != "active":
            self.adjust_balance(user_id, -cost_cents, reason)
            now = _now()
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO usage_events(id, user_id, daily_cents, wallet_cents, reason, created_at) "
                    "VALUES (?, ?, 0, ?, ?, ?)",
                    (uuid.uuid4().hex, user_id, -cost_cents, reason, now),
                )
            return UsageCharge(daily_cents=0, wallet_cents=cost_cents, charge_date=today)

        for _ in range(5):
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT daily_allowance_cents, daily_allowance_used_cents, daily_allowance_reset_date "
                    "FROM subscriptions WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                used_today = row["daily_allowance_used_cents"] if row["daily_allowance_reset_date"] == today else 0
                daily_remaining = max(0, row["daily_allowance_cents"] - used_today)
                daily_portion = min(cost_cents, daily_remaining)
                wallet_portion = cost_cents - daily_portion

                account = connection.execute(
                    "SELECT balance_cents FROM accounts WHERE user_id = ?", (user_id,)
                ).fetchone()
                wallet_balance = int(account["balance_cents"]) if account else 0
                if wallet_portion > wallet_balance:
                    raise InsufficientBalanceError(
                        f"Not enough balance: this generation costs ${cost_cents / 100:.2f}, "
                        f"you have ${daily_remaining / 100:.2f} left in today's plan allowance "
                        f"and ${wallet_balance / 100:.2f} in your wallet.",
                        daily_remaining_cents=daily_remaining,
                        wallet_cents=wallet_balance,
                    )

                now = _now()
                cursor = connection.execute(
                    "UPDATE subscriptions SET daily_allowance_used_cents = ?, daily_allowance_reset_date = ?, "
                    "updated_at = ? WHERE user_id = ? AND daily_allowance_used_cents = ? AND daily_allowance_reset_date = ?",
                    (
                        used_today + daily_portion,
                        today,
                        now,
                        user_id,
                        row["daily_allowance_used_cents"],
                        row["daily_allowance_reset_date"],
                    ),
                )
                if cursor.rowcount == 0:
                    # Lost a race with a concurrent charge on this same
                    # subscription (possibly from the other process) --
                    # retry with freshly-read state rather than fail the
                    # generation over a benign race.
                    continue
                if wallet_portion > 0:
                    self._apply_balance_delta(connection, user_id, -wallet_portion, now)
                    connection.execute(
                        "INSERT INTO credit_ledger(id, user_id, delta, reason, reference_id, created_at) "
                        "VALUES (?, ?, ?, ?, NULL, ?)",
                        (uuid.uuid4().hex, user_id, -wallet_portion, reason, now),
                    )
                connection.execute(
                    "INSERT INTO usage_events(id, user_id, daily_cents, wallet_cents, reason, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (uuid.uuid4().hex, user_id, daily_portion, wallet_portion, reason, now),
                )
            return UsageCharge(daily_cents=daily_portion, wallet_cents=wallet_portion, charge_date=today)
        raise RuntimeError("charge_usage: too much contention on this account's daily allowance.")

    def _apply_refund(self, user_id: str, charge: UsageCharge, reason: str) -> None:
        """The actual reversal of a charge_usage() result -- the part that
        can fail (a write against a busy/locked db). Split out of
        refund_usage() so that method can record the obligation durably
        before attempting this.

        The daily-side reversal only applies while `daily_allowance_reset_date`
        still matches charge.charge_date -- if the day has since rolled
        over, that day's bucket was already reset to zero, and crediting
        into today's fresh bucket would incorrectly inflate it. That case
        is a deliberate silent no-op: the user isn't harmed, they already
        got a full fresh allowance for the new day.
        """
        if charge.wallet_cents > 0:
            self.adjust_balance(user_id, charge.wallet_cents, reason)
        if charge.daily_cents > 0:
            now = _now()
            with self._connect() as connection:
                cursor = connection.execute(
                    "UPDATE subscriptions SET "
                    "daily_allowance_used_cents = MAX(0, daily_allowance_used_cents - ?), updated_at = ? "
                    "WHERE user_id = ? AND daily_allowance_reset_date = ?",
                    (charge.daily_cents, now, user_id, charge.charge_date),
                )
                if cursor.rowcount:
                    connection.execute(
                        "INSERT INTO usage_events(id, user_id, daily_cents, wallet_cents, reason, created_at) "
                        "VALUES (?, ?, ?, 0, ?, ?)",
                        (uuid.uuid4().hex, user_id, -charge.daily_cents, reason, now),
                    )

    def record_pending_refund(self, user_id: str, charge: UsageCharge, reason: str) -> str:
        """Durably records a refund obligation before attempting to apply
        it. Returns the new pending_refunds row id."""
        refund_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO pending_refunds"
                "(id, user_id, daily_cents, wallet_cents, charge_date, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (refund_id, user_id, charge.daily_cents, charge.wallet_cents, charge.charge_date, reason, _now()),
            )
        return refund_id

    def _claim_and_apply_pending_refund(
        self, user_id: str, refund_id: str, charge: UsageCharge, reason: str
    ) -> None:
        """Atomically claims one pending_refunds row before applying it, so
        refund_usage's own immediate attempt and a concurrently-triggered
        flush_pending_refunds (this app runs as two separate OS processes --
        the FastAPI server and the AgentCore agent -- sharing one SQLite
        file, so this isn't just an in-process race) can't both apply the
        same refund. The UPDATE's `WHERE resolved_at IS NULL` is the CAS:
        only the caller that flips it from NULL wins the right to apply.
        A failed apply reverts the claim (back to NULL) rather than leaving
        the row stuck "resolved" without ever actually crediting it.
        """
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE pending_refunds SET resolved_at = ? WHERE id = ? AND resolved_at IS NULL",
                (_now(), refund_id),
            )
            if cursor.rowcount == 0:
                return  # already claimed (and applied, or being applied) elsewhere
        try:
            self._apply_refund(user_id, charge, reason)
        except Exception:
            logger.exception("Could not apply pending refund %s for %s; left pending for later flush", refund_id, user_id)
            with self._connect() as connection:
                connection.execute("UPDATE pending_refunds SET resolved_at = NULL WHERE id = ?", (refund_id,))

    def flush_pending_refunds(self, user_id: str) -> None:
        """Best-effort: applies any refund obligations for this user that
        were recorded but never successfully applied. Called opportunistically
        from get_balance and charge_usage, so a refund that failed at
        refund_usage() time (a transient DB/contention issue) gets a real
        chance to complete on the user's very next balance read or charge,
        instead of staying lost until someone happens to notice."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, daily_cents, wallet_cents, charge_date, reason FROM pending_refunds "
                "WHERE user_id = ? AND resolved_at IS NULL",
                (user_id,),
            ).fetchall()
        for row in rows:
            charge = UsageCharge(
                daily_cents=row["daily_cents"], wallet_cents=row["wallet_cents"], charge_date=row["charge_date"]
            )
            self._claim_and_apply_pending_refund(user_id, row["id"], charge, row["reason"])

    def refund_usage(self, user_id: str, charge: UsageCharge, reason: str) -> None:
        """Reverse a charge_usage() result durably: the obligation is
        recorded (record_pending_refund) before it's applied, so if applying
        it fails right here, the obligation isn't lost -- flush_pending_refunds
        (wired into get_balance/charge_usage) finishes it on the user's next
        interaction instead. Only raises if even recording the obligation
        fails; a failure to apply it is caught and left pending."""
        refund_id = self.record_pending_refund(user_id, charge, reason)
        self._claim_and_apply_pending_refund(user_id, refund_id, charge, reason)

    def claim_pending_subscription_checkout(self, user_id: str, *, ttl_seconds: int = 24 * 3600) -> bool:
        """Atomically claims the one pending-checkout slot for this user, so
        two concurrent /subscribe calls (double-click, two tabs) can't both
        create a Stripe subscription before either webhook lands. Returns
        False if a still-fresh claim already exists; the caller should tell
        the user a checkout is already in progress rather than starting a
        second one. A claim older than ttl_seconds (Stripe Checkout Sessions
        themselves expire after 24h) is treated as abandoned and can be
        stolen by a fresh attempt.
        """
        self.ensure_account(user_id)
        now = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE pending_subscription_checkouts SET created_at = ? "
                "WHERE user_id = ? AND created_at < ?",
                (now, user_id, now - ttl_seconds),
            )
            if cursor.rowcount:
                return True
            try:
                connection.execute(
                    "INSERT INTO pending_subscription_checkouts(user_id, created_at) VALUES (?, ?)",
                    (user_id, now),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def release_pending_subscription_checkout(self, user_id: str) -> None:
        """Releases a claim taken by claim_pending_subscription_checkout
        without waiting for its TTL -- for when the checkout attempt itself
        never made it to Stripe (e.g. the Session.create call failed), so
        the user isn't locked out of retrying for up to 24h over an error
        that left no actual pending checkout behind."""
        with self._connect() as connection:
            connection.execute("DELETE FROM pending_subscription_checkouts WHERE user_id = ?", (user_id,))

    def sync_subscription(
        self,
        user_id: str,
        *,
        stripe_subscription_id: str | None,
        plan_id: str,
        status: str,
        monthly_budget_cents: int,
        current_period_end: int | None,
    ) -> bool:
        """Upsert subscription state from a Stripe webhook event. Does not
        touch daily_allowance_used_cents/daily_allowance_reset_date on an
        existing row -- a plan change updates the budget going forward
        only, with no attempt to prorate the current day's already-spent
        allowance.

        Returns False (a no-op) instead of applying the update when the
        user already has a *different*, still-live subscription on file.
        Stripe does not guarantee webhook delivery order, so a delayed
        event for a subscription that's since been superseded (canceled and
        replaced by a new one) must not be allowed to clobber the live one
        -- e.g. a late `customer.subscription.deleted` for the old
        subscription arriving after the new one's `created` event has
        already been applied. The caller (server/billing.py) additionally
        re-fetches the authoritative subscription object from Stripe before
        calling this, which handles the same-subscription-id ordering case
        (two events for the *same* id arriving out of order).
        """
        self.ensure_account(user_id)
        now = _now()
        daily_allowance_cents = monthly_budget_cents // 30 if status == "active" else 0
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT stripe_subscription_id, status FROM subscriptions WHERE user_id = ?", (user_id,)
            ).fetchone()
            if (
                existing
                and existing["stripe_subscription_id"] is not None
                and existing["stripe_subscription_id"] != stripe_subscription_id
                and existing["status"] in ("active", "past_due")
            ):
                logger.warning(
                    "Ignoring stale subscription event for %s: event subscription %s "
                    "does not match live subscription %s",
                    user_id,
                    stripe_subscription_id,
                    existing["stripe_subscription_id"],
                )
                return False
            connection.execute(
                "INSERT INTO subscriptions(user_id, stripe_subscription_id, plan_id, status, "
                "monthly_budget_cents, daily_allowance_cents, daily_allowance_used_cents, "
                "daily_allowance_reset_date, current_period_end, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "  stripe_subscription_id = excluded.stripe_subscription_id, "
                "  plan_id = excluded.plan_id, "
                "  status = excluded.status, "
                "  monthly_budget_cents = excluded.monthly_budget_cents, "
                "  daily_allowance_cents = excluded.daily_allowance_cents, "
                "  current_period_end = excluded.current_period_end, "
                "  updated_at = excluded.updated_at",
                (
                    user_id,
                    stripe_subscription_id,
                    plan_id,
                    status,
                    monthly_budget_cents,
                    daily_allowance_cents,
                    _today_utc(),
                    current_period_end,
                    now,
                    now,
                ),
            )
            # A definitive subscription event has now landed for this user
            # (successfully or as a cancellation) -- any earlier in-flight
            # checkout claim is resolved either way.
            connection.execute("DELETE FROM pending_subscription_checkouts WHERE user_id = ?", (user_id,))
        return True

    def get_subscription_state(self, user_id: str) -> dict[str, Any] | None:
        """Read-only peek at subscription state, applying the same lazy
        daily reset charge_usage does but without writing -- so a dashboard
        read after a day boundary shows the correct remaining allowance
        even before the next real charge persists a reset."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT plan_id, status, monthly_budget_cents, daily_allowance_cents, "
                "daily_allowance_used_cents, daily_allowance_reset_date, current_period_end "
                "FROM subscriptions WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if not row or row["status"] not in ("active", "past_due"):
            return None
        today = _today_utc()
        used_today = row["daily_allowance_used_cents"] if row["daily_allowance_reset_date"] == today else 0
        remaining = max(0, row["daily_allowance_cents"] - used_today)
        return {
            "plan_id": row["plan_id"],
            "status": row["status"],
            "monthly_budget_cents": row["monthly_budget_cents"],
            "daily_allowance_cents": row["daily_allowance_cents"],
            "daily_allowance_remaining_cents": remaining,
            "current_period_end": row["current_period_end"],
        }

    def list_ledger(self, user_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, delta, reason, reference_id, created_at FROM credit_ledger "
                "WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, max(1, min(limit, 100))),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "delta": row["delta"],
                "reason": row["reason"],
                "reference_id": row["reference_id"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def set_stripe_customer(self, user_id: str, stripe_customer_id: str) -> None:
        self.ensure_account(user_id)
        with self._connect() as connection:
            connection.execute(
                "UPDATE accounts SET stripe_customer_id = ?, updated_at = ? WHERE user_id = ?",
                (stripe_customer_id, _now(), user_id),
            )

    def get_stripe_customer(self, user_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT stripe_customer_id FROM accounts WHERE user_id = ?", (user_id,)
            ).fetchone()
        return row["stripe_customer_id"] if row else None


repository = StudioRepository()
