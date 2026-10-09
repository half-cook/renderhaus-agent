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

The backend packages 17 live skills, including vidu-q4, conversational-edit and the optional
hyperframes skill. The original six names remain compatible.
`metadata.include_tools` is a space-separated string of dispatch wrappers.
`metadata.gateway_tools` records exact Gateway names separately. Abstract seed aliases never
replace wrapper names in `include_tools`. Tests parse the actual middleware metadata and
check every declared or body-referenced tool name against `configs/gateway/*.tools.json`
and the optional local HyperFrames schema.

| Skill | Dispatch tools | Gateway tools |
| --- | --- | --- |
| [audio](../agent/deep_agent/skills/audio/SKILL.md) | `call_audio_tool` | `ElevenLabs___music_compose`<br>`ElevenLabs___text_to_sound_effects_convert`<br>`ElevenLabs___text_to_speech_convert`<br>`FishAudio___generate_speech` |
| [audio-bed](../agent/deep_agent/skills/audio-bed/SKILL.md) | `call_audio_tool` | `ElevenLabs___text_to_speech_convert`<br>`ElevenLabs___music_compose`<br>`ElevenLabs___text_to_sound_effects_convert`<br>`FishAudio___generate_speech` |
| [continuity-qc](../agent/deep_agent/skills/continuity-qc/SKILL.md) | `call_media_tool` | `Fal___text_to_video`<br>`Fal___get_video_task` |
| [conversational-edit](../agent/deep_agent/skills/conversational-edit/SKILL.md) | `call_editor_tool`<br>`call_audio_tool` | `Remotion___prepare_conversational_edit`<br>`Remotion___render_timeline`<br>`Remotion___get_render_progress`<br>`Remotion___export_nle_timeline`<br>`ElevenLabs___speech_to_text_convert`<br>`ElevenLabs___speech_to_text_transcripts_get` |
| [edit-v2v](../agent/deep_agent/skills/edit-v2v/SKILL.md) | `call_media_tool` | `Fal___video_to_video`<br>`Fal___get_video_task`<br>`Fal___list_fal_models`<br>`Runway___video_to_video`<br>`Runway___get_runway_task`<br>`Runway___list_runway_models`<br>`Luma___modify_video`<br>`Luma___get_video_task`<br>`Luma___list_luma_models` |
| [final-assembly](../agent/deep_agent/skills/final-assembly/SKILL.md) | `call_editor_tool` | `Remotion___export_nle_timeline`<br>`Remotion___get_render_progress`<br>`Remotion___render_timeline` |
| [hyperframes](../agent/deep_agent/skills/hyperframes/SKILL.md) | `call_editor_tool`<br>`call_audio_tool` | Local `HyperFrames___render_composition`<br>`ElevenLabs___text_to_speech_convert` |
| [i2v](../agent/deep_agent/skills/i2v/SKILL.md) | `call_media_tool` | `Fal___image_to_video`<br>`Fal___reference_to_video`<br>`Fal___get_video_task`<br>`Kling___image_to_video`<br>`Kling___get_video_task`<br>`Seedance___image_to_video`<br>`Seedance___get_video_task`<br>`Runway___image_to_video`<br>`Runway___get_runway_task`<br>`Seedream___text_to_image`<br>`Seedream___image_to_image`<br>`Luma___image_to_video`<br>`Luma___get_video_task`<br>`Luma___list_luma_models`<br>`Fal___vidu_q4_i2v`<br>`Fal___vidu_q4_r2v` |
| [motion-graphics](../agent/deep_agent/skills/motion-graphics/SKILL.md) | `call_editor_tool`<br>`call_media_tool` | `Remotion___render_timeline`<br>`Remotion___get_render_progress`<br>`Remotion___export_nle_timeline`<br>`Seedream___text_to_image`<br>`Seedream___image_to_image`<br>`Runway___text_to_image`<br>`Runway___image_to_image`<br>`Runway___get_runway_task` |
| [product-images](../agent/deep_agent/skills/product-images/SKILL.md) | `call_media_tool` | `Runway___get_runway_task`<br>`Runway___image_to_image`<br>`Runway___text_to_image`<br>`Seedream___image_to_image`<br>`Seedream___text_to_image` |
| [refinement](../agent/deep_agent/skills/refinement/SKILL.md) | `call_media_tool`<br>`call_audio_tool`<br>`call_editor_tool` | `Fal___video_to_video`<br>`Luma___modify_video`<br>`Runway___video_to_video`<br>`Seedream___image_to_image` |
| [resolve-handoff](../agent/deep_agent/skills/resolve-handoff/SKILL.md) | `call_editor_tool` | `Remotion___export_nle_timeline` |
| [still-then-video](../agent/deep_agent/skills/still-then-video/SKILL.md) | `call_media_tool` | `Seedream___text_to_image`<br>`Seedream___image_to_image`<br>`Runway___text_to_image`<br>`Runway___image_to_image`<br>`Runway___get_runway_task`<br>`Fal___image_to_video`<br>`Fal___get_video_task`<br>`Kling___image_to_video`<br>`Kling___get_video_task`<br>`Seedance___image_to_video`<br>`Seedance___get_video_task`<br>`Fal___vidu_q4_i2v`<br>`Fal___vidu_q4_r2v` |
| [storyboard-shots](../agent/deep_agent/skills/storyboard-shots/SKILL.md) | `call_media_tool` | `Fal___get_video_task`<br>`Fal___image_to_video`<br>`Seedance___get_video_task`<br>`Seedance___image_to_video`<br>`Seedream___image_to_image`<br>`Fal___vidu_q4_i2v`<br>`Fal___vidu_q4_r2v` |
| [t2v](../agent/deep_agent/skills/t2v/SKILL.md) | `call_media_tool` | `Fal___text_to_video`<br>`Fal___get_video_task`<br>`Fal___list_fal_models`<br>`Kling___text_to_video`<br>`Kling___omni_video`<br>`Kling___get_video_task`<br>`Kling___list_kling_models`<br>`Runway___text_to_video`<br>`Runway___get_runway_task`<br>`Runway___list_runway_models`<br>`Seedance___text_to_video`<br>`Seedance___get_video_task`<br>`Seedance___list_seedance_models`<br>`Luma___text_to_video`<br>`Luma___extend_video`<br>`Luma___get_video_task`<br>`Luma___list_luma_models` |
| [video-short](../agent/deep_agent/skills/video-short/SKILL.md) | `call_media_tool`<br>`call_audio_tool`<br>`call_editor_tool` | `Fal___get_video_task`<br>`Fal___image_to_video`<br>`Fal___text_to_video`<br>`Seedance___get_video_task`<br>`Seedance___image_to_video`<br>`Seedance___text_to_video`<br>`Seedream___text_to_image` |
| [vidu-q4](../agent/deep_agent/skills/vidu-q4/SKILL.md) | `call_media_tool` | `Fal___vidu_q4_i2v`<br>`Fal___vidu_q4_r2v`<br>`Fal___get_video_task`<br>`Fal___list_fal_models` |

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
| `vidu_q4_i2v` | `Fal___vidu_q4_i2v` |
| `vidu_q4_r2v` | `Fal___vidu_q4_r2v` |
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
| `transcript_edit` | `Remotion___prepare_conversational_edit` |
| `hyperframes_render` | provider pending: HyperFrames |

