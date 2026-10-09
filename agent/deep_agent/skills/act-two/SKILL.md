---
name: act-two
description: Transfer facial or upper-body acting with Runway Act-Two, or full-body motion with Kling 3 Pro Motion Control. Process long performances in sequential shot or silence chunks and assemble them.
metadata:
  include_tools: call_media_tool call_editor_tool
  routing_tools: runway_act_two kling_motion_control remotion_render
  gateway_tools: Runway___act_two Runway___get_runway_task Fal___kling_motion_control Fal___get_video_task Remotion___render_timeline Remotion___get_render_progress
---

# Performance transfer

Use the explicit requested provider first. Otherwise use Kling for full_body_motion,
whole-body motion or dance. Use Act-Two for facial_performance and upper-body acting.
Cost never selects the model. A project.confidential field has no routing effect.
Generation tools remain explicit-only and do not implement performance transfer.
There is no neutral benchmark for these choices. A/B visual evidence is still pending.

Identify every real face, body and voice in both inputs. Obtain the user's consent
acknowledgement before setting subjects and consent_confirmed=true. Spending approval alone
is not likeness consent. Synthetic characters still require rights to the driving performance.
Both paid tools always pause with estimated cost, including autonomous runs.
Disclose the host, model, default or exception reason, consent and price before dispatch.
Neither tool's output is training eligible.

## One clip

Discover the exact Gateway schema before dispatch.
Runway___act_two requires character_uri, performance_uri, measured performance_duration_seconds,
subjects and consent_confirmed. character_type is image or video. The performance must be 3-30s.
body_control defaults true. expression_intensity is 1-5, default 3. Use a documented pixel ratio.
Character video requires body_control=false and retains its own body/camera movement.
Single subject, visible face and starting pose alignment help performance capture.
Wait for Runway___get_runway_task with the saved job_id at least five seconds apart.
Use download=true to retain the completed output before its provider URL expires.

Fal___kling_motion_control requires image_url, video_url, measured performance_duration_seconds,
subjects and consent_confirmed. character_orientation=video supports 3-30s and is the default
for full-body movement. image orientation supports only 3-10s. keep_original_sound defaults true.
Optional prompt guides the appearance. Facial element binding is not exposed in this adapter.
Poll Fal___get_video_task with the exact job_id and download=true. No direct Kling credentials
are used for this fal transport.

## Long Act-Two performances

A whole-take route over 30s blocks direct submission and asks for supported chunks.
Use known shot or silence timestamps, never arbitrary cuts through speech or acting.
If boundaries are unknown, request timestamps before paid work. Every chunk must be 3-30s,
sorted, contiguous and cover the intended take. Merge a short tail into its previous chunk
only if the combined length remains within 30s. Otherwise require another suitable boundary.

For each chunk, supply the original hosted performance_uri, measured source_duration_seconds,
performance_start_seconds, the chunk length as performance_duration_seconds, and boundary_kind
shot or silence. The adapter measures the source, trims locally, verifies the chunk and uploads
it before the paid request. This requires ffmpeg, ffprobe and a source host in
REMOTION_LOCAL_MEDIA_HOSTS. If these dependencies are unavailable, refuse long-take processing
with the returned concrete reason. An existing Runway upload URI cannot be trimmed locally.

Submit and approve only the first chunk. Poll and download it to terminal success before
requesting approval for the next chunk. A failed or rejected chunk stops the sequence.
Polling never submits another paid task. Keep a manifest in agent files containing source
offsets, durations, job IDs and saved output paths. Do not put credentials or signed URLs there.
Use the same character, ratio, expression and body controls throughout the take.

After every chunk succeeds, call Remotion___render_timeline with ordered video visuals.
Each visual uses its saved output_path, its chunk duration and a cumulative start_seconds.
Use source_in_seconds=0 and transition=cut. Retain audio with volume=1 when wanted.
Poll Remotion___get_render_progress to save the final MP4. Rendering has its existing approval
and compute quote. Do not call generation again to concatenate or check status.

Inspect face, pose and temporal continuity with continuity-qc. Open/play the saved final MP4.
A queued task or dry-run is incomplete media. Record customer acceptance or rejection through
record_media_outcome using the saved call ID. Spending approval is separate from visual review.

Official request, pricing and service terms were read 2026-10-09. Runway costs 5 credits/s
at $0.01/credit. Fal Kling Pro costs $0.168/s. Use host billing estimates including the existing
platform fee. Fractional billing and live account availability still need invoice validation.

Sources include https://docs.dev.runwayml.com/api/,
https://docs.dev.runwayml.com/guides/pricing/,
https://runway.com/terms-of-use,
https://fal.ai/models/fal-ai/kling-video/v3/pro/motion-control/api and
https://fal.ai/legal/terms-of-service.
