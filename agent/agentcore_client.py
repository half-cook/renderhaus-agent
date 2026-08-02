"""Client for invoking the Renderhaus agent hosted on Bedrock AgentCore Runtime."""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

import boto3


def agentcore_enabled() -> bool:
    return bool((os.getenv("AGENTCORE_RUNTIME_ARN") or "").strip())


def agentcore_region() -> str:
    return (
        os.getenv("AGENTCORE_REGION")
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
        or "us-east-1"
    )


def _runtime_arn() -> str:
    arn = (os.getenv("AGENTCORE_RUNTIME_ARN") or "").strip()
    if not arn:
        raise RuntimeError("AGENTCORE_RUNTIME_ARN is not set.")
    return arn


def _session_id(session_id: str | None) -> str:
    """AgentCore requires runtimeSessionId length >= 33."""
    raw = (session_id or "").strip() or f"renderhaus-{uuid.uuid4().hex}"
    cleaned = re.sub(r"[^A-Za-z0-9_=+-]", "-", raw)
    if len(cleaned) < 33:
        cleaned = f"{cleaned}-{uuid.uuid4().hex}"
    return cleaned[:256]


def invoke(
    action: str,
    payload: dict[str, Any] | None = None,
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    body = {"action": action, **(payload or {})}
    client = boto3.client("bedrock-agentcore", region_name=agentcore_region())
    response = client.invoke_agent_runtime(
        agentRuntimeArn=_runtime_arn(),
        runtimeSessionId=_session_id(session_id),
        payload=json.dumps({"input": body}).encode("utf-8"),
        qualifier=os.getenv("AGENTCORE_QUALIFIER") or "DEFAULT",
        contentType="application/json",
        accept="application/json",
    )
    stream = response.get("response")
    if stream is None:
        raise RuntimeError("AgentCore returned an empty response stream.")
    raw = stream.read() if hasattr(stream, "read") else stream
    if isinstance(raw, memoryview):
        raw = raw.tobytes()
    if isinstance(raw, bytes):
        text = raw.decode("utf-8")
    else:
        text = str(raw)
    data = json.loads(text)
    if isinstance(data, dict) and isinstance(data.get("output"), dict):
        output = data["output"]
        if output.get("error"):
            raise RuntimeError(str(output["error"]))
        return output
    if isinstance(data, dict) and data.get("error"):
        raise RuntimeError(str(data["error"]))
    if isinstance(data, dict):
        return data
    raise RuntimeError(f"Unexpected AgentCore response: {data!r}")
