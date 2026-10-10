# Shared video index

Footage memory and the future segment-edit workflow use one SQLite database
per project. Footage memory currently writes assets, windows, timestamped
events, speakers and search documents. It does not run segmentation, shot
detection, embeddings, annotations or an edit workflow.

## Storage and identity

The tool host stores the database at
`$RENDERHAUS_VIDEO_INDEX_ROOT/<workspace_id>/<project_id>/video_index.sqlite3`.
The root defaults to `.renderhaus/projects`. These files are local project
state and must not enter source control. The host confines project identifiers
and source paths, rejects symlinked databases and keeps media in the existing
ffmpeg job directory. `assets.path_key` contains the confined relative key
`<job_id>/<relative_path>`. It never stores a signed URL or credentials.

`index_meta` binds each database to one `project_id` and `workspace_id`.
Opening a database with another identity fails before migration. Every
application table carries both identifiers. Index methods scope reads by
both identifiers, and composite foreign keys prevent child rows from
referencing another project's assets or windows.

Assets are unique on `project_id`, `workspace_id`, `content_hash` and
`asset_version_id`. Missing version identifiers use the empty string internally.
Re-uploading the same bytes with the same version reuses the asset and its
memory, while updating the current path key. A different hash or version
creates a distinct asset. `assets_for_path` lets status detect memory for
earlier bytes at the same source key. Content reuse never crosses projects.

## Implemented schema

The DDL lives in
[001_core.sql](../providers/footage_memory/sql/001_core.sql).
All times ending in `_ms` are integer milliseconds measured from the beginning
of their source asset.

| Table | Main fields and purpose |
| --- | --- |
| `assets` | `id`, `content_hash`, `asset_version_id`, `path_key`, `duration_s`, `fps`, `indexed_at`, `memory_version`, `hierarchy_json`. Asset identity and completion state. |
| `windows` | `id`, `asset_id`, `t0_ms`, `t1_ms`, `status`, `backend_ref`. One bounded analysis window. |
| `events` | `id`, `asset_id`, `window_id`, `kind`, `t0_ms`, `t1_ms`, `speaker_id`, `text`, `confidence`, `attrs_json`. The canonical retrieval records. |
| `speakers` | `id`, `asset_id`, `label`, `attrs_json`. Speaker labels within one asset. |
| `search_docs` | `id`, `asset_id`, `asset_version_id`, `owner_kind`, `owner_id`, `text`, `fts`. Canonical search text and normalized tokens. |
| `embeddings` | `id`, `owner_kind`, `owner_id`, `asset_id`, `asset_version_id`, `t_ms`, `dim`, `vec`, `model_ref`. Plain float32 BLOB records reserved for future analyses. |

`kind` is one of `dialogue`, `sound`, `on_screen_text`, `moment`, `person`,
`object` or `location`. Events must stay within their window; windows must
stay within the source duration. Confidence must be finite and between zero
and one. Speaker labels resolve to the same asset's `speakers` rows.

`replace_window_events` validates every incoming event before its transaction
replaces the old events and search documents. Invalid replacements preserve
the previous records. Event identifiers derive from the project, window,
ordinal and normalized event data, so repeated fixture builds keep stable IDs.
Changes clear completion and the derived hierarchy. `mark_complete` requires
complete windows covering the whole source without gaps. Search excludes
assets without a `memory_version`.

The backend's structured events populate `events`. Each event produces one
`search_docs` row with `owner_kind=event` and `owner_id=events.id`. Dialogue
may reference a speaker; non-speech sounds and visible text remain separate
events. Provider-supplied attributes cannot set verification state.

## Search and verification

The index detects FTS5 by trying to create `search_docs_fts`. When available,
that virtual table indexes normalized event text with both scope identifiers
stored alongside each row. Triggers synchronize it with `search_docs`.
Unavailable FTS5 falls back to parameterized token `LIKE` candidates followed
by exact token scoring. Tests also exercise `use_fts=False`.

Both paths apply the same deterministic score, token coverage plus token
density, with asset ID, start time and event ID as tie-breakers. Empty queries
return no hits. Limits are bounded from 1 to 100 in the index; the tool
contract applies its own tighter bound. Arbitrary FTS query syntax is not
accepted. This branch implements lexical retrieval, not semantic search.

Hits contain `hit_id`, `clip_id`, `t0_s`, `t1_s`, `speaker`, `snippet`, `kind`,
`score`, `confidence` and `verify_required=true`. Retrieval is never ground
truth. A real narrow watch can persist `verified`, `refuted` or `ambiguous`
in `events.attrs_json.verification`, with refined source timestamps. Dry-run
verification does not authorize extraction. The tool host enforces that rule
before it calls the existing fixed ffmpeg trim operation.

## Derived hierarchy

`hierarchy(asset_id)` groups event IDs into
Root > SuperEvent > MacroEvent > Subgraph. It partitions the asset into
intervals of three to eight minutes whenever the asset is at least three
minutes long. Shorter assets have one shorter macro. A super-event contains
up to four consecutive macros. Event start times assign each canonical event
to exactly one subgraph; speaker and entity references come from those same
rows.

