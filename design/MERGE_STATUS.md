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

### 5.1 Merge (combine multiple clips into one job) — fixed 2026-08-07

**Before**: the old static frontend's "Merge" button (`POST /api/projects/{id}/merge`) worked,
because the same UI maintained the project's server-side `timeline.items` via drag-and-drop
(`PUT /api/projects/{id}/timeline`).

**Was broken because**: `putProjectTimeline` and `mergeProject` both existed in
`web/src/lib/api/client.ts`, but neither was called from any component — nothing populated
`project.timeline.items`, so `mergeProject`'s precondition (≥2 video items on the project's
timeline) could never be met. Fell out of the Unified Timeline decision: the "don't build a
second timeline UI" half was done, the "still sync the snapshot" half wasn't.

**Fix**: `ProjectLibrary.tsx`'s `handleDropOnProject` now calls a new `syncProjectTimeline`
helper after every `addProjectArtifact` — refetches the project's current video/music jobs and
`PUT`s them (just `{job_id}` per item; the backend fills in `asset_id`/`media_type`/`label`/
`duration_seconds` from each job record itself, doesn't trust those fields from the client). A
"Merge video clips" button now appears in the "In this project" section once ≥2 video jobs are
present, calling `mergeProject` and opening the resulting merged job in the workspace. Verified
type-checking/linting clean and rendering correctly (button correctly absent with <2 video jobs);
the actual merge call itself still needs the pending signed-in verification pass (§4).

### 5.2 Download finished media — fixed 2026-08-07

**Before**: the old frontend's canvas toolbar had a "Download" button, enabled once `media_url`
was present.

**Was missing**: zero download affordance anywhere in the rebuild.

**Fix**: `JobWorkspace.tsx` now renders a Download link (`<a href={job.media_url} download>`)
alongside the "Add to timeline" button, for any completed job with a `media_url` — video, image,
or music, matching the old UI's scope (image jobs get a download link too, they just never got an
"add to timeline" button, consistent with §5.1's video/music-only timeline scope).

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
