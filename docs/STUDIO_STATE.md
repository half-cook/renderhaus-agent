# Studio state and asset identity

The Studio treats database IDs as durable state and URLs as temporary delivery details. A canvas
never persists an S3 URL, local filesystem path, provider URL, or signed URL.

```text
Clerk user
   |
   +-- active organization ---------> workspace_id = org:<clerk_org_id>
   `-- no active organization ------> workspace_id = user:<clerk_user_id>
                                          |
                                          +-- projects
                                          |     `-- canvas_documents (revisioned JSON)
                                          +-- assets (logical identity)
                                          |     `-- asset_versions (immutable bytes)
                                          |             `-- asset_relations (provenance)
                                          `-- executions
                                                `-- tool_calls
```

## Asset flow

```text
upload / provider output / Remotion render
                    |
                    v
       register immutable bytes + checksum
                    |
                    v
       { assetId, versionId, kind, metadata }
                    |
          +---------+----------+
          |                    |
          v                    v
   canvas node output    agent working context
          |                    |
          +---------+----------+
                    v
       resolve version at execution boundary
                    |
                    v
        authenticated content response
```

Regenerating an existing node creates a new `asset_version` under the same logical `asset`. Agent
tools receive an `asset_version_id` or a canvas `node_id`; they do not pass provider URLs between
tools. Derived outputs record `derived_from` or `composed_from` relations to their inputs.

The browser turns a version ID into `/api/studio/assets/{versionId}/content` only while rendering a
preview or download. The backend resolves the same version to a provider-readable source only at a
tool invocation boundary.

## Canvas writes and job history

Canvas documents use optimistic revisions:

```text
client loads revision 12
       |
       +-- PUT expected_revision=12 --> save revision 13
       `-- stale PUT expected_revision=12 --> 409 conflict + reload
```

Agent submissions are durable `executions`; every tool call is appended to the execution ledger as
it starts and completes. Completed output asset IDs and partial output survive a server restart or a
later agent failure. The Studio queue reads this ledger instead of process memory.

## Local and production storage

`server/studio_state.py` is the local adapter. It stores relational state in
`.renderhaus/studio.sqlite3` and managed media in `.renderhaus/media/assets/`. The table boundaries,
workspace keys, immutable version model, and revision checks are intentionally compatible with a
production Postgres implementation. In production, replace the repository adapter and move media
bytes to object storage; the Studio API and canvas document shape do not change.

Every repository lookup is workspace-scoped. Clerk's active organization is the team workspace;
users without an organization get a personal workspace. `RENDERHAUS_DISABLE_AUTH=true` is only a
deliberate local-development escape hatch. Never enable it in a shared deployment.

## Legacy migration

On first load, the Studio reads the former local-storage canvas once. Saving it registers any known
media with the backend, replaces URL/path fields with `{assetId, versionId, ...}`, and marks the
browser migration complete. New writes are server-authoritative.