## Conversational editing after generation

The editor compiles cuts from existing footage and word-level transcripts. It does not select
the generative V2V ladder. Explicit restyling still selects `edit-v2v`; an existing approved
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
this preparer. Rendering retains its separate approval and cap behavior; premium-generation
rules are unchanged. A plan approval never authorizes new transcription or video generation.

The manager or audio role uses the existing paid ElevenLabs `speech_to_text_convert`, with
verbatim word timestamps, and supplies its result to the editor. Transcripts are cached by
immutable source version in private conversation files. Operator-configured Scribe quotes
remain required for a known estimate; otherwise the cost is unknown. Confidential-project
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
remain incomplete without host inspection. HyperFrames, fframes, local-QC dispatch, live
model judgment and real NLE round trips remain unverified or unavailable.
See [decisions and verification](conversational-edit-decisions.tsv) and
[third-party notices](THIRD_PARTY_NOTICES.md) for the adaptation and its MIT notice.

## Offline routing verification

`tests/fixtures/skill_routing.json` retains all 55 original workbook rows plus the Vidu Q4 (6),
conversational-edit (3) and HyperFrames (3) CSV rows, for **67 total**, **29 active** and
**38 skipped** cases. The Vidu CSV re-states three i2v workbook prompts, so those prompts appear
twice; the HyperFrames CSV's seven motion-graphics rows already existed and are not duplicated.
The unqualified product-photo row expects Kling and is skipped because the existing cheapest
Standard route uses Seedance. HyperFrames cases explicitly enable the dry-run tool. The
conversational-edit HyperFrames-overlay row stays skipped: overlays inside conversational edits
are not wired, even though the standalone hyperframes skill now exists.
Each skip is a generated unittest with its concrete reason, not a dropped fixture row.
An active case asserts the selected skill and proposed exact Gateway name through the same
router used by the runner. Five Resolve suites need a local bridge or transcription/import
integration even though the final packaging tool exists. TTS-only lipsync rows are skipped
because speech alone does not animate a character.
The conversational OTIO row is active. The local-QC and HyperFrames rows keep their exact
seed aliases and explicit dependency skips; they do not claim working QC or overlays.

