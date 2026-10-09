"""Bounded RunPod HTTP transport for continuity similarities, without ML dependencies."""

from __future__ import annotations

import base64
import io
import json
import math
import os
import queue
import re
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Sequence
from urllib.error import HTTPError, URLError

from agent.deep_agent.continuity_qc import DINOV3_MODEL, SIGLIP_MODEL, Shot

MAX_FRAMES = 8
MAX_FRAME_BYTES = 8 * 1024 * 1024
MAX_JSON_BYTES = 10 * 1024 * 1024
PENDING = frozenset({"IN_QUEUE", "IN_PROGRESS"})
TERMINAL_FAILURES = frozenset({"FAILED", "CANCELLED", "TIMED_OUT"})
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
SHOT_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_open = urllib.request.build_opener(_NoRedirect).open


class RunPodBackendError(Exception):
    """A fixed, credential-free reason safe to include in an incomplete report."""


class _SyncTimeout(RunPodBackendError):
    pass


@dataclass(frozen=True)
class RunPodSettings:
    endpoint_id: str
    api_key: str = field(repr=False)
    timeout_seconds: float = 120.0
    request_timeout_seconds: float = 95.0
    max_retries: int = 2
    poll_interval_seconds: float = 1.0

    @classmethod
    def from_environment(cls) -> RunPodSettings:
        endpoint = os.environ.get("CONTINUITY_QC_RUNPOD_ENDPOINT_ID", "").strip()
        key = os.environ.get("RUNPOD_API_KEY", "").strip()
        if not endpoint or not key:
            raise RunPodBackendError("RunPod credentials or endpoint are not configured.")
        if not IDENTIFIER.fullmatch(endpoint):
            raise RunPodBackendError("RunPod endpoint configuration is invalid.")
        try:
            timeout = float(os.environ.get("CONTINUITY_QC_RUNPOD_TIMEOUT_SECONDS", "120"))
            request_timeout = float(os.environ.get("CONTINUITY_QC_RUNPOD_REQUEST_TIMEOUT_SECONDS", "95"))
            retries = int(os.environ.get("CONTINUITY_QC_RUNPOD_MAX_RETRIES", "2"))
            poll = float(os.environ.get("CONTINUITY_QC_RUNPOD_POLL_INTERVAL_SECONDS", "1"))
            if not all(math.isfinite(value) and 0 < value <= 3600
                       for value in (timeout, request_timeout, poll)) or not 0 <= retries <= 5:
                raise ValueError
        except (ValueError, OverflowError):
            raise RunPodBackendError("RunPod timeout, retry or poll configuration is invalid.") from None
        return cls(endpoint, key, timeout, request_timeout, retries, poll)


class _FrameBuffer(io.BytesIO):
    def write(self, data):
        if self.tell() + len(data) > MAX_FRAME_BYTES:
            raise RunPodBackendError("Continuity frame exceeds the RunPod byte limit.")
        return super().write(data)


