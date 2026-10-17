# Silent knowledge explainers

The [knowledge-explainer skill](../agent/deep_agent/skills/knowledge-explainer/SKILL.md)
plans graphic beats, readable on-screen copy and sound effects at the same event timestamps.
It has no narration or TTS step. A whiteboard request with voiceover retains
`whiteboard-explainer`; adding Foley to an existing clip retains `audio-bed`.

## Existing tools and native arguments

No provider or Gateway tool is added. The skill reuses these discovered tools:

The packaged JSON separates its event plan from renderer arguments. Each beat records an
ID, onset, duration, graphic action, on-screen text, source and optional SFX cue. Discover
schemas before dispatch and send only native arguments. Text-described one-shots use
ElevenLabs; completed audio assets attach to `audio_tracks` at their planned event onsets.
Video input uses Mirelo after a silent render completes. Mirelo returns a video with audio,
not a separate audio track, and its API has no event-timestamp argument. The beat list guides
its prompt; actual synchronization requires playback inspection. Use final assembly when
the requested delivery still needs it, preserving the muxed audio.

Remotion currently accepts prepared image/video assets and timed text, rather than arbitrary
React or custom scene code. The original sample uses a static SVG diagram and timed labels.
Its data URL is compatible with Lambda; the local backend requires an approved image staged
at an authorized local path.
Unsupported path drawing, bespoke chart animation or camera motion requires prepared assets
or a clear blocked result. Local rendering rejects motion, grade and rotation controls;
Lambda's new fitted-font/box fields require the matching composition version. See
[local assembly](LOCAL_ASSEMBLY.md) and [Remotion editing](REMOTION_EDITING.md).

Keep measured source FPS and resolution for final assembly unless explicitly requested
otherwise. Report delivered width and height, `source_resolution` and resolution warnings.
A 1920x1080 canvas from 1280x720 must say "upscaled from 1280x720; no added detail". Native
1280x720 is 720p. Unknown source dimensions remain unknown. The existing Topaz `upscale`
skill provides enhancement with its existing approval gate.

## Official source checks, 2026-10-09

The existing billing system adds the Renderhaus fee. Do not present raw provider rates as a
guaranteed customer total. Existing paid-video cost approval, autonomous premium-video gate,
approval exemptions and spend cap remain in force. Rejection must not resubmit. Speech-producing
endpoints cannot dispatch for the silent workflow, including through an approved resume.

## Routing and validation

Offline tests exercise routing, speech rejection before approval/provider access, native
timeline cue placement, packaged skill loading and Deep Agents 0.7.23 autonomous
Mirelo approval/rejection/resume with fake Gateway transports. They establish plan and policy
behavior, not rendered media quality. Full check results are in

The required full suite exposed a pre-existing intermittent Studio charging failure under
concurrent allowance use. The fix reserves the SQLite write transaction before reading
either the daily allowance or wallet, preserving charge amounts, approvals and spending
limits. The regression covers separate repository connections, both exhausted balances and
refusal without extra charges. Full validation passed: 1,713 tests with 47 skips, Ruff, CI
and Studio TypeScript. The offline wheel contains all 26 skills and the exact packaged
knowledge template. CI builds its Lambda package using cached wheels with index access
disabled. Independent review also verified rollback after an injected mid-charge error.

Comet browser E2E is blocked: no controllable Comet session is available, and this task
prohibits live provider calls. No browser actions, generated playback, audio alignment or
factual/visual acceptance are claimed. Studio concurrent charging and visible balances also
remain untested in Comet. The ignored `.renderhaus/e2e/` report records these blockers through
`scripts/browser_e2e_hook.py`.

No new environment variables, dry-run flags, secrets, model policies, Studio labels or
Gateway schemas are needed. Reuse existing `FAL_KEY`, `ELEVENLABS_API_KEY`, renderer setup
and their default-true dry-run flags. Public source reads use no provider credentials.
