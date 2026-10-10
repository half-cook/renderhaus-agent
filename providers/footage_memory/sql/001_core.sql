CREATE TABLE IF NOT EXISTS index_meta (
    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    asset_version_id TEXT NOT NULL DEFAULT '',
    path_key TEXT NOT NULL,
    duration_s REAL NOT NULL CHECK(duration_s >= 0),
    fps REAL CHECK(fps > 0),
    indexed_at TEXT,
    memory_version TEXT,
    hierarchy_json TEXT,
    UNIQUE(project_id, workspace_id, content_hash, asset_version_id),
    UNIQUE(id, project_id, workspace_id)
);

CREATE TABLE IF NOT EXISTS windows (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    t0_ms INTEGER NOT NULL CHECK(t0_ms >= 0),
    t1_ms INTEGER NOT NULL CHECK(t1_ms > t0_ms),
    status TEXT NOT NULL CHECK(status IN ('pending', 'complete', 'failed')),
    backend_ref TEXT,
    UNIQUE(project_id, workspace_id, asset_id, t0_ms, t1_ms),
    UNIQUE(id, asset_id, project_id, workspace_id),
    UNIQUE(id, project_id, workspace_id),
    FOREIGN KEY(asset_id, project_id, workspace_id)
        REFERENCES assets(id, project_id, workspace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS speakers (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    label TEXT NOT NULL,
    attrs_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(asset_id, label, project_id, workspace_id),
    UNIQUE(id, asset_id, project_id, workspace_id),
    FOREIGN KEY(asset_id, project_id, workspace_id)
        REFERENCES assets(id, project_id, workspace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    window_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN (
        'dialogue', 'sound', 'on_screen_text', 'moment', 'person', 'object', 'location'
    )),
    t0_ms INTEGER NOT NULL CHECK(t0_ms >= 0),
    t1_ms INTEGER NOT NULL CHECK(t1_ms >= t0_ms),
    speaker_id TEXT,
    text TEXT NOT NULL,
    confidence REAL NOT NULL CHECK(confidence >= 0 AND confidence <= 1),
    attrs_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(id, project_id, workspace_id),
    FOREIGN KEY(asset_id, project_id, workspace_id)
        REFERENCES assets(id, project_id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY(window_id, asset_id, project_id, workspace_id)
        REFERENCES windows(id, asset_id, project_id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY(speaker_id, asset_id, project_id, workspace_id)
        REFERENCES speakers(id, asset_id, project_id, workspace_id)
);
CREATE INDEX IF NOT EXISTS events_asset_time ON events(project_id, workspace_id, asset_id, t0_ms);

CREATE TABLE IF NOT EXISTS search_docs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    asset_version_id TEXT NOT NULL DEFAULT '',
    owner_kind TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    text TEXT NOT NULL,
    fts TEXT NOT NULL DEFAULT '',
    UNIQUE(project_id, workspace_id, owner_kind, owner_id),
    FOREIGN KEY(asset_id, project_id, workspace_id)
        REFERENCES assets(id, project_id, workspace_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS search_docs_owner ON search_docs(project_id, workspace_id, owner_kind, owner_id);

CREATE TABLE IF NOT EXISTS embeddings (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    owner_kind TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    asset_version_id TEXT NOT NULL DEFAULT '',
    t_ms INTEGER NOT NULL CHECK(t_ms >= 0),
    dim INTEGER NOT NULL CHECK(dim > 0),
    vec BLOB NOT NULL CHECK(length(vec) = dim * 4),
    model_ref TEXT NOT NULL,
    UNIQUE(project_id, workspace_id, asset_id, owner_kind, owner_id, model_ref),
    FOREIGN KEY(asset_id, project_id, workspace_id)
        REFERENCES assets(id, project_id, workspace_id) ON DELETE CASCADE
);