Run `.venv/bin/python -m unittest discover -s tests -p test_skill_routing.py -v` to see each
case and skip reason. Other offline tests exercise the compiled graph with `ScriptedModel`
and fake Gateway, premium approve/reject resumes, model/environment/region gates, unknown
quotes, concurrent and interrupted spending, and injected continuity embeddings.
`test_provider_ladder.py` adds capability/tier/cost ordering, confidential project context,
review provenance, retry recovery, and compiled fake-model approval-interrupt checks. These
checks make no live or paid provider calls and download no weights.

## Optional HyperFrames compositions

The [HyperFrames skill](../agent/deep_agent/skills/hyperframes/SKILL.md) adapts selected
Apache-2.0 guidance for faceless explainers, product launches, captions with supplied
timings, and kinetic titles. There are now 15 packaged skills. The
[assessment](HYPERFRAMES_ASSESSMENT.md) records all 21 upstream skill decisions,
runtime requirements, and hosted HeyGen exclusions. Attribution and modifications
appear in [third-party notices](THIRD_PARTY_NOTICES.md).

| Contract | Behavior |
| --- | --- |
| `metadata.include_tools` | `call_editor_tool call_audio_tool` |
| `metadata.gateway_tools` | `HyperFrames___render_composition ElevenLabs___text_to_speech_convert` |
| `HYPERFRAMES_ENABLED` | Defaults to `false`. Explicit HyperFrames requests are blocked while disabled. |
| `HYPERFRAMES_DRY_RUN` | Defaults to `true`. The optional local tool validates input and returns preview metadata. |
| Live rendering | Returns `not_run` because an isolated renderer is not configured, even when dry-run is disabled. |
| Compute estimate | Unknown. Non-autonomous dispatch pauses, and an autonomous cap blocks an unknown quote. |
| Confidential projects | The existing executor allowlist blocks HyperFrames previews. No confidentiality gate is relaxed. |

`HyperFrames___render_composition` is an implemented local tool with an MCP-shaped
schema in `agent/hyperframes.py`. Deep Agents injects it only when enabled. It is
not a deployed Gateway Lambda target, so it has no entry in the provider catalog or
`configs/gateway`. Skill contract checks include this local schema alongside the
remote Gateway schemas. Discover it through `read_studio_context`; use its exact
schema and the editor dispatch wrapper. No renderer dependencies enter the Lambda ZIP.

Remotion stays the default for unnamed motion graphics and explicit Remotion requests,
including "Remotion lower thirds". Explicit HyperFrames requests take priority over
generic kinetic-title and video rules. A request for HyperFrames with ElevenLabs VO
selects the HyperFrames skill and the existing speech tool as its first step.
The feature flag makes HyperFrames available and does not reroute unnamed requests.

