-- Reserved extension schema. Footage-memory does not populate these tables.
CREATE TABLE IF NOT EXISTS shots (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    asset_version_id TEXT NOT NULL,
    window_id TEXT,
    idx INTEGER NOT NULL,
    t0_ms INTEGER NOT NULL,
    t1_ms INTEGER NOT NULL,
    caption TEXT,
    shot_type TEXT,
    keyframes_json TEXT NOT NULL DEFAULT '[]',
    analysed_at TEXT,
    UNIQUE(id, project_id, workspace_id),
    FOREIGN KEY(asset_id, project_id, workspace_id)
        REFERENCES assets(id, project_id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY(window_id, asset_id, project_id, workspace_id)
        REFERENCES windows(id, asset_id, project_id, workspace_id)
);

CREATE TABLE IF NOT EXISTS components (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    label TEXT NOT NULL,
    label_embedding_ref TEXT,
    kind TEXT NOT NULL CHECK(kind IN ('object', 'person', 'surface', 'text')),
    created_at TEXT NOT NULL,
    UNIQUE(id, project_id, workspace_id)
);

CREATE TABLE IF NOT EXISTS tracks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    component_id TEXT NOT NULL,
    asset_version_id TEXT NOT NULL,
    shot_id TEXT NOT NULL,
    window_id TEXT,
    t0_ms INTEGER NOT NULL,
    t1_ms INTEGER NOT NULL,
    mean_conf REAL,
    bbox_path_json TEXT NOT NULL DEFAULT '[]',
    mask_blob_key TEXT,
    mask_fps REAL,
    mask_w INTEGER,
    mask_h INTEGER,
    source TEXT NOT NULL CHECK(source IN ('auto', 'click', 'text')),
    model_ref TEXT,
    UNIQUE(id, project_id, workspace_id),
    FOREIGN KEY(asset_id, project_id, workspace_id)
        REFERENCES assets(id, project_id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY(component_id, project_id, workspace_id)
        REFERENCES components(id, project_id, workspace_id),
    FOREIGN KEY(shot_id, project_id, workspace_id)
        REFERENCES shots(id, project_id, workspace_id),
    FOREIGN KEY(window_id, asset_id, project_id, workspace_id)
        REFERENCES windows(id, asset_id, project_id, workspace_id)
);

-- The plan describes mask blobs beside tracks; this table records their keys only.
CREATE TABLE IF NOT EXISTS masks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    asset_version_id TEXT NOT NULL,
    track_id TEXT,
    shot_id TEXT,
    window_id TEXT,
    blob_key TEXT NOT NULL,
    format TEXT NOT NULL,
    fps REAL,
    width INTEGER,
    height INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(asset_id, project_id, workspace_id)
        REFERENCES assets(id, project_id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY(track_id, project_id, workspace_id)
        REFERENCES tracks(id, project_id, workspace_id),
    FOREIGN KEY(shot_id, project_id, workspace_id)
        REFERENCES shots(id, project_id, workspace_id),
    FOREIGN KEY(window_id, asset_id, project_id, workspace_id)
        REFERENCES windows(id, asset_id, project_id, workspace_id)
);

CREATE TABLE IF NOT EXISTS annotations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    parent_id TEXT,
    author_kind TEXT NOT NULL CHECK(author_kind IN ('user', 'agent')),
    author_id TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('open', 'resolved', 'applied', 'dismissed', 'out_of_date')),
    mentions_json TEXT NOT NULL DEFAULT '[]',
    intent_hint TEXT,
    changeset_id TEXT,
    change_item_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(id, project_id, workspace_id),
    FOREIGN KEY(parent_id, project_id, workspace_id)
        REFERENCES annotations(id, project_id, workspace_id)
);

CREATE TABLE IF NOT EXISTS anchors (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    annotation_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    asset_id TEXT,
    asset_version_id TEXT,
    shot_id TEXT,
    window_id TEXT,
    t0_ms INTEGER,
    t1_ms INTEGER,
    frame_index INTEGER,
    geometry_json TEXT,
    track_id TEXT,
    audio_json TEXT,
    word_ids_json TEXT,
    snapshot_key TEXT,
    FOREIGN KEY(annotation_id, project_id, workspace_id)
        REFERENCES annotations(id, project_id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY(asset_id, project_id, workspace_id)
        REFERENCES assets(id, project_id, workspace_id),
    FOREIGN KEY(shot_id, project_id, workspace_id)
        REFERENCES shots(id, project_id, workspace_id),
    FOREIGN KEY(track_id, project_id, workspace_id)
        REFERENCES tracks(id, project_id, workspace_id),
    FOREIGN KEY(window_id, asset_id, project_id, workspace_id)
        REFERENCES windows(id, asset_id, project_id, workspace_id)
);

CREATE TABLE IF NOT EXISTS analysis_jobs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    asset_version_id TEXT NOT NULL,
    depth TEXT NOT NULL CHECK(depth IN ('index', 'components')),
    status TEXT NOT NULL,
    estimate_cents INTEGER,
    cap_cents INTEGER,
    actual_cents INTEGER,
    tool_call_id TEXT,
    error TEXT,
    FOREIGN KEY(asset_id, project_id, workspace_id)
        REFERENCES assets(id, project_id, workspace_id) ON DELETE CASCADE
);
