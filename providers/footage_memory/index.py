"""The shared, project-scoped video index. No model or media calls happen here."""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import re
import sqlite3
import struct
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = 2
EVENT_KINDS = frozenset({
    "dialogue", "sound", "on_screen_text", "moment", "person", "object", "location",
})
_SQL_DIR = Path(__file__).with_name("sql")
_MIGRATIONS = ("001_core.sql", "002_segment_edit.sql")
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def _number(value: Any, label: str, *, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def _milliseconds(value: Any) -> int:
    _number(value, "Timestamp")
    if not isinstance(value, int):
        raise ValueError("Timestamp must be an integer number of milliseconds")
    return value


def _path_key(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\\" in value or ":" in value:
        raise ValueError("Asset path must be a confined relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\x00" in value or path.as_posix() == ".":
        raise ValueError("Asset path must be a confined relative path")
    return path.as_posix()


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.casefold())


class VideoIndex:
    def __init__(self, db_path: Path, project_id: str, workspace_id: str = "local", *,
                 use_fts: bool = True):
        if not project_id or not workspace_id:
            raise ValueError("Project and workspace are required")
        self.project_id = project_id
        self.workspace_id = workspace_id
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.fts_available = False
        try:
            self._check_identity()
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError("Video index schema is newer than this application")
            for next_version in range(version + 1, SCHEMA_VERSION + 1):
                sql = (_SQL_DIR / _MIGRATIONS[next_version - 1]).read_text(encoding="utf-8")
                self.connection.executescript(
                    f"BEGIN IMMEDIATE;\n{sql}\nPRAGMA user_version={next_version};\nCOMMIT;"
                )
            with self.connection:
                self.connection.execute(
                    "INSERT OR IGNORE INTO index_meta(singleton,project_id,workspace_id) VALUES(1,?,?)",
                    self._scope,
                )
            self._check_identity()
            if use_fts:
                try:
                    self._create_fts()
                    self.fts_available = True
                except sqlite3.OperationalError:
                    self.connection.rollback()
                    for action in ("insert", "update", "delete"):
                        self.connection.execute(f"DROP TRIGGER IF EXISTS search_docs_fts_{action}")
                    self.connection.commit()
        except Exception:
            self.close()
            raise

    @property
    def _scope(self) -> tuple[str, str]:
        return self.project_id, self.workspace_id

    def __enter__(self) -> VideoIndex:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _check_identity(self) -> None:
        exists = self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='index_meta'"
        ).fetchone()
        if exists:
            row = self.connection.execute(
                "SELECT project_id,workspace_id FROM index_meta WHERE singleton=1"
            ).fetchone()
            if row and tuple(row) != self._scope:
                raise ValueError("Video index belongs to another project or workspace")

    def _id(self, kind: str, *parts: Any) -> str:
        payload = json.dumps([*self._scope, *parts], sort_keys=True, separators=(",", ":"))
        return f"fm_{kind}_{hashlib.sha256(payload.encode()).hexdigest()[:32]}"

    def _row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def _require_asset(self, asset_id: str) -> dict[str, Any]:
        asset = self.asset(asset_id)
        if asset is None:
            raise ValueError("Asset not found in this project")
        return asset

    def _window(self, window_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM windows WHERE id=? AND project_id=? AND workspace_id=?",
            (window_id, *self._scope),
        ).fetchone()
        if row is None:
            raise ValueError("Window not found in this project")
        return dict(row)

    def upsert_asset(self, *, content_hash: str, path_key: str, duration_s: float,
                     fps: float | None = None, asset_version_id: str | None = None) -> dict[str, Any]:
        duration_s = _number(duration_s, "Duration")
        if fps is not None:
            fps = _number(fps, "Frame rate", minimum=0.000001)
        path_key = _path_key(path_key)
        if not isinstance(content_hash, str) or not content_hash.strip():
            raise ValueError("Asset content hash is required")
        version = asset_version_id or ""
        if not isinstance(version, str):
            raise ValueError("Asset version must be text")
        asset_id = self._id("asset", content_hash, version)
        with self.connection:
            self.connection.execute(
                "INSERT INTO assets(id,project_id,workspace_id,content_hash,asset_version_id,"
                "path_key,duration_s,fps) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(project_id,workspace_id,content_hash,asset_version_id) "
                "DO UPDATE SET path_key=excluded.path_key",
                (asset_id, *self._scope, content_hash, version, path_key, duration_s, fps),
            )
        return self._require_asset(asset_id)

    def find_asset(self, content_hash: str, asset_version_id: str | None = None) -> dict[str, Any] | None:
        return self._row(self.connection.execute(
            "SELECT * FROM assets WHERE project_id=? AND workspace_id=? AND content_hash=? "
            "AND asset_version_id=?", (*self._scope, content_hash, asset_version_id or ""),
        ).fetchone())

    def asset(self, asset_id: str) -> dict[str, Any] | None:
        return self._row(self.connection.execute(
            "SELECT * FROM assets WHERE id=? AND project_id=? AND workspace_id=?",
            (asset_id, *self._scope),
        ).fetchone())

    def assets_for_path(self, path_key: str) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM assets WHERE path_key=? AND project_id=? AND workspace_id=? "
            "ORDER BY indexed_at DESC,id", (_path_key(path_key), *self._scope),
        )]

    def asset_by_path(self, path_key: str) -> dict[str, Any] | None:
        return next(iter(self.assets_for_path(path_key)), None)

    def windows(self, asset_id: str) -> list[dict[str, Any]]:
        self._require_asset(asset_id)
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM windows WHERE asset_id=? AND project_id=? AND workspace_id=? ORDER BY t0_ms,t1_ms,id",
            (asset_id, *self._scope),
        )]

    def prepare_window_layout(self, asset_id: str, windows: list[tuple[int, int]]) -> None:
        asset = self._require_asset(asset_id)
        requested = []
        for t0_ms, t1_ms in windows:
            t0_ms, t1_ms = _milliseconds(t0_ms), _milliseconds(t1_ms)
            if t0_ms >= t1_ms or t1_ms > round(asset["duration_s"] * 1000):
                raise ValueError("Window timestamps must stay within the asset")
            requested.append((t0_ms, t1_ms))
        requested.sort()
        covered_to = 0
        for t0_ms, t1_ms in requested:
            if t0_ms != covered_to:
                raise ValueError("Window layout must cover the asset without gaps or overlaps")
            covered_to = t1_ms
        if covered_to != round(asset["duration_s"] * 1000):
            raise ValueError("Window layout must cover the asset without gaps or overlaps")
        requested_set = set(requested)
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            asset = self._require_asset(asset_id)
            existing = self.windows(asset_id)
            if {(row["t0_ms"], row["t1_ms"]) for row in existing} == requested_set:
                return
            if asset["memory_version"] is not None:
                raise ValueError("A completed memory cannot change its window layout")
            for window in existing:
                if (window["t0_ms"], window["t1_ms"]) in requested_set:
                    continue
                self.connection.execute(
                    "DELETE FROM search_docs WHERE owner_kind='event' AND owner_id IN "
                    "(SELECT id FROM events WHERE window_id=? AND project_id=? AND workspace_id=?)",
                    (window["id"], *self._scope),
                )
                self.connection.execute(
                    "DELETE FROM windows WHERE id=? AND asset_id=? AND project_id=? AND workspace_id=?",
                    (window["id"], asset_id, *self._scope),
                )
            self.connection.execute(
                "UPDATE assets SET indexed_at=NULL,memory_version=NULL,hierarchy_json=NULL "
                "WHERE id=? AND project_id=? AND workspace_id=?", (asset_id, *self._scope),
            )

    def add_window(self, asset_id: str, t0_ms: int, t1_ms: int, status: str = "complete",
                   backend_ref: str | None = None) -> dict[str, Any]:
        asset = self._require_asset(asset_id)
        t0_ms, t1_ms = _milliseconds(t0_ms), _milliseconds(t1_ms)
        if t0_ms >= t1_ms or t1_ms > round(asset["duration_s"] * 1000):
            raise ValueError("Window timestamps must stay within the asset")
        if status not in {"pending", "complete", "failed"}:
            raise ValueError("Invalid window status")
        window_id = self._id("win", asset_id, t0_ms, t1_ms)
        with self.connection:
            self.connection.execute(
                "INSERT INTO windows(id,project_id,workspace_id,asset_id,t0_ms,t1_ms,status,backend_ref) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,"
                "backend_ref=excluded.backend_ref",
                (window_id, *self._scope, asset_id, t0_ms, t1_ms, status, backend_ref),
            )
            if status != "complete":
                self.connection.execute("UPDATE assets SET indexed_at=NULL,memory_version=NULL,hierarchy_json=NULL WHERE id=?",
                                        (asset_id,))
        return self._window(window_id)

    def _normalize_event(self, window: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        kind = event.get("kind")
        if kind not in EVENT_KINDS:
            raise ValueError("Invalid event kind")
        t0, t1 = _milliseconds(event.get("t0_ms")), _milliseconds(event.get("t1_ms"))
        if t0 < window["t0_ms"] or t1 > window["t1_ms"] or t0 > t1:
            raise ValueError("Event timestamps must stay within the window")
        text = event.get("text", "")
        if not isinstance(text, str):
            raise ValueError("Event text must be text")
        confidence = _number(event.get("confidence", 0.5), "Confidence")
        if confidence > 1:
            raise ValueError("Confidence must be between zero and one")
        attrs = event.get("attrs", event.get("attrs_json", {}))
        if isinstance(attrs, str):
            attrs = json.loads(attrs)
        if not isinstance(attrs, dict):
            raise ValueError("Event attributes must be an object")
        attrs = dict(attrs)
        attrs.pop("verification", None)
        attrs_json = json.dumps(attrs, sort_keys=True, separators=(",", ":"), allow_nan=False)
        speaker = event.get("speaker", event.get("speaker_label"))
        if speaker is not None and (not isinstance(speaker, str) or not speaker.strip()):
            raise ValueError("Speaker label must be text")
        speaker_id = event.get("speaker_id")
        if speaker_id:
            row = self.connection.execute(
                "SELECT label FROM speakers WHERE id=? AND asset_id=? AND project_id=? AND workspace_id=?",
                (speaker_id, window["asset_id"], *self._scope),
            ).fetchone()
            if row is None and not speaker:
                raise ValueError("Speaker not found in this asset")
            if row is not None:
                speaker = row[0]
        if speaker:
            speaker_id = self._id("spk", window["asset_id"], speaker)
        return {"kind": kind, "t0_ms": t0, "t1_ms": t1, "text": text,
                "confidence": confidence, "attrs_json": attrs_json, "speaker": speaker,
                "speaker_id": speaker_id or None}

    def replace_window_events(self, window_id: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        window = self._window(window_id)
        normalized = [self._normalize_event(window, event) for event in events]
        asset = self._require_asset(window["asset_id"])
        event_ids = []
        with self.connection:
            self.connection.execute(
                "DELETE FROM search_docs WHERE owner_kind='event' AND owner_id IN "
                "(SELECT id FROM events WHERE window_id=? AND project_id=? AND workspace_id=?)",
                (window_id, *self._scope),
            )
            self.connection.execute("DELETE FROM events WHERE window_id=? AND project_id=? AND workspace_id=?",
                                    (window_id, *self._scope))
            for ordinal, event in enumerate(normalized):
                if event["speaker_id"]:
                    self.connection.execute(
                        "INSERT OR IGNORE INTO speakers(id,project_id,workspace_id,asset_id,label) VALUES(?,?,?,?,?)",
                        (event["speaker_id"], *self._scope, window["asset_id"], event["speaker"]),
                    )
                event_id = self._id("evt", window_id, ordinal, event)
                event_ids.append(event_id)
                self.connection.execute(
                    "INSERT INTO events(id,project_id,workspace_id,asset_id,window_id,kind,t0_ms,t1_ms,"
                    "speaker_id,text,confidence,attrs_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (event_id, *self._scope, window["asset_id"], window_id, event["kind"], event["t0_ms"],
                     event["t1_ms"], event["speaker_id"], event["text"], event["confidence"], event["attrs_json"]),
                )
                self.connection.execute(
                    "INSERT INTO search_docs(id,project_id,workspace_id,asset_id,asset_version_id,"
                    "owner_kind,owner_id,text,fts) VALUES(?,?,?,?,?,'event',?,?,?)",
                    (self._id("doc", event_id), *self._scope, window["asset_id"], asset["asset_version_id"],
                     event_id, event["text"], " ".join(_tokens(event["text"]))),
                )
            self.connection.execute("UPDATE assets SET indexed_at=NULL,memory_version=NULL,hierarchy_json=NULL WHERE id=?",
                                    (window["asset_id"],))
        return [self.event(event_id) for event_id in event_ids]

    def mark_complete(self, asset_id: str, memory_version: str) -> None:
        asset = self._require_asset(asset_id)
        windows = self.windows(asset_id)
        covered_to = 0
        for window in windows:
            if window["status"] != "complete" or window["t0_ms"] > covered_to:
                raise ValueError("Memory is incomplete")
            covered_to = max(covered_to, window["t1_ms"])
        if covered_to < round(asset["duration_s"] * 1000):
            raise ValueError("Memory is incomplete")
        if not isinstance(memory_version, str) or not memory_version:
            raise ValueError("Memory version is required")
        with self.connection:
            self.connection.execute(
                "UPDATE assets SET indexed_at=?,memory_version=?,hierarchy_json=? WHERE id=? AND project_id=? AND workspace_id=?",
                (datetime.now(timezone.utc).isoformat(), memory_version,
                 json.dumps(self.hierarchy(asset_id), sort_keys=True), asset_id, *self._scope),
            )

    def event(self, event_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT e.*,s.label AS speaker FROM events e LEFT JOIN speakers s ON s.id=e.speaker_id "
            "AND s.asset_id=e.asset_id AND s.project_id=e.project_id AND s.workspace_id=e.workspace_id "
            "WHERE e.id=? AND e.project_id=? AND e.workspace_id=?", (event_id, *self._scope),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["attrs"] = json.loads(result["attrs_json"])
        return result

    def verify_event(self, event_id: str, verdict: str, t0_ms: int, t1_ms: int) -> None:
        event = self.event(event_id)
        if event is None:
            raise ValueError("Moment not found in this project")
        if verdict not in {"verified", "refuted", "ambiguous"}:
            raise ValueError("Invalid verification result")
        t0, t1 = _milliseconds(t0_ms), _milliseconds(t1_ms)
        asset = self._require_asset(event["asset_id"])
        if t1 > round(asset["duration_s"] * 1000) or t0 > t1:
            raise ValueError("Verification timestamps must stay within the asset")
        attrs = event["attrs"]
        attrs["verification"] = {"verdict": verdict, "t0_ms": t0, "t1_ms": t1}
        with self.connection:
            self.connection.execute("UPDATE events SET attrs_json=? WHERE id=? AND project_id=? AND workspace_id=?",
                                    (json.dumps(attrs, sort_keys=True), event_id, *self._scope))

    def _create_fts(self) -> None:
        self.connection.executescript("""
            BEGIN IMMEDIATE;
            CREATE VIRTUAL TABLE IF NOT EXISTS search_docs_fts USING fts5(
                id UNINDEXED, project_id UNINDEXED, workspace_id UNINDEXED, text
            );
            CREATE TRIGGER IF NOT EXISTS search_docs_fts_insert AFTER INSERT ON search_docs BEGIN
                INSERT INTO search_docs_fts(id,project_id,workspace_id,text)
                    VALUES(new.id,new.project_id,new.workspace_id,new.fts);
            END;
            CREATE TRIGGER IF NOT EXISTS search_docs_fts_update AFTER UPDATE ON search_docs BEGIN
                DELETE FROM search_docs_fts WHERE id=old.id;
                INSERT INTO search_docs_fts(id,project_id,workspace_id,text)
                    VALUES(new.id,new.project_id,new.workspace_id,new.fts);
            END;
            CREATE TRIGGER IF NOT EXISTS search_docs_fts_delete AFTER DELETE ON search_docs BEGIN
                DELETE FROM search_docs_fts WHERE id=old.id;
            END;
            DELETE FROM search_docs_fts;
            INSERT INTO search_docs_fts(id,project_id,workspace_id,text)
                SELECT id,project_id,workspace_id,fts FROM search_docs;
            COMMIT;
        """)
        self.connection.commit()

    def query(self, query: str, scope: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("Result limit must be between one and 100")
        if not isinstance(query, str) or len(query) > 2000:
            raise ValueError("Search question must be text of at most 2000 characters")
        tokens = sorted(set(_tokens(query)))[:64]
        if not tokens:
            return []
        parameters: list[Any] = [*self._scope]
        conditions = ("e.project_id=? AND e.workspace_id=? AND a.memory_version IS NOT NULL "
                      "AND w.status='complete'")
        if scope is not None:
            conditions += " AND e.asset_id=?"
            parameters.append(scope)
        candidates = ""
        if self.fts_available:
            candidates = (" AND d.id IN (SELECT id FROM search_docs_fts WHERE search_docs_fts MATCH ? "
                          "AND project_id=? AND workspace_id=?)")
            parameters.extend([" OR ".join(f'"{token}"' for token in tokens), *self._scope])
        else:
            candidates = " AND (" + " OR ".join("d.fts LIKE ?" for _ in tokens) + ")"
            parameters.extend(f"%{token}%" for token in tokens)
        rows = self.connection.execute(
            "SELECT e.*,s.label AS speaker FROM events e JOIN assets a ON a.id=e.asset_id "
            "JOIN windows w ON w.id=e.window_id AND w.asset_id=e.asset_id "
            "AND w.project_id=e.project_id AND w.workspace_id=e.workspace_id "
            "JOIN search_docs d ON d.owner_kind='event' AND d.owner_id=e.id "
            "AND d.project_id=e.project_id AND d.workspace_id=e.workspace_id "
            "LEFT JOIN speakers s ON s.id=e.speaker_id AND s.asset_id=e.asset_id "
            f"WHERE {conditions}{candidates}", parameters,
        ).fetchall()
        hits = []
        for row in rows:
            counts = Counter(_tokens(row["text"]))
            matched = sum(token in counts for token in tokens)
            if not matched:
                continue
            score = 10 * matched / len(tokens) + sum(counts[token] for token in tokens) / max(sum(counts.values()), 1)
            hits.append({"hit_id": row["id"], "clip_id": row["asset_id"],
                         "t0_s": row["t0_ms"] / 1000, "t1_s": row["t1_ms"] / 1000,
                         "speaker": row["speaker"], "snippet": row["text"], "kind": row["kind"],
                         "score": round(score, 6), "confidence": row["confidence"], "verify_required": True})
        hits.sort(key=lambda hit: (-hit["score"], hit["clip_id"], hit["t0_s"], hit["hit_id"]))
        return hits[:limit]

    def hierarchy(self, asset_id: str) -> dict[str, Any]:
        asset = self._require_asset(asset_id)
        duration_ms = round(asset["duration_s"] * 1000)
        events = [dict(row) for row in self.connection.execute(
            "SELECT id,kind,t0_ms,t1_ms,speaker_id FROM events WHERE asset_id=? "
            "AND project_id=? AND workspace_id=? ORDER BY t0_ms,id", (asset_id, *self._scope),
        )]
        macro_count = max(1, math.ceil(duration_ms / 480000))
        macros = []
        for i in range(macro_count):
            t0, t1 = duration_ms * i // macro_count, duration_ms * (i + 1) // macro_count
            members = [event for event in events if t0 <= event["t0_ms"] < t1 or
                       (i == macro_count - 1 and event["t0_ms"] == t1)]
            macros.append({"id": self._id("macro", asset_id, i), "kind": "MacroEvent",
                           "t0_ms": t0, "t1_ms": t1,
                           "subgraph": {"kind": "Subgraph", "event_ids": [e["id"] for e in members],
                                        "speaker_ids": sorted({e["speaker_id"] for e in members if e["speaker_id"]}),
                                        "entity_event_ids": [e["id"] for e in members if e["kind"] in
                                                             {"person", "object", "location"}]}})
        supers = [{"id": self._id("super", asset_id, i // 4), "kind": "SuperEvent",
                   "t0_ms": group[0]["t0_ms"], "t1_ms": group[-1]["t1_ms"], "children": group}
                  for i in range(0, len(macros), 4) if (group := macros[i:i + 4])]
        return {"id": self._id("root", asset_id), "kind": "Root", "project_id": self.project_id,
                "workspace_id": self.workspace_id, "asset_id": asset_id, "children": supers,
                "derived": True, "verify_required": True}

    def add_embedding(self, *, asset_id: str, owner_kind: str, owner_id: str, t_ms: int,
                      vector: list[float], model_ref: str) -> dict[str, Any]:
        asset = self._require_asset(asset_id)
        t_ms = _milliseconds(t_ms)
        if t_ms > round(asset["duration_s"] * 1000) or not 1 <= len(vector) <= 100000:
            raise ValueError("Invalid embedding dimensions or timestamp")
        values = []
        for value in vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Embedding values must be finite numbers")
            values.append(float(value))
        try:
            blob = struct.pack(f"<{len(values)}f", *values)
        except OverflowError as exc:
            raise ValueError("Embedding values must fit float32") from exc
        embedding_id = self._id("emb", asset_id, owner_kind, owner_id, model_ref)
        with self.connection:
            self.connection.execute(
                "INSERT INTO embeddings(id,project_id,workspace_id,owner_kind,owner_id,asset_id,"
                "asset_version_id,t_ms,dim,vec,model_ref) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET vec=excluded.vec,dim=excluded.dim,t_ms=excluded.t_ms",
                (embedding_id, *self._scope, owner_kind, owner_id, asset_id, asset["asset_version_id"],
                 t_ms, len(values), blob, model_ref),
            )
        return dict(self.connection.execute("SELECT * FROM embeddings WHERE id=?", (embedding_id,)).fetchone())

    def install_vec_adapter(self, dim: int) -> bool:
        if not isinstance(dim, int) or isinstance(dim, bool) or not 1 <= dim <= 100000:
            raise ValueError("Vector dimensions must be between one and 100000")
        try:
            sqlite_vec = importlib.import_module("sqlite_vec")
        except ImportError:
            return False
        table = f"embeddings_vec_{dim}"
        try:
            self.connection.enable_load_extension(True)
            sqlite_vec.load(self.connection)
            self.connection.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING vec0("
                f"id TEXT PRIMARY KEY,vec float[{dim}],project_id TEXT,workspace_id TEXT,+asset_id TEXT)"
            )
            self.connection.execute(f"DELETE FROM {table}")
            self.connection.execute(
                f"INSERT INTO {table}(id,vec,project_id,workspace_id,asset_id) "
                "SELECT id,vec,project_id,workspace_id,asset_id FROM embeddings "
                "WHERE dim=? AND project_id=? AND workspace_id=?", (dim, *self._scope),
            )
            self.connection.commit()
            return True
        except (sqlite3.Error, OSError, AttributeError):
            self.connection.rollback()
            return False
        finally:
            try:
                self.connection.enable_load_extension(False)
            except (sqlite3.Error, AttributeError):
                pass
