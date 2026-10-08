# Skill routing and media policy

Renderhaus proposes an intent skill before media work. The deterministic router in
`agent/deep_agent/routing.py` reads `routing_policy.json`. The Deep Agents runner includes
the proposal in the user message and `read_studio_context`. The model reads the selected
`/skills/<name>/SKILL.md`, discovers the actual Gateway schema, and proposes dispatch.
A route is a proposal, not proof that a live model follows it. Pending providers return `pending`, explicitly denied provider requests return `blocked`,
and unknown intents return `unrouted`. None invents a tool or a paid fallback.
The shared Gateway executor enforces provider/model gates, approvals, and spending limits
regardless of the model's proposal, including subagent dispatch and approved resumes.

## Packaged skills

Eight intent skills were added. The original six names remain compatible. There are 14 live
skills in total. `metadata.include_tools` is a space-separated string of dispatch wrappers.
`metadata.gateway_tools` records exact Gateway names separately. Abstract seed aliases never
replace wrapper names in `include_tools`. Tests parse the actual middleware metadata and
check every declared or body-referenced Gateway name against `configs/gateway/*.tools.json`.

| Skill | Dispatch tools | Gateway tools |
| --- | --- | --- |
| [audio](../agent/deep_agent/skills/audio/SKILL.md) | `call_audio_tool` | `ElevenLabs___music_compose`<br>`ElevenLabs___text_to_sound_effects_convert`<br>`ElevenLabs___text_to_speech_convert`<br>`FishAudio___generate_speech` |
| [audio-bed](../agent/deep_agent/skills/audio-bed/SKILL.md) | `call_audio_tool` | `ElevenLabs___text_to_speech_convert`<br>`ElevenLabs___music_compose`<br>`ElevenLabs___text_to_sound_effects_convert`<br>`FishAudio___generate_speech` |
| [continuity-qc](../agent/deep_agent/skills/continuity-qc/SKILL.md) | `call_media_tool` | `Fal___text_to_video`<br>`Fal___get_video_task` |
| [edit-v2v](../agent/deep_agent/skills/edit-v2v/SKILL.md) | `call_media_tool` | `Fal___video_to_video`<br>`Fal___get_video_task`<br>`Fal___list_fal_models`<br>`Runway___video_to_video`<br>`Runway___get_runway_task`<br>`Runway___list_runway_models` |
| [final-assembly](../agent/deep_agent/skills/final-assembly/SKILL.md) | `call_editor_tool` | `Remotion___export_nle_timeline`<br>`Remotion___get_render_progress`<br>`Remotion___render_timeline` |
| [i2v](../agent/deep_agent/skills/i2v/SKILL.md) | `call_media_tool` | `Fal___image_to_video`<br>`Fal___reference_to_video`<br>`Fal___get_video_task`<br>`Kling___image_to_video`<br>`Kling___get_video_task`<br>`Seedance___image_to_video`<br>`Seedance___get_video_task`<br>`Runway___image_to_video`<br>`Runway___get_runway_task`<br>`Seedream___text_to_image`<br>`Seedream___image_to_image` |
| [motion-graphics](../agent/deep_agent/skills/motion-graphics/SKILL.md) | `call_editor_tool`<br>`call_media_tool` | `Remotion___render_timeline`<br>`Remotion___get_render_progress`<br>`Remotion___export_nle_timeline`<br>`Seedream___text_to_image`<br>`Seedream___image_to_image`<br>`Runway___text_to_image`<br>`Runway___image_to_image`<br>`Runway___get_runway_task` |
| [product-images](../agent/deep_agent/skills/product-images/SKILL.md) | `call_media_tool` | `Runway___get_runway_task`<br>`Runway___image_to_image`<br>`Runway___text_to_image`<br>`Seedream___image_to_image`<br>`Seedream___text_to_image` |
| [refinement](../agent/deep_agent/skills/refinement/SKILL.md) | `call_media_tool`<br>`call_audio_tool`<br>`call_editor_tool` | `Fal___video_to_video`<br>`Runway___video_to_video`<br>`Seedream___image_to_image` |
| [resolve-handoff](../agent/deep_agent/skills/resolve-handoff/SKILL.md) | `call_editor_tool` | `Remotion___export_nle_timeline` |
| [still-then-video](../agent/deep_agent/skills/still-then-video/SKILL.md) | `call_media_tool` | `Seedream___text_to_image`<br>`Seedream___image_to_image`<br>`Runway___text_to_image`<br>`Runway___image_to_image`<br>`Runway___get_runway_task`<br>`Fal___image_to_video`<br>`Fal___get_video_task`<br>`Kling___image_to_video`<br>`Kling___get_video_task`<br>`Seedance___image_to_video`<br>`Seedance___get_video_task` |
| [storyboard-shots](../agent/deep_agent/skills/storyboard-shots/SKILL.md) | `call_media_tool` | `Fal___get_video_task`<br>`Fal___image_to_video`<br>`Seedance___get_video_task`<br>`Seedance___image_to_video`<br>`Seedream___image_to_image` |
| [t2v](../agent/deep_agent/skills/t2v/SKILL.md) | `call_media_tool` | `Fal___text_to_video`<br>`Fal___get_video_task`<br>`Fal___list_fal_models`<br>`Kling___text_to_video`<br>`Kling___omni_video`<br>`Kling___get_video_task`<br>`Kling___list_kling_models`<br>`Runway___text_to_video`<br>`Runway___get_runway_task`<br>`Runway___list_runway_models`<br>`Seedance___text_to_video`<br>`Seedance___get_video_task`<br>`Seedance___list_seedance_models` |
| [video-short](../agent/deep_agent/skills/video-short/SKILL.md) | `call_media_tool`<br>`call_audio_tool`<br>`call_editor_tool` | `Fal___get_video_task`<br>`Fal___image_to_video`<br>`Fal___text_to_video`<br>`Seedance___get_video_task`<br>`Seedance___image_to_video`<br>`Seedance___text_to_video`<br>`Seedream___text_to_image` |

