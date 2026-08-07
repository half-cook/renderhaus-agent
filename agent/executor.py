"""Deterministic supervisor executor — walks a TypedProductionPlan via modality workers."""

from __future__ import annotations

import asyncio
from typing import Any

from agent.director import PlanNode, TypedProductionPlan, plan_production


async def _run_node(
    node: PlanNode,
    *,
    completed: dict[str, Any],
    session_id: str | None,
    user_id: str | None,
    local_only: bool,
) -> dict[str, Any]:
    # Import inside the function to avoid a circular import with agent.service.
    from agent.service import (
        poll_music_generation,
        poll_video_generation,
        start_image_generation,
        start_music_generation,
        start_video_generation,
    )

    instruction = node.prompt
    if node.kind == "music" and node.lyrics:
        instruction = f"{node.prompt}\n\nUse these lyrics exactly:\n{node.lyrics}"

    worker_kwargs = {
        "session_id": session_id,
        "user_id": user_id,
        "local_only": local_only,
    }

    if node.kind == "video":
        ref = None
        for dep in node.depends_on:
            art = completed.get(dep) or {}
            for item in art.get("artifacts") or []:
                if isinstance(item, dict) and item.get("output_path"):
                    ref = item["output_path"]
                    break
            poll = art.get("poll") if isinstance(art.get("poll"), dict) else None
            if ref is None and poll and isinstance(poll.get("output_path"), str):
                ref = poll["output_path"]
        if ref:
            instruction = f"{instruction}\nUse this local reference image: {ref}."
        result = await start_video_generation(instruction, **worker_kwargs)
        job_id = _first_job_id(result)
        if job_id:
            polled = await _poll_until(
                lambda: poll_video_generation(job_id, **worker_kwargs)
            )
            result = {**result, "poll": polled}
        return {"node_id": node.id, "kind": node.kind, **result}

    if node.kind == "image":
        result = await start_image_generation(instruction, **worker_kwargs)
        return {"node_id": node.id, "kind": node.kind, **result}

    if node.kind == "music":
        result = await start_music_generation(instruction, **worker_kwargs)
        job_id = _first_job_id(result)
        if job_id:
            polled = await _poll_until(
                lambda: poll_music_generation(job_id, **worker_kwargs)
            )
            result = {**result, "poll": polled}
        return {"node_id": node.id, "kind": node.kind, **result}

    return {
        "node_id": node.id,
        "kind": node.kind,
        "status": "skipped",
        "note": f"Kind {node.kind} is planned but not wired in the executor yet.",
    }


def _first_job_id(result: dict[str, Any]) -> str | None:
    for artifact in reversed(result.get("artifacts") or []):
        if isinstance(artifact, dict) and isinstance(artifact.get("job_id"), str):
            return artifact["job_id"]
    poll = result.get("poll")
    if isinstance(poll, dict) and isinstance(poll.get("job_id"), str):
        return poll["job_id"]
    return None


async def _poll_until(factory, *, attempts: int = 60, delay_s: float = 5.0) -> dict[str, Any]:
    last: dict[str, Any] = {}
    for _ in range(attempts):
        last = await factory()
        status = str(last.get("status") or "").lower()
        if status in {"succeeded", "failed", "cancelled", "canceled", "timeouted", "dry_run"}:
            return last
        await asyncio.sleep(delay_s)
    return {
        **last,
        "status": last.get("status") or "timeout",
        "note": "Executor poll budget exhausted.",
    }


def _ready(node: PlanNode, done: set[str]) -> bool:
    return all(dep in done for dep in node.depends_on)


async def run_plan(
    plan: TypedProductionPlan,
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    local_only: bool = False,
) -> dict[str, Any]:
    """Execute plan nodes in dependency order (fan-out when independent)."""
    pending = {node.id: node for node in plan.nodes}
    completed: dict[str, Any] = {}
    done: set[str] = set()
    results: list[dict[str, Any]] = []

    while pending:
        batch = [node for node in pending.values() if _ready(node, done)]
        if not batch:
            blocked = sorted(pending)
            raise RuntimeError(f"Deadlocked production plan; blocked nodes: {blocked}")

        batch_results = await asyncio.gather(
            *[
                _run_node(
                    node,
                    completed=completed,
                    session_id=session_id,
                    user_id=user_id,
                    local_only=local_only,
                )
                for node in batch
            ]
        )
        for node, result in zip(batch, batch_results, strict=True):
            completed[node.id] = result
            done.add(node.id)
            results.append(result)
            pending.pop(node.id, None)

    return {
        "title": plan.title,
        "summary": plan.summary,
        "rationale": plan.rationale,
        "node_results": results,
        "status": "completed",
    }


async def supervise_brief(
    brief: str,
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    execute: bool = True,
    local_only: bool = False,
    plan: TypedProductionPlan | None = None,
) -> dict[str, Any]:
    """Director plans; optional deterministic execution (no LLM owns paid tools)."""
    typed = plan or await plan_production(brief)
    payload: dict[str, Any] = {
        "plan": typed.model_dump(),
        "mode": "plan_and_execute" if execute else "plan_only",
    }
    if execute:
        payload["execution"] = await run_plan(
            typed,
            session_id=session_id,
            user_id=user_id,
            local_only=local_only,
        )
    return payload
