# Motion carry QC

`motion_carry_probe` is a free local post-render gate for motion graphics,
product demos, knowledge explainers, and explicitly requested HyperFrames films.
Generative shot continuity still uses `local_qc`.

This is an independent clean-room implementation of a published idea. No
third-party code, animation library, look, template, or external threshold was
read or copied. The non-commercial source project and prohibited research
directories were not accessed. All decision thresholds come from our own films.

## Run the probe

Discover `Remotion___motion_carry_probe` through `call_editor_tool`. Supply the
owned Studio `job_id`, an in-job MP4 `input_path`, and optional exact `timeline`.
`beats_s` lists zero, boundaries, and measured duration. `elements` lists stable
`id`, `start_s`, `end_s`, optional `main_subject`, `intentional_exit`, and ordered
`keyframes` with `time_s` and normalized `[x, y, width, height]` boxes. Boxes
associate pixel tracks with declared elements and select a declared main subject.
There are at most 200 beat times, 100 elements, and 500 keyframes per element.
Paths cannot escape the owned job, follow an escaping symlink, or use a URL.
Maximum input size is 128 MiB and maximum duration is 120 seconds.

`MOTION_CARRY_QC_DRY_RUN` defaults true. Satya enables actual local measurement
by setting it false on the worker with ffmpeg and ffprobe installed. No secret
or provider key is needed. Dry-run reads no media. Lambda measurement returns
`skipped`; schemas and other Remotion tools still import without NumPy or Pillow
in the Lambda package. Direct Studio `/invoke` refuses the probe so reads must
use the owned agent job. Remote-only media needs host staging into that job.
The probe itself never downloads it. When actual local QC is enabled, a local
Remotion poll stages a checksum-named copy into the owned job. It requires a
render ID started in that Studio execution. Its `motion_carry_timeline` retains
exact visual clip cuts and item lifetimes. Pass that metadata to the probe.

```bash
MOTION_CARRY_QC_DRY_RUN=false RENDERHAUS_MEDIA_DIR=.renderhaus/media \
  .venv/bin/python -c 'from providers.remotion.motion_carry import motion_carry_probe; import json; print(json.dumps(motion_carry_probe("job-id", "film.mp4"), indent=2))'
```

The saved JSON contains `schema_version`, `status`, `passed`, film `carry_score`,
per-boundary times, scores, tracked boxes and candidate element IDs, five separate
`checks`, evidence timestamps, fixes, failures, calibration identity, timeline
hash and MP4 SHA-256. Infrastructure errors yield `skipped` and preserve the
render. Dry-run and skipped checks cannot pass.

## Measures and limits

The analyzer samples at 12 fps and 96x54 pixels, with a 45-second subprocess
deadline. One probe runs per worker process; a concurrent request returns
`skipped` with a busy reason. Audio uses an anonymous temporary-file mapping
and chunked statistics. Frame differences are also chunked; stderr is discarded.
The review's 120-second stereo sample peaked at about 239 MiB after this change,
down from 589 MiB. This is an observation, not a memory guarantee.
These are resource bounds, not calibrated quality cutoffs. Films above
120 seconds are skipped instead of truncated. Four-corner background estimates
isolate connected foreground regions. Their normalized shape, color, position
and size support tracking in a short window across each boundary. Carry combines
the weakest appearance match, median-step to largest-step ratio, and visible
spatial transformation. Static identity scores zero. A teleport loses trajectory
continuity. A fade through an empty frame loses its visible track. Film carry is
the mean; every measured boundary must pass the fitted cutoff.

Exact beat timing takes priority. Without it, adaptive scene-change peaks and
audio-energy rises propose boundaries. The median absolute deviation detector
and foreground segmentation fractions are authored measurement parameters, not
imported decision thresholds. Audio onsets do not establish editorial intent.
Insufficient beats or trackable regions remain incomplete. Declared lifetimes
alone do not prove identity. Keyframe boxes add evidence, never an automatic pass.

Cadence uses beat-length coefficient of variation. Rests use the longest run
of changes below the fitted stillness floor. Audio peak uses four-times resampling
at 192 kHz, preserving mono or stereo channels rather than downmixing. This is
a true-peak approximation, not a broadcast loudness certificate. Absent audio
is explicit and does not fail clipping. The gate metric combines peak excess
above normalized PCM full scale with the fraction of oversampled values reaching
that rail. A clean loud sine is a passing control; source clipping that a codec
conceals can remain undetected. More than two channels is unsupported.
Fast motion combines displacement per second with edge sharpness. Tracked
subject edge contact flags a possible unintended exit unless its declared main
subject explicitly has an intentional exit.

