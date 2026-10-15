---
name: motion-graphics
description: Assemble lower thirds, captions, explainers, channel intro stings and YouTube end screens using the built Remotion timeline contract.
metadata:
  remotion_backend: configured
  remotion_features: named_templates clip_timing transitions fit_position scale motion titles captions audio_mix canvas encoding
  include_tools: call_editor_tool call_media_tool
  gateway_tools: Ffmpeg___ffmpeg_tool Remotion___render_timeline Remotion___get_render_progress Remotion___export_nle_timeline HyperFrames___render_composition Remotion___motion_carry_probe
  routing_tools: remotion_render hyperframes_render ffmpeg_tool motion_carry_probe
---

# Motion graphics

Remotion is the default renderer. For a request explicitly naming HyperFrames, read
[HyperFrames](../hyperframes/SKILL.md) and follow the host's optional-tool route.

Read `read_studio_context` and reuse existing assets. Search Gateway for Remotion's
exact `render_timeline` schema. `remotion_render` maps to `Remotion___render_timeline`
through `call_editor_tool`. Build its native `title`, `visuals`, `audio_tracks`,
`text_overlays`, `aspect_ratio`, and `fps` arguments. Do not send arbitrary JSX,
a composition source string, or an invented animation contract.
Omit `output_resolution` unless the customer requests a resolution. Follow
[final assembly](../final-assembly/SKILL.md) for source-sized canvases and truthful delivery
dimensions, including warnings when clips are upscaled or source dimensions are unknown.

Each visual needs `kind`, `url`, and `duration_seconds`. Set timing with `start_seconds`
and `source_in_seconds`. Use supported `motion`, `scale`, position, `fit`, and transitions
for simple movement. Text overlays need `text`, `start_seconds`, and `duration_seconds`;
choose native position, color, size, weight, and fades. The built contract supports these
titles and motions. Measured word highlights are available through the bounded
[podcast audiogram](../podcast-audiogram/SKILL.md) template; arbitrary kinetic typography
or custom components need a future integration. Explain that limit for a brief requiring unsupported animation.

For missing image assets, read [still images](../image-gen/SKILL.md) and use the matching
default or specialist. Recraft vector output and Ideogram text-only edits use the built
image-gen exceptions. A supplied existing Ideogram asset needs no generation.
Do not promise SVG from a raster tool.

## Channel intro and YouTube end-screen templates

If the user supplies a raster logo for a reveal, sting, splash or loader, read
[logo animation](../logo-animation/SKILL.md). That workflow traces and audits the logo
locally, then requires explicit approval of the static SVG before rendering.
Channel intros without a supplied logo remain in this skill.

Keep these inside motion-graphics. Discover the existing timeline schema and set its
`template.name` to `youtube-intro-sting` for a 3–5 second logo sting, or
`youtube-end-screen` for an exactly 20-second 16:9 end-screen plate. Use `visuals=[]`,
`duration_seconds`, supplied `logo_url`, `show_name` and bounded RGB colors. Optional
source audio spans the full template at volume 1 and zero fades. These templates own
their geometry and reject audiogram words, captions, amplitudes and correction options.
Use customer art; no vendor logos. User-facing labels are “Channel intro” and
“YouTube end screen”.

The end-screen planner declares video/playlist and subscribe/channel reservations as
normalized data. Its logo/text boxes must stay outside those rectangles. The exact native
element geometry is UNVERIFIED: official help read 2026-10-10 verifies a last 5–20 second
window, a minimum 25-second uploaded video and up to four elements for standard 16:9,
not fixed pixel zones. Re-verify current official limits and actual YouTube Studio element
placement before shipping. Append the plate to a sufficiently long video; no upload or
native-element insertion tool is added. Read [the zone data and contract](../../../../docs/PODCAST_AUDIOGRAM.md).

