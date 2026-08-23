# Node Canvas — v0 Implementation Spec

A node-based infinite canvas for AI image, video, and audio generation, built as a new surface
on the existing `renderhaus-agent` repo (branch `harness-switch`, commit `281883e`).

**Revision 0.2.** Changes from 0.1: object storage is R2 rather than S3; the queue is Postgres
rather than SQS; DynamoDB is out of the architecture entirely; audio ships in v0; `studio/` is
deleted rather than ported; the frontend is Tailwind-only. A verification appendix at the end
lists what was deliberately deferred to keep implementation unblocked.

**Scope discipline:** everything in this document is either needed for v0 or is expensive to
retrofit later. Anything that can be added seamlessly afterward has been removed and listed in
§10. If you find yourself building something not described here, stop and ask.

---

# ⚠️ OPEN DECISIONS — resolve before or during implementation

**Nothing here blocks M1 or M2.** Foundation and contracts can be built today; every item below
lands in M3 or later. Items marked **[AI]** need the AI engineer specifically — they are model
behaviour questions, not architecture.

## Blocks M3–M6

- [ ] **Credit peg and `MODEL_RATES`.** §9 ships with `/* ... */`. Pick a peg (e.g. 100 credits
      = $1) and per-model rates. **The peg is permanent** — changing it later silently
      reinterprets every historical `cost_credits`. Change rates instead.
- [ ] **`DAILY_CREDIT_CAP` and `MAX_CONCURRENT_PER_USER`.** Placeholders are 2,000 and 3. Set
      them low enough that the deliberate race overshoot in §5.4 is affordable.
- [ ] **Does BytePlus charge for failed generations?** §5.4 excludes `failed` from the daily
      total on the assumption you are not charged. If that is wrong, the cap leaks. One real
      failed generation answers it.
- [ ] **Neon vs RDS.** Reversible (connection string), but pick before M1 migrations run.
      Neon for branch-per-PR while the schema churns; RDS if you need VPC.
- [ ] **Model activation in the Ark Console.** `ModelNotOpen` is a provisioning error, not a
      code error. Confirm every model in `OPERATIONS` is activated on the production key.

## Closed since 0.1 — do not re-litigate

- **Same product as the timeline editor?** Yes. `web/` already has Next 16, Tailwind 4, and
  Clerk; a separate Vite app costs a second auth integration for nothing.
- **Seedream multi-reference.** Deferred. `reference` is `multi: False`, so at most one image
  per role in v0.
- **Do the `[image N]` tokens help?** At most one reference per role now, so at most one token.
  Keep the mechanism; verify when multi-reference lands.
- **Does the image node show a resolution control?** No. `config_fields` decides, and
  `text_to_image` does not list it.
- **Audio in v0?** Yes — music and voiceover, as terminal leaves.
- **Object storage.** R2. Both the S3 bucket and the DynamoDB table are empty, so the switch
  costs nothing.
- **Queue.** Postgres. See §1.

## [AI] Model behaviour — needs the AI engineer

- [ ] **Content policy on realistic human faces.** There are reports ModelArk rejects them,
      including AI-generated ones. Your reference material is a photoreal person drinking
      sparkling water. If this holds it is product-shaping, not an implementation detail, and
      needs a specific user-facing error rather than a generic failure. **Test this first.**
- [ ] **`generate_audio`, `watermark`, `service_tier` defaults.** Currently unset in
      `GenerationConfig`. Decide product defaults; `watermark: false` at minimum.
- [ ] **Valid resolution × aspect-ratio combinations per model.** `GenerationConfig` allows any
      pairing. The provider will reject some. Either constrain in Pydantic or map defensively.
- [ ] **Native first/last-frame support.** Deferred from v0 (§10), but confirm whether ModelArk
      accepts a second role-tagged image in `content`. It determines whether the video node
      ever gets frame-exact interpolation or only start-frame conditioning.

## Deferred, with a trigger

- [ ] **CDN** (R2 custom domain). Expect to want this early — v0 fires one signed redirect per
      asset.
- [ ] **Unify the canvas and timeline asset stores.** Both are empty today, so this is a pure
      code change with no data migration — an unusually cheap option to keep open. Do it when
      the timeline is next touched.
- [ ] **Postgres queue → a broker** if sustained load passes a few generations per second.
- [ ] **Clerk cost** at volume. Not a capability limit. `owner_id` is opaque `text` so a swap is
      a backfill.
- [ ] **Project deletion cascades transformation rows while the provider keeps generating and
      billing.** Someone will delete a project to cancel a generation. Low frequency, real cost.

## Assumptions to verify in review

- Seedream and Fish Audio are synchronous; Seedance and Mureka are async task-based (§6). The
  consumer branches on this.
- Fish Audio ships two starter voices. Thin for a product feature; `list_voices()` exists when
  it matters.
- Mureka exposes nine largely undifferentiated models. v0 surfaces `auto` only.
- Model IDs `seedance-1-5-pro-251215` and `seedream-5-0-lite-260128` are read from the current
  provider defaults and will drift.
- Duration is silently clamped to 4–12s by the provider; Pydantic rejects out-of-range first.

---

**§0.1 — The canvas is a document, the generation ledger is relational.** Node positions, draft
prompts, and edges live in one JSONB blob. Only assets and transformations get real tables.

**§0.2 — The submit payload is self-contained.** The backend executes a generation without
reading the project document. Everything it needs arrives in the request body. One sanctioned
exception: asset scoping at hydration (§5.1).

**§0.3 — Generation history is immutable.** At submit, the frontend resolves every input
reference to a concrete asset ID and freezes it into the transformation row. Later canvas edits
never mutate past executions.

If a change violates one of these, it is the wrong change.

---

## 1. Stack

Backend is Python. Frontend is TypeScript. Nothing straddles.

| Layer | Choice | Status |
|---|---|---|
| API | FastAPI + uvicorn | Exists |
| Database | Postgres (Neon or RDS) + SQLAlchemy 2.0 async + Alembic | **New** |
| Queue | Postgres, `SELECT … FOR UPDATE SKIP LOCKED` | **New** |
| Worker | Second entrypoint on the same image | **New** |
| Storage | Cloudflare R2 via boto3 | **New** (the S3 helpers in `server/assets.py` port over) |
| Auth | Clerk | Exists, both sides |
| Provider | BytePlus ModelArk via `providers/seedance`, `providers/seedream` | Exists |
| Provider (audio) | Mureka (music), Fish Audio (speech) | Exists |
| Frontend | Next.js 16, React 19, Zustand 5, Tailwind 4 | Exists |
| Canvas | `@xyflow/react` v12 — **not** `reactflow`, which is v11 | **New** |
| Server state | TanStack Query | **New** |

**Only two things need provisioning: Postgres and an R2 bucket.** The worker is another command
on the image you already build; the sweeper is a loop inside it.

**There is no separate queue service.** The transformations table *is* the queue, claimed with
`SELECT … FOR UPDATE SKIP LOCKED`. At v0 volume — generations measured in seconds to minutes,
single-digit concurrency — this is not a compromise, and it buys three things that matter more
than throughput: the insert and the enqueue become one transaction (so a committed row can never
be a lost message), the queue claim and the status claim become the same `UPDATE`, and the local
stack is `docker compose up postgres` with nothing else running.

**Next.js API routes are transport only** — proxying and auth forwarding. No business logic, no
database, no provider calls. One backend.

### Reversibility

Several choices above are inherited from the existing repo rather than chosen on merits. That
is deliberate, and safe, because of how the cost of changing them is distributed:

| Decision | Cost to change | Trigger to revisit |
|---|---|---|
| Data model (§0, §3) | Months, or never | — |
| Postgres | Months | — |
| Clerk → another IdP | Weeks (subject-ID backfill) | Per-MAU cost at volume |
| R2 → S3 or anything | ~A weekend (object copy + `endpoint_url`) | — |
| Next.js → separate Vite app | Days | If canvas and timeline become separate products |
| Postgres queue → SQS or Redis | Days | Sustained load past a few generations per second |

**Every expensive decision is in the data model, and none of it is inherited.** The
document-as-blob split, the immutable transformation log, and the idempotency rules are
stack-independent — identical on AWS, Cloudflare, or a single box.

Two rules keep the cheap decisions cheap. **Store `storage_key`, never a URL** — this is what
makes an S3→R2 migration a copy job rather than a data rewrite, and what lets a CDN slot in
front later. **Keep `owner_id` opaque `text`** — it holds whatever subject the IdP issues, so
swapping providers is a backfill, not a schema change.

