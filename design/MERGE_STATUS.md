# Merge status — Renderhaus

Started 2026-08-04, this snapshot 2026-08-07. Living document — update it as the remaining gaps
close, don't let it drift. This is the "what actually happened, what works right now, what
doesn't" summary; `MERGE_PLAN.md` has the full git-mechanics log, `PRODUCTION_READINESS.md` has
the scale/architecture audit. Read this one first, follow the pointers if you need more depth.

## 1. What "the merge" was

Two previously-separate codebases, combined into one repo on branch `merge-renderhaus-agent`
(not pushed anywhere — `main` still holds the untouched pre-merge warm-light snapshot as a
fallback):

- **warm-light** — a Next.js manual video timeline editor (`web/`). No backend of its own beyond
  a single synchronous ffmpeg transcode route.
- **renderhaus-agent** — a Python/FastAPI backend (`server/`, `agent/`, `mcps/`, `lambdas/`) doing
  AI video/image/music generation, project libraries, and multi-shot "Production" plans. Had its
  own frontend (`server/static/*`, vanilla JS) which is now deleted.

## 2. Timeline

1. **First merge pass** — `web/` renamed nothing, `renderhaus-agent`'s `web/` renamed to `server/`
   to clear the collision, warm-light's Next.js app merged in clean. Old static frontend deleted.
   Full detail: `MERGE_PLAN.md` §1–6.
2. **Second reconciliation pass** — `renderhaus-agent/main` moved one commit (added the Production
   feature, CI, a Mureka Lambda gateway) after the first pass landed; merged that in too, resolved
   6 conflicts. `MERGE_PLAN.md` §7.
