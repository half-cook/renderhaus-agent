# Run Renderhaus on your computer

The local launcher starts FastAPI, Studio, and the local MCP gateway. It reads
`renderhaus/app` in `us-east-1` using your own AWS identity. Credentials stay in
process memory. The launcher does not create environment files.

Media providers default to dry-run, including when the shared secret sets their
flags to false. Agent LLM calls and Clerk sign-in remain live-capable and need
network access on your computer. A media dry-run previews a request and does not
produce a finished image, audio file, or video.

## Install prerequisites

Use Bash on macOS or Linux, Git, Make, Python >=3.11, and Node >=20.9.0 with npm.
Python's minimum is in `pyproject.toml`; `Dockerfile.agentcore` uses Python 3.11.
Studio has no top-level `engines` field or `.nvmrc`. Its locked Clerk packages
require Node >=20.9.0, which also satisfies its Next.js and Playwright engines.
Use a supported Node LTS release meeting that minimum.

Install [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html).
The launcher uses `aws sts get-caller-identity` when the CLI is present and boto3
otherwise. Both use your shell's AWS credential chain. It never copies another
person's AWS identity into the app.

## Configure your AWS identity

For IAM Identity Center, use the start URL and SSO region supplied by your AWS
administrator. Select the role in account `648597472910` with access to the
secret. Run these commands:

```bash
aws configure sso --profile renderhaus-local
aws sso login --profile renderhaus-local
export AWS_PROFILE=renderhaus-local
export AWS_REGION=us-east-1
```

If your administrator supplies access keys for your own IAM identity, enter
them in the AWS CLI prompt on your computer:

```bash
aws configure --profile renderhaus-local
export AWS_PROFILE=renderhaus-local
export AWS_REGION=us-east-1
```

The AWS CLI stores profile credentials in its standard AWS files. Never enter
credentials in repository files or chat. Shell access keys take precedence over
profile credentials in the standard credential chain. Unset stale
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_SESSION_TOKEN` variables
when you intend to use SSO.

Ask the operator for the read-only policy JSON and have your administrator
attach it to your identity or permission set. The supplied policy must match:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": "arn:aws:secretsmanager:us-east-1:648597472910:secret:renderhaus/app-uu3xWe"
    }
  ]
}
```

