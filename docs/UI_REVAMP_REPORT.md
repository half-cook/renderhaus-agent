# Studio UI revamp handoff

The requested UI screens are implemented or extended on `feat/ui-revamp`. Local
checks and production fixture validation pass. Real-backend browser E2E remains
**blocked and pending**: Comet is unavailable in this environment, as specified in
the task. The branch was previously pushed. This task did not push, open a PR,
rebase committed history, or change main/staging.

## Commits

| Commit | Change |
| --- | --- |
| `4b19432` | Style Studio agent, billing and timeline surfaces |
| `65efb34` | Add noindex approval state review board |
| `89364aa` | Add demo project overview and signup welcome flow |
| `a02ef0a` | Add export sheet and honest project JSON download |
| `f402507` | Validate billing edges, approval focus and browser interactions |
| `fd0aa54` | Fix production capture isolation, contrast and dock boundaries |

The final documentation commit contains this report and the completed work record.
The earlier merged billing implementation was extended, including its flat
approval payloads, paused-cap endpoint and receipts.

## Scope and deviations

All m01–m18 screens are in the capture kit, including export configure/done and
the extra light m04 variant. No requested screen is missing. The implementation
uses the mockup structure, component sizes and tokens; it is not a pixel-identical
copy. Mockups are mostly 1440×900, while the capture viewport is 1920×1200. Fixed
widths, such as the 716px agent column, are preserved instead of scaling the whole
interface. The comparisons resize the reference to the capture's height while
preserving its aspect ratio.

| Screen | Deviation from the designer mockup and reason |
| --- | --- |
| m01 landing | Keeps the already committed interactive canvas section. The full page is 3494px tall, versus the taller reference; the 1920×1200 fold is also captured. Primary links use dark text on ember to pass contrast checks. The existing local example film supplies the hero. |
| m02 home | Preserves the committed Home layout. Project cards, account credit and names use the fixture API fields; empty projects retain their empty state. |
| m03 empty agent | Starter tiles say that an estimate will be shown, without price chips: no starter estimate payload exists. Sidebar actions and task metadata retain the existing workspace behavior. |
| m04 agent run | Uses the real payload shape: the illustrated run includes the already charged still, so its estimate/cap are $1.31/$2.00 rather than the mockup's $1.05/$1.50. There is no invented approval thumbnail. The right panel keeps the existing artifact selector and optional source comparison. |
| m05 approval states | Shows seven states, including cap reached and low credit, with sample markers and inactive controls. Three 420px columns are centered in a 1440px board. The full-page capture is 2128px tall so every state is visible. |
| m06 canvas and dock | Uses real React Flow nodes, connections and existing inspector controls. The saved fixture viewport and node positions leave the toolbar clear of content. The rail, inspector, scene rail, minimap and zoom controls stay above the 250px timeline dock; the browser boundary check passes. |
| m07 full timeline | Omits the agent proposal chip and the new Agent review block, as requested because they have no backend data. The existing agent diff panel remains available in Agent mode. Static shot previews represent the fixture media; they do not prove a rendered film or voiceover. |
| m08 demo project | The tour omits a numeric paid-step price when the server supplies no current estimate. Storyboard cards say “Included in demo.” Tasks and files come from the project payload. The template has three approved five-second shots with static thumbnails and editable trims. |
| m09 signup open | Exercises the existing verification UI using dry-run fixtures; the partial six-digit code and hold countdown represent that form's state. No email or SMS is sent. |
| m10 spots left | Uses a six-spot wave fixture; the wave counts and form reflect the server-shaped availability payload. Retains the committed signup layout. |
| m11 full | Keeps the existing full-wave waitlist flow. It does not show an unavailable credit-claim action. |
| m12 signup success | Opens the created project with `?welcome=1`. The banner reads the grant from `account.beta_credit`; a separate $12.34 fixture interaction proves it is not hard-coded to $10. A Sonner toast accompanies it. “Back to home” replaces the mockup's feedback button because no feedback destination is provided. |
| m13 light agent run | Uses the same run data and layout as m04 with light tokens. Thus the same $1.31/$2.00 payload difference and missing approval thumbnail apply. Both this screen and the extra light m04 are captured and scanned with axe. |
| m14 wrong code | Uses the existing inline error, retained hold and resend behavior against dry-run verification fixtures. The copy remains neutral. |
| m15 run receipt | Preserves server actual/estimate/cap values ($2.29/$2.58/$3.50) and balances. The supplied artifact fixture is an image, so the preview identifies it as an image rather than pretending it is a completed video. Tool history and elapsed time follow the fixture execution metadata. |
| m16 cap reached | Uses `execution.paused_cap` and the server's raise options, charged amount and balance. The right spend panel reflects that payload; no options or remaining credit are inferred. |
| m17 low credit | Uses the real insufficient-credit envelope: $1.50 credit, $1.31 estimate and $2.00 cap, with the server's $1.50 lower-cap option. This differs from the mockup's illustrative $1.20 credit. Missing lower-cap options offer add credit only. |
| m18 export configure | There is no designer export mockup. The sheet honestly shows disconnected rendering, project JSON, resolution not applicable and size unavailable until preparation. An estimate ledger appears only for a complete server estimate payload. |
| m18 export done | There is no designer export mockup. The done state represents the actual editable JSON download, with its actual byte size, rather than a rendered movie. |

