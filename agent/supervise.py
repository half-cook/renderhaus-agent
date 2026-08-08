"""CLI for the Director/Executor supervisor flow."""

from __future__ import annotations

import argparse
import asyncio
import json

from agent.config import load_local_env
from agent.service import supervise_production
from agent.tracing import flush_langfuse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan (and optionally execute) a Renderhaus supervised production."
    )
    parser.add_argument("brief", nargs="+", help="Creative brief for the Director.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="After planning, run modality workers (respects *_DRY_RUN flags).",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Skip AgentCore remote hop even if AGENTCORE_RUNTIME_ARN is set.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    load_local_env()
    brief = " ".join(args.brief).strip()
    result = await supervise_production(
        brief,
        execute=args.execute,
        local_only=args.local_only,
        user_id="cli",
    )
    flush_langfuse()
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
