# renderhaus-agent — agent instructions

## What you are building

The node canvas specified in `design/merge-doc.md` (revision 0.2). That document is
self-contained — there is no addendum and no precedence chain. Appendix A lists what was
deliberately deferred.

Read it before writing code. It is long; read it anyway. It contains the reasoning for decisions
that look arbitrary out of context.

## Hard rules

1. **`studio/` is deleted in M5. Do not read it for patterns.** It is a `localStorage` prototype
   with a different data model (`kind` not `type`, client-side execution, no auth). Copying from it
   will silently reintroduce everything the spec was written to fix. Delete it at the start of M5,
   before writing the new canvas, along with `server/studio.py`, `server/studio_options.py`, and
   the `studio` Makefile target.
2. **Never modify `providers/*/api.py`.** New provider behaviour goes in
   `server/canvas/adapters.py`. Those modules are shared with the timeline surface and the MCP
   gateway.
3. **Never call a `wait_for_*` helper.** They block. `providers/registry.py` already excludes them
   from tool exposure; the worker must respect the same rule.
4. **One stylesheet.** `web/src/app/globals.css` and nothing else. Tokens exist only for port
   colours and status colours; everything else is literal Tailwind utilities.
5. **Stop at every milestone boundary.** Run that milestone's acceptance checks from spec §12 and
   addendum Part F, report results, and wait. Do not start the next milestone.

## Locked decisions

These were open in the spec. They are now closed — do not re-litigate them, and do not silently
choose differently.

| Decision | Value |
|---|---|
| Object storage | **Cloudflare R2**, via boto3. See below. |
| Queue | **Postgres**, `SELECT … FOR UPDATE SKIP LOCKED`. No SQS, no broker. |
| Legacy DynamoDB assets | **The table is empty. There is nothing to migrate.** Do not write a backfill, a dual-read path, or an id-compatibility shim. |
| Frontend home | `web/` — Next 16, Tailwind 4, Clerk. No new app. |
| Styling | Tailwind only. The 1,229-line `studio/app/globals.css` is deleted, not ported. |
| Audio in v0 | **Yes.** `text_to_music` (Mureka), `text_to_speech` (Fish Audio). Terminal leaves — no operation accepts audio input. |
| Scene approval | **Yes.** `NodeData.approved` + `story_order`. Must land in M2. |
| Undo/redo | **Yes**, via `zundo` on the document slice. Document-only, no backend. |
| Multi-reference images | **No.** `reference` is `multi: False` in v0. |
| Fish Audio voices | Ship the two starter voices. Full library is post-v0. |
| Mureka models | Expose `auto` only. Keep the rest in `OperationSpec.models` for later. |
| Wire format | camelCase, via `alias_generator=to_camel` on a shared `CanvasModel` base. The JSONB document is stored in wire form. |
| Local dev stack | Postgres only. `docker compose up postgres` is the whole thing. |

## R2 configuration

R2 is S3-compatible but not identical. Three things matter:

```python
# server/canvas/storage.py — NEW. Do not extend server/assets.py; it holds the
# timeline's AWS session and its DynamoDB coupling, which the canvas does not want.
from botocore.config import Config

_R2 = boto3.client(
    "s3",
    endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    region_name="auto",                          # R2 has exactly one region
    config=Config(
        request_checksum_calculation="when_required",   # REQUIRED
        response_checksum_validation="when_required",   # REQUIRED
    ),
)
```

Without those two `Config` lines every `PutObject` fails with
`501 NotImplemented: Header 'x-amz-checksum-crc32' not implemented`. R2 supports CRC32 only as a
composite checksum; boto3 ≥1.36 sends a full-object CRC32 by default. This is the single most
likely thing to burn an hour.

Also true of R2, so do not copy these patterns from `assets.py`:

- `PutBucketPolicy` is unimplemented. Use presigned URLs for access, never a bucket policy.
- Object tagging is unimplemented.
- `PutBucketCors`, `CreateBucket`, and `HeadBucket` all work, so the bootstrap logic ports directly —
  but the CORS rule must include `PUT`, not just `GET`/`HEAD` (see `assets.py:194` for the shape,
  and note its `except ClientError` only logs a warning, so a failure here is silent).

## Environment

```
DATABASE_URL              postgres, async driver (postgresql+asyncpg://)
TEST_DATABASE_URL         separate disposable database for `pytest` (M1) — never DATABASE_URL's target
R2_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET
RENDERHAUS_DEV_USER       local identity when Clerk is unconfigured; default "local"
SEEDANCE_DRY_RUN          default true
SEEDREAM_DRY_RUN          default true
MUREKA_DRY_RUN            default true
FISH_AUDIO_DRY_RUN        default true
```

The health check must fail loudly if `DATABASE_URL` or any `R2_*` is unset.
Silent fallbacks here produce failures that look like application bugs.

## Money

`MODEL_RATES` values are **placeholders and must be over-estimates.** The rates feed a spend cap, so
over-estimating fails closed (generation stops early) and under-estimating fails open (you overspend
before the cap trips). Never "correct" a rate downward without a real invoice line to justify it.
Every rate carries a `# TODO(verify)` comment until confirmed. Current caps: $20/user/day,
5 concurrent generations per project, 10 per user.

## Build order

M1 → M6 per spec §12. Two additions to M1, before anything else:

1. Add `pytest` and `pytest-asyncio`. There is currently no test framework and no `tests/`
   directory. Every acceptance check becomes a test named after itself.
2. Add a Node step to `.github/workflows/ci.yml` — the §4 contract diff needs one.

## Where things live

```
server/canvas/          NEW   routes, contracts, adapters.py, storage.py, worker.py
server/assets.py        KEEP  timeline's S3 + DynamoDB. Canvas does not touch it.
server/projects.py      PARK  timeline's JSON project store
providers/*/api.py      FROZEN
web/src/app/canvas/     NEW
web/src/components/canvas/  NEW  ten components, listed in addendum §C.2
studio/                 DELETE in M5
```

Routes: existing API is `/api/*`, the canvas is `/v1/*`. `web/src/lib/api/client.ts` currently
assumes `/api` — do not break it.
