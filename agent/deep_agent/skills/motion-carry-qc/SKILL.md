---
name: motion-carry-qc
description: Check rendered motion graphics, product demos, knowledge explainers for slideshow cuts, missing carry and rhythm faults before human review. This local probe does not assess generative shot identity.
metadata:
  remotion_backend: configured
  remotion_features: clip_timing transitions fit_position scale motion titles captions audio_mix canvas encoding
  include_tools: call_editor_tool
  routing_tools: motion_carry_probe remotion_render
  gateway_tools: Remotion___motion_carry_probe Remotion___render_timeline Remotion___get_render_progress
---

# Motion carry QC

The harness finish rubric uses this skill for relevant renders. Run `inspect_media` on the
current local file and view sampled frames with `read_file`. These harness tools supplement
the saved motion probe. A rubric verdict cannot override a failing or stale probe report.

Discover `Remotion___motion_carry_probe` and call it through `call_editor_tool`.
The canonical routing ID is `motion_carry_probe`. Supply the current Studio
execution's `job_id` and the rendered MP4's `input_path` inside that job.
For an owned local Remotion render, use the poll's staged `output_path` and
`motion_carry_timeline`. Preserve that timing as the probe's `timeline`.
URLs and media in another job cannot be measured. If the completed render is
only available remotely, report local staging as a blocker. Do not fetch it
through a paid provider, change flags, or invent a host path.

When available, preserve exact composition timing in optional `timeline`.
`beats_s` lists zero, each beat boundary, and the measured film duration.
`elements` lists stable `id`, `start_s`, and `end_s`. Optional `keyframes`
contain `time_s` and normalized `[x, y, width, height]` boxes. Mark a known
`main_subject` and an `intentional_exit` only when the storyboard calls for it.
Without exact timing the probe detects scene changes and audio onsets.
Never turn a declared identity into proof of carry. Static identity, a
teleport or fade replacement earns no credit without visible transformation.

The probe is free, local and has no model, network, approval or secret.
`MOTION_CARRY_QC_DRY_RUN` defaults true. A dry-run or skipped report is
incomplete QC. Infrastructure faults fail softly and preserve the render.
Thresholds are PROVISIONAL and were fitted only on our synthetic films.

Selection remains explicit user request, then named exception, then default.
This skill makes no paid calls. Its re-render offer does not authorize a paid
render. Require a saved passing report that still matches the current MP4
checksum before claiming final completion. Open/play the actual artifact
and keep visual review pending until performed. Report delivered width,
height, source_resolution and resolution warnings under final-assembly.

This is an independent clean-room implementation of a published idea.
No third-party code, animation library, look, template, or external threshold
was read or copied. See `docs/MOTION_CARRY_QC.md` for calibration and limits.

The configured Remotion backend must support every requested feature. Unsupported features refuse before media I/O
or AWS submission. Crop/pad reframing requires local/worker; fitted font/box overlays require
Lambda overlay contract version 2 or local/worker. Use named motion presets; arbitrary render
keyframes, per-word kinetic typography and custom components remain unavailable.
