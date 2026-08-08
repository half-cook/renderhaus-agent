#!/usr/bin/env python3
"""One-time: IAM OIDC role for GitHub Actions + repo secret/environment."""

from __future__ import annotations

import json
import subprocess
import sys
import time

import boto3
from botocore.exceptions import ClientError


ACCOUNT = "648597472910"
REGION = "us-east-1"
ROLE_NAME = "RenderhausGitHubActionsDeployRole"
OIDC_PROVIDER_ARN = f"arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"
REPO = "half-cook/renderhaus-agent"
SECRET_NAME = "renderhaus/app"


def ensure_role(iam) -> str:
    role_arn = f"arn:aws:iam::{ACCOUNT}:role/{ROLE_NAME}"
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Federated": OIDC_PROVIDER_ARN},
                "Action": "sts:AssumeRoleWithWebIdentity",
                "Condition": {
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                    },
                    "StringLike": {
                        # PRs + branches in this repo
                        "token.actions.githubusercontent.com:sub": f"repo:{REPO}:*",
                    },
                },
            }
        ],
    }
    try:
        iam.get_role(RoleName=ROLE_NAME)
        print(f"Role exists: {role_arn}")
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchEntity":
            raise
        iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="GitHub Actions OIDC deploy role for Renderhaus AgentCore/Gateway",
            MaxSessionDuration=3600,
        )
        print(f"Created role: {role_arn}")

    iam.update_assume_role_policy(RoleName=ROLE_NAME, PolicyDocument=json.dumps(trust))

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "SecretsRead",
                "Effect": "Allow",
                "Action": [
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:DescribeSecret",
                ],
                "Resource": [
                    f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:{SECRET_NAME}-*",
                    f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:{SECRET_NAME}",
                ],
            },
            {
                "Sid": "LambdaDeploy",
                "Effect": "Allow",
                "Action": [
                    "lambda:CreateFunction",
                    "lambda:UpdateFunctionCode",
                    "lambda:UpdateFunctionConfiguration",
                    "lambda:GetFunction",
                    "lambda:GetFunctionConfiguration",
                    "lambda:PublishVersion",
                    "lambda:TagResource",
                ],
                "Resource": [
                    f"arn:aws:lambda:{REGION}:{ACCOUNT}:function:renderhaus-*",
                ],
            },
            {
                "Sid": "IamForDeployedRoles",
                "Effect": "Allow",
                "Action": [
                    "iam:CreateRole",
                    "iam:GetRole",
                    "iam:UpdateAssumeRolePolicy",
                    "iam:PutRolePolicy",
                    "iam:GetRolePolicy",
                    "iam:TagRole",
                ],
                "Resource": [
                    f"arn:aws:iam::{ACCOUNT}:role/RenderhausMurekaLambdaRole",
                    f"arn:aws:iam::{ACCOUNT}:role/RenderhausMurekaGatewayRole",
                    f"arn:aws:iam::{ACCOUNT}:role/RenderhausAgentCoreRuntimeRole",
                ],
            },
            {
                "Sid": "PassRoles",
                "Effect": "Allow",
                "Action": "iam:PassRole",
                "Resource": [
                    f"arn:aws:iam::{ACCOUNT}:role/RenderhausMurekaLambdaRole",
                    f"arn:aws:iam::{ACCOUNT}:role/RenderhausMurekaGatewayRole",
                    f"arn:aws:iam::{ACCOUNT}:role/RenderhausAgentCoreRuntimeRole",
                ],
            },
            {
                "Sid": "EcrPush",
                "Effect": "Allow",
                "Action": [
                    "ecr:GetAuthorizationToken",
                ],
                "Resource": "*",
            },
            {
                "Sid": "EcrRepo",
                "Effect": "Allow",
                "Action": [
                    "ecr:CreateRepository",
                    "ecr:DescribeRepositories",
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:CompleteLayerUpload",
                    "ecr:UploadLayerPart",
                    "ecr:InitiateLayerUpload",
                    "ecr:PutImage",
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                ],
                "Resource": [
                    f"arn:aws:ecr:{REGION}:{ACCOUNT}:repository/renderhaus-agentcore",
                ],
            },
            {
                "Sid": "AgentCoreControl",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:*",
                ],
                "Resource": "*",
            },
            {
                "Sid": "StsIdentity",
                "Effect": "Allow",
                "Action": ["sts:GetCallerIdentity"],
                "Resource": "*",
            },
        ],
    }
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="RenderhausGitHubActionsDeployPolicy",
        PolicyDocument=json.dumps(policy),
    )
    print("Attached inline deploy policy")
    time.sleep(5)
    return role_arn


def ensure_github(role_arn: str) -> None:
    # Environment (empty body = create/update with defaults)
    subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "PUT",
            f"repos/{REPO}/environments/production",
            "--input",
            "-",
        ],
        input=b"{}",
        check=True,
    )
    print("Ensured GitHub environment: production")

    # Secrets
    subprocess.run(
        ["gh", "secret", "set", "AWS_ROLE_TO_ASSUME", "-R", REPO, "--body", role_arn],
        check=True,
    )
    print("Set secret AWS_ROLE_TO_ASSUME")

    subprocess.run(
        [
            "gh",
            "secret",
            "set",
            "RENDERHAUS_SECRETS_NAME",
            "-R",
            REPO,
            "--body",
            SECRET_NAME,
        ],
        check=True,
    )
    print("Set secret RENDERHAUS_SECRETS_NAME")


def main() -> int:
    iam = boto3.client("iam")
    role_arn = ensure_role(iam)
    ensure_github(role_arn)
    print("\nDone.")
    print(f"Role: {role_arn}")
    print("Next: push workflows (if not already) then Actions → Deploy → Run workflow")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"setup failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
