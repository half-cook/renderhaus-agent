#!/usr/bin/env python3
"""Offline chat batch driver. Explicit operator approval binds each render stage."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from providers.ffmpeg.sandbox import input_file, job_directory  # noqa: E402
from providers.remotion.ad_variants import authorize, render_ad_variants  # noqa: E402
from providers.remotion.chat_story import batch_rows  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('plan', 'render_first', 'render_batch'))
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--table', required=True, help='Job-relative CSV or JSON table of scripts.')
    parser.add_argument('--campaign', default='chat')
    parser.add_argument('--approve-plan', default='', help='Exact reviewed plan hash; approves this stage only.')
    args = parser.parse_args()
    if args.stage != 'plan' and not args.approve_plan:
        parser.error('Rendering requires --approve-plan HASH. Review the sample before batch approval.')
    job = job_directory(args.job_id)
    rows = batch_rows(input_file(job, args.table, max_bytes=2 * 1024 * 1024).read_text(encoding='utf-8-sig'))
    with authorize(args.stage, args.approve_plan, 'operator:cli'):
        result = render_ad_variants(args.stage, args.job_id, {'mode': 'chat_story', 'campaign': args.campaign},
                                    rows, plan_hash=args.approve_plan)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    if result['status'] in {'blocked', 'failed'}:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
