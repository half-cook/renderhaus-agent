---
name: named-provider
description: Honor explicit provider requests, including Pixelcut loops, PixVerse VibeMV and preview-blocked Wan edits, with disclosure.
metadata:
  include_tools: call_media_tool call_audio_tool
  routing_tools: pixelcut_looping_video pixverse_vibemv wan3_edit wan3_extend kling_t2v kling_i2v runway_gen45_t2v runway_aleph_edit luma_ray3_t2v luma_ray3_modify vidu_q4_i2v vidu_q4_r2v seedream_t2i fish_audio_tts wan_vace_edit
  gateway_tools: Fal___pixelcut_looping_video Fal___pixverse_vibemv ModelStudio___edit_wan3_video ModelStudio___extend_wan3_video ModelStudio___get_task ElevenLabs___music_compose Fal___get_video_task Fal___image_to_video Fal___list_fal_models Fal___reference_to_video Fal___text_to_video Fal___video_to_video Fal___vidu_q4_i2v Fal___vidu_q4_r2v FishAudio___generate_speech Kling___get_video_task Kling___image_to_video Kling___list_kling_models Kling___omni_video Kling___text_to_video Luma___extend_video Luma___get_video_task Luma___image_to_video Luma___list_luma_models Luma___modify_video Luma___text_to_video Runway___get_runway_task Runway___image_to_image Runway___image_to_video Runway___list_runway_models Runway___text_to_image Runway___text_to_video Runway___video_to_video Seedream___image_to_image Seedream___text_to_image
---

# Named provider

These built providers remain available through explicit requests. Their generation/edit/image tools
are `explicit_only`; unnamed requests follow the capability map. Disclose
`explicit request; not the default for <capability>` with provider, model and estimate.
An exception's name, such as Runway Act-Two or Kling Motion Control, stays in its specialist skill.
Wan 3.0 generation uses the generation defaults. Wan 3.0 edit/extend or Model Studio naming
uses the preview adapter below. Wan 2.x VACE naming means the legacy tools.

Explicit "use Pixelcut looping video" selects `Fal___pixelcut_looping_video` on fal.
Supply `image_url` (JPEG/PNG/WebP); optional `prompt` is at most 4000 characters.
Integer `duration` is 5–15 seconds (default 5), `resolution` is 480p/768p/1080p
(default 1080p), `motion` is subtle/spin (default subtle), and `include_audio` defaults false.
Pixelcut is never the automatic product-loop or spin choice. Do not send a model argument.

Explicit "PixVerse VibeMV" or "VibeMV" selects `Fal___pixverse_vibemv` on fal.
Supply an authorized MP3/WAV `audio_url` and its measured `audio_duration_seconds`, 10–360.
The measured duration is a local pricing field; do not infer it from a requested video length.
Optional `image_url` anchors a character; `style_image_url` requires `style="Custom"`,
and Custom requires that reference. Use exact style/music_style values from Gateway's schema.
Optional `lyrics` is at most 5000 characters. `lip_sync_switch` defaults false, safety checking
true, `resolution` 720p (1080p supported), and `aspect_ratio` 16:9 (9:16, 1:1, 4:3, 3:4 supported).
Use owned/licensed music, lyrics and images. Real face/voice inputs require their corresponding
`real_face_refs`/`real_voice_refs` flags and explicit `likeness_consent=true` for every subject.
An unnamed music or lyrics video follows the capability default; never substitute VibeMV.

Both are `explicit_only`, commercial hosted service models with `training_eligible=false`.
Default `FAL_DRY_RUN=true` previews only. Always disclose the provider/model and host estimate,
and pause for cost approval even in autonomous runs or with premium approval disabled.
Pixelcut bills output seconds; VibeMV bills measured audio seconds rounded up to whole seconds.
Host quotes include the existing platform fee. Missing measurements mean unknown cost and a blocker.
Submit once and poll `Fal___get_video_task` with `download=true`. Play the saved MP4, check
Pixelcut's loop seam or VibeMV's music/lyrics alignment, and preserve actual output dimensions.
Queue acceptance is incomplete media. These outputs never enter the training flywheel.
See docs/providers/named-fal-video.md for verified sources and current validation limits.

Explicit "use Wan to edit this clip", "Wan 3.0 edit", "Model Studio edit" or named extension
requests use `wan3_edit` or `wan3_extend`, mapped to `ModelStudio___edit_wan3_video` and
`ModelStudio___extend_wan3_video`. Warn that Alibaba preview terms permit internal testing
only until GA; live customer use remains preview-blocked, even with spending approval.
Disclose that Seedance 2.5 is the permanent edit/extend default. Wan is never a capability
exception, interim or automatic fallback. A future licence change does not restore default routing.

Keep the original asset version. Supply its `video_url` or Studio asset handle, a `prompt`,
measured `source_duration_seconds` from 1 through 15 and measured `source_fps` of at least 16.
Do not invent source measurements. The adapter supports one source video and optional
`reference_image_urls` and `reference_audio_urls`; each audio needs its matching measured
`reference_audio_durations`. References containing real faces or voices need
`real_face_refs=true` and `likeness_consent=true` for permission to use each likeness.