class RunPodClient:
    def __init__(self, settings: RunPodSettings):
        self.settings = settings
        self.base_url = f"https://api.runpod.ai/v2/{settings.endpoint_id}"
        self.deadline = time.monotonic() + settings.timeout_seconds

    def _remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise RunPodBackendError("RunPod continuity QC deadline exceeded.")
        return remaining

    def _pause(self, seconds: float) -> None:
        time.sleep(min(seconds, self._remaining()))
        self._remaining()

    def _read(self, request: urllib.request.Request, timeout: float) -> bytes:
        outcomes: queue.Queue[bytes | Exception] = queue.Queue(maxsize=1)

        def read_response():
            try:
                with _open(request, timeout=timeout) as result:
                    raw = result.read(MAX_JSON_BYTES + 1)
            except Exception as exc:
                outcomes.put(exc)
            else:
                outcomes.put(raw)

        threading.Thread(target=read_response, daemon=True, name="continuity-qc-runpod").start()
        try:
            outcome = outcomes.get(timeout=min(timeout, self._remaining()))
        except queue.Empty:
            raise TimeoutError("RunPod request deadline exceeded.") from None
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def _request(self, path: str, body: bytes | None = None, *, sync: bool = False) -> dict[str, Any]:
        for attempt in range(self.settings.max_retries + 1):
            request = urllib.request.Request(
                self.base_url + path, data=body,
                headers={"Authorization": f"Bearer {self.settings.api_key}",
                         "Content-Type": "application/json"},
                method="POST" if body is not None else "GET",
            )
            timeout = min(self.settings.request_timeout_seconds, self._remaining())
            try:
                raw = self._read(request, timeout)
                self._remaining()
                if len(raw) > MAX_JSON_BYTES:
                    raise RunPodBackendError("RunPod response exceeds the byte limit.")
                try:
                    payload = json.loads(raw)
                except (ValueError, UnicodeError):
                    raise RunPodBackendError("RunPod returned malformed JSON.") from None
                if not isinstance(payload, dict):
                    raise RunPodBackendError("RunPod returned a malformed job response.")
                return payload
            except HTTPError as exc:
                if exc.code != 429 and not 500 <= exc.code < 600:
                    raise RunPodBackendError(f"RunPod HTTP {exc.code}.") from None
                reason = f"RunPod HTTP {exc.code} retry limit exceeded."
            except (TimeoutError, URLError, OSError) as exc:
                is_timeout = isinstance(exc, TimeoutError) or (
                    isinstance(exc, URLError) and isinstance(exc.reason, TimeoutError))
                if sync and is_timeout:
                    raise _SyncTimeout("RunPod synchronous request timed out.") from None
                reason = "RunPod network retry limit exceeded."
            if attempt == self.settings.max_retries:
                raise RunPodBackendError(reason)
            self._pause(min(0.25 * 2 ** attempt, 5.0))
        raise AssertionError("Unreachable retry state")

    def _output(self, job: dict[str, Any]) -> dict[str, Any] | None:
        status = job.get("status")
        if status == "COMPLETED":
            output = job.get("output")
            if not isinstance(output, dict) or "error" in output:
                raise RunPodBackendError("RunPod worker returned an invalid result.")
            return output
        if status in TERMINAL_FAILURES:
            raise RunPodBackendError(f"RunPod job ended with {status}.")
        if status not in PENDING:
            raise RunPodBackendError("RunPod returned an unknown job status.")
        return None

    def similarities(self, shots: Sequence[Shot], dino_model: str) -> list[tuple[float, float]]:
        self._remaining()
        if not 2 <= len(shots) <= MAX_FRAMES:
            raise RunPodBackendError("RunPod continuity QC requires 2 to 8 frames.")
        ids = [shot.shot_id for shot in shots]
        if not all(isinstance(value, str) and SHOT_IDENTIFIER.fullmatch(value) for value in ids) or len(set(ids)) != len(ids):
            raise RunPodBackendError("Continuity shot IDs must be unique bounded ASCII identifiers.")
        model_key = "dinov3" if dino_model == DINOV3_MODEL else "dinov2"
        models = {"siglip": SIGLIP_MODEL, model_key: dino_model}
        frames = []
        for shot in shots:
            self._remaining()
            try:
                buffer = _FrameBuffer()
                shot.frame.save(buffer, format="PNG")
                encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            except RunPodBackendError:
                raise
            except Exception:
                raise RunPodBackendError("Continuity frames could not be encoded as PNG.") from None
            frames.append({"id": shot.shot_id, "b64": encoded})
        expected_pairs = list(zip(ids, ids[1:]))
        body = json.dumps({"input": {"frames": frames, "models": list(models),
                                     "pairs": expected_pairs, "return": ["similarities"]}},
                          allow_nan=False).encode()
        if len(body) > MAX_JSON_BYTES:
            raise RunPodBackendError("Continuity request exceeds the RunPod byte limit.")
        try:
            job = self._request("/runsync", body, sync=True)
        except _SyncTimeout:
            job = self._request("/run", body)
        output = self._output(job)
        if output is None and not job.get("id"):
            job = self._request("/run", body)
            output = self._output(job)
        if output is None:
            job_id = job.get("id")
            if not isinstance(job_id, str) or not IDENTIFIER.fullmatch(job_id):
                raise RunPodBackendError("RunPod returned an invalid job ID.")
            delay = self.settings.poll_interval_seconds
            while output is None:
                self._pause(delay)
                job = self._request(f"/status/{job_id}")
                if job.get("id", job_id) != job_id:
                    raise RunPodBackendError("RunPod returned a different job ID.")
                output = self._output(job)
                delay = min(delay * 1.5, 5.0)
        self._remaining()
        return _parse_similarities(output, expected_pairs, models)


def _parse_similarities(output: dict[str, Any], expected_pairs: Sequence[tuple[str, str]],
                        models: dict[str, str]) -> list[tuple[float, float]]:
    rows = output.get("pairs")
    if output.get("models") != models or not isinstance(rows, list) or len(rows) != len(expected_pairs):
        raise RunPodBackendError("RunPod returned mismatched continuity models or pairs.")
    scores = []
    for row, (before, after) in zip(rows, expected_pairs, strict=True):
        if not isinstance(row, dict) or (row.get("before"), row.get("after")) != (before, after):
            raise RunPodBackendError("RunPod returned mismatched continuity pair IDs.")
        similarities = row.get("similarities")
        if not isinstance(similarities, dict) or set(similarities) != set(models):
            raise RunPodBackendError("RunPod returned missing continuity similarities.")
        values = tuple(similarities[key] for key in models)
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
                   and math.isfinite(value) and -1 <= value <= 1 for value in values):
            raise RunPodBackendError("RunPod returned invalid continuity similarities.")
        scores.append((float(values[0]), float(values[1])))
    return scores


def runpod_similarities(shots: Sequence[Shot], dino_model: str) -> list[tuple[float, float]]:
    return RunPodClient(RunPodSettings.from_environment()).similarities(shots, dino_model)
