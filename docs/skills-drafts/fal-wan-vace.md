# Route generation and editing to fal Wan VACE

Status: provider built. Explicit-request guidance lives in named-provider; unchanged training guidance lives in continuity-qc.
The named-provider skill and `agent/deep_agent/routing_policy.json` define current routing.
This provider is explicit-only outside its existing training path or declared pending-default interim.

This provider reference informs the installed intent skills. Those skills own live routing.
The authoritative tool and pricing reference is
[FAL_WAN_VACE.md](../FAL_WAN_VACE.md).

Use this provider for Wan VACE text clips, animation from a first frame,
reference-guided subject consistency, and edits that need masks, expansion,
reframing, depth, or pose control. Choose it when the user explicitly requests Wan VACE, or the unchanged host training path selects it. Wan 2.x VACE is explicit-only outside the unchanged training path. Ordinary video uses Wan 3.0
or its declared interim; edit controls alone do not opt into legacy VACE.

## Tool order

1. Call `Fal___list_fal_models` when model availability, endpoint contracts,
   licence, or pricing matters. This is a free static catalog.
2. Select one generation tool and its documented inputs.
   - `Fal___text_to_video` takes `prompt`.
   - `Fal___image_to_video` takes `first_frame_url` and `prompt`.
   - `Fal___reference_to_video` takes a nonempty `ref_image_urls` list and `prompt`.
   - `Fal___video_to_video` takes `video_url` and an `edit_mode`.
3. Use `model="fal-ai/wan-vace-14b"` by default. Use explicit frame count and
   resolution for the quote. Keep the user's action and spending authorization.
4. Submit once. Preserve the entire returned `job_id`, including its endpoint
   prefix. A `dry_run` is terminal and produces no media.
5. Call `Fal___get_video_task` with that `job_id` and `download=true`. Continue
   polling the same job while queued or running. Do not generate again to check
   progress. The current host can wait automatically after an approved poll.
6. On success, use the durable Studio asset version produced from `video_url`.
   Open the actual clip before claiming it is usable. On failure, report the
   error and preserve the job handle. Polling errors do not justify another
   paid submission.
7. For a final video deliverable in the current Studio manager, assemble the
   generated clip with `Remotion___render_timeline` and poll
   `Remotion___get_render_progress`. The current final-video guard requires a
   successful Remotion export. This provider change does not alter that rule.

Studio resolves `renderhaus-asset://<version-id>` inputs to provider-reachable
URLs before Gateway dispatch. Direct provider calls require public HTTP(S) URLs
or data URIs. Use native field names; do not pass local file paths to fal.

## Edit controls

Use `edit_mode="inpainting"` with exactly one mask URL. Use
`edit_mode="outpainting"` with at least one expansion side and optional
`expand_ratio`. Use `edit_mode="reframe"` with `zoom_factor` or `trim_borders`;
its prompt may be omitted. Use `depth` or `pose` with `preprocess` when needed.
Use `freeform` only when native mixed sources are needed; choose its `task`
explicitly. For a masked freeform edit, use `task="inpainting"` and one mask.
Do not send masks, references, or geometry fields to routes that reject them.

The supported frame count is 81 through 241, and FPS is 5 through 30. Reference
images guide consistency; they do not guarantee an identical subject in every
frame. fal does not document a reference-count limit on these API pages.

## Cost and licence rules

Estimate provider cost with the documented unit `num_frames / 16` video seconds,
not `num_frames / frames_per_second`. Wan 2.1 rates for 480p/580p/720p are
$0.04/$0.06/$0.08 per video second. Wan 2.2 inpainting/outpainting/reframe/depth
rates are $0.05/$0.075/$0.10. The existing platform fee applies. Sources and the
2026-10-08 verification date are in the provider reference.

Wan 2.2 freeform and pose, plus auto/240p/360p resolutions, lack an unambiguous
confirmed rate. Live requests for them are blocked. Use a priced combination
or explain the pricing blocker. Do not invent a price, treat pending zero
metadata as free, or substitute a paid model without the user's authorization.
Catalog and polling tools cost zero. Dry runs cost zero and make no HTTP calls.

Results carry `training_eligible=true` and `weights_license="Apache-2.0"` for
the continuity-QC training flywheel. Preserve these fields in tool-result
provenance. fal's hosted-service Terms of Service still apply.

`FAL_KEY` stays server-side in the existing environment/Secrets Manager path.
`FAL_DRY_RUN` defaults to true. Enable live execution only after the operator
configures the key, confirms the quoted combination, and authorizes spending.
Do not request credentials in chat.
