"""Offline tests for scripts/continuity_qc_benchmark.py: no footage, weights or downloads."""

from __future__ import annotations

import importlib.util
import json
import random
import sys
import unittest
from pathlib import Path

from agent.deep_agent.continuity_qc import (
    DINO_MODEL,
    DINOV3_MODEL,
    SIGLIP_MODEL,
    ContinuityQC,
    Shot,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("continuity_qc_benchmark", ROOT / "scripts/continuity_qc_benchmark.py")
bench = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bench  # dataclasses resolve their module at class creation
SPEC.loader.exec_module(bench)

try:
    import PIL  # noqa: F401
except ImportError:
    PIL = None


class MetricTests(unittest.TestCase):
    def test_auroc_extremes_and_ties(self):
        self.assertEqual(bench.auroc([0.9, 0.8], [0.1, 0.2]), 1.0)
        self.assertEqual(bench.auroc([0.1], [0.9]), 0.0)
        self.assertEqual(bench.auroc([0.5, 0.5], [0.5, 0.5]), 0.5)
        self.assertAlmostEqual(bench.auroc([0.9, 0.4], [0.5, 0.1]), 0.75)
        with self.assertRaises(ValueError):
            bench.auroc([], [0.1])

    def test_auroc_matches_pairwise_definition(self):
        rng = random.Random(3)
        pos = [round(rng.random(), 2) for _ in range(40)]
        neg = [round(rng.random(), 2) for _ in range(30)]
        pairwise = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))
        self.assertAlmostEqual(bench.auroc(pos, neg), pairwise)

    def test_best_threshold_and_cross_validation(self):
        scores, labels = [0.9, 0.85, 0.7, 0.4, 0.3, 0.75], [1, 1, 1, 0, 0, 0]
        threshold, accuracy = bench.best_threshold(scores, labels)
        self.assertAlmostEqual(accuracy, 5 / 6)
        self.assertEqual(bench.accuracy_at(scores, labels, threshold), accuracy)
        separable = [0.9, 0.8, 0.95, 0.1, 0.2, 0.15] * 5
        self.assertEqual(bench.cross_validated_accuracy(separable, [1, 1, 1, 0, 0, 0] * 5), 1.0)

    def test_bootstrap_interval_brackets_point_estimate(self):
        pos, neg = [0.9, 0.7, 0.8, 0.6, 0.85], [0.2, 0.65, 0.3, 0.1]
        low, high = bench.bootstrap_auroc(pos, neg, rounds=200)
        self.assertLessEqual(low, bench.auroc(pos, neg))
        self.assertGreaterEqual(high, bench.auroc(pos, neg))

    def test_paired_bootstrap_delta_detects_the_better_scorer(self):
        pairs = [{"id": f"p{i}", "label": "consistent" if i % 2 else "inconsistent"} for i in range(40)]
        good = {p["id"]: (0.9 if p["label"] == "consistent" else 0.1) + int(p["id"][1:]) / 1000 for p in pairs}
        noisy = {p["id"]: random.Random(int(p["id"][1:])).random() for p in pairs}
        result = bench.paired_bootstrap_delta(good, noisy, pairs, rounds=200)
        self.assertGreater(result["delta"], 0)
        self.assertGreater(result["p_left_better"], 0.95)
        self.assertEqual(bench.paired_bootstrap_delta(good, good, pairs, rounds=50)["delta"], 0)

    def test_combination_mirrors_continuity_qc(self):
        class Fake:
            def __init__(self, model_id, vectors):
                self.model_id, self.vectors = model_id, vectors

            def embed(self, frame):
                return self.vectors[frame]

        siglip = Fake(SIGLIP_MODEL, {"a": [1, 0], "b": [0.8, 0.6]})
        dino = Fake(DINO_MODEL, {"a": [1, 0], "b": [0.6, 0.8]})
        pair = ContinuityQC(siglip=siglip, dino=dino).score([Shot("1", "a"), Shot("2", "b")]).pairs[0]
        s, d = pair.siglip_similarity, pair.dino_similarity
        self.assertAlmostEqual(bench.combine(s, d, "mean"), (s + d) / 2)
        from agent.deep_agent.continuity_qc import load_calibration

        cal = load_calibration()
        self.assertEqual(bench.calibrated_accept(s, d, cal.models[SIGLIP_MODEL], cal.models[DINO_MODEL]),
                         pair.accepted)
        self.assertAlmostEqual(bench.combine(s, d, "min"), min(s, d))
        with self.assertRaises(ValueError):
            bench.combine(s, d, "max")

    def test_models_point_at_production_ids(self):
        self.assertEqual(bench.MODELS, {"siglip": SIGLIP_MODEL, "dinov2": DINO_MODEL, "dinov3": DINOV3_MODEL})

    def test_summary_and_markdown(self):
        pairs = [{"id": f"p{i}", "label": "consistent" if i < 4 else "inconsistent",
                  "category": cat} for i, cat in enumerate(
            ["same_shot", "cross_shot_same_scene", "same_character_other_scene", "perturbed",
             "different_scene", "hard_negative"])]
        scores = {"p0": 0.95, "p1": 0.8, "p2": 0.5, "p3": 0.9, "p4": 0.2, "p5": 0.6}
        summary = bench.summarise(scores, pairs)
        self.assertAlmostEqual(summary["per_category_auroc"]["same_character_other_scene"], 0.5)
        self.assertEqual(summary["per_category_auroc"]["different_scene"], 1.0)
        table = bench.markdown({"models": {"x": summary},
                                "latency": {"x": {"median": 0.1, "mean": 0.1, "p90": 0.2, "threads": 4, "frames": 6}}})
        self.assertIn("| x |", table)