The edge board adds free $0.00, $1,240.50, long title, three-line prompt,
insufficient balance, cap reached with $0.00 remaining, actual above estimate
but under cap, and twelve-step cases. The separate twelve-card agent run remains
scrollable within the transcript; it does not expand the whole workspace.

## Verification

| Check | Before | After |
| --- | --- | --- |
| TypeScript, `npx tsc --noEmit -p .` | Passed | Passed |
| Node, `node --test tests/*.test.cjs` | 64 passed | 85 passed, zero failed/skipped |
| Production Next build | Passed | Passed |
| `verify-image-specialists.cjs` | Not measured separately | Passed offline routing checks |
| `verify-mureka.cjs` | Not measured separately | 13 cases passed |
| `verify-runway.cjs` | Not measured separately | 11 scenarios passed |
| Ruff across agent/lambdas/scripts/server/providers | Not measured | Passed |
| Python unittest discovery | Not measured | 1899 run, 38 skipped, zero failures |
| `scripts/ci_check.py` | Not measured | Passed; beta/demo/export inventory contains 12 routes |
| Fixture browser interactions | Not measured | 7 passed |
| Production captures and privacy/copy guards | Existing kit | 23 passed, zero page errors |
| Axe WCAG A/AA checks | Not measured | 23 scans; zero violations at any impact |
| Real-backend Comet E2E | Unavailable | Blocked; pending |

Python ran with the requested empty secrets name and all listed provider dry-run
flags. Three Python tests were added (one demo-template test and two export-route
tests); the prior full Python count was not measured. The 1899-test total includes
those additions. Adapter tests read the actual JSON examples from `docs/BILLING.md`,
including pending, insufficient credit, paused cap and receipts. They also cover
incomplete/rejected approvals, missing totals, money formatting, `parseSeconds`,
copy filtering and the edge cases above. UI prices are never summed from lines.

The seven fixture browser checks exercised approval heading focus and its estimate/
cap accessible name; keyboard trim/reorder/remove; dock boundaries; export focus
trap/Escape and downloaded JSON contents; account-backed welcome dismissal; signup
redirect to the created demo; and playback of the existing local example film.
The browser and `ffprobe` both report that file as **1706×960**. Its
`source_resolution` and source dimensions are unknown; no render receipt or
resolution warnings were supplied for it. No new assembled video was rendered.

Captures use `npm run build` and production `next start` on localhost:5191.
The ignored `.next-design-shots/` directory prevents a concurrently running dev
process from replacing production manifests. Earlier attempts exposed that race;
archiving `.next/` alone did not prevent later overwrites. The runner now owns and
stops its server and still blocks unmatched API calls. The normal app build keeps
its default `.next/` output.

## Artifacts

Screenshots and browser output are uncommitted:

- Dark: `/workspace/rh-ui-revamp-shots/after/dark/desktop-1920x1200/`
- Light: `/workspace/rh-ui-revamp-shots/after/light/desktop-1920x1200/`
- 18 labelled comparisons: `/workspace/rh-ui-revamp-shots/after/side-by-side/`
- Axe JSON: `/workspace/rh-ui-revamp-shots/a11y/after/{dark,light}/`
- Browser observations: `/workspace/rh-ui-revamp-shots/observations/after/{dark,light}/`
- Local check logs and summary: `.renderhaus/e2e/checks/`
- Real E2E blocker: `.renderhaus/e2e/ui-revamp.json`, recorded with `scripts/browser_e2e_hook.py`

All capture viewports are 1920×1200. The full-page landing and review boards retain
their content height; other PNGs are exactly 1920×1200. The extra captures are the
landing fold, edge board and twelve-step run. The committed comparison script is
`studio/design-shots/side-by-side.py`. Export has no reference image to pair.

## Remaining backend scope and attention

