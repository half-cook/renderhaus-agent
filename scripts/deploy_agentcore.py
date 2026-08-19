#!/usr/bin/env python3
"""Build, push, and deploy the Renderhaus agent to Bedrock AgentCore Runtime."""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


ROOT = Path(__file__).resolve().parents[1]
ROLE_NAME = "RenderhausAgentCoreRuntimeRole"
REPO_NAME = "renderhaus-agentcore"
RUNTIME_NAME = "renderhaus_agent"
DEFAULT_SECRET_NAME = "renderhaus/app"

# Non-secret runtime bootstrap only. Application secrets come from Secrets Manager.
RUNTIME_BOOTSTRAP_KEYS = [
    "AGENT_MODEL",
    "BYTEPLUS_BASE_URL",
    "SEEDANCE_MODEL",
    "SEEDANCE_DRY_RUN",
    "SEEDREAM_MODEL",
    "SEEDREAM_DRY_RUN",
    "MUREKA_API_URL",
    "MUREKA_MODEL",
    "MUREKA_DRY_RUN",
    "FISH_AUDIO_MODEL",
    "FISH_AUDIO_DRY_RUN",
    "AWS_S3_BUCKET",
    "AWS_DYNAMODB_ASSETS_TABLE",
    "LANGFUSE_BASE_URL",
    "RENDERHAUS_MEDIA_DIR",
    "AGENTCORE_GATEWAY_URL",
    "AGENTCORE_GATEWAY_AUTH_TOKEN",
]


def load_bootstrap_env(*, secret_name: str) -> dict[str, str]:
    from server.config import load_local_env

    # Prefer Secrets Manager when configured; fall back to .env.local during migration.
    os.environ.setdefault("RENDERHAUS_SECRETS_NAME", secret_name)
    load_local_env()
    env: dict[str, str] = {
        "AGENTCORE_RUNTIME": "1",
        "RENDERHAUS_SECRETS_NAME": secret_name,
        "RENDERHAUS_MEDIA_DIR": os.getenv("RENDERHAUS_MEDIA_DIR") or "/tmp/renderhaus/media",
    }
    for key in RUNTIME_BOOTSTRAP_KEYS:
        value = os.getenv(key)
        if value and value.strip():
            env[key] = value.strip()
    env.setdefault("SEEDANCE_DRY_RUN", "true")
    env.setdefault("SEEDREAM_DRY_RUN", "true")
    env.setdefault("MUREKA_DRY_RUN", "true")
    return env


