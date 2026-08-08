"""Director planner: typed production plans only — no provider tool calls."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Literal

from pydantic import BaseModel, Field


MediaKind = Literal["video", "image", "music", "speech"]


class PlanNode(BaseModel):
    id: str = Field(description="Stable node id used for idempotent execution.")
    kind: MediaKind
    prompt: str
    depends_on: list[str] = Field(default_factory=list)
    lyrics: str | None = None
    notes: str | None = None


class TypedProductionPlan(BaseModel):
    title: str
    summary: str
    nodes: list[PlanNode]
    rationale: str = ""


DIRECTOR_SYSTEM = """You are the Renderhaus Director/Planner.
Given a creative brief, produce a compact JSON production plan.
Rules:
- Emit ONLY valid JSON matching the schema (title, summary, nodes[], rationale).
- Each node needs a stable snake_case id, kind in {video,image,music,speech}, prompt, optional depends_on.
- Prefer 2–6 nodes. Do not invent provider names or tool calls.
- For music BGM use kind=music without lyrics. For songs include lyrics on the node.
- Video nodes should be short clip prompts (under ~15s intent). Image nodes are keyframes/reference stills.
- depends_on lists prior node ids that must finish first.
"""


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


async def plan_production(brief: str) -> TypedProductionPlan:
    """Call the chat model for a typed plan. Falls back to a heuristic plan if model fails."""
    model_id = os.getenv("AGENT_MODEL", "openai:gpt-4.1-mini")
    try:
        from langchain.chat_models import init_chat_model

        model = init_chat_model(model_id)
        message = await model.ainvoke(
            [
                {"role": "system", "content": DIRECTOR_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        "Brief:\n"
                        f"{brief}\n\n"
                        "Return JSON with keys: title, summary, nodes "
                        "(array of {id, kind, prompt, depends_on, lyrics?, notes?}), rationale."
                    ),
                },
            ]
        )
        content = message.content if hasattr(message, "content") else str(message)
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block) for block in content
            )
        data = _extract_json(str(content))
        return TypedProductionPlan.model_validate(data)
    except Exception:  # noqa: BLE001 - deterministic fallback keeps executor usable offline
        return TypedProductionPlan(
            title="Quick multi-modal draft",
            summary="Fallback heuristic plan from brief.",
            rationale="Model planning unavailable; used deterministic template.",
            nodes=[
                PlanNode(id="hero_still", kind="image", prompt=brief[:500]),
                PlanNode(
                    id="hero_clip",
                    kind="video",
                    prompt=brief[:500],
                    depends_on=["hero_still"],
                ),
                PlanNode(
                    id="score",
                    kind="music",
                    prompt=f"Instrumental underscore for: {brief[:240]}",
                    depends_on=["hero_clip"],
                ),
            ],
        )