Low contrast, complex full-frame footage, occlusion, simultaneous motion, short
events between sampled frames, or a changed dominant region can cause missed
tracks and false alarms. The unlabelled subject is the largest foreground region,
not a semantic person or product detector. These checks do not accept framing,
captions, legal copy or prices. Playback and human visual review remain required.

## Recalibrate on Renderhaus deliverables

Ten committed six-second 160x90 films occupy about 1.6 MiB. They show our own
product card and labels with carrying, slideshow, fade replacement and rhythm
faults, plus blurred-fast-move and intentional-exit controls. The manifest records
hashes, exact timing and independent per-check labels. A fault variant can also
fail an unlabelled check. No labels come from the analyzer's predictions.

Local Remotion rejects motion/grade/rotation and its browser runtime is absent.
HyperFrames has no renderer. The set uses the authorized synthetic fallback
through Pillow, NumPy and installed ffmpeg's native MPEG-4 encoder and ALAC audio.
It is not claimed as Remotion or HyperFrames rendered output. No external template
or new renderer download is involved.

```bash
.venv/bin/python scripts/calibrate_motion_carry.py \
  --build-fixtures tests/fixtures/motion_carry \
  --output providers/remotion/motion_carry_calibration.json
```

To fit real deliverables, follow these steps:

1. Save authorized local MP4s and exact timing outside the synthetic fixture set.
2. Have Satya label each check independently. Use `labels` booleans for `carry`,
   `uniform_cadence`, `no_rests`, `clipped_audio`, `unblurred_fast_move` and
   `subject_exit`. True means that check should pass. Omit uncertain labels.
   Include both positive and negative examples per check, including held and
   continuously moving examples. Reserve separate labelled films for evaluation.
3. Create a manifest using the committed shape. Each film has a `name`, relative
   `file`, `sha256`, optional `timeline` and `labels`. The script verifies supplied
   hashes and refuses classes that do not separate.
4. Run `.venv/bin/python scripts/calibrate_motion_carry.py --manifest /local/labelled/manifest.json --output /tmp/candidate.json`.
5. Inspect every score, false acceptance, false rejection and missing track. Test
   the candidate on the reserved films and real playback. Perfect separation of
   this tiny fit set does not establish general accuracy.
6. Replace committed calibration only after reviewing that evidence. Rerun the
   focused and full suites and log the evaluation results. Every generated file
   remains `provisional=true`; removing it requires a reviewed change backed by
   labelled real-deliverable evaluation.

Stillness uses the midpoint between each class's tenth-percentile frame changes.
Each quality gate then uses the midpoint of the closest positive and negative
class extrema. Non-separating classes stop without writing a candidate.
`motion_carry_calibration.json` records all scores, film hashes, class extrema,
cutoffs and class counts. Its PROVISIONAL cutoffs are:

| Measure | Cutoff | Passing direction |
| --- | ---: | --- |
| Per-boundary carry | 0.0204842161 | At least |
| Beat-length CV | 0.2198484326 | At least |
| Longest rest | 0.4583333333 seconds | At least |
| Peak excess plus rail-contact fraction | 0.0504142499 | At most |
| Speed times sharpness | 0.8158769063 | At most |
| Subject edge-frame fraction | 0.0277777778 | At most |
| Stillness delta | 0.0015553135 | At most, for measuring rests |

The tiny fit separates our clean soundtrack from a clipped example. This does
not establish accuracy on mastered, lossy or mixed real soundtracks. Recalibrate
on labelled real deliverables before treating the cutoff as reliable.

## Delivery enforcement

The four skills direct the editor to probe the completed MP4 with known timing.
Completion requires the saved JSON to match the report, current calibration,
owned job and current output checksum. New render or finishing work invalidates
a prior pass. Probing an old file after finishing cannot certify the new output.
The `motion_carry_required` render-event marker keeps the requirement on follow-up
exports; an unrelated generative continuity request retains its own QC route.
This gate certifies one MP4 at a time. A multi-output motion batch remains incomplete
until separate report aggregation is implemented. Motion metrics do not waive
delivery-render, matrix or deliverable-QC checks.
Another job's report or another rendered output cannot certify this film.
Run-limit recovery uses the same gate. A failed probe preserves the rendered
intermediate and never submits a paid replacement automatically.

