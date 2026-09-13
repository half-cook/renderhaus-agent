"""Compatibility entrypoint for callers of the former Studio manager.

All model and Gateway execution now runs through the Codex harness.
"""

from __future__ import annotations

from dataclasses import dataclass
from agent.studio_agent_next import (
    StudioAgentContext,
    StudioAgentOutput,
    StudioAgentRequest,
    StudioNode as StudioNodeReference,
    StudioToolEvent,
    normalize_markdown_filename,
    run_studio_agent as _run,
)


@dataclass
class StudioAgentRun:
    final: StudioAgentOutput
    tool_events: list[StudioToolEvent]


async def run_studio_agent(prompt: str, *, nodes=None, harness=None, **kwargs):
    request = StudioAgentRequest(prompt=prompt, nodes=list(nodes or []))
    studio = StudioAgentContext(nodes=list(request.nodes), **kwargs)
    final = await _run(request, studio=studio, harness=harness)
    return StudioAgentRun(final=final, tool_events=studio.tool_events)