class PairTests(unittest.TestCase):
    shots = {
        "f1": [[i * 5.0, i * 5.0 + 4.5] for i in range(12)],
        "f2": [[i * 4.0, i * 4.0 + 3.8] for i in range(8)],
    }
    scenes = {
        "f1": [{"id": "a", "shots": [[0, 3], [10, 11]], "characters": ["hero"]},
               {"id": "b", "shots": [[4, 7]], "characters": ["hero", "foe"]},
               {"id": "c", "shots": [[8, 9]], "characters": ["villager"]}],
        "f2": [{"id": "x", "shots": [[0, 3]], "characters": ["robot"]},
               {"id": "y", "shots": [[4, 6]], "characters": ["robot"]}],
    }

    def refs(self):
        return bench.label_shots(self.shots, self.scenes)

    def palettes(self, refs):
        rng = random.Random(1)
        out = {}
        for ref in refs:
            raw = [rng.random() for _ in range(8)]
            out[ref.key] = [x / sum(raw) for x in raw]
        return out

    def test_scene_ranges_can_recur_and_characters_are_film_scoped(self):
        refs = {r.key: r for r in self.refs()}
        self.assertEqual(refs["f1-011"].scene, "f1:a")
        self.assertEqual(refs["f1-000"].characters, frozenset({"f1:hero"}))
        self.assertIsNone(refs["f2-007"].scene)
        with self.assertRaisesRegex(ValueError, "two scenes"):
            bench.label_shots(self.shots, {"f1": [{"id": "a", "shots": [[0, 2]]}, {"id": "b", "shots": [[2, 3]]}]})

    def test_pairs_are_labelled_honestly_and_deterministic(self):
        refs = self.refs()
        lookup = {r.key: r for r in refs}
        pairs = bench.build_pairs(refs, self.palettes(refs), per_category=6)
        self.assertEqual(pairs, bench.build_pairs(refs, self.palettes(refs), per_category=6))
        categories = {p["category"] for p in pairs}
        self.assertEqual(categories, set(bench.POSITIVE + bench.NEGATIVE))
        for pair in pairs:
            a, b = lookup[pair["a"][2]], lookup[pair["b"][2]]
            category = pair["category"]
            self.assertEqual(pair["label"], "consistent" if category in bench.POSITIVE else "inconsistent")
            if category in ("same_shot", "perturbed"):
                self.assertEqual(a.key, b.key)
            if category == "same_shot":
                self.assertGreater(pair["b"][1], pair["a"][1])
                self.assertLessEqual(pair["b"][1], a.end)
            if category == "cross_shot_same_scene":
                self.assertEqual(a.scene, b.scene)
                self.assertNotEqual(a.key, b.key)
            if category == "same_character_other_scene":
                self.assertNotEqual(a.scene, b.scene)
                self.assertTrue(a.characters & b.characters)
            if category in bench.NEGATIVE:
                self.assertNotEqual(a.scene, b.scene)
                self.assertFalse(a.characters & b.characters)
        kinds = [p["perturbation"] for p in pairs if p["category"] == "perturbed"]
        self.assertEqual(set(kinds), set(bench.PERTURBATIONS))
        self.assertTrue(json.dumps(pairs))

    def test_hard_negatives_prefer_matching_palettes(self):
        refs = self.refs()
        palettes = self.palettes(refs)
        pairs = bench.build_pairs(refs, palettes, per_category=4)
        hard = [bench.palette_similarity(palettes[p["a"][2]], palettes[p["b"][2]])
                for p in pairs if p["category"] == "hard_negative"]
        rand = [bench.palette_similarity(palettes[p["a"][2]], palettes[p["b"][2]])
                for p in pairs if p["category"] == "different_scene"]
        self.assertGreaterEqual(sum(hard) / len(hard), sum(rand) / len(rand))

    def test_palette_similarity_is_histogram_intersection(self):
        self.assertAlmostEqual(bench.palette_similarity([0.5, 0.5], [0.5, 0.5]), 1.0)
        self.assertAlmostEqual(bench.palette_similarity([1.0, 0.0], [0.0, 1.0]), 0.0)

    def test_sources_record_url_and_licence(self):
        for meta in bench.FILMS.values():
            self.assertTrue(meta["url"].startswith("https://download.blender.org/"))
            self.assertIn("CC BY", meta["licence"])
            self.assertTrue(meta["licence_url"].startswith("https://creativecommons.org/licenses/by/"))

    def test_checked_in_scene_labels_parse(self):
        scenes = json.loads((ROOT / "docs/continuity_qc_benchmark_scenes.json").read_text())["films"]
        self.assertEqual(set(scenes), set(bench.FILMS))
        fake = {film: [[i, i + 1.0] for i in range(300)] for film in scenes}
        self.assertTrue(any(r.scene for r in bench.label_shots(fake, scenes)))


@unittest.skipIf(PIL is None, "Pillow is an optional benchmark dependency")
class PerturbationTests(unittest.TestCase):
    def test_perturbations_keep_size_and_change_pixels(self):
        from PIL import Image

        image = Image.new("RGB", (64, 36))
        image.putdata([((x * 4) % 256, (y * 7) % 256, (x * y) % 256) for y in range(36) for x in range(64)])
        for kind in bench.PERTURBATIONS:
            with self.subTest(kind=kind):
                out = bench.perturb(image, kind, seed=1)
                self.assertEqual(out.size, image.size)
                self.assertNotEqual(list(out.convert("RGB").getdata()), list(image.getdata()))
        with self.assertRaises(ValueError):
            bench.perturb(image, "rotate")
        self.assertAlmostEqual(sum(bench.palette(image)), 1.0)


if __name__ == "__main__":
    unittest.main()
