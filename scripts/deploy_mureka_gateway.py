#!/usr/bin/env python3
"""Deploy Mureka tools as a Lambda + AgentCore Gateway target.

Creates/updates:
  - IAM role for the Lambda (Secrets Manager + basic logs)
  - IAM role for the Gateway (lambda:InvokeFunction)
  - Lambda function renderhaus-mureka-tools
  - AgentCore Gateway renderhaus-mureka-gateway
  - Gateway target Mureka pointing at the Lambda with full tool schema

Writes .env.agentcore.gateway with AGENTCORE_GATEWAY_URL / ids.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


ROOT = Path(__file__).resolve().parents[1]
TOOLS_SCHEMA_PATH = ROOT / "configs" / "mureka_gateway_tools.json"
HANDLER_PATH = ROOT / "lambdas" / "mureka" / "handler.py"
MUREKA_PKG = ROOT / "mcps" / "mureka"

FUNCTION_NAME = "renderhaus-mureka-tools"
LAMBDA_ROLE_NAME = "RenderhausMurekaLambdaRole"
GATEWAY_ROLE_NAME = "RenderhausMurekaGatewayRole"
GATEWAY_NAME = "renderhaus-mureka-gateway"
TARGET_NAME = "Mureka"
DEFAULT_SECRET_NAME = "renderhaus/app"


def _load_tools_schema() -> list[dict]:
    return json.loads(TOOLS_SCHEMA_PATH.read_text())


def _ensure_lambda_role(iam, account: str, region: str, secret_name: str) -> str:
    role_arn = f"arn:aws:iam::{account}:role/{LAMBDA_ROLE_NAME}"
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                "Resource": f"arn:aws:logs:{region}:{account}:*",
            },
            {
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
        iam.get_role(RoleName=LAMBDA_ROLE_NAME)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            raise
        iam.create_role(
            RoleName=LAMBDA_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Lambda execution role for Renderhaus Mureka Gateway tools",
        )
    iam.put_role_policy(
        RoleName=LAMBDA_ROLE_NAME,
        PolicyName="RenderhausMurekaLambdaPolicy",
        PolicyDocument=json.dumps(policy),
    )
    time.sleep(8)
    return role_arn


def _ensure_gateway_role(iam, account: str, region: str, lambda_arn: str) -> str:
    role_arn = f"arn:aws:iam::{account}:role/{GATEWAY_ROLE_NAME}"
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
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
                "Effect": "Allow",
                "Action": ["lambda:InvokeFunction"],
                "Resource": [lambda_arn, f"{lambda_arn}:*"],
            }
        ],
    }
    try:
        iam.get_role(RoleName=GATEWAY_ROLE_NAME)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            raise
        iam.create_role(
            RoleName=GATEWAY_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="AgentCore Gateway role for Renderhaus Mureka Lambda tools",
        )
    iam.update_assume_role_policy(RoleName=GATEWAY_ROLE_NAME, PolicyDocument=json.dumps(trust))
    iam.put_role_policy(
        RoleName=GATEWAY_ROLE_NAME,
        PolicyName="RenderhausMurekaGatewayPolicy",
        PolicyDocument=json.dumps(policy),
    )
    time.sleep(5)
    return role_arn


def _build_lambda_zip() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        package = tmp_path / "package"
        package.mkdir()
        # Install minimal runtime deps into the package root.
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "httpx",
                "pydantic",
                "-t",
                str(package),
                "--quiet",
            ],
            check=True,
        )
        # Copy mureka package (api.py + __init__).
        dest_pkg = package / "mcps" / "mureka"
        dest_pkg.mkdir(parents=True)
        (package / "mcps" / "__init__.py").write_text('"""MCP packages for Lambda packaging."""\n')
        for name in ("__init__.py", "api.py"):
            src = MUREKA_PKG / name
            if src.exists():
                shutil.copy2(src, dest_pkg / name)
        # Handler at package root.
        shutil.copy2(HANDLER_PATH, package / "handler.py")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in package.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(package).as_posix())
        return buf.getvalue()


def _upsert_lambda(
    lam,
    *,
    role_arn: str,
    region: str,
    secret_name: str,
    env: dict[str, str],
) -> str:
    zip_bytes = _build_lambda_zip()
    runtime_env = {
        "MUREKA_DRY_RUN": env.get("MUREKA_DRY_RUN", "true"),
        "MUREKA_API_URL": env.get("MUREKA_API_URL", "https://api.mureka.ai"),
        "MUREKA_MODEL": env.get("MUREKA_MODEL", "auto"),
        "RENDERHAUS_SECRETS_NAME": secret_name,
        "RENDERHAUS_MEDIA_DIR": "/tmp/renderhaus/media",
        "AWS_REGION_NAME": region,
    }
    # Prefer injecting API key from env/secrets into Lambda env for cold-start simplicity.
    if env.get("MUREKA_API_KEY"):
        runtime_env["MUREKA_API_KEY"] = env["MUREKA_API_KEY"]

    config = {
        "FunctionName": FUNCTION_NAME,
        "Runtime": "python3.11",
        "Role": role_arn,
        "Handler": "handler.handler",
        "Timeout": 120,
        "MemorySize": 512,
        "Architectures": ["arm64"],
        "Environment": {"Variables": runtime_env},
    }
    try:
        lam.get_function(FunctionName=FUNCTION_NAME)
        print(f"Updating Lambda {FUNCTION_NAME}")
        # Architectures is valid on create_function / update_function_code only —
        # not on update_function_configuration.
        lam.update_function_code(
            FunctionName=FUNCTION_NAME,
            ZipFile=zip_bytes,
            Architectures=config["Architectures"],
        )
        # Wait briefly for code update before config update.
        time.sleep(3)
        config_update = {
            k: v
            for k, v in config.items()
            if k not in ("FunctionName", "Architectures")
        }
        lam.update_function_configuration(FunctionName=FUNCTION_NAME, **config_update)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        print(f"Creating Lambda {FUNCTION_NAME}")
        lam.create_function(**config, Code={"ZipFile": zip_bytes}, Publish=True)
        time.sleep(5)
    fn = lam.get_function(FunctionName=FUNCTION_NAME)
    return fn["Configuration"]["FunctionArn"]


def _find_gateway(control, name: str) -> dict | None:
    token = None
    while True:
        kwargs = {}
        if token:
            kwargs["nextToken"] = token
        resp = control.list_gateways(**kwargs)
        for item in resp.get("items") or resp.get("gateways") or []:
            if item.get("name") == name or item.get("gatewayName") == name:
                return item
        token = resp.get("nextToken")
        if not token:
            return None


def _upsert_gateway(control, *, role_arn: str) -> tuple[str, str]:
    """Return (gateway_id, gateway_url)."""
    existing = _find_gateway(control, GATEWAY_NAME)
    # NONE authorizer for Runtime HTTP MCP bootstrap; harden later with IAM/JWT.
    create_kwargs = {
        "name": GATEWAY_NAME,
        "roleArn": role_arn,
        "protocolType": "MCP",
        "authorizerType": "NONE",
        "description": "Renderhaus Mureka music tools via Lambda",
    }
    # Some SDK versions require authorizerConfiguration omitted for NONE.
    if existing:
        gateway_id = existing.get("gatewayId") or existing.get("gatewayIdentifier") or existing.get("id")
        print(f"Gateway exists: {gateway_id}")
    else:
        print(f"Creating gateway {GATEWAY_NAME}")
        try:
            resp = control.create_gateway(**create_kwargs)
        except ClientError:
            # Fallback shapes across SDK previews.
            create_kwargs.pop("authorizerType", None)
            resp = control.create_gateway(
                name=GATEWAY_NAME,
                roleArn=role_arn,
                protocolType="MCP",
                description="Renderhaus Mureka music tools via Lambda",
            )
        gateway_id = (
            resp.get("gatewayId")
            or resp.get("gatewayIdentifier")
            or (resp.get("gateway") or {}).get("gatewayId")
        )
        if not gateway_id:
            raise RuntimeError(f"create_gateway returned no id: {resp}")
        time.sleep(5)

    detail = control.get_gateway(gatewayIdentifier=gateway_id)
    gateway = detail.get("gateway") or detail
    url = (
        gateway.get("gatewayUrl")
        or gateway.get("url")
        or f"https://{gateway_id}.gateway.bedrock-agentcore.{control.meta.region_name}.amazonaws.com/mcp"
    )
    return gateway_id, url


def _upsert_target(control, *, gateway_id: str, lambda_arn: str) -> str:
    tools = _load_tools_schema()
    target_configuration = {
        "mcp": {
            "lambda": {
                "lambdaArn": lambda_arn,
                "toolSchema": {"inlinePayload": tools},
            }
        }
    }
    credential = [{"credentialProviderType": "GATEWAY_IAM_ROLE"}]

    # List existing targets
    try:
        listed = control.list_gateway_targets(gatewayIdentifier=gateway_id)
    except ClientError:
        listed = {"items": []}
    items = listed.get("items") or listed.get("targets") or []
    match = next((t for t in items if t.get("name") == TARGET_NAME), None)
    if match:
        target_id = match.get("targetId") or match.get("gatewayTargetId")
        print(f"Updating gateway target {TARGET_NAME} ({target_id})")
        control.update_gateway_target(
            gatewayIdentifier=gateway_id,
            targetId=target_id,
            name=TARGET_NAME,
            targetConfiguration=target_configuration,
            credentialProviderConfigurations=credential,
        )
        return target_id
    print(f"Creating gateway target {TARGET_NAME}")
    resp = control.create_gateway_target(
        gatewayIdentifier=gateway_id,
        name=TARGET_NAME,
        targetConfiguration=target_configuration,
        credentialProviderConfigurations=credential,
    )
    return resp.get("targetId") or resp.get("gatewayTargetId") or TARGET_NAME


def _bootstrap_env(secret_name: str) -> dict[str, str]:
    from server.config import load_local_env

    os.environ.setdefault("RENDERHAUS_SECRETS_NAME", secret_name)
    load_local_env()
    keys = [
        "MUREKA_API_KEY",
        "MUREKA_API_URL",
        "MUREKA_MODEL",
        "MUREKA_DRY_RUN",
    ]
    return {k: os.getenv(k, "") for k in keys if os.getenv(k)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=os.getenv("AWS_REGION") or "us-east-1")
    parser.add_argument(
        "--secret-name",
        default=os.getenv("RENDERHAUS_SECRETS_NAME") or DEFAULT_SECRET_NAME,
    )
    args = parser.parse_args()
    region = args.region
    secret_name = args.secret_name
    os.environ.setdefault("AWS_REGION", region)

    env = _bootstrap_env(secret_name)
    session = boto3.session.Session(region_name=region)
    account = session.client("sts").get_caller_identity()["Account"]
    iam = session.client("iam")
    lam = session.client("lambda")
    control = session.client("bedrock-agentcore-control", region_name=region)

    lambda_role = _ensure_lambda_role(iam, account, region, secret_name)
    lambda_arn = _upsert_lambda(
        lam,
        role_arn=lambda_role,
        region=region,
        secret_name=secret_name,
        env=env,
    )
    gateway_role = _ensure_gateway_role(iam, account, region, lambda_arn)
    gateway_id, gateway_url = _upsert_gateway(control, role_arn=gateway_role)
    target_id = _upsert_target(control, gateway_id=gateway_id, lambda_arn=lambda_arn)

    out = ROOT / ".env.agentcore.gateway"
    out.write_text(
        "\n".join(
            [
                f"AGENTCORE_GATEWAY_URL={gateway_url}",
                f"AGENTCORE_GATEWAY_ID={gateway_id}",
                f"AGENTCORE_MUREKA_TARGET_ID={target_id}",
                f"AGENTCORE_MUREKA_LAMBDA_ARN={lambda_arn}",
                f"AGENTCORE_REGION={region}",
                f"AWS_REGION={region}",
                "",
            ]
        )
    )
    print(f"Wrote {out}")
    print(f"Gateway URL: {gateway_url}")
    print("Next: set AGENTCORE_GATEWAY_URL in Secrets Manager / runtime env, then redeploy AgentCore runtime.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
