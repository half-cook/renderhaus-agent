# Renderhaus capability map

One quality-first default serves each capability. Selection order is **explicit provider/model request > named exception > default > declared interim while the default is pending or commercially blocked**. Prices inform approval and disclosure; they never order models. Wan 3 generation uses fal; its edit and extend defaults use Alibaba Model Studio. See [fal contracts](FAL_WAN3_PROVIDER.md) and [Model Studio contracts](ALIBABA_MODELSTUDIO.md).

## Capability choices

| Capability | Default routing ID | Exception predicate → routing ID | Built interim | A/B candidates (inactive) |
| --- | --- | --- | --- | --- |
| t2v | `wan3_t2v` | `dialogue && !real_face_refs` → `seedance25_t2v` (synthetic dialogue) | None; Wan 3 built | gemini_omni_11_flash |
| i2v | `wan3_i2v` | `dialogue && !real_face_refs` → `seedance25_i2v` (synthetic dialogue) | None; Wan 3 built | gemini_omni_11_flash, vidu_q4_i2v |
| reference_video | `wan3_r2v` | `dialogue && !real_face_refs` → `seedance25_r2v` (synthetic dialogue references) | — | — |
| v2v_edit | `wan3_edit` | — | `seedance25_edit` while Wan commercial policy is blocked | — |
| extend | `wan3_extend` | — | `seedance25_extend` while Wan commercial policy is blocked | — |
| still_image | `gpt_image25_t2i` | `vector_output` → `recraft_v41_vector` (editable vector output) | `seedream_t2i` | — |
| image_edit | `gpt_image25_edit` | `text_only_edit` → `ideogram45_edit` (pixel-preserving text-only edit) | `seedream_edit` | ideogram45_edit |
| lipsync | `sync3_lipsync` | `duration_over_30s && presenter` → `heygen_avatar_v` (long presenter or digital twin) | — | heygen_avatar_v |
| performance_transfer | `runway_act_two` | `full_body_motion` → `kling_motion_control` (full-body motion or dance) | — | kling_motion_control |
| tts | `eleven_v4_turbo` | — | — | — |
| voice_clone | `voices_ivc_create` | — | — | — |
| music | `mureka_v95` | — | `elevenlabs_music` | — |
| sfx | `mirelo_v2a` | `text_only_sfx` → `elevenlabs_sfx_v2` (text-only sound effect) | — | elevenlabs_sfx_v2 |
| upscale | `topaz_upscale` | — | — | — |
| interpolate | `topaz_interpolate` | `linear_fps` → `topaz_interpolate` (Chronos for linear frame-rate conversion) | — | — |
| motion_graphics | `remotion_render` | `explicit_html_template` → `hyperframes_render` (explicit HTML template request) | — | — |
| nle_handoff | `Remotion___export_nle_timeline` | — | — | — |
| continuity_qc | `local_qc` | — | — | gemini_vlm_judge |

Canonical aliases remain stable even when an official endpoint differs from the research lead. A pending alias has no Gateway binding and cannot perform a request. Plain default requests can use only the listed interim and disclose “interim default until <alias> lands”. A named exact future model stays pending rather than silently running a different model. Bare “Seedance” uses the upgraded 2.5 adapter. Exception defaults do not receive unrelated capability interims.

The t2v, i2v and reference_video defaults use Wan 3 on fal. The synthetic-dialogue exceptions
now use Seedance 2.5 through fal US. Real-person references force Wan generation with consent.
Wan edit/extend remain defaults but their preview licence selects the declared Seedance 2.5
interims for synthetic sources. Real-person edit/extend refuse that interim. The single Wan
model `live_enabled` policy switch restores its selection, while the unchanged adapter hard
licence block remains. BytePlus is optional only for authorized non-US platform use.

## Deterministic intent predicates

- `dialogue`: quoted speech or says/talking/dialogue/speaking, with explicit “no dialogue” and “not talking” negation.
- `real_face_refs`: a real-person/actor reference, a described user photo/video, a CEO/selfie/face reference, or authoritative reference metadata. An argument set to false cannot erase prompt evidence. Video generation forces Wan 3 and requires explicit likeness consent.
- `vector_output`: SVG/vector/logo output → Recraft. Ideogram generation without an existing image uses the GPT Image default; only `text_only_edit` selects Ideogram editing.
- `full_body_motion`: dance/body motion → Kling Motion Control. `facial_performance`: facial expression/performance → Act-Two. Body motion wins when both apply.
- `duration_over_30s`: generation/performance single shots over 30 seconds are blocked with a split-into-shots reason. A long presenter/digital twin lipsync request uses pending HeyGen Avatar V.
- `text_only_sfx`: a sound request without source video → built ElevenLabs SFX v2. Source-video Foley → pending Mirelo. Its verified endpoint returns muxed videos and is included in the paid-video approval gate.
- `explicit_html_template`: explicit HTML/CSS/web template request → flag-gated HyperFrames; ordinary motion graphics uses Remotion.
- `linear_fps`: built Topaz interpolation with Chronos rather than the default Apollo; explicit model requests still win. See [Topaz](TOPAZ.md).

## Explicit-only tools and approvals

