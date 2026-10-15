# Preview a finishing pass before the full job

Studio prepares a sample of at most three seconds, processes that sample with the existing
finishing tool, and asks the customer to compare it before proposing full processing.
The sample retains the source dimensions and frame rate before enhancement. A duration
field alone never trims the source submitted to the provider.

The customer sees original and enhanced videos with linked playback and scrubbing. They
can choose side-by-side playback or switch between A and B. Both saved videos must load
and play before the continue action becomes available. A broken video leaves **Keep
original** available. Customer copy uses neutral labels and contains no vendor names or fees.

## Agent workflow

1. Read the `upscale` skill and run continuity QC. Discover the selected Topaz schema.
2. Call native `prepare_finishing_preview(tool_name, arguments, start_seconds,
   duration_seconds)`. Use an owned source version and the requested full settings.
   The default sample duration is three seconds. The host measures the original, supplies
   omitted source measurements, rejects conflicting supplied measurements, creates a real
   sample, and registers it as an owned asset version.
3. Submit the returned `preview_arguments` to the existing selected Gateway tool. This
   paid preview requests its own cost approval, including in autonomous mode.
4. Save the provider job ID and poll `Topaz___get_video_task` with `download=true`.
   Queued, failed, dry-run, unmeasured, or missing output cannot reach visual review.
5. Call native `review_finishing_preview(preview_id)`. Its arguments contain no
   model-authored comparison or claimed approval. The host builds the comparison from
   the saved files. Accepting the visual review authorizes no spending.
6. After acceptance, submit `full_arguments`. The existing full-job cost approval still
   applies. Changes to the source or settings require a new preview and review.

If the sample covers the entire source, accepting it keeps the processed sample as the
full artifact. The host blocks a second identical paid job. A partial sample never completes
a longer-source request. Final artifacts still need playback inspection, and delivery-render
workflows retain their existing saved QC report and checksum requirements.

## State and policy

`FinishingPreviewGate` owns preview state in the executor's scoped conversation snapshot.
It binds source, sample, full processing arguments, and saved output checksums. The native
approve/reject interrupt uses the installed Deep Agents 0.7.23 middleware and the existing
checkpoint and resume mechanism. Rejecting the review blocks the full request. Replay and
restart use the stored job rather than creating a replacement paid job.
Native tool execution requires the actual host review decision, bound to the comparison.
Middleware eligibility alone grants no authority. A finishing dispatch similarly requires
its own host spending decision. If another tool makes a batched action eligible after
middleware checks, the action returns without running and requests a fresh approval call.
The latest sample for the same full request controls approval. An older accepted sample
cannot override a newer rejection. A failed or rejected sample retains its state when
prepared again with the same range and settings. A customer-requested replacement needs
a different sample range or revised settings. This change adds no same-sample retry control.

The preview gate adds two native tools and no provider or Gateway endpoint. Starlight
Precise 2.6 on fal remains the upscale default. Apollo remains the interpolation default,
and the Chronos linear-motion exception still follows explicit requests. Unknown quotes,
including slow-motion pricing, remain unknown and block live processing. No new secrets,
approval exemptions, autonomous spending limits, or routing tiers are introduced.

## Sources and licence

The workflow pattern comes from
[DreamLoveBetty/topaz-video-skill](https://github.com/DreamLoveBetty/topaz-video-skill),
whose [MIT licence](https://github.com/DreamLoveBetty/topaz-video-skill/blob/main/LICENSE)
was read 2026-10-15. This implementation adapts the workflow concept without copying its
code. The upstream skill controls a licensed local Mac application and excludes Starlight.
Renderhaus continues to use its hosted finishing adapter. No local application bridge,
model weights, AGPL code, or non-commercial dependency is added.

These official sources were rechecked 2026-10-15. Existing rates remain as originally
recorded on 2026-10-09 in [Topaz finishing](TOPAZ.md).

| Fact | Official source |
| --- | --- |
| Whole-video input, Starlight Precise 2.6 default, scale, FPS, softness, H264 fields | [fal upscale API](https://fal.ai/models/topaz/upscale/video/generative/api) |
| Apollo and Chronos model values, target FPS, slowdown, H264 fields | [fal interpolation API](https://fal.ai/models/topaz/interpolate/video/api) |
| Starlight 10 s examples of $1.20 at 1080p30, $2.60 at 4K30, $2.40 at 1080p60, $5.10 at 4K60 | [fal upscale pricing](https://fal.ai/models/topaz/upscale/video/generative) |
| Apollo and Chronos 10 s 30-to-60 examples of $0.30 at 1080p and $0.60 at 4K | [fal interpolation pricing](https://fal.ai/models/topaz/interpolate/video) |
| Direct identifiers `slp-2.6`, `apo-8`, `chr-2` | [Starlight](https://developer.topazlabs.com/video-models/starlight/starlight-precise-2.6), [Apollo](https://developer.topazlabs.com/video-models/frame-interpolation/apollo), [Chronos](https://developer.topazlabs.com/video-models/frame-interpolation/chronos) |
| Commercial hosted integration and input permissions | [fal Terms of Service](https://fal.ai/legal/terms-of-service), [fal API Services](https://fal.ai/legal/api-services) |

Model policies retain `license=service-terms`, `weights_license=closed-weights`, and
`training_eligible=false`. The sample does not grant new face, voice, or media rights.
Visual quality evidence remains vendor supplied. No live quality improvement is claimed.

## Validation limits

Offline verification uses local video files, real FFmpeg measurement and clipping, scripted
native graph runs, and mocked provider transport. RT-194 verifies the default routing choice.
These checks do not establish browser E2E or live provider success.

Comet control is unavailable in this session, and live or paid calls are explicitly excluded.
The real Studio preview, visual review rejection, separate full-job cost approval, and
generated-artifact playback remain pending. Evidence and the blocked report belong under
ignored `.renderhaus/e2e/`. See [browser E2E](BROWSER_E2E.md).
