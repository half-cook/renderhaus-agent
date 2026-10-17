# Short drama series

`short-drama-series` develops episodic fiction through outline approval, series and
character bibles, episode scripts, locked storyboards, staged production, edit and review.
It adds two free Deep Agents tools and reuses existing paid Gateway tools. It adds no
provider, model, credential, price table, generation tier or deployment action.

## Runtime contract

The planning-only route selects this skill for microdramas, short dramas, Chinese 短剧/漫剧
and episode-specific fictional scripts/storyboards. It returns no paid tool. Single ads,
podcasts and chat-thread compositions retain their existing routes. RT-188 was absent
from both the starting fixture and supplied capability routing CSV. It is added from
the task spec with eleven routing boundary cases. Inventory is 21 providers, 140 Gateway
tools, 42 skills and 342 fixture rows, of which 336 are active and six remain skipped.

`review_drama_outline(outline)` uses native approve/reject interrupts with a zero-production
cost quote. Only the approved tool execution stores the canonical outline and SHA-256
in the host-owned conversation snapshot. A user-editable file or `approved: true` cannot
authorize production. A changed outline clears the previous executable batch and locks.

`validate_drama_episode(episode, jobs)` validates a strict typed document and exact
existing-tool arguments. It stores the valid episode and next batch in the same host
snapshot. Validation alone authorizes no spending. A failed replacement clears the
previous batch. The role dispatcher refuses a paid call whose arguments differ from
the validated job. Every paid series call receives a native cost approval, including
stills, voice and music in autonomous mode. Global `APPROVAL_EXEMPT_TOOLS` and the
autonomous spending cap are unchanged. Each submitted job ID is retained to prevent
unintentional repeat submission. A requested retry needs a new job ID and approval.

The installed `deepagents==0.7.23` signatures are authoritative. The implementation reuses
its existing `interrupt_on` predicates, checkpointer, thread IDs and `Command(resume=...)`
protocol. Outline rejection is handled locally and never sent to Gateway. Subagents
receive the free checker/review tools and existing skills explicitly. Provider access
continues through the role dispatchers. No separate executor or orchestration graph exists.

State and files persist within the current workspace/project/conversation. Another
conversation must receive the files explicitly. An explicit request to stop or leave
the series disables its gate and retains its bibles and job history for later reuse.

## Episode checks

The [skill](../agent/deep_agent/skills/short-drama-series/SKILL.md) links the
[working-file contract](../agent/deep_agent/skills/short-drama-series/references/working-files.md)
and [example episode](../agent/deep_agent/skills/short-drama-series/templates/episode.json).
All working records are Markdown/JSON with stable episode, subject, line, lock and cut IDs.

The pure checker enforces 2-5 second cuts, segments no longer than 15 seconds, unique IDs,
known speakers/subjects/lines, exactly one assignment per script beat, applicable locks
cited and repeated verbatim in both prompts, and verbatim captions when supplied.
Cross-episode checks prevent changed or renamed locks for an established depicted
subject. A changed location/prop roster also needs a revised outline. Dialogue time is
estimated deterministically at four CJK characters/second and twelve other non-space
characters/second, rounded up to a tenth, with a 0.4-second minimum. Action time is explicit.
This is a planning estimate, never a measured voice duration or a semantic quality score.

Image and video jobs bind prompts to the storyboard; speech jobs bind text to script
lines. Video duration must equal the segment and fit the selected API's own limits.
Lip-sync uses measured source/audio durations and the corresponding segment. Music and
final assembly use their existing argument contracts. Paid video tools without a supported
series job contract refuse rather than bypass segment checks. All other workflows keep
those tools. Only independent jobs in the current batch can run together. Dependent
reference/shot/assembly batches use real completed asset handles.

## Provider evidence

Official pages were re-read on **2026-10-15**. Existing billing tables retain their original
2026-10-08/09 citations and dates; this feature introduces no rate or API identifier.