### R2 specifics

boto3 speaks to R2 with an `endpoint_url` override, but not unmodified. Two client settings are
mandatory:

```python
# server/canvas/storage.py — NEW. Do not extend server/assets.py; it carries the
# timeline's AWS session, which the canvas has no reason to inherit.
from botocore.config import Config

_R2 = boto3.client(
    "s3",
    endpoint_url=f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    region_name="auto",                                 # R2 has exactly one region
    config=Config(
        request_checksum_calculation="when_required",   # REQUIRED
        response_checksum_validation="when_required",   # REQUIRED
    ),
)
```

Without those two `Config` lines every `PutObject` fails with `501 NotImplemented: Header
'x-amz-checksum-crc32' not implemented`. R2 implements CRC32 only as a *composite* checksum;
boto3 ≥1.36 sends a full-object CRC32 by default. This is the single most likely thing to cost
you an hour.

Also true of R2, and worth knowing before copying patterns out of `assets.py`:

- `PutBucketPolicy` is unimplemented — use presigned URLs for access, never a bucket policy.
- Object tagging is unimplemented.
- `PutBucketCors`, `CreateBucket`, and `HeadBucket` all work, so the bootstrap logic ports
  directly.

Egress is the real cost lever for a video product: S3 charges roughly $0.09/GB, R2 charges
nothing.

### Why Postgres and not the existing stores

`server/projects.py`, `server/productions.py`, and the job store all write JSON files to local
disk; `server/assets.py` uses DynamoDB. None of them supports transactions, unique constraints,
or conditional updates, and v0 needs all three: idempotency keys, version-conflict autosave, and
the status-claim guard. Every correctness guarantee in this document rests on one of them:

| Guarantee | Mechanism |
|---|---|
| One active generation per node | partial unique index |
| Daily spend cap | aggregate over a time window |
| Status claim | conditional `UPDATE` |
| Submit is atomic | insert + spend check in one transaction |
| Queue claim | `FOR UPDATE SKIP LOCKED` |
| Sweeper singleton | `pg_try_advisory_lock` |

**Nothing in this architecture wants a document store.** The canvas document is the one piece
that looks like one, but what makes it work is `version`-based optimistic concurrency, not query
flexibility — and JSONB in a relational row gives that plus the ability to write it in the same
transaction as everything else. The backend never queries into it.

**DynamoDB is therefore not part of v0 at all.** It backs exactly one thing in the repo today,
the legacy assets table, and that table is empty.

---

## 2. Repo changes

### Keep unmodified

`providers/*/api.py` — a working BytePlus adapter with correct model IDs, payload shapes, task
polling, error parsing, and a dry-run mode that *is* the mock provider. `mcps/` — thin FastMCP
wrapper, costs nothing, becomes the agent surface later. `server/auth.py` — Clerk is done.

### Change

```
server/
├── db/                    NEW      models.py, session.py
├── contracts/             NEW      document, operations, pricing (Pydantic)
├── canvas/                NEW      routes, adapters.py, storage.py, worker.py
├── contracts/base.py      NEW      CanvasModel — camelCase alias generator (§4)
├── assets.py              KEEP     timeline's S3 + DynamoDB. The canvas does not touch it.
├── projects.py            PARK     legacy timeline surface, leave it alone
├── studio.py              DELETE   unauthenticated route that calls paid providers
├── studio_options.py      DELETE   after its enum tables are folded into OPERATIONS
├── app.py                 EDIT     drop the asyncio job runner, mount canvas router
alembic/                   NEW
providers/                 FROZEN   new behaviour goes in server/canvas/adapters.py
studio/                    DELETE   see below
web/src/
├── app/canvas/[id]/page.tsx        NEW   "use client"
├── components/canvas/              NEW   ten components (§11)
├── lib/canvas/store.ts             NEW   document slice
├── contracts/generated.ts          NEW   generated, never hand-edited
└── components/editor/**            NONE  timeline untouched
```

**`studio/` is superseded.** The repo contains a third frontend — Next 15 on port 5174, already
on `@xyflow/react` v12 — that is a `localStorage` prototype of this canvas. It has no server
project, no auth, and no database, so there is nothing to migrate. Read it for interaction
behaviour if you like; **do not read it for patterns.** Its data model differs (`kind` not
`type`, client-side execution, six node kinds), and copying from it silently reintroduces
everything this document was written to fix. Delete it at the *start* of M5, before the new
canvas is written, together with `server/studio.py`, `server/studio_options.py`, and the
`studio` Makefile target, so there is never a window where two canvases exist.

`assets.py` stays where it is. Its S3 helpers are the reference implementation for
`server/canvas/storage.py` — presigning, checksum dedupe, signed URLs, bucket and CORS
bootstrap — but the canvas writes its own module against R2 rather than inheriting the DynamoDB
coupling. Four call sites in `app.py` keep using `assets.py` for the timeline surface.

**CORS is not already solved.** `CORSMiddleware` is mounted in `app.py`, but the bucket rule at
`assets.py:194` sets `AllowedMethods: ["GET", "HEAD"]`. Direct browser uploads need `PUT`, and
the call is wrapped in an `except ClientError` that only logs a warning — so a misconfigured
bucket fails silently and surfaces as a preflight error in the browser console. Verify the
origin lists include your dev port.

**Presigned PUT does not exist yet either.** `assets.py` has `presigned_content_url` (GET) and
`register_upload(content: bytes)`, which proxies bytes through the API — exactly what §5.3
forbids. `storage.py` needs:

```python
def presigned_upload_url(*, storage_key: str, content_type: str, ttl_seconds: int = 900) -> str:
    return _R2.generate_presigned_url("put_object", ExpiresIn=ttl_seconds,
        Params={"Bucket": bucket(), "Key": storage_key, "ContentType": content_type})
```

The client must send an identical `Content-Type` on the PUT or the signature fails with a 403
carrying no useful body.

---

## 3. Schema

Three tables. Nothing else exists in v0.

```sql
create extension if not exists "pgcrypto";

create type asset_type   as enum ('image', 'video', 'audio');
create type asset_status as enum ('pending', 'ready', 'failed');
create type tx_status    as enum ('queued', 'running', 'succeeded', 'failed');

-- The backend NEVER parses `document`. It reads and writes it whole.
create table projects (
  id          uuid primary key default gen_random_uuid(),
  owner_id    text not null,                 -- Clerk subject
  title       text not null default 'Untitled',
  document    jsonb not null,
  version     integer not null default 0,    -- optimistic concurrency for autosave
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

-- Append-only. Never UPDATE after status='ready'. Never DELETE.
create table assets (
  id                uuid primary key default gen_random_uuid(),
  project_id        uuid not null references projects(id) on delete cascade,
  transformation_id uuid,                    -- null for uploads
  type              asset_type not null,
  status            asset_status not null default 'pending',
  storage_key       text not null,           -- R2 object key, never a URL
  content_type      text not null,
  width             integer,
  height            integer,
  duration_ms       integer,
  metadata          jsonb not null default '{}',
  created_at        timestamptz not null default now()
);

-- Immutable execution log. `request` is the frozen snapshot.
create table transformations (
  id              uuid primary key default gen_random_uuid(),
  project_id      uuid not null references projects(id) on delete cascade,
  user_id         text not null,             -- denormalized; history queries are per-user
  node_id         text check (node_id ~ '^node_[a-zA-Z0-9_-]{12}$'),
  operation       text not null,
  provider        text not null,
  model_id        text not null,
  request         jsonb not null,
  status          tx_status not null default 'queued',
  provider_job_id text,
  error           jsonb,
  provider_response jsonb,                   -- terminal provider payload, verbatim (§5.6)
  idempotency_key text unique,
  retry_of_id     uuid references transformations(id),
  cost_credits    integer,                   -- captured now, charged later (§9)
  queued_at       timestamptz not null default now(),
  started_at      timestamptz,
  completed_at    timestamptz,

  -- Queue state. The table IS the queue; there is no external broker.
  visible_at      timestamptz not null default now(),   -- delayed re-poll
  lease_expires_at timestamptz,                         -- claimed-until; sweeper reclaims past it
  attempts        integer not null default 0
);

-- Operational levers. One row, three columns; the 2am kill switch.
create table system_flags (
  key        text primary key,
  value      jsonb not null,
  updated_at timestamptz not null default now()
);
insert into system_flags (key, value) values ('generation', '{"enabled": true}');

create index assets_project_idx on assets (project_id, created_at desc);
create index tx_active_idx      on transformations (status, started_at)
                                where status in ('queued', 'running');
create index tx_user_recent_idx on transformations (user_id, queued_at desc);

-- The queue claim. Partial, so it stays small no matter how long the log grows.
create index tx_claimable_idx on transformations (visible_at)
                              where status in ('queued', 'running');

-- One active generation per node, enforced by the DATABASE not the application.
-- An application-level SELECT-then-INSERT races: two simultaneous submits both
-- see nothing running and both insert. NULL node_ids do not conflict.
create unique index tx_one_active_per_node
  on transformations (node_id) where status in ('queued', 'running');
```