The agent surfaces failures verbatim, links the report and offers `remotion_render`
after fixes. `hyperframes_render` is offered only when explicitly requested and
retains its renderer blocker. Missing media, dry-run, invalid report or skipped
measurement is incomplete QC. Re-renders retain approval and spending caps.
`APPROVAL_EXEMPT_TOOLS` and the cap are unchanged; this tool has its own explicit
free exemption. Explicit request, exception and default selection order is unchanged.

## Price, licence and validation

No provider, endpoint, model ID or weights are added. Price is $0 locally; no
official paid quote is applicable. `training_eligible=false`; inspection grants
no training rights to source media. Existing provider and model policies remain.

NumPy 2.4.6 was already installed and is now declared directly for array work.
Its [official BSD-3-Clause licence](https://numpy.org/doc/stable/license.html)
was read 2026-10-10. Pillow was already a direct dependency under
[MIT-CMU](https://pillow.readthedocs.io/en/stable/about.html#license), read 2026-10-10.
No OpenCV or other dependency is added. Existing ffmpeg and ffprobe executables
are invoked, not vendored. Their [build-dependent LGPL/GPL terms](https://ffmpeg.org/legal.html),
read 2026-10-10, remain the operator's responsibility. No GPL, AGPL or non-commercial
third-party code or weights were copied or introduced by this implementation.

The baseline passed 2,089 tests with seven skips. Probe verification exercises
real local binaries and a scripted model through Deep Agents 0.7.23. These are
supporting checks. Comet Studio E2E is blocked because its control is unavailable
here. No browser pass is claimed.

## Changed files

- [.github/workflows/deploy.yml](../.github/workflows/deploy.yml)
- [Dockerfile.agentcore](../Dockerfile.agentcore)
- [agent/deep_agent/motion_carry_gate.py](../agent/deep_agent/motion_carry_gate.py)
- [agent/deep_agent/routing.py](../agent/deep_agent/routing.py)
- [agent/deep_agent/routing_policy.json](../agent/deep_agent/routing_policy.json)
- [agent/deep_agent/runner.py](../agent/deep_agent/runner.py)
- [agent/deep_agent/skills/hyperframes/SKILL.md](../agent/deep_agent/skills/hyperframes/SKILL.md)
- [agent/deep_agent/skills/knowledge-explainer/SKILL.md](../agent/deep_agent/skills/knowledge-explainer/SKILL.md)
- [agent/deep_agent/skills/motion-carry-qc/SKILL.md](../agent/deep_agent/skills/motion-carry-qc/SKILL.md)
- [agent/deep_agent/skills/motion-graphics/SKILL.md](../agent/deep_agent/skills/motion-graphics/SKILL.md)
- [agent/deep_agent/skills/product-demo-video/SKILL.md](../agent/deep_agent/skills/product-demo-video/SKILL.md)
- [agent/gateway_executor.py](../agent/gateway_executor.py)
- [agent/studio_agent_next.py](../agent/studio_agent_next.py)
- [configs/gateway/remotion.tools.json](../configs/gateway/remotion.tools.json)
- [docs/DEEP_AGENT.md](../docs/DEEP_AGENT.md)
- [docs/MOTION_CARRY_QC.md](../docs/MOTION_CARRY_QC.md)
- [docs/SKILLS.md](../docs/SKILLS.md)
- [docs/motion-carry-qc-decisions.tsv](../docs/motion-carry-qc-decisions.tsv)
- [providers/catalog.py](../providers/catalog.py)
- [providers/contracts.py](../providers/contracts.py)
- [providers/registry.py](../providers/registry.py)
- [providers/remotion/api.py](../providers/remotion/api.py)
- [providers/remotion/local.py](../providers/remotion/local.py)
- [providers/remotion/motion_carry.py](../providers/remotion/motion_carry.py)
- [providers/remotion/motion_carry_calibration.json](../providers/remotion/motion_carry_calibration.json)
- [pyproject.toml](../pyproject.toml)
- [scripts/calibrate_motion_carry.py](../scripts/calibrate_motion_carry.py)
- [scripts/ci_check.py](../scripts/ci_check.py)
- [server/billing_rates.py](../server/billing_rates.py)
- [server/studio.py](../server/studio.py)
- [tests/fixtures/motion_carry/blurred_fast_move.mp4](../tests/fixtures/motion_carry/blurred_fast_move.mp4)
- [tests/fixtures/motion_carry/carrying.mp4](../tests/fixtures/motion_carry/carrying.mp4)
- [tests/fixtures/motion_carry/clipped_audio.mp4](../tests/fixtures/motion_carry/clipped_audio.mp4)
- [tests/fixtures/motion_carry/fade_replace.mp4](../tests/fixtures/motion_carry/fade_replace.mp4)
- [tests/fixtures/motion_carry/intentional_exit.mp4](../tests/fixtures/motion_carry/intentional_exit.mp4)
- [tests/fixtures/motion_carry/manifest.json](../tests/fixtures/motion_carry/manifest.json)
- [tests/fixtures/motion_carry/no_rests.mp4](../tests/fixtures/motion_carry/no_rests.mp4)
- [tests/fixtures/motion_carry/slideshow.mp4](../tests/fixtures/motion_carry/slideshow.mp4)
- [tests/fixtures/motion_carry/subject_exit.mp4](../tests/fixtures/motion_carry/subject_exit.mp4)
- [tests/fixtures/motion_carry/unblurred_fast_move.mp4](../tests/fixtures/motion_carry/unblurred_fast_move.mp4)
- [tests/fixtures/motion_carry/uniform_cadence.mp4](../tests/fixtures/motion_carry/uniform_cadence.mp4)
- [tests/fixtures/skill_routing.json](../tests/fixtures/skill_routing.json)
- [tests/test_hyperframes.py](../tests/test_hyperframes.py)
- [tests/test_local_assembly.py](../tests/test_local_assembly.py)
- [tests/test_motion_carry_host.py](../tests/test_motion_carry_host.py)
- [tests/test_motion_carry_qc.py](../tests/test_motion_carry_qc.py)
- [tests/test_provider_ladder.py](../tests/test_provider_ladder.py)
- [tests/test_skill_routing.py](../tests/test_skill_routing.py)

No new provider, vendor model, Studio model-picker entry or secret is added.
The internal policy label `motion-carry-local` represents this analyzer, not model weights.
Remotion already routes to the editor through `DISPATCH_TARGETS`.

## Verification outcome, 2026-10-10

- Starting commit: 2,089 unittests passed, seven skipped.
- Final suite: 2,114 tests passed, seven skipped, including 22 motion probe/host tests.
- Ruff passed over `agent lambdas scripts server providers`.
- `scripts/ci_check.py` passed, including actual ARM Lambda packaging and all dry-run dispatches.
  Offline packaging used cached wheel bytes and their declared platform tags with
  `PIP_NO_INDEX=1` and `PIP_FIND_LINKS=/tmp/motion-wheel-cache`. No download or packaging mock.
- Studio `tsc --noEmit -p .` passed using the authorized temporary dependency symlink,
  which was removed after the check.
- Rebuilding all ten films reproduced every MP4 checksum and the calibration JSON exactly.
- A parent-run 120-second stereo control peaked at 244,836 KiB RSS and correctly remained
  skipped because its black, silent frames offered no beats or subject to certify.
- RT-163 and RT-164 are active motion-carry rows. RT-165 is active generative-continuity protection.
  Five skips remain unchanged: one HyperFrames-overlay dependency, three capture dependencies,
  and RT-E043's unverified exact end-card OCR semantics.
- Browser E2E is blocked. The ignored receipt `.renderhaus/e2e/motion-carry-blocked.json`
  records the missing Comet access and pending real Studio flow and playback.

Only `MOTION_CARRY_QC_DRY_RUN` is new, defaulting true. No secrets are added.
Existing provider dry-run flags remained true for the required checks; tests only
activate authorized local binary paths or mocked provider calls. No paid/live provider
API, push, PR or deployment was performed.

Open work is real-deliverable calibration, Comet Studio E2E and playback,
remote-only artifact staging, and multi-output motion-report aggregation.
The existing HyperFrames renderer remains unavailable. No new vendor model ID,
endpoint or price is unverified, because this feature adds none.
