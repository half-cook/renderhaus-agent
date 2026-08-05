# Merge plan — warm-light → renderhaus-agent

Living document. Update this as decisions get made and steps get done — don't let it drift out
of sync with reality. Status tags follow `ARCHITECTURE.md`'s convention: `[DONE]`, `[IN PROGRESS]`,
`[TODO]`, `[OPEN QUESTION]` (undecided, needs discussion before it can move to TODO).

## 1. Goal

Combine two codebases for the same product into one repo:

- **warm-light** (this repo, uncommitted) — Next.js/TypeScript browser timeline editor. The
  manual-editing engine (Layer A in `ARCHITECTURE.md`), plus the eventual agent-orchestrator UI
  (Layer B) on top of it.
- **[renderhaus-agent](https://github.com/half-cook/renderhaus-agent)** — Python/FastAPI backend:
  LangChain agent, AWS Bedrock AgentCore runtime, per-provider generation MCPs (Seedance/Seedream/
  Mureka/Gemini TTS), Clerk auth, S3 + DynamoDB asset storage, a project/timeline persistence
  layer, and a disposable static-HTML/vanilla-JS frontend.

Target end state: warm-light's Next.js app becomes the frontend; renderhaus-agent's Python app
becomes the backend it talks to. Neither codebase is thrown away.

## 2. Key decisions

Decision log — newest first. Each entry: the call, the reasoning, the date.

- **2026-08-04 — Renamed Python dir is called `server/`.** `app.py`/`auth.py`/`assets.py`/
  `projects.py` are all server-side logic (route handlers, Clerk token verification, S3/DynamoDB
  access, ffmpeg orchestration) — none of it moves to the frontend when merged, a Next.js frontend
  just calls it as an API. `server/` pairs cleanly with `web/` and avoids clashing with the `/api/...`
  route prefix already used inside the app.
- **2026-08-04 — Preserve renderhaus-agent's git history.** Real merge (`--allow-unrelated-histories`)
  rather than a snapshot copy — the repo is small and the history is recent/relevant enough to be
  worth the extra git surgery.
- **2026-08-04 — Timeline: client Command model is authoritative; server timeline is a persisted
  snapshot.** warm-light's client-side Zustand + invertible-Command model
  (`web/src/lib/timeline/commands.ts`) drives active editing (instant edits, undo/redo, and it's
  what the planned agent orchestrator is designed to emit against). `server/projects.py`'s
  `ProjectStore` + `timeline.items` + ffmpeg merge/export step aren't replaced — they become the
  save/checkpoint target (`PUT /api/projects/{id}/timeline`) and the thing that hydrates the client
  store on project reload, and the export pipeline. `timeline.items`'s shape may need adjusting to
  represent the Command model's serialized clips, but nothing here gets thrown away.
- **2026-08-04 — Local dev wiring: Next.js `rewrites()` proxy.** `next.config.ts` proxies `/api/*`
  to `http://127.0.0.1:8000` in dev, keeping the browser same-origin (no CORS setup) and letting
  frontend code call `/api/...` as relative paths. Production hosting story is deferred.
- **2026-08-04 — Delete `web/static/*` (old frontend) outright, no archive folder.** Fully
  recoverable from git history (and specifically from the pre-merge commit) whenever needed for
  reference — an `archive/` directory would just be one more thing nobody maintains.

## 3. Open questions

- **[OPEN QUESTION] Push destination.** Branch + PR against `half-cook/renderhaus-agent`, or
  something else? Deferred per instruction — reconcile and verify everything works locally first,
  revisit push once that's done. No push happens without explicit confirmation regardless.

## 4. Target layout (proposed, pending the naming question above)

```
renderhaus-agent/                  (repo root — combined)
├── README.md                      existing, updated to describe both halves + link ARCHITECTURE.md
├── ARCHITECTURE.md                from warm-light
├── agent/                         existing — LangChain agent, AgentCore client, tracing
├── mcps/                          existing — generation provider MCP servers
├── server/                        renamed from existing web/ — FastAPI app (auth, projects, assets, app.py)
├── web/                           from warm-light — Next.js editor frontend
├── docs/                          merged: existing research/adr/plans/product/architecture + warm-light's assets/
├── spikes/                        from warm-light — timeline-render spike
├── configs/, scripts/, .cursor/, .vscode/   existing, unchanged
├── pyproject.toml                 existing, package refs updated web.* → server.*
└── Dockerfile.agentcore           existing, checked for web.* references
```

Note: `docs/` doesn't actually collide on file paths — renderhaus-agent's `docs/` has
`research/ adr/ plans/ product/ architecture/ README.md`; warm-light's only has
`docs/assets/architecture-diagram.png`. Those merge cleanly as-is.

## 5. Migration steps

- [x] **1.** Commit warm-light's current working tree as a baseline commit (safety snapshot before
      any surgery). Done: `main` @ `c87cbfc`.
