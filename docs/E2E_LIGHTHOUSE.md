# Lighthouse operator driver

`scripts/e2e_lighthouse.py` runs the lighthouse brief through `run_studio_agent`,
the selected Deep Agents manager and roles, and an embedded loopback
`scripts/local_gateway.py` server. Discovery exposes only
`x_amz_bedrock_agentcore_search`; paid dispatch uses the discovered provider
schemas, existing approval/resume flow and typed provider contracts.

The default command writes a plan without constructing a model, starting the
Gateway or invoking providers:

```bash
.venv/bin/python scripts/e2e_lighthouse.py \
  --out .renderhaus/e2e/lighthouse-plan
```

The output directory must be empty. Use a new directory for every attempt.
The default spend cap is $5. No live run was performed while implementing this
branch; all model/provider boundaries in the tests are fake.

## Operator live run

An operator with an existing authorized Anthropic key and provider credentials
can explicitly enable one run. Keep secrets in the process environment or the
existing application secret, never command arguments or output files.
The driver does not load a Secrets Manager secret automatically.

```bash
RENDERHAUS_AGENT_MODEL=anthropic:claude-sonnet-5-5 \
FAL_DRY_RUN=false ELEVENLABS_DRY_RUN=false REMOTION_DRY_RUN=false \
  .venv/bin/python scripts/e2e_lighthouse.py \
  --live --spend-cap-usd 5 --out .renderhaus/e2e/lighthouse-sonnet55
```

`--live` authorizes the driver to approve quoted steps within the cap. It leaves
other provider dry-run settings intact. The embedded Gateway is bound to
loopback and is closed after the run. Local assembly needs ffmpeg and ffprobe.
The driver sets the local media directory beneath `--out`; provider-generated
artifacts must be available there before assembly. Existing per-role model and
effort overrides still apply. The driver accepts only Anthropic models with
verified token rates and text-only model input. Multimodal inputs fail before a
model call because hidden vision tokens would invalidate its reservation.

## Spend and retry behavior

The shared budget counts completed model usage, model reservations, paid media
attempts and in-flight media reservations. Model input uses a conservative UTF-8
byte bound plus framing, priced at the highest published cache-write rate; each
call also reserves its maximum output. Approval batches include earlier pending
approvals when checking the cap. The Gateway checks the budget again immediately
before provider dispatch. Unknown prices, exhausted budgets and unmetered model
results stop paid work. Provider failures and cancellation keep their quoted
charge, since an accepted request may still be billed.

The driver permits one paid video-generation attempt and one speech attempt,
including provider substitutions or changed prompts. It does not retry failed
agent calls. Anthropic SDK retries are disabled; searches and polling of the
original job remain available. A failed or interrupted run requires operator
reconciliation with vendor history before any new live run. The cost fields are
published-price estimates, not provider invoices.

`--max-output-tokens` defaults to 4096, `--max-turns` to 40 and
`--timeout-seconds` to 1800. Reaching a limit records an incomplete run.
Tracing is disabled in both legacy/V2 environment settings and the LangSmith
execution context. JSON and text records strip credential fields and signed URL queries.

## Outputs and completion

The driver writes `agent_events.jsonl`, `gateway_ledger.jsonl`, `summary.json`
and, after a delivered artifact, `final.json`, `final.mp4`,
`final.ffprobe.json` and `final.ffprobe.txt`. The probe files are sanitized.
The summary includes model, per-model token counters, model cost, per-step
media estimates, total, outstanding reservations, wall time, fps and bitrate.
Startup errors and missing artifacts also produce a failed summary.

Completion requires an actual local MP4 with positive duration, video and audio
streams, and a successful complete ffmpeg decode. A provider acceptance, dry-run
or queued job cannot report completion. A decode verifies playback integrity;
it does not judge narration quality or prove browser delivery.

The offline tests exercise the actual loopback MCP transport, search, approval
resume and artifact validation with a fake agent and mocked provider dispatch.
They also cover cap rejection, parallel reservations, paid failures/cancellation,
retry prevention, cache pricing, unknown usage, tracing and sanitized evidence.

Comet browser E2E is blocked in this environment. This command is an operator
API-path check and does not satisfy [browser validation](BROWSER_E2E.md).
