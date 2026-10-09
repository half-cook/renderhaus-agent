# Upscale provider reference

Status: built in feat/finishing-topaz, default dry-run.

The installed [upscale skill](../../agent/deep_agent/skills/upscale/SKILL.md) contains the
workflow. Canonical routing IDs `topaz_upscale` and `topaz_interpolate` map to
`Topaz___upscale_video` and `Topaz___interpolate_video`; poll `Topaz___get_video_task`.
Starlight Precise 2.6 is the upscale default, Apollo the interpolation default, and Chronos
the plain linear-motion FPS exception. Explicit model requests win. SeedVR2 and RIFE stay retired.

See [Topaz](../TOPAZ.md) for typed arguments, verified endpoints, price examples,
service licences, unknown-price blockers and blocked Comet validation. All submits pause
with cost even when autonomous. Previews are not media. Outputs are not training eligible.