Kling generation/Omni, Runway Gen-4.5/Aleph/Gen-4 Image, Luma, Vidu Q4, Seedream, Fish Audio, ElevenLabs music and Wan 2.x VACE remain built. Named requests use their existing tools with “explicit request; not the default for <capability>”. Declared interims can use demoted tools while their replacement is pending. The existing rejected-shot Wan 2.x training retry path and provenance eligibility checks remain unchanged. MiniMax H3 and Hunyuan stay blocked.

All paid video pauses for approval with a cost estimate, including autonomous runs: current Seedance, Fal/Wan/Vidu, Kling, Runway, Luma and Remotion, plus built Sync, HeyGen and Topaz and the future Act-Two, Kling Motion, Mureka lyrics-video and Mirelo aliases. Sync, HeyGen and Topaz always pause even when the general premium-video switch is disabled. `premium_video_approval` / `RENDERHAUS_PREMIUM_VIDEO_APPROVAL` remains the global switch. Approval exemptions and the autonomous spending cap are unchanged; paid non-video behavior follows the existing effect classification. Voice-clone writes retain their existing autonomous behavior. Editorial cut-plan confirmation and final paid rendering remain separate approvals.

Each dispatch publishes MODEL_UPDATE with provider, model, approval estimate and default/exception/explicit/interim reason. Unknown prices stay unknown, including in dry-run mode. The optional `ab_arm` outcome field only records a label; no A/B runner or evaluation harness is activated.

## Confidential handling is dropped

`project.confidential` and the older quality setting remain stored metadata. Neither changes routing, approval or provider selection. No confidential-route skill, Wan-only confidential rule, refusal, or FLUX alias exists. True-confidential workbook rows and archived confidential drafts are dropped; false prefixes are ordinary prompts. Tests compare actual dispatch/approval behavior with the flag on and off.

## US availability

Sources below were read on **2026-10-08**, except Sync transport evidence rechecked on **2026-10-09**. “yes” with an inference note describes ordinary service access, not a model-specific region guarantee. Unclear eligibility remains a future activation check. No paid API request was made.

