#!/usr/bin/env python3
"""Deploy provider tools as Lambdas + AgentCore Gateway targets.

Creates/updates:
  - Shared IAM role for provider Lambdas (Secrets Manager + logs)
  - IAM role for the Gateway (lambda:InvokeFunction on renderhaus-*-tools)
  - One Lambda per provider: renderhaus-{id}-tools
  - AgentCore Gateway renderhaus-mureka-gateway (existing name, reused)
  - One Gateway target per provider with the generated tool schema

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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers.catalog import ProviderSpec, parse_provider_ids
from providers.registry import load_committed_schemas

HANDLER_PATH = ROOT / "lambdas" / "handler.py"
PROVIDERS_DIR = ROOT / "providers"

LAMBDA_ROLE_NAME = "RenderhausGatewayLambdaRole"
GATEWAY_ROLE_NAME = "RenderhausMurekaGatewayRole"
GATEWAY_NAME = "renderhaus-mureka-gateway"
DEFAULT_SECRET_NAME = "renderhaus/app"


def build_lambda_zip() -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        package = tmp_path / "package"
        package.mkdir()
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
        dest_providers = package / "providers"
        shutil.copytree(
            PROVIDERS_DIR,
            dest_providers,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        shutil.copy2(HANDLER_PATH, package / "handler.py")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in package.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(package).as_posix())
        return buf.getvalue()


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
            Description="Lambda execution role for Renderhaus Gateway provider tools",
        )
    iam.put_role_policy(
        RoleName=LAMBDA_ROLE_NAME,
        PolicyName="RenderhausGatewayLambdaPolicy",
        PolicyDocument=json.dumps(policy),
    )
    time.sleep(8)
    return role_arn


def _ensure_gateway_role(iam, account: str, region: str) -> str:
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
    lambda_arn = f"arn:aws:lambda:{region}:{account}:function:renderhaus-*-tools"
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
            Description="AgentCore Gateway role for Renderhaus provider Lambdas",
        )
    iam.update_assume_role_policy(RoleName=GATEWAY_ROLE_NAME, PolicyDocument=json.dumps(trust))
    iam.put_role_policy(
        RoleName=GATEWAY_ROLE_NAME,
        PolicyName="RenderhausMurekaGatewayPolicy",
        PolicyDocument=json.dumps(policy),
    )
    time.sleep(5)
    return role_arn


def _upsert_lambda(
    lam,
    *,
    spec: ProviderSpec,
    role_arn: str,
    region: str,
    secret_name: str,
    env: dict[str, str],
    zip_bytes: bytes,
) -> str:
    runtime_env = {
        "RENDERHAUS_PROVIDER": spec.id,
        "RENDERHAUS_SECRETS_NAME": secret_name,
        "RENDERHAUS_MEDIA_DIR": "/tmp/renderhaus/media",
        "AWS_REGION_NAME": region,
        **spec.default_env,
    }
    for key in spec.env_keys:
        if env.get(key):
            runtime_env[key] = env[key]

    config = {
        "FunctionName": spec.function_name,
        "Runtime": "python3.11",
        "Role": role_arn,
        "Handler": "handler.handler",
        "Timeout": 120,
        "MemorySize": 512,
        "Architectures": ["arm64"],
        "Environment": {"Variables": runtime_env},
    }
    try:
        lam.get_function(FunctionName=spec.function_name)
        print(f"Updating Lambda {spec.function_name}")
        lam.update_function_code(
            FunctionName=spec.function_name,
            ZipFile=zip_bytes,
            Architectures=config["Architectures"],
        )
        time.sleep(3)
        config_update = {
            key: value
            for key, value in config.items()
            if key not in ("FunctionName", "Architectures")
        }
        lam.update_function_configuration(FunctionName=spec.function_name, **config_update)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        print(f"Creating Lambda {spec.function_name}")
        lam.create_function(**config, Code={"ZipFile": zip_bytes}, Publish=True)
        time.sleep(5)
    fn = lam.get_function(FunctionName=spec.function_name)
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
    existing = _find_gateway(control, GATEWAY_NAME)
    create_kwargs = {
        "name": GATEWAY_NAME,
        "roleArn": role_arn,
        "protocolType": "MCP",
        "authorizerType": "NONE",
        "description": "Renderhaus provider tools via Lambda",
    }
    if existing:
        gateway_id = existing.get("gatewayId") or existing.get("gatewayIdentifier") or existing.get("id")
        print(f"Gateway exists: {gateway_id}")
    else:
        print(f"Creating gateway {GATEWAY_NAME}")
        try:
            resp = control.create_gateway(**create_kwargs)
        except ClientError:
            create_kwargs.pop("authorizerType", None)
            resp = control.create_gateway(
                name=GATEWAY_NAME,
                roleArn=role_arn,
                protocolType="MCP",
                description="Renderhaus provider tools via Lambda",
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


def _upsert_target(control, *, spec: ProviderSpec, gateway_id: str, lambda_arn: str) -> str:
    tools = load_committed_schemas(spec)
    target_configuration = {
        "mcp": {
            "lambda": {
                "lambdaArn": lambda_arn,
                "toolSchema": {"inlinePayload": tools},
            }
        }
    }
    credential = [{"credentialProviderType": "GATEWAY_IAM_ROLE"}]
    try:
        listed = control.list_gateway_targets(gatewayIdentifier=gateway_id)
    except ClientError:
        listed = {"items": []}
    items = listed.get("items") or listed.get("targets") or []
    match = next((item for item in items if item.get("name") == spec.target_name), None)
    if match:
        target_id = match.get("targetId") or match.get("gatewayTargetId")
        print(f"Updating gateway target {spec.target_name} ({target_id})")
        control.update_gateway_target(
            gatewayIdentifier=gateway_id,
            targetId=target_id,
            name=spec.target_name,
            targetConfiguration=target_configuration,
            credentialProviderConfigurations=credential,
        )
        return target_id
    print(f"Creating gateway target {spec.target_name}")
    resp = control.create_gateway_target(
        gatewayIdentifier=gateway_id,
        name=spec.target_name,
        targetConfiguration=target_configuration,
        credentialProviderConfigurations=credential,
    )
    return resp.get("targetId") or resp.get("gatewayTargetId") or spec.target_name


def _bootstrap_env(secret_name: str, specs: tuple[ProviderSpec, ...]) -> dict[str, str]:
    from server.config import load_local_env

    os.environ.setdefault("RENDERHAUS_SECRETS_NAME", secret_name)
    load_local_env()
    keys = {"RENDERHAUS_MEDIA_DIR"}
    for spec in specs:
        keys.update(spec.env_keys)
        keys.update(spec.default_env)
    return {key: os.getenv(key, "") for key in sorted(keys) if os.getenv(key)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=os.getenv("AWS_REGION") or "us-east-1")
    parser.add_argument(
        "--secret-name",
        default=os.getenv("RENDERHAUS_SECRETS_NAME") or DEFAULT_SECRET_NAME,
    )
    parser.add_argument(
        "--provider",
        default="all",
        help="Provider id, comma-separated list, or all",
    )
    parser.add_argument(
        "--build-zip-only",
        action="store_true",
        help="Build the Lambda zip and exit without calling AWS",
    )
    parser.add_argument(
        "--zip-out",
        default="",
        help="Optional path to write the Lambda zip when using --build-zip-only",
    )
    args = parser.parse_args()
    specs = parse_provider_ids(args.provider)

    if args.build_zip_only:
        zip_bytes = build_lambda_zip()
        if args.zip_out:
            Path(args.zip_out).write_bytes(zip_bytes)
            print(f"wrote {args.zip_out} ({len(zip_bytes)} bytes)")
        else:
            print(f"built lambda zip ({len(zip_bytes)} bytes)")
        return 0

    region = args.region
    secret_name = args.secret_name
    os.environ.setdefault("AWS_REGION", region)

    env = _bootstrap_env(secret_name, specs)
    session = boto3.session.Session(region_name=region)
    account = session.client("sts").get_caller_identity()["Account"]
    iam = session.client("iam")
    lam = session.client("lambda")
    control = session.client("bedrock-agentcore-control", region_name=region)

    lambda_role = _ensure_lambda_role(iam, account, region, secret_name)
    zip_bytes = build_lambda_zip()
    lambda_arns: dict[str, str] = {}
    target_ids: dict[str, str] = {}
    for spec in specs:
        lambda_arns[spec.id] = _upsert_lambda(
            lam,
            spec=spec,
            role_arn=lambda_role,
            region=region,
            secret_name=secret_name,
            env=env,
            zip_bytes=zip_bytes,
        )
    gateway_role = _ensure_gateway_role(iam, account, region)
    gateway_id, gateway_url = _upsert_gateway(control, role_arn=gateway_role)
    for spec in specs:
        target_ids[spec.id] = _upsert_target(
            control,
            spec=spec,
            gateway_id=gateway_id,
            lambda_arn=lambda_arns[spec.id],
        )

    lines = [
        f"AGENTCORE_GATEWAY_URL={gateway_url}",
        f"AGENTCORE_GATEWAY_ID={gateway_id}",
        f"AGENTCORE_REGION={region}",
        f"AWS_REGION={region}",
    ]
    for spec in specs:
        key = spec.id.upper()
        lines.append(f"AGENTCORE_{key}_TARGET_ID={target_ids[spec.id]}")
        lines.append(f"AGENTCORE_{key}_LAMBDA_ARN={lambda_arns[spec.id]}")
    out = ROOT / ".env.agentcore.gateway"
    out.write_text("\n".join(lines) + "\n")
    print(f"Wrote {out}")
    print(f"Gateway URL: {gateway_url}")
    print("Next: set AGENTCORE_GATEWAY_URL in Secrets Manager / runtime env, then redeploy AgentCore runtime.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