Starter prices and structured approval tier/thumbnail fields are not supplied by
the current API. Existing `detail` text is shown only when neutral; no missing
metadata is invented. Agent proposal chips and the new timeline review block are
intentionally absent. Lower-cap approval sends the existing `cap_cents` contract;
no richer semantics or live paid approval were validated.

The new export GET route verifies project ownership and reports disconnected
rendering. The typed adapter supports future complete estimates and completed
same-origin downloads, but paid rendering, format/resolution selection and render
submission await a backend implementation. The JSON fallback is functional and
browser-tested. Existing per-user demo copies keep their edits and are not silently
overwritten with template version 2.

Comet cannot be controlled here. The real approval/cap, persistence, signup and
export flows therefore remain unverified with a real signed-in backend. Fixture
screenshots and unit tests are supporting evidence only, as required by
`docs/BROWSER_E2E.md`.

The pstack audit skill asks for a reviewer on a different model family:
“Before handing back, spawn a subagent on a different model family from the one
that did the work.” The installed dispatch routes require external provider calls
for that review, which the task prohibits. That review was not performed; no
cross-model review is claimed. The requirement comes from
`/home/box/.codex/plugins/cache/open-pstack/pstack/1.5.0/skills/show-me-your-work/SKILL.md`.
The decision trail is `docs/ui-revamp-decisions.tsv`; the workflow record is
`docs/ui-revamp-work.md`.

## Changes & Timeline v1

This work starts from the staging merge at `88f958d`. Concept C's numbered edit
list is implemented across Changes, chat, Compare, Timeline and the twelve-state
design board. The inspector's older Agent review block is superseded when a
structured changeset exists. Projects with no changesets keep their existing UI;
an API failure shows a retryable error and never silently substitutes fixtures.
No changeset producer exists yet, so ordinary agent runs do not populate the tab.

### Built

- A typed, validated `ChangesDocument` adapter and Zustand store share current,
  checkpoint and proposed clip lists. Numbered changes support Accept, Reject,
  Revert, Undo, Re-apply, free-only bulk acceptance and confirmed checkpoint
  restore. Restore saves the previous cut and creates a new version. Takes remain
  immutable records; rejecting a paid take retains its price and media reference.
- The third right-panel tab contains the Changeset header, numbered kind-specific
  rows, collapsed decisions, a charged ledger with separate Agent orchestration,
  and checkpoint restoration. The chat card opens Compare; badges insert
  `change N` at the composer caret. Steering remains ordinary agent text.
- Compare replaces the main workspace. Swipe, Side by side and hold-B Flicker
  share a clock and shot/time alignment. Linked zoom/pan, frame stepping, Loop,
  retained-take picking and the cut ribbon are implemented. Frame notes include
  the timecode, use the normal agent submission API with the compared shot's
  context, and preserve an unsent composer draft. Fixture posters explicitly say
  they do not play; video takes support extensionless media URLs and seek to the
  trimmed first frame after metadata loads.
- Timeline uses the existing track model with numbered flags, explicit states,
  a bottom/right trim hatch, top-left Take count, cover thumbnails, Current cut /
  With changes, retained takes and an attached voiceover chip. A longer voiceover
  offers Keep or Trim to fit. The latter changes cut metadata; it does not create
  a new recording. The proposed cut is read-only until decisions are accepted.
- `/design/change-states` is noindex and contains all twelve states using the real
  `ChangeRow` and existing `ApprovalCard`. Connected approvals reuse the existing
  approval, cancel and `answerAgentCap` APIs. Fixture-only paid controls cannot
  authorize a run. J/K, A/R/C, hold B and G avoid inputs and dialogs. A on an
  untaken paid change only focuses its price heading; still acceptance opens the
  existing confirmation. Status text, accessible names and strike-throughs
  accompany colour.

### Persistence and contract

The new server module is 243 lines; with the repository, route and inventory
additions, the new nonblank server logic stays below the approximately 300-line
limit. SQLite stores a validated changeset document and checkpoint cut JSON.
Ownership follows the existing project repository boundary. Mutations use an
expected revision, retain paid outputs, reject unsafe media substitutions and
mark stale references Out of date. No endpoint calculates prices or generates
media. Offline tests cover persistence, ownership, stale revisions, paid guards,
retention and restore history.

| Implemented request | Response / constraint |
| --- | --- |
| `GET /api/studio/projects/{id}/changesets` | `{items: ChangesDocument[]}`; empty when no producer has saved documents. |
| `POST /api/studio/changesets/{cid}/changes/{n}/{action}` | Updated document. Body: `expected_revision`, optional `take_id`, `cut`, `max_duration_ms`. Per-row actions plus `n=0` bulk, metadata trim and manual cut edits. |
| `POST /api/studio/changesets/{cid}/restore` | Updated document containing a new cut version and preserved prior cut. |