### Columns that aren't obvious

- `projects.version` — autosave concurrency. `UPDATE ... WHERE version = $2`; zero rows means a
  concurrent write.
- `assets.status` — the row exists before the bytes do, because the client PUTs directly to R2
  and reports back afterward. Without it the UI renders broken images.
- `transformations.visible_at` — replaces a broker's `DelaySeconds`. A worker that finds a job
  still running pushes this forward instead of re-enqueueing a message.
- `transformations.lease_expires_at` — replaces a broker's visibility timeout. A worker sets it
  on claim; the sweeper reclaims anything past it, which is how a killed worker's job resumes.
- `assets.metadata` — a JSONB catch-all so future per-asset fields need no migration.
- `transformations.node_id` — opaque text with a format CHECK, deliberately **no** foreign key.
  Nodes live in the document, and orphaned node IDs are the correct outcome: cascade would
  shred history, set-null would sever it. The CHECK catches format drift, which is the real
  risk.
- `transformations.cost_credits` — see §9. The one thing that cannot be backfilled.

### Migrations

Alembic. Three rules: never edit an applied migration, every change additive first (add
nullable → backfill → add constraint), renames use expand-and-contract. Read and edit every
autogenerated file before applying — autogenerate misses enums, server defaults, and CHECK
constraints.

### Migrating existing data

**There is none.** The DynamoDB assets table and the S3 bucket are both empty; the JSON project
files are timeline documents, not canvas documents. Do not write a backfill script, a dual-read
path, or an id-compatibility shim.

This is a one-time property worth recording: because both asset stores are empty, unifying the
canvas and timeline asset stores later is a pure code change with no data migration. That option
stays free indefinitely — take it when the timeline is next touched, not during v0.

---

## 4. Contracts

Pydantic is the source of truth. TypeScript is generated.

```bash
python -m server.contracts.export > web/src/contracts/schema.json
npx json-schema-to-typescript web/src/contracts/schema.json > web/src/contracts/generated.ts
git diff --exit-code web/src/contracts/    # CI fails on drift
```

Commit the generated file. The exit-code check turns "frontend and backend disagree about the
document shape" from a runtime mystery into a red build.

**The wire format is camelCase.** Every contract model inherits one base, so the generated
TypeScript matches idiomatic frontend code with no hand-written mapping layer:

```python
# server/contracts/base.py
class CanvasModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel,
                              populate_by_name=True,
                              serialize_by_alias=True)
```

**The JSONB document is stored in wire form.** That is what makes §0.1's read-and-write-whole
rule hold — the backend never re-keys the blob it persists.

### The canvas document

```python
# server/contracts/document.py
NodeType = Literal["text", "image", "video", "audio"]

class TextSegment(BaseModel):
    type: Literal["text"]
    text: str

class ReferenceSegment(BaseModel):
    type: Literal["reference"]
    node_id: str
    role: str = "reference"

PromptSegment = Annotated[TextSegment | ReferenceSegment, Field(discriminator="type")]

class GenerationConfig(CanvasModel):
    operation: str                            # EXPLICIT, never inferred from edges
    model_id: str | None = None
    aspect_ratio: Literal["16:9","9:16","1:1"] = "16:9"
    duration_sec: int = Field(5, ge=4, le=12)  # BytePlus clamps to 4-12
    resolution: Literal["480p","720p","1080p"] = "720p"
    voice: str | None = None                  # text_to_speech
    gender: str | None = None                 # text_to_music

class NodeData(CanvasModel):
    title: str | None = None
    text_content: str | None = None           # text nodes
    prompt: list[PromptSegment] = []
    config: GenerationConfig
    asset_id: UUID | None = None              # current displayed output
    active_transformation_id: UUID | None = None
    approved: bool = False                    # scene approval; image/video nodes only
    story_order: int | None = None            # 1-based, compacted on change

class CanvasNode(BaseModel):
    id: str = Field(pattern=r"^node_[a-zA-Z0-9_-]{12}$")
    type: NodeType
    position: Position
    data: NodeData

class CanvasEdge(BaseModel):
    id: str
    source: str
    target: str
    target_handle: str                        # the input role

class CanvasDocument(BaseModel):
    schema_version: Literal[1] = 1
    nodes: list[CanvasNode] = []
    edges: list[CanvasEdge] = []
    viewport: Viewport = Viewport()
```

`schema_version` is a `Literal`, so future versions become a discriminated union and old
documents fail loudly rather than silently mis-parsing.

### Operation registry

Declares, per operation, what its inputs are called and which are required. The same data is
needed in four places, and if any two disagree you get bugs with no obvious cause: rendering
handles, validating connections, checking required inputs before submit, and re-validating
server-side.

```python
# server/contracts/operations.py
class OperationSpec(CanvasModel):
    provider: Literal["seedream", "seedance", "mureka", "fish_audio"]
    output_type: Literal["image", "video", "audio"]
    inputs: list[InputRole]
    default_model: str
    config_fields: list[str]        # drives the inspector AND submit-time validation

OPERATIONS = {
    "text_to_image": OperationSpec(
        provider="seedream", output_type="image",
        inputs=[InputRole("reference", accepts=["image"], required=False, multi=False),
                InputRole("context",   accepts=["text"],  required=False, multi=True)],
        default_model="seedream-5-0-lite-260128",
        config_fields=["aspect_ratio"],
    ),
    "image_to_video": OperationSpec(
        provider="seedance", output_type="video",
        inputs=[InputRole("start_frame", accepts=["image"], required=True,  multi=False),
                InputRole("context",     accepts=["text"],  required=False, multi=True)],
        default_model="seedance-1-5-pro-251215",
        config_fields=["resolution", "duration_sec"],      # ratio follows the frame
    ),
    "text_to_video": OperationSpec(
        provider="seedance", output_type="video",
        inputs=[InputRole("context", accepts=["text"], required=False, multi=True)],
        default_model="seedance-1-5-pro-251215",
        config_fields=["aspect_ratio", "resolution", "duration_sec"],
    ),
    "text_to_music": OperationSpec(
        provider="mureka", output_type="audio",
        inputs=[InputRole("context", accepts=["text"], required=False, multi=True)],
        default_model="auto",
        config_fields=["gender"],
    ),
    "text_to_speech": OperationSpec(
        provider="fish_audio", output_type="audio",
        inputs=[InputRole("script", accepts=["text"], required=True, multi=False)],
        default_model="s2.1-pro-free",
        config_fields=["voice"],
    ),
}

DEFAULT_OPERATION = {"image": "text_to_image", "video": "text_to_video",
                     "audio": "text_to_music"}
```

**`provider` lives here, not in the request.** A client should not get to name the provider it
bills you for; submit reads `spec.provider`.

**`config_fields` is the single source of truth for what a node exposes.** The inspector renders
exactly this list and submit rejects any config key absent from it. That is why `text_to_image`
has no `resolution` — Seedream's presets do not map cleanly onto 480p/720p, and an image node
that pretends otherwise is lying to the user.

**`reference` is `multi: False` in v0.** `seedream.image_to_image(image_path_or_url: str)` takes
one image; multi-reference is both unverified model behaviour and an unwritten provider
signature. One character to flip when both change.

**Audio nodes are terminal leaves.** No operation accepts an `audio` input role, so the `audio`
port type needs a colour and a label but adds no edge rules — it simply never validates as a
target. Lip-sync and scored clips are consequently out of v0; that is the honest boundary.

Roles are plain strings, not an enum — `end_frame`, `style_ref`, and `mask` are coming and an
enum migration per addition is friction with no payoff.

**Text nodes are input-only.** They feed context to other nodes and have no generate button.
`operation_for_node` returns `None` for them. There is deliberately no `text_to_text`.

Export `OPERATIONS` as JSON alongside the schema so the frontend imports the same data.

### Flattening a prompt

Converts the structured prompt into the string sent to the model **and** the positionally
matched inputs. Generate both together or the indices won't line up.

