"""Generate the static backdrop and social-share art used by the web UI.

Run once when the art direction changes; the results are committed under
web/static/img so the UI never depends on a live provider call at page load.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from agent.config import ROOT, load_local_env
from mcps.seedream.server import text_to_image


TARGET_DIR = ROOT / "web" / "static" / "img"

ASSETS = [
    {
        "name": "stage-backdrop",
        "aspect_ratio": "16:9",
        "size": "2K",
        "prompt": (
            "Very dark, near-black photograph of an empty brutalist concrete gallery at night. "
            "One narrow shaft of cool daylight falls across a raw concrete floor, everything else "
            "sinks into deep shadow. Shot on medium format film, shallow depth of field, heavy "
            "atmospheric haze, visible film grain, muted desaturated neutral greys, no colour cast, "
            "no people, no objects, no text, no logos. Quiet luxury, editorial, understated."
        ),
    },
    {
        "name": "social-card",
        "aspect_ratio": "16:9",
        "size": "2K",
        "prompt": (
            "Dark editorial still life: a single brushed chrome cylinder standing on polished "
            "concrete in a black studio, lit by one soft rectangular key light from the left. "
            "Deep blacks, neutral greys, subtle specular highlight along the chrome edge, "
            "fine film grain, generous negative space on the right side of the frame. "
            "Medium format photography, no people, no text, no logos, no colour tint."
        ),
    },
]


def main() -> int:
    load_local_env()
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    for asset in ASSETS:
        print(f"generating {asset['name']}…", flush=True)
        result = text_to_image(
            prompt=asset["prompt"],
            aspect_ratio=asset["aspect_ratio"],
            size=asset["size"],
        )
        if result.get("status") != "succeeded":
            print(f"  skipped: {result.get('status')} — {result.get('note')}", flush=True)
            continue
        source = Path(result["output_path"])
        destination = TARGET_DIR / f"{asset['name']}{source.suffix}"
        shutil.copyfile(source, destination)
        print(f"  wrote {destination.relative_to(ROOT)}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
