---
name: continuity-qc
description: Compare shots with SigLIP and DINOv2 and gate synthetic continuity training inputs to Apache Wan assets.
metadata:
  include_tools: call_media_tool
  gateway_tools: Fal___text_to_video Fal___get_video_task
---

# Continuity QC

Read `read_studio_context` and identify ordered shot versions and the approved reference.
`local_qc` maps to the local continuity module, not a Gateway tool. Use the offline-testable
`agent.deep_agent.continuity_qc` integration when the host configures it. The agent's
Gateway does not expose an invented `local_qc` endpoint. If embeddings are not configured,
report the check as incomplete rather than making up scores or dispatching QC as generation.

The host can select `CONTINUITY_QC_BACKEND=runpod`; `local` remains the default.
RunPod uses a separate preconfigured Serverless endpoint with baked weights and the same
calibration. Do not create an endpoint, change host settings, or request credentials to
complete QC. Report `status="skipped"` and its reason as an incomplete check, even though
`accepted=False`. A skipped check is not evidence of drift. See
`docs/CONTINUITY_QC_RUNPOD.md` for operator setup and verification limits.

Compare shot appearance using only `google/siglip-so400m-patch14-384` and
`facebook/dinov2-base` embeddings. Models load lazily through optional host dependencies.
Do not download weights, install a heavy package, or call a hosted model to complete a check
without the user's authorization. Tests inject fake embedders and run without downloads.
Report each model's cosine similarity and calibrated probability, the acceptance rule and
threshold from the report, and shot versions. The committed calibration was fitted on film
frames, not Renderhaus generations, so say that the scores are provisional.
An appearance match is not proof of face identity.

Face identity uses a pluggable interface. The default implementation returns
`not configured`, which must remain visible in the QC result. Never load InsightFace or
another face-recognition package as an implicit substitute.
DINOv3 (`facebook/dinov3-vitb16-pretrain-lvd1689m`) can replace DINOv2 in the DINO slot only
when `continuity_qc.dinov3_enabled` is on (default off). It is gated, ships under the DINOv3
Licence (not Apache-2.0) and needs legal review before production use. Never silently
substitute DINOv3 for the configured DINOv2 model; the report names the DINO model used.

Before training, enforce `agent/deep_agent/routing_policy.json` through the continuity
training hook. Accept only approved Wan provenance with both `training_eligible=true` and
`weights_license=Apache-2.0`. Reject forged flags, missing provenance, other models, and
outputs from Vidu Q4, Kling, Runway, Seedance, Seedream, Veo, Luma, MiniMax H3, or Hunyuan.
MiniMax H3 and Hunyuan are blocked or geo-gated and never training-eligible.

For authorized synthetic training previews, `wan_t2v` maps to `Fal___text_to_video`
through `call_media_tool`, using a policy-approved Wan model and a priced request.
Poll the saved ID with `Fal___get_video_task` and `download=true`. Preserve its training
metadata. A queued job, unknown-origin asset, or dry-run is not a training asset.
QC never authorizes a premium generation or unsupported upscale by itself.

Report progress before provider work. Respect DRY_RUN. Never change it to obtain an artifact.
A preview or queued job is not finished media. Required approval appears in the existing chat.
Use the smallest useful request and avoid redundant paid variants.
