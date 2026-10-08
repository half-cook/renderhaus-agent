from __future__ import annotations

import hashlib
import json

from agent.studio_agent_next import StudioAgentRequest


def execution_scope(request: StudioAgentRequest) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                request.workspace_id,
                request.project_id,
                request.conversation_id,
                request.job_id,
            ]
        ).encode()
    ).hexdigest()


def conversation_scope(request: StudioAgentRequest) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                request.workspace_id,
                request.project_id,
                request.conversation_id or request.job_id,
            ]
        ).encode()
    ).hexdigest()