```python
def flatten_prompt(node: CanvasNode, doc: CanvasDocument):
    inputs, counters, text = [], {"image": 0, "video": 0}, ""
    for seg in node.data.prompt:
        if seg.type == "text":
            text += seg.text
            continue
        src = next((n for n in doc.nodes if n.id == seg.node_id), None)
        if src is None:
            continue                          # deleted node: drop the reference
        if src.type == "text":
            text += src.data.text_content or ""     # inline verbatim
        else:
            n = counters[src.type] = counters[src.type] + 1
            text += f"[{src.type} {n}]"
            inputs.append({"role": seg.role, "ordinal": n, "asset_id": src.data.asset_id})
    return text, inputs
```

**Do not auto-generate descriptions for image or video references.** The asset is already
passed to the model as a real input; a caption is redundant at best and fights the actual image
when the two disagree. The indexed token is the convention multi-reference models expect.

---

## 5. API

All routes under `/v1`. Clerk subject as `owner_id`.

| Method | Path | Response |
|---|---|---|
| `POST` | `/projects` | `{ project }` |
| `GET` | `/projects` | `{ projects }` (no document) |
| `GET` | `/projects/:id` | `{ project, document, assets, active_transformations }` |
| `PUT` | `/projects/:id/document` | `{ version }` or `409` |
| `POST` | `/projects/:id/assets` | `{ asset_id, upload_url }` |
| `POST` | `/assets/:id/complete` | `{ asset }` |
| `GET` | `/assets/:id/url` | `302` to a signed R2 URL |
| `POST` | `/projects/:id/transformations` | `{ transformation }` |
| `GET` | `/projects/:id/transformations?status=active` | `{ transformations }` |
| `POST` | `/transformations/:id/retry` | `{ transformation }` |

No webhook route — ModelArk has no callback endpoint, so completion is poll-driven (§7).

### 5.1 Hydration and asset scoping

`GET /projects/:id` is the single load call. It returns the document, **only the assets the
document references**, and every transformation the client needs to resolve node state.

```python
referenced = {n.data.asset_id for n in document.nodes if n.data.asset_id}
# plus outputs of any transformation returned below
```

A project with 300 generations but 5 nodes returns 5 assets, not 300.

**This is the one sanctioned exception to §0.2.** It reads two fields and does not interpret
structure. No other endpoint may parse the document.

### Which transformations to return

Not just the active ones. Return the union of:

1. All `queued` and `running` transformations for the project.
2. Every transformation whose ID appears as an `active_transformation_id` on a node — **in any
   status.**

The second clause is not optional. Without it, a generation that completes while the tab is
closed is orphaned forever: the node still carries `active_transformation_id`, renders a
spinner on reload, polls the active list, gets nothing, and spins indefinitely — while the
asset sits in R2 referenced by nothing. Starting a three-minute video and closing the laptop is
the single most common real flow, so this path must work.

On load the client reconciles: for any returned transformation in a terminal status, attach its
output asset to the node and clear `active_transformation_id`, which triggers an autosave.

Also drop any active transformation whose `node_id` matches no node — the node was deleted
mid-generation. The asset is orphaned, which is acceptable; a spinner attached to nothing is
not.

### 5.2 Document write

```python
result = await session.execute(
    update(Project)
    .where(Project.id == pid, Project.version == body.version)
    .values(document=body.document, version=Project.version + 1)
    .returning(Project.version)
)
if result.first() is None:
    raise HTTPException(409, "version_conflict")
```

On 409 the client refetches and warns. No merge.

### 5.3 Upload

Never proxy bytes through the API. Client posts metadata, gets a `pending` row and a presigned
PUT (15 min), uploads directly to R2, measures dimensions locally, posts `/complete`.

Storage key: `{project_id}/assets/{asset_id}.{ext}`.

### 5.3.1 Authorization

**Make authorization structural, not per-endpoint discipline.** Two FastAPI dependencies, used
by every route that touches a project or an asset. If a handler receives its object from a
dependency, it cannot forget the check.

```python
async def owned_project(project_id: UUID, user_id: str = Depends(current_user_id),
                        session=Depends(db)) -> Project:
    p = await session.scalar(select(Project).where(
        Project.id == project_id, Project.owner_id == user_id))
    if p is None:
        raise HTTPException(404)          # 404, not 403 — do not confirm existence
    return p

async def owned_asset(asset_id: UUID, user_id: str = Depends(current_user_id),
                      session=Depends(db)) -> Asset:
    a = await session.scalar(select(Asset).join(Project).where(
        Asset.id == asset_id, Project.owner_id == user_id))
    if a is None:
        raise HTTPException(404)
    return a
```

**`current_user_id` is not a dependency.** Its real signature is
`current_user_id(auth: RequestState | None) -> str`, so `Depends(current_user_id)` will not
resolve. Wrap it once and leave the existing callers alone:

```python
def _user_id(auth: AuthUser) -> str: return current_user_id(auth)
CurrentUser = Annotated[str, Depends(_user_id)]
```

With Clerk unconfigured it returns the literal `"local"`, so every developer shares one
`owner_id` and the two cross-user checks below pass without testing anything. Make it settable —
`os.getenv("RENDERHAUS_DEV_USER", "local")` — so those checks are runnable with two terminals.

**Asset ownership changes shape in the port.** The DynamoDB `Asset` carried `user_id` and
`get_asset_for_user` compared it directly. The Postgres asset has only `project_id`, so every
asset read must join through `projects.owner_id`. Missing this on `GET /assets/:id/url` is a
straightforward IDOR — anyone holding an asset UUID reads anyone else's video.

Four places need it, and the presign one is the easiest to overlook:

| Endpoint | Check |
|---|---|
| `POST /projects/:id/assets` | `owned_project` — otherwise anyone writes into your bucket namespace |
| `POST /assets/:id/complete` | `owned_asset` |
| `GET /assets/:id/url` | `owned_asset`, 1-hour signed TTL |
| `POST /projects/:id/transformations` | `owned_project` |

Submit additionally validates `Asset.project_id == project_id` (§5.5), which blocks referencing
your *own* asset from a different project — a separate concern from ownership.

### 5.4 Spend guards

v0 has no credit balance, so these are the **only** thing between a UI bug and an unbounded
provider bill. Three layers, each catching what the one above misses.

```python
MAX_CONCURRENT_PER_USER = 3        # bounds parallel burn
DAILY_CREDIT_CAP        = 2_000    # bounds serial burn

async def check_spend_guards(session, user_id):
    # Layer 1 — global kill switch. Cached 10s in-process so it costs nothing
    # per request, and flipping the row halts all generation without a deploy.
    if not await generation_enabled(session):
        raise HTTPException(503, "generation_paused")

    # Layer 2 — concurrency. Stops a runaway loop firing hundreds in parallel.
    in_flight = await session.scalar(
        select(func.count()).select_from(Transformation).where(
            Transformation.user_id == user_id,
            Transformation.status.in_(["queued", "running"])))
    if in_flight >= MAX_CONCURRENT_PER_USER:
        raise HTTPException(429, "too_many_active_generations")

    # Layer 3 — rolling daily spend. Concurrency alone does not stop a user
    # serially firing 500 generations a day, three at a time.
    spent = await session.scalar(
        select(func.coalesce(func.sum(Transformation.cost_credits), 0)).where(
            Transformation.user_id == user_id,
            Transformation.queued_at > func.now() - text("interval '24 hours'"),
            Transformation.status != "failed"))
    if spent >= DAILY_CREDIT_CAP:
        raise HTTPException(429, "daily_limit_reached")
```

Layer 3 is free because `cost_credits` is already written at submit (§9). This is the first
v0 payoff for capturing cost early, not just a v1 hook.

**These checks race, deliberately.** Two concurrent submits can both pass. With a concurrency
cap of 3 the overshoot is bounded to a few generations, and locking to close a gap that small
is not worth the complexity. Set the caps low enough that the overshoot is affordable.

**The kill switch earns its table.** When you notice a bug at 2am, an env var means a redeploy;
a row means a single `UPDATE`. Three columns is a fair price for that.

Alert on aggregate daily spend independently of these caps. The guards protect you from one
runaway user; only an alert tells you every user got 3x more expensive after a model change.

### 5.5 Submit

