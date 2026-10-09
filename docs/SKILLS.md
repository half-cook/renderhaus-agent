# Skill routing and media policy

Renderhaus proposes an intent skill before media work. The deterministic router in
`agent/deep_agent/routing.py` reads `routing_policy.json`. The Deep Agents runner supplies
that proposal in the user message and `read_studio_context`. The model reads the selected
`/skills/<name>/SKILL.md`, discovers the actual Gateway schema, and proposes dispatch.
The shared Gateway executor enforces provider/model policy, approvals, and spending limits
on manager calls, subagent calls, and approved resumes.

A route is a proposal, not evidence of live output. Unbuilt tools return `pending`, policy
refusals return `blocked`, retired requests return `retired`, and unknown intents return
`unrouted`. No status invents a Gateway target or authorizes a substitute paid provider.

## Packaged skills

The backend packages 24 skills. Some explain pending capabilities; installing their
instructions does not install a provider adapter. The original execution skills remain
available. `image-gen` and `named-provider` cover the new still-image policy and explicit
requests for providers retained outside automatic selection. The archived `vidu-q4` skill
is removed; its built Fal tools remain available through `named-provider`.

`metadata.include_tools` is a space-separated string of real dispatch wrappers.
`metadata.routing_tools` separately lists canonical defaults, exceptions, or workflow IDs.
`metadata.gateway_tools` contains only built Gateway names, including the optional local
HyperFrames schema. Pending IDs never become dispatch wrappers or fabricated endpoints.
Tests parse the installed Deep Agents middleware metadata and check Gateway references
against `configs/gateway/*.tools.json` and the local schema.

The following table comes from the packaged `SKILL.md` metadata. Each linked skill owns its
exact Gateway names, native arguments, and operational constraints.

