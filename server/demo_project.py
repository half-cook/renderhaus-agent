"""Per-user demo project, copied from one shared, pre-generated template.

The template carries no paid work. Its approved shots use static preview stills;
opening or copying it never generates media. Each user owns an editable copy.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
from typing import Any

from fastapi import APIRouter, HTTPException

from server.auth import AuthUser, current_user_id, current_workspace_id
from server.studio_state import StudioRepository, repository

router = APIRouter(tags=["demo project"])

DEMO_PROJECT_NAME = "Matte travel mug"
DEMO_TEMPLATE_VERSION = 2


def demo_template() -> dict[str, Any]:
    """The shared set. Each user gets a deep copy, so edits never leak between users."""
    return {
        "schemaVersion": 2,
        "projectName": DEMO_PROJECT_NAME,
        "demoTemplateVersion": DEMO_TEMPLATE_VERSION,
        "nodes": [
            {"id": "demo-brief", "type": "text", "position": {"x": 80, "y": 120},
             "data": {"kind": "text", "title": "Brief", "status": "idle", "inputs": [],
                      "config": {"prompt": "A matte-black stainless travel mug on a pale stone counter, soft morning window light."}}},
            {"id": "demo-still", "type": "image", "position": {"x": 460, "y": 80},
             "data": {"kind": "image", "title": "Product still", "status": "idle", "inputs": [],
                      "config": {"prompt": "Product photo of a matte-black travel mug on a pale stone counter.",
                                 "thumbnail_url": "/beta/still-mug-wide.jpg"}}},
            *[
                {"id": f"demo-shot-{index + 1}", "type": "video",
                 "position": {"x": 880, "y": 80 + index * 280},
                 "data": {"kind": "video", "title": title, "status": "idle", "inputs": [],
                          "approved": True, "storyOrder": index,
                          "config": {"prompt": prompt, "duration_seconds": 5,
                                     "trim_in_seconds": 0, "trim_out_seconds": 5,
                                     "aspect_ratio": "16:9", "thumbnail_url": thumbnail}}}
                for index, (title, prompt, thumbnail) in enumerate([
                    ("Shot 1 · macro", "Slow push-in on the matte texture. No text.", "/beta/shot-macro.jpg"),
                    ("Shot 2 · lift", "A hand lifts the mug from the counter. No text.", "/beta/shot-lift.jpg"),
                    ("Shot 3 · window", "Gentle tilt toward morning window light. No text.", "/beta/shot-window.jpg"),
                ])
            ],
        ],
        "edges": [
            {"id": "demo-edge-1", "source": "demo-brief", "target": "demo-still", "sourceHandle": "text",
             "targetHandle": "prompt", "data": {"dataType": "text", "targetField": "prompt"}},
        ],
        "viewport": {"x": 80, "y": 80, "zoom": 1},
    }


def demo_project_id(workspace_id: str) -> str:
    return "demo-" + hashlib.sha256(workspace_id.encode()).hexdigest()[:16]


def copy_demo_project(repo: StudioRepository, workspace_id: str, user_id: str) -> dict[str, Any]:
    """Idempotent: a second call returns the same project and never overwrites edits."""
    project_id = demo_project_id(workspace_id)
    repo.ensure_workspace(workspace_id, user_id)
    with repo._connect() as connection:
        existing = connection.execute(
            "SELECT id FROM projects WHERE id = ? AND workspace_id = ?", (project_id, workspace_id)
        ).fetchone()
    if existing:
        return {"project_id": project_id, "name": DEMO_PROJECT_NAME, "copied": False}
    repo.create_project(workspace_id, user_id, DEMO_PROJECT_NAME, project_id=project_id)
    repo.save_canvas(workspace_id, project_id, user_id, copy.deepcopy(demo_template()))
    return {"project_id": project_id, "name": DEMO_PROJECT_NAME, "copied": True}


@router.post("/api/studio/demo-project")
async def open_demo_project(auth: AuthUser) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            copy_demo_project, repository, current_workspace_id(auth), current_user_id(auth))
    except Exception as exc:  # noqa: BLE001 - never leak internals to the client
        raise HTTPException(status_code=409, detail="Could not open the demo project.") from exc