Resolution defaults to `1080p`, audio to true, and aspect ratio to `adaptive`.
Edit `duration=-1` requests source-length preservation. Extend `duration` is the TOTAL target
output length, not the added portion. For a 5-second source extended by 2 seconds, use
`duration=7`, billed as 5 input plus 7 output seconds. Use `direction` forward, backward or
both; it becomes prompt intent, not a vendor request field. Extension requires adaptive ratio.
Input plus output duration cannot exceed 30 seconds. Split longer inputs before submission.
Smart `duration=-1` has an unknown quote and stays dry-run until billing reconciliation exists.
Any future permitted live call requires an explicit integer output duration; extension must
exceed source length. Current preview licensing blocks all live customer use, including
workspace hosts. Explain the internal-evaluation restriction and stop; spending approval
and disabling dry-run cannot override it.

The host defaults to US Virginia prices. `DASHSCOPE_BASE_URL` defaults to the legacy US host,
whose synthesis POST is UNVERIFIED and blocked live. The documented US workspace host can
be configured by the operator. Never alter flags or host settings to bypass a blocked request.
Approval shows input plus total output cost, including the platform fee, even in autonomous runs.

Submit once, save the returned `job_id`, and poll `ModelStudio___get_task` with `download=true`
at least 15 seconds apart. A failed/expired/unknown task is a blocker, not authority to resubmit.
Download the actual MP4 before its 24-hour URL expires and inspect the edit and preserved motion.
Keep continuity-qc on `local_qc`. The model has closed weights, evaluation-only preview licensing and
`training_eligible=false`; customer visual acceptance does not grant training rights.

Preserve the requested operation. Kling text/image tools use `duration_seconds`, `aspect_ratio`,
`resolution` and `generate_audio`. Omni references require real existing element IDs, not inferred
IDs. Runway Gen-4.5 uses `model="gen4.5"`, integer 2-10 second durations and `ratio`.
Aleph uses `Runway___video_to_video`, `model="aleph2"`, `video_path_or_url`, `prompt` and measured
`video_duration_seconds` for a 2-30 second source. Do not send an output duration or deprecated ratio.
Runway images use `gen4_image`; image Turbo requires a source and `gen4_image_turbo` on the reference
operation. Poll `Runway___get_runway_task` at least five seconds apart and retain required attribution.

Luma generation uses `ray-3.2`. Modify accepts a measured 5/10 second source with exactly one input.
Extend needs a completed Luma generation UUID, not an arbitrary clip. See docs/providers/luma.md.
Luma outputs remain ineligible for training/evaluation datasets.

Vidu single-frame animation maps to `Fal___vidu_q4_i2v` with `image_url` and optional `prompt`.
Vidu reference/voice identity maps to `Fal___vidu_q4_r2v` with `prompt`, up to 12
`reference_image_urls` and up to 3 `reference_audio_urls`. Use `audio=true` when R2V needs audio;
I2V audio is implicit. Both use integer `duration` 3-16 and exact `540p`, `720p`, `1080p`, `2K`, `4K`.
Do not send a model argument. Reference IDs in the prompt must match real supplied list positions.
Vidu promo prices expire 2026-11-30; use the host billing estimate and date, not a copied price.
Poll `Fal___get_video_task` with the saved ID. Vidu outputs are not training-eligible.

Wan VACE uses existing Fal video tools with model and native controls. For `Fal___video_to_video`,
provide `video_url` and `edit_mode`. Inpainting takes exactly one mask. Outpainting needs an expansion
side. Reference guidance needs nonempty `ref_image_urls`. Billing uses `num_frames / 16`, independent
of playback FPS. Only priced model/resolution combinations may go live. The training hook's existing
Wan eligibility/rejection rules remain unchanged; a by-name request does not grant training rights.

Seedream uses its built image tools. Fish uses `FishAudio___generate_speech` only when Gateway
exposes that conditional target; otherwise report the absent target. API access grants no Fish
Speech weight licence. An explicit ElevenLabs music request uses `ElevenLabs___music_compose`.
All paid video still pauses in autonomous runs. Poll the selected provider's saved job once submitted.

Veo, Hedra, LivePortrait, InfiniteTalk, SeedVR2, RIFE, MMAudio, ACE-Step, Kandinsky generative video,
HeyGen generative video and fframes are retired. Explain retirement and offer the mapped replacement.
Do not pretend a replacement fulfills the named vendor request. MiniMax H3 and Hunyuan remain blocked.

Follow `read_studio_context.intent_route`. Selection uses the explicit requested provider/model,
then a named exception, then the capability default. Cost estimates support approval and disclosure;
they never select a provider. Pending defaults use only the policy's declared interim tool.
Disclose provider, model, estimated cost and `default`, `exception: <reason>`, `explicit request`,
or `interim default until <provider> lands` before each dispatch. Unknown prices stay unknown.
All paid video pauses for approval even in autonomous runs when `premium_video_approval` is enabled.
Paid non-video retains the existing non-autonomous approval and autonomous spend cap.

Search Gateway for the selected built tool and use its exact schema through the matching role.
Pending aliases are routing identifiers, not Gateway endpoints. Never invent a tool or change a
DRY_RUN flag to satisfy a request. Submit once, preserve the returned job ID, and poll the same job.
A queued job or dry-run is incomplete media. Open/play the actual saved artifact before delivery.
Record explicit customer visual acceptance/rejection with `record_media_outcome` and the saved call ID.
A spending approval is not visual acceptance. Training eligibility follows provenance and the existing
Wan training hook; these routing instructions cannot grant training rights.