The tool previews HTML and output settings without executing scripts, fetching assets,
producing frames, or creating a media artifact. Schema validation is not HyperFrames
lint or visual validation. Dry-run and blocked results leave video delivery incomplete.
The approval exemption set, premium-video policy, provider ladder, and spending cap
remain unchanged. HyperFrames outputs are never continuity training inputs.

TODOs are the isolated Node/Chromium/FFmpeg worker, local dependency and managed-media
staging, lint and proof-frame inspection, actual MP4 playback, and any hosted-service
terms and pricing review. Comet E2E remains blocked in this environment.

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
Fal supports the two declared Wan VACE models with Apache-2.0 policy and the two fixed
Vidu Q4 endpoints under `service-terms`. Vidu training and output terms remain a TODO.
Their model policies set `training_eligible=false`, with no new region blocks. Seedance and
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

## Provider capability table and ladder

`routing_policy.json` is the single source for capabilities, tier membership, native controls,
and duration limits. `routing.capability_table()` resolves each row's `policy_ref` against
existing provider/model licence, region and training policy. It derives price grids from
`server/billing_rates.py` and its Fal price helper. No copied rate numbers are stored in the
config. `jobs` records t2v, i2v, start_end_frame, native_audio, max_resolution, 4k, voice_references, multi_shot,
v2v_edit, reference_elements, lipsync, upscale, and image. Unclear capabilities are false
with a note. The `controls` map narrows a capability to the actual job schema.

This table summarizes all 17 configured rows. All rows have lipsync=false and upscale=false.
Resolutions describe supported output presets, not inferred provider marketing claims.

| Provider/model | Built jobs | Extra supported controls | Maximum output | Pricing status |
| --- | --- | --- | --- | --- |
| Fal Wan VACE 14B | t2v, i2v, reference, v2v | End frame, reference images | 720p | Published endpoint/resolution rates |
| Fal Wan 2.2 VACE | t2v, i2v, reference, v2v | End frame, reference images | 720p | Depth/inpaint/outpaint/reframe known; freeform/pose unknown |
| Fal Vidu Q4 I2V | i2v | Implicit native audio, 3 through 16 seconds | 4K | Published per-second promo and list rates |
| Fal Vidu Q4 R2V | i2v, reference | Audio toggle, up to 12 images and 3 voice clips | 4K | Same rates, no audio surcharge |
| Seedance 1.5 Pro | t2v, i2v | Native audio | 1080p | Published token formula |
| Seedream 5.0 Lite | Image, image edit | Image references | 3K | 1K known; 2K/3K unknown |
| Kling 3.0 | t2v, i2v | Audio, end frame, multi-shot, i2v elements | 4K | Published per-second grids |
| Kling 3.0 Turbo | t2v, i2v | Multi-shot | 1080p | Unknown |
| Kling 3.0 Omni | t2v, i2v | Audio, end frame, multi-shot, elements | 4K | Published per-second grids |
| Runway Gen-4.5 | t2v, i2v | No audio/end frame/multi-shot control | 720 class | Published per-second rate |
| Runway Aleph 2 | v2v | Single reference image | Unspecified, input up to 1080p | Integer measured duration known; fractional unknown |
| Runway gen4_image | Image, image edit | Image references | 1080 class | Published per-image rates |
| Runway gen4_image_turbo | Image edit only | Source image required | 1080 class | Published per-image rate |
| Luma Ray 3.2 | t2v, i2v, modify, extend | End frame on i2v | 1080p | Published duration/resolution tiers only |
| Veo | Unavailable | All capabilities false | Unspecified | Unknown |
| MiniMax H3 | Unavailable | All capabilities false; existing US block | Unspecified | Unknown |
| Hunyuan | Unavailable | All capabilities false; existing US block | Unspecified | Unknown |

Speed classes are typical labels, not measured SLAs. Only the two approved Wan models
are training-eligible. Hosted models retain their service-terms restrictions. MiniMax H3
and Hunyuan retain their US blocks even if an operator later enables them.

