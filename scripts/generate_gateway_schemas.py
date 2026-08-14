#!/usr/bin/env python3
"""Write committed AgentCore Gateway tool schemas from provider APIs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from providers.catalog import parse_provider_ids
from providers.registry import generate_schemas, load_committed_schemas, write_schemas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="all", help="Provider id, comma list, or all")
    parser.add_argument("--check", action="store_true", help="Fail if generated schemas differ from committed JSON")
    parser.add_argument("--list", action="store_true", help="Print Gateway tool names and exit")
    args = parser.parse_args()
    specs = parse_provider_ids(args.provider)

    if args.list:
        for spec in specs:
            tools = generate_schemas(spec)
            print(f"{spec.id} ({spec.target_name} / {spec.function_name})")
            for tool in tools:
                print(f"  {tool['name']}")
        return 0

    failed = False
    for spec in specs:
        generated = generate_schemas(spec)
        if args.check:
            committed = load_committed_schemas(spec)
            if committed != generated:
                print(
                    f"schema drift: {spec.id} — run python scripts/generate_gateway_schemas.py",
                    file=sys.stderr,
                )
                failed = True
                continue
            names = [tool["name"] for tool in committed]
            print(f"ok {spec.id} gateway schema ({len(names)} tools)")
            continue
        path = write_schemas(spec, generated)
        print(f"wrote {path.relative_to(ROOT)} ({len(generated)} tools)")
        if spec.id == "mureka":
            print(f"wrote configs/mureka_gateway_tools.json ({len(generated)} tools)")
    if failed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
