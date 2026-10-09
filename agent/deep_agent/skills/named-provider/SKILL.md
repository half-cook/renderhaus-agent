---
name: named-provider
description: Honor explicit Kling, Runway, Luma, Vidu, Seedream, Fish or Wan VACE requests with disclosure.
metadata:
  include_tools: call_media_tool call_audio_tool
  routing_tools: kling_t2v kling_i2v runway_gen45_t2v runway_aleph_edit luma_ray3_t2v luma_ray3_modify vidu_q4_i2v vidu_q4_r2v seedream_t2i fish_audio_tts wan_vace_edit
  gateway_tools: ElevenLabs___music_compose Fal___get_video_task Fal___image_to_video Fal___list_fal_models Fal___reference_to_video Fal___text_to_video Fal___video_to_video Fal___vidu_q4_i2v Fal___vidu_q4_r2v FishAudio___generate_speech Kling___get_video_task Kling___image_to_video Kling___list_kling_models Kling___omni_video Kling___text_to_video Luma___extend_video Luma___get_video_task Luma___image_to_video Luma___list_luma_models Luma___modify_video Luma___text_to_video Runway___get_runway_task Runway___image_to_image Runway___image_to_video Runway___list_runway_models Runway___text_to_image Runway___text_to_video Runway___video_to_video Seedream___image_to_image Seedream___text_to_image
---

# Named provider

These built providers remain available through explicit requests. Their generation/edit/image tools
are `explicit_only`; unnamed requests follow the capability map. Disclose
`explicit request; not the default for <capability>` with provider, model and estimate.
An exception's name, such as Runway Act-Two or Kling Motion Control, stays in its specialist skill.
Wan 3.0 naming means the capability default; Wan 2.x VACE naming means these legacy tools.

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