| Skill | Dispatch wrappers | Capability routing IDs |
| --- | --- | --- |
| [act-two](../agent/deep_agent/skills/act-two/SKILL.md) | `call_media_tool` | `runway_act_two`<br>`kling_motion_control` |
| [audio](../agent/deep_agent/skills/audio/SKILL.md) | `call_audio_tool` | `eleven_v4_turbo`<br>`voices_ivc_create`<br>`mureka_v95`<br>`mirelo_v2a`<br>`elevenlabs_sfx_v2` |
| [audio-bed](../agent/deep_agent/skills/audio-bed/SKILL.md) | `call_audio_tool`<br>`call_media_tool` | `eleven_v4_turbo`<br>`voices_ivc_create`<br>`mureka_v95`<br>`mirelo_v2a`<br>`elevenlabs_sfx_v2` |
| [continuity-qc](../agent/deep_agent/skills/continuity-qc/SKILL.md) | `call_media_tool` | `local_qc`<br>`gemini_vlm_judge` |
| [conversational-edit](../agent/deep_agent/skills/conversational-edit/SKILL.md) | `call_editor_tool`<br>`call_audio_tool` | `remotion_render`<br>`hyperframes_render` |
| [edit-v2v](../agent/deep_agent/skills/edit-v2v/SKILL.md) | `call_media_tool` | `wan3_edit`<br>`wan3_extend`<br>`seedance25_edit`<br>`seedance25_extend` |
| [final-assembly](../agent/deep_agent/skills/final-assembly/SKILL.md) | `call_editor_tool` | `remotion_render` |
| [hyperframes](../agent/deep_agent/skills/hyperframes/SKILL.md) | `call_editor_tool`<br>`call_audio_tool` | `hyperframes_render` |
| [i2v](../agent/deep_agent/skills/i2v/SKILL.md) | `call_media_tool` | `wan3_i2v`<br>`wan3_r2v`<br>`seedance25_i2v`<br>`seedance25_r2v` |
| [image-gen](../agent/deep_agent/skills/image-gen/SKILL.md) | `call_media_tool` | `gpt_image25_t2i`<br>`gpt_image25_edit`<br>`recraft_v41_vector`<br>`ideogram45_edit` |
| [lipsync](../agent/deep_agent/skills/lipsync/SKILL.md) | `call_media_tool`<br>`call_audio_tool` | `sync3_lipsync`<br>`heygen_avatar_v`<br>`eleven_v4_turbo` |
| [lyrics-video](../agent/deep_agent/skills/lyrics-video/SKILL.md) | `call_audio_tool`<br>`call_editor_tool` | `mureka_lyrics_video`<br>`mureka_v95` |
| [motion-graphics](../agent/deep_agent/skills/motion-graphics/SKILL.md) | `call_editor_tool`<br>`call_media_tool` | `remotion_render`<br>`hyperframes_render` |
| [named-provider](../agent/deep_agent/skills/named-provider/SKILL.md) | `call_media_tool`<br>`call_audio_tool` | `kling_t2v`<br>`kling_i2v`<br>`runway_gen45_t2v`<br>`runway_aleph_edit`<br>`luma_ray3_t2v`<br>`luma_ray3_modify`<br>`vidu_q4_i2v`<br>`vidu_q4_r2v`<br>`seedream_t2i`<br>`fish_audio_tts`<br>`wan_vace_edit` |
| [product-demo-video](../agent/deep_agent/skills/product-demo-video/SKILL.md) | `call_editor_tool` | `cutaway_record`<br>`remotion_render`<br>`hyperframes_render` |
| [product-images](../agent/deep_agent/skills/product-images/SKILL.md) | `call_media_tool` | `gpt_image25_t2i`<br>`gpt_image25_edit`<br>`recraft_v41_vector`<br>`ideogram45_edit` |
| [refinement](../agent/deep_agent/skills/refinement/SKILL.md) | `call_media_tool`<br>`call_audio_tool`<br>`call_editor_tool` | `gpt_image25_edit`<br>`wan3_edit`<br>`seedance25_edit`<br>`remotion_render` |
| [resolve-handoff](../agent/deep_agent/skills/resolve-handoff/SKILL.md) | `call_editor_tool` | `Remotion___export_nle_timeline` |
| [still-then-video](../agent/deep_agent/skills/still-then-video/SKILL.md) | `call_media_tool` | `gpt_image25_t2i`<br>`gpt_image25_edit`<br>`wan3_i2v`<br>`seedance25_i2v` |
| [storyboard-shots](../agent/deep_agent/skills/storyboard-shots/SKILL.md) | `call_media_tool` | `gpt_image25_t2i`<br>`gpt_image25_edit`<br>`wan3_i2v`<br>`wan3_r2v`<br>`seedance25_i2v`<br>`seedance25_r2v` |
| [t2v](../agent/deep_agent/skills/t2v/SKILL.md) | `call_media_tool` | `wan3_t2v`<br>`seedance25_t2v` |
| [upscale](../agent/deep_agent/skills/upscale/SKILL.md) | `call_media_tool` | `topaz_upscale`<br>`topaz_interpolate` |
| [video-short](../agent/deep_agent/skills/video-short/SKILL.md) | `call_media_tool`<br>`call_audio_tool`<br>`call_editor_tool` | `gpt_image25_t2i`<br>`wan3_t2v`<br>`wan3_i2v`<br>`seedance25_t2v`<br>`seedance25_i2v`<br>`remotion_render` |
| [whiteboard-explainer](../agent/deep_agent/skills/whiteboard-explainer/SKILL.md) | `call_editor_tool` | `remotion_render`<br>`hyperframes_render` |

Fish Audio has built API code and a committed schema but is not in the active provider
catalog. Its named request requires a discovered target. `local_qc` is a Python integration
with caller-decoded frames, not a Gateway endpoint. A ready QC route does not prove the host
has configured embeddings or completed a comparison.

## Capability selection

[The capability map](CAPABILITY_MAP.md) is the reference for defaults, exception predicates,
explicit-only tools, pending branches, US hosts, evidence, and A/B candidates.
Selection uses an explicit requested provider/model, then a matching exception, then the
capability default. A pending default uses only its declared interim. Cost and stored quality
tiers do not order models. Prices support disclosure and spending controls.

Wan 3.0 on fal now provides t2v, i2v and reference_video defaults. The synthetic-dialogue exceptions use the upgraded Seedance 2.5 tools through fal US.
Still-image and image-edit defaults use the built OpenAI GPT Image 2.5 Sunburst tools.
Seedream requires an explicit named request. Wan 3.0 on Alibaba Model Studio
remains the edit and extend default. Its preview licence blocks commercial use, so the declared
Seedance 2.5 fal interims serve synthetic inputs. Luma modify and extend remain explicit-only.
ElevenLabs music is the music interim.
These entries expire when their capability default becomes commercially available; they do not create permanent
exceptions for demoted providers. An exact named pending model has no substitute interim.

