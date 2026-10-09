# HyperFrames assessment

Assessed on 2026-10-08 from the public upstream source at commit
[`3aa68869f7d4cec8b37cdfcb9cd539389b63abed`](https://github.com/heygen-com/hyperframes/tree/3aa68869f7d4cec8b37cdfcb9cd539389b63abed).
The assessed CLI, engine, and producer packages report version `0.8.143`.

## Decision and fit next to Remotion

Adapt selected skill prose into one scoped Renderhaus `hyperframes` skill.
Remotion Lambda remains the default motion-graphics renderer, including plain
"Remotion lower thirds" requests. HyperFrames is an optional editor tool selected
by an explicit request when its enable flag is on. The flag makes the tool
available; unnamed motion requests still use Remotion. It adds an HTML authoring option.

This branch exposes a preview-only dry-run contract. It does not produce a real
MP4 or execute HTML. `HYPERFRAMES_ENABLED` defaults off and
`HYPERFRAMES_DRY_RUN` defaults true. Live rendering stays disabled until an
isolated renderer worker is provisioned, even if dry-run is disabled.
No HyperFrames packages enter the Lambda bundle or deployment workflow.

The [upstream README](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/README.md) describes HTML, CSS, media, and
seekable animations rendered through Chromium and FFmpeg. HTML compositions do
not require React or a bundler. Renderhaus already has a Remotion Lambda path,
so replacing that path would add deployment and operational work without meeting
an additional requirement of this branch.

The chosen patterns cover faceless topic explainers, product launches from
supplied briefs and assets, readable caption overlays with supplied timings,
and short kinetic titles or lower thirds. A preview is not proof of a playable
artifact. Paid media dependencies retain existing gateway approval and spend rules.

## Decisions for all published skills

The [README skill catalog](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/README.md) lists 21 published skills.
"Adapt" means selected prose, rather than an unmodified standalone installation.
No upstream runtime, scripts, templates, fonts, or model weights are vendored.

| Upstream skill | Decision | Reason and adaptation |
| --- | --- | --- |
| [hyperframes](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/hyperframes/SKILL.md) | Adapt | Scope entry guidance to explicit HyperFrames selection. Remove its blanket renderer default and automatic installation. |
| [hyperframes-core](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/hyperframes-core/SKILL.md) | Adapt | Retain composition roots, timing attributes, clip lifecycle, bounded duration, and deterministic seeking. |
| [hyperframes-animation](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/hyperframes-animation/SKILL.md) | Adapt | Retain seekable motion and transform guidance. Do not vendor runtime adapters. |
| [hyperframes-creative](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/hyperframes-creative/SKILL.md) | Adapt | Retain brief, typography, palette, and storyboard guidance without preset assets. |
| [faceless-explainer](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/faceless-explainer/SKILL.md) | Adapt | Plan text explainers with invented typography, diagrams, and supplied data. Remove HeyGen audio and helper scripts. |
| [product-launch-video](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/product-launch-video/SKILL.md) | Adapt | Plan launches from supplied briefs and brand assets. Do not add site capture or hosted media resolution. |
| [motion-graphics](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/motion-graphics/SKILL.md) | Adapt | Retain kinetic titles, numeric callouts, logo reveals, and lower thirds. This skill owns kinetic-type. |
| [embedded-captions](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/embedded-captions/SKILL.md) | Adapt partially | Retain readable rails and supplied word timings. Skip matting, transcription, and cinematic embedding. |
| [hyperframes-cli](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/hyperframes-cli/SKILL.md) | Adapt partially | Retain local validation and render requirements. Replace shell instructions with real gateway tools. |
| [hyperframes-audio](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/hyperframes-audio/SKILL.md) | Skip | The separate audio-mixing runtime exceeds scope. Existing approved audio tools remain the source of audio. |
| [hyperframes-keyframes](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/hyperframes-keyframes/SKILL.md) | Skip | Specialized authoring and diagnostics exceed the preview-only renderer contract. |
| [hyperframes-registry](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/hyperframes-registry/SKILL.md) | Skip | Hosted catalog discovery and installation need network and asset-provenance work. |
| [hyperframes-studio](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/hyperframes-studio/SKILL.md) | Skip | The upstream editor is separate from Renderhaus Studio integration. |
| [media-use](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/media-use/SKILL.md) | Skip | HeyGen media APIs, credentials, generation, and downloads need separate terms and approval review. |
| [general-video](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/general-video/SKILL.md) | Skip | A broad fallback would compete with existing video routing. |
| [talking-head-recut](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/talking-head-recut/SKILL.md) | Skip | Its large overlay pipeline and separate MIT attribution chain are unnecessary for the selected patterns. |
| [music-to-video](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/music-to-video/SKILL.md) | Skip | Beat analysis and audio-led generation exceed scope. |
| [pr-to-video](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/pr-to-video/SKILL.md) | Skip | GitHub ingestion is outside the motion-graphics request. |
| [figma](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/figma/SKILL.md) | Skip | Figma import and connector integration are separate work. |
| [slideshow](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/slideshow/SKILL.md) | Skip | Its output is a navigable deck, rather than rendered video. |
| [remotion-to-hyperframes](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/remotion-to-hyperframes/SKILL.md) | Skip | Source migration is not requested. Existing Remotion behavior stays available. |

## Runtime requirements and the CLI contract

[CLI package metadata](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/packages/cli/package.json) and
[engine package metadata](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/packages/engine/package.json) require
Node.js `>=22`. Local rendering also needs Chromium or Chrome Headless Shell,
FFmpeg, ffprobe, suitable shared libraries, disk space, and worker memory.
The engine uses Puppeteer. Upstream supports separate local, AWS Lambda,
Google Cloud Run, and hosted HeyGen render paths.

The assessed [render command](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/packages/cli/src/commands/render.ts)
accepts an optional positional project directory. Its `--composition` flag
selects the entry HTML and defaults to `index.html`. A future provisioned worker
can invoke its pinned installed executable with this supported command shape:

```text
hyperframes render <project-directory> --composition index.html --output renders/video.mp4 --fps 30 --quality draft --format mp4 --workers 1 --strict --json
```

The quality default is `looks`. Supported qualities include `draft`, `looks`,
`delivery`, `standard`, and `high`. MP4 is the default format. WebM and MOV
support transparent overlays. FPS falls back to root `data-fps`, then 30.
`--json` is documented for final batch output and does not promise single-render
JSON output. The CLI has no `--browser-path` argument. Its canonical environment
variable for a preinstalled browser is `HYPERFRAMES_BROWSER_PATH`.

The [composition contract](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/hyperframes-core/SKILL.md)
uses a standalone root with `data-composition-id`, canvas dimensions, and bounded
`data-duration`. Timed layers use `class="clip"`, `data-start`, and
`data-duration`. A GSAP composition registers one paused timeline under the root
ID. Other seekable adapters are available. Render-time clocks, unseeded
randomness, and network-dependent state violate deterministic output.

The [CLI workflow](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/hyperframes-cli/SKILL.md) calls for
`check`, proof snapshots, final preview, rendering, and output inspection.
A future integration must verify that the resulting artifact opens and plays.
Fake-model contracts and a returned job ID cannot establish rendering success.

## Isolation and offline behavior

The [CLI entry point](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/packages/cli/src/cli.ts) loads `.env` from
its working directory and starts telemetry and update machinery. Its
[browser preflight](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/packages/cli/src/browser/preflight.ts) can
ensure a browser and trigger a download. Upstream skill instructions also run
`npx`, skill updates, hosted catalog queries, auth, usage, and feedback commands.
The adaptation removes these instructions.

A future worker needs a pinned preinstalled executable and browser, an isolated
working directory without `.env`, a controlled environment, network isolation,
filesystem limits, timeouts, and resource limits. Verified opt-outs are
`HYPERFRAMES_NO_TELEMETRY=1`, `HYPERFRAMES_NO_UPDATE_CHECK=1`, and
`HYPERFRAMES_NO_AUTO_INSTALL=1`. `CI=true` suppresses interactive behavior.
These variables do not themselves establish network isolation.

The [browser manager](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/packages/engine/src/services/browserManager.ts)
uses `--no-sandbox` and `--disable-setuid-sandbox`. Composition HTML executes
JavaScript. Running untrusted HTML in the Studio server process is therefore
outside this branch's safe runtime contract.

The full [caption workflow](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/embedded-captions/SKILL.md)
requires Sharp, Puppeteer, GSAP, FFmpeg, ffprobe, WhisperX via `uvx`, and human
segmentation. Matting downloads approximately 168 MB of u2net weights on first
use. These dependencies and the transcription pipeline remain unimplemented.
Caption adaptations use supplied text and word timings only.

## Hosted HeyGen services remain out of scope

The [hosted render guide](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/hyperframes-cli/references/cloud.md)
describes authenticated project upload, `POST /v3/hyperframes/renders`, polling,
and signed artifact download. Narrated creation workflows also use HeyGen TTS
and music retrieval. Local rendering does not require those hosted APIs.

TODO before adding hosted calls: review HeyGen service terms, data handling,
authentication, official pricing, and gateway approval requirements. Hosted
pricing is unknown in this branch. Local runtime infrastructure cost is also
unknown. The Apache license grants software rights and does not establish a
hosted-service price.

## License and attribution

The [upstream LICENSE](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/LICENSE) is Apache-2.0 and contains
`Copyright 2026 HeyGen, Inc.`. Renderhaus keeps the full license unchanged in
[third_party/hyperframes/LICENSE](../third_party/hyperframes/LICENSE).
Apache-2.0 section 4 requires license distribution, prominent modification
notices, retained relevant attribution, and applicable upstream NOTICE content.

There is no root NOTICE at the assessed commit. The
[Renderhaus NOTICE](../third_party/hyperframes/NOTICE) records that absence,
source attribution, and downstream modifications. It does not claim to be an
upstream notice. Adapted skill files mark their changes. The
[third-party notices](THIRD_PARTY_NOTICES.md) document the retained material.

The skipped [talking-head notice](https://github.com/heygen-com/hyperframes/blob/3aa68869f7d4cec8b37cdfcb9cd539389b63abed/skills/talking-head-recut/NOTICE.md)
retains an MIT attribution to `notedit/vtake-skills`, copyright 2026 leeoxiang.
Asset and regression-fixture notices also exist upstream. Those files are not
copied. OpenMontage and guizang-product-video-skill sources are excluded.

## Remaining verification and work

Offline fake-model checks cover routing, preview contracts, and gateway approval
behavior. Real Chromium rendering, media playback, renderer performance, and
visual quality remain unverified. Comet browser E2E is blocked because Comet is
unavailable in this environment. Provisioning the isolated local worker and
reviewing hosted-service terms require separate work.