Selection filters required capabilities, native controls, duration, availability, licence,
and region before considering tier. Within the tier, the cheapest known total price wins;
unknown prices sort after known prices. An explicit provider wins only when all policy and
capability checks pass. A failed request returns its refusal reason in chat. Tool arguments
must actually enable the required audio/end-frame/reference controls and meet the requested
resolution and duration. A wrong tool/model returns the selected route for rediscovery,
never silently substitutes the action after an approval.

| Tier | New finished video | Video edit |
| --- | --- | --- |
| Draft | Fal Wan | Fal Wan VACE |
| Standard, default | Seedance, Kling or Vidu Q4 by cost | Luma Modify, `Luma___modify_video` |
| Premium | Built, enabled Kling or Runway Gen-4.5; Veo unavailable | Runway Aleph |

Faithful plate and multi-shot edits prefer Aleph unless Draft or confidential. This is an
editing preference, not a native multi-shot capability. Draft previews and an automatic
retry after an explicit artifact rejection use Wan only, retaining the rejected job's
requirements. If Wan cannot meet them, the retry is blocked instead of weakening the brief
or escalating. Approval rejection never starts a retry. A saved review/retry transition is
idempotent across a resume. Unrelated new shots retain their chosen tier.

The default still requirement is 2K, selecting Seedream with an unknown quote. At a compatible
lower resolution, cost ordering can select Runway images. Draft still previews can reuse an
approved image or show a Wan video frame. There is no built Wan image-generation tool;
Draft/confidential image generation and image reject retries fail with a clear capability
refusal. Building a Wan image tool is an open dependency, not an invented capability.

### Confidential project source

Projects persist `provider_policy` in `projects.provider_policy_json`. Project creation
accepts `{"provider_policy":{"confidential":true,"quality_tier":"standard"}}`.
Authenticated, workspace-scoped `GET` and `PUT /api/studio/projects/{project_id}/provider-policy`
read/update that policy. The Studio host populates `StudioAgentRequest.confidential` and
`quality_tier` from it, for both local and remote workers. The executor uses that host context
for both Deep Agents and Codex. Mentioning confidential in chat also tightens the policy;
a prompt cannot relax a confidential project. There is no new Studio settings control yet.

Confidential video/image projects use Wan at every tier and on rejection. Unsupported
capabilities refuse generation. This rule never permits escalation to another image/video
provider, including a previously approved call. New audio generation on other providers is also
blocked. Polling and assembly of existing media remain available.

### Chat disclosure and approval

Before dispatch, the host emits a chat `MODEL_UPDATE` with provider/model, tier, capability
filters, estimated cost including the existing platform fee, and typical speed class.
Unpublished rates render as **unknown**. Published-price disclosure ignores dry-run zero charges
without changing any provider setting. Q4 uses the promotional schedule through 2026-11-30
and the published list schedule afterward. Dispatch/cap accounting continues to use billing's
actual dry-run charge. Both quote paths keep billing validation. Missing measured edit
durations stay unknown. Q4 pricing and its dated expiry are encoded in `server/billing_rates.py`.

Paid tools still pause in non-autonomous runs. The existing premium video target rule for
Kling, Runway, Luma and future Veo still pauses autonomous runs, with the estimate in the
native interrupt description. Kling requires this approval even when selected at Standard.
`premium_video_approval` and `RENDERHAUS_PREMIUM_VIDEO_APPROVAL` retain their previous semantics.
`APPROVAL_EXEMPT_TOOLS`, existing free tools and the optional autonomous spend cap are unchanged.
The new free conversational-edit preparer requires separate cut-plan confirmation.
The Codex fallback uses the same executor and retains its approval/checkpoint protocol.

Unknown combinations include Kling Turbo, Wan 2.2 freeform/pose and unpriced resolutions,
fractional Aleph billing, unpriced Luma lengths, Seedream larger sizes, invalid ElevenLabs
operator quotes, and Remotion's compute placeholder. Unknown is never a guessed amount or
a dry-run zero. A spending cap blocks an unknown-cost paid call as before.

### Provider outcomes and training