Dialogue without real-person references selects the Seedance exception. Real-person photo/video
references force Wan and prohibit Seedance or Omni, including the Seedance interim. Real-face Wan 3 dispatch requires an explicit likeness_consent acknowledgement. Vector output selects built Recraft. Text-only edits
on an existing image select built Ideogram; Ideogram generation without an edit image selects
the GPT generation default. Full-body motion selects built Kling Motion Control on fal; facial and
upper-body acting select built Act-Two on Runway. Video-synchronized SFX uses built Mirelo on fal, while
text-only effects use built ElevenLabs. Requests over 30 seconds need supported shot splitting
or a refusal; long presenter/digital-twin videos use the HeyGen exception.

Explicit-only Kling generation, Runway generation/Aleph/images, Luma, Vidu Q4, Seedream,
Fish Audio, ElevenLabs music, and legacy Wan VACE retain their code, schemas, and billing.
An explicit request gets `explicit request; not the default for <capability>` disclosure.
Their presence in Gateway discovery does not authorize automatic selection.
Veo, Hedra, LivePortrait, InfiniteTalk, SeedVR2, RIFE, MMAudio, and ACE-Step are retired.
MMAudio checkpoints and non-commercial InsightFace weights remain blocked for product use.
MiniMax H3 and Hunyuan remain blocked. A retired named request reports retirement before the
customer chooses a mapped replacement.

`routing.capability_table()` exposes built job controls, limits, provider/model policy, and
billing references. Selection checks native controls, duration, availability, licence, and
region for the chosen tool. An unsupported combination refuses rather than searches a price
ladder. The executor requires those controls in the actual submitted arguments. A wrong tool
or model returns the selected route for rediscovery; approval never authorizes silent substitution.

### Stored project settings

Projects retain `provider_policy` in `projects.provider_policy_json` and the authenticated,
workspace-scoped `GET` and `PUT /api/studio/projects/{project_id}/provider-policy` endpoints.
Existing `confidential` and `quality_tier` fields remain compatible with stored requests.
Neither field changes routing, approvals, or provider selection. Mentioning confidentiality
in chat also adds no provider restriction. There is no `confidential-route` skill or FLUX
confidential fallback. Every project uses the same quality-first capability map.

### Disclosure and approval

Before each dispatch, the host emits `MODEL_UPDATE` with provider, model, estimated cost
including the existing platform fee, and the selection basis. The basis is `default`,
`exception: <reason>`, `explicit request`, or `interim default until <provider> lands`.
Unpublished rates remain unknown. Published-price disclosure does not confuse dry-run zero
charges with a live price and does not change a provider setting.

All paid video pauses with an estimate even in autonomous runs while
`premium_video_approval` is enabled. That includes current Seedance, Kling, Runway, Luma,
Vidu and rendering tools, plus future video-producing capabilities when implemented.
`RENDERHAUS_PREMIUM_VIDEO_APPROVAL=false` disables the additional autonomous video pause
for existing tools. Sync and HeyGen always pause, independently of that switch.
Paid non-video retains the existing non-autonomous approvals and authorized autonomous mode.
`APPROVAL_EXEMPT_TOOLS`, free tools, and the autonomous spending cap remain unchanged.
The free conversational-edit preparer still requires separate cut-plan confirmation.
The Codex fallback shares this executor and policy.

Billing comes from `server/billing_rates.py` and the provider's documented contract.
Vidu Q4 uses its dated promotion through 2026-11-30 and list rates afterward.
Dispatch and cap accounting use actual dry-run charges. Unsupported dimensions, missing
measured source durations, unconfirmed larger Seedream sizes, and operator quotes can remain
unknown. Unknown is never free or a guessed amount. A cap blocks unknown-cost paid dispatch.

## Conversational editing after generation

The editor compiles cuts from existing footage and word-level transcripts. It does not select
the generative video-edit capability. Explicit restyling still selects `edit-v2v`; an existing approved
timeline export still selects `resolve-handoff`. An OTIO request after an agent cut selects
`conversational-edit` and the existing exporter. A requested HyperFrames edit returns pending
instead of silently substituting a different overlay provider.

`Remotion___prepare_conversational_edit` is a pure local tool in the existing Remotion target,
available through `DISPATCH_TARGETS["call_editor_tool"]`. It always returns `status="dry_run"`
with canonical `render_arguments`, `timeline`, output-timed `transcript`, `captions`, `cuts`
and `qc_expectations`. It reads no media, contacts no provider, creates no artifact and changes
no source. No new dry-run flag or provider/deployment threshold is needed.

