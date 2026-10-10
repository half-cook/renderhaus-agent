"""Label and pair each designer mockup with its production fixture capture."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SCREENS = {
    "m01-landing": "01-landing",
    "m02-home": "02-home",
    "m03-agent-empty": "03-agent-empty",
    "m04-agent-run": "04-agent-run",
    "m05-approval-states": "05-approval-states",
    "m06-canvas-timeline": "06-canvas-timeline",
    "m07-timeline": "07-timeline",
    "m08-demo-project": "08-demo-project",
    "m09-signup-open": "09-signup-open",
    "m10-signup-spots-left": "10-signup-spots-left",
    "m11-signup-full": "11-signup-full",
    "m12-signup-success": "12-signup-success",
    "m13-agent-run-light": "13-agent-run-light",
    "m14-signup-code-error": "14-signup-code-error",
    "m15-run-receipt": "15-run-receipt",
    "m16-cap-reached": "16-cap-reached",
    "m17-low-credit": "17-low-credit",
}


def pair(mockup: Path, capture: Path, destination: Path) -> None:
    left, right = Image.open(mockup).convert("RGB"), Image.open(capture).convert("RGB")
    height = right.height
    left = left.resize((round(left.width * height / left.height), height), Image.Resampling.LANCZOS)
    output = Image.new("RGB", (left.width + right.width + 2, height + 48), "#121110")
    output.paste(left, (0, 48))
    output.paste(right, (left.width + 2, 48))
    draw = ImageDraw.Draw(output)
    font = ImageFont.load_default(size=18)
    draw.text((20, 14), "Designer mockup", fill="#f2eee6", font=font)
    draw.text((left.width + 22, 14), "Studio · production build · fixture data", fill="#f2eee6", font=font)
    destination.parent.mkdir(parents=True, exist_ok=True)
    output.save(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mockups", type=Path, default=Path("/workspace/renderhaus-ui/mockups"))
    parser.add_argument("--captures", type=Path, default=Path("/workspace/rh-ui-revamp-shots/after"))
    args = parser.parse_args()
    for screen, mockup in SCREENS.items():
        theme = "light" if screen.startswith("m13") else "dark"
        source = args.captures / theme / "desktop-1920x1200" / f"{screen}.png"
        pair(args.mockups / f"{mockup}.png", source, args.captures / "side-by-side" / f"{screen}.png")
    pair(args.mockups / "13-agent-run-light.png", args.captures / "light/desktop-1920x1200/m04-agent-run.png",
         args.captures / "side-by-side/m04-agent-run-light.png")
    print("Created 18 labelled comparisons. Export has no designer mockup.")


if __name__ == "__main__":
    main()
