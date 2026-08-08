#!/usr/bin/env python3
"""Fast CI checks that do not call paid providers."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def check_gateway_tools_schema() -> None:
    path = ROOT / "configs" / "mureka_gateway_tools.json"
    tools = json.loads(path.read_text())
    assert isinstance(tools, list) and tools, "gateway tools schema must be a non-empty list"
    names = [t["name"] for t in tools]
    required = {
        "text_to_music",
        "create_instrumental",
        "create_song",
        "create_song_from_prompt",
        "query_music_task",
        "generate_soundtrack",
    }
    missing = sorted(required - set(names))
    assert not missing, f"missing gateway tools: {missing}"
    print(f"ok gateway tools schema ({len(tools)} tools)")


def check_imports() -> None:
    import sys

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from mcps.mureka import api  # noqa: F401
    from agent import config, director, executor, service  # noqa: F401
    from lambdas.mureka import handler  # noqa: F401

    assert isinstance(api.dry_run(), bool)
    print("ok python imports")


def check_mcp_configs() -> None:
    for name in ("mcp.local.json", "mcp.agentcore.json"):
        raw = json.loads((ROOT / "configs" / name).read_text())
        assert "mcpServers" in raw
        print(f"ok configs/{name}")


def main() -> int:
    check_gateway_tools_schema()
    check_mcp_configs()
    check_imports()
    print("ci_check passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"ci_check failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
