---
name: vidu-q4
description: Animate a first-frame image or keep image and voice references consistent with Vidu Q4 on fal, with native audio and resolutions through 4K.
metadata:
  include_tools: call_media_tool
  gateway_tools: Fal___vidu_q4_i2v Fal___vidu_q4_r2v Fal___get_video_task Fal___list_fal_models
---

# Vidu Q4

Read `read_studio_context` and follow the host route. Vidu Q4 is Standard hosted video.
Confidential projects and rejected-artifact retries permit Wan only. Preserve required
features and explain a blocked retry when Wan cannot meet them.
Search Gateway before dispatch and use the returned native schema with `call_media_tool`.
The radar aliases `vidu_q4_i2v` and `vidu_q4_r2v` map to `Fal___vidu_q4_i2v` and
`Fal___vidu_q4_r2v`. Each tool has a fixed endpoint. Do not send a `model` argument.

For a first-frame animation, use `Fal___vidu_q4_i2v` with `image_url` and optional
`prompt` of at most 5000 characters. Native audio is implicit. There is no audio toggle,
aspect-ratio field, end frame, or multi-shot control on this tool.

For subject or voice consistency, use `Fal___vidu_q4_r2v` with a nonempty `prompt`
of at most 5000 characters. `reference_image_urls` accepts up to 12 PNG, JPEG, or WebP
images. `reference_audio_urls` accepts up to 3 MP3 voice clips, each 3 through 12 seconds
and at most 50 MB. Use authorized voices. Refer to images as `[@reference_image_1]`
and voices as `[reference_audio_1]`, with positions matching their lists.
Set `audio=true` for dialogue and sound effects. R2V defaults to `audio=false` and silent
video. Its `aspect_ratio` accepts `16:9`, `9:16`, `4:3`, `3:4`, or `1:1`.
References guide consistency and do not guarantee identity.

Both tools accept integer `duration` from 3 through 16 seconds, default 5.
`resolution` accepts exactly `540p`, `720p`, `1080p`, `2K`, or `4K`, default `720p`.
Retain the case of `2K` and `4K`. Optional `seed` is an integer.
Keep `enable_safety_checker=true` unless the caller has provider authorization to relax it.
Use immutable `renderhaus-asset://` handles for existing media. Studio resolves them at
the provider boundary. External media uses public URLs or base64 data URIs.
I2V supports PNG, JPEG, JPG, and WebP first frames up to 50 MB.

Disclose the host provider/model, tier, filters, and estimate including the platform fee.
Official fal promotional rates expire on 2026-11-30. Later estimates use published list
prices. Audio does not add an R2V surcharge. Unknown quotes remain unknown.
Paid calls pause in non-autonomous mode. Standard Q4 is not a premium target, so an
authorized autonomous run uses the existing spend cap without an extra premium interrupt.
Respect `FAL_DRY_RUN`; never change it. A dry-run previews input and produces no media.

Submit once and preserve the returned `job_id`. Poll `Fal___get_video_task` with that
handle and `download=true`. A queued job is incomplete. Open and play the saved MP4
before claiming completed media. Polling failure does not authorize another paid job.
Record explicit customer review using `record_media_outcome` and the saved generation
call ID. Read [continuity QC](../continuity-qc/SKILL.md) when shot comparisons are needed.
Face identity checks remain incomplete when the host has no configured adapter.

Fal labels these endpoints for commercial use under hosted service terms.
Q4 outputs are never continuity-training inputs. TODO review Vidu's training and output
terms before reconsidering eligibility. Do not infer a weight licence from hosted access.