Each source has `id`, immutable `url`, measured `duration_seconds` and verbatim `words`.
Each word has `text`, `start` and `end`, optionally `type`. Spoken-word indices omit spacing
and audio-event records. Each segment names `source_id`, inclusive `first_word` and
`last_word`, optionally short `padding_seconds`. Separate segments remove an internal filler
or silence. The compiler protects kept words and neighboring discarded speech/events,
quantizes cuts to safe frame boundaries and rejects ranges that cannot satisfy those bounds.
The source-to-output map controls captions even when takes are reordered.

The required `plan_summary` is a plain-English proposal. The host requests cut-plan approval
before preparation, including autonomous runs. Approve resumes the exact saved call; reject
never reaches Gateway. The pure tool has zero provider cost and does not reserve paid spend.
`APPROVAL_EXEMPT_TOOLS` stays unchanged. The free-tools list and free billing branch add only
this preparer. Rendering retains its separate paid-video approval and cap behavior, including autonomous runs. A plan approval never authorizes new transcription or video generation.

The manager or audio role uses the existing paid ElevenLabs `speech_to_text_convert`, with
verbatim word timestamps, and supplies its result to the editor. Transcripts are cached by
immutable source version in private conversation files. Operator-configured Scribe quotes
remain required for a known estimate; otherwise the cost is unknown. Existing approval
and autonomous-cap rules still apply. No new price is asserted. Transcripts and plans do not
enter the outcome training hook, and preparation preserves asset handles until render dispatch.

The renderer adds independent dialogue fade fields so a short audio fade does not blacken
the picture. Grading uses bounded `none`, `neutral` or `warm` choices on media only. Timed
text overlays precede the separate final subtitle track. Studio's existing render review
shows subtitle timing, grade and audio fades. Audio fades are evaluated at render FPS;
sample-accurate 30 ms fades require future audio preprocessing and audible verification.
At 12–16 fps the 30 ms envelope can produce no attenuation; at 30 fps it only attenuates
the boundary frames. These fields do not prove pop-free audio.

Preparation preserves source handles, but automatic output lineage through rendering/polling
is unverified. The preexisting executor recovers source IDs by `job_id`, while Remotion polls
use `render_id`. Keep source metadata in the plan and NLE snapshot; automatic poll association
is an open follow-up. Existing Remotion training restrictions remain in force.

NLE export requires actual pinned source metadata and baked effects. A preparation snapshot
alone lacks the checksums/timecodes/provenance needed for export. Local ffmpeg merge/probe
utilities live in `server/projects.py`; Aleph input probing lives in `server/runway_inputs.py`.
Neither exposes an editor QC Gateway tool. Cut, playback and loudness inspection therefore
remain incomplete without host inspection. HyperFrames footage compositing, local-QC dispatch, live model judgment, and real NLE round
trips remain unverified or unavailable. fframes is retired.
See [decisions and verification](conversational-edit-decisions.tsv) and
[third-party notices](THIRD_PARTY_NOTICES.md) for the adaptation and its MIT notice.

## Offline routing verification

The [upscale skill](../agent/deep_agent/skills/upscale/SKILL.md) now dispatches
`Topaz___upscale_video` and `Topaz___interpolate_video`, then polls
`Topaz___get_video_task`. Starlight Precise 2.6 and Apollo are the quality-first defaults;
Chronos applies to plain linear-motion FPS conversion unless a model is explicitly named.
Measured input dimensions, duration and FPS bind the quote to the submitted request.
Topaz submissions always pause with cost, including autonomous runs. Dry-run previews
and queued jobs never satisfy final delivery. See [Topaz](TOPAZ.md) for pricing, licence
sources, unknown-price blockers and the blocked Comet check.

`tests/fixtures/skill_routing.json` contains 129 retained routing rows.
There are 122 active cases and 7 explicit skips. Seven performance-transfer cases now use built tools. Three Mureka lyrics-video cases
now use built tools; music routes use Mureka without an ElevenLabs interim. Five Topaz upscale/interpolation cases
now use built tools. Seedance reference dialogue and two
previously licence-skipped edit cases now use built Seedance tools. The extension increment
case stays skipped because appended-versus-combined length semantics are UNVERIFIED.
The 23 archived rows are dropped,
including confidential-route and `[project.confidential=true]` rows. A false prefix is ordinary
routing input. The read-only workbook and source map are not copied into the repository.

Active cases assert the canonical routing choice, selected skill, actual built/interim Gateway
name, and status. The over-30-second single-shot case asserts a refusal. Pending rows keep
`provider pending: <tool> (feat/<branch>)` reasons. The NLE import row stays skipped with
`provider pending: nle import (feat/nle-import-fcpxml)`.

