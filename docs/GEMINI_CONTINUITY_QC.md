# Gemini continuity judge

`gemini_vlm_judge` maps to `Gemini___judge_continuity`. It is an explicit experimental
candidate. The quality-first continuity default remains `local_qc`, the calibrated
SigLIP+DINOv2 rule with 0.845 accuracy on the 420 labelled pairs. Confidentiality does not
alter selection. Explicit requests take precedence over the gated default.

The implementation uses the installed Deep Agents 0.7.23 dispatch and native interrupt
path. It adds no planner or subagent and leaves the Haiku manager setting unchanged.

## Official API and terms

All sources below were read on **2026-10-09**.

| Verification | Official source | Result |
| --- | --- | --- |
| Model ID | [Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash) | `gemini-3.8-flash` verified |
| Image input | [Image understanding](https://ai.google.dev/gemini-api/docs/image-understanding) | Two inline PNG/JPEG images supported |
| Video understanding | [Video understanding](https://ai.google.dev/gemini-api/docs/video-understanding) | Reviewed; this adapter uses keyframes only |
| Structured output | [JSON schema](https://ai.google.dev/gemini-api/docs/structured-output) | JSON response with a schema supported |
| Async request and response | [Interactions API reference](https://ai.google.dev/api/interactions-api) | POST background interaction and GET saved interaction |
| Hosting | [Available regions](https://ai.google.dev/gemini-api/docs/available-regions) | United States listed |
| Licence | [Gemini API additional terms](https://ai.google.dev/gemini-api/terms) | Hosted service terms; commercial professional/business use, no distributed weights |

The endpoint is `https://generativelanguage.googleapis.com/v1beta/interactions`.
The request fixes the model, ordered text/image inputs, `background=true`, `store=true`,
standard service tier, JSON response schema, minimal thinking and 512 output tokens.
Polling reads the saved interaction ID and model; it never submits a replacement job.
Background requests retain inputs on Google's service. Follow the linked terms and obtain
the rights and applicable permissions to send source images. No Gemini-specific mandatory
recorded face/voice consent workflow was verified. No likeness generation is added.

`weights_license=service-terms`, `commercial=true`, `training_eligible=false`. The hosted
terms restrict using the service to develop competing models and do not clearly grant this
project's synthetic training use. No vendor code or weights are copied. No AGPL or
non-commercial dependency is added. Existing SigLIP/DINOv2 licences and DINOv3 restrictions
are unchanged.

## Configuration

Secrets come only from environment variables or the existing Secrets Manager bundle.
`scripts/sync_secrets.py` forwards the optional Gemini variables; no secret file is needed.

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | absent | Required only for live use; add to Secrets Manager |
| `GEMINI_DRY_RUN` | `true` | Prevent requests; CI forces true |
| `GEMINI_VLM_MODEL` | `gemini-3.8-flash` | Configurable model ID; any unverified override is dry-run only |
| `GEMINI_VLM_TIMEOUT_SECONDS` | `30` | Whole judge deadline, maximum 300 seconds |
| `GEMINI_VLM_MAX_RETRIES` | `2` | Transient retry count, maximum 5 |
| `GEMINI_TOOL_COST_CENTS_JSON` | absent | Operator request estimate, e.g. `{"judge_continuity":10}`; an estimate, not vendor pricing |
| `CONTINUITY_QC_BACKEND` | `local` | Explicit `vlm` enables this experimental backend; `runpod` remains available |
| `CONTINUITY_QC_EMBEDDING_BACKEND` | `local` | Embedding pre-filter host for `vlm`; optional `runpod` |

The policy's `vlm_prefilter_threshold` defaults to 0.1. The provider validates decoded images,
model IDs and typed arguments before any paid request. Limits are 4 MiB and 16 million pixels
per image, 12 MiB for the request, and 1 MiB for the response. It does not fetch caller URLs.

## Execution and failure handling

The composed QC backend embeds both frames first. It keeps both cosines, calibrated
probabilities and their mean in each pair's report. Clearly rejected pairs skip the judge.
Other pairs use the fixed character/wardrobe/props/lighting/location rubric. The strict
response is `{same_shot_continuity: bool, confidence: number, issues: string[]}`.
Extra fields, coercions, duplicate JSON keys, non-finite confidence, malformed status,
mismatched IDs/models and oversized output are failures.

POST retries only an explicit 429 rejection. A timeout or 5xx after submission is ambiguous
and must not cause another paid submission. GET retries transient 429/5xx within the deadline.
Errors use fixed redacted messages. A failure returns `status=skipped`, preserves embedding
metrics when available, stops subsequent judge calls and never blocks rendering. Dry-run
returns no verdict. Polling a dry-run handle cannot make a live request.

Gateway tools are `Gemini___judge_continuity(before_image_b64, after_image_b64, model="")`
and `Gemini___get_task(job_id, model="")`. The Gateway provider does not calculate embeddings;
the continuity host or skill must apply the pre-filter before dispatching it. The `local_qc`
host integration is still separate from Gateway dispatch.

Manual judge calls use the existing native approval with a cost description and experimental
disclosure. Autonomous calls obey the unchanged spend cap. Unknown cost blocks a capped run.
The approval exemption list and paid-video approval behavior are unchanged.

## Pricing and verification limits

[Official pricing](https://ai.google.dev/gemini-api/docs/pricing), read 2026-10-09, lists
standard input at $0.75 per million tokens and output including thinking at $3.75 through
2026-12-31. From 2027-01-01 the rates are $1.50 and $7.50. Billing code applies the expiry
and counts reported input, output and thought tokens. Pre-call usage is unknown unless the
operator supplies an estimate; no guessed token cost enters routing. Existing platform fees
apply to operator quotes. Polling has no generation quote.

See [the eval procedure](CONTINUITY_QC_BENCHMARK.md#experimental-gemini-judge-and-eval-gate)
for the labelled 420-pair estimate and promotion rules. This branch performs only fake-client,
mocked-HTTP and dry-run checks, with no live provider calls or committed eval result.
Comet browser E2E is blocked because Comet cannot be controlled in this environment.
Browser approval/disclosure and the visible skipped result remain unverified. Offline native
approval/resume/rejection checks support the implementation but do not replace browser E2E.

Final offline verification ran 1,329 tests, with 1,322 passing and 7 skipped. Ruff,
CI dry-run packaging and Studio TypeScript typechecking passed. The suite adds 65 tests
for the provider, composed backend, gate and native approval flow. Six routing fixture
rows remain skipped; the optional worker dependency-import test requires torch and runpod. The actual 420-frame-set dry-run completed with 420 skipped decisions,
`live=false`, and a nonqualifying receipt. No live accuracy claim is made.

The pre-existing `uv.lock` omits the pinned Deep Agents dependencies. An offline refresh
also cannot resolve OpenTimelineIO for the declared Python >=3.14 range from the available
cache, so the lock remains unchanged. Refresh it when the full package metadata cache is
available. This branch validates the installed Python 3.11 environment and the project's
pip-based CI packaging path. Pillow is now a required dependency for bounded image decoding.

Pillow 12.3.0 uses the [MIT-CMU licence](https://pillow.readthedocs.io/en/stable/about.html#license),
verified 2026-10-09. Its required dependency replaces the former optional image decoder
for this provider; test setup reused an existing offline package cache.
