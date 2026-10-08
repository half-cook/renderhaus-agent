# Runway skill guidance draft

Status: provider built. Guidance is incorporated in the live t2v, i2v, edit-v2v, and product-images skills.
The live skills and `agent/deep_agent/routing_policy.json` define current routing.

This provider reference informs the installed intent skills. Those skills own live routing.

## Choose Runway for the requested media operation

Route to Runway when the user requests Runway, Gen-4.5, Gen-4 Image, or Aleph, or when
an existing clip needs a generative visual edit. Use Aleph to change the scene,
objects, appearance, or lighting in a source clip with a text instruction.
Use the ordinary composition renderer for cuts, titles, audio placement, and assembly.

Use `Runway___text_to_video` for a new clip from text.
Use `Runway___image_to_video` to animate an existing image.
Use `Runway___video_to_video` for an existing clip, a text edit instruction, and
an optional guidance image at a stated timestamp.
Use `Runway___text_to_image` for a new still from text.
Use `Runway___image_to_image` for reference-based image generation or variation.
Gen-4 Image Turbo requires a source image and is available only through the reference tool.

Search Gateway for the concrete intent and inspect the returned tool schema.
`Runway___list_runway_models` returns a free local supported-model catalog.
It does not prove current account access. Do not invent a live model-list endpoint.

## Submit once and poll the same task

1. Resolve existing Studio media through its durable asset handle.
2. Check the model, prompt, dimensions, duration, and reference constraints in the tool schema.
3. Confirm the user's existing spending authorization covers the quoted generation.
4. Submit the matching creation tool once and retain its `job_id`.
5. Call `Runway___get_runway_task` with that ID at least five seconds apart.
6. On `succeeded`, save every returned image or video through Studio's asset registration path.
7. Return the durable asset reference and verify that the actual artifact opens or plays when browser access is available.

Continue polling `queued` and `running`. Treat `failed`, `cancelled`, and `dry_run`
as terminal outcomes with no usable generated artifact. A task being accepted is
not a completed generation. An HTTP 404 does not prove which cancellation/deletion
case occurred. Preserve the error and task ID. Do not resubmit a paid generation
without authorization just to recover a polling or download error.

## Enforce input and spending rules

Gen-4.5 uses `gen4.5` and integer durations of 2-10 seconds. Aleph uses `aleph2` and
edits a 2-30 second source clip at up to 1080p and 30 FPS. Supply its measured
`video_duration_seconds` for the cost quote. The live Studio host measures the
source with ffprobe and overwrites that value before billing, then submits the
exact measured bytes. An external Runway upload handle cannot be measured for an
Aleph Studio quote; use an owned Studio clip, HTTPS source, or data URI instead.
A guidance image becomes a keyframe
at `reference_seconds`. Do not send an output duration or deprecated ratio to Aleph.

Use HTTPS URLs with domain hostnames, correct media headers, HEAD support, and no
redirects. Reuse valid `runway://` handles or small supported base64 data URIs.
The adapter caps encoded image and Aleph video data URIs at 5 MiB. Do not pass
browser credentials, local arbitrary paths, expired upload handles, or large encoded media.
Studio publishes owned input handles as small data URIs or official ephemeral uploads
using their stored media metadata. Runway still validates media compatibility.
Use local Studio execution; generation through the optional separate AgentCore
runtime is blocked until its asset and task context is connected.

`RUNWAY_DRY_RUN` defaults to true. A dry-run submits no paid task, returns no generated
media, and costs zero. Only an operator's explicit false setting enables live calls.
Never change dry-run settings or fetch keys merely to satisfy a test.

The published 2026-10-08 provider rates are $0.12/second for Gen-4.5,
$0.28/second for Aleph with a $0.56 minimum, $0.05 or $0.08 per Gen-4 Image by
supported resolution tier, and $0.02 per Image Turbo. Use server billing for the
quote and its disclosed platform fee. Polls and model listing are free.
Do not invent prices for unsupported dimensions or output formats. Fractional
Aleph invoice rounding and later task-failure reconciliation remain unverified.

## Apply the provider's terms

Follow [Runway terms](https://runway.com/terms-of-use) and the
[attribution requirements](https://docs.dev.runwayml.com/usage/attribution/).
Use the required "Powered by Runway" label and link in applicable interfaces.
Ensure the user has rights to source/reference content and follows the provider's
usage rules. Do not promise ownership, exclusivity, or a blanket commercial licence.
The current agent's final-video assembly policy remains in effect until its backend
migration deliberately changes that policy.

## Report limitations accurately

Use [the provider reference](../RUNWAY.md) for tool arguments, pricing, and documented
OpenAPI/input-guide discrepancies. Never call a mocked or dry-run check real E2E.
If Comet, login, a key, or spending authorization is missing, record blocked browser
verification and report that the live API and actual artifact remain unverified.