Fixture overrides preserve the existing transcript preparer and cut-plan approval instead of
routing directly to rendering. Export after an agent cut retains the conversational-edit
workflow. Explicit HyperFrames plus narration retains its existing workflow and enabled dry-run
fixture context. HyperFrames footage overlays remain skipped because standalone preview does
not implement compositing. The ambiguous Ideogram asset-generation row follows the binding GPT
generation rule. Retired-provider replacement examples retain `source_prompt`; separate tests
assert that explicit retired requests dispatch nothing. [Decisions](capability-map-decisions.tsv)
record these differences from the workbook.

The pending specialists cover VLM judging and cutaway capture. A declared interim activates other pending defaults where supported.
Wan 3 generation uses its built tools. Model Studio edit/extend retain their default IDs but
select Seedance while the commercial policy is blocked. Real-person references require Wan
consent for generation and refuse the Seedance edit/extend interim.

`.venv/bin/python -m unittest discover -s tests -p test_skill_routing.py -v` reports each
fixture and skip reason. Supporting tests cover capability defaults/exceptions, named demoted
providers, interim constraints, inert project flags, every paid-video autonomous approval,
provider/model/region policy, spend recovery, provenance, and injected continuity embeddings.
They make no live provider calls and download no weights.

## Optional HyperFrames compositions

The [HyperFrames skill](../agent/deep_agent/skills/hyperframes/SKILL.md) adapts Apache-2.0
guidance for HTML compositions, supplied timings, and kinetic titles. The
[assessment](HYPERFRAMES_ASSESSMENT.md) records upstream decisions, runtime dependencies,
and hosted HeyGen exclusions. Attribution remains in [third-party notices](THIRD_PARTY_NOTICES.md).

`HYPERFRAMES_ENABLED` defaults false. While disabled, explicit requests report a blocker.
`HYPERFRAMES_DRY_RUN` defaults true. The enabled local
`HyperFrames___render_composition` validates input and returns preview metadata through
`call_editor_tool`; it is not a deployed Gateway Lambda target. Live rendering returns
`not_run` until an isolated renderer exists, even if dry-run is disabled.

Remotion remains the motion-graphics default. An explicit HyperFrames or HTML-template
request selects the optional exception without changing unnamed requests. HyperFrames with
ElevenLabs VO uses the existing speech step first. The preview does not execute HTML, fetch
assets, create frames, mix audio, composite footage, or produce an MP4. Schema validation
cannot pass artifact/playback checks. Compute cost remains unknown; paid-video approval
and any active cap still apply. The stored confidential flag creates no HyperFrames restriction.
HyperFrames outputs remain ineligible for continuity training.

## Provider, model, licence, and region policy

`routing_policy.json` packages provider availability, hosted-service or weight licence status,
model allowlists, commercial status, consent notes, region restrictions, and training eligibility.
`explicit_only` governs automatic selection separately from whether a built named request can run.
`service-terms` is an internal API classification, not an open-weight licence or a grant of rights.
Future unverified IDs/API contracts remain pending and dry-run; the capability map records the
verification and US-host evidence rather than guessing availability.

Region gates use `RENDERHAUS_CUSTOMER_REGION`, the operator-provided customer country code.
An empty allowed-region list adds no regional restriction. A nonempty list fails closed without
an allowed region. Provider/model blocks still apply after spending approval.
Model configuration resolves through the existing environment and native argument contract;
explicit model arguments take precedence. Changing an environment default cannot bypass a
model allowlist. MiniMax H3 and Hunyuan remain blocked and never train QC.

Seedance 2.5 defaults to fal US. Global fal and the authorized non-US BytePlus route are
operator configuration choices. BytePlus live platform use requires written authorization;
US end users remain excluded. The 1.5 Pro model stays selectable on BytePlus. [US availability](CAPABILITY_MAP.md) separates verified availability from
unclear evidence. Real-face/voice consent follows each provider's actual terms.

Only successful, non-dry-run Fal assets with a policy-approved legacy Wan model,
`training_eligible=true`, and `weights_license="Apache-2.0"` can enter the existing training hook.
Both provider and model policy must permit that use. Queued/failed assets and missing provenance
fail. Hosted closed-model outputs remain ineligible even with forged flags. This boundary trusts
host provenance; it does not cryptographically authenticate arbitrary caller dictionaries.

## Provider outcomes and training