def ensure_role(iam, account: str, region: str, bucket: str, secret_name: str) -> str:
    role_arn = f"arn:aws:iam::{account}:role/{ROLE_NAME}"
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AssumeRolePolicy",
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock-agentcore:{region}:{account}:*"
                    },
                },
            }
        ],
    }
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ECRImageAccess",
                "Effect": "Allow",
                "Action": ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
                "Resource": [f"arn:aws:ecr:{region}:{account}:repository/*"],
            },
            {
                "Sid": "ECRTokenAccess",
                "Effect": "Allow",
                "Action": ["ecr:GetAuthorizationToken"],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": ["logs:DescribeLogStreams", "logs:CreateLogGroup"],
                "Resource": [
                    f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*"
                ],
            },
            {
                "Effect": "Allow",
                "Action": ["logs:DescribeLogGroups"],
                "Resource": [f"arn:aws:logs:{region}:{account}:log-group:*"],
            },
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": [
                    f"arn:aws:logs:{region}:{account}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*"
                ],
            },
            {
                "Effect": "Allow",
                "Action": [
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                ],
                "Resource": ["*"],
            },
            {
                "Effect": "Allow",
                "Action": "cloudwatch:PutMetricData",
                "Resource": "*",
                "Condition": {
                    "StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}
                },
            },
            {
                "Sid": "GetAgentAccessToken",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:GetWorkloadAccessToken",
                    "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                    "bedrock-agentcore:GetWorkloadAccessTokenForUserId",
                ],
                "Resource": [
                    f"arn:aws:bedrock-agentcore:{region}:{account}:workload-identity-directory/default",
                    f"arn:aws:bedrock-agentcore:{region}:{account}:workload-identity-directory/default/workload-identity/{RUNTIME_NAME}-*",
                ],
            },
            {
                "Sid": "BedrockModelInvocation",
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                "Resource": [
                    "arn:aws:bedrock:*::foundation-model/*",
                    f"arn:aws:bedrock:{region}:{account}:*",
                ],
            },
            {
                "Sid": "RenderhausS3",
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:ListBucket",
                ],
                "Resource": [
                    f"arn:aws:s3:::{bucket}",
                    f"arn:aws:s3:::{bucket}/*",
                ],
            },
            {
                "Sid": "RenderhausDynamo",
                "Effect": "Allow",
                "Action": [
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:Query",
                    "dynamodb:DescribeTable",
                ],
                "Resource": [
                    f"arn:aws:dynamodb:{region}:{account}:table/*",
                ],
            },
            {
                "Sid": "RenderhausSecrets",
                "Effect": "Allow",
                "Action": [
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:DescribeSecret",
                ],
                "Resource": [
                    f"arn:aws:secretsmanager:{region}:{account}:secret:{secret_name}-*",
                    f"arn:aws:secretsmanager:{region}:{account}:secret:{secret_name}",
                ],
            },
        ],
    }

    try:
        iam.get_role(RoleName=ROLE_NAME)
        print(f"IAM role exists: {role_arn}")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchEntity":
            raise
        iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Execution role for Renderhaus Bedrock AgentCore Runtime",
        )
        print(f"Created IAM role: {role_arn}")

    iam.update_assume_role_policy(RoleName=ROLE_NAME, PolicyDocument=json.dumps(trust))
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="RenderhausAgentCoreRuntimePolicy",
        PolicyDocument=json.dumps(policy),
    )
    time.sleep(8)
    return role_arn


def docker_login_and_image_uri(ecr) -> str:
    try:
        ecr.create_repository(repositoryName=REPO_NAME)
        print(f"Created ECR repository {REPO_NAME}")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "RepositoryAlreadyExistsException":
            raise

    auth = ecr.get_authorization_token()["authorizationData"][0]
    user_pass = base64.b64decode(auth["authorizationToken"]).decode("utf-8")
    username, password = user_pass.split(":", 1)
    registry = auth["proxyEndpoint"].replace("https://", "")
    subprocess.run(
        ["docker", "login", "--username", username, "--password-stdin", registry],
        input=password + "\n",
        text=True,
        check=True,
        cwd=ROOT,
    )
    return f"{registry}/{REPO_NAME}"


def build_and_push(image_uri: str) -> None:
    cmd = [
        "docker",
        "buildx",
        "build",
        "--platform",
        "linux/arm64",
        "-f",
        "Dockerfile.agentcore",
        "-t",
        f"{image_uri}:latest",
        "--push",
        ".",
    ]
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def upsert_runtime(control, *, role_arn: str, image_uri: str, env: dict[str, str]):
    existing = control.list_agent_runtimes().get("agentRuntimes") or []
    match = next((item for item in existing if item.get("agentRuntimeName") == RUNTIME_NAME), None)
    artifact = {"containerConfiguration": {"containerUri": f"{image_uri}:latest"}}
    common = {
        "roleArn": role_arn,
        "networkConfiguration": {"networkMode": "PUBLIC"},
        "protocolConfiguration": {"serverProtocol": "HTTP"},
        "lifecycleConfiguration": {
            "idleRuntimeSessionTimeout": 900,
            "maxLifetime": 7200,
        },
        "environmentVariables": env,
        "agentRuntimeArtifact": artifact,
    }
    if match:
        runtime_id = match["agentRuntimeId"]
        print(f"Updating AgentCore runtime {runtime_id}")
        response = control.update_agent_runtime(agentRuntimeId=runtime_id, **common)
        arn = response.get("agentRuntimeArn") or match.get("agentRuntimeArn")
    else:
        print(f"Creating AgentCore runtime {RUNTIME_NAME}")
        response = control.create_agent_runtime(
            agentRuntimeName=RUNTIME_NAME,
            description="Renderhaus LangChain agent + generation MCPs",
            **common,
        )
        arn = response["agentRuntimeArn"]
    print(f"Runtime ARN: {arn}")
    print(f"Status: {response.get('status')}")
    return arn


