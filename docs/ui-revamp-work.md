# Studio revamp work record

- [x] Read the Principles section of the poteto-mode skill.
- [x] Phase A: Frame.
- [x] Phase B: Design the workflow.
- [x] Phase C: Run the loop.
- [x] Style existing components and compare m03, m04, m06, m07, m13, m15, m16, m17.
- [x] Add the approval states review board.
- [x] Add the demo project and welcome flow with three static approved shots.
- [x] Add the typed export sheet with honest disconnected behavior.
- [x] Exercise edge cases, keyboard interactions, copy guards and axe.
- [x] Phase D: Keep the audit trail.
- [x] Phase E: Verify local checks and hand back with the Comet blocker recorded.

Done requires all requested local checks, production fixture captures of m01 through m18 plus the light run, side-by-side images and a clean committed branch. Comet E2E remains blocked as the user stated. No live media calls, pushes, PRs or history rewrites are authorized.

The mockups define the structure and tokens. Existing adapters and UI are extended. Money comes from payload cents. Export uses a discriminated state with disconnected, configure and done variants. Fixture data stays in tests and explicit noindex review routes. Each priority unit gets TypeScript and focused checks before its commit. The final report records deviations and unsupported backend capabilities.

Local outcome: 85 node tests, 1,899 Python tests with 38 skips, production build,
three verification scripts, Ruff and ci_check pass. Seven fixture interactions,
23 production captures and 23 axe scans pass; axe reports zero violations.
See [UI_REVAMP_REPORT.md](UI_REVAMP_REPORT.md) for the artifacts and deviations.
Real-backend Comet validation remains blocked and pending.