Fish Audio has built API code and a committed schema, but it is not in the active provider
catalog. `FishAudio___generate_speech` requires a discovered target. An absent target is an
incomplete capability, not permission to invent one. Local QC is a Python integration with
caller-supplied decoded frames. It has no Gateway endpoint; the skill reports incomplete QC
when the host has not configured embeddings. Synthetic Wan preview generation is disclosed
separately by the QC skill.

## Seed aliases

Every canonical alias from the read-only seed README has a mapping or explicit pending reason.
The resolver also contains `runway_i2v` and `runway_gen4_t2i` for built Runway image workflows.
NLE aliases all package the same timeline snapshot. The exporter returns OTIO, FCPXML, EDLs,
a manifest, and media together; an alias does not imply a separate Gateway tool.

| Abstract name | Gateway tool or pending provider |
| --- | --- |
| `kling_t2v` | `Kling___text_to_video` |
| `kling_i2v` | `Kling___image_to_video` |
| `runway_gen45_t2v` | `Runway___text_to_video` |
| `runway_aleph_edit` | `Runway___video_to_video` |
| `wan_t2v` | `Fal___text_to_video` |
| `wan_i2v` | `Fal___image_to_video` |
| `wan_vace_edit` | `Fal___video_to_video` |
| `seedance_t2v` | `Seedance___text_to_video` |
| `seedance_i2v` | `Seedance___image_to_video` |
| `seedream_t2i` | `Seedream___text_to_image` |
| `elevenlabs_tts` | `ElevenLabs___text_to_speech_convert` |
| `fish_audio_tts` | `FishAudio___generate_speech` |
| `remotion_render` | `Remotion___render_timeline` |
| `otio_export` | `Remotion___export_nle_timeline` |
| `fcpxml_export` | `Remotion___export_nle_timeline` |
| `edl_export` | `Remotion___export_nle_timeline` |
| `media_package` | `Remotion___export_nle_timeline` |
| `local_qc` | Local `continuity_qc.ContinuityQC`, no Gateway dispatch |
| `runway_act_two` | provider pending: Runway Act-Two |
| `hedra_character3` | provider pending: Hedra |
| `liveportrait_lipsync` | provider pending: LivePortrait |
| `infinitetalk_lipsync` | provider pending: InfiniteTalk |
| `seedvr2_upscale` | provider pending: SeedVR2 |
| `rife_interpolate` | provider pending: RIFE |
| `topaz_upscale` | provider pending: Topaz |
| `mmaudio_sfx` | provider pending: MMAudio |
| `ace_step_music` | provider pending: ACE-Step |
| `veo_t2v` | provider pending: Veo |
| `veo_i2v` | provider pending: Veo |
| `veo_extend` | provider pending: Veo |
| `ideogram_t2i` | provider pending: Ideogram |
| `recraft_t2i` | provider pending: Recraft |
| `runway_gen4_t2i` | `Runway___text_to_image` |
| `runway_i2v` | `Runway___image_to_video` |