The mutation URLs identify the changeset directly rather than repeating a
project ID. The repository derives its project and checks ownership. Manual cut
editing supports trim, reorder and removal; it cannot change a take, voice or
still reference. Paid candidates are guarded across direct acceptance,
re-application, alternate take selection and proposed-cut preview.

Billing consumes integer cents and the existing approval/card, `paused_cap` and
receipt adapters. A cap pause can reuse the original stored estimate when the
pause payload omits it. Missing estimates remain incomplete. The UI does not
compute prices. Disconnected approval controls with sufficient supplied credit
remain disabled without incorrectly claiming insufficient credit.

### Backend gaps and proposed contracts

| Missing capability | Concrete proposed contract |
| --- | --- |
| Agent changeset production | After a run produces proposals, save a `ChangesDocument` through the internal `StudioRepository.save_changes_document` boundary: stable changeset ID, project ID, revision, numbered kind-specific before/after references, current/checkpoint cuts, immutable takes, billing lines and execution/call IDs. The existing GET then exposes it; no client inference from agent prose. |
| Take generation and separate paid quoting | A future `POST /api/studio/projects/{id}/shots/{slot}/takes/quote` returns the existing approval payload: `estimate_cents`, `cap_cents`, `lines[]`, balance fields and linked execution/call IDs. Approve/reject uses the existing approval API. Completion publishes an immutable `Take` plus receipt/actual cents and a new document revision. A partly accepted changeset never receives this paid proposal; create its own changeset. |
| Durable take media and inventory | Persist take metadata/media for the project's lifetime, expose `GET /api/studio/projects/{id}/shots/{slot}/takes`, and use the existing authenticated asset/playback-ticket resolver. Rejected takes retain their price, media and status; there is no paid-delete or expiry path. |
| Canvas / export reconciliation and proposed-cut rendering | Accept/restore currently persists the changeset's cut, without changing legacy canvas nodes or the renderer. A future reconciliation boundary must select a versioned `cut_id` and map its slots, trims, order, voice/still references to the rendering/export model. A render request must name `cut_id` and `mode: current|changes`; it must return existing render/job/asset contracts. No proposed-cut render or delivered artifact is claimed here. |

The current repository stores checkpoint JSON, but no agent-side film checkpoint
producer is connected. Run-resume checkpoints are a different record. Source
dimensions remain unknown when absent; the fixed 16:9 preview is not an export
resolution claim. Voiceover re-recording, branches and difference views remain
outside v1.

### Open-question defaults used

These are Satya's supplied defaults for spec section 10 item 10:

1. Free changes say Free and never open a price card. Paid work uses one supplied
   price, estimate and hard cap; Agent orchestration has its own ledger line.
   Accepting or rejecting an already charged result adds no cost.
2. Rejected paid takes remain in Takes with their price for the project's
   lifetime. No paid output is deleted.
3. Paid changes are priced and approved separately and cannot join a partly
   accepted changeset. Accept free changes always excludes them and is hidden
   when there are zero free pending changes.
4. Voiceover re-recording is outside v1. Branches and difference views wait until
   after beta. The v1 UI uses the approved Changeset / Change / Take / Checkpoint
   vocabulary, including Accept, Reject, Revert, Undo, Re-apply, Compare and Restore.

### Mockup deviations

| Screen | Observed deviation and reason |
| --- | --- |
| m24 Agent Changes | Uses the existing project sidebar/header and regular conversation layout, with the real Changeset card rather than an invented transcript. Accepted/rejected rows collapse to one line with full accessible titles. The light variant darkens status text locally to pass contrast. |
| m25 Compare Swipe | Uses distinct supplied cool/warm posters and labels them Still preview; Play is disabled for these fixtures. No output resolution or frame detail is fabricated. The new-take quote opens the real approval card but cannot run without a connected producer. |
| m26 Compare Side by side | Shares the same honest poster limitation and quote boundary. Playback and zoom link controls are implemented for real video payloads; static captures demonstrate linked zoom/pan and frame references. The retained third take stays grey with its price. |
| m27 Timeline Changes | Deliberately fixes the mockup glitches: Take 2 of 3 stays above the trim hatch and thumbnails preserve aspect ratio. Flags stack when they collide. With changes is a read-only preview; a long voiceover warning is exercised in the one-shot heavy-trim fixture. The monitor uses a supplied still until real video media is available. |
| m28 Change States | Three columns contain the actual complete row and approval components. The full-page image is 1920×1806, taller than the reference because estimate, cap, receipt and explanatory copy are retained. Paid design controls are explicitly disconnected. Waveforms are labelled illustrations; no audio playback or re-recording is implied. Mockup Sample tags are omitted from all new screens. |