Local rendering supports these templates. Lambda refuses until the operator deploys the
checked matching composition and sets `REMOTION_TEMPLATE_CONTRACT_VERSION=1`; never set
that declaration yourself. Template art uses that versioned contract without a separate
overlay version requirement. Review a full first render plus extracted stills at 10% and
60% through the real ffmpeg `extract_frames` operation; obtain visual approval before
extra aspects. Play the full video with audio and run loudness/deliverable QC for each output.

## Plan timing and reuse media

Save a short project brief with the audience, intended takeaway, required copy, brand
references, duration, aspect ratio, and explicit delivery controls. Keep user-approved
choices and rejected approaches in that brief. Reference it during revisions instead of
repeating the full production history.

Use a compact storyboard table. Give each scene a stable ID, start and end seconds,
visual action, audio cue, exact on-screen text, and a visible check for completion.
Expand only the scene being changed. Keep this planning table in project files.
translate it into the discovered timeline fields before dispatch.

When the brief requests music sync, derive cuts, visual entrances, and audio cues from
one beat schedule using supplied timing or measured music beats. Record the timing source
and any unverified BPM or first-beat offset. Do not invent beat measurements. Align cue
times to the composition's frame grid, preserving the source frame rate unless requested
otherwise. After an audio edit, recheck the schedule against the edited track.
For event-led motion without music, use the planned event times instead of imposing a BPM.
Read [audio bed](../audio-bed/SKILL.md) when new sound assets are needed.

Maintain a media ledger with exact asset version handles, saved call and job IDs, completed
output handles, measured durations, and approval and verification states. Preserve identifiers
unchanged. Read the ledger before generating replacements or submitting another render.
Prefer stable asset handles in saved files. Keep credentials and signed URL query strings
out of review evidence. A stage handoff names its task, relevant brief and ledger paths,
changed scenes, expected output, and checks. It never assumes access to earlier conversation.

## Preview and verify

Validate supported arguments against the discovered schema before submitting. Preview one
representative beat with the native timeline before expanding a long composition, when a
render is authorized. Keep the requested delivery controls. Disclose preview and full-render
cost estimates through the existing approval flow. An unknown quote stays unknown.
Remote resource limits and render times stay unknown unless the host measures them.
Do not import upstream RAM thresholds or token-saving percentages as measured facts.

Submit one render and preserve `render_id`, `bucket_name`, and `output_key` unchanged.
Poll `Remotion___get_render_progress` and inspect the completed MP4 before delivery.
Batch timestamped frame-review requests when inspection tools are available. Check the
opening and closing frames, each scene's settled text, and frames on both sides of important
cuts or reveals. Inspect text clipping, missing glyphs, overlaps, unexpected blank frames,
and the exact approved copy. Play the full saved MP4 with its audio to check rhythm, cue
alignment, holds, and the ending. Still frames alone cannot verify motion or sound sync.
Record what was planned, what was observed, the artifact handle, and any failures or pending
visual review. If playback or inspection is unavailable, report verification as incomplete.
After edits, inspect the new output and affected neighboring transitions again.

For delivery presets or technical media checks, read
[delivery render](../remotion-delivery-render/SKILL.md) and
[deliverable QC](../remotion-deliverable-qc/SKILL.md). Those workflows require a saved passing
QC report that still matches every output checksum. Report each failure verbatim.
Technical checks leave framing, captions, legal copy, and prices pending visual review.
For a file-based editor handoff, read [Resolve handoff](../resolve-handoff/SKILL.md)
and use `Remotion___export_nle_timeline`. Bake unsupported titles or effects before export.
Do not claim NLE export renders those effects automatically.

The external remotion-dev skills repository is optional reference material only.
No upstream skill content is vendored here, and no upstream licence grant is assumed.

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.

Follow `read_studio_context.intent_route`. Selection uses the explicit requested provider/model,
then a named exception, then the capability default. Cost estimates support approval and disclosure;
they never select a provider. Pending defaults use only the policy's declared interim tool.
Disclose provider, model, estimated cost and `default`, `exception: <reason>`, `explicit request`,
or `interim default until <provider> lands` before each dispatch. Unknown prices stay unknown.
All paid video pauses for approval even in autonomous runs when `premium_video_approval` is enabled.
Paid non-video retains the existing non-autonomous approval and autonomous spend cap.