## Offline routing verification

`tests/fixtures/skill_routing.json` retains all 55 rows exported from the workbook.
There are **21 active** cases and **34 skipped** cases. Each skip is a generated unittest
with its concrete pending-provider or integration reason, not a dropped fixture row.
An active case asserts the selected skill and proposed exact Gateway name through the same
router used by the runner. Five Resolve suites need a local bridge or transcription/import
integration even though the final packaging tool exists. TTS-only lipsync rows are skipped
because speech alone does not animate a character.

Run `.venv/bin/python -m unittest discover -s tests -p test_skill_routing.py -v` to see each
case and skip reason. Other offline tests exercise the compiled graph with `ScriptedModel`
and fake Gateway, premium approve/reject resumes, model/environment/region gates, unknown
quotes, concurrent and interrupted spending, and injected continuity embeddings. These
checks make no live or paid provider calls and download no weights.

## Provider, model, licence, and region policy

`agent/deep_agent/routing_policy.json` is packaged with the backend. Each provider has an
`enabled` switch, a licence classification, regional restrictions, and training eligibility.
Model allowlists and `model_policies` add model-specific licence and region gates. Region
checks use `RENDERHAUS_CUSTOMER_REGION`, an operator-provided customer country code, not the
AWS deployment region. An empty allowed-region list adds no regional restriction. A
nonempty list fails closed when the customer region is missing. Provider and model blocks
apply even when a dispatch has already been approved.

`service-terms` is an internal hosted-service classification, not an open-weight licence
or a claim about legal rights. Approved built hosted APIs can generate but cannot train QC.
Fal supports only the two declared Wan VACE models with Apache-2.0 policy. Seedance and
Seedream initially allow their current configured default models only. Add a reviewed model
to the policy before changing those defaults. Kling, Runway, and Fish allow their declared
built models. Policy resolves `KLING_MODEL`, `SEEDANCE_MODEL`, `SEEDREAM_MODEL`, and
`FISH_AUDIO_MODEL` before enforcing gates or estimating spend; explicit arguments take
precedence. Omni uses its fixed model rather than the Kling default environment setting.

MiniMax H3 and Hunyuan are disabled by default and declare a US region block for any future
activation. Neither is training-eligible in any region. Veo remains disabled/pending. Luma (`ray-3.2`) is enabled under service terms, routed through `t2v`, `i2v` and `edit-v2v`, premium (cost estimate + approval, also in autonomous runs) and never training-eligible.
Only successful, non-dry-run Fal assets with an allowed Wan model, `training_eligible=true`,
and `weights_license="Apache-2.0"` may enter the training hook. Both provider and model policy
must permit Apache training. Queued/failed results and missing provenance fail. Kling,
Runway, Luma, Seedance, Seedream, and Veo outputs cannot enter training, even with forged
eligibility flags. This validation trusts host-supplied provider provenance; it does not
cryptographically authenticate arbitrary dictionaries submitted by a caller.

