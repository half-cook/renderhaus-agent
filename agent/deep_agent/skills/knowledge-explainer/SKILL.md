---
name: knowledge-explainer
description: Create silent graphic knowledge or science explainers with on-screen text and event-synced sound effects. No narration or TTS. Remotion is the default; use HyperFrames only when explicitly named.
metadata:
  include_tools: call_editor_tool call_media_tool call_audio_tool
  routing_tools: remotion_render hyperframes_render mirelo_v2a elevenlabs_sfx_v2
  gateway_tools: Remotion___render_timeline Remotion___get_render_progress HyperFrames___render_composition Fal___mirelo_v2a Fal___get_video_task ElevenLabs___text_to_sound_effects_convert
---

# Silent knowledge explainer

Use this skill for no-narration knowledge shorts and graphic explainers with
sound effects synced to on-screen events. Graphics and labels carry the claim.
Do not create narration, dialogue, voice clones, or TTS. For a whiteboard brief
with voiceover, read [whiteboard-explainer](../whiteboard-explainer/SKILL.md).
For sound added to an existing clip, read [audio-bed](../audio-bed/SKILL.md).

## Plan the event timeline

Read `read_studio_context` and follow its `intent_route`. Save the supplied
sources, approved text, asset version handles, aspect ratio, and duration.
Choose one claim. Keep every sentence of the supplied source script on screen,
using quieter labels for secondary detail. Split crowded beats instead of
dropping claims. Use one primary graphic action per beat, and hold labels long
enough to read.

Save an event list before generation or rendering. Each event records `event_id`,
`start_seconds`, `duration_seconds`, `graphic_action`, `on_screen_text`, and
`source`. An optional `sfx` records its routing ID, sound description, duration,
and completed asset handle. Derive each cue's onset from its event's
`start_seconds`, so edits move picture and sound together. Keep cues inside the
composition and align their starts to its frame rate.

Prototype one representative beat before extending the composition. For an
asset-only sample, read [the silent graphic template](templates/silent-graphic.json)
through `/skills/knowledge-explainer/templates/silent-graphic.json`. Replace its
illustrative labels with approved source text. Copy only `arguments` to the
Remotion call. The separate `events` list is a saved plan, not a Gateway argument.
Generate each text-described cue with its discovered schema, then attach its
completed asset to `audio_tracks` at the event's `start_seconds`. The template's
empty audio list supplies silent picture, not the finished SFX export.
The embedded SVG data URL is a Lambda sample. For local rendering, replace it
with an approved PNG asset or a provider-returned local media path. The local
renderer rejects data URLs. Report a missing compatible source as a blocker.

## Choose the renderer and sound source

Default to `remotion_render` through `Remotion___render_timeline`. Read
[motion-graphics](../motion-graphics/SKILL.md) for the supported timeline contract.
Use supplied images or videos, supported motion, and `text_overlays` for labels.
The renderer does not accept arbitrary HTML, JSX, animated diagrams, marker
hands, or an event-list API. Report unsupported motion or missing assets.
For diagram art, read [image-gen](../image-gen/SKILL.md), which uses GPT Image 2.5
by default and Recraft V4.1 for editable SVGs.

Use `hyperframes_render` only when the user names HyperFrames. Read
[hyperframes](../hyperframes/SKILL.md) for a seekable HTML composition. Derive all
animation state from time, so any frame can be inspected. Report disabled or
unavailable tools as blockers. The current HyperFrames tool validates inputs
only. Rendering, audio mixing, and MP4 export remain pending.

Choose SFX by input, following [audio-bed](../audio-bed/SKILL.md):

- With completed silent picture, default to `mirelo_v2a` through
  `Fal___mirelo_v2a` using `call_media_tool`. Finish and poll the picture render
  first. Supply its authorized `video_url`, measured `duration` of 1-60 seconds,
  `num_samples=1`, and optional `text_prompt` describing the planned sounds.
  Mirelo has no event-timestamp argument. Timing is a quality target that needs
  playback inspection. It returns a video with audio, not a separate audio file.
  Submit once after approval, preserve `job_id`, and poll `Fal___get_video_task`
  with `download=true`.
- For text-described one-shots, use the `elevenlabs_sfx_v2` exception through
  `ElevenLabs___text_to_sound_effects_convert` with `call_audio_tool`. Supply
  `text`, `duration_seconds` of 0.5-30, and `model_id=eleven_text_to_sound_v2`.
  Save the returned audio asset. Place each cue in Remotion's `audio_tracks`
  with its event's `start_seconds`, cue `duration_seconds`, `source_in_seconds`,
  `volume`, and any fades. This model does not see the picture.

Honor a supported explicit SFX provider before the input exception or default.
An ambient bed uses the same SFX tools and stays below the event cues. Do not add
music or vocals by default. Avoid generating both a Mirelo track and duplicate
one-shots for the same events unless the user requested the combination. Mute
original visual audio with `volume=0` when replacing it. Preserve Mirelo's muxed
soundtrack when using that result.

Paid generative B-roll is outside the default graphic path. If the user requests
AI B-roll, read the appropriate video skill and obtain its existing cost approval.
Honor an explicitly named built video provider through
[named-provider](../named-provider/SKILL.md). Keep Remotion as the assembly
default unless HyperFrames is explicitly named. Cost never selects a provider.

## Render and verify

Discover exact schemas before each dispatch. Use asset handles from saved tool
results or Studio context. Planning fields never become extra Gateway arguments.
For text cues, assemble graphics, labels, and completed SFX in one Remotion render.
For Mirelo, render silent picture first, then score that result. Its completed
MP4 already has the soundtrack. Reassemble it through Remotion only when the
requested delivery still needs edits or mixing. Preserve its soundtrack and
measured timing.

Read [final-assembly](../final-assembly/SKILL.md) for source resolution, frame
rate, bitrate, polling, and output reporting. Omit `fps`, `video_bitrate`, and
`output_resolution` unless the user sets them. The template's explicit frame
rate applies to its asset-only sample. Remove it when adapting the sample to
video sources unless the user requests that rate.

Disclose provider, model, selection reason, and estimated cost before dispatch.
Remotion and Mirelo follow the existing paid-video approval policy, including
autonomous runs. Text SFX follows the existing audio approval and spend cap.
Respect dry-run flags and unknown quotes. Preserve successful assets and job IDs
during recovery. A rejected approval ends that action until the user asks again.

Open and play the final MP4. Inspect cue timing, label readability, quiet gaps,
duration, and the absence of speech. Recheck after edits. Deliver only after
successful rendering or Mirelo polling supplies an MP4 and playback confirms it. Otherwise
report an incomplete export with saved job IDs and blockers. State delivered
`width`, `height`, `source_resolution`, and every resolution warning as directed
by final-assembly. Record visual acceptance or rejection only after explicit
user review. Spending approval is not visual acceptance.
Trim only empty dark gaps without on-screen text. If requested, choose a cover
and write publishing copy from finished frames. Keep the cover outside the timeline.

The MIT-licensed [vibe knowledge video skill](https://github.com/LuZhong-Li/vibe-knowledge-video-skill)
is a pattern reference only. No upstream text, code, runtime, dependencies, or
weights are included. Renderer and SFX terms remain those of the existing tools.
