# Deep Agents harness v2

The Studio runner extends Deep Agents 0.7.23 with local execution and measured review before completion. Gateway dispatch still owns paid work. Provider defaults remain quality-first and explicit customer requests take precedence.

## Execution workspace

`agent/deep_agent/sandbox.py` implements `SandboxBackendProtocol`. The manager and editor receive the SDK `execute` tool. Other roles retain read tools and scoped Gateway dispatch. `StateExecutionBackend` keeps virtual notes in checkpoint state while forwarding execution to `JobSandbox`. `CompositeBackend` routes `/skills/` to packaged skills and `/work/` to the current job's files. SDK permissions deny writes to both routes.

Each command runs in bubblewrap with separate user, PID, mount and network namespaces. The environment is built from an allowlist. Provider keys, AWS configuration, project source and browser sessions are absent. The runtime mounts `/usr` and selected runtime configuration read-only. The job input snapshot is read-only at `/input`. Shell writes use a bounded tmpfs at `/work`; root and `/dev` are read-only, and `/tmp` resolves inside `/work`. Only validated regular files and directories are copied back; links, devices and traversal paths are rejected. The container runs as UID 10001 so the process limit applies.

Default limits are 60 seconds wall time, 32 KiB console output, 512 MiB writable disk, 2 GiB address space per process, 64 processes and 128 open descriptors. The CPU limit applies to each process and the wall deadline terminates the process group. Output overflow terminates execution. Failed commands do not publish a partial workspace snapshot. Missing bubblewrap or namespace support fails closed. There is no unrestricted-host fallback.

The runtime includes ffmpeg, ffprobe and Python. Remotion CLI dependencies are mounted read-only from `remotion/node_modules`; the container recipe installs them and Chromium. Package downloads and provider APIs are unavailable inside the shell. Browser-backed rendering also needs an installed browser and working local runtime; CLI availability alone does not establish a successful render. The existing Remotion renderer remains the default for assembled films.

`stage_media` copies an owned `renderhaus-asset://` version through the existing authenticated resolver. It does not accept arbitrary network URLs. Files that exceed the workspace quota return a concrete blocker. Use relative paths in `execute` and `/work/` paths in `read_file`.

## Inspection and finish

`inspect_media` runs ffprobe and ffmpeg locally. Its report includes stream metadata, duration, dimensions, frame-rate labels, integrated EBU R128 loudness, true peak, silence and black intervals, and the file checksum. Frame-rate labels do not prove CFR. Speech sampling is explicitly skipped because no approved free local transcription path is configured.

Visual evidence uses the SDK `read_file` implementation from the pinned `[video]` extra. Video `offset` and `limit` are seconds. Sampled timestamped images reach the model as image blocks. This does not prove playback, OCR, editorial acceptance or audio intelligibility.

The finish tool accepts final `media_paths`. It requires this turn's inspection and visual reads to match current checksums. Linked or newly registered media cannot skip inspection by omitting paths. If paths are omitted, newly created or changed local media files are inferred from checksums; owned copies staged as inputs are excluded. Missing inspection can send the manager back twice, after which the host records an incomplete result. The SDK `RubricMiddleware` applies the continuity, motion-carry and deliverable-QC skills where relevant. It has read-only tools and at most two revisions. Inspection repairs reduce that remaining revision allowance.

The host reads the saved rubric status. Grader errors and exhausted revisions remain incomplete. A rubric verdict cannot override the existing delivery QC report, required approvals, or output checksums. Pending visual review remains explicit. Local media publication happens after successful inspection and grading.

## Routing and recovery

`read_studio_context` returns ranked suggestions, selection reasons and the capability table. The order remains explicit request, named exception, capability default. A model may use another allowed automatic route with `routing_reason`; the host posts a neutral progress explanation. Required capabilities, licences, regions, forbidden tools, explicit-only status, consent, caps and paid approvals stay enforced. Confidential metadata does not change routing.

