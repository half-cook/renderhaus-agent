# Silent knowledge explainers

The [knowledge-explainer skill](../agent/deep_agent/skills/knowledge-explainer/SKILL.md)
plans graphic beats, readable on-screen copy and sound effects at the same event timestamps.
It has no narration or TTS step. A whiteboard request with voiceover retains
`whiteboard-explainer`; adding Foley to an existing clip retains `audio-bed`.

## Existing tools and native arguments

No provider or Gateway tool is added. The skill reuses these discovered tools:

| Routing ID | Gateway tool | Key arguments |
| --- | --- | --- |
| `remotion_render` | `Remotion___render_timeline` | `title`, `visuals`; optional `text_overlays`, `audio_tracks`, `subtitles`, `aspect_ratio`, `fps`, `output_resolution` |
| Renderer poll | `Remotion___get_render_progress` | Returned `render_id`, `bucket_name`; `download=true` |
| `hyperframes_render` | `HyperFrames___render_composition` | `html`, `duration_seconds`, `width`, `height`, `fps` |
| `mirelo_v2a` | `Fal___mirelo_v2a` | `video_url`, optional `text_prompt`, measured `duration`, `num_samples=1`, optional `seed` |
| Mirelo poll | `Fal___get_video_task` | Returned `job_id`, `download=true` |
| `elevenlabs_sfx_v2` | `ElevenLabs___text_to_sound_effects_convert` | `text`, optional `duration_seconds`, `loop`, `prompt_influence`, `output_format`, `model_id=eleven_text_to_sound_v2` |

Selection remains explicit request, matching exception, then capability default. Remotion
renders by default. HyperFrames requires its name and enabled local discovery. Its current
adapter only previews composition metadata and refuses live rendering without an isolated
worker. It cannot deliver an MP4 here. An explicitly named video-generation provider retains
its named route and disclosure; graphic assembly still uses Remotion. Confidential metadata
and price-tier words do not change selection.

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

| Component | Verified API or licence | Price and training decision |
| --- | --- | --- |
| Mirelo SFX 1.6 on fal | [Official API](https://fal.ai/models/mirelo-ai/sfx1.6/video-to-video/api): `mirelo-ai/sfx1.6/video-to-video`, video input and muxed-video output. Closed weights, commercial hosted service under [fal terms](https://fal.ai/legal/terms-of-service). | [Official model pricing](https://fal.ai/models/mirelo-ai/sfx1.6/video-to-video): $0.01/generated second for one sample. Samples 2–4 remain UNVERIFIED and dry-run-only. Existing `training_eligible=false`: competing-model restrictions and no verified general training grant. |
| ElevenLabs Sound Effects V2 | [Official API](https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert): `/v1/sound-generation`, `eleven_text_to_sound_v2`, optional 0.5–30 seconds. Proprietary hosted service; [terms](https://elevenlabs.io/terms-of-use) allow commercial use on paid plans; free-plan outputs are non-commercial and unsuitable here. | [Official API pricing](https://elevenlabs.io/pricing/api) lists $0.12/minute but also describes generation-based metering. TODO: exact per-call quote remains `unknown` unless an operator supplies `ELEVENLABS_TOOL_COST_CENTS_JSON`. Existing `training_eligible=false`: no verified output-training grant. |
| Remotion renderer | [Official submit](https://www.remotion.dev/docs/lambda/rendermediaonlambda) and [poll](https://www.remotion.dev/docs/lambda/getrenderprogress) APIs. [Licence](https://github.com/remotion-dev/remotion/blob/main/LICENSE.md): free for individuals, nonprofits and companies with at most three employees; other companies need a commercial licence. | No flat Lambda quote verified; estimate `unknown`. The existing eight-cent billing placeholder is not a verified price. Local provider charge is zero, excluding operator compute. No model is added; renderer use grants no training rights to input assets. |
| HyperFrames renderer | [Apache-2.0 licence](https://github.com/heygen-com/hyperframes/blob/main/LICENSE). Existing optional adapter, preview only. | Live worker and compute quote unavailable. No model or training permission added. |
| Pattern source | [LuZhong-Li/vibe-knowledge-video-skill](https://github.com/LuZhong-Li/vibe-knowledge-video-skill), [MIT licence](https://github.com/LuZhong-Li/vibe-knowledge-video-skill/blob/main/LICENSE). | Patterns only: beat planning, on-screen explanation and event Foley. No upstream code, text or dependency copied. |

The existing billing system adds the Renderhaus fee. Do not present raw provider rates as a
guaranteed customer total. Existing paid-video cost approval, autonomous premium-video gate,
approval exemptions and spend cap remain in force. Rejection must not resubmit. Speech-producing
endpoints cannot dispatch for the silent workflow, including through an approved resume.

## Routing and validation

Two exact seed rows are added and active: the no-narration control-illusion short selects
Remotion, and the explicitly named HyperFrames silent science explainer selects its gated
preview. Searching the full capability-map CSV found only those two knowledge-explainer rows.
The related third row is the existing whiteboard-with-voiceover case; its source expectation
is retained, with actual workflow ownership corrected to `whiteboard-explainer`.

Inventory is 16 providers, 115 cataloged Gateway tools, 26 packaged skills and 220 fixture
rows: 175 active, 45 skipped. No pending provider row is activated by this skill-only change.
The retained skips are 29 delivery/loudness/QC, 10 subject-aware aspect/reframe, three Cutaway
capture, two unverified LUT/multicam semantics and one HyperFrames footage-overlay case.

Offline tests exercise routing, speech rejection before approval/provider access, native
timeline cue placement, packaged skill loading and Deep Agents 0.7.23 autonomous
Mirelo approval/rejection/resume with fake Gateway transports. They establish plan and policy
behavior, not rendered media quality. Full check results are in
[the decisions file](knowledge-explainer-decisions.tsv).

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
