#!/usr/bin/env python3
"""Create Remotion IAM resources, deploy the renderer, and deploy the Renderhaus site."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web"
DEPLOYMENT_PATH = ROOT / ".renderhaus" / "remotion" / "deployment.json"
ROLE_NAME = "remotion-lambda-role"


def _run_node(command: str, *, region: str, marker: str) -> dict[str, object]:
    env = dict(os.environ)
    env["REMOTION_APP_REGION"] = region
    completed = subprocess.run(
        ["node", "scripts/remotion-lambda.mjs", command],
        cwd=WEB_ROOT,
        env=env,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    print(completed.stdout, end="")
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(marker):
            value = json.loads(line.removeprefix(marker))
            if isinstance(value, dict):
                return value
    raise RuntimeError(f"Remotion helper did not return {marker.rstrip('=')}")


def _ensure_lambda_role(iam, role_policy: dict[str, object]) -> str:
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
    try:
        role = iam.get_role(RoleName=ROLE_NAME)["Role"]
        print(f"IAM role exists: {role['Arn']}")
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchEntity":
            raise
        role = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Execution role for Remotion Lambda render functions",
        )["Role"]
        print(f"Created IAM role: {role['Arn']}")
    iam.update_assume_role_policy(
        RoleName=ROLE_NAME,
        PolicyDocument=json.dumps(trust),
    )
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="RemotionLambdaRuntimePolicy",
        PolicyDocument=json.dumps(role_policy),
    )
    return str(role["Arn"])


def _attach_deployer_policy(iam, sts, user_policy: dict[str, object]) -> None:
    arn = str(sts.get_caller_identity()["Arn"])
    if ":user/" in arn:
        user_name = arn.split(":user/", 1)[1]
        iam.put_user_policy(
            UserName=user_name,
            PolicyName="RenderhausRemotionLambdaDeployPolicy",
            PolicyDocument=json.dumps(user_policy),
        )
        print(f"Attached the Remotion deploy policy to IAM user {user_name}.")
        return
    if ":assumed-role/" in arn:
        role_name = arn.split(":assumed-role/", 1)[1].split("/", 1)[0]
        iam.put_role_policy(
            RoleName=role_name,
            PolicyName="RenderhausRemotionLambdaDeployPolicy",
            PolicyDocument=json.dumps(user_policy),
        )
        print(f"Attached the Remotion deploy policy to IAM role {role_name}.")
        return
    raise RuntimeError(f"Unsupported AWS principal for automatic setup: {arn}")


def _sync_runtime_settings(session: boto3.Session, deployment: dict[str, object]) -> None:
    secret_id = (
        os.getenv("RENDERHAUS_SECRETS_ARN")
        or os.getenv("RENDERHAUS_SECRETS_NAME")
        or ""
    ).strip()
    if not secret_id:
        print("No Renderhaus Secrets Manager locator is configured; skipped runtime sync.")
        return
    client = session.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_id)
    raw = response.get("SecretString") or "{}"
    values = json.loads(raw)
    if not isinstance(values, dict):
        raise RuntimeError(f"Secret {secret_id} must contain a JSON object.")
    values.update(
        {
            "REMOTION_APP_REGION": str(deployment["region"]),
            "REMOTION_APP_FUNCTION_NAME": str(deployment["functionName"]),
            "REMOTION_APP_SERVE_URL": str(deployment["serveUrl"]),
            "REMOTION_APP_BUCKET_NAME": str(deployment["bucketName"]),
        }
    )
    client.put_secret_value(SecretId=secret_id, SecretString=json.dumps(values))
    print(f"Updated Remotion runtime settings in Secrets Manager ({secret_id}).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=os.getenv("AWS_REGION") or "us-east-1")
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="Sync an existing deployment file into Secrets Manager without redeploying.",
    )
    args = parser.parse_args()

    from server.config import load_local_env

    load_local_env()
    session = boto3.Session(region_name=args.region)
    if args.sync_only:
        deployment = json.loads(DEPLOYMENT_PATH.read_text())
        if not isinstance(deployment, dict):
            raise RuntimeError(f"Invalid deployment metadata: {DEPLOYMENT_PATH}")
        _sync_runtime_settings(session, deployment)
        return 0
    policies = _run_node(
        "policies",
        region=args.region,
        marker="RENDERHAUS_REMOTION_POLICIES=",
    )
    role_policy = policies.get("rolePolicy")
    user_policy = policies.get("userPolicy")
    if not isinstance(role_policy, dict) or not isinstance(user_policy, dict):
        raise RuntimeError("Remotion returned invalid IAM policies.")

    iam = session.client("iam")
    _ensure_lambda_role(iam, role_policy)
    _attach_deployer_policy(iam, session.client("sts"), user_policy)
    time.sleep(5)

    deployment = _run_node(
        "deploy",
        region=args.region,
        marker="RENDERHAUS_REMOTION_DEPLOYMENT=",
    )
    DEPLOYMENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEPLOYMENT_PATH.write_text(json.dumps(deployment, indent=2) + "\n")
    print(f"Saved deployment metadata: {DEPLOYMENT_PATH}")
    _sync_runtime_settings(session, deployment)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
