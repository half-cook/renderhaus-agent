#!/usr/bin/env python3
"""Sync non-empty .env.local values into AWS Secrets Manager."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from dotenv import dotenv_values

from server.secrets import (
    BOOTSTRAP_ENV_KEYS,
    EXCLUDED_SECRET_KEYS,
    clear_secrets_cache,
    secret_payload_from_mapping,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECRET_NAME = "renderhaus/app"


def ensure_secret(client, *, name: str, payload: dict[str, str], description: str) -> str:
    body = json.dumps(payload, indent=2, sort_keys=True)
    try:
        response = client.create_secret(
            Name=name,
            Description=description,
            SecretString=body,
        )
        print(f"Created secret {name}")
        return response["ARN"]
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceExistsException":
            raise
    response = client.put_secret_value(SecretId=name, SecretString=body)
    print(f"Updated secret {name} (version {response.get('VersionId')})")
    describe = client.describe_secret(SecretId=name)
    return describe["ARN"]


def write_bootstrap_env(
    *,
    path: Path,
    secret_name: str,
    region: str,
    keep: dict[str, str],
) -> None:
    lines = [
        "# Bootstrap only — application secrets live in AWS Secrets Manager.",
        f"AWS_REGION={region}",
        f"AWS_DEFAULT_REGION={region}",
        f"RENDERHAUS_SECRETS_NAME={secret_name}",
        "",
    ]
    for key in sorted(keep):
        if key in {"AWS_REGION", "AWS_DEFAULT_REGION", "RENDERHAUS_SECRETS_NAME"}:
            continue
        lines.append(f"{key}={keep[key]}")
    if keep:
        lines.append("")
    path.write_text("\n".join(lines))
    print(f"Wrote bootstrap env to {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--secret-name",
        default=os.getenv("RENDERHAUS_SECRETS_NAME") or DEFAULT_SECRET_NAME,
    )
    parser.add_argument("--region", default=os.getenv("AWS_REGION") or "us-east-1")
    parser.add_argument(
        "--env-file",
        default=str(ROOT / ".env.local"),
        help="Source env file to sync from.",
    )
    parser.add_argument(
        "--rewrite-bootstrap",
        action="store_true",
        help="Backup .env.local and replace it with a thin bootstrap file.",
    )
    parser.add_argument(
        "--keep-local",
        action="append",
        default=[],
        help="Extra key to keep in the bootstrap .env.local (repeatable).",
    )
    args = parser.parse_args()

    env_path = Path(args.env_file).expanduser().resolve()
    if not env_path.is_file():
        print(f"Missing env file: {env_path}", file=sys.stderr)
        return 1

    raw = dotenv_values(env_path)
    payload = secret_payload_from_mapping(raw)
    if not payload:
        print("No non-empty secret/config values found to sync.", file=sys.stderr)
        return 1

    client = boto3.client("secretsmanager", region_name=args.region)
    arn = ensure_secret(
        client,
        name=args.secret_name,
        payload=payload,
        description="Renderhaus app secrets and runtime configuration",
    )
    clear_secrets_cache()
    print(f"Secret ARN: {arn}")
    print(f"Synced {len(payload)} keys (excluded bootstrap/AWS credential keys).")

    if args.rewrite_bootstrap:
        backup = env_path.with_suffix(env_path.suffix + ".bak")
        backup.write_text(env_path.read_text())
        print(f"Backed up {env_path} -> {backup}")
        keep: dict[str, str] = {}
        for key in list(BOOTSTRAP_ENV_KEYS) + list(args.keep_local):
            value = raw.get(key) or os.getenv(key)
            if value and str(value).strip() and key not in EXCLUDED_SECRET_KEYS:
                keep[key] = str(value).strip()
        # Always keep AgentCore pointers locally for offline bootstrap clarity.
        for key in ("AGENTCORE_RUNTIME_ARN", "AGENTCORE_REGION", "AGENTCORE_QUALIFIER"):
            value = raw.get(key)
            if value and str(value).strip():
                keep[key] = str(value).strip()
        write_bootstrap_env(
            path=env_path,
            secret_name=args.secret_name,
            region=args.region,
            keep=keep,
        )

    print("\nSet locally (or keep via --rewrite-bootstrap):")
    print(f"  RENDERHAUS_SECRETS_NAME={args.secret_name}")
    print(f"  AWS_REGION={args.region}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
