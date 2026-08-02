#!/usr/bin/env python3
"""Smoke-test the deployed AgentCore runtime (dry-run video start)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from agent.config import load_local_env


ROOT = Path(__file__).resolve().parents[1]


async def main() -> int:
    load_local_env()

    from agent.agentcore_client import agentcore_enabled, invoke

    if not agentcore_enabled():
        print("AGENTCORE_RUNTIME_ARN is not set.", file=sys.stderr)
        return 1

    result = invoke(
        "start_video_generation",
        {
            "prompt": (
                "Creative prompt: a quiet neon alley at night with soft rain.\n"
                "Vibe: cinematic. Aspect ratio: 16:9. Duration: 5 seconds. "
                "No reference image is supplied. Generate native sound when supported. "
                "Start exactly one video generation and return."
            ),
            "user_id": "smoke-agentcore",
        },
        session_id="smoke-agentcore-session-0001-abcdefghij",
    )
    print(json.dumps(result, indent=2, sort_keys=True)[:4000])
    artifacts = result.get("artifacts") or []
    if not artifacts:
        print("No artifacts returned.", file=sys.stderr)
        return 1
    status = str(artifacts[-1].get("status") or "")
    if status not in {"dry_run", "queued", "running", "succeeded"}:
        print(f"Unexpected artifact status: {status}", file=sys.stderr)
        return 1
    print(f"OK: AgentCore returned status={status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
