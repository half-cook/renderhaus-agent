#!/usr/bin/env python3
"""Operator driver for the real local matrix. --approve-plan is an explicit human decision."""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from providers.ffmpeg.sandbox import input_file, job_directory  # noqa: E402
from providers.remotion.ad_variants import authorize, render_ad_variants  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("plan", "render_first", "render_batch"))
    parser.add_argument("--media-root", type=Path, default=ROOT / ".renderhaus/demo")
    parser.add_argument("--job-id", default="ad-demo")
    parser.add_argument("--master", default="master.mp4")
    parser.add_argument("--table", default="variants.csv")
    parser.add_argument("--brief", default="brief.json")
    parser.add_argument("--approve-plan", default="", help="Exact reviewed plan hash; authorizes this stage only.")
    args = parser.parse_args()
    if args.stage != "plan" and not args.approve_plan:
        parser.error("Render stages require --approve-plan HASH after reviewing the plan/cost and first frames.")
    os.environ["RENDERHAUS_MEDIA_DIR"] = str(args.media_root.resolve())
    os.environ["REMOTION_RENDER_BACKEND"] = "local"
    os.environ["REMOTION_DRY_RUN"] = "false"
    job = job_directory(args.job_id)
    with input_file(job, args.table).open(encoding="utf-8-sig", newline="") as table:
        rows = list(csv.DictReader(table))
    for row in rows:
        for field in ("start_s", "end_s"):
            if row.get(field):
                row[field] = float(row[field])
            elif field in row:
                del row[field]
    brief = json.loads(input_file(job, args.brief).read_text())
    with authorize(args.stage, args.approve_plan, "operator:cli"):
        result = render_ad_variants(args.stage, args.job_id, brief, rows, args.master, args.approve_plan)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    if result["status"] in {"blocked", "failed"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