`record_media_outcome(call_id, outcome)` records an explicit customer acceptance or rejection
of a saved completed generation call. The host checks for a verdict in the current request,
uses saved provider/job provenance, and refuses queued or dry-run reviews. The conservative
English verdict recognizer can refuse unfamiliar wording; the model cannot create acceptance.

`agent/deep_agent/outcomes.py` appends JSONL to `.renderhaus/provider-outcomes/outcomes.jsonl`,
or `RENDERHAUS_OUTCOME_DIR/outcomes.jsonl`. Each row includes event ID, provider/model, job type,
provider job ID when available, workspace/project/execution scope, verdict, and stage.
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
`continuity_qc.dinov3_enabled` and `ContinuityConfig.enable_dinov3` default OFF. When turned on,
`facebook/dinov3-vitb16-pretrain-lvd1689m` replaces DINOv2 in the DINO slot (same CLS pooling,
same `min(siglip, dino) >= threshold` rule, `ContinuityReport.dino_model` records which model
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

Vidu Q4 validation results are recorded in [vidu-q4-decisions.tsv](vidu-q4-decisions.tsv).
The suite ran 551 tests: 516 passed and 35 skipped. Ruff passed for `agent lambdas scripts server providers`, and

Conversational-edit branch: final checks ran 552 tests, with 516 passed and 36 explicit skips.
`scripts/ci_check.py` passed with every provider DRY_RUN flag enabled and secrets loading
disabled. Its Lambda packaging used the existing local wheelhouse with pip network access
disabled. Studio's `tsc --noEmit -p .` and the timeline-review checks passed; the temporary
`node_modules` link was removed. The Remotion renderer's separate typecheck remains blocked
because its npm package/types are unavailable locally. Current offline checks cover routing proposals,
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
- The routing fixture's Luma case is active (see the counts above).

## Vidu Q4 on fal

The fixed endpoint tools use the radar names with the existing `Fal___` target prefix.
Separate schemas avoid mixing Wan frame controls with Q4 seconds and audio controls.
The [I2V API](https://fal.ai/models/fal-ai/vidu/q4/image-to-video/api) requires `image_url`
and has an optional `prompt`. The [R2V API](https://fal.ai/models/fal-ai/vidu/q4/reference-to-video/api)
requires `prompt`, accepts optional `reference_image_urls` and `reference_audio_urls`,
and defaults to silent `audio=false`. I2V audio is implicit and has no toggle.
Both tools use integer `duration` from 3 through 16, default 5, and exact resolution enums
`540p`, `720p`, `1080p`, `2K`, and `4K`, default `720p`. `2K` uses the existing nominal
comparison rank 2048 in policy. That rank does not assert the artifact's pixel dimensions.

Official [I2V pricing](https://fal.ai/models/fal-ai/vidu/q4/image-to-video) and
[R2V pricing](https://fal.ai/models/fal-ai/vidu/q4/reference-to-video), accessed 2026-10-08,
list a promotion until November 30 and the later list rates. This branch binds the cutoff
to the requested 2026-11-30, inclusive in UTC. `vidu_q4_rates()` uses list rates from
2026-12-01. The platform fee uses the existing `_with_fee`. Audio does not increase
R2V pricing. Estimates remain unknown for undocumented settings.

Q4 is Standard because these are general still and reference generation endpoints with
published per-second prices and no requested premium step-up. Standard cost ordering is
unchanged; Seedance remains the unqualified default. Q4 is outside `premium_targets` and
`free_tools`. Non-autonomous paid calls pause with a native cost preview and chat disclosure.
Autonomous Q4 keeps the existing spend cap. Premium approvals and exempt tools are unchanged.
Confidential projects and rejected-artifact retries restrict fal to the Wan model allowlist.
Q4 polling retains non-training provenance from the endpoint handle, including after restart.

There are still eight provider targets. Fal grows from six tools to eight. CI derives tool
counts from generated schemas, so it has no numeric threshold to update. The deploy workflow's
eight-provider threshold remains correct. The Docker skill-count check changes to 15.
Billing-only edits rebuild both the Gateway ZIP and agent runtime so their shared rates stay current.
No AGPL code or source workbook/ledger files were copied into this repository.
