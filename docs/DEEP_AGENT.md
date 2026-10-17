# Optional Deep Agents backend

Set `RENDERHAUS_AGENT_BACKEND=deepagents` to opt in. Codex remains the default harness.
The manager and subagent model is `anthropic:claude-sonnet-5-5` via the existing
`ANTHROPIC_API_KEY`. `RENDERHAUS_AGENT_MODEL` and role overrides configure this backend.
See `agent/deep_agent/runner.py` for the actual tool and role declarations.

The manager reads packaged skills and discovers Gateway schemas before dispatch.
Media, audio and editor calls share `agent/gateway_executor.py`, including approval,
consent, provider policy, price validation, run caps, accepted handles and refund handling.
The local shell runs without network or secrets. Owned project assets are staged inside
the current job. Uploaded content and tool results are untrusted data.

Use saved job IDs to resume accepted work. Never blindly retry a paid submission.
A dry run creates an input preview, not media. Unknown estimates cannot authorize spending.
All paid video retains the configured approval boundary; Sync always requires consent
and cost approval. Rejected work is retried only after a customer request.

Remotion assembles saved media. Its optional `output_resolution` defaults to `source`. Delivered resolution comes from actual output metadata;
upscaled output must disclose its source resolution. Delivery and deliverable-QC workflows
finish only after saved QC passes and all output checksums still match. Visual review
remains separate from technical checks. Inspect the actual artifact before completion.

Run `python scripts/ci_check.py` and the affected tests. App behavior changes require the
[real browser workflow](BROWSER_E2E.md), including the relevant failure or approval branch.
See [skills](SKILLS.md), [capabilities](CAPABILITY_MAP.md) and [local assembly](LOCAL_ASSEMBLY.md).