3. **Production-readiness audit** — read the actual code (not the docs' stated intentions) against
   ~100k req/day traffic. Found real issues: a blocking `subprocess` call in an async route, three
   separate local-JSON/in-process stores with no shared concurrency control, imperative infra
   creation at boot, an accepted-but-unbuilt Temporal ADR. None of these are fixed yet — this was
   an audit, not a remediation pass. Full detail: `PRODUCTION_READINESS.md`.
4. **Frontend rebuild** — the actual subject of this document's §4 below. `web/` had zero UI for
   any of renderhaus-agent's product (generation, library, production) because that only ever
   lived in the deleted static frontend. Rebuilt as real Next.js panels, wired to the live backend
   with Clerk auth. Plan file (ephemeral, not in the repo): `inherited-wishing-flurry.md`.

## 3. Current state — what's actually verified working

- **Backend boots for real** against live AWS credentials — S3/DynamoDB checked, Clerk active,
  provider keys loaded. Confirmed via `curl` and a real browser, not just `import` checks.
- **Frontend boots and renders** — editor shell, all six IconRail tabs (Generate/Library/
  Production/Captions/Text/Settings), proxy to the backend confirmed working end-to-end.
- **Auth gating confirmed three times** — submitting a generation, a production brief, and (via
  the same pattern) project creation all correctly open Clerk's real sign-in modal when signed
  out, rather than firing an unauthenticated request.
- **`web/` type-checks and lints clean** end to end (`npx tsc --noEmit`, `npx eslint src`).

## 4. What's NOT yet verified

Nobody has signed in and actually run a generation through to completion. Every write action
correctly *gates* on auth, but the full submit → poll → complete → review cycle, project
creation with real jobs, and production plan → approve → execute have never been exercised with a
real session. This needs a human to sign in once — not something achievable from an agent session
alone. **This is the single most important next step**, ahead of any of the gaps in §5.

## 5. Known gaps vs. the two original apps — what worked before, what doesn't now, and why

Verified against the actual code (not assumed), 2026-08-07.

### 5.1 Merge (combine multiple clips into one job) — broken, not just unbuilt

**Before**: the old static frontend's "Merge" button (`POST /api/projects/{id}/merge`) worked,
because the same UI maintained the project's server-side `timeline.items` via drag-and-drop
(`PUT /api/projects/{id}/timeline`).

**Now**: `putProjectTimeline` and `mergeProject` both exist in `web/src/lib/api/client.ts` — but
grepped the whole `web/src` tree and **neither is called from any component**. Nothing populates
`project.timeline.items` anymore, so `mergeProject`'s precondition (≥2 video items on the
project's timeline) can never be met. The merge feature is present in the backend, wired in the
client, and completely unreachable from the UI.

**Why**: this fell out of the decision to make `project.timeline` a snapshot-sync target instead
of a second visible timeline widget (Unified Timeline, "Approach A") — the sync side of that
decision (write to `project.timeline` when artifacts change) was never actually implemented, only
the "don't build a second timeline UI" side was.

**Path forward**: when a video/music job is added to a project (`ProjectLibrary.tsx`'s
`handleDropOnProject`, or a future "add to project" action), also call `putProjectTimeline` with
the current list of that project's video/music artifacts — keeps the snapshot in sync
automatically, invisibly, no new UI needed for the sync itself. Then add a visible "Merge" action
in `ProjectLibrary.tsx`'s "In this project" section (enabled once ≥2 video artifacts are present)
that calls `mergeProject`.

### 5.2 Download finished media — missing

**Before**: the old frontend's canvas toolbar had a "Download" button, enabled once `media_url`
was present.

**Now**: grepped `web/src/components/generation` for "download" — zero matches. No download
affordance anywhere in the rebuild.

**Path forward**: trivial — `job.media_url` is already available wherever a completed job renders
(`JobWorkspace.tsx`'s `MediaResult`). Add `<a href={job.media_url} download>Download</a>` (or a
styled button wrapping the same), enabled once `job.status === "complete"`.

### 5.3 Drag a clip directly onto the timeline — narrowed, not lost

**Before**: the old UI's V1/M1 timeline lanes were themselves drop targets — dragging a completed
job onto a lane placed it, as an alternative to a button.

**Now**: per the Unified Timeline decision, there's no second timeline lane to drop onto. The
*outcome* (get a clip onto the timeline) is fully covered by the explicit "Add to timeline"
button (`useAddToTimeline.ts`, wired into `JobWorkspace.tsx` and `ProjectLibrary.tsx`'s
`ArtifactCard`) — this is a UX narrowing (one fewer way to do the same thing), not a lost
capability.

**Path forward**: optional, low priority. Could add a native HTML5 drop handler directly on
`CanvasTimeline`'s canvas element, consuming the same `text/plain` job-id payload
`RecentHistoryStrip`/`ArtifactCard` already set on drag start, calling the same
`useAddToTimeline` hook on drop. Not needed unless the button turns out to be a real friction
point in practice.

### 5.4 Project delete/rename — present in the backend, not exposed by either old or new UI

**Checked, not a regression**: `deleteProject`, `updateProject`, and `deleteProduction` all exist
in `web/src/lib/api/client.ts` and are unused, same as §5.1's finding — but based on the old
static frontend's documented behavior (project cards showed title + counts, click to open; no
delete/rename action was ever described), this doesn't appear to have been built in the old UI
either. Flagging as a gap in *both* apps, not something the rebuild dropped.

### 5.5 Everything else — no regressions found

`web/src/lib/timeline/**` (the Command/undo-redo model), `PreviewPanel.tsx`, `TimelinePanel.tsx`,
`CanvasTimeline.tsx`, and everything else that predates this session's rebuild is **byte-for-byte
untouched** since the original repo merge (confirmed via `git diff 99167a1 HEAD -- web/src`,
filtered to pre-existing files — zero diffs outside the four intentional integration seams: 
`EditorShell.tsx`, `IconRail.tsx`, `TopBar.tsx`, `layout.tsx`).

The two dropped `IconRail` stub tabs (`Media`, `Transitions`) had zero implemented functionality
behind them — confirmed via the original code's own comment ("Stub tonight — no panel content
behind these yet"). Import (what "Media" was aspirationally for) already lived inline in
`PreviewPanel`/`TimelinePanel` and still does. Nothing functional was lost dropping those tabs.

## 6. Where to look for more detail

- **Git mechanics of the repo merge itself** (conflicts, resolutions, verification steps): `MERGE_PLAN.md`
- **Scale/architecture audit** (blocking subprocess bug, local-JSON stores, Temporal ADR question):
  `PRODUCTION_READINESS.md`
- **Product/architecture vision** (what warm-light is trying to be): `ARCHITECTURE.md`
- **Long-video production-agent program** (renderhaus-agent's own roadmap): `../docs/README.md`