`record_media_outcome(call_id, outcome)` records an explicit customer acceptance or rejection
of a saved completed generation call. The host checks for a verdict in the current request,
uses saved provider/job provenance, and refuses queued or dry-run reviews. The conservative
English verdict recognizer can refuse unfamiliar wording; the model cannot create acceptance.

`agent/deep_agent/outcomes.py` appends JSONL to `.renderhaus/provider-outcomes/outcomes.jsonl`,
or `RENDERHAUS_OUTCOME_DIR/outcomes.jsonl`. Each row includes event ID, provider/model, job type,
provider job ID when available, workspace/project/execution scope, verdict, stage, and optional
`ab_arm`. The arm field is metadata only; there is no A/B execution framework.
Approval-stage rows distinguish spending authorization/rejection from artifact review.
Offline dry-run authorizations can be logged but never become training rows. A lock serializes
appends, and event IDs deduplicate replays within workspace/project scope. The store contains
no prompts, generated media, credentials or media URLs. It remains local, append-only audit;
operators must provide durable storage for workers when retention across restarts is needed.

An accepted review may be marked training-eligible only for a registered immutable asset
version with approved Wan Apache provenance, success, no dry-run, and eligible source lineage.
Polls carry the original generation's source version IDs through local/remote registration.
Owned lineage restrictions survive session recovery. Hosted-provider outcomes always remain
ineligible, even with forged flags. Logging does not itself emit a dataset or run training.
The continuity training hook below remains Wan-only.

Explicit artifact rejection retains the existing legacy Wan training retry path and requested
features. Unsupported retry capabilities refuse. Approval rejection never starts a retry.
Saved review/retry transitions are idempotent across a resume. Outside that path, legacy Wan
VACE is reachable by name; it is not an automatic low-cost default.

## Continuity QC

`local_qc` remains the continuity-QC default for every project. The pending `gemini_vlm_judge`
can be promoted only after beating 0.85 accuracy on the 420 labelled pairs. This branch adds no
VLM adapter or benchmark result. `CONTINUITY_QC_BACKEND=local` remains the default. The optional `runpod` backend sends a
batch to a separate RunPod Serverless worker with baked SigLIP and DINO weights. It uses
the same calibration and acceptance rule. Configure `RUNPOD_API_KEY` and
`CONTINUITY_QC_RUNPOD_ENDPOINT_ID` on the host only after endpoint setup. A remote failure
returns `status="skipped"`, a reason, and `accepted=False`; it never authorizes generation.
The current runner's `local_qc` alias still needs a host integration, not Gateway dispatch.
See [CONTINUITY_QC_RUNPOD.md](CONTINUITY_QC_RUNPOD.md) for the contract, build commands,
operator requirements, and validation limits.

