# Media timing and recovery

## Remotion

`remotion/src/Root.tsx` registers `RenderhausTimeline` and supports images with camera motion,
frame-decoded video, audio with source trims/fades, and text layers. Visual track ends set the
composition duration. Music starting after the visual end is rejected; music crossing that
end is clipped. A 30-second visual edit with a 188-second score still exports 30 seconds.
2.39:1 uses codec-compatible 1920×804 dimensions, including at 24 fps.

The provider stores the actual output key under `renders/<render_id>/...` and returns a durable
Studio asset only after completion. The manager tracks provider identifiers, checks an existing
unfinished render before starting replacements, and distinguishes failed polling from failed
rendering. A request requiring video cannot be marked completed without a successful Remotion
MP4 result. Polling and approval changes do not silently retry paid media creation.

## ElevenLabs music duration

`ElevenLabs___music_compose` accepts exactly one of `prompt` or `composition_plan_json`.
With a prompt, `music_length_ms` requests 3000–600000 milliseconds; use
`force_instrumental=true` for music without vocals. Composition plans specify section timing.
The tool returns completed audio. Dubbing and Flows use their own asynchronous status tools.
Keep source audio intact and use Remotion to enforce the final video's exact duration.
See [ElevenLabs setup and full catalog](ELEVENLABS.md).

## Verification

Run the Python media/harness tests, `npm run typecheck --prefix remotion`, and the Studio build.
Then follow [BROWSER_E2E.md](BROWSER_E2E.md) in signed-in Comet with the real backend. Reuse
existing assets for a small export. Observe the approval, progress, final artifact, playback,
duration, and recovery across reload. API health and a queued render are insufficient.
