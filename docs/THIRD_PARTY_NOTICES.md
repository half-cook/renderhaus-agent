# Third-party notices

## browser-use/video-use

The [conversational-edit skill](../agent/deep_agent/skills/conversational-edit/SKILL.md)
adapts workflow patterns from [browser-use/video-use](https://github.com/browser-use/video-use).
The upstream README, SKILL.md and LICENSE were read on 2026-10-08.
Copyright (c) 2026 Browser Use. The upstream MIT notice is retained verbatim in
[third_party/video-use/LICENSE](../third_party/video-use/LICENSE).
The runtime image copies the notice, and Python distributions include it as a license file.

The adapted patterns cover transcript-led cutting, review before execution, short audio
fades, output-relative caption timing, subtitles after overlays, and output inspection.
The provider code uses Renderhaus's existing Remotion contract. No upstream helper code
or full repository is vendored. No code or text from the AGPL projects OpenMontage or
guizang-product-video-skill is included.

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

## HyperFrames cinematic-caption and tactile-collage packs

The existing HyperFrames skill expands with adapted recipes and example HTML from
[audrey-560/hyperframes-cinematic-caption at 6cdb01d74949cab379e048e9092709adbb3b203b](https://github.com/audrey-560/hyperframes-cinematic-caption/tree/6cdb01d74949cab379e048e9092709adbb3b203b)
and [audrey-560/hyperframes-tactile-collage at ef6a49f5a250e6b3b1a0839cafc7a2d43872e619](https://github.com/audrey-560/hyperframes-tactile-collage/tree/ef6a49f5a250e6b3b1a0839cafc7a2d43872e619).
Both full upstream LICENSE files were read on 2026-10-09. Both are MIT,
Copyright (c) 2026 Audrey.

The complete copyright, permission, and warranty notices remain verbatim in
[cinematic-caption LICENSE](../third_party/hyperframes-cinematic-caption/LICENSE)
and [tactile-collage LICENSE](../third_party/hyperframes-tactile-collage/LICENSE).
Python distributions include both licences and the adapted resources. The
AgentCore image copies the `third_party/` directory. Adapted files identify their
upstream source and Renderhaus modifications.

Caption recipes retain semantic emphasis, reading order, translucent hero text,
safe placement, and contact-sheet review. Collage recipes retain paper/ink roles,
physical scene grammar, safe layering modes, and restrained motion.
Renderhaus replaces installation and script dispatch with the existing preview
contract. It removes the hidden tactile template root and uses host-provided
GSAP only as a future rendering requirement. No upstream font data, installer,
transcription, segmentation, third-party footage, or hosted API is included.

These packs remain resources inside the `hyperframes` skill. Remotion stays the
default renderer. Their permissive code licences do not authorize training on
customer source media. See [pack details](HYPERFRAMES_TEMPLATE_PACKS.md) for
the preview contract and remaining verification.