```python
async def submit(session, project_id, user_id, body):
    spec = OPERATIONS.get(body.operation)
    if not spec:
        raise HTTPException(400, "unknown_operation")

    await check_spend_guards(session, user_id)

    for key in body.request.config.model_fields_set:
        if key not in spec.config_fields and key not in ("operation", "model_id"):
            raise HTTPException(400, f"config_not_supported:{key}")

    for role in spec.inputs:
        supplied = [i for i in body.request.inputs if i.role == role.role]
        if role.required and not supplied:
            raise HTTPException(400, f"missing_required_input:{role.role}")
        if not role.multi and len(supplied) > 1:
            raise HTTPException(400, f"too_many_inputs:{role.role}")

    asset_ids = [i.asset_id for i in body.request.inputs if i.asset_id]
    if asset_ids:
        found = await session.scalars(select(Asset.id).where(
            Asset.id.in_(asset_ids), Asset.project_id == project_id,
            Asset.status == "ready"))
        if len(set(found)) != len(set(asset_ids)):
            raise HTTPException(400, "invalid_asset_reference")

    stmt = insert(Transformation).values(
        project_id=project_id, user_id=user_id, node_id=body.node_id,
        operation=body.operation, provider=spec.provider, model_id=body.model_id,
        request=body.request.model_dump(),
        cost_credits=estimate_cost(body.operation, body.model_id, body.request.config),
        idempotency_key=body.idempotency_key, retry_of_id=body.retry_of_id,
    ).on_conflict_do_nothing(index_elements=["idempotency_key"]).returning(Transformation)

    try:
        tx = (await session.execute(stmt)).scalar_one_or_none()
        if tx is None:                        # idempotent replay
            return await session.scalar(select(Transformation).where(
                Transformation.idempotency_key == body.idempotency_key))
        await session.commit()
    except IntegrityError as exc:
        # tx_one_active_per_node fired: this node already has a generation in
        # flight. Without the index, the second submit would overwrite
        # active_transformation_id, the first job would still run and complete,
        # and you would have paid for a result nobody ever sees.
        await session.rollback()
        if "tx_one_active_per_node" in str(exc.orig):
            raise HTTPException(409, "node_already_generating")
        raise

    return tx                                 # the INSERT *is* the enqueue
```

**The `execute` must be inside the `try`.** With asyncpg the partial-unique-index violation
raises at `session.execute`, not at `commit()`; put the execute outside and the
`node_already_generating` branch is unreachable.

**There is no `send_message` here.** The row is the queue entry, committed in the same
transaction as the spend check, so "insert succeeded but enqueue failed" — the classic source of
stranded jobs — cannot happen. The worker picks it up on its next tick.

The backend never opens `projects.document`. Input resolution happened on the client.

---

### 5.6 Data capture for v1 observability

Same philosophy as cost capture (§9): **build no dashboards in v0, but record the data points
that cannot be reconstructed later.** Tooling is cheap to add; history is not.

**Already in the schema, no work needed.** `queued_at` / `started_at` / `completed_at` give
queue latency and provider latency. `status` gives success rate. `cost_credits` gives spend.
`request` snapshots model, operation, and config. `provider_job_id` cross-references BytePlus
support tickets. Together these answer most of what you will ask in v1 — success rate by model,
p50/p95 latency, cost per user per day, failure reasons — with a `GROUP BY` and no migration.

**Two things that must be captured deliberately:**

`provider_response` stores the terminal provider payload verbatim. BytePlus returns a `usage`
block that the existing provider code already extracts and discards. Storing the whole payload
rather than picking fields means v1 can mine it for questions you have not thought of yet, and
it is the only record of what actually happened on their side. Payloads are small.

`error` must carry the provider's own code and message, not just ours:
`{code, message, retryable, provider_code, provider_message}`. "Generation failed" is useless
in aggregate; "42% of failures are content-policy rejections on human faces" is a product
decision.

**The correlation ID is the part that is expensive to retrofit**, because adding it later means
touching every call site. From day one, `transformation_id` goes on every structured log line
from submit through completion, alongside `project_id` and `user_id`. Log provider request and
response bodies at debug level with the API key redacted — when a generation fails for an
unclear reason, that is the only evidence you will have.

Wire Sentry on both the API and the worker with `transformation_id` as a tag. That is the whole
v0 observability budget.

