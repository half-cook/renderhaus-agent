# Changes & Timeline v1 work record

The work starts at `88f958d` on `feat/ui-revamp`. No push, pull request,
history rewrite, provider generation or change to main/staging is authorized.

## Workflow

1. Read the Principles section of poteto-mode.
2. Frame. Ground existing billing, review, timeline and repository storage.
3. Design the workflow. Establish baseline checks and a shared typed contract.
4. Run the loop. Verify each implementation unit before committing it.
5. Keep the audit trail. Append decisions with evidence as units finish.
6. Verify and hand back. Inspect production captures and report remaining gaps.

## Implementation units

- Domain adapter, immutable cut transitions, explicit fixture/API store and small
  ownership-checked persistence routes. State transitions get offline tests first.
- Numbered row, Changes panel, chat card, composer insertion and keyboard review.
- Compare with shared timing, static poster disclosure and cut alignment ribbon.
- Timeline markers, safe trim hatch, retained takes and attached audio warning.
- Twelve-state noindex board, stress fixtures, copy/privacy gates and production
  captures. Re-run existing m01–m18 captures, accessibility and interactions.
- Full offline verification, report and small local commits. Leave a clean tree.

## Grounding and architecture

`AgentDock` owns normal agent text and paid approvals. `AgentReviewPanel` owns the
right panel tabs and existing saved-plan comparison. `TimelineView` and `Timeline`
share `lib/rh/timeline.ts` clip geometry and existing canvas editing actions.
`ApprovalCard`, `Ledger`, `RunBilling` and the billing adapters own money display.
`StudioRepository` stores project state in SQLite; export routes check project
ownership before reading it. Agent checkpoints hold run-resume state and are not
film checkpoints. No changeset, take or film-checkpoint routes existed at baseline.

The new adapter owns changeset documents, typed edit references and pure cut
transitions. The store owns selection and mutation requests. UI components share
that document and never compute prices. Stored current cuts were selected over
event replay because existing clip trims and ordering are already direct values.
Kind-specific references allow a take and trim on one shot to remain independent.
Stale referenced values must become Out of date without modifying the cut.

## Throughput checkpoint

Five screens and twelve row states share one row component. Three isolated native
worktrees cover domain/backend, compare and timeline. The root owns the review
surfaces, integration and verification. The dependency is the shared domain
contract. CSS fragments are integrated sequentially into `revamp.css`.

The pstack architect defaults include external Claude and Grok lanes. They are
omitted because this task prohibits live provider calls. Only its native Codex
lane and native ad-hoc helpers run. No cross-provider design consensus is claimed.
The user has settled the Concept C design, so no new product design approval is
needed. The existing Radix primitives are reused without initializing shadcn.

## Definition of done and limits

The unit and offline suites pass; TypeScript and production builds pass; all new
screens and existing m01–m18 are captured with strict copy/privacy guards; new
screens have no serious/critical axe violations; fixture browser interactions
verify accepting, rejecting, restoring, keyboard, compare and overlap edges.
Screenshots stay outside git. The report names every missing backend contract.

Real-backend Comet E2E is unavailable as specified by the user. It remains blocked
and pending, regardless of fixture browser results. Agent-side changeset creation,
take generation/storage and rendering the proposed cut are out of this task.

## Outcome

All authorized implementation units are built. Changes, Compare, Timeline and
the twelve-state board share the same document; no generation or client pricing
was added. Three local feature commits contain the domain/persistence layer,
comparison/timeline, and review integration. The validation/report commit records
the final evidence and proposed backend contracts.

TypeScript, 131 Node tests, 2,119 offline Python tests (seven skipped), production
build, five readiness scripts, Ruff and dry-run CI pass. The production fixture
browser passes 17 flows. Thirty-three captures and axe scans pass strict guards
with zero accessibility violations. Twenty-two preserved old captures have zero
changed pixels; m06 also has zero changed pixels against a fresh `88f958d`
production baseline after fixing the kit's camera-settling race.

The last reviews fixed paid candidate substitution, manual media edits, stale
targets, lost restore history, frame-note context and extensionless video/initial
seek handling. The video test required actual byte-range media responses; it now
observes the trimmed frame and playback. The final paused-cap board fixture uses
receipt lines that account for its supplied charged total. No review findings
remain in scope. The decision trail was checked against the conversation, logs,
source and capture paths. The external model-family trail review remains omitted
under the no-live-provider constraint; no cross-provider review is claimed.

Real-backend Comet E2E is still blocked and pending. Agent-produced changesets,
take generation/storage, legacy canvas/export reconciliation and rendering the
proposed cut need the contracts in `docs/UI_REVAMP_REPORT.md`. No screenshots
are committed, and this task makes no push, PR or history rewrite.
