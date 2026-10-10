"""Per-user demo project, copied from one shared, pre-generated template.

The template carries no paid work: it is plain notes and unrun steps, so opening
or copying it costs nothing. Clips shown in Studio's demo screen are static
fixtures; replacing them with pre-generated assets only needs the template here.
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
DEMO_TEMPLATE_VERSION = 1


def demo_template() -> dict[str, Any]:
    """The shared set. Each user gets a deep copy, so edits never leak between users."""
    return {
        "schemaVersion": 2,
        "projectName": DEMO_PROJECT_NAME,
        "demoTemplateVersion": DEMO_TEMPLATE_VERSION,
        "nodes": [
            {"id": "demo-brief", "type": "text", "position": {"x": 80, "y": 120},
             "data": {"kind": "text", "title": "Brief", "status": "idle", "inputs": [],
                      "config": {"text": "A matte-black stainless travel mug on a pale stone counter, soft morning window light."}}},
            {"id": "demo-still", "type": "image", "position": {"x": 460, "y": 80},
             "data": {"kind": "image", "title": "Product still", "status": "idle", "inputs": [],
                      "config": {"prompt": "Product photo of a matte-black travel mug on a pale stone counter."}}},
            {"id": "demo-shot-1", "type": "video", "position": {"x": 460, "y": 300},
             "data": {"kind": "video", "title": "Shot 1 · push-in", "status": "idle", "inputs": [],
                      "config": {"prompt": "Slow push-in on the handle and the matte texture. No text."}}},
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
