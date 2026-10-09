# ElevenLabs through AgentCore Gateway

Renderhaus exposes **41 media feature and supporting lookup/retrieval tools** from the pinned
[ElevenLabs OpenAPI document](https://api.elevenlabs.io/openapi.json), selected explicitly in
`providers/elevenlabs/catalog.py`. The same allowlist controls discovery, schemas and dispatch;
an OpenAPI refresh cannot add tools implicitly.

The catalog covers speech and v4 dialogue (including timestamps/HTTP streams), music composition,
video soundtracks and stems, sound effects, voice conversion/isolation, transcription/alignment,
dubbing generation/status/output, voice discovery/design/instant cloning, pronunciation rules,
and speech history retrieval. Voice creation and pronunciation-rule creation remain because
their IDs are inputs to speech generation. Dubbing project/language creation and retrieval
remain because they are the generation and output APIs for current dubbing models.

Account, subscription, usage, workspace, API-key/service-account, conversational-agent, phone,
production-order, ElevenLabs Studio/Flows/assets management and resource edit/delete APIs are
excluded. Image/video generation follows the capability map: Wan 3.0 is the plain-video default,
GPT Image support is pending, and Seedream requires an explicit request. The full upstream specification
is retained only for validation and review; it is not the exposed tool catalog.
Existing Mureka media remains in project history; Mureka is no longer a selectable provider.

## Key location

In AWS Secrets Manager, open **`renderhaus/app` in `us-east-1`**, edit the existing JSON secret,
and add or update **`ELEVENLABS_API_KEY`**. Preserve all other keys. The provider Lambda reads
that field using its execution role; the key is not embedded in the tool schema, prompts,
browser or Lambda environment. A key is already present in this environment and the live
model-list request succeeded during setup.

For local-only calls, `.env.local` can contain `ELEVENLABS_API_KEY=...`; a configured Secrets
Manager value takes precedence. Never commit the file. Do not use `sync_secrets.py` with a
bootstrap-only `.env.local`: that script replaces the whole secret. Rotate/recycle the provider
Lambda after replacing a key because its warm process caches the value.

## How the agent chooses tools

The agent starts with `x_amz_bedrock_agentcore_search`. Every generated tool has the upstream
operation description plus Renderhaus guidance: when to use it, required inputs, output type,
whether it changes content, and whether explicit approval is required.

| Request | Search intent / selected tool family |
| --- | --- |
| Background score or song | Music composition; `ElevenLabs___music_compose` |
| Soundtrack guided by an existing video | Video to music |
| Narration or character dialogue | Voice search, text to speech, text to dialogue |
| Foley, ambience, clean recorded dialogue | Sound effects or audio isolation |
| Captions, transcript timing, translated speech | Speech to text, forced alignment, dubbing |

The manager instructions contain the same routing rules. Official
[ElevenLabs skills](https://github.com/elevenlabs/skills) informed this guidance. Installing a
global skill alone would not reach Renderhaus: its Codex harness disables host skill discovery.
Voiceover uses Eleven v4 Turbo. Music routing follows the capability map; pending defaults
remain blocked rather than silently substituting a demoted provider. Account administration,
phone/voice-agent work and human production orders are
unavailable through Renderhaus, including in autonomous mode.

## Wire format and boundaries

- One shared dispatcher converts the schema into HTTP calls. No handwritten endpoint wrappers.
  Structured objects/unions use fields ending in `_json` because Gateway's Lambda schema dialect
  cannot represent them; their shape is described in each field. The complete upstream schema
  validates decoded input before any provider request.
- Multipart files use owned Renderhaus `source_ref` handles. The server resolves them to signed
  storage URLs; the Lambda only downloads from configured Renderhaus S3 buckets, without
  redirects. Binary audio/video/archive results go to private S3 and return a six-hour download
  URL. Studio imports supported media into durable project versions.
- HTTP streams are collected into completed files. JSON audio/timestamps and multipart audio
  are unpacked. Realtime WebSocket speech/voice conversations require a separate realtime
  client; they are not HTTP operations and cannot be run as Gateway tool calls.
- Requests currently allow 100 MiB per input/output and 180 seconds of upstream read inactivity
  within a 240-second Lambda. Longer/larger work requires the upstream asynchronous workflow
  or a longer-running worker. Provider plan, API-key scopes, quotas and endpoint availability
  still apply. Secret/token fields in responses are redacted from agent output.
- Gateway `renderhaus-media-gateway` uses IAM/SigV4 for AWS callers. AWS does not allow changing
  an existing gateway's authentication type, so the three other media targets were copied from
  the old public gateway. Renderhaus now uses the new URL; Mureka is removed from both catalogs.
  Existing JWT auth is preserved by deployment. The runtime role needs
  `bedrock-agentcore:InvokeGateway` on this gateway.

Music uses exactly one of `prompt` or `composition_plan_json`. With a prompt, set
`music_length_ms` (3000–600000) and `force_instrumental=true` for an instrumental. A normal
composition returns completed audio; it is not a Mureka-style asynchronous job to poll.
Dubbing has its own returned IDs and status/retrieval operations.

With Stripe disabled, provider charges go directly to the configured ElevenLabs account.
TTS approvals now estimate characters from the [official API price page](https://elevenlabs.io/pricing/api),
read 2026-10-09. The v4 list rate is $0.08 per 1,000 characters. The Turbo multiplier is 0.5,
so its list rate is $0.04. The promotion is $0.022 for v4 and $0.011 for Turbo through
2026-10-12. The estimator returns to list price on 2026-10-13 and rounds provider cost up
to integer cents before the existing platform fee. The priced TTS allowlist contains only
`eleven_v4_turbo` and `eleven_v4`; this fix adds no models or rates. Unrelated operations
keep an unknown estimate unless an operator quote exists.
When Stripe billing is enabled, write operations require explicit per-tool integer-cent quotes
in `ELEVENLABS_TOOL_COST_CENTS_JSON`; there is no invented blanket generation price. Read-only
lookups do not debit the Renderhaus wallet. Quotes are operator-controlled fixed per-call prices,
not invoice reconciliation; set them for the allowed workload before enabling customer billing.
Missing Stripe quotes fail TTS dispatch before approval; the billing requirement remains in force.

All four TTS Gateway tools expose the same priced choices. They require `voice_id` and `text`;
`model_id` is optional. An explicit allowed ID takes precedence over `ELEVENLABS_TTS_MODEL`.
When `model_id` is omitted, that setting defaults to `eleven_v4_turbo`. An unpriced or empty
configured default fails clearly at estimate time. The resolver in `server/billing_rates.py`
uses `ELEVENLABS_CHARACTER_MULTIPLIERS` as the allowlist for discovery, estimates and HTTP requests.
An unpriced model fails before native approval, spending reservation, credentials or provider I/O,
including when an operator quote exists. A stale schema produces a normal failed tool result
with `Allowed model_ids: eleven_v4, eleven_v4_turbo` so the agent can correct the request.

AgentCore's schema dialect cannot store JSON Schema `enum`, so the generated model description
contains the allowed values. `providers/elevenlabs/catalog.py` overrides the upstream TTS model
description and default before projecting the schema. Regenerating Gateway schemas retains the pin.
The pinned upstream OpenAPI remains an intact vendor reference and is not agent-facing discovery.
See [the decisions record](fix-tts-model-pin-decisions.tsv) for evidence and validation limits.

`ELEVENLABS_DRY_RUN` defaults to `true` and alone controls whether the dispatcher sends HTTP
requests. The operator's 2026-10-09 run confirmed `eleven_v4_turbo` supports HTTP TTS.
The [HTTP conversion](https://elevenlabs.io/docs/api-reference/text-to-speech/convert),
[timestamps](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps),
[streaming](https://elevenlabs.io/docs/api-reference/text-to-speech/stream), and
[streaming timestamps](https://elevenlabs.io/docs/api-reference/text-to-speech/stream-with-timestamps)
references, read 2026-10-09, accept `model_id` and require `can_do_text_to_speech` from the models endpoint.
The public model overview still emphasizes the websocket transport. No live request was made
during this fix. Other HTTP speech variants remain subject to vendor model compatibility.
Comet browser validation is blocked because Comet control is unavailable in this workspace.
Offline scripted approval tests do not verify live speech generation or artifact playback.

Without an output bucket, generated audio has an absolute `result.output_path` under
`RENDERHAUS_MEDIA_DIR`. Pass that plain path as `audio_tracks[].output_path` to the local
Remotion renderer. With a bucket, the existing signed URL handoff remains available.
Never convert the path to a `file://` URL.

The [terms](https://elevenlabs.io/terms-of-use), read 2026-10-09, permit commercial output
for paid users and require rights to supplied voices. Training eligibility stays false because
we have not verified a clear grant to train competing models on that output.

## Refresh and deploy

```bash
.venv/bin/python scripts/update_elevenlabs_schema.py
.venv/bin/python -m unittest discover -s tests -p 'test_elevenlabs.py'
.venv/bin/python scripts/generate_gateway_schemas.py --check
.venv/bin/python scripts/deploy_gateway.py --provider elevenlabs
```

Review the feature allowlist and schema diff before deployment. Missing selected operations
fail generation; new upstream operations remain excluded. The deploy script waits until ElevenLabs is ready
before removing the Mureka target. Gateway's native OpenAPI import was considered but does not
support binary media responses, so this uses the existing Lambda-target architecture.
See [AWS OpenAPI limitations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-schema-openapi.html).

The pinned specification is upstream API documentation, not a vendored SDK. The official
[MIT-licensed Python SDK](https://github.com/elevenlabs/elevenlabs-python) was used as an
implementation reference; no additional SDK dependency is required.
