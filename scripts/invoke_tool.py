#!/usr/bin/env python3
"""Invoke a provider tool the same way AgentCore Gateway Lambdas do."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers.catalog import get_provider
from providers.registry import dispatch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--tool", required=True)
    parser.add_argument("--args", default="{}", help="JSON object of tool arguments")
    args = parser.parse_args()
    spec = get_provider(args.provider)
    os.environ.setdefault("RENDERHAUS_PROVIDER", spec.id)
    payload = json.loads(args.args)
    if not isinstance(payload, dict):
        raise ValueError("--args must be a JSON object")
    result = dispatch(spec.id, args.tool, payload)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
