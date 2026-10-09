"""Calibrated continuity scoring: offline, uses committed benchmark cosines only."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import unittest
from pathlib import Path

from agent.deep_agent.continuity_qc import (
    DINO_MODEL,
    DINOV3_MODEL,
    SIGLIP_MODEL,
    Calibration,
    ContinuityConfig,
    ContinuityQC,
    Shot,
    load_calibration,
)

ROOT = Path(__file__).resolve().parents[1]
SCORES = json.loads((ROOT / "docs/continuity_qc_benchmark_scores.json").read_text())
SPEC = importlib.util.spec_from_file_location("continuity_qc_benchmark", ROOT / "scripts/continuity_qc_benchmark.py")
bench = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bench
SPEC.loader.exec_module(bench)


def vector(cosine: float) -> list[float]:
    """Unit vector whose cosine with [1, 0] is the requested value."""
    return [cosine, math.sqrt(max(0.0, 1 - cosine * cosine))]


class Fake:
    def __init__(self, model_id, cosine):
        self.model_id, self.cosine = model_id, cosine

    def embed(self, frame):
        return [1.0, 0.0] if frame == "a" else vector(self.cosine)


def checker(siglip_cos, dino_cos, *, dino_model=DINO_MODEL, **config):
    return ContinuityQC(
        siglip=Fake(SIGLIP_MODEL, siglip_cos), dino=Fake(dino_model, dino_cos),
        config=ContinuityConfig(enable_dinov3=dino_model == DINOV3_MODEL, **config),
    )


def decisions(dino_key: str, dino_model: str, rule: str = "calibrated_mean"):
    calibration = load_calibration()
    config = ContinuityConfig(rule=rule, enable_dinov3=dino_model == DINOV3_MODEL)
    out = []
    for row in SCORES["pairs"]:
        accepted, _, _ = calibration.decide(row["siglip"], row[dino_key], dino_model, config)
        out.append((row, accepted))
    return out


def rate(results, category):
    chosen = [accepted for row, accepted in results if row["category"] == category]
    return sum(chosen) / len(chosen)


def accuracy(results):
    return sum(accepted == (row["label"] == "consistent") for row, accepted in results) / len(results)


class CalibrationFileTests(unittest.TestCase):
    def test_default_calibration_covers_every_slot_model_and_states_its_limits(self):
        calibration = load_calibration()
        self.assertEqual(type(calibration).__name__, Calibration.__name__)
        self.assertEqual(set(calibration.models), {SIGLIP_MODEL, DINO_MODEL, DINOV3_MODEL})
        self.assertEqual(calibration.method, "platt-logistic-class-balanced")
        self.assertEqual((calibration.acceptance_threshold, calibration.veto_threshold), (0.5, 0.2))
        self.assertIn("recalibrate", calibration.warning.lower())
        for slope, _ in calibration.models.values():
            self.assertGreater(slope, 0)

    def test_committed_calibration_reproduces_from_committed_scores(self):
        calibration = load_calibration()
        labels = [1 if row["label"] == "consistent" else 0 for row in SCORES["pairs"]]
        for key, model in SCORES["models"].items():
            slope, intercept = bench.fit_platt([row[key] for row in SCORES["pairs"]], labels)
            self.assertAlmostEqual(slope, calibration.models[model][0], places=3)
            self.assertAlmostEqual(intercept, calibration.models[model][1], places=3)

    def test_probabilities_are_monotonic_and_bounded(self):
        calibration = load_calibration()
        values = [calibration.probability(DINO_MODEL, c) for c in (-1, 0, 0.3, 0.7, 1)]
        self.assertEqual(values, sorted(values))
        self.assertTrue(all(0 < v < 1 for v in values))

    def test_missing_model_or_bad_thresholds_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "calibration"):
            ContinuityQC(siglip=Fake(SIGLIP_MODEL, 1), dino=Fake(DINO_MODEL, 1),
                         calibration=Calibration(models={SIGLIP_MODEL: (1.0, 0.0)}))
        for bad in ({"acceptance_threshold": 1.5}, {"veto_threshold": -0.1}, {"rule": "max"},
                    {"acceptance_threshold": float("nan")}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ContinuityConfig(**bad)


class CalibratedDecisionTests(unittest.TestCase):
    def test_true_same_shot_and_perturbed_pairs_pass(self):
        for dino_key, model in (("dinov2", DINO_MODEL), ("dinov3", DINOV3_MODEL)):
            results = decisions(dino_key, model)
            with self.subTest(model=model):
                self.assertGreaterEqual(rate(results, "same_shot"), 0.95)
                self.assertGreaterEqual(rate(results, "perturbed"), 0.95)

    def test_clear_negatives_fail(self):
        for dino_key, model in (("dinov2", DINO_MODEL), ("dinov3", DINOV3_MODEL)):
            results = decisions(dino_key, model)
            with self.subTest(model=model):
                self.assertLessEqual(rate(results, "different_scene"), 0.10)
                self.assertLessEqual(rate(results, "hard_negative"), 0.15)

    def test_accuracy_beats_the_old_min_rule(self):
        new = accuracy(decisions("dinov2", DINO_MODEL))
        old = accuracy(decisions("dinov2", DINO_MODEL, rule="legacy_min"))
        self.assertAlmostEqual(old, 0.519, places=3)
        self.assertGreater(new, old + 0.25)
        self.assertGreaterEqual(new, 0.80)

    def test_cross_validated_accuracy_also_beats_the_old_rule(self):
        rows = SCORES["pairs"]
        labels = [1 if r["label"] == "consistent" else 0 for r in rows]
        cv = bench.cross_validated_calibrated_accuracy(
            [r["siglip"] for r in rows], [r["dinov2"] for r in rows], labels)
        self.assertGreaterEqual(cv, 0.80)

    def test_fake_embedders_typical_pairs(self):
        same_shot = checker(0.92, 0.74).score([Shot("1", "a"), Shot("2", "b")]).pairs[0]
        self.assertTrue(same_shot.accepted)
        self.assertGreater(same_shot.score, 0.5)
        negative = checker(0.55, 0.11).score([Shot("1", "a"), Shot("2", "b")]).pairs[0]
        self.assertFalse(negative.accepted)
        self.assertLess(negative.score, 0.5)

    def test_one_model_drift_is_vetoed_not_averaged_away(self):
        pair = checker(1.0, 0.0).score([Shot("1", "a"), Shot("2", "b")]).pairs[0]
        self.assertGreater(pair.siglip_score, 0.9)
        self.assertLess(pair.dino_score, 0.2)
        self.assertFalse(pair.accepted)

    def test_dinov3_uses_its_own_calibration(self):
        report = checker(0.92, 0.80, dino_model=DINOV3_MODEL).score([Shot("1", "a"), Shot("2", "b")])
        calibration = load_calibration()
        self.assertEqual(report.dino_model, DINOV3_MODEL)
        self.assertAlmostEqual(report.pairs[0].dino_score, calibration.probability(DINOV3_MODEL, 0.80))

    def test_report_records_rule_and_threshold(self):
        report = checker(0.92, 0.74).score([Shot("1", "a"), Shot("2", "b")])
        self.assertEqual(report.rule, "calibrated_mean")
        self.assertEqual(report.acceptance_threshold, 0.5)

    def test_legacy_rule_remains_available_for_comparison(self):
        pair = checker(0.92, 0.74, rule="legacy_min").score([Shot("1", "a"), Shot("2", "b")]).pairs[0]
        self.assertFalse(pair.accepted)  # min(0.92, 0.74) < 0.8: the old false reject
        self.assertTrue(checker(0.92, 0.74).score([Shot("1", "a"), Shot("2", "b")]).pairs[0].accepted)


class FitTests(unittest.TestCase):
    def test_fit_platt_separates_and_balances_classes(self):
        xs = [0.1, 0.2, 0.25, 0.3, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95]
        ys = [0, 0, 0, 0, 1, 1, 1, 1, 1, 1]
        slope, intercept = bench.fit_platt(xs, ys)
        self.assertGreater(slope, 0)
        boundary = -intercept / slope
        self.assertTrue(0.3 < boundary < 0.7)
        with self.assertRaises(ValueError):
            bench.fit_platt([0.1, 0.2], [1, 1])


if __name__ == "__main__":
    unittest.main()
