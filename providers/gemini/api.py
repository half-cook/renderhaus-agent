"""Bounded Gemini background Interactions client, official docs read 2026-10-09.

https://ai.google.dev/gemini-api/docs/interactions
POST is retried only after 429. Ambiguous paid submissions are never resubmitted.
"""

from __future__ import annotations

import base64
import io
import json
import os
import queue
import threading
import time
import uuid

import httpx
from pydantic import ValidationError

from providers.gemini.contracts import (
    GeminiJudgement,
    GeminiSettings,
    RUBRIC_HASH,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    VERIFIED_MODEL,
    request_body,
    validate_job_id,
)

INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
MAX_RESPONSE_BYTES = 1024 * 1024
TRAINING_METADATA = {
    "training_eligible": False,
    "weights_license": "service-terms",
    "hosted_terms_url": "https://ai.google.dev/gemini-api/terms",
}


class GeminiError(RuntimeError):
    """Safe fixed messages only; upstream content must never enter reports."""


def dry_run() -> bool:
    return os.getenv("GEMINI_DRY_RUN", "true").lower() != "false"


def _base(settings: GeminiSettings) -> dict:
    return {
        "provider": "gemini",
        "model": settings.model,
        "rubric_hash": RUBRIC_HASH,
        "verification": "verified" if settings.model == VERIFIED_MODEL else "UNVERIFIED",
        **TRAINING_METADATA,
    }


def _live_guard(settings: GeminiSettings) -> None:
    if settings.dry_run:
        raise GeminiError("Gemini dry-run is enabled; no judge request made.")
    if settings.model != VERIFIED_MODEL:
        raise GeminiError(
            "UNVERIFIED Gemini model; live judge use is blocked and cost estimate unknown."
        )
    if not os.getenv("GEMINI_API_KEY"):
        raise GeminiError("GEMINI_API_KEY is required for live Gemini evaluation.")


