from __future__ import annotations

import os
import re
import subprocess
import time

from providers.ffmpeg import api as media_api
from providers.ffmpeg.sandbox import job_directory
from providers.reference_shots.contracts import parse_arguments, tool_schema, validate_arguments as validate_arguments


def shot_breakdown(op: str, job_id: str, input_path: str, params: dict | None = None) -> dict:
    """Measure real local media or report labels against unchanged measured evidence."""
    result = {"op": op, "ok": False, "outputs": [], "warnings": [],
              "estimated_cost_usd": 0, "training_eligible": False}
    token = None
    try:
        request, parsed = parse_arguments(dict(op=op, job_id=job_id, input_path=input_path, params=params))
        if os.getenv("REFERENCE_SHOTS_DRY_RUN", "true").lower() != "false":
            return {**result, "ok": True, "status": "dry_run",
                    "warnings": ["Dry-run validates arguments only; no media or labels were inspected."]}
        if request.input_path.startswith("renderhaus-asset://"):
            raise ValueError("The owned media handle must be staged locally by the host before measurement.")
        from providers.reference_shots.analysis import Budget, measure
        from providers.reference_shots.report import build_report

        directory = job_directory(request.job_id)
        budget = Budget(time.monotonic() + 240)
        parent_deadline = media_api._EXECUTION_DEADLINE.get()
        if parent_deadline is not None:
            budget = Budget(min(budget.deadline, parent_deadline))
        token = media_api._EXECUTION_DEADLINE.set(budget.deadline)
        if request.op == "measure":
            payload = measure(directory, request.input_path, budget)
        else:
            payload = build_report(directory, request.input_path, parsed, budget)
        return {**result, **payload}
    except (ValueError, OSError, TypeError, subprocess.SubprocessError) as exc:
        error = "Reference analysis exceeded its hard deadline." if isinstance(exc, subprocess.TimeoutExpired) else str(exc)
        error = re.sub(r"(?:https?|file|s3)://\S+", "[url]", error)
        error = re.sub(r"(?<![A-Za-z0-9])(?:/|\.\.?/)[^\s'\"]+", "[path]", error)
        return {**result, "status": "failed", "error": error[:1500]}
    finally:
        if token is not None:
            media_api._EXECUTION_DEADLINE.reset(token)


TOOL_HANDLERS = {"shot_breakdown": shot_breakdown}
GATEWAY_TOOLS = tuple(TOOL_HANDLERS)
GATEWAY_SCHEMAS = [tool_schema()]
