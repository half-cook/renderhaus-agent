#!/usr/bin/env python3
"""Backward-compatible wrapper. Prefer scripts/deploy_gateway.py --provider mureka."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    script = ROOT / "scripts" / "deploy_gateway.py"
    return subprocess.run(
        [sys.executable, str(script), "--provider", "mureka", *sys.argv[1:]],
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
