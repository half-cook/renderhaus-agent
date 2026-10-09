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

## Upload limits

`POST /api/studio/upload?project_id=<project>` accepts the existing image, video,
and audio formats. Canvas Upload, Upload reference, and the agent Files panel
all use this route. The review panel displays saved assets and does not upload
files. The ASCII panel reads files locally for conversion and does not send
them to either upload route.

| Media kind | Default maximum | Accepted extensions |
|---|---|---|
| Image | 15 MB | PNG, JPG, JPEG, WebP, GIF, SVG |
| Video | 100 MB | MP4, WebM, MOV, M4V |
| Audio | 50 MB | MP3, WAV, M4A, OGG, FLAC |

MB means 1,048,576 bytes here. An exact-limit file is allowed. These defaults
retain the legacy image limit and allow larger clips and audio without an
unbounded application read. Studio retains filename-based media classification
and existing SVG sanitization. Uploading does not introduce codec conversion or
new formats.

`configs/studio-upload-limits.json` is the shared source for these defaults and
the 1 MB multipart overhead allowance. `STUDIO_MAX_UPLOAD_MB` overrides all
kinds. `STUDIO_MAX_IMAGE_UPLOAD_MB`, `STUDIO_MAX_VIDEO_UPLOAD_MB`, and
`STUDIO_MAX_AUDIO_UPLOAD_MB` override individual kinds after the global setting.
Values must be positive integers. Empty values use the defaults. No new secrets
are required.

`GET /api/health` returns `max_upload_mb`, the largest configured maximum, and
`max_upload_mb_by_kind`. Studio fetches these limits before each upload and
rejects oversized files before sending their content. The backend enforces the
same bounds, returns HTTP 413 with `File is larger than N MB.`, and returns HTTP
415 for unsupported types. A dismissed error disappears. Retrying or switching
projects clears the upload alert. Network errors, interrupted responses, and
proxy errors also display a readable alert on both the canvas and agent view.

Both backend upload routes copy files into temporary paths in chunks of at most
1 MB. Files larger than Starlette's spool threshold already reside on disk when
the route runs. The route bounds its own reads and removes temporary paths after
success or failure. Multipart parsing happens before route validation, so this
is not an early rejection of the incoming network body.

`POST /api/uploads` remains the separate legacy image-reference route. It accepts
only magic-checked PNG, JPEG, and WebP and uses the configured image maximum.
`GET /api/config` keeps `max_upload_mb` as the image maximum for existing clients.

Next 15.5.23 uses `experimental.middlewareClientMaxBodySize` in
`studio/next.config.ts`. The value is the largest configured upload maximum plus
1 MB for multipart overhead, or 101 MB with the defaults. This raises the existing
buffer limit. Clerk's middleware matchers still cover every API route. The newer
[Next configuration documentation](https://nextjs.org/docs/app/api-reference/config/next-config-js/proxyClientMaxBodySize)
uses the name `proxyClientMaxBodySize`. This clone uses the verified installed
15.5.23 option. Documentation read on 2026-10-09.

The same upload environment settings must reach both the backend and the Next
build/start process. Backend settings can come from the existing environment or
Secrets Manager loader. Next does not read backend Secrets Manager settings.
Restart the backend and rebuild/restart Next after changing these settings.
`studio/tests/uploads.test.cjs` compares the actual Next config with the Python
resolver under default and overridden limits. CI runs these contracts, all
Studio tests, and the Studio typecheck.

The local HTTP regression check uploaded the existing 13,655,545-byte MP4 through
Next into the real SQLite/file repository, downloaded identical bytes, and
opened the saved artifact with ffprobe. It also observed 413 for an oversized
image and 415 for an unsupported file. Comet browser validation is blocked in
this environment and remains incomplete.

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
