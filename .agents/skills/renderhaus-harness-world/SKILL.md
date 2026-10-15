---
name: renderhaus-harness-world
description: Repository facts for building offline Renderhaus harness evaluations with real graph execution and mocked providers.
---

Use `agent/deep_agent/runner.py::run_with_servers` as the harness boundary. Native interruptions need the same checkpoint scope and interrupt IDs on resume. `GatewayExecutor` owns paid dispatch, approval, schema validation and provider policy.

Create isolated job directories under a temporary `RENDERHAUS_MEDIA_DIR`. Local transforms use the Linux isolation backend. Inspect the resulting bytes and metadata independently. Provider dry-run results are input previews and cannot prove delivered media.

The Studio database environment variable is `RENDERHAUS_STUDIO_DATABASE`. Set it before imports, then replace the worker repository with a per-trial instance. Keep the virtualenv interpreter path intact: resolving its symlink selects the base Python and can lose installed dependencies.

When comparing older runners, retain their existing fixed ffmpeg operations as fallbacks. Use plain fixture notes when appending file context to requests; quoted JSON can change the dialogue intent heuristic. Provider transport must remain mocked and networking denied even when quote flags are enabled for a cost stimulus.

Separate deterministic protocol checks from semantic model quality. Mock model token bounds and dollar estimates are not measured live usage. Comet browser validation remains a separate required product check.

Freeze source before scored runs. Retain and replace outcomes from superseded fingerprints, then rescore the final evidence. Calibrate temporal media checks against wrong outputs with plausible duration, such as a trimmed clip presented as a speed change or a constant frame presented as a boomerang.

This skill is an unreviewed initial record derived from source and local tests. Task-specific prompts and scoring stay in `evals/harness-v2/Task.md` and `cases.json`.