## Wan-first video and premium approval

Wan/Fal is the configured default text, image, and edit video tier. Explicit supported
provider requests and configured premium intent rules can propose another tier. Every
premium video generation on Kling or Runway requires approval, including autonomous runs.
Veo is included in the step-up target policy for future support but currently cannot dispatch.
The conservative rule pauses even if no Wan job has yet run, rather than waiting for a paid
Wan attempt to fail. Premium still images do not trigger this video-only tightening.

The switch `premium_video_approval` defaults ON. Set
`RENDERHAUS_PREMIUM_VIDEO_APPROVAL=false` to disable that additional autonomous pause.
Non-autonomous approval behavior remains as before, apart from a cost estimate in the
approval payload and visible label. ElevenLabs administrative approvals remain enforced.
Polling, listing, search, and free packaging do not trigger the premium rule. Existing
non-autonomous approval rules still apply to those calls; Remotion NLE packaging retains
its unconditional exemption. The Deep runner's native interrupt predicate and shared
`tool_needs_approval` use the same policy.

`estimate_cost` uses only `server.billing_rates.cost_for` for amounts and exposes USD totals
including the existing platform fee. Known dry-run requests use billing's zero charge.
Unconfirmed combinations are detected before billing's dry-run shortcuts and shown as
**unknown**, never a guessed amount. Examples include Kling Turbo audio semantics, Wan 2.2
freeform/pose and unpriced resolutions, fractional Aleph billing, Seedream Lite larger size
tiers, missing/invalid ElevenLabs operator quotes, and Remotion's compute placeholder.
No new rates are introduced. Unknown estimates remain visible in approval descriptions and
labels. The runner never manufactures approval or changes provider DRY_RUN settings.

## Continuity QC

`agent/deep_agent/continuity_qc.py` compares adjacent caller-decoded shot frames with only
`google/siglip-so400m-patch14-384` and `facebook/dinov2-base` embeddings. It caches one
embedding per model per shot. Each pair returns both cosine similarities and an average
summary score. Both similarities must meet `ContinuityConfig.similarity_threshold`, default
0.8. The threshold is a configurable engineering default, not an empirically validated
identity or continuity accuracy guarantee. The report also returns per-pair acceptance.

The `FaceIdentity` Protocol permits a separately licensed host adapter. Its default returns
`not configured`. Visual similarity does not establish face identity. No InsightFace or
other face-recognition package is imported or installed.

Optional torch/transformers imports and model loading happen on the first embedding call.
No heavy required dependency is added to pyproject. Loading uses `local_files_only=True`;
the host must separately provision approved cached weights. Tests inject embedders and mock
loading, with no downloads. Missing packages or caches produce an explicit incomplete check.
`continuity_qc.dinov3_enabled` and `ContinuityConfig.enable_dinov3` default OFF. Enabling DINOv3
currently raises a gated-access/licence-review error; a separately reviewed adapter is still
required. No DINOv3 model silently replaces the two supported models.

`training_loop_hook(assets, consume)` validates the entire batch through policy before
calling a training consumer. One ineligible asset rejects the batch with no consumer side
effects. The hook supplies a boundary for host training code, not a downloaded model or an
automatically running training service.

## Optional autonomous spending cap

`RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS` is OFF when unset or empty. Set a nonnegative integer
number of cents to cap estimated spend for one autonomous execution. Zero blocks any paid
call with a positive estimate. Non-autonomous runs retain their approval behavior and ignore
the cap. A cap requires a stable `job_id`; Studio executions already supply one.

The executor resolves a confirmed estimate after schema validation and approval. If the next
paid call would exceed the cap, or its cost is unknown, paid dispatch stops for that run with
a clear reason. Free polls/listing/packaging remain available to recover existing jobs.
An approval does not override the cap. Unknown-priced calls remain blocked under a cap even
in dry run. When unset, the cap does not calculate spend or add dispatch restrictions.

