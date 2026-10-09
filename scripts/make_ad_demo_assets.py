#!/usr/bin/env python3
"""Generate repeatable customer-demo inputs locally, without model calls."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from providers.ffmpeg.sandbox import validate_job_id  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media-root", type=Path, default=ROOT / ".renderhaus/demo")
    parser.add_argument("--job-id", default="ad-demo")
    parser.add_argument("--size", choices=("small", "720p", "1080p"), default="720p")
    args = parser.parse_args()
    validate_job_id(args.job_id)
    if not shutil.which("ffmpeg"):
        parser.error("ffmpeg is required to create real demo media.")
    directory = args.media_root.resolve() / args.job_id
    if directory.exists():
        parser.error("The demo job already exists. Choose a new job-id; inputs are never overwritten.")
    directory.mkdir(parents=True)
    width, height = {"small": (640, 360), "720p": (1280, 720), "1080p": (1920, 1080)}[args.size]
    duration = 2 if args.size == "small" else 4
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-n", "-f", "lavfi", "-i",
        f"testsrc2=size={width}x{height}:rate=24:duration={duration}", "-f", "lavfi", "-i",
        f"aevalsrc=0.12*sin(2*PI*220*t)*(0.5+0.5*sin(2*PI*3*t)):s=48000:d={duration}",
        "-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        "-shortest", str(directory / "master.mp4")], check=True, timeout=60,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    rows = []
    for sku, colour in zip(("A", "B", "C"), ((224, 30, 80), (20, 160, 200), (240, 160, 25)), strict=True):
        logo = Image.new("RGBA", (192, 96), (0, 0, 0, 0))
        draw = ImageDraw.Draw(logo)
        draw.rounded_rectangle((4, 4, 188, 92), radius=20, fill=(*colour, 220))
        draw.text((88, 36), sku, fill="white", font=ImageFont.truetype("DejaVuSans.ttf", 24))
        logo.save(directory / f"logo_{sku}.png")
        product = Image.new("RGB", (320, 320), colour)
        ImageDraw.Draw(product).rectangle((80, 40, 240, 280), fill="white")
        product.save(directory / f"product_{sku}.png")
        for aspect in ("9:16", "1:1", "4:5", "16:9", "2.39:1"):
            rows.append({"variant_key": f"demo_{sku}_{aspect.replace(':', 'x').replace('.', 'p')}", "sku": sku,
                         "price_text": "$9.99", "cta_text": "Shop now", "logo_asset": f"logo_{sku}.png",
                         "legal_text": "Terms apply", "locale": "en-CA", "aspect": aspect,
                         "product_asset": f"product_{sku}.png"})
    with (directory / "variants.csv").open("x", newline="", encoding="utf-8") as table:
        writer = csv.DictWriter(table, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (directory / "brief.json").write_text(json.dumps({"campaign": "demo", "logo_alpha_required": True,
        "legal_locales": ["en-CA"], "legal_by_locale": {"en-CA": "Terms apply"}}, indent=2))
    with (directory / "reframe.csv").open("x", newline="", encoding="utf-8") as table:
        writer = csv.DictWriter(table, fieldnames=("variant_key", "aspect"))
        writer.writeheader()
        writer.writerows({"variant_key": f"master_{aspect.replace(':', 'x').replace('.', 'p')}", "aspect": aspect}
                         for aspect in ("9:16", "1:1", "4:5", "16:9", "2.39:1"))
    (directory / "reframe-brief.json").write_text(json.dumps({"campaign": "reframe-demo",
        "reframe_only": True, "allow_upscale": False}, indent=2))
    print(json.dumps({"job_id": args.job_id, "directory": str(directory), "variants": len(rows),
                      "reframe_variants": 5,
                      "master_width": width, "master_height": height, "fps": 24, "media_cost_usd": 0}))


if __name__ == "__main__":
    main()
