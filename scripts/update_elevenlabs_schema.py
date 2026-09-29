#!/usr/bin/env python3
"""Refresh the pinned official ElevenLabs schema and regenerate Gateway tools.

Review the resulting diff, run tests/test_elevenlabs.py, then deploy the target.
There is no network schema discovery during normal requests.
"""
import json
from pathlib import Path
import subprocess
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://api.elevenlabs.io/openapi.json"


def main():
    with urlopen(SOURCE, timeout=60) as response:
        data = response.read()
    spec = json.loads(data)
    if not spec.get("openapi", "").startswith("3.") or not spec.get("paths"):
        raise ValueError("Upstream did not return an OpenAPI 3 document.")
    destination = ROOT / "providers/elevenlabs/openapi.json"
    previous = destination.read_bytes()
    destination.write_bytes(data)
    try:
        subprocess.run([sys.executable, "scripts/generate_gateway_schemas.py", "--provider", "elevenlabs"], cwd=ROOT, check=True)
    except BaseException:
        destination.write_bytes(previous)
        raise
    print(f"Refreshed ElevenLabs from {SOURCE}. Review and test before deployment.")


if __name__ == "__main__":
    main()
