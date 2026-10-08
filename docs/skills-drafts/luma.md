---
name: luma-video
description: Generate, animate, extend, or modify video with the direct Luma Ray 3.2 API when the user requests Luma or needs an existing clip restyled.
---

# Luma video

Status: merged. This guidance now lives in the live `t2v`, `i2v` and `edit-v2v` skills and
`agent/deep_agent/routing_policy.json`; this file is kept as the provider reference draft.
Use the provider's Gateway tools. Do not call Luma HTTP endpoints from an agent skill.

## Choose the operation

Route to Luma when the user requests Luma or Ray 3.2, needs start/end image anchors,
wants to extend a completed Luma generation, or wants an existing video restyled.
Use the configured default provider for ordinary requests without a Luma-specific need.
Read [the provider reference](../providers/luma.md) for the tool signatures and limits.

- Use `Luma___text_to_video` for a new video from text.
- Use `Luma___image_to_video` for a start image, an end image, or both. Anchor clips must be 5s.
- Use `Luma___extend_video` with a completed generation UUID and `direction` set to `forward` or `backward`.
- Use `Luma___modify_video` for restyle or edit. Supply exactly one MP4 source or completed Luma generation and its measured 5s or 10s duration. The source aspect ratio and duration are preserved.
- Use `Luma___list_luma_models` when capabilities or model selection are relevant. It is a documented offline catalog and does not prove account access.

The wire model is `ray-3.2`. The current official API has no separate Flash model ID.
Use `360p` draft for cheaper previews. Extend has no confirmed `360p` price and does not accept that option here.
Never invent a model, resolution, duration, or aspect ratio.

## Submit once and poll

1. Check the user's inputs, operation, and spending authorization.
2. Submit the selected tool once and keep its `job_id`.
3. Call `Luma___get_video_task(job_id=..., download=true)` to check that job.
4. Continue polling a pending job without submitting a replacement. Allow video generation time to finish.
5. On `succeeded`, use the persisted output or managed asset. Open or play the artifact before claiming successful delivery when browser access is available.
6. On `failed`, report the provider's `failure_code` and `failure_reason`. A poll transport error does not mean the generation failed.

`queued` and `running` are pending. `succeeded`, `failed`, and `dry_run` are terminal for the host workflow.
A dry run creates no playable video. Report that state accurately.
Do not retry a paid submit after a timeout without checking whether it created a job.
The tools do not expose blocking wait helpers through Lambda.

## Costs and rights

Use `server/billing_rates.py` and the [official API pricing reference](https://docs.agents.lumalabs.ai/guides/pricing/),
checked on 2026-10-08, for quotes. Prices depend on operation, resolution, and duration.
10s generation costs three times the 5s amount. Modify uses its separate edit tier.
Extend bills one 5s block. Polls, model listing, and dry runs are free.
Renderhaus discloses its existing platform fee alongside provider cost.
Do not derive an unconfirmed per-second price for other Modify source lengths.
The detailed API prices differ from some marketing-page edit prices; account invoice verification is pending.
Asynchronous provider refunds are not automatically reconciled by the current Studio submit/poll path.

Treat every Luma output as non-training-eligible. Never put it into continuity-qc training,
fine-tuning, or evaluation datasets, even if the user approves ordinary generation.
Keep `training_eligible=false` on derived media and its provenance.
Commercial use remains subject to the customer's applicable terms and order.
Disclose AI-generated output. Do not promise exclusive rights or unrestricted resale.
The controlling [API terms](https://lumalabs.ai/legal/api-terms-of-use) restrict dataset use and standalone redistribution.
See the provider reference for the [enterprise](https://lumalabs.ai/legal/enterprise-terms-of-service)
and [individual](https://lumalabs.ai/legal/terms-of-service) output-rights conditions.

## Configuration and unavailable dependencies

`LUMA_API_KEY` comes from the server environment or Secrets Manager.
`LUMA_DRY_RUN` defaults true. Never change it to enable spending without the user's authorization.
Do not request credentials in chat or expose them in arguments, outputs, or logs.
When Comet, login, account access, or paid-call authorization is unavailable, record the concrete blocker.
Offline tests and dry runs do not prove live generation or browser E2E success.