Tool failures include a cause, saved original call ID, allowed next action and safe alternatives. A free Gateway failure permits one alternative attempt. The host infers the active failure chain when `retry_of` is omitted, and a failed alternative cannot start a fresh chain under a new call ID. That allowance survives checkpoint restoration. A successful alternative closes the chain. Paid failures require fresh approval even in autonomous mode. An ambiguous creation response asks for saved-job reconciliation rather than resubmission. Approval rejection never authorizes a retry.

## Clarification cards

`ask_user` uses a native LangGraph interrupt with a structured question and options or free text. The reason must be `cost_difference` or `irreversible_outcome`. Routine implementation decisions remain with the agent. Question copy uses neutral outcomes without internal model names or billing terms.

Questions share durable pause storage with approvals but have a separate `kind`, answer schema, endpoint and Studio card. Answering a question does not call the spending approval gate, raise a cap, or authorize a paid action. Mixed question and approval batches resume only when all required responses are present. The same checkpoint scope and interrupt IDs must match on resume.

## Budget accounting

The run-level ledger reserves work before actual model calls, including role models, rubric grading, summaries and repairs. It settles usage once and retains ambiguous reservations for reconciliation. SDK retries are disabled on guarded models. The host pauses as `paused_cap` when an envelope cannot fit. Unknown-priced metered work fails closed.

Budget snapshots expose spent, reserved and remaining credit to each agent decision turn. Local shell and inspection work records orchestration units and uses an optional host compute rate. A zero configured compute rate means no separate local compute charge; it does not hide the model calls used to plan, inspect or revise.

The approval estimate includes higher-effort model calls, rubric grading, summaries and local action assumptions. The default estimate rises from 75 to 142 cents, before media charges, using 16 manager/role calls, three rubric calls and two summaries at 6000 input and 4000 output tokens each. Twelve ten-second local actions have no assigned compute price unless the host configures one. These are planning assumptions, not measured typical-run costs or authorization to exceed the hard cap. Existing estimate overrides remain available. The [offline report](HARNESS_V2_EVAL.md) separates modeled costs from measured API usage. Real-token calibration is pending under this task's prohibition on live calls.

## Optional reference tools

`web_search` and `web_fetch` are stable tools behind `RENDERHAUS_WEB_ENABLED`, off by default. They use no credentials or proxy environment. Fetch accepts HTTPS on a fixed public documentation allowlist, validates redirects, and bounds time and response size. Search uses the free Wikipedia reference endpoint. It is not a general commercial search service.

Results have explicit untrusted provenance and escaped nonce-delimited content. Web pages, transcripts and subtitles cannot grant spending approval, change policy, raise a cap, or invoke tools. There is no web access from the execution sandbox.

## Inventory and verification

Provider inventory remains 19 providers, 137 Gateway tools and 39 packaged runtime skills. Routing fixtures remain 313 rows, 307 active and six skipped. Six harness tools are tracked separately. The local evaluation World Knowledge skill is not a packaged runtime skill.

CI runs pytest so the new function-style tests are included. The image recipe includes bubblewrap, media tools and Remotion dependencies. Namespace availability still depends on the deployment host. A container build or typecheck does not prove host sandbox support.

Run the required checks from the repository root:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check agent lambdas scripts server providers
.venv/bin/python scripts/ci_check.py
cd studio && ./node_modules/.bin/tsc --noEmit -p .
```

Comet validation of the question card, answer persistence and resumed graph remains required. This session has no Comet browser-control connection. The ignored E2E receipt records the blocker; mocks and typechecks do not count as browser success.

## Sources and decisions

The installed package is the signature authority. The [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview), [rubric documentation](https://docs.langchain.com/oss/python/deepagents/rubric), and [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) were read on 2026-10-15. The existing Sonnet 5.5 input, output and cache rates match the pricing page. [Official vision limits](https://platform.claude.com/docs/en/build-with-claude/vision), read on the same date, bound each image at 4784 visual tokens plus a conservative protocol allowance. Unknown media types use the model context ceiling. No new provider model, endpoint or media price was introduced.

The [official bubblewrap 0.8.0 source](https://raw.githubusercontent.com/containers/bubblewrap/v0.8.0/bubblewrap.c), read on 2026-10-15, confirms the tmpfs size and read-only remount options used with the Bookworm container recipe. The image and its deployment host have not been exercised in this task.