| Existing path | Official evidence re-read | Result |
| --- | --- | --- |
| Wan 3.0 reference | [schema](https://fal.ai/models/alibaba/wan-3.0/reference-to-video/api), [pricing](https://fal.ai/models/alibaba/wan-3.0/reference-to-video) | Model path and reference inputs confirmed. Published 480p/720p/1080p output rates are $0.05/$0.10/$0.20 per second. Input video seconds are also billed. |
| Seedance 2.5 US reference/edit/extend | [schema](https://fal.ai/models/bytedance/seedance-2.5/us/reference-to-video/api), [pricing](https://fal.ai/models/bytedance/seedance-2.5/us/reference-to-video) | Existing US path and reference/editing/extension task enum confirmed. Published token rates match existing $25.68/M for 480p/720p and $28.08/M for 1080p, with the 0.6 video-input factor. Extension source inclusion remains UNVERIFIED. |
| Images | [model/pricing](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst), [generate schema](https://developers.openai.com/api/reference/resources/images/methods/generate), [edit schema](https://developers.openai.com/api/reference/resources/images/methods/edit) | Existing image model and schemas confirmed. Rates remain $5/M text input, $8/M image input and $30/M image output tokens; the per-image approval quote is an estimate, not a fixed provider price. |
| Speech | [models](https://elevenlabs.io/docs/overview/models), [convert schema](https://elevenlabs.io/docs/api-reference/text-to-speech/convert), [pricing](https://elevenlabs.io/pricing/api) | Existing `eleven_v4_turbo` ID and $0.04/1,000 characters confirmed. |
| Music | [song schema](https://fal.ai/models/mureka/api/generate/song/api), [song pricing](https://fal.ai/models/mureka/api/generate/song), [instrumental schema](https://fal.ai/models/mureka/api/generate/instrumental/api), [instrumental pricing](https://fal.ai/models/mureka/api/generate/instrumental) | Existing `mureka-9.5` and hosted paths confirmed. fal lists $0.225 for lyrics-to-song/instrumental and $0.75 for prompt-to-song, matching existing billing. Direct API pricing was not readable and is not substituted. |
| Rendering | [Remotion Lambda](https://www.remotion.dev/docs/lambda) | Existing renderer and backend contract reused. Compute estimates depend on configured backend; missing estimates remain unknown. |

Existing commercial API policies are recorded in each provider's `model_policies` and
provider docs, including [fal service terms](https://fal.ai/legal/terms-of-service).
This workflow grants no new training eligibility. It imports no model weights or code
under a non-commercial or AGPL licence. Demoted providers remain available by explicit
request and retain their existing disclosures. No source-of-truth research file is copied.

## Verification and limits

Offline tests exercise strict timing and locks, native outline approval/rejection,
autonomous image/voice/music cost pauses, session restoration, exact-job binding,
stale plans and scoped per-shot selection. The checker tests include valid alternatives,
malformed data and realistic continuity failures. These tests do not claim creative quality,
live provider execution, factual visual continuity, subtitle readability or browser E2E.
No paid model eval or Harbor run is authorized by this task.
An independent offline instruction check produced a valid two-episode outline and an
eight-second draft with two four-second cuts. It found two documentation ambiguities:
where unsupported outline metadata belongs, and how to label an episode drafted before
approval. The skill now puts extra story notes in `adaptation_notes`/the readable bible
and uses an explicitly unapproved draft hash. This check authorizes no production.

Comet browser validation is pending because this session has no browser-control tool.
Access was requested. The ignored `.renderhaus/e2e/short-drama-series.json` receipt records
the blocker. Required browser scenario is outline rejection/approval followed by an exact
job cost approval. No live/paid API call or generated-media playback is authorized here.
Delivery still requires a played artifact and saved, passing final QC with matching
checksums. Report delivered dimensions, source resolution and every warning honestly.

## Provenance

Workflow stages and continuity patterns are adapted in original wording from
[zenstory-ai/drama-skills](https://github.com/zenstory-ai/drama-skills/tree/f53fb206507cb0cfb07fd29b692156dd4fb8fe7d)
under MIT and
[eternityspring/shuohao-skills](https://github.com/eternityspring/shuohao-skills/tree/d28a9c539b40523d081794b25ff9113016bd98e0)
under Apache-2.0. The revisions and licences were read on 2026-10-15. The
[NOTICE](../agent/deep_agent/skills/short-drama-series/NOTICE) and full licence texts ship
with the skill. No upstream executable code, artwork, audio, fonts or weights are vendored.
