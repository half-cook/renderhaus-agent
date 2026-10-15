#!/usr/bin/env python3
"""One-time, additive: ECR repo + GitHub OIDC provider + least-privilege push role for web-image.yml.

Usage: python scripts/setup_ecr_ci.py [--extra-ref refs/heads/feat/ci-arm-ecr]
"""
from __future__ import annotations

import argparse
import json

import boto3
from botocore.exceptions import ClientError

ACCOUNT, REGION = "648597472910", "us-east-1"
REPO_NAME, ROLE_NAME = "renderhaus-agent", "RenderhausGitHubEcrPushStaging"
GH_REPO = "half-cook/renderhaus-agent"
OIDC_URL = "token.actions.githubusercontent.com"
OIDC_ARN = f"arn:aws:iam::{ACCOUNT}:oidc-provider/{OIDC_URL}"
TAGS = [{"Key": "Project", "Value": "renderhaus"}, {"Key": "Env", "Value": "beta"}]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extra-ref", action="append", default=[])
    refs = ["refs/heads/staging", *ap.parse_args().extra_ref]
    ecr, iam = boto3.client("ecr", region_name=REGION), boto3.client("iam")

    try:
        repo = ecr.create_repository(repositoryName=REPO_NAME, imageScanningConfiguration={"scanOnPush": True},
                                     encryptionConfiguration={"encryptionType": "AES256"}, tags=TAGS)["repository"]
        print("created ECR", repo["repositoryUri"])
    except ecr.exceptions.RepositoryAlreadyExistsException:
        repo = ecr.describe_repositories(repositoryNames=[REPO_NAME])["repositories"][0]
        print("ECR exists", repo["repositoryUri"])
    ecr.put_lifecycle_policy(repositoryName=REPO_NAME, lifecyclePolicyText=json.dumps({"rules": [
        {"rulePriority": 1, "description": "drop untagged after 3d", "selection": {"tagStatus": "untagged",
         "countType": "sinceImagePushed", "countUnit": "days", "countNumber": 3}, "action": {"type": "expire"}},
        {"rulePriority": 2, "description": "keep 30 images", "selection": {"tagStatus": "any",
         "countType": "imageCountMoreThan", "countNumber": 30}, "action": {"type": "expire"}}]}))

    try:
        iam.get_open_id_connect_provider(OpenIDConnectProviderArn=OIDC_ARN)
        print("OIDC provider exists")
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise
        iam.create_open_id_connect_provider(Url=f"https://{OIDC_URL}", ClientIDList=["sts.amazonaws.com"],
                                            ThumbprintList=["6938fd4d98bab03faadb97b34396831e3780aea1"], Tags=TAGS)
        print("created OIDC provider")

    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Federated": OIDC_ARN},
             "Action": "sts:AssumeRoleWithWebIdentity", "Condition": {
                 "StringEquals": {f"{OIDC_URL}:aud": "sts.amazonaws.com",
                                  f"{OIDC_URL}:sub": [f"repo:{GH_REPO}:ref:{r}" for r in refs]}}}]}
    try:
        iam.create_role(RoleName=ROLE_NAME, AssumeRolePolicyDocument=json.dumps(trust), MaxSessionDuration=3600,
                        Description="GitHub Actions (staging) push-only to ECR renderhaus-agent", Tags=TAGS)
        print("created role")
    except iam.exceptions.EntityAlreadyExistsException:
        iam.update_assume_role_policy(RoleName=ROLE_NAME, PolicyDocument=json.dumps(trust))
        print("updated role trust", refs)
    iam.put_role_policy(RoleName=ROLE_NAME, PolicyName="ecr-push", PolicyDocument=json.dumps({
        "Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
            {"Effect": "Allow", "Resource": repo["repositoryArn"], "Action": [
                "ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer",
                "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage",
                "ecr:DescribeImages"]}]}))
    print("role", f"arn:aws:iam::{ACCOUNT}:role/{ROLE_NAME}")


if __name__ == "__main__":
    main()