- [x] **2.** Add renderhaus-agent as a git remote, fetch.
- [x] **3.** Create an integration branch from `renderhaus-agent/main` (`merge-renderhaus-agent`,
      upstream tracking deliberately unset so nothing can accidentally push to their `main`).
- [x] **4.** On that branch: `git mv web server`; fixed `from web.` imports across `app.py`,
      `auth.py`, `assets.py`, `projects.py`; updated `pyproject.toml`, `Dockerfile.agentcore`,
      README run instructions, `scripts/generate_ui_assets.py`. Done @ `c93ee07`. Note: checking out
      this branch left stray untracked Next.js build artifacts (`node_modules`, `.next` leftovers)
      physically inside the old `web/` path from the prior branch switch — cleaned those out before
      the `git mv` landed, so `server/` only contains intentionally-renamed content.
- [x] **5.** Merged the warm-light baseline commit into the integration branch
      (`--allow-unrelated-histories`). Done @ `99167a1` — clean merge, no conflicts, exactly the
      disjoint-paths result predicted in §4.
- [x] **6.** (Conflict resolution — not needed, see above.)
- [x] **7.** Deleted `server/static/*` (old frontend). Also removed the now-dead `StaticFiles`
      mount, `/` index route, and branded-404 handling in `server/app.py` (it served
      `server/static/index.html` / `404.html`, which no longer exist) — `/` now returns a small JSON
      status body, `/api/*` and everything else stays JSON-only. Dropped the matching
      `[tool.setuptools.package-data]` block in `pyproject.toml`. See §6 for the now-orphaned
      `scripts/generate_ui_assets.py`.
- [x] **8.** Updated root `README.md`: two-process dev setup, structure section, links to
      `ARCHITECTURE.md`/`MERGE_PLAN.md`, `:3000` added to the Clerk `CLERK_AUTHORIZED_PARTIES`
      example. Also fixed a stale `web/app.py` path reference in
      `docs/architecture/long-video-system-design.md` → `server/app.py`.
- [x] **9.** Added `web/next.config.ts` `rewrites()`: `/api/:path*` → `BACKEND_ORIGIN`
      (`http://127.0.0.1:8000` by default, overridable via env). Confirmed against this repo's
      pinned Next.js 16.2.12 docs (`web/AGENTS.md` warns this version has non-standard APIs vs.
      training data) that `rewrites()` + external-destination rewrites are still supported as-is.
- [x] **10.** Verified. `server/`: `.venv` built with Homebrew Python 3.13 (system `python3` was
      3.9.6, below the `>=3.11` requirement in `pyproject.toml`), `pip install -e .` clean,
      `from server.app import app` imports and lists all expected routes with no dead `/static`
      routes. Full live boot needs real AWS credentials (`assets.py`'s `init_assets_db()` requires
      `AWS_S3_BUCKET`) — pre-existing requirement, unrelated to this merge, not exercised here.
      `web/`: `npm install` (491M `node_modules` had to be reinstalled — see note below),
      `npm run dev` serves `/` with 200, `npx tsc --noEmit` clean. Proxy itself verified end-to-end
      against a throwaway stub standing in for the backend (avoids needing real AWS): stub served
      `GET /api/config` on `:8000`, `curl http://localhost:3000/api/config` through the Next.js dev
      server returned the stub's body — rewrite confirmed working. Stub and dev server torn down
      after.

  **Correction on `web/node_modules`**: step 4's commit message called the untracked Next.js
  artifacts found in the old `web/` path (during the branch switch) "checkout cruft" and deleted
  them. That was wrong — they were the real, previously-installed `node_modules` (488M) from
  before any of this branch surgery, left in place because untracked/gitignored files survive
  `git checkout` across branches. Nothing precious was lost (fully reproducible from
  `package-lock.json`, no local patches), but it did mean an extra `npm install` was needed here
  that shouldn't have been necessary. Flagging so it doesn't read as intentional in the git log.

- [ ] **11.** Design pass on timeline reconciliation (§2) — separate follow-up, not required for the
      merge to be "done," but tracked here so it doesn't get lost.
- [ ] **12.** Push branch / open PR — only after explicit confirmation (§3).

## 6. Risks / things to watch

- Both sides define secrets/env loading (`agent/config.py`'s `.env.local` + AWS Secrets Manager vs.
  whatever warm-light's Next.js app expects) — needs a single documented story, not two.
- **`scripts/generate_ui_assets.py` is now orphaned.** It generated `stage-backdrop.jpg` /
  `social-card.jpg` for the old static frontend's `<meta>` tags — that frontend is deleted (step 7).
  Path reference was mechanically updated to `server/static/img` so it wouldn't silently point at a
  dead `web/` path, but running it now just creates an unused directory. Leaving it in place rather
  than deleting, in case the art-generation logic (Seedream prompt, aspect ratios) is worth reusing
  for `web/public/` assets later — needs an explicit call, not a silent delete.
- No CI configured on either side yet as far as I've seen — worth flagging separately, not in scope
  for this merge.
