#!/usr/bin/env python3
"""Run synthetic offline footage retrieval scoring without provider requests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from providers.footage_memory.evaluation import evaluate_backends, load_fixtures  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backends", nargs="+", default=["mock", "gemini"])
    parser.add_argument("--fixtures", type=Path, help="Alternative synthetic fixture JSON.")
    parser.add_argument(
        "--predictions", type=Path, help="Offline JSON mapping backend names to timestamp records."
    )
    parser.add_argument("--output", type=Path, help="Write JSON here instead of stdout.")
    arguments = parser.parse_args()
    try:
        fixtures = load_fixtures(arguments.fixtures)
        predictions = None
        if arguments.predictions:
            predictions = json.loads(arguments.predictions.read_text(encoding="utf-8"))
            if not isinstance(predictions, dict):
                raise ValueError("Offline predictions must map backend names to timestamp records.")
        result = evaluate_backends(arguments.backends, fixtures=fixtures, predictions=predictions)
        output = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if arguments.output:
            arguments.output.write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
    except (ValueError, KeyError, TypeError, OSError):
        sys.stderr.write(
            "Offline footage evaluation could not run. Check the input files and backend settings.\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