`agent/deep_agent/continuity_qc.py` compares adjacent caller-decoded shot frames with only
`google/siglip-so400m-patch14-384` and `facebook/dinov2-base` embeddings. It caches one
embedding per model per shot. Each pair returns both cosine similarities, each model's
calibrated probability (`siglip_score`, `dino_score`) and their mean (`score`). The default
`calibrated_mean` rule accepts when the mean probability is at least 0.5 and neither model is
below the 0.2 drift veto. Per-model Platt calibration lives in
`agent/deep_agent/continuity_qc_calibration.json`, fitted by
`scripts/continuity_qc_benchmark.py calibrate` from `docs/continuity_qc_benchmark_scores.json`.
The old `min(siglip, dino) >= 0.8` rule remains as `rule="legacy_min"` for comparison only:
DINO cosines run far lower than SigLIP's, so it rejected 57% of same-shot and 97% of same-scene
true pairs. The calibration was fitted on film frames and must be recalibrated on labelled
Renderhaus generations; it is not an identity or accuracy guarantee. See
[CONTINUITY_QC_BENCHMARK.md](CONTINUITY_QC_BENCHMARK.md#calibrated-scoring).

The `FaceIdentity` Protocol permits a separately licensed host adapter. Its default returns
`not configured`. Visual similarity does not establish face identity. No InsightFace or
other face-recognition package is imported or installed.

Optional torch/transformers imports and model loading happen on the first embedding call.
No heavy required dependency is added to pyproject. Loading uses `local_files_only=True`;
the host must separately provision approved cached weights. Tests inject embedders and mock
loading, with no downloads. Missing packages or caches produce an explicit incomplete check.
`continuity_qc.dinov3_enabled` and `ContinuityConfig.enable_dinov3` default OFF. When turned on,
`facebook/dinov3-vitb16-pretrain-lvd1689m` replaces DINOv2 in the DINO slot (same CLS pooling,
its own calibration entry in the same rule, `ContinuityReport.dino_model` records which model
scored). It loads from the local cache only (transformers>=4.56); `HF_TOKEN` is read from the
environment only. The DINOv3 Licence permits commercial use with conditions, so legal review is
required before enabling it in production. Benchmark and recommendation:
[CONTINUITY_QC_BENCHMARK.md](CONTINUITY_QC_BENCHMARK.md). No DINOv3 model silently replaces
the two supported models.

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

Installed skills distinguish a built dispatch tool from a pending routing alias.
`docs/skills-drafts/` keeps pending adapter references and retired historical guidance.
Recraft and Ideogram edit now use built fal tools; see [Image specialists](IMAGE_SPECIALISTS.md). MMAudio, ACE-Step and Veo references are retired, not future activation plans.
Transcript cuts, silence removal and captions are folded into conversational-edit. NLE re-import
still needs feat/nle-import-fcpxml. File export does not control Resolve, establish a graded
round trip, or provide AAF. Fish discovery remains conditional.

[Remotion's upstream skills](https://github.com/remotion-dev/skills) are optional reference
material. No upstream content or licence grant is assumed. The built renderer uses its typed
timeline contract, not arbitrary JSX. No AGPL code or non-commercial weights are adopted.

## Validation limits

Offline checks establish deterministic routing, actual skill metadata/schema references,
approval/spend behavior, and QC/provenance boundaries. They do not establish live model judgment,
provider credentials, account access, generated playback, quality, or a real NLE import.

Comet browser E2E is blocked because this environment has no controllable Comet session.
This task also prohibits paid/live provider calls. Browser validation remains pending;
ignored `.renderhaus/e2e/` records the blocker through `scripts/browser_e2e_hook.py`.
No dry-run, scripted model or accepted job is a browser E2E pass. The branch's decisions file
records the final offline checks without retaining superseded historical suite totals here.

## Wan 3 generation

The existing t2v, i2v, still-then-video and storyboard-shots skills now name
`Fal___generate_wan3_t2v`, `Fal___generate_wan3_i2v` and `Fal___generate_wan3_r2v`.
All three poll `Fal___get_video_task`. Controls, costs, consent and dry-run limits are in
[the Wan 3 provider reference](FAL_WAN3_PROVIDER.md). There are still 24 packaged skills.
The Wan branch activated four specific workbook rows; after Sync, 31 dependency rows remain skipped.

Plain shot/clip requests with voiceover produce ordered video, TTS and final-assembly steps.
The router excludes image generation and editing from their discovered tools and dispatches.
MP4 export uses final-assembly; OTIO, FCPXML and EDL export uses resolve-handoff.
Deliverable duration describes the shot/clip length, never audio placement such as starting at 1 s.
RT-152 through RT-156 are committed routing gates. RT-155 separately verifies Seedream exclusion
and verifies the built GPT Image default without an expected failure.

Local final assembly uses the same `Remotion___render_timeline` and
`Remotion___get_render_progress` tools with `REMOTION_RENDER_BACKEND=local`. Provider-returned
plain `output_path` fields can supply visuals and audio without S3. Trims, fit, fades, and
audio timing/volume/fades are supported; captions and motion effects require Lambda. See
[local assembly and gateway setup](LOCAL_ASSEMBLY.md). The default backend remains Lambda.

## Wan 3 edit and extend

The default IDs remain `wan3_edit` and `wan3_extend`. Their existing Model Studio adapter
retains its hard preview licence restriction. Automatic customer routing follows the declared
`seedance25_edit` and `seedance25_extend` interims while the Wan model policy has
`live_enabled=false`. A single change to that policy flag restores Wan selection. It cannot
remove the adapter's hard live block or establish commercial rights.

The edit-v2v and refinement skills discover the built Seedance tools, reuse fal polling,
require measured source inputs and prohibit real-person references. Explicit Luma, Aleph,
and VACE requests remain available with disclosure. Paid video pauses in autonomous runs.
After HeyGen wiring there are 12 providers, 95 Gateway tools and 24 skills. Seedance reference dialogue and the
two edit fixture rows are active. The extension increment row remains skipped because its
length semantics are UNVERIFIED; 30 other rows still have dependency blockers.
See [Seedance configuration, prices and licence limits](SEEDANCE_2_5.md) and
[Model Studio's unchanged restriction](ALIBABA_MODELSTUDIO.md).

## OpenAI still images

`OpenAI___generate_image` and `OpenAI___edit_image` implement the still-image and image-edit
defaults, including text-in-image generation. Edits accept a primary image, up to 15 additional
references, and an optional mask. Results contain saved images synchronously, without polling.
Seedream remains explicit-only. Spending approval and visual approval remain separate.
The OpenAI branch activated eight GPT routing rows. With Sync, 98 routing cases are active
and 31 remain skipped, including Recraft and Ideogram specialists.
There are 12 providers, 95 Gateway tools, and 24 packaged skills.

[OpenAI configuration and verified sources](OPENAI_IMAGES.md) describe the default dry-run flag,
unknown pre-call costs, output training restriction, and blocked Comet validation.

## sync-3 lip sync

The lipsync skill now exposes `Sync___lipsync_video` and `Sync___get_video_task`, plus
ElevenLabs TTS for script-only input. It requires existing footage, identified face/voice
subjects, explicit consent and measured timing. Fal is primary; direct Sync requires
operator acknowledgement of written vendor permission. Sync always requires cost approval.
Five routing rows become active: four existing-footage requests select Sync, and the
image-plus-audio generated talking shot selects Seedance 2.5 i2v. HeyGen handles the long-presenter exception.
There are 12 providers, 95 Gateway tools and 24 packaged skills. No new skill directory is
needed because the existing lipsync draft is converted in place. See [SYNC.md](SYNC.md) and
[lipsync decisions](lipsync-sync3-decisions.tsv). Browser E2E remains blocked: Comet is unavailable.


## HeyGen long presenter exception

The existing lipsync skill now exposes four `HeyGen___` tools for Avatar V presenters.
It follows explicit request → duration over 30 seconds with presenter/digital-twin intent →
sync-3 default. Project confidentiality does not change this order. Both matching workbook
rows are active: 98 routing cases and 31 dependency skips remain. Every HeyGen submission
requires recorded face/voice consent and pauses with a price estimate, including autonomous
runs. Preview output is incomplete media. [HeyGen reference](HEYGEN.md) records API contracts,
commercial restrictions, upload training, pricing and the blocked Comet check.

## Mureka music and lyrics video

Mureka V9.5 is the music default on fal, with instrumental beds and songs under
`mureka_v95`. ElevenLabs music remains explicit-only. The existing audio-bed and
lyrics-video skills now use six `Mureka___` tools; no new skill directory was needed.
Lyrics video always pauses with cost, including autonomous runs. Raw audio/TTS
upload preparation remains blocked until the upload and recognition APIs are wired.
There are 14 providers, 110 Gateway tools and 24 packaged skills. See
[Mureka](MUREKA.md) for contracts, official dated prices, licences and blocked Comet E2E.

## Performance transfer

The act-two skill now dispatches Runway Act-Two by default and fal Kling 3 Pro Motion Control
for full-body movement. Both require subject consent and cost approval even in autonomous runs.
Long Act-Two sources use sequential 3-30s shot/silence segments and the existing Remotion assembly.
See [performance contracts, prices and limits](PERFORMANCE_TRANSFER.md). Browser E2E remains blocked.

## Picture-synchronized SFX

The audio-bed skill now exposes `Fal___mirelo_v2a` and reuses `Fal___get_video_task` through the manager/media role. Video input selects Mirelo; text-only effects select ElevenLabs SFX. Explicit requests win. Mirelo returns video with audio and pauses with cost even in autonomous runs under the paid-video policy. Samples 2–4 remain dry-run-only because their billing is unverified. Three SFX rows are activated, leaving 122 active routing cases and 7 skips. No skill directory was added. See [Mirelo](MIRELO.md) for sources, contracts and pending playback/A/B validation.

## Image specialist activation

`Fal___ideogram_edit` serves the text-only existing-image edit exception and
`Fal___recraft_text_to_vector` serves editable SVG/vector output. Both reuse
`Fal___get_video_task`, default to dry-run, quote verified fal image prices and
exclude training. SVG content is validated and sanitized before persistence.
The image-gen, product-images and refinement skills expose their real tool names.
Six fixture rows activate: 122 active, seven skipped of 129. The inventory is
14 providers, 110 tools and 24 skills. Comet validation and Ideogram quality A/B
remain pending. See [Image specialists](IMAGE_SPECIALISTS.md) for contracts,
official sources read 2026-10-09, licence decisions and configuration.
