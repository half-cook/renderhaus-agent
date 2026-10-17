---
name: named-provider
description: Honor explicit provider requests, including Pixelcut loops, PixVerse VibeMV, with disclosure.
metadata:
  include_tools: call_media_tool call_audio_tool
  routing_tools: gemini_vlm_judge kling_motion_control pixverse_vibemv pixelcut_looping_video voices_ivc_create eleven_v4_turbo vidu_q4_i2v vidu_q4_r2v seedream_t2i fish_audio_tts wan_vace_edit
  gateway_tools: Gemini___judge_continuity Gemini___get_task Fal___kling_motion_control Fal___pixverse_vibemv Fal___pixelcut_looping_video ElevenLabs___voices_ivc_create ElevenLabs___text_to_speech_convert ElevenLabs___music_compose Fal___get_video_task Fal___image_to_video Fal___list_fal_models Fal___reference_to_video Fal___text_to_video Fal___video_to_video Fal___vidu_q4_i2v Fal___vidu_q4_r2v FishAudio___generate_speech Seedream___image_to_image Seedream___text_to_image
---

# Named provider

Explicit Gemini/VLM continuity review uses `Gemini___judge_continuity` with authorized
keyframe inputs, then `Gemini___get_task` for the saved job. `GOOGLE_API_KEY` supplies access;
`GEMINI_DRY_RUN` defaults true. Use exact discovered schemas. A dry-run or skipped response
contains no verdict. Require the host's cost approval and preserve unknown estimates.
This experimental review is not a validated delivery or training gate. It never grants
training rights. Native visual continuity QC is unavailable.

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
## Performance transfer

Use `Fal___kling_motion_control` for an image plus driving performance video.
Require named subjects and `consent_confirmed=true` separately from cost approval.
The driving clip is 3–30 seconds; image orientation permits at most 10 seconds.
Poll the saved job with `Fal___get_video_task`; never blindly resubmit accepted work.

Explicit Gemini/VLM continuity review is experimental. It is not the default or a delivery-QC pass. Require the existing cost approval, poll the accepted job, and keep unknown estimates unknown.