### Motion, accessibility and review

| Motion finding | Resolution |
| --- | --- |
| The reused approval card's older entrance exceeds the new flow's 160ms base and repeats on review navigation. | Disable its entrance within Changes rows and dialogs. Review selection, keyboard navigation, swipe dragging and hold-B switch immediately. Remaining colour feedback uses the existing 160ms token and reduced-motion rules. |

Native code and comment reviews found and verified fixes for paid candidate
substitution, unsafe manual cut media edits, stale/deleted targets, restore
history, initial video seeking and frame-note context. There are no remaining
code findings in the reviewed scope. External architect and audit-review lanes
were omitted under the prohibition on live provider calls; no cross-provider
review or consensus is claimed.

### Verification and evidence

| Check | Before | After / outcome |
| --- | --- | --- |
| `npx tsc --noEmit -p .` | Pass | Pass, including after restoring generated Next config churn. |
| `node --test tests/*.test.cjs` | 85 passed | 131 passed; no skips or failures. |
| Offline Python discovery | 2,100 run; 7 skipped | 2,119 run; 7 skipped; pass. |
| Production `npm run build` | Existing production kit | Pass; isolated `.next-design-shots` output with Clerk keys empty, served by production Next. |
| `node scripts/verify-*.cjs` | One pre-existing stale label assertion | All five scripts pass. The stale script now asserts the existing neutral video labels; artifact-routing checks are retained. |
| Ruff across agent/lambdas/scripts/server/providers | — | Pass. |
| `scripts/ci_check.py` with all requested dry-run flags | — | Pass, including the 15-route inventory. No live provider calls. |
| Production fixture browser | 7 earlier checks | 17 pass, including actual local video loading/trimmed-frame seek/playback, normal timecoded frame submission, mutation rollback and safe paid keyboard handling. |
| Captures / strict privacy and copy guards | 23 preserved m01–m18 captures | 33 current captures: the original 23 plus 10 Changes screens/variants. All capture guards pass, including forbidden v1 vocabulary. |
| Axe WCAG A/AA | Earlier kit results | 33 scans; zero violations, including zero serious/critical findings. |
| Existing-screen visual regression | Preserved pre-task captures | 22 captures have zero changed pixels. m06 originally captured a moving camera; a fresh detached `88f958d` production baseline and the final screen both wait for camera settling and have zero changed pixels. |

The final m28 capture and axe scan were repeated after correcting its paused-cap
fixture's receipt lines to account for the supplied $1.50 charged cap. Its money
values remain fixture payload values, never UI calculations. The extensionless
video browser fixture supports byte-range responses so its trimmed first frame
can actually decode; the check observes a ready frame at one second and playback.

Local feature commits:

- `306a662` — Add typed changesets and ownership-checked cut decisions.
- `bac0355` — Build linked take comparison and timeline change markers.
- `72e7c49` — Integrate numbered Changes review and checkpoint restore.

The final validation/report commit contains this section, the capture inventory,
strict copy rules and browser checks. Nothing was pushed during this task.

Evidence locations:

- Checks: `.renderhaus/e2e/changes-checks/` (baseline/final logs and summary).
- Captures: `/workspace/rh-ui-revamp-shots/after/dark/desktop-1920x1200/`,
  with m24 light at `after/light/desktop-1920x1200/m24-agent-changes-light.png`.
- Labelled mockup-left / production-right comparisons:
  `/workspace/rh-ui-revamp-shots/after/side-by-side/m24-agent-changes.png`,
  `m25-compare-swipe.png`, `m26-compare-side-by-side.png`,
  `m27-timeline-changes.png`, `m28-change-states.png`.
- Axe JSON: `/workspace/rh-ui-revamp-shots/a11y/after/`.
- Preserved-baseline comparisons: `/workspace/rh-ui-revamp-shots/changes-regression/`.
- Fresh m06 baseline: `/workspace/rh-ui-revamp-shots/changes-regression-fresh/`.
- Browser workflow receipt: `.renderhaus/e2e/changes-v1.json`, recorded through
  `scripts/browser_e2e_hook.py record` as blocked, never passed.

Screenshots and browser evidence are not committed. Generated Next config
changes were removed; the final source tree keeps the existing config formatting.
Real-backend Comet E2E remains **blocked and pending**, as explicitly specified
by the user. Fixture browser actions, offline repository tests and screenshots
do not prove signed-in persistence or live approval/cap behavior.
