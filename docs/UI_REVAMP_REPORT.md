# Studio UI revamp handoff

The requested UI screens are implemented or extended on `feat/ui-revamp`. Local
checks and production fixture validation pass. Real-backend browser E2E remains
**blocked and pending**: Comet is unavailable in this environment, as specified in
the task. Nothing was pushed; no PR, rebase or change to main/staging was made.

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
