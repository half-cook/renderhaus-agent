"""Load application configuration from AWS Secrets Manager."""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any

import boto3
from botocore.exceptions import ClientError


logger = logging.getLogger(__name__)

# Never sync or inject these into Secrets Manager payloads.
EXCLUDED_SECRET_KEYS = {
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
    "AWS_SECURITY_TOKEN",
}

# Bootstrap keys that may remain in a local .env file to find the secret.
BOOTSTRAP_ENV_KEYS = {
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "RENDERHAUS_SECRETS_NAME",
    "RENDERHAUS_SECRETS_ARN",
    "AGENTCORE_RUNTIME",
}


def secrets_locator() -> str | None:
    return (
        (os.getenv("RENDERHAUS_SECRETS_ARN") or "").strip()
        or (os.getenv("RENDERHAUS_SECRETS_NAME") or "").strip()
        or None
    )


def aws_region() -> str:
    return os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"


@lru_cache(maxsize=4)
def fetch_secret_map(secret_id: str) -> dict[str, str]:
    client = boto3.client("secretsmanager", region_name=aws_region())
    response = client.get_secret_value(SecretId=secret_id)
    payload = response.get("SecretString") or ""
    if not payload and response.get("SecretBinary"):
        payload = response["SecretBinary"].decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise RuntimeError(f"Secret {secret_id} must be a JSON object of string values.")
    result: dict[str, str] = {}
    for key, value in data.items():
        if key in EXCLUDED_SECRET_KEYS:
            continue
        if value is None:
            continue
        text = str(value).strip()
        if text:
            result[str(key)] = text
    return result


def apply_secret_map(values: dict[str, str], *, override: bool = True) -> list[str]:
    applied: list[str] = []
    for key, value in values.items():
        if key in EXCLUDED_SECRET_KEYS:
            continue
        if not override and os.getenv(key):
            continue
        os.environ[key] = value
        applied.append(key)
    return applied


def load_secrets_from_manager(*, override: bool = True) -> list[str]:
    """Fetch RENDERHAUS_SECRETS_* and inject into the process environment."""
    secret_id = secrets_locator()
    if not secret_id:
        return []
    try:
        values = fetch_secret_map(secret_id)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "ClientError")
        raise RuntimeError(
            f"Failed to load AWS Secrets Manager secret {secret_id}: {code}"
        ) from exc
    applied = apply_secret_map(values, override=override)
    logger.info("Loaded %s keys from Secrets Manager (%s)", len(applied), secret_id)
    return applied


def clear_secrets_cache() -> None:
    fetch_secret_map.cache_clear()


def secret_payload_from_mapping(values: dict[str, Any]) -> dict[str, str]:
    payload: dict[str, str] = {}
    for key, value in values.items():
        if key in EXCLUDED_SECRET_KEYS or key in BOOTSTRAP_ENV_KEYS:
            continue
        if value is None:
            continue
        text = str(value).strip()
        if text:
            payload[str(key)] = text
    return payload