def write_env_hint(arn: str, region: str, secret_name: str) -> None:
    hint = ROOT / ".env.agentcore"
    hint.write_text(
        "\n".join(
            [
                f"AGENTCORE_RUNTIME_ARN={arn}",
                f"AGENTCORE_REGION={region}",
                "AGENTCORE_QUALIFIER=DEFAULT",
                f"RENDERHAUS_SECRETS_NAME={secret_name}",
                f"AWS_REGION={region}",
                "",
            ]
        )
    )
    print(f"Wrote {hint}.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=os.getenv("AWS_REGION") or "us-east-1")
    parser.add_argument(
        "--secret-name",
        default=os.getenv("RENDERHAUS_SECRETS_NAME") or DEFAULT_SECRET_NAME,
    )
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    region = args.region
    secret_name = args.secret_name

    os.environ.setdefault("AWS_REGION", region)
    os.environ.setdefault("AWS_DEFAULT_REGION", region)
    env = load_bootstrap_env(secret_name=secret_name)
    bucket = env.get("AWS_S3_BUCKET") or os.getenv("AWS_S3_BUCKET")
    if not bucket:
        print(
            "AWS_S3_BUCKET must be available via Secrets Manager or bootstrap env.",
            file=sys.stderr,
        )
        return 1
    if not os.getenv("OPENAI_API_KEY"):
        print(
            "OPENAI_API_KEY must be present in Secrets Manager before deploy.",
            file=sys.stderr,
        )
        return 1

    session = boto3.session.Session(region_name=region)
    account = session.client("sts").get_caller_identity()["Account"]
    iam = session.client("iam")
    ecr = session.client("ecr")
    control = session.client("bedrock-agentcore-control", region_name=region)

    role_arn = ensure_role(iam, account, region, bucket, secret_name)
    image_uri = docker_login_and_image_uri(ecr)
    if not args.skip_build:
        build_and_push(image_uri)

    runtime_env = dict(env)
    runtime_env["AWS_REGION"] = region
    runtime_env["AWS_DEFAULT_REGION"] = region
    runtime_env["RENDERHAUS_SECRETS_NAME"] = secret_name
    # Keep media dir container-local even if secret has a laptop path.
    runtime_env["RENDERHAUS_MEDIA_DIR"] = "/tmp/renderhaus/media"

    arn = upsert_runtime(
        control,
        role_arn=role_arn,
        image_uri=image_uri,
        env=runtime_env,
    )
    write_env_hint(arn, region, secret_name)

    for _ in range(60):
        listed = control.list_agent_runtimes().get("agentRuntimes") or []
        item = next((row for row in listed if row.get("agentRuntimeArn") == arn), None)
        status = (item or {}).get("status")
        print(f"Waiting for runtime status={status}")
        if status in {"READY", "ACTIVE", "CREATE_COMPLETE", "UPDATE_COMPLETE"}:
            break
        if status in {"CREATE_FAILED", "UPDATE_FAILED", "FAILED"}:
            print(f"Runtime entered failed status: {status}", file=sys.stderr)
            return 1
        time.sleep(10)

    print("\nNext steps:")
    print("1) Keep RENDERHAUS_SECRETS_NAME in local bootstrap env")
    print("2) Restart the web app")
    print("3) Run: .venv/bin/python scripts/smoke_agentcore.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