**Not captured, deliberately:** client-side product analytics. Node creation, edge wiring, and
session behaviour are not in the transformation table, but most product questions ("do people
use reference images?", "how many nodes per project?") are answerable from `request` and the
document. Add PostHog when you have a question the database cannot answer.

---

## 6. Provider integration

**The canvas calls `providers/*/api.py` functions directly, not through MCP.** MCP exists for
tool *selection*, which the canvas doesn't do — the user picks the operation explicitly. Keep
MCP as a parallel surface for the agent later. Same functions, two consumers.

**All of it goes through one new file: `server/canvas/adapters.py`.** `providers/*/api.py` is
frozen — it is shared with the timeline surface and the MCP gateway — so the adapter is new code
beside it, never a modification. It owns four things that would otherwise scatter through the
worker:

```python
async def submit(tx, inputs) -> ProviderResult:
    return await to_thread(_submit, tx, inputs)     # every provider fn is sync httpx

def _submit(tx, inputs):
    cfg, prompt = tx.request["config"], tx.request["resolvedPrompt"]
    image = _first_image_url(inputs)                # None when no image input is wired

    match (tx.operation, image):
        case ("text_to_image", None):
            raw = seedream.text_to_image(prompt=prompt, model=tx.model_id, ...)
        case ("text_to_image", url):                # a reference makes it an edit
            raw = seedream.image_to_image(image_path_or_url=url, prompt=prompt, ...)
        case ("text_to_video", None):
            raw = seedance.text_to_video(prompt=prompt, model=tx.model_id, ...)
        case ("image_to_video", url) if url:
            raw = seedance.image_to_video(image_path_or_url=url, prompt=prompt, ...)
        case ("text_to_music", _):
            raw = mureka.create_song_from_prompt(prompt=prompt, model=tx.model_id,
                                                 gender=cfg.get("gender"))
        case ("text_to_speech", _):
            raw = fish_audio.generate_speech(prompt, cfg["voice"],   # positional!
                                             "mp3", tx.model_id)
        case _:
            raise ValueError(f"no adapter for {tx.operation}")

    return _normalize(raw, spec=OPERATIONS[tx.operation])
```

1. **Dispatch.** `text_to_image` with a `reference` wired is Seedream's `image_to_image`. That
   branch lives in one `match`, not scattered through the worker.
2. **`to_thread` on everything.** Every provider function is synchronous `httpx.Client`. Without
   `to_thread` a live Seedream call blocks the worker's event loop for its full 180s timeout and
   every async SQLAlchemy session on that loop stalls with it.
3. **Output normalisation.** Seedream returns a URL; Seedance, Mureka, and Fish Audio return
   local file paths. One place converts, then streams to R2.
4. **Config mapping.** `resolution` → Seedream `size`, `duration_sec` → `duration_seconds`.

**Output goes to R2.** `_download_video` writes to a local `Path`. The adapter uploads from that
path rather than modifying the provider function, so the MCP path keeps working.

**Never call the blocking helpers.** `text_to_video_and_wait` and `wait_for_video_task` block.
Use `text_to_video` / `image_to_video` to submit and `get_video_task` to poll.
`providers/registry.py` already forbids exposing these as tools; the same rule applies here.

**Classify errors.** `_provider_error` parses BytePlus's `error.code`. Map to
`{code, message, retryable}`. Transient (5xx, timeout, rate limit) retries invisibly up to 3
times. Permanent (content policy, invalid input) fails immediately with the provider's message
preserved.

### Image and video complete differently

**Video (Seedance) is asynchronous**: create a task, poll for the result. **Image (Seedream) is
synchronous**: the response carries the image URL or base64 directly. The poll loop in §7
assumes async, so the consumer must branch:

```python
result = await adapters.submit(tx, inputs)
if result.is_terminal:                # image or speech: done in one call
    await complete(session, tx, result)
else:                                 # video or music: task id, start the poll loop
    await mark_running(session, tx, result.provider_job_id)
    await defer(session, tx, seconds=5)
```

Everything downstream — assets-before-claim, deterministic asset IDs, the sweeper — is
unchanged. Only the entry into the poll loop is conditional. A synchronous transformation never
enters `running` for long, so the sweeper's `running` cases simply never fire for images.

**`is_terminal` splits by provider, not by media type.** Seedream (image) and Fish Audio
(speech) are synchronous; Seedance (video) and Mureka (music) are task-based. `_normalize` sets
the flag so the worker never needs to know which is which.

**Mureka's poll depends on local disk.** `query_task()` reads job metadata written by
`_remember_task()` at submit time to decide which endpoint to query. On a worker that did not
perform the submit, that file is absent and it silently queries the wrong endpoint. Pre-seed it
with the public helper immediately before polling:

```python
write_task_meta(job_id, {"kind": "song"})    # we only ever call create_song_from_prompt
raw = query_task(job_id=job_id, download=True)
```

Seedream also takes `size` (`"2K"`, or explicit `"1024x1024"`) rather than the video models'
`resolution`. The adapter maps `GenerationConfig.resolution` onto it via the provider's existing
`_size_for_ratio`; do not add a second field to the config.

### What the provider layer already confirms

- Base URL `https://ark.ap-southeast.bytepluses.com/api/v3`
- `POST /contents/generations/tasks`, `GET /contents/generations/tasks/{id}`
- Body: `model`, `content` (array of `{type: text}` / `{type: image_url}`), `ratio`, `duration`,
  `resolution`, `watermark`, `generate_audio`
- **Duration clamped to 4–12s**, silently. Pydantic must reject out-of-range before it reaches
  the provider
- Seedance 2.0 T2V rejects `service_tier`
- Images may be base64 data URLs, so a signed asset URL isn't strictly required
- `ModelNotOpen` means activate the model in the Ark Console — surface it as a distinct,
  actionable error
- **`SEEDANCE_DRY_RUN` defaults to `true` and returns a synthetic task. This is your mock
  provider.** Build the entire status machine against it at zero cost

---

## 7. Job execution

One image, two entrypoints:

```
uvicorn server.app:app          # API
python -m server.worker         # consumer + sweeper
```

### Claiming work

The transformations table is the queue. One statement claims a job, takes a lease, and makes it
invisible to every other worker — the same primitive a broker gives you, minus the broker:

```python
CLAIM = text("""
    update transformations set
        lease_expires_at = now() + interval '60 seconds',
        attempts         = attempts + 1
    where id = (
        select id from transformations
        where status in ('queued', 'running')
          and visible_at <= now()
          and (lease_expires_at is null or lease_expires_at < now())
        order by visible_at
        for update skip locked
        limit 1
    )
    returning *
""")
```

`SKIP LOCKED` is what makes this safe under concurrency: two workers running the statement at
the same instant take different rows rather than blocking on each other. The worker loops on a
one-second tick when the claim comes back empty.

### Poll loop

ModelArk has no webhook, so the worker defers itself rather than re-enqueueing a message.
`visible_at` is the delay; there is no 15-minute ceiling.

```python
result = await adapters.poll(tx)
if result.status == "running":
    if tx.attempts > 120: return await fail(tx, "provider_timeout")
    await defer(session, tx, seconds=backoff(tx.attempts))   # 5, 5, 10, cap 15s
else:
    await complete(session, tx, result)
```

```python
async def defer(session, tx, *, seconds):
    await session.execute(update(Transformation).where(Transformation.id == tx.id)
        .values(visible_at=func.now() + timedelta(seconds=seconds),
                lease_expires_at=None))          # release the lease
```

**The lease replaces a visibility timeout, and the sweeper replaces a DLQ.** A worker killed
mid-job leaves `lease_expires_at` in the past; the next claim picks the row up. A job that fails
repeatedly is caught by the `attempts` ceiling and the sweeper's timeout rules, which you are
building regardless.

### Completion — order matters

**Write assets before claiming the status transition.** Claiming first strands a `succeeded`
row with no outputs if the download fails, and the guard then blocks any repair. Writing assets
first means a failed download leaves the row `running` and the sweeper retries naturally.

That inversion risks duplicate assets if two workers race, closed by a deterministic asset ID:

```python
async def complete(session, tx, result):
    if result.status == "succeeded":
        for i, out in enumerate(result.outputs):
            asset_id = uuid5(ASSET_NS, f"{tx.id}:{i}")     # deterministic
            key = f"{tx.project_id}/assets/{asset_id}.{ext_for(out.content_type)}"
            await stream_to_s3(out.url, key)               # raises → stays 'running'
            await session.execute(insert(Asset).values(
                id=asset_id, project_id=tx.project_id, transformation_id=tx.id,
                status="ready", storage_key=key, ...
            ).on_conflict_do_nothing())

    # Claim LAST. Zero rows means someone already handled it.
    await session.execute(update(Transformation)
        .where(Transformation.id == tx.id,
               Transformation.status.in_(("queued", "running")))
        .values(status=result.status, error=result.error,
                provider_response=result.raw, completed_at=func.now(),
                lease_expires_at=None))
```

**The claim must accept `queued`, not just `running`.** Synchronous operations — Seedream images
and Fish Audio speech — go straight from `queued` to terminal without passing through
`mark_running`. Guard on `running` alone and the `UPDATE` matches zero rows: the assets are
written, the row never goes terminal, the sweeper's stale-`queued` rule re-claims it, and you pay
the provider twice. The deterministic asset ID hides the duplicate asset but not the duplicate
spend.

Download the result into R2 rather than storing the provider URL — those expire in 24h–7d, and
storing them gives you a canvas that silently rots.

### Sweeper

An interval loop in the same worker, guarded by `pg_try_advisory_lock` so multiple replicas
don't duplicate work. It reconciles every boundary where a crash leaves inconsistency:

| Condition | Cause | Action |
|---|---|---|
| `queued`, `visible_at` past, lease expired | Worker died before claiming or mid-claim | Reclaim |
| `running`, null `provider_job_id`, older than 60s | Provider accepted, DB write failed — handle lost | Fail |
| `running`, no progress 2min | Lost message, or normal | Poll; complete if terminal |
| `running`, older than 15min | Provider stalled | Fail `provider_timeout` |
| `assets.status='pending'` older than 1h | Presign issued, `/complete` never called | Delete row and R2 object |

**Nothing that exists only in a queue message is durable.** With the queue *in* the database
that property is free rather than earned — there is no message to lose, and every recovery rule
above is a query over rows that are already committed.

### Idempotency inventory

Every retryable path needs a natural key. If a new write path isn't in this table, it's a bug
waiting for a retry.

| Path | Key | Enforced by |
|---|---|---|
| Submit | client `idempotency_key` | unique index |
| Asset on completion | `uuid5(tx_id:ordinal)` | PK + `on_conflict_do_nothing` |
| Status transition | status is `running` | conditional `UPDATE` |
| Document write | `version` | conditional `UPDATE` |

---

## 8. Failure and retry

**Retry creates a new row**, never resets the old one — resetting mutates a record §0.3 calls
immutable and destroys the audit trail. `POST /transformations/:id/retry` copies the frozen
`request` verbatim, mints a **new** `uuid4` idempotency key, and sets `retry_of_id`.

Reusing the original key means the unique constraint silently returns the same failed row and
the user clicks Retry forever with nothing happening. This is the most likely bug in this
section.

Two user actions fall out with no extra UI: **Retry** resubmits the snapshot (right for
transient failures), and **editing the prompt then Generate** re-resolves from current state
(right when the input was rejected).

| Node state | Shows |
|---|---|
| `idle` | Generate button |
| `queued` / `running` | Spinner, elapsed time |
| `failed` | Error message, Retry button |
| `succeeded` | The asset, Regenerate button |

`active_transformation_id` keeps pointing at a failed transformation so a reload still shows the
error; cleared on retry or dismiss.

---

## 9. Cost capture

**Capture now, charge later.** No balance checks, no ledger, no Stripe in v0 — but
`cost_credits` must be written from the first generation, because the price *at the time* is
the one thing that cannot be reconstructed later.

```python
# server/contracts/pricing.py — pure, no DB access
def estimate_cost(operation, model_id, config) -> int:
    rate = MODEL_RATES.get(model_id, MODEL_RATES["__default"])
    if OPERATIONS[operation].output_type == "video":
        return ceil(rate.per_second * config.duration_sec * RES_MULT[config.resolution])
    return rate.flat
```

Credits are an internal unit. **Pick a peg (e.g. 100 credits = $1) and never change it** — change
the rates instead, or every historical `cost_credits` silently means something different and
revenue analysis breaks with no error.

Your own cost in USD is *not* stored, because `request` snapshots the model and duration, so it
can be recomputed later from a cost table. Only the retail price is unrecoverable.

The eventual system is an append-only `credit_ledger` plus a cached `user_credits.balance` with
`CHECK (balance >= 0)`, using reserve-then-settle: deduct an estimate in the same transaction as
the submit, refund on permanent failure. Charging on completion would let a user with 300
credits fire twenty 100-credit generations in parallel. **None of it requires changing
`transformations`** — that is the entire point of capturing cost now.

---

## 10. Explicitly out of scope

Named so they don't get half-built. Each is additive later with no schema or architecture
change.

- **First/last-frame video.** Adding `end_frame` is one entry in the operation registry plus an
  adapter branch. Verify ModelArk accepts a second role-tagged image before designing UI.
- **Undo/redo.** Document-only, via `zundo`. Additive.
- **Cancel.** Terminal status plus a provider call. Additive.
- **Credit ledger, balances, Stripe.** §9.
- **Rate limiting.** Credits become the real rate limit for generation.
- **Asset garbage collection.** Deleting the wrong asset breaks history irreversibly; the rules
  are easier to get right with usage data.
- **Multiplayer.** The document-as-blob design is Yjs-compatible. Until then, two tabs is
  last-write-wins with a version conflict.
- **CDN for asset delivery.** v0 serves assets via a signed redirect per asset, so a 50-node
  canvas fires 50 redirects and pulls video from R2 directly. Slow and expensive at any real
  usage. CloudFront in front of S3, or an R2 public custom domain, fixes it — and slots in
  cleanly *because* `storage_key` is a key rather than a URL. Expect to want this early; it is
  out of v0 scope only because it changes no code.
- **Vision-model captions on assets.** §4.

---

## 11. Frontend

The canvas is a new route beside the timeline editor. Everything in `components/editor/` is
untouched.

### Styling

**Tailwind only. One stylesheet.** `web/` already runs Tailwind 4 and its existing components
use raw utility classes on a `neutral-*` dark palette with `lucide-react` icons; the canvas
follows that convention exactly. The deleted `studio/` app carried a 1,229-line hand-rolled
stylesheet — it is not ported in any form. The entire design system is a `@theme` block:

```css
/* web/src/app/globals.css */
@import "tailwindcss";
@import "@xyflow/react/dist/style.css";   /* vendor: pane transform + handle positioning */

@theme {
  --color-port-text:   var(--color-neutral-400);
  --color-port-image:  var(--color-indigo-400);
  --color-port-video:  var(--color-teal-400);
  --color-port-audio:  var(--color-pink-400);

  --color-status-queued:    var(--color-neutral-400);
  --color-status-running:   var(--color-indigo-400);
  --color-status-succeeded: var(--color-emerald-400);
  --color-status-failed:    var(--color-red-400);
}

.canvas-root {                             /* dark only, scoped to this route */
  color-scheme: dark;
  --xy-background-color: var(--color-neutral-950);
  --xy-edge-stroke: var(--color-neutral-600);
  --xy-edge-stroke-selected: var(--color-indigo-400);
}
```

Two rules. **No `.css` files beyond `globals.css`** — if a style needs a name, it needs a
component. **Tokens exist only for port and status colours**, because each is referenced from
three places (handle, edge, badge) and they must agree; everything else is a literal utility
class at the point of use. Do not invent tokens for spacing, radius, or type scale.

Handles take `className` directly, so port colours need no stylesheet — but the `!` prefixes are
required to beat React Flow's vendor specificity, which is the one place the vendor CSS leaks:

```tsx
<Handle id={role.role} type="target" position={Position.Left}
        className="!h-3 !w-3 !border-2 !border-neutral-950 !bg-port-image" />
```

### Ten components

Driving the node off `OperationSpec` collapses what would otherwise be one component per node
type into one:

```
components/canvas/
  CanvasShell.tsx        layout: rail | pane | inspector, strip along the bottom
  CanvasPane.tsx         ReactFlowProvider + ReactFlow, drop handling, cycle-guarded onConnect
  ToolRail.tsx           rail groups -> addNode(operation)
  NodeCard.tsx           ONE node component; renders by OperationSpec.output_type
  NodePorts.tsx          handles from OperationSpec.inputs + output_type
  NodeStatusBadge.tsx    queued/running/succeeded/failed + retry
  AssetPreview.tsx       <img> | <video> | <audio> switch, keyed off asset_type
  NodeInspector.tsx      renders exactly OperationSpec.config_fields
  SequenceStrip.tsx      approved scenes, ordered
  CanvasHeader.tsx       project name, save state, credit balance
```

An `<audio controls>` element on a node card is a legitimate v0 answer. Do not build a waveform.

**Readiness before submit.** Missing required inputs become sentences — "Add a prompt first." —
and disable the generate button, rather than producing a failing submit. Derive them from
`OperationSpec.inputs`.

**Undo/redo** via `zundo` on the document slice. Document-only, no backend, 50 steps.

**React Flow is a view, not the state.** Run it fully controlled off Zustand:

```tsx
<ReactFlow nodes={nodes} edges={edges}
  onNodesChange={applyNodeChanges} onEdgesChange={applyEdgeChanges}
  onConnect={onConnect} isValidConnection={isValidConnection}
  nodeTypes={nodeTypes} onlyRenderVisibleElements fitView />
```

Zustand holds the document. TanStack Query holds server state. Don't mix them.

### Connection validation

Driven by the shared `OPERATIONS` registry so frontend and backend agree on what's legal. Check
that the target role exists, that it accepts the source's output type, and — on day one —
**guard against cycles with a visited-set DFS.** Users will connect a node to itself, and an
unguarded traversal blows the stack and takes the tab with it.

For `multi: false` roles, `onConnect` **replaces** the existing edge rather than rejecting the
drop. Swapping the start frame feels correct; a connection that won't stick feels broken.

Changing a node's operation prunes edges whose `target_handle` no longer exists in the new spec.

### Autosave

Debounce 2s after idle, force flush every 30s of continuous editing, and flush on
`visibilitychange` with `fetch(..., { keepalive: true })` — **not** `sendBeacon`, which cannot
set the Clerk auth header.

This means dragging nodes for ten seconds fires one PUT. The two-second window is an accepted
data-loss window: a tab crash mid-edit loses up to 2s. That's the price of §0.1.

### Generate

```ts
const spec = operationForNode(node);
if (!spec) return;                          // text nodes are input-only

// flattenPrompt emits the [image N] tokens AND matching inputs together.
// Do not walk the segments again here — that double-counts them.
const { resolvedPrompt, promptInputs } = flattenPrompt(node, doc);

const edgeInputs = doc.edges.filter(e => e.target === nodeId).flatMap(e => {
  const src = doc.nodes.find(n => n.id === e.source);
  if (!src) return [];
  return src.type === 'text'
    ? [{ role: e.targetHandle, ordinal: 0, text: src.data.textContent ?? '' }]
    : src.data.assetId ? [{ role: e.targetHandle, ordinal: 0, assetId: src.data.assetId }] : [];
});

await api.submit(projectId, {
  idempotencyKey: crypto.randomUUID(), nodeId, operation: spec.operation,
  modelId: node.data.config.modelId ?? spec.defaultModel,
  request: { promptSegments: node.data.prompt, resolvedPrompt,
             config: node.data.config, inputs: [...edgeInputs, ...promptInputs] },
});
```

Because resolution happens here, §0.3 is enforced on the client: swapping a start frame while a
job is queued leaves the queued job pointing at the old asset. Correct, and it falls out of the
design.

### Polling

```ts
refetchInterval: (q) => (q.state.data?.length ? 2000 : false)
```

Poll only while something runs. `active_transformation_id` is persisted in the document, so a
reload knows which nodes show spinners before the first poll returns.

### Performance

- `React.memo` every node with a comparator on `data` — React Flow re-renders all nodes on
  viewport change otherwise.
- `onlyRenderVisibleElements` past ~50 nodes.
- Video nodes render a poster image, never a live `<video>`, until clicked.
- Narrow selectors. `useStore(s => s.document.nodes)` in a node component re-renders every node
  when any node moves.
- Never put a `File`, blob, or base64 string in `node.data` — it's serialized on every autosave.

---

## 12. Build order

**Hand over M1–M4 as the first wave.** It ends with a curl-able backend whose entire lifecycle
runs against the dry-run provider.

**M1 — Foundation.** Postgres provisioned, SQLAlchemy models, Alembic initialized, first
migration applied to a dev branch, health check doing a real `SELECT 1` and failing loudly when
`DATABASE_URL` or any `R2_*` variable is unset.

Two things first, because they have no home today: add `pytest` and `pytest-asyncio` and create
`tests/` — every acceptance check below becomes a test named after itself — and add a Node step
to `.github/workflows/ci.yml`, which the §4 contract diff needs.

**M2 — Contracts.** `server/contracts/` with document, operations, and pricing. The export →
generate → diff-check CI pipeline. Do this before route work; everything depends on the shapes.

**M3 — Projects and assets.** Project CRUD, scoped hydration, document PUT with 409.
`server/canvas/storage.py` against R2 — presigned PUT, presigned GET, CORS including `PUT`.
No migration script; there is no data.

**M4 — Transformations against dry-run.** Worker, claim statement, poll loop, sweeper,
assets-before-claim completion, retry. All four `*_DRY_RUN` flags `true` throughout.

**M5 — Canvas frontend.** Delete `studio/` first. Then the React Flow route, the ten components
of §11, typed handles, cycle-guarded validation, autosave, upload, generate, polling.

**M6 — Live provider.** All four `*_DRY_RUN=false`. Verify model activation and the content
policy on realistic faces before wiring the full registry — see the verification appendix.

## Acceptance checks

- Double-clicking generate creates exactly one transformation row.
- Reloading mid-generation restores the spinner and the result still lands on the node.
- **Closing the tab, letting a generation finish, then reloading attaches the asset to the node
  and clears the spinner** — the result is never orphaned.
- A user with 3 in-flight generations gets a 429 on the fourth.
- A user past the daily credit cap gets a 429 even with nothing in flight.
- Flipping the `generation` system flag to disabled returns 503 on submit within 10s,
  with no redeploy.
- Two simultaneous submits for the same node produce one row and one 409 — the unique
  index holds, not just the application check.
- Requesting `GET /assets/:id/url` for another user's asset returns 404, not 403, not the file.
- Requesting a presigned upload URL for another user's project returns 404.
- Every succeeded transformation has a non-null `provider_response`.
- Every log line from submit to completion carries the same `transformation_id`.
- Deleting a node does not delete or orphan its transformation history.
- A `queued` transformation whose worker died before claiming is reclaimed by the sweeper.
- Two workers claiming simultaneously take different rows, never the same one.
- A synchronous generation — image *or* speech — reaches `succeeded` without polling, and the
  sweeper does not re-claim it.
- A Mureka poll executed on a worker that did not perform the submit returns the correct status.
- Simulating a failed download leaves the row `running`; the retry produces one asset, not two.
- Killing and restarting the worker mid-generation still completes the job.
- Two worker replicas do not both run the sweeper.
- Dragging nodes for 10 seconds fires at most one document PUT.
- Editing a node's prompt while a job is queued does not change what that job generates.
- Retrying a failed transformation creates a second row with a different idempotency key.
- `GET /projects/:id` on a project with 100 generations but 5 nodes returns 5 assets.
- A malformed `node_id` is rejected by the database.
- An active transformation whose `node_id` matches no node is dropped at hydration.
- A node with two reference segments and two wired edges submits four inputs, not six.
- `duration_sec: 2` is rejected by Pydantic, not silently clamped by the provider.
- Text nodes have no generate button.
- Every transformation row has a non-null `cost_credits` and `user_id`.
- The contract diff check fails CI when a Pydantic model changes without regenerating TS.
- No Next.js API route imports from `server/` or touches the database.
- Every transformation row has a non-null `provider` matching its operation's registry entry.
- Submitting a config key absent from the operation's `config_fields` returns 400.
- Two `reference` inputs on one submit return 400, not a silently dropped second image.
- A worker running a live Seedream call still answers a concurrent poll for another
  transformation within a second — catches a missing `to_thread`.
- An audio node offers no outgoing connection to any video operation.
- The generated TypeScript is camelCase and `components/canvas` compiles against it with no
  hand-written mapping layer.
- With `RENDERHAUS_DEV_USER` set to two values, the cross-user 404 checks fail before the
  ownership dependency is wired and pass after.
- `find web/src -name "*.css" | wc -l` returns 1.
- `grep -r "api/studio\|studio/" web/ server/ Makefile` returns nothing after M5.

---

# Appendix A — Post-merge verification

Everything here was deliberately deferred so implementation could start. Each item is safe to
defer because dry-run defaults, spend caps, or an empty legacy store absorb the risk in the
meantime — and each one is a real failure if it reaches users unverified.

Ordered by the gate it blocks, not by importance.

## Gate 1 — Before the first live provider call

Four curls, twenty minutes. Do them **before** M6, not during it, or a failure is ambiguous
between your code and your account.

- [ ] **Ark model activation.** Confirm `seedream-5-0-lite-260128` and `seedance-1-5-pro-251215`
      are enabled on the BytePlus account. An un-activated model returns an auth-shaped error
      that looks exactly like a bad key.
- [ ] **Content policy on realistic human faces.** If ModelArk rejects them this is
      product-shaping, not an implementation detail, and needs a specific user-facing error.
      Test with a plain portrait prompt.
- [ ] **Mureka key is live** and `create_song_from_prompt` returns a task id.
- [ ] **Fish Audio key is live** and both starter voice IDs resolve — `_lookup_voice_id` falls
      back silently when a voice is not found.
- [ ] **Does BytePlus bill failed generations?** Determines whether a `failed` transformation
      refunds credits. One deliberate content-policy rejection, then the invoice.

## Gate 2 — Before the first browser upload

- [ ] **R2 CORS includes `PUT`.** The rule ported from `assets.py:194` sets `GET`/`HEAD` only,
      and its `except ClientError` swallows configuration failures into a log warning.
- [ ] **Presigned PUT round-trips against R2** with the `Config` checksum settings from §1 —
      from the browser, not from Python. The two paths fail differently.
- [ ] **`Content-Type` on the PUT matches the presign exactly.** A mismatch is a 403 with an
      empty body.
- [ ] **R2 credentials have write scope.** A presigned URL cannot grant permission the signer
      does not hold; this surfaces only at upload time.

## Gate 3 — Before a second worker replica

- [ ] **Mureka polling on a worker that did not submit** — see §6.
- [ ] **`pg_try_advisory_lock` actually prevents two sweepers.** Only observable with two
      replicas running.
- [ ] **Two workers claiming concurrently take different rows.** `SKIP LOCKED` under real
      contention, not a unit test.
- [ ] **Worker deployment target and restart policy.** §7 says "another command on the same
      image", which answers packaging but not deployment. Still undefined.

## Gate 4 — Before real users

- [ ] **Replace every `MODEL_RATES` placeholder with an invoice-verified number.** Grep for
      `TODO(verify)`. Placeholders must be **over**-estimates: the rate feeds a spend cap, so
      over-estimating fails closed and under-estimating fails open. When the cap trips early
      during M4–M6 that is correct behaviour, not a bug to fix by lowering the number.
- [ ] **Set the credit peg.** Permanent once history exists — see §9.
- [ ] **Confirm the caps.** `DAILY_CREDIT_CAP` and `MAX_CONCURRENT_PER_USER` are placeholders.
- [ ] **Exercise the kill switch.** Flip the row, confirm generation halts with no redeploy.
- [ ] **Clerk configured in every environment that matters.** With Clerk off, `current_user_id`
      returns `RENDERHAUS_DEV_USER`, so every user shares an owner and both cross-user checks
      pass vacuously.
- [ ] **Sentry on API and worker** with `transformation_id` as a tag.

## Gate 5 — Cleanup, any time after M5

- [ ] `grep -r "api/studio\|studio/" web/ server/ Makefile` returns nothing.
- [ ] `find web/src -name "*.css" | wc -l` returns 1.
- [ ] `design/ARCHITECTURE.md` and `design/MERGE_PLAN.md` updated — both predate the canvas.
- [ ] `_ensure_output_asset` in `app.py:263` is dead code once the legacy job store is retired.

## Known-deferred, not bugs

Recorded so nobody "fixes" them mid-implementation.

- **Multi-reference images.** `image_to_image()` takes one image. `multi: False` is deliberate.
- **Audio cannot feed video.** No operation accepts an `audio` input role, so lip-sync and
  scored clips are out. This is the honest v0 boundary.
- **Canvas and timeline have separate asset stores.** Both empty, so unifying later is a code
  change with no data migration.
- **Two design systems coexist** until the timeline is restyled.
- **Fish Audio ships two voices.**

## Environment

```
DATABASE_URL              postgres, async driver (postgresql+asyncpg://)
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

The health check fails loudly if `DATABASE_URL` or any `R2_*` is unset. Silent fallbacks here
produce failures that look like application bugs. Note there is no queue URL — that is the
point of §1.
