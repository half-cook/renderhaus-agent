#!/usr/bin/env python3
"""Hit the live AgentCore Gateway MCP endpoint: tools/list, then one dry-run tool."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.config import load_local_env  # noqa: E402
from server.secrets import clear_secrets_cache  # noqa: E402

PROTOCOL_VERSION = "2025-03-26"


def _parse_mcp_body(response: httpx.Response) -> dict:
    text = response.text
    if "data:" in text:
        for line in text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
    return response.json()


def _post(url: str, payload: dict, *, region: str, sign: bool) -> httpx.Response:
    body = json.dumps(payload)
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": PROTOCOL_VERSION,
    }
    if sign:
        session = boto3.Session(region_name=region)
        creds = session.get_credentials()
        if creds is None:
            raise RuntimeError("No AWS credentials available to SigV4-sign Gateway requests.")
        frozen = creds.get_frozen_credentials()
        request = AWSRequest(method="POST", url=url, data=body, headers=headers)
        SigV4Auth(frozen, "bedrock-agentcore", region).add_auth(request)
        headers = dict(request.headers)
    return httpx.post(url, headers=headers, content=body, timeout=60.0)


def _mcp_json(url: str, payload: dict, *, region: str, sign: bool) -> tuple[int, dict]:
    response = _post(url, payload, region=region, sign=sign)
    if response.status_code >= 400:
        try:
            body = _parse_mcp_body(response)
        except (json.JSONDecodeError, ValueError):
            body = {"error": {"message": response.text[:400]}}
        return response.status_code, body
    return response.status_code, _parse_mcp_body(response)


def _list_tools(url: str, *, region: str) -> tuple[list[str], bool]:
    names: list[str] = []
    cursor = None
    sign_choice: bool | None = None
    while True:
        payload: dict = {"jsonrpc": "2.0", "id": "list-tools-request", "method": "tools/list"}
        if cursor:
            payload["params"] = {"cursor": cursor}
        listed = None
        status = 0
        for sign in ((sign_choice,) if sign_choice is not None else (True, False)):
            status, listed = _mcp_json(url, payload, region=region, sign=sign)
            print(f"tools/list sigv4={sign} HTTP {status}")
            if status < 400 and listed is not None and not listed.get("error"):
                sign_choice = sign
                break
        if listed is None or listed.get("error"):
            message = (listed or {}).get("error") or f"HTTP {status}"
            raise RuntimeError(f"tools/list failed: {message}")
        result = listed.get("result") or {}
        names.extend(str(tool.get("name")) for tool in (result.get("tools") or []))
        cursor = result.get("nextCursor")
        if not cursor:
            break
    if sign_choice is None:
        raise RuntimeError("tools/list did not succeed with or without SigV4")
    return names, sign_choice


def main() -> int:
    clear_secrets_cache()
    load_local_env()
    hint = dotenv_values(ROOT / ".env.agentcore.gateway")
    url = (os.getenv("AGENTCORE_GATEWAY_URL") or hint.get("AGENTCORE_GATEWAY_URL") or "").strip()
    region = os.getenv("AWS_REGION") or os.getenv("AGENTCORE_REGION") or "us-east-1"
    gateway_id = (os.getenv("AGENTCORE_GATEWAY_ID") or hint.get("AGENTCORE_GATEWAY_ID") or "").strip()
    if not url:
        print("AGENTCORE_GATEWAY_URL is empty after loading secrets.", file=sys.stderr)
        return 1

    print(f"Gateway URL: {url}")
    if gateway_id:
        control = boto3.client("bedrock-agentcore-control", region_name=region)
        detail = control.get_gateway(gatewayIdentifier=gateway_id)
        gateway = detail.get("gateway") or detail
        print(f"authorizerType={gateway.get('authorizerType')!r} status={gateway.get('status')!r}")

    try:
        names, sign = _list_tools(url, region=region)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"tools ({len(names)}):")
    for name in names:
        print(f"  {name}")

    call_name = next((name for name in names if name.endswith("list_seedance_models")), None)
    if call_name is None:
        print("No list_seedance_models tool on the gateway.", file=sys.stderr)
        return 1

    call_payload = {
        "jsonrpc": "2.0",
        "id": "call-tool-request",
        "method": "tools/call",
        "params": {"name": call_name, "arguments": {}},
    }
    status, result = _mcp_json(url, call_payload, region=region, sign=sign)
    print(f"tools/call {call_name} HTTP {status}")
    print(json.dumps(result, indent=2, default=str)[:2000])
    if status >= 400 or result.get("error"):
        return 1
    content = ((result.get("result") or {}).get("content") or [])
    text = content[0].get("text") if content and isinstance(content[0], dict) else ""
    try:
        inner = json.loads(text) if text else {}
    except json.JSONDecodeError:
        inner = {}
    if isinstance(inner, dict) and inner.get("error"):
        print(f"Lambda tool error: {inner.get('error_type')}: {inner.get('error')}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
