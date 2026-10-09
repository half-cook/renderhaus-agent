# Mirelo picture-synchronized SFX

`mirelo_v2a` maps to `Fal___mirelo_v2a` on the existing fal provider. Video-input SFX defaults to Mirelo SFX 1.6. Text-only effects use `ElevenLabs___text_to_sound_effects_convert`. Explicit provider requests take precedence, then the text-only exception, then the default. Attached video versions participate in Studio's route proposal. Confidential project metadata does not change selection. No canonical ID clashes were found.

## Verified contract

Official sources read **2026-10-09**:

- [fal API reference](https://fal.ai/models/mirelo-ai/sfx1.6/video-to-video/api).
- [fal OpenAPI schema](https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=mirelo-ai/sfx1.6/video-to-video).
- [fal model and pricing page](https://fal.ai/models/mirelo-ai/sfx1.6/video-to-video).

The verified endpoint is `mirelo-ai/sfx1.6/video-to-video`. Arguments:

| Argument | Contract |
| --- | --- |
| `video_url` | Required public HTTPS media or an authorized `renderhaus-asset://<version>` handle. Studio resolves handles after approval, before the provider request. Unresolved handles cannot reach live HTTP. |
| `text_prompt` | Optional sound description. Describe footsteps, impacts or ambience rather than visual edits. |
| `duration` | Seconds, 1–60, default 10. Match the measured input duration. Above 10 seconds uses sliding windows. Fractional seconds are supported. |
| `num_samples` | Integer 1–4. Renderhaus explicitly sends 1 by default; fal's schema defaults to 2. Samples 2–4 are dry-run-only until billing is verified. |
| `seed` | Optional integer, -1 through the published maximum 18446744073709552000. Null or -1 selects random generation. |

A strict Pydantic contract rejects invalid controls and extra arguments before any paid request. The queue submit saves an endpoint-qualified job handle. Reuse `Fal___get_video_task` with `download=true`. The official result contains `model: "sfx-1.6"` and a nonempty `video` list of file objects. These are MP4s with audio tracks. This endpoint does not return a separate audio file.

The poll exposes the whole list as `videos`, preserving file metadata, and saves the first variant as the existing `video_url`/`output_path` result. Studio registers that primary artifact. Delivery requires a successful downloaded result and a saved local MP4 or registered video version. A worker-local path alone is insufficient when the agent runs on another host. Queued jobs and dry-run previews are incomplete media. Captions or other assembly requests still require a final render.

## Price and approval

The [official model page](https://fal.ai/models/mirelo-ai/sfx1.6/video-to-video), read **2026-10-09**, publishes **$0.01 per second**. For one requested sample, a 10-second clip costs $0.10 before the existing Renderhaus fee. Billing rounds provider cents upward for fractional durations. Chat approval uses the published cost even in dry-run mode; dry-run ledger charges remain zero.

**UNVERIFIED:** the page does not clearly state billing for multiple samples. Their estimate stays `unknown`, and live submission is blocked before HTTP. No multiplier is invented. Resolve this TODO against official billing documentation before enabling samples 2–4.

Mirelo produces video, so it belongs to the paid-video approval gate. It pauses with provider/model and cost even in autonomous runs when the existing premium-video policy is enabled. The policy's global switch, approval exemptions and autonomous spend cap are unchanged. Direct Studio invocation returns a chat-approval requirement rather than bypassing the gate.

## Licence and configuration

Mirelo is a commercial hosted API, with `service-terms` licence classification and closed weights. Sources read **2026-10-09** are the [commercial model listing](https://fal.ai/models/mirelo-ai/sfx1.6/video-to-video), [fal terms](https://fal.ai/legal/terms-of-service) and [API supplemental terms](https://fal.ai/legal/api-services). US access is inferred from fal's US service provisions; no model-specific region guarantee is published. The fal terms restrict competing-model training. No affirmative general output-training grant was verified, so `training_eligible=false`.

Input media rights and any required likeness/voice consent remain the customer's responsibility under fal's terms. This is sound-effects generation from existing footage, not voice cloning or identity generation. No weights or upstream implementation are copied.

The text-only exception remains the existing ElevenLabs SFX tool. Its [official API](https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert), read **2026-10-09**, accepts `text` at `/v1/sound-generation`, optional 0.5–30 second duration and the `eleven_text_to_sound_v2` model. [ElevenLabs terms](https://elevenlabs.io/terms-of-use), read **2026-10-09**, provide commercial use on paid plans; free-plan outputs are non-commercial. Its existing `training_eligible=false` remains because no output-training grant was verified. This change does not revise its billing rates.

MMAudio remains retired. Its [official checkpoint card](https://huggingface.co/hkchengrex/MMAudio), read **2026-10-09**, declares CC-BY-NC-4.0 weights. Non-commercial weights cannot be used in Renderhaus. No AGPL code is added.

Reuse `FAL_KEY` through env/Secrets Manager and `FAL_DRY_RUN`, default `true`. `scripts/sync_secrets.py` already maps both. There are **no new secrets or environment variables**, and no change to ElevenLabs configuration. CI explicitly sets all existing dry-run flags. Do not disable dry-run to verify this offline branch.

## Validation and quality follow-up

Mocked HTTP tests cover schema boundaries, exact queue bodies, polling/error states, primary artifact saving, unknown multi-sample cost, routing, Studio asset context and native Deep Agents approval/resume/rejection. They use installed deepagents 0.7.23 and no provider keys or network calls. The three Mirelo fixture rows are active; 116 total routing cases are active and 13 retain their dependency or unverified-semantics skips. Inventory is 14 providers, 108 Gateway tools and 24 skills.

Comet browser E2E is **blocked** because no controllable Comet browser is available here. The task also prohibits live provider calls. Generated playback and real synchronization quality remain untested. The ignored `.renderhaus/e2e/` report records the blocker through `scripts/browser_e2e_hook.py`; offline tests are not browser evidence.

Evidence for picture synchronization is thin. Run an approved A/B against text-described ElevenLabs SFX on the same short silent clips. Include footsteps, impacts and ambience, and compare alignment, sound appropriateness, artifacts and preservation of the source video. Record blinded human judgments and actual playback before claiming a quality advantage. No paid A/B was run in this task.
