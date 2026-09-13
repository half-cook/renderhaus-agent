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

## Mureka duration support

Reviewed against the official documentation on September 11, 2026:

- Standard [instrumental generation](https://platform.mureka.ai/docs/api/operations/post-v1-instrumental-generate.html)
  has **no exact-duration request field**. A prompt saying “30 seconds” is musical guidance,
  not a hard limit. Keep the original score available and set the final Remotion timeline length.
- [Soundtrack generation](https://platform.mureka.ai/docs/api/operations/post-v1-soundtrack-generate.html)
  uses an uploaded `image_id` or `video_id` (exactly one, upload purpose `soundtrack`).
  `audio_start` / `audio_end` are **integer milliseconds**, minimum 3000 ms apart. For example,
  `audio_start: 0, audio_end: 30000` requests a 30-second range. The service caps ranges to its
  available music and adds its own fades; video-only duration follows the video within that cap.
- Generation defaults to `n: 1` in Renderhaus to avoid unrequested extra variations. Soundtrack
  results must be polled with `kind: "song"`; instrumental jobs use `kind: "instrumental"`.
  Explicit kind survives Lambda cold starts, unlike in-memory job metadata.

No unsupported duration parameter is sent to the standard generation endpoint. Exact output
duration is enforced in the final video. The granular soundtrack request contract is covered
by tests; it should not be described as live provider-tested without its own browser receipt.

## Verification

Run the Python media/harness tests, `npm run typecheck --prefix remotion`, and the Studio build.
Then follow [BROWSER_E2E.md](BROWSER_E2E.md) in signed-in Comet with the real backend. Reuse
existing assets for a small export. Observe the approval, progress, final artifact, playback,
duration, and recovery across reload. API health and a queued render are insufficient.
