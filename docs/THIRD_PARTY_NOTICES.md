# Third-party notices

## HyperFrames

Renderhaus adapts selected motion-graphics guidance from
[heygen-com/hyperframes at commit 3aa68869f7d4cec8b37cdfcb9cd539389b63abed](https://github.com/heygen-com/hyperframes/tree/3aa68869f7d4cec8b37cdfcb9cd539389b63abed),
assessed on 2026-10-08. Copyright 2026 HeyGen, Inc.

The upstream work uses Apache-2.0. Renderhaus retains the complete
[license](../third_party/hyperframes/LICENSE) and records attribution and
modifications in a [Renderhaus notice](../third_party/hyperframes/NOTICE).
The assessed upstream has no root NOTICE file. Adapted skill files carry
prominent modification notices.

The adaptation retains composition, storyboard, kinetic-title, product-launch,
and readable-caption guidance. It removes upstream installation, hosted API,
credential, telemetry, publishing, and script-dispatch instructions. Remotion
remains the default. The optional tool exposes dry-run previews only.

No HyperFrames runtime, registry assets, fonts, matting models, or scripts are
vendored. The skipped `talking-head-recut` skill has a separate MIT attribution
chain and is not included. OpenMontage and guizang-product-video-skill sources
are not included.

See [the assessment](HYPERFRAMES_ASSESSMENT.md) for the source files, per-skill
decisions, runtime requirements, and remaining work.
