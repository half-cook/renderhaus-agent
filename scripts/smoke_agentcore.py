#!/usr/bin/env python3
"""Smoke-test the deployed AgentCore runtime.

Disabled until the OpenAI Agents SDK harness replaces the old LangChain runtime.
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "AgentCore smoke test is disabled until the OpenAI Agents SDK harness is rebuilt.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
