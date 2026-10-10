# Renderhaus design screenshots

This kit is copied from the research screenshot workflow and adapted for
Studio's single `npm ci`. The local package.json is an ES module marker only.
No screenshots or browser output are committed. These are mock design captures,
not the real-backend Comet E2E required by AGENTS.md.

From `studio/`, run `npm ci`, `npm run shots:install`, then `npm run shots:after`.
The runner builds without Clerk keys, starts production Next on localhost:5191,
waits for readiness, captures 1920x1200 stills, and stops only its own server.
`npm run shots:before` sets `SHOT_LABEL=before`. The following variables are
optional.

| Variable | Meaning |
| --- | --- |
| `SHOT_THEME=light` | Capture light instead of dark |
| `SHOT_STUDIO_DIR=/absolute/path/studio` | Build and serve a baseline checkout, including its sibling configs/ |
| `SHOT_PORT=5190` | Baseline server port, default is 5191 |
| `SHOT_SKIP_BUILD=1` | Reuse an existing production build made without Clerk keys |
| `SHOT_OUT_DIR=/absolute/path` | Evidence location, default is design-shots/out/ |

Run `npm run shots:compare -- dark` and `npm run shots:compare -- light` to
produce HTML and JSON reports plus diff PNGs. Pixelmatch's threshold is 0.05;
inspect the images as well as the percentages. Use the same OS and browser for
both builds. The default browser setting requests reduced motion. The fixed
clock, theme storage, locale, font readiness, and disabled CSS animations keep
captures repeatable. The theme applies before paint.

`screens.ts` lists existing screens and future beta placeholders. Auth screens
are skipped because the kit intentionally uses no Clerk keys. Beta pages are
skipped because they do not exist yet. Update these conditions when the approved
screens exist. The current approval card has no price field.

`fixtures/studio.json` and `account.json` contain only Demo Studio and Demo
Creator data. The artifact SVG is a static mock. Every unmatched API request is
aborted, including non-fixture mutations. The only POST allowed is the local
fixture's playback ticket. A scrubbed, ignored `fixtures/studio.har` can supply
additional fixtures. Never record a real account or commit a HAR. The privacy
guard fails on real-looking emails, signed media URLs, and Next's dev indicator.

`npm run shots:a11y` runs optional axe WCAG 2.2 A/AA checks with the same routing
and privacy guard, writes JSON, and fails on serious or critical findings.
These checks are manual and do not require browsers in CI. Existing findings
remain visible. For optional mobile captures, run Playwright directly against
an owned production server with `SHOT_BASE_URL=http://localhost:5191` and
`--project=mobile-iphone15`. The runner's default is desktop only.

See [UI_REVAMP_STACK.md](../../docs/UI_REVAMP_STACK.md) for adding components
and [DESIGN_SYSTEM.md](../design/DESIGN_SYSTEM.md) for the pinned contract.