`mark_complete` stores this derived reference tree in `assets.hierarchy_json`.
It does not copy event text or create another memory database. Replacing
events clears the cached tree. These groups are temporal containers, not
inferred themes or story arcs; semantic aggregation remains future work.

## Schema versioning

`PRAGMA user_version` is the migration version, currently 2. Version 1 creates
the memory schema. Version 2 creates the separately documented segment-edit
extension tables. Each migration runs under `BEGIN IMMEDIATE` and advances
the version in the same transaction. Reopening a database runs only missing
migrations. A database from a newer application version fails explicitly.

Future changes add numbered migrations instead of rewriting installed schema
files. They must preserve asset identity and complete a migration before any
tool reads the new shape. `memory_version` records the analysis format
separately from the SQLite schema version. The host currently uses
`footage-memory-v1:dry`; this identifies synthetic memory and does not promote
a backend to the live default.

Before an interrupted build retries, `prepare_window_layout` validates continuous full-source
coverage and atomically removes obsolete windows, events and search documents. Matching
window IDs remain. Extension references prevent deletion and roll the transaction back.
Completed memory is protected from repartitioning and remains reusable.

## sqlite-vec compatibility

`embeddings.vec` is a little-endian float32 BLOB, exactly `dim * 4` bytes.
The format follows the optional extension's
[Python vector interface](https://alexgarcia.xyz/sqlite-vec/python.html),
read 2026-10-10. No embedding model runs in this branch.

`install_vec_adapter(dim)` imports `sqlite_vec` only when called. Missing or
unloadable extensions return `False` and retain the plain BLOB table. When
available, it loads the extension into this connection, creates
`embeddings_vec_<dim>` using `vec0`, and rebuilds it from scoped rows with the
same dimension. The
[vec0 metadata documentation](https://alexgarcia.xyz/sqlite-vec/features/vec0.html),
read 2026-10-10, documents its project/workspace metadata columns and auxiliary
asset ID. The adapter disables extension loading afterward. Its derived
table is a cache, not another source of truth. Re-run the adapter after
writing vectors; automatic synchronization and nearest-neighbor retrieval
are outside this branch. Tests verify the BLOB codec, missing-extension
behavior and generated adapter DDL without requiring sqlite-vec.

The extension is [MIT or Apache-2.0](https://github.com/asg017/sqlite-vec).
It is optional and not vendored. No AGPL or non-commercial code or weights
are included.

## How the segment-edit plan plugs in

[002_segment_edit.sql](../providers/footage_memory/sql/002_segment_edit.sql)
contains the extension DDL. This migration creates the tables but no tool
populates or exposes them now. The columns retain the plan's section 5.1
shape, with project/workspace scope and explicit local asset/window references.

| Future table | Writer and relationship |
| --- | --- |
| `shots` | Shot detection writes immutable `asset_version_id`, local `asset_id`, `idx`, source times, caption, shot type, keyframes and analysis time. Nullable `window_id` identifies a corresponding memory window where possible. |
| `components` | Project-level names, kinds and label embedding references. Components may appear in multiple assets. |
| `tracks` | Component instances within a version and shot. It retains confidence, bbox path, mask metadata, source and model reference, and may reference a memory window. |
| `masks` | Blob-key metadata for a shot or track. Section 5.1 describes mask blobs beside tracks without a separate table; this reserved table reconciles those keys with the requested shared schema. It has no BLOB column. |
| `annotations` | Notes, threads, author, status, mentions and links to changesets/change items. |
| `anchors` | Notes targeting versions, shots, tracks, frames, time ranges, audio and words. Local `asset_id` and nullable `window_id` connect them to the shared records. |
| `analysis_jobs` | Future index/component job status, estimate, cap, actual cost, tool call and error. |

Future SigLIP 2 analysis writes `keyframe`, `track_crop`, `caption` and
`transcript` vectors into the existing `embeddings` table, keeping owner IDs
and immutable asset-version IDs. Future Gemini shot naming writes captions
and component labels into `search_docs` with corresponding `owner_kind` and
`owner_id`, and may populate `shots.caption` and `components.label`. The
current query tool still returns event hits only; adding cross-owner search
and hybrid ranking requires a later migration and tool change.

Shots may cross memory-window boundaries, so their `window_id` is nullable
and their asset/version binding remains authoritative. Tracks reference
their shot and component rather than inventing new asset identities. Masks
remain private external blobs addressed by keys; rendered mask videos will
use the Studio's existing video asset versions and `mask_of` relation.
Neither signed URLs nor mask pixels belong in SQLite.

SAM, SigLIP, PySceneDetect, segmentation, annotations, component search,
mask editing, UI and APIs from the segment-edit plan remain out of scope.
The shared schema gives that plan one destination for its records without
adding a second footage index.

## Evidence

`tests/test_video_index.py` covers schema creation and version-1 migration,
idempotency, project isolation, event/speaker round trips, hash/version reuse,
FTS parity and fallback, bounded deterministic retrieval, derived hierarchy,
verification state, float32 storage and optional adapter behavior. It checks
extension columns and proves footage-memory leaves those tables empty.

The hierarchy and build/query design have attribution in
[NOTICE.md](../providers/footage_memory/NOTICE.md). No upstream source code
files or media fixtures were copied.
