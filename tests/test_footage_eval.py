from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from providers.footage_memory.evaluation import (
    evaluate_backends,
    generate_fixtures,
    load_fixtures,
    score_predictions,
)


class FootageEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.labels = [
            {"query_id": "q1", "clip_id": "a", "t0_s": 10.0},
            {"query_id": "q1", "clip_id": "a", "t0_s": 30.0},
            {"query_id": "q2", "clip_id": "b", "t0_s": 20.0},
        ]

    def test_timestamp_precision_recall_counts_false_positives_and_misses(self):
        predictions = [
            {"query_id": "q1", "clip_id": "a", "t0_s": 11.5},
            {"query_id": "q1", "clip_id": "a", "t0_s": 12.0},
            {"query_id": "q1", "clip_id": "a", "t0_s": 30.0},
            {"query_id": "q2", "clip_id": "a", "t0_s": 20.0},
        ]
        result = score_predictions(self.labels, predictions)
        self.assertEqual(result["true_positives"], 2)
        self.assertEqual(result["false_positives"], 2)
        self.assertEqual(result["false_negatives"], 1)
        self.assertEqual(result["precision"], 0.5)
        self.assertAlmostEqual(result["recall"], 2 / 3)

    def test_two_second_boundary_inclusive(self):
        labels = [{"query_id": "q1", "clip_id": "a", "t0_s": 10.0}]
        for t0, expected in ((8, 1), (12, 1), (12.00001, 0)):
            with self.subTest(t0=t0):
                result = score_predictions(labels, [{"query_id": "q1", "clip_id": "a", "t0_s": t0}])
                self.assertEqual(result["true_positives"], expected)

    def test_matching_is_one_to_one_and_order_independent(self):
        labels = [
            {"query_id": "q1", "clip_id": "a", "t0_s": 10},
            {"query_id": "q1", "clip_id": "a", "t0_s": 12},
        ]
        predictions = [
            {"query_id": "q1", "clip_id": "a", "t0_s": 11},
            {"query_id": "q1", "clip_id": "a", "t0_s": 8},
        ]
        self.assertEqual(score_predictions(labels, predictions)["true_positives"], 2)
        self.assertEqual(
            score_predictions(labels, list(reversed(predictions)))["true_positives"], 2
        )

    def test_exact_duplicate_predictions_cannot_improve_recall(self):
        labels = [{"query_id": "q1", "clip_id": "a", "t0_s": 10}]
        prediction = {"query_id": "q1", "clip_id": "a", "t0_s": 10}
        result = score_predictions(labels, [prediction, dict(prediction)])
        self.assertEqual(result["true_positives"], 1)
        self.assertEqual(result["false_positives"], 1)
        self.assertEqual(result["duplicate_predictions"], 1)
        self.assertEqual(result["precision"], 0.5)

    def test_invalid_or_duplicate_labels_rejected(self):
        label = {"query_id": "q1", "clip_id": "a", "t0_s": 10}
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            score_predictions([label, dict(label)], [])
        for value in (float("nan"), float("inf"), -1, True, "10"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                score_predictions([label], [{**label, "t0_s": value}])

    def test_empty_inputs_have_defined_zero_scores(self):
        self.assertEqual(score_predictions([], [])["precision"], 0)
        self.assertEqual(score_predictions([], [])["recall"], 0)
        self.assertEqual(score_predictions(self.labels, [])["false_negatives"], 3)

    def test_committed_fixtures_match_generator_and_are_synthetic(self):
        fixtures = load_fixtures()
        self.assertEqual(fixtures, generate_fixtures())
        self.assertEqual(
            fixtures["provenance"], "Generated fictional events; no real footage or vendor data."
        )
        self.assertTrue(all(case["split"] == "held_out" for case in fixtures["cases"]))

    def test_offline_backend_reports_are_not_a_default_promotion(self):
        with (
            patch("socket.socket", side_effect=AssertionError("No network")),
            patch(
                "os.getenv",
                side_effect=lambda name, default=None: {
                    "FOOTAGE_MEMORY_DRY_RUN": "true",
                }.get(name, default),
            ),
        ):
            report = evaluate_backends(["mock", "gemini"])
        self.assertEqual(set(report["backends"]), {"mock", "gemini"})
        self.assertFalse(report["default_promoted"])
        self.assertTrue(report["synthetic_only"])
        for result in report["backends"].values():
            self.assertEqual(result["precision"], 1)
            self.assertEqual(result["recall"], 1)

    def test_refuted_answers_do_not_count_as_retrieval_hits(self):
        backend = SimpleNamespace(
            answer=lambda _question, _media: {"verdict": "refuted", "t0_s": 12}
        )
        with patch("providers.footage_memory.evaluation.get_backend", return_value=backend):
            report = evaluate_backends(["candidate"])
        self.assertEqual(report["backends"]["candidate"]["prediction_count"], 0)
        self.assertEqual(report["backends"]["candidate"]["false_negatives"], 6)

    def test_cli_runs_from_outside_repo_and_outputs_json(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                str(root / ".venv/bin/python"),
                str(root / "scripts/eval_footage_memory.py"),
                "--backends",
                "mock",
            ],
            cwd="/tmp",
            check=True,
            capture_output=True,
            text=True,
        )
        report = json.loads(result.stdout)
        self.assertTrue(report["synthetic_only"])
        self.assertEqual(report["backends"]["mock"]["true_positives"], 6)

    def test_cli_scores_external_predictions_without_selecting_a_backend(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "predictions.json"
            path.write_text(
                json.dumps(
                    {
                        "candidate": [
                            {"query_id": "q01", "clip_id": "m01", "t0_s": 14},
                            {"query_id": "q02", "clip_id": "wrong", "t0_s": 37},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    str(root / ".venv/bin/python"),
                    str(root / "scripts/eval_footage_memory.py"),
                    "--backends",
                    "qwen_omni",
                    "--predictions",
                    str(path),
                ],
                cwd=directory,
                check=True,
                capture_output=True,
                text=True,
            )
        report = json.loads(result.stdout)
        self.assertEqual(report["backends"]["candidate"]["precision"], 0.5)
        self.assertEqual(report["backends"]["candidate"]["recall"], 1 / 6)

    def test_cli_disabled_candidate_reports_a_neutral_error(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                str(root / ".venv/bin/python"),
                str(root / "scripts/eval_footage_memory.py"),
                "--backends",
                "qwen_omni",
            ],
            cwd="/tmp",
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("qwen", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