def _request(
    method: str, url: str, settings: GeminiSettings, deadline: float, body: dict | None = None
) -> dict:
    _live_guard(settings)
    for attempt in range(settings.max_retries + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise GeminiError("Gemini judge deadline exceeded; evaluation skipped.")
        status, raw = _read(method, url, body, remaining, deadline)
        retryable = status == 429 or (method == "GET" and 500 <= status < 600)
        if retryable and attempt < settings.max_retries:
            delay = min(0.25 * 2**attempt, max(0, deadline - time.monotonic()))
            time.sleep(delay)
            continue
        if not 200 <= status < 300:
            raise GeminiError("Gemini API request failed; evaluation skipped.")
        try:
            payload = json.loads(raw, object_pairs_hook=_unique_fields)
        except (ValueError, RecursionError):
            raise GeminiError("Gemini returned invalid JSON; evaluation skipped.") from None
        if not isinstance(payload, dict):
            raise GeminiError("Gemini returned an invalid interaction; evaluation skipped.")
        return payload
    raise GeminiError("Gemini retry limit reached; evaluation skipped.")


def _read(method: str, url: str, body: dict | None, timeout: float, deadline: float) -> tuple[int, bytes]:
    outcomes: queue.Queue[tuple[int, bytes] | Exception] = queue.Queue(maxsize=1)
    client_factory = httpx.Client
    key = os.environ["GEMINI_API_KEY"]

    def read_response():
        try:
            with client_factory(timeout=timeout, follow_redirects=False) as client:
                with client.stream(method, url, headers={"x-goog-api-key": key}, json=body) as response:
                    chunks = bytearray()
                    for chunk in response.iter_bytes():
                        if time.monotonic() >= deadline:
                            raise GeminiError("Gemini judge deadline exceeded; evaluation skipped.")
                        if len(chunks) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise GeminiError("Gemini response exceeds byte limit; evaluation skipped.")
                        chunks.extend(chunk)
                    outcomes.put((response.status_code, bytes(chunks)))
        except Exception as exc:
            outcomes.put(exc)

    threading.Thread(target=read_response, daemon=True, name="continuity-qc-gemini").start()
    try:
        outcome = outcomes.get(timeout=timeout)
    except queue.Empty:
        raise GeminiError("Gemini judge deadline exceeded; evaluation skipped.") from None
    if time.monotonic() >= deadline:
        raise GeminiError("Gemini judge deadline exceeded; evaluation skipped.")
    if isinstance(outcome, GeminiError):
        raise outcome
    if isinstance(outcome, Exception):
        raise GeminiError("Gemini transport failed; check the existing interaction before resubmitting.") from None
    return outcome


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    parsed = {}
    for key, value in pairs:
        if key in parsed:
            raise ValueError("Duplicate JSON field.")
        parsed[key] = value
    return parsed


def _normalized(payload: dict, settings: GeminiSettings, expected_job_id: str | None = None) -> dict:
    job_id = payload.get("id")
    try:
        validate_job_id(job_id)
    except ValueError:
        raise GeminiError(
            "Gemini returned an invalid interaction ID; evaluation skipped."
        ) from None
    if payload.get("model") != settings.model:
        raise GeminiError("Gemini returned an unexpected model; evaluation skipped.")
    if expected_job_id is not None and job_id != expected_job_id:
        raise GeminiError("Gemini returned a different interaction; evaluation skipped.")
    base = {**_base(settings), "job_id": job_id, "dry_run": False}
    status = payload.get("status")
    if not isinstance(status, str):
        raise GeminiError("Gemini returned an invalid status; evaluation skipped.")
    if status in {"queued", "in_progress"}:
        return {**base, "status": "queued" if status == "queued" else "running"}
    if status != "completed":
        raise GeminiError("Gemini interaction did not complete; evaluation skipped.")
    steps = payload.get("steps")
    if not isinstance(steps, list):
        raise GeminiError("Gemini returned invalid model output; evaluation skipped.")
    texts = []
    for step in steps:
        if not isinstance(step, dict) or step.get("type") != "model_output":
            continue
        content = step.get("content")
        if not isinstance(content, list):
            raise GeminiError("Gemini returned invalid model output; evaluation skipped.")
        texts.extend(
            part.get("text")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    if len(texts) != 1 or not isinstance(texts[0], str) or len(texts[0]) > 16_384:
        raise GeminiError("Gemini returned no unique bounded judgement; evaluation skipped.")
    try:
        parsed = json.loads(texts[0], object_pairs_hook=_unique_fields)
        judgement = GeminiJudgement.model_validate(parsed)
    except (ValidationError, ValueError, RecursionError):
        raise GeminiError("Gemini judgement failed strict parsing; evaluation skipped.") from None
    usage = payload.get("usage", {})
    usage = (
        {
            name: value
            for name, value in usage.items()
            if name in {"total_input_tokens", "total_output_tokens", "total_thought_tokens"}
            and type(value) is int
            and value >= 0
        }
        if isinstance(usage, dict)
        else {}
    )
    return {**base, "status": "succeeded", **judgement.model_dump(), "usage": usage}


def submit(before_image_b64: str, after_image_b64: str, model: str = "") -> dict:
    settings = GeminiSettings.from_env(model)
    body = request_body(before_image_b64, after_image_b64, settings.model)
    if settings.dry_run:
        return {
            **_base(settings),
            "job_id": "gemini_dry_" + uuid.uuid4().hex,
            "status": "skipped",
            "dry_run": True,
            "cost_estimate": "unknown"
            if settings.model != VERIFIED_MODEL
            else "token estimate required",
            "reason": "Gemini dry-run is enabled; no judge request made.",
        }
    try:
        return _normalized(
            _request(
                "POST",
                INTERACTIONS_URL,
                settings,
                time.monotonic() + settings.timeout_seconds,
                body,
            ),
            settings,
        )
    except GeminiError as exc:
        return {**_base(settings), "status": "skipped", "dry_run": False, "reason": str(exc)}


def poll(job_id: str, model: str = "") -> dict:
    validate_job_id(job_id)
    settings = GeminiSettings.from_env(model)
    if settings.dry_run or job_id.startswith("gemini_dry_"):
        return {
            **_base(settings),
            "job_id": job_id,
            "status": "skipped",
            "dry_run": True,
            "reason": "Gemini dry-run interaction has no judgement.",
        }
    try:
        return _normalized(
            _request(
                "GET",
                INTERACTIONS_URL + "/" + job_id,
                settings,
                time.monotonic() + settings.timeout_seconds,
            ),
            settings,
            job_id,
        )
    except GeminiError as exc:
        return {
            **_base(settings),
            "job_id": job_id,
            "status": "skipped",
            "dry_run": False,
            "reason": str(exc),
        }


def _encode(frame) -> str:
    output = io.BytesIO()
    try:
        if frame.width * frame.height > MAX_IMAGE_PIXELS:
            raise ValueError("oversized frame")
        frame.save(output, format="PNG")
        if output.tell() > MAX_IMAGE_BYTES:
            raise ValueError("oversized encoded image")
    except Exception:
        raise GeminiError("Gemini keyframe encoding failed; evaluation skipped.") from None
    return base64.b64encode(output.getvalue()).decode("ascii")


class GeminiClient:
    def __init__(self, settings: GeminiSettings):
        self.settings = settings

    def judge(self, before, after) -> GeminiJudgement:
        _live_guard(self.settings)
        try:
            body = request_body(_encode(before), _encode(after), self.settings.model)
        except ValueError:
            raise GeminiError("Gemini keyframe validation failed; evaluation skipped.") from None
        deadline = time.monotonic() + self.settings.timeout_seconds
        result = _normalized(
            _request("POST", INTERACTIONS_URL, self.settings, deadline, body), self.settings
        )
        while result["status"] in {"queued", "running"}:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GeminiError("Gemini judge deadline exceeded; evaluation skipped.")
            time.sleep(min(0.25, remaining))
            result = _normalized(
                _request("GET", INTERACTIONS_URL + "/" + result["job_id"], self.settings, deadline),
                self.settings,
                result["job_id"],
            )
        return GeminiJudgement.model_validate(
            {name: result[name] for name in GeminiJudgement.model_fields}
        )


def judge_pair(before, after) -> GeminiJudgement:
    return GeminiClient(GeminiSettings.from_env()).judge(before, after)
