"""Small fal queue HTTP client.

Official protocol, checked 2026-10-08:
https://docs.fal.ai/model-apis/model-endpoints/queue
https://fal.ai/docs/documentation/model-apis/inference/queue
Queue lookup routes match the official Python client's RequestHandle.from_request_id:
https://github.com/fal-ai/fal/blob/main/projects/fal_client/src/fal_client/client.py
"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlsplit

import httpx


BASE_URL = "https://queue.fal.run"
STATES = {"IN_QUEUE": "queued", "IN_PROGRESS": "running", "COMPLETED": "succeeded"}


class FalAPIError(RuntimeError):
    def __init__(self, status_code: int, payload: Any):
        super().__init__(f"fal API error {status_code}: {payload}")
        self.status_code = status_code
        self.payload = payload


def dry_run() -> bool:
    return os.getenv("FAL_DRY_RUN", "true").lower() != "false"


def headers() -> dict[str, str]:
    key = os.getenv("FAL_KEY")
    if not key:
        raise RuntimeError("FAL_KEY is required for live fal calls.")
    return {"Authorization": f"Key {key}", "Content-Type": "application/json"}


def request(method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "queue.fal.run":
        raise ValueError("fal queue URLs must use https://queue.fal.run.")
    with httpx.Client(timeout=60) as client:
        response = client.request(method, url, headers=headers(), json=body)
    try:
        payload = response.json()
    except ValueError as exc:
        raise FalAPIError(response.status_code, "Non-JSON response") from exc
    if response.is_error:
        raise FalAPIError(response.status_code, payload)
    if not isinstance(payload, dict):
        raise RuntimeError("fal returned a non-object response.")
    return payload


def submit(endpoint_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return request("POST", f"{BASE_URL}/{endpoint_id}", arguments)


def request_url(endpoint_id: str, request_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", request_id):
        raise ValueError("Invalid fal request id.")
    # fal's clients use the app root for queue lookups, dropping the inference route.
    app_id = "/".join(endpoint_id.split("/")[:2])
    return f"{BASE_URL}/{app_id}/requests/{request_id}"


def status(endpoint_id: str, request_id: str) -> dict[str, Any]:
    return request("GET", f"{request_url(endpoint_id, request_id)}/status")


def result(endpoint_id: str, request_id: str) -> dict[str, Any]:
    return request("GET", request_url(endpoint_id, request_id))


def mapped_status(payload: dict[str, Any]) -> str:
    if payload.get("error") or payload.get("error_type"):
        return "failed"
    state = payload.get("status")
    if state not in STATES:
        raise RuntimeError(f"Unknown fal queue state: {state!r}")
    return STATES[state]