Search Gateway for the selected built tool and use its exact schema through the matching role.
Pending aliases are routing identifiers, not Gateway endpoints. Never invent a tool or change a
DRY_RUN flag to satisfy a request. Submit once, preserve the returned job ID, and poll the same job.
A queued job or dry-run is incomplete media. Open/play the actual saved artifact before delivery.
Record explicit customer visual acceptance/rejection with `record_media_outcome` and the saved call ID.
A spending approval is not visual acceptance. Training eligibility follows provenance and the existing
Wan training hook; these routing instructions cannot grant training rights.

## References

The guidance above paraphrases these pattern sources. No upstream text, scripts, runtime,
dependencies, or weights are vendored. Their licences do not grant rights to project media
or change model training eligibility. Renderer terms remain those of the existing tools.

- [Agent-Video-Driver.SKILL](https://github.com/JularDepick/Agent-Video-Driver.SKILL/blob/069577f138f75deccbd3b7a799e1571a9f9eaedd/skills/agent-video-driver/SKILL.md), by JularDepick.
  [Apache-2.0 licence](https://github.com/JularDepick/Agent-Video-Driver.SKILL/blob/069577f138f75deccbd3b7a799e1571a9f9eaedd/LICENSE), read 2026-10-10.
  Its [beat-sync](https://github.com/JularDepick/Agent-Video-Driver.SKILL/blob/069577f138f75deccbd3b7a799e1571a9f9eaedd/skills/agent-video-driver/references/beat-sync.md),
  [prompt planning](https://github.com/JularDepick/Agent-Video-Driver.SKILL/blob/069577f138f75deccbd3b7a799e1571a9f9eaedd/skills/agent-video-driver/references/prompt-scaffolding.md), and
  [verification](https://github.com/JularDepick/Agent-Video-Driver.SKILL/blob/069577f138f75deccbd3b7a799e1571a9f9eaedd/skills/agent-video-driver/references/verification.md)
  inform shared cue timing, bounded stage briefs, frame review, and final playback.
- [motion-efficiency](https://github.com/Ninesam-9/motion-efficiency/blob/925cb290c424db5aec2089e354335fe6a3a16b1d/SKILL.md), by NINECODE.
  [MIT licence](https://github.com/Ninesam-9/motion-efficiency/blob/925cb290c424db5aec2089e354335fe6a3a16b1d/LICENSE), read 2026-10-10.
  It informs compact scene tables, exact media ledgers, focused revisions, batched inspection,
  and cost disclosure with existing approval and verification gates.

- Channel template pattern: [iart-ai/youtube-video-skills](https://github.com/iart-ai/youtube-video-skills/blob/f3df381d65abe5078f5ed410bbc3ed72e7cb92bd/skills/youtube-intro-outro/SKILL.md)
as a pattern, read 2026-10-10. Its
[MIT licence](https://github.com/iart-ai/youtube-video-skills/blob/f3df381d65abe5078f5ed410bbc3ed72e7cb92bd/LICENSE)
and attribution are recorded in [NOTICE](../../../../providers/remotion/NOTICE.md).
No upstream runtime, assets or dependency is copied.


After a completed MP4 render, read [motion-carry-qc](../motion-carry-qc/SKILL.md)
and run `motion_carry_probe` through `Remotion___motion_carry_probe` with the owned
local MP4 and exact beat timing when available. Surface any failed report and
offer a re-render before presenting the film as final. A dry-run, missing MP4
or skipped probe is incomplete QC. This free local check grants no paid calls.

The configured Remotion backend must support every requested feature. Unsupported features refuse before media I/O
or AWS submission. Crop/pad reframing requires local/worker; fitted font/box overlays require
Lambda overlay contract version 2 or local/worker. Use named motion presets; arbitrary render
keyframes, arbitrary kinetic typography and custom components remain unavailable. Bounded
audiogram word highlights and channel templates use the named_templates contract.