| Provider | Host | US available | Official source | Read date | Notes |
| --- | --- | --- | --- | --- | --- |
| Alibaba Wan 3.0 | fal | yes | [Official source](https://fal.ai/legal/terms-of-service) | 2026-10-08 | Inferred from US customer provisions, US-based fal and commercial model listing; model-specific geographic guarantee not published. |
| Alibaba Wan 3.0 | Alibaba Model Studio, US Virginia or Singapore | yes | [Official source](https://www.alibabacloud.com/help/en/model-studio/wan3-video-generation-api-reference) | 2026-10-08 | Official Virginia endpoint and same-reference edit/extension examples verified. Workspace, model and API key must share region. |
| ByteDance Seedance 2.5 | fal US default | yes | [Official source](https://fal.ai/models/bytedance/seedance-2.5/us/text-to-video) | 2026-10-08 | Explicit US-hosted endpoint. |
| ByteDance Seedance 2.5 | BytePlus optional | no | [Official source](https://docs.byteplus.com/en/docs/ModelArk/availability) | 2026-10-08 | Published exhaustive country list includes Canada and omits US. Availability subject to point-of-purchase confirmation. |
| OpenAI GPT Image 2.5 Sunburst | OpenAI Images API | yes | [Official source](https://help.openai.com/en/articles/5347006-openai-api-supported-countries-and-territories) | 2026-10-08 | United States explicitly listed. Organization verification may be required. |
| Recraft V4.1 Pro vector | fal | yes | [Official source](https://fal.ai/legal/terms-of-service) | 2026-10-08 | US fal service eligibility inferred from terms; model-specific region guarantee not published. |
| Ideogram 4.5 edit | fal | yes | [Official source](https://fal.ai/legal/terms-of-service) | 2026-10-08 | US fal eligibility inferred from terms; no model-specific region guarantee. |
| sync-3 | fal primary | yes | [Official source](https://fal.ai/legal/terms-of-service) | 2026-10-09 | US service access inferred from fal terms and commercial model listing; model-specific geographic guarantee not published. |
| sync-3 | sync.so optional | unclear | [Official source](https://sync.so/terms) | 2026-10-09 | Direct integration needs express written permission; no explicit country eligibility list located. |
| HeyGen Avatar V | HeyGen direct | unclear | [Official source](https://help.heygen.com/en/articles/11187873-heygen-privacy-and-security-standards) | 2026-10-08 | Official help confirms US AWS hosting; no explicit customer-country eligibility table verified. |
| Runway Act-Two | Runway direct | yes | [Official source](https://runway.com/terms-of-use) | 2026-10-08 | Section15 says services controlled and offered from US facilities. |
| Kling 3.0 Motion Control Pro | fal; direct Kling optional | yes | [Official source](https://fal.ai/legal/terms-of-service) | 2026-10-08 | US fal eligibility inferred from terms. Direct Kling US eligibility unclear. |
| Mureka V9.5 | Mureka direct | yes | [Official source](https://platform.mureka.ai/privacy_policy.pdf) | 2026-10-08 | Inferred from explicit US-user privacy provisions; no API-specific region guarantee located. |
| Mirelo SFX1.6 | fal | yes | [Official source](https://fal.ai/legal/terms-of-service) | 2026-10-08 | US fal eligibility inferred from terms; direct Mirelo availability unclear. |
| ElevenLabs Eleven v4 Turbo | ElevenLabs direct | yes | [Official source](https://help.elevenlabs.io/hc/en-us/articles/22497891312401-Do-you-restrict-access-to-the-service-and-platform-for-any-specific-countries) | 2026-10-08 | Official restricted-country list excludes US. |
| ElevenLabs SFX v2 | ElevenLabs direct | yes | [Official source](https://help.elevenlabs.io/hc/en-us/articles/22497891312401-Do-you-restrict-access-to-the-service-and-platform-for-any-specific-countries) | 2026-10-08 | No US restriction listed. |
| Topaz Starlight Precise2.6, Apollo, Chronos | fal default; Topaz direct optional | yes | [Official source](https://fal.ai/legal/terms-of-service) | 2026-10-08 | US fal eligibility inferred. Direct Topaz customer-region guarantee not located. |
| Google Gemini3.8 Flash | Gemini Developer API paid | yes | [Official source](https://ai.google.dev/gemini-api/docs/available-regions) | 2026-10-08 | United States explicitly listed. |
| Remotion and in-house NLE exporter | customer AWS Lambda / local exporter | yes | [Official source](https://www.remotion.dev/docs/lambda) | 2026-10-08 | Official region list includes us-east-1,us-east-2,us-west-1,us-west-2; in-house local exporter no regional vendor gate. |
| HyperFrames | local dry-run renderer | yes | [Official source](https://github.com/heygen-com/hyperframes/blob/main/LICENSE) | 2026-10-08 | Apache code licence has no US exclusion; local operation. |
| ElevenLabs Instant Voice Cloning | ElevenLabs direct | yes | [Official source](https://help.elevenlabs.io/hc/en-us/articles/22497891312401-Do-you-restrict-access-to-the-service-and-platform-for-any-specific-countries) | 2026-10-08 | Official restricted-country list excludes US. |
| SigLIP and DINOv2 continuity embeddings | existing RunPod worker / local | yes | [Official source](https://github.com/facebookresearch/dinov2/blob/main/LICENSE) | 2026-10-08 | Worldwide Apache licence for customer-controlled execution; specific RunPod account/region availability not verified. |

The requested external copy at `/workspace/rh-runs/us-availability-2026-10-08.md` could not be written under this workspace permission profile. An identical standalone table is at `docs/US_AVAILABILITY.md`; a temporary copy is at `/tmp/rh-capability-evidence/us-availability-2026-10-08.md`.

## Official IDs, schemas, prices and licences

These are documented future-adapter inputs, not active billing entries. Existing provider billing rates remain authoritative for built tools. The structured research record is [capability-map-evidence.json](capability-map-evidence.json). Pricing below uses official public pages read **2026-10-08**. Do not apply an unverified estimate or expire a promo silently.

### Alibaba Wan 3.0 — fal

Routing IDs: `wan3_t2v`, `wan3_i2v`, `wan3_r2v`. Official IDs: `alibaba/wan-3.0/text-to-video`, `alibaba/wan-3.0/image-to-video`, `alibaba/wan-3.0/reference-to-video`. Status: **verified**.

fal queue submit/status/result; prompt, resolution, duration 2-30s, audio; start_image_url and optional end_image_url for i2v; refs capped at 10 images, 5 videos and 5 audio, each video/audio total <=15s. [Official API source](https://fal.ai/wan-3) [Official API source](https://fal.ai/models/alibaba/wan-3.0/reference-to-video/api) [Official API source](https://fal.ai/models/alibaba/wan-3.0/image-to-video)

USD/s 480p=0.05, 720p=0.10, 1080p=0.20. Measured reference-video input seconds add to output seconds at the same resolution rate. Audio/image reference surcharges are not published and are not invented. Read 2026-10-09. [Official pricing](https://fal.ai/models/alibaba/wan-3.0/reference-to-video)

commercial API; closed weights; fal model card Commercial use. `training_eligible=false`: fal terms 14(c) restrict improving competing third-party products from outputs. Read 2026-10-09. [Licence/terms source](https://fal.ai/legal/terms-of-service)

Fal reference schema does not document edit-preserve-duration or explicit extend mode.

### Alibaba Wan 3.0 — Alibaba Model Studio, US Virginia or Singapore

Routing IDs: `wan3_edit`, `wan3_extend`. Official IDs: `wan3.0-video`. Status: **verified**.

POST https://{WorkspaceId}.us-east-1.maas.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis; X-DashScope-Async:enable; model, input.prompt, input.media reference_video; extend prompt includes extension intent and ratio adaptive. GET same regional /api/v1/tasks/{task_id}. [Official API source](https://www.alibabacloud.com/help/en/model-studio/wan3-video-generation-api-reference)

Virginia USD/s 480P=0.041256,720P=0.082513,1080P=0.165025; Singapore=0.05/0.10/0.20. Input video plus output seconds billed. [Official pricing](https://www.alibabacloud.com/help/en/model-studio/wan3-0-video)

Proprietary service terms and closed weights. **Customer live use is blocked** by [Preview Product Terms §1.1](https://www.alibabacloud.com/help/en/legal/latest/alibaba-cloud-international-website-beta-testing-terms), which permits only internal testing, research and evaluation. Product Terms §3.14 makes the preview terms controlling. Both sources read 2026-10-09. `training_eligible=false`: §4.48 restricts training competing products without authorization. Personal references require rights and consent. [Licence/terms source](https://www.alibabacloud.com/help/en/legal/latest/alibaba-cloud-international-website-product-terms-of-service-v-3-8-0), read 2026-10-09.

Model is preview. `duration=-1` means smart duration and remains dry-run with unknown cost. Explicit extension duration is total output length. The documented workspace endpoint is verified; the mandated default `https://dashscope-us.aliyuncs.com` synthesis POST is **UNVERIFIED** and blocked live. [Regions](https://www.alibabacloud.com/help/en/model-studio/regions), read 2026-10-09. See [Model Studio configuration and decisions](ALIBABA_MODELSTUDIO.md).

### ByteDance Seedance 2.5 — fal US default

Routing IDs: `seedance25_t2v`, `seedance25_i2v`, `seedance25_r2v`, `seedance25_edit`, `seedance25_extend`. Official IDs: `bytedance/seedance-2.5/us/text-to-video`, `bytedance/seedance-2.5/us/image-to-video`, `bytedance/seedance-2.5/us/reference-to-video`. Status: **verified**.

fal queue; prompt for t2v, image_url/end_image_url for i2v, image_urls/video_urls/audio_urls for refs; resolution 480p/720p/1080p, duration to 30s, generate_audio,end_user_id. [Official API source](https://fal.ai/models/bytedance/seedance-2.5/us/text-to-video/api) [Official API source](https://fal.ai/models/bytedance/seedance-2.5/us/image-to-video/api) [Official API source](https://fal.ai/models/bytedance/seedance-2.5/us/reference-to-video)

US USD/M tokens: 25.68 at 480p/720p and 28.08 at 1080p. Global rates are 21.40 and 23.40 respectively. Video references multiply the full input-plus-output token cost by 0.6. Use the documented token formula rather than per-second approximations. [US pricing](https://fal.ai/models/bytedance/seedance-2.5/us/reference-to-video), [global pricing](https://fal.ai/models/bytedance/seedance-2.5/reference-to-video), read 2026-10-09.

Commercial hosted API with proprietary weights. `training_eligible=false`: fal terms section 14.3 restrict competing-model training. [Licence/terms source](https://fal.ai/legal/terms-of-service), read 2026-10-09.

US endpoint rates exceed map's non-US fal leads. Real-person references remain blocked by routing.

### ByteDance Seedance 2.5 — BytePlus optional

Routing IDs: `seedance25_t2v`, `seedance25_i2v`, `seedance25_r2v`, `seedance25_edit`, `seedance25_extend`. Official IDs: `dreamina-seedance-2-5-260628`. Status: **verified ID and async endpoint; optional direct host**.

ModelArk POST `https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks` with model, text/image/video/audio content and reference roles, generate_audio, ratio and duration. Poll GET `/contents/generations/tasks/{id}`. Editing and extension use `omni_reference_task_type`. [Official task API](https://docs.byteplus.com/en/docs/modelark/create-video-generation-task-api), [2.5 tutorial](https://docs.byteplus.com/zh-TW/docs/modelark/seedance-2-5), read 2026-10-09.

Official indexed direct pricing, read 2026-10-09, lists USD 10.70/M without video and 6.40/M with video at 480p/720p; 1080p is 11.70/M without video and 7.00/M with video. The video-input minimum-token floor is UNVERIFIED, so those estimates remain unknown and dry-run. [Official pricing](https://docs.byteplus.com/id/docs/modelark/model-pricing?redirect=1)

Proprietary API. Current terms §4.2.3 require written authorization for platform reintegration/resale and exclude US end users. Direct live platform use is blocked without operator authorization. `training_eligible=false`; no continuity-training grant accepted. [Licence/terms source](https://docs.byteplus.com/en/docs/legal/docs-service-specific-terms), read 2026-10-09.

### OpenAI GPT Image 2.5 Sunburst — OpenAI Images API

Routing IDs: `gpt_image25_t2i`, `gpt_image25_edit`. Official IDs: `gpt-image-2.5-sunburst`, `gpt-image-2.5-sunburst-2026-09-08`. Status: **verified; adapter built, dry-run by default**. See [provider configuration](OPENAI_IMAGES.md), re-verified on 2026-10-09.

POST /v1/images/generations or /v1/images/edits; model,prompt; edit has input images; size dimensions multiples16, ratio1:3..3:1; quality low/medium/high/xhigh/max/auto. [Official API source](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst) [Official API source](https://developers.openai.com/api/docs/guides/image-generation) [Official API source](https://developers.openai.com/api/reference/resources/images/methods/generate)

USD/1M tokens text input=5, image input=8, image output=30, batch output=15. [Official pricing](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst)

OpenAI Services Agreement proprietary API; commercial applications and output ownership. `training_eligible=false`: Services Agreement 3.3(e) restricts developing competing AI with outputs except defined permitted exceptions.. [Licence/terms source](https://openai.com/policies/services-agreement/)

### Recraft V4.1 Pro vector — fal

Routing IDs: `recraft_v41_vector`. Official IDs: `fal-ai/recraft/v4.1/pro/text-to-vector`. Status: **verified**.

fal queue; prompt,image_size,colors,background_color; images[] SVG files output. [Official API source](https://fal.ai/models/fal-ai/recraft/v4.1/pro/text-to-vector/api)

USD 0.30/image [Official pricing](https://fal.ai/models/fal-ai/recraft/v4.1/pro/text-to-vector)

commercial API, fal Commercial use. `training_eligible=false`: fal third-party competing-model training restriction.. [Licence/terms source](https://fal.ai/models/fal-ai/recraft/v4.1/pro/text-to-vector)

Map omitted fal-ai prefix; corrected official host endpoint does not change canonical routing alias.

### Ideogram 4.5 edit — fal

Routing IDs: `ideogram45_edit`. Official IDs: `ideogram/v4.5/edit`. Status: **verified**.

prompt,image_url required; reference_image_urls,mask_url; edit_precision=high for unchanged-pixel restoration; quality very_low/low/medium/high. [Official API source](https://fal.ai/models/ideogram/v4.5/edit/api)

USD/image very_low=0.008,low=0.03,medium=0.06,high=0.22. [Official pricing](https://fal.ai/models/ideogram/v4.5/edit)

commercial API, fal Commercial use. `training_eligible=false`: fal third-party competing-model training restriction.. [Licence/terms source](https://fal.ai/models/ideogram/v4.5/edit)

Only edit requests select specialist; generation remains GPT Image default.

### sync-3 — fal primary, authorized Sync direct

Routing ID: `sync3_lipsync`; Gateway: `Sync___lipsync_video`. Verified models/endpoints:
`sync-3` direct and `fal-ai/sync-lipsync/v3` on fal. Fal is the US-accessible default;
Sync direct requires written permission under its competitor/integration terms.
[Official fal API](https://fal.ai/models/fal-ai/sync-lipsync/v3/api),
[direct API](https://sync.so/docs/api-reference/api/generate-api/create).

Fal: $8/minute. Direct legacy Base: $0.133/s at 25 fps, charged per output frame;
credit-plan rates are unknown. Read **2026-10-09**. Existing platform fees apply.
[fal price](https://fal.ai/models/fal-ai/sync-lipsync/v3),
[Sync billing](https://sync.so/docs/product/billing).

Closed proprietary service, `service-terms`, `training_eligible=false`. Fal advertises
commercial use and permits customer API integrations. Direct Sync permits upload reuse
for improvement and has additional competitor/redistribution restrictions. Face/voice
consent is mandatory. Fal's hard duration ceiling is **UNVERIFIED**; the adapter uses a
configurable operational cap, not a claimed vendor limit. [fal terms](https://fal.ai/legal/terms-of-service),
[fal data terms](https://fal.ai/legal/api-services), [Sync terms](https://sync.so/terms).
See [SYNC.md](SYNC.md) for chunking limits, guardrails and evidence.

### HeyGen Avatar V — HeyGen direct

Routing IDs: `heygen_avatar_v`. Official IDs: `avatar_v`. Status: **verified**.

POST /v3/videos type=avatar,avatar_id,script,voice_id,resolution,engine={type:avatar_v}; poll GET /v3/videos/{video_id}. Avatar look must list avatar_v in supported_api_engines; consent. [Official API source](https://developers.heygen.com/avatar-v) [Official API source](https://developers.heygen.com/llms.txt)

TODO unknown; map https://developers.heygen.com/docs/pricing returns404; current official index points to signed-in API dashboard and unpublished enterprise pricing. [Official pricing](https://developers.heygen.com/llms.txt)

proprietary API; exact terms require future adapter branch verification. `training_eligible=false`: No clear output-training permission verified.. [Licence/terms source](https://developers.heygen.com/avatar-v)

Avatar V requires an eligible digital_twin look; arbitrary photo animation should not silently use Avatar IV.

### Runway Act-Two — Runway direct

Routing IDs: `runway_act_two`. Official IDs: `act_two`. Status: **verified**.

POST /v1/character_performance; model=act_two,character={type:image|video,uri},reference={type:video,uri} duration3..30s; optional bodyControl,expressionIntensity1..5,ratio,seed. Character must have visible recognizable face; task poll through existing Runway endpoint. [Official API source](https://docs.dev.runwayml.com/guides/models/) [Official API source](https://raw.githubusercontent.com/runwayml/sdk-python/main/src/runwayml/types/character_performance_create_params.py) [Official API source](https://raw.githubusercontent.com/runwayml/sdk-python/main/src/runwayml/resources/character_performance.py)

USD 0.05/second per official model list; credit conversion pricing page not fully rendered by text browser. [Official pricing](https://docs.dev.runwayml.com/guides/models/)

Runway Terms proprietary API; commercial use allowed; competing product training restricted.. `training_eligible=false`: Runway Terms5.2(viii) restricts using outputs to train similar/competitive products.. [Licence/terms source](https://runway.com/terms-of-use)

### Kling 3.0 Motion Control Pro — fal; direct Kling optional

Routing IDs: `kling_motion_control`. Official IDs: `fal-ai/kling-video/v3/pro/motion-control`. Status: **verified fal; direct UNVERIFIED**.

image_url,video_url,character_orientation=image|video required; optional prompt,keep_original_sound defaulttrue. image orientation max10s; video orientation max30s; one optional facial-binding element on video orientation. [Official API source](https://fal.ai/models/fal-ai/kling-video/v3/pro/motion-control) [Official API source](https://fal.ai/models/fal-ai/kling-video/v3/pro/motion-control/api)

USD 0.168/second fal pro; direct Kling pricing TODO unknown. [Official pricing](https://fal.ai/models/fal-ai/kling-video/v3/pro/motion-control)

commercial fal API, Commercial use model label. `training_eligible=false`: fal third-party competing-model training restriction.. [Licence/terms source](https://fal.ai/models/fal-ai/kling-video/v3/pro/motion-control)

### Mureka V9.5 — Mureka direct

Routing IDs: `mureka_v95`, `mureka_lyrics_video`. Official IDs: `mureka-9.5`. Status: **verified ID in official docs JS schema; API branches pending**.

Song POST /v1/song/generate requires lyrics,model. Instrumental POST /v1/instrumental/generate requires model. model enum includes mureka-9.5; n defaults2 max3 billed per song. Lyrics-video POST /v1/lyrics-video/generate song_id xor upload_audio_id, background assets. [Official API source](https://platform.mureka.ai/docs/api/operations/post-v1-song-generate.html) [Official API source](https://platform.mureka.ai/docs/api/operations/post-v1-instrumental-generate.html) [Official API source](https://platform.mureka.ai/docs/api/operations/post-v1-lyrics-video-generate.html) [Official API source](https://platform.mureka.ai/docs/assets/chunks/theme.Cv864CFs.js)

TODO unknown; official pricing page renders no public price text in available browser; map $0.15/song unverified. [Official pricing](https://platform.mureka.ai/pricing)

paid API output full usage rights and commercial authorization per FAQ; weights proprietary. `training_eligible=false`: Commercial distribution permission does not explicitly authorize model training.. [Licence/terms source](https://platform.mureka.ai/docs/en/faq.html)

### Mirelo SFX1.6 — fal

Routing IDs: `mirelo_v2a`. Official IDs: `mirelo-ai/sfx1.6/video-to-video`. Status: **verified**.

video_url required;text_prompt,duration default10 (sliding windows >10),num_samples default2,seed; result.video[] muxed videos. Advertised up to60s. [Official API source](https://fal.ai/models/mirelo-ai/sfx1.6/video-to-video) [Official API source](https://fal.ai/models/mirelo-ai/sfx1.6/video-to-video/api)

USD 0.01/second; exact per-sample multiplier requires branch schema verification. [Official pricing](https://fal.ai/models/mirelo-ai/sfx1.6/video-to-video)

commercial fal API model card. `training_eligible=false`: fal third-party competing-model training restriction.. [Licence/terms source](https://fal.ai/models/mirelo-ai/sfx1.6/video-to-video)

Canonical mirelo_v2a is a routing alias; verified map endpoint returns muxed videos, not bare audio. Future adapter must handle/extract audio without silently changing endpoint. Explicitly set num_samples to estimate accurately.

### ElevenLabs Eleven v4 Turbo — ElevenLabs direct

Routing IDs: `eleven_v4_turbo`. Official IDs: `eleven_v4_turbo`. Status: **verified ID; existing REST TTS transport UNVERIFIED**.

Official launch/model docs specifically direct v4 Turbo to wss://api.elevenlabs.io/v1/text-to-dialogue/stream-input. REST /v1/text-to-speech/{voice_id} requires model can_do_text_to_speech; public reference does not verify v4 Turbo flag. [Official API source](https://elevenlabs.io/docs/overview/models) [Official API source](https://elevenlabs.io/docs/changelog/2026/9/28) [Official API source](https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/realtime-tdd) [Official API source](https://elevenlabs.io/docs/api-reference/text-to-speech/convert)

USD/1000chars standard0.04; promo0.011 through Oct12 2026, then standard rate. Do not retain promo indefinitely. [Official pricing](https://elevenlabs.io/pricing/api)

ElevenLabs paid commercial API; Terms of Service. `training_eligible=false`: No clear model-training permission verified.. [Licence/terms source](https://elevenlabs.io/terms-of-use)

Do not mark model ID unverified; endpoint support is unverified. Keep unsupported transport dry-run.

### ElevenLabs SFX v2 — ElevenLabs direct

Routing IDs: `elevenlabs_sfx_v2`. Official IDs: `eleven_text_to_sound_v2`. Status: **verified**.

POST /v1/sound-generation;text required;duration_seconds0.5..30,loop,prompt_influence0..1,model_id enum/default eleven_text_to_sound_v2. Returns audio. [Official API source](https://elevenlabs.io/docs/overview/models) [Official API source](https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert)

USD 0.12/minute per API pricing; pricing FAQ ambiguously says per generation metering. Verify exact SFX estimate unit before changing built rate. [Official pricing](https://elevenlabs.io/pricing/api)

paid commercial API, royalty-free generated SFX. `training_eligible=false`: No explicit model-training grant verified.. [Licence/terms source](https://elevenlabs.io/pricing/api)

### Topaz Starlight Precise2.6, Apollo, Chronos — fal default; Topaz direct optional

Routing IDs: `topaz_upscale`, `topaz_interpolate`. Official IDs: `topaz/upscale/video/generative`, `topaz/interpolate/video`, `apo-8`. Status: **verified**.

fal video_url; upscale model='Starlight Precise 2.6',upscale_factor,target_fps,softness; interpolation model Apollo/Chronos/Aion,target_fps,slowdown_factor. Direct Apollo=apo-8,slowmo,fps. [Official API source](https://fal.ai/models/topaz/upscale/video/generative/api) [Official API source](https://fal.ai/models/topaz/interpolate/video/api) [Official API source](https://developer.topazlabs.com/video-models/frame-interpolation/apollo)

Starlight 10s30fps USD1.20<=1080p,2.60at4K; Apollo/Chronos10s30to60fps USD0.30at1080p,0.60at4K. Frame-rate/slowdown affects cost; direct dollars per credit TODO. [Official pricing](https://fal.ai/models/topaz/upscale/video/generative)

commercial API, fal Commercial use. `training_eligible=false`: fal third-party competing-model training restriction.. [Licence/terms source](https://fal.ai/models/topaz/interpolate/video)

### Google Gemini3.8 Flash — Gemini Developer API paid

Routing IDs: `gemini_vlm_judge`. Official IDs: `gemini-3.8-flash`. Status: **verified**.

Text/Image/Video/Audio/PDF inputs, text output, structured output supported; video/keyframe judge needs branch schema. [Official API source](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)

Standard paid USD/1M tokens input0.75,output3.75 through2026-12-31; from2027-01-01 input1.50,output7.50. Batch half. Model-output cost depends on video/keyframe tokens. [Official pricing](https://ai.google.dev/gemini-api/docs/pricing)

proprietary Gemini API terms; API model licence is distinct from documentation CC-BY/Apache sample licences. `training_eligible=false`: No clear permission for output model-training verified.. [Licence/terms source](https://ai.google.dev/gemini-api/terms)

Pending eval-gated alternative; local_qc remains continuity default.

### Remotion and in-house NLE exporter — customer AWS Lambda / local exporter

Routing IDs: `remotion_render`, `remotion_nle_export`. Official IDs: not a model API. Status: **built, not model APIs**.

Existing repo contracts unchanged; no new adapter. [Official API source](https://www.remotion.dev/docs/license) [Official API source](https://www.remotion.dev/docs/lambda)

Remotion licence and AWS compute charges depend on organization/render settings; no invented fixed render charge. [Official pricing](https://www.remotion.dev/docs/license)

Remotion commercial licence; in-house exporter repo licence. `training_eligible=false`: No generated model-output training policy needed; retain existing repo policy.. [Licence/terms source](https://www.remotion.dev/docs/license)

### HyperFrames — local dry-run renderer

Routing IDs: `hyperframes_render`. Official IDs: not a model API. Status: **built, flag-gated explicit-only**.

Existing repo tool unchanged. [Official API source](https://github.com/heygen-com/hyperframes/blob/main/LICENSE)

Local runtime compute; hosted HeyGen HyperFrames rate TODO unknown, not adopted. [Official pricing](https://developers.heygen.com/llms.txt)

Apache-2.0 code. `training_eligible=false`: Code licence does not blanket-authorize source media use.. [Licence/terms source](https://github.com/heygen-com/hyperframes/blob/main/LICENSE)

### ElevenLabs Instant Voice Cloning — ElevenLabs direct

Routing IDs: `voices_ivc_create`. Official IDs: not a model API. Status: **verified built endpoint**.

POST /v1/voices/add multipart name/files required; optional remove_background_noise,description,labels; returns voice_id,requires_verification. Require subject rights and consent. [Official API source](https://elevenlabs.io/docs/api-reference/voices/ivc/create) [Official API source](https://elevenlabs.io/docs/eleven-creative/voices/voice-cloning/instant-voice-cloning)

API pricing Starter and above includes Instant Voice Cloning; standalone per-create charge not published. Keep existing billing policy or TODO unknown. [Official pricing](https://elevenlabs.io/pricing/api)

paid commercial API; explicit rights and consent required for source voice. `training_eligible=false`: No permission to export a clone or train a separate model verified.. [Licence/terms source](https://elevenlabs.io/docs/eleven-creative/voices/voice-cloning/instant-voice-cloning)

### SigLIP and DINOv2 continuity embeddings — existing RunPod worker / local

Routing IDs: `local_qc`. Official IDs: `google/siglip-so400m-patch14-384`, `facebook/dinov2-base`. Status: **official upstream model families verified; deployed config unchanged**.

Existing in-house embeddings/QC contract; no new adapter or remote API. [Official API source](https://huggingface.co/google/siglip-so400m-patch14-384) [Official API source](https://huggingface.co/facebook/dinov2-base) [Official API source](https://github.com/facebookresearch/dinov2/blob/main/LICENSE)

Compute depends on existing worker deployment; no fixed model-generation rate. [Official pricing](https://huggingface.co/facebook/dinov2-base)

Apache-2.0 weights/model metadata, DINOv2 Apache-2.0 code. `training_eligible=false`: Retain existing QC policy; model licence alone does not authorize training on user source media.. [Licence/terms source](https://huggingface.co/facebook/dinov2-base)

## Thin evidence and activation TODOs

- Eleven v4 Turbo ID is verified, but its public docs describe WebSocket Text-to-Dialogue. Existing HTTP TTS/dialogue compatibility is **UNVERIFIED**. Every existing HTTP speech variant defaults its model via `ELEVENLABS_TTS_MODEL=eleven_v4_turbo` and forces dry-run for that ID even when ELEVENLABS_DRY_RUN=false. A verified HTTP model can be configured explicitly. Its published WebSocket price is not installed as an HTTP billing quote; HTTP estimates remain unknown without operator rates.
- Future provider branches must enforce typed args before paid requests, submit/poll correctly, add explicit price unit/expiry handling and validate host eligibility/licence/subject consent before live activation. The original capability-map branch required no new credentials. Sync reuses FAL_KEY; its optional authorized direct transport needs SYNC_API_KEY.
- HeyGen and Mureka direct prices, direct Kling/Topaz prices, some model-specific training rights and direct Sync/HeyGen US eligibility remain TODO/unknown. Mureka n defaults to two songs and Mirelo num_samples defaults to two; estimate the exact requested count before submitting.
- New SaaS aliases are not training eligible: commercial output rights alone do not grant competing-model training rights. Existing Wan2 Apache/provenance training-flywheel behavior is preserved; host service terms still need review on any new training host.
- Continuity remains local_qc. Gemini judge is pending and eval-gated. The research lead requires >0.85 agreement on 420 paired evaluations before replacement; no evaluations are claimed here. Omni/Flash and Vidu motion candidates remain inactive until evidence justifies a decision.
- Retired aliases: Veo, Hedra Character3, LatentSync, LivePortrait, InfiniteTalk, SeedVR2, RIFE, ACE-Step and MMAudio. MMAudio weights are CC-BY-NC-4.0, blocked for commercial use ([official model](https://huggingface.co/hkchengrex/MMAudio)). No AGPL or non-commercial code/weights are copied or activated. Retired aliases have no dispatch binding.

## Skills and routing fixtures

There are 24 packaged skills, 13 provider targets and 99 Gateway tools. No deployment is claimed. New packaged skills are image-gen, named-provider, act-two, lipsync, upscale, lyrics-video, product-demo-video and whiteboard-explainer. Vidu’s archived skill is removed; its real tools remain under named-provider. Draft alias include_tools cannot be copied verbatim into this harness: `metadata.include_tools` must contain real dispatch wrappers, `metadata.routing_tools` records the canonical aliases, and `metadata.gateway_tools` contains only built Gateway names.

The original workbook migration retained 122 fixtures; later provider branches expanded the set to 129. There are now 103 active cases and 26 skips, including one unverified extension-semantics case and 25 named dependencies. The 23 archived/confidential rows remain dropped. “Active” includes built interims and the required 45-second single-shot refusal; it does not assert future adapters exist. NLE import remains skipped. Detailed expectation adjustments and retired replacements are in [capability-map-decisions.tsv](capability-map-decisions.tsv).

| Skipped dependency/reason | Rows |
| --- | --- |
| provider pending: HyperFrames overlays (feat/hyperframes-overlays) | 1 |
| provider pending: cutaway_record (feat/product-demo-capture) | 3 |
| provider pending: gemini_vlm_judge (feat/continuity-qc-vlm-judge) | 1 |
| provider pending: ideogram45_edit (feat/image-specialists) | 2 |
| provider pending: kling_motion_control (feat/perf-transfer) | 2 |
| provider pending: mirelo_v2a (feat/sfx-mirelo) | 3 |
| provider pending: mureka_lyrics_video (feat/provider-mureka) | 3 |
| provider pending: nle import (feat/nle-import-fcpxml) | 1 |
| provider pending: recraft_v41_vector (feat/image-specialists) | 4 |
| provider pending: runway_act_two (feat/perf-transfer) | 5 |
| semantics unverified: Seedance appended-versus-combined extension length (feat/seedance-2-5); Wan extend remains preview-licence blocked | 1 |

## Verification

The original capability-map branch recorded **792 tests run, 748 passed, 44 skipped**; Ruff, offline CI packaging and Studio TypeScript typecheck pass. Gateway schemas regenerated without changes. That branch added no dry-run flags or secrets; optional `ELEVENLABS_TTS_MODEL` is the one new runtime config key.

Offline tests exercise deterministic routing, native Deep Agents interrupt/resume/reject in fresh workers, disclosure and billing guards, training provenance, fixture expectations, schema/inventory checks and dry-run provider dispatch. Comet browser E2E is **blocked**: user reports Comet is unavailable in this environment. No browser actions, live generation, artifact playback or authenticated paid provider calls are claimed.

Read [SKILLS.md](SKILLS.md), [DEEP_AGENT.md](DEEP_AGENT.md) and the [decision trail](capability-map-decisions.tsv) for the runtime and migration details.

## Seedance 2.5 upgrade evidence

The three dialogue exceptions and both edit/extend interims now bind built Seedance Gateway
tools. Fal's reference endpoint explicitly supports `task=editing` and `task=extension`.
The default host is fal US; global endpoints retain separate verified rates. Adaptive prices
need measured source aspect and never assume unknown dimensions. BytePlus video-input
estimates remain UNVERIFIED until its minimum-token floor is available.
See [the provider reference](SEEDANCE_2_5.md) and [decisions](seedance-2-5-decisions.tsv)
for official URLs read 2026-10-09, authorization, watermark limits and blocked Comet E2E.