This policy grants no secret updates, S3 writes, DynamoDB access, or deployments.
No KMS statement is needed for this secret's default `aws/secretsmanager` key.
AWS documents this case in [Secrets Manager permissions](https://docs.aws.amazon.com/secretsmanager/latest/userguide/auth-and-access_iam-policies.html).

## Install the app

Use the reviewed `feat/local-run-secrets` branch supplied by the operator. It is
local until the operator publishes or transfers it. If the checkout command
below reports an unknown branch, obtain that branch as a Git bundle or fetch it
from the operator's approved remote before continuing.

```bash
git clone https://github.com/half-cook/renderhaus-agent.git
cd renderhaus-agent
git checkout feat/local-run-secrets
make setup
cd studio
npm ci
cd ..
```

Ensure `python3` selects Python >=3.11 before `make setup`. The equivalent setup
command is `bash scripts/setup_agent.sh`.

Use shell variables for local bootstrap configuration. Move existing root
`.env.local` and Studio `.env`, `.env.local`, `.env.development`, or
`.env.development.local` files out of the checkout before using the launcher.
Keep any old credential files private. The launcher refuses these files to
prevent stale keys or endpoints from entering a child process.

## Start the app

```bash
export AWS_PROFILE=renderhaus-local
export AWS_REGION=us-east-1
make local-check
make local
```

`local-check` verifies prerequisites, your AWS identity, and secret readability.
It prints loaded key names and an effective dry-run table. It never prints key
values, including the publishable key. The secret name defaults to
`renderhaus/app`; override it with `RENDERHAUS_SECRETS_NAME` if needed.
`RENDERHAUS_SECRETS_ARN`, when supplied, takes precedence over the name.

Open **http://localhost:5174** and sign in to the shared Clerk app. Logs for all
three services go to ignored `.renderhaus/logs/` with private file permissions.
Ctrl-C terminates the launcher and its child process groups. If a service exits
or fails to open its port within 60 seconds, the launcher stops the other
services and exits non-zero. First-time Studio compilation can take longer;
use separate terminals to diagnose that case.

You can run services individually in three terminals:

```bash
bash scripts/run_local.sh gateway
bash scripts/run_local.sh backend
bash scripts/run_local.sh studio
```

The ports are fixed to match the current app:

| Service | Address |
| --- | --- |
| Studio | `http://localhost:5174` |
| FastAPI | `http://127.0.0.1:8000` |
| Local gateway | `http://127.0.0.1:8765/mcp` |

`bash scripts/run_local.sh status` inspects the local ports without AWS calls.
A listening port is not proof of authentication or application health.
`bash scripts/run_local.sh check --print-keys` reports configuration names and
dry-run states without starting services. `up` and `all` both start all services.

## Choose dry-run or live providers

`run_local.sh` always selects `RENDERHAUS_LOCAL_PROFILE=local`. The normal Python
loader reads `.env.local`, applies the secret with `override=True`, and then
applies defaults. With the local profile, it captures local controls before the
secret read and reapplies local settings afterward. Secret values cannot enable
live providers or replace the local gateway.

Every known `*_DRY_RUN` flag is forced to true, including FAL, MODELSTUDIO,
ELEVENLABS, KLING, RUNWAY, LUMA, HYPERFRAMES, SYNC, HEYGEN, HEYGEN_VOICE, TOPAZ,
MUREKA, SEEDANCE, SEEDREAM, FISH_AUDIO, GEMINI_TTS, GEMINI, OPENAI_IMAGES,
REMOTION, FOOTAGE_MEMORY, BETA_VERIFICATION, FFMPEG, and MOTION_CARRY_QC.
Any additional dry-run flags present in the secret are also forced to true.
Setting `FAL_DRY_RUN=false` alone does not bypass the local profile.

To explicitly authorize live providers, set their uppercase prefixes in
`RENDERHAUS_LOCAL_LIVE_PROVIDERS` before starting the app. For example:

```bash
export RENDERHAUS_LOCAL_LIVE_PROVIDERS=FAL,TOPAZ
bash scripts/run_local.sh check
bash scripts/run_local.sh up
```

This enables live fal and Topaz calls. The launcher prints a loud LIVE warning.
Some adapters need both their own flag and their host flag to be false, such as
Topaz, Mureka, fal-backed Seedance, and fal-backed Sync. Enabling FAL can also
enable other tools that share that host. Use the dry-run table before starting.
Remove the opt-in to restore all dry-runs:

```bash
unset RENDERHAUS_LOCAL_LIVE_PROVIDERS
```

The launcher does not edit billing rates, approval interrupts, approval
exemptions, or autonomous spending limits. Existing paid-video approval rules
still apply, including their autonomous cost pauses. The gateway stays local
even with live providers enabled. A live opt-in permits requests but does not
override adapter licence, consent, or unverified-model blocks.

The profile clears production runtime and gateway IDs, gateway auth tokens,
bucket names, Stripe secret/webhook keys, and `REMOTION_APP_*` settings. Local
Stripe checkout is unavailable. It sets local app URLs, development
Node mode, local Remotion rendering, and Studio SQLite/file storage. It selects
the repo's Sonnet default instead of a production `AGENT_MODEL`. Explicit shell
`AGENT_MODEL` or `RENDERHAUS_AGENT_MODEL` and per-role model/effort overrides are
preserved. Agent LLM keys remain available to Python services.
The secret cannot replace the caller's AWS identity selectors, credential-file
locations, `HOME`, or `PATH`.

Studio's publishable key is passed through its process environment. Its
installed Clerk middleware also requires `CLERK_SECRET_KEY`; that key is passed
only to the Next server process and Python services, never written to disk or
put in a `NEXT_PUBLIC_*` variable. Studio receives no agent, media-provider, or
AWS credentials. No Studio source changes are needed.

## Use local storage and Clerk origins

Studio stores projects and immutable asset versions in
`.renderhaus/studio.sqlite3` and `.renderhaus/media/assets/`. Local startup skips
the legacy AWS asset initializer, which otherwise creates DynamoDB/S3 resources.
Legacy cloud asset routes and publishing local files for remote providers are
unavailable in this profile. Live adapters that require S3 publication or cloud
job manifests remain blocked without a separately designed storage setup.
This read-only IAM policy intentionally does not grant that access.

Use `localhost:5174`, not `127.0.0.1:5174`, unless the shared secret explicitly
lists that origin in `CLERK_AUTHORIZED_PARTIES`. Clerk compares exact origins,
including the port. The shared app allows `http://localhost:5174`, `:3000`, and
`:8000`. On `TOKEN_INVALID_AUTHORIZED_PARTIES`, return to the allowed hostname.
If you need another origin, ask the operator to add it to the shared secret,
then restart the API. Do not disable authentication. See
[Studio authentication and troubleshooting](STUDIO_AGENT.md).

## Troubleshoot by error code

The launcher reports error codes and corrective actions without AWS exception
messages, credential values, or stack traces.

| Code | Action |
| --- | --- |
| `MissingVenv`, `PythonVersion` | Install Python >=3.11 and run `make setup`. |
| `MissingNode`, `NodeVersion` | Install Node >=20.9.0 with npm. |
| `MissingNodeModules` | Run `npm ci` in `studio/`. |
| `StudioEnvFile`, `LocalEnvFile` | Move the conflicting env files out of the checkout. |
| `NoCredentialsError`, `PartialCredentialsError` | Configure your own AWS profile. Unset incomplete shell credentials. |
| `ProfileNotFound` | Check `AWS_PROFILE` and configure that named profile. |
| `ExpiredToken`, `ExpiredTokenException`, `SSOUnauthorizedTokenError`, `UnauthorizedSSOTokenError`, `TokenRetrievalError` | Run `aws sso login --profile renderhaus-local`, or refresh temporary keys. |
| `InvalidClientTokenId`, `UnrecognizedClientException` | Check your selected identity and remove stale shell access keys. |
| `AccessDenied`, `AccessDeniedException` | Ask for the exact read-only IAM policy above. |
| `ResourceNotFoundException` | Check `AWS_REGION=us-east-1` and the secret name or ARN. |
| `EndpointConnectionError`, `ConnectTimeoutError`, `ReadTimeoutError` | Check the region and network, then retry. |
| `DecryptionFailure` | Ask the secret owner to check its encryption settings. |
| `AWSIdentityFailed` | Check profile configuration and SSO login. The CLI's raw output is suppressed. |
| `MissingSecretName`, `InvalidSecret`, `MissingClerkConfig`, `InvalidConfiguration` | Check shell controls and ask the operator to check the secret's format and required key names. |
| `PortInUse` | Stop the existing service on the reported port. |
| `ServiceExited`, `StartupTimeout` | Inspect `.renderhaus/logs/` locally. Do not paste raw logs containing credentials. |
| `LocalRunFailed` | Check dependencies and configuration in this guide. Raw exception text is suppressed. |
| `TOKEN_INVALID_AUTHORIZED_PARTIES` | Use `http://localhost:5174` or have the operator authorize the exact origin. |

## Keep credentials private

Never commit environment files, paste keys in chat, run credential-loading
commands with shell tracing, or copy another person's AWS credentials. Rotate
any credential that leaks. `.env.local`, `studio/.env.local`, and
`.renderhaus/logs/` are ignored by Git. Logs are still private local data; do not
share them without checking their contents.

This launcher was validated with fake AWS clients and fake secrets only.
Live AWS reads, provider requests, Clerk sign-in, and Comet browser E2E remain
unverified here. No provider prices, model licences, training eligibility, or
routing defaults change as part of this tooling task.
