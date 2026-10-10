# Footage memory verification

Read date: 2026-10-10. Branch: `feat/skill-footage-memory`; starting commit: `c12f0c8`.
All understanding is synthetic. No paid/live model call, secret read, push, PR or deployment
was performed. The installed Deep Agents 0.7.23 signatures were used.

## Checks

The final full suite passed: **2,448 tests run, 2,440 passed, 8 unchanged skips** in
398.011 seconds. This includes all starting-commit tests and 101 additional cases.
The earlier full run exposed the stale miniature packaging fixture; it was corrected,
the seven focused packaging tests passed, and the full suite was rerun successfully.
Ruff and `scripts/ci_check.py` passed. CI verifies 18 providers, 134 tools, 36 skills,
271 routing rows, 265 active rows and six unchanged routing skips. It builds and inspects
the real Lambda ZIP, including both migrations, synthetic fixtures and attribution.

Commands used:

```bash
.venv/bin/ruff check agent lambdas scripts server providers
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python scripts/ci_check.py
# Inside studio, with the temporary installed-dependency link:
./node_modules/.bin/tsc --noEmit -p .
```

The Python suite and CI used `RENDERHAUS_SECRETS_NAME=""` and all requested dry-run
settings: `SEEDANCE_DRY_RUN`, `SEEDREAM_DRY_RUN`, `ELEVENLABS_DRY_RUN`,
`FISH_AUDIO_DRY_RUN`, `REMOTION_DRY_RUN`, `KLING_DRY_RUN`, `RUNWAY_DRY_RUN`,
`FAL_DRY_RUN`, `LUMA_DRY_RUN` and `HYPERFRAMES_DRY_RUN`, plus
`FOOTAGE_MEMORY_DRY_RUN` and `GEMINI_DRY_RUN`, all `true`.

The focused regressions exercise schema migrations, project isolation, content/version
reuse, all seven event kinds, speakers, FTS fallback, optional vector adapter behavior,
path confinement, routing thresholds, approval/rejection/resume, verification refusal,
retry repartitioning, duplicate clips, re-uploaded source pointers and refined cuts.
Network and credential access fail in the new backend tests. Local ffmpeg creates and
probes a fictional select with native 160x90 geometry, expected duration and audio.
Neither ffprobe nor a mock answer establishes browser playback or real-footage semantics.

Studio `tsc --noEmit -p .` passed with a temporary symlink to the complete installed
`/workspace/rh-staging/studio/node_modules`. The requested Runway clone's dependency tree
was incomplete. Both temporary links were removed; no external dependency files changed.

The offline A/B smoke set has six fictional labelled moments. Both synthetic candidates
report six true positives, precision 1.0 and recall 1.0 at an inclusive two-second tolerance.
`default_promoted=false`. This checks scoring, not model quality.

Comet E2E is **blocked**, as the user specified that Comet is unavailable here. No browser
actions were performed. The estimate/approval UI, visible search/verification results and
saved-select playback remain unvalidated. The ignored report is
`.renderhaus/e2e/footage-memory.json`, recorded with `scripts/browser_e2e_hook.py record`.

## Routing changes

Eight new rows are active: RT-177, RT-178, RT-179 and FM-001 through FM-005. RT-177 preserves
the workbook sequence and adds the mandatory narrow verification before extraction.
RT-179's parked Resolve request maps to the existing `conversational-edit` skill,
`transcript_edit` alias and `Remotion___prepare_conversational_edit`. No Resolve skill is added.

Six older rows remain skipped: one HyperFrames overlay request needs
`feat/hyperframes-overlays`; four capture requests need `cutaway_record` /
`feat/product-demo-capture`; one exact end-card OCR comparison needs
`feat/remotion-ocr-verification`. Qwen is a disabled backend candidate, not an activated
live routing row. Existing routing rows are preserved.

## Changed files

```text
.github/workflows/deploy.yml
Dockerfile.agentcore
agent/deep_agent/routing.py
agent/deep_agent/routing_policy.json
agent/deep_agent/runner.py
agent/deep_agent/skills/footage-memory/SKILL.md
agent/gateway_executor.py
configs/gateway/ffmpeg.tools.json
configs/gateway/footage_memory.tools.json
docs/DEEP_AGENT.md
docs/FOOTAGE_MEMORY.md
docs/SKILLS.md
docs/VIDEO_INDEX.md
docs/footage-memory-decisions.tsv
docs/footage-memory-verification.md
providers/catalog.py
providers/contracts.py
providers/ffmpeg/api.py
providers/ffmpeg/ops.py
providers/ffmpeg/sandbox.py
providers/footage_memory/NOTICE.md
providers/footage_memory/__init__.py
providers/footage_memory/api.py
providers/footage_memory/backends.py
providers/footage_memory/contracts.py
providers/footage_memory/decisions.py
providers/footage_memory/evaluation.py
providers/footage_memory/fixtures.json
providers/footage_memory/index.py
providers/footage_memory/service.py
providers/footage_memory/sql/001_core.sql
providers/footage_memory/sql/002_segment_edit.sql
pyproject.toml
scripts/ci_check.py
scripts/eval_footage_memory.py
scripts/sync_secrets.py
server/billing_rates.py
studio/lib/canvas/model-labels.ts
studio/lib/canvas/tool-registry.ts
tests/fixtures/skill_routing.json
tests/test_drop_pyav_package.py
tests/test_footage_backends.py
tests/test_footage_eval.py
tests/test_footage_memory.py
tests/test_footage_routing.py
tests/test_footage_trim.py
tests/test_skill_routing.py
tests/test_video_index.py
```

Provider details, estimates, official pricing/terms, configuration and remaining live work
are in [FOOTAGE_MEMORY.md](FOOTAGE_MEMORY.md). The shared schema and segment-edit integration
boundary are in [VIDEO_INDEX.md](VIDEO_INDEX.md); decisions and source reads are in
[footage-memory-decisions.tsv](footage-memory-decisions.tsv).
