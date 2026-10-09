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
