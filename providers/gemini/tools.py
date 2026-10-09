from __future__ import annotations

from providers.gemini import api
from providers.gemini.contracts import validate_arguments


def judge_continuity(before_image_b64: str, after_image_b64: str, model: str = "") -> dict:
    """Submit two PNG/JPEG keyframes for the fixed continuity rubric; poll get_task. Paid evaluation requires normal approval. Default dry-run is skipped, never a continuity verdict."""
    validate_arguments("judge_continuity", locals())
    return api.submit(before_image_b64, after_image_b64, model)


def get_task(job_id: str, model: str = "") -> dict:
    """Poll an existing Gemini interaction once. No new paid submission. Skipped reports remain incomplete checks and never block rendering."""
    validate_arguments("get_task", locals())
    return api.poll(job_id, model)


TOOL_HANDLERS = {"judge_continuity": judge_continuity, "get_task": get_task}
GATEWAY_TOOLS = tuple(TOOL_HANDLERS)
GATEWAY_TOOL_NAMES = GATEWAY_TOOLS