Reservations happen synchronously before awaiting Gateway submission and are keyed by call
ID. The ledger is saved to session state and `session_sink` before submission, then merged
into native checkpoints. A matching resumed execution restores it, including a reservation
saved during an interrupted submission. A new execution scope resets it. Rejections and
schema errors consume no spend. Ambiguous transport failures retain reservations because
the provider might have accepted the job. Retries cannot double-dispatch the same reserved
call. This is a conservative estimate ledger, not invoice reconciliation or an exactly-once
distributed billing guarantee. Durability still depends on the host persisting `session_sink`.

## Pending drafts and references

Live skills never disclose unbuilt provider tools. Drafts under `docs/skills-drafts/` carry
`Status: provider pending` and the provider or integration needed to unlock them.

- `veo-t2v` requires Google Veo; `act-two` requires the separate Runway character-performance adapter.
- `lipsync` requires LivePortrait, InfiniteTalk, or Hedra. ElevenLabs speech alone cannot unlock it.
- `upscale` requires SeedVR2, Topaz, or RIFE.
- `mmaudio`, `ace-step`, `ideogram`, and `recraft` require their own adapters and reviewed contracts/licences.
- `resolve-rough-cut`, `resolve-silence-cut`, `resolve-auto-subs`, `resolve-roundtrip`, and
  `resolve-new-track-safety` require local Resolve/transcription/import integrations.

Built Kling, Runway, Fal Wan VACE, and Resolve export draft notes are retained as historical
references and now point to the live skills. File-based export does not control Resolve,
perform a graded round trip, or provide AAF. Fish Audio discovery remains conditional.

[Remotion's upstream skills](https://github.com/remotion-dev/skills) are an optional reference.
No upstream content was vendored, and no upstream licence grant is assumed. Motion graphics
use this branch's `Remotion___render_timeline` snapshot contract rather than arbitrary JSX.

## Validation limits

The starting suite had 330 passing tests. Final checks ran 433 tests, with 398 passed and
35 explicit skips. Ruff passed for `agent lambdas scripts server providers`, and
`scripts/ci_check.py` passed with every provider DRY_RUN flag enabled and secrets loading
disabled. Current offline checks cover routing proposals,
actual skill parsing/schema names, both approval paths, spending, and QC boundaries. They
do not prove live model judgment, legal review, provider/account access, model-weight quality,
generated playback, or an editor import. Comet cannot be controlled here, and the task forbids
live/paid provider calls and downloads. Studio browser E2E is blocked and remains pending,
recorded under ignored `.renderhaus/e2e/` with `scripts/browser_e2e_hook.py`.

## Luma routing (added on staging)

Luma landed on staging after this branch was cut, so it was wired in during the staging merge:

| Seed alias | Gateway tool | Skill |
| --- | --- | --- |
| `luma_ray3_t2v` | `Luma___text_to_video` | `t2v` |
| `luma_ray3_extend` | `Luma___extend_video` | `t2v` |
| `luma_ray3_i2v` | `Luma___image_to_video` | `i2v` |
| `luma_ray3_modify` | `Luma___modify_video` | `edit-v2v` |

- Policy: `providers.luma` is enabled, licence `service-terms`, model `ray-3.2` only, no region gate, `training_eligible: false`.
- `Luma` is a premium target (`text_to_video`, `image_to_video`, `extend_video`, `modify_video`), so its paid calls pause for approval with the `cost_for` estimate even in autonomous runs; `list_luma_models` and `get_video_task` are free.
- Estimates come from the official Ray 3.2 table in `server/billing_rates.py`; settings without a published price (e.g. 360p extend, non-5/10 s modify sources) show as unknown.
- The routing fixture's Luma case is active: 21 active and 34 skipped routing cases.
