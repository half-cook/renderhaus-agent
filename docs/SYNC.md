# Sync lip sync

`Sync___lipsync_video` replaces speech on existing footage through fal's
`fal-ai/sync-lipsync/v3` endpoint. `Sync___get_video_task` polls the saved job.
The transport uses the existing `FAL_KEY`; no separate Sync credential is needed.

Requests require HTTPS video and audio, measured durations and frame rate, a named
subject declaration, and `consent_confirmed=true`. Cost approval cannot supply consent.
Paid submissions always require approval. Unknown models and prices block live work.

`SYNC_DRY_RUN` and `FAL_DRY_RUN` must both be false for live submission. Dry runs
make no media. Long requests require validated shot/silence boundaries, paired media
splitting and durable manifests. Reuse accepted handles; never blindly retry a paid call.
Saved output URLs omit credentials. Completed MP4s are validated and written atomically.

The published estimate uses fal's per-minute rate in `server/billing_rates.py`.
See [fal API contract](https://fal.ai/models/fal-ai/sync-lipsync/v3/api) and
[fal terms](https://fal.ai/legal/terms-of-service).
