from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agent.deep_agent.continuity_qc import ContinuityConfig, ContinuityQC, Shot
from test_continuity_qc import FakeEmbedder
from agent.deep_agent.continuity_qc import SIGLIP_MODEL, DINO_MODEL


class VLMBackendTests(unittest.TestCase):
    def checker(self, **kwargs):
        vectors = {"a": [1, 0], "b": [1, 0], "c": [-1, 0]}
        return ContinuityQC(siglip=FakeEmbedder(SIGLIP_MODEL, vectors),
                            dino=FakeEmbedder(DINO_MODEL, vectors), **kwargs)

    def test_default_does_not_invoke_vlm(self):
        judge = Mock()
        report = self.checker(judge=judge).score([Shot("1", "a"), Shot("2", "b")])
        self.assertTrue(report.accepted)
        judge.judge.assert_not_called()

    def test_vlm_decision_preserves_embedding_metric(self):
        from providers.gemini.contracts import GeminiJudgement

        judge = Mock()
        judge.judge.return_value = GeminiJudgement(same_shot_continuity=False,
                                                   confidence=0.9, issues=["wardrobe changed"])
        report = self.checker(config=ContinuityConfig(backend="vlm"), judge=judge).score(
            [Shot("1", "a"), Shot("2", "b")])
        self.assertFalse(report.accepted)
        self.assertEqual(report.pairs[0].siglip_similarity, 1)
        self.assertGreater(report.pairs[0].score, 0.9)
        self.assertEqual(report.pairs[0].judgement.issues, ["wardrobe changed"])
        judge.judge.assert_called_once_with("a", "b")

    def test_clear_rejection_never_sends_frames(self):
        judge = Mock()
        report = self.checker(config=ContinuityConfig(backend="vlm"), judge=judge).score(
            [Shot("1", "a"), Shot("2", "c")])
        self.assertEqual(report.status, "completed")
        self.assertFalse(report.accepted)
        self.assertEqual(report.pairs[0].judge_status, "prefilter_rejected")
        judge.judge.assert_not_called()

    def test_prefilter_can_be_disabled(self):
        from providers.gemini.contracts import GeminiJudgement

        judge = Mock()
        judge.judge.return_value = GeminiJudgement(same_shot_continuity=True, confidence=1, issues=[])
        report = self.checker(config=ContinuityConfig(backend="vlm", vlm_prefilter_threshold=0),
                              judge=judge).score([Shot("1", "a"), Shot("2", "c")])
        self.assertTrue(report.accepted)
        judge.judge.assert_called_once()

    def test_failure_skips_report_retaining_scores_and_redacts_exception(self):
        judge = Mock()
        judge.judge.side_effect = RuntimeError("GEMINI_API_KEY=should-never-appear")
        report = self.checker(config=ContinuityConfig(backend="vlm"), judge=judge).score(
            [Shot("1", "a"), Shot("2", "b"), Shot("3", "c")])
        self.assertEqual(report.status, "skipped")
        self.assertEqual(len(report.pairs), 2)
        self.assertEqual(report.pairs[0].siglip_similarity, 1)
        self.assertNotIn("should-never", report.reason)
        self.assertFalse(report.accepted)

    def test_runpod_can_supply_prefilter_metrics(self):
        from providers.gemini.contracts import GeminiJudgement

        judge = Mock()
        judge.judge.return_value = GeminiJudgement(same_shot_continuity=True, confidence=.8, issues=[])
        with patch("agent.deep_agent.continuity_qc_runpod.runpod_similarities", return_value=[(.9, .8)]):
            report = self.checker(config=ContinuityConfig(backend="vlm", embedding_backend="runpod"),
                                  judge=judge).score([Shot("1", "a"), Shot("2", "b")])
        self.assertTrue(report.accepted)
        self.assertEqual(report.pairs[0].dino_similarity, .8)

    def test_dry_run_has_no_network(self):
        with patch.dict(os.environ, {"GEMINI_DRY_RUN": "true"}), patch(
                "urllib.request.OpenerDirector.open", side_effect=AssertionError("network")):
            report = self.checker(config=ContinuityConfig(backend="vlm")).score(
                [Shot("1", "a"), Shot("2", "b")])
        self.assertEqual(report.status, "skipped")
        self.assertIn("dry-run", report.reason)

    def test_invalid_prefilter_is_rejected(self):
        for value in (-.1, 1.1, float("nan"), True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ContinuityConfig(vlm_prefilter_threshold=value)

    def test_embedding_host_configuration_is_respected(self):
        with patch.dict(os.environ, {"CONTINUITY_QC_EMBEDDING_BACKEND": "runpod"}):
            self.assertEqual(ContinuityConfig(backend="vlm").embedding_backend, "runpod")


class VLMEvalGateTests(unittest.TestCase):
    def setUp(self):
        from agent.deep_agent import continuity_qc_vlm as vlm

        self.vlm = vlm
        self.rows = json.loads(vlm.SCORES_PATH.read_text())["pairs"]

    def result(self, correct=420, **kwargs):
        from agent.deep_agent.continuity_qc import load_calibration

        config = ContinuityConfig(backend="local")
        calibration = load_calibration()
        decisions = []
        for i, pair in enumerate(self.rows):
            same = pair["label"] == "consistent"
            prediction = same if i < correct else not same
            _, siglip, dino = calibration.decide(pair["siglip"], pair["dinov2"], DINO_MODEL, config)
            decisions.append({"id": pair["id"], "status": "completed", "same_shot_continuity":
                              prediction, "cascade_accepted": prediction and
                              (siglip + dino) / 2 >= config.vlm_prefilter_threshold,
                              "confidence": .9, "issues": []})
        return self.vlm.eval_report(decisions, live=True, **kwargs)

    def test_threshold_is_strict_and_recomputed(self):
        from agent.deep_agent.routing import POLICY

        with patch.dict(POLICY["continuity_qc"], {"vlm_prefilter_threshold": 0}):
            low = self.result(357)
            low["accuracy"] = 1
            self.assertFalse(self.vlm.eval_qualifies(low))
            self.assertTrue(self.vlm.eval_qualifies(self.result(358)))

    def test_receipt_requires_full_strict_judgements(self):
        for field, value in (("confidence", "bad"), ("issues", "bad"), ("confidence", float("nan"))):
            result = self.result()
            result["decisions"][0][field] = value
            with self.subTest(field=field, value=value):
                self.assertFalse(self.vlm.eval_qualifies(result))
        result = self.result()
        del result["decisions"][0]["confidence"]
        self.assertFalse(self.vlm.eval_qualifies(result))

    def test_gate_rejects_impossible_cascade_decisions(self):
        from agent.deep_agent.routing import POLICY

        with patch.dict(POLICY["continuity_qc"], {"vlm_prefilter_threshold": 1}):
            result = self.result()
            for row in result["decisions"]:
                row["cascade_accepted"] = row["same_shot_continuity"]
            self.assertFalse(self.vlm.eval_qualifies(result))

    def test_helper_cannot_call_live_adapter_without_live_flag(self):
        from scripts.continuity_qc_benchmark import evaluate_vlm

        with patch.dict(os.environ, {"GEMINI_DRY_RUN": "false"}), patch(
                "providers.gemini.api.judge_pair") as judge, self.assertRaisesRegex(ValueError, "live"):
            evaluate_vlm([], Path("unused"))
        judge.assert_not_called()

    def test_provenance_config_and_coverage_cannot_be_bypassed(self):
        for field, value in [("live", False), ("model", "unverified"), ("rubric_sha256", "bad"),
                             ("dataset_sha256", "bad"), ("calibration_sha256", "bad"),
                             ("prefilter_threshold", .3)]:
            result = self.result()
            result[field] = value
            with self.subTest(field=field):
                self.assertFalse(self.vlm.eval_qualifies(result))
        for change in (lambda rows: rows.pop(), lambda rows: rows.append(rows[0]),
                       lambda rows: rows[0].update(status="skipped"),
                       lambda rows: rows[0].update(same_shot_continuity=1)):
            result = self.result()
            change(result["decisions"])
            self.assertFalse(self.vlm.eval_qualifies(result))

    def test_no_committed_result_means_no_promotion(self):
        self.assertFalse(self.vlm.default_vlm_enabled())
        from agent.deep_agent.routing import POLICY, route_intent, select_provider

        choice = {**POLICY["capability_map"]["continuity_qc"], "default": "gemini_vlm_judge"}
        with patch.dict(POLICY["capability_map"], {"continuity_qc": choice}):
            self.assertEqual(route_intent("check continuity").alias, "local_qc")
            self.assertEqual(select_provider("continuity_qc").alias, "local_qc")
        with patch.dict(os.environ, {"CONTINUITY_QC_BACKEND": "local"}):
            self.assertEqual(ContinuityConfig().backend, "local")

    def test_configured_receipt_requires_matching_digest(self):
        from agent.deep_agent.routing import POLICY

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eval.json"
            path.write_text(json.dumps(self.result()))
            gate = {**POLICY["continuity_qc"]["vlm_eval_gate"], "result_sha256": self.vlm.file_hash(path)}
            with patch.object(self.vlm, "EVAL_PATH", path), patch.dict(
                    POLICY["continuity_qc"], {"vlm_eval_gate": gate}):
                self.assertTrue(self.vlm.default_vlm_enabled())
                path.write_text("{}")
                self.assertFalse(self.vlm.default_vlm_enabled())
                path.write_text("[" * 1500 + "0" + "]" * 1500)
                gate["result_sha256"] = self.vlm.file_hash(path)
                self.assertFalse(self.vlm.default_vlm_enabled())

    def test_metrics_include_all_rows_and_per_category_acceptance(self):
        report = self.result(358)
        self.assertEqual(report["pairs"], 420)
        self.assertEqual(report["accuracy"], 358 / 420)
        self.assertEqual(len(report["per_category"]), 6)
        self.assertTrue(all(row["pairs"] == 70 for row in report["per_category"].values()))
        self.assertFalse(self.vlm.eval_qualifies(self.vlm.eval_report(report["decisions"], live=False)))

    def test_canonical_labels_are_not_taken_from_work_manifest(self):
        from scripts.continuity_qc_benchmark import validate_vlm_pairs
        from agent.deep_agent.routing import POLICY

        pairs = [{"id": row["id"], "label": row["label"], "category": row["category"],
                  "a": ["film", 1, "shot", "scene"], "b": ["film", 2, "shot", "scene"],
                  "perturbation": None} for row in self.rows]
        with patch.dict(POLICY["continuity_qc"]["vlm_eval_gate"], {"manifest_sha256": self.vlm.manifest_hash(pairs)}):
            validate_vlm_pairs(pairs, self.rows)
            pairs[0]["label"] = "inconsistent"
            with self.assertRaises(ValueError):
                validate_vlm_pairs(pairs, self.rows)

    def test_explicit_candidate_routing_does_not_promote_default(self):
        from agent.deep_agent.routing import route_intent

        route = route_intent("VLM judge the keyframes for wardrobe consistency")
        self.assertEqual(route.alias, "gemini_vlm_judge")
        self.assertEqual(route.tool, "Gemini___judge_continuity")
        self.assertIn("experimental", route.disclosure.lower())
        self.assertEqual(route_intent("check continuity", confidential=True).alias, "local_qc")
        self.assertEqual(route_intent("Use Gemini to check continuity").alias, "gemini_vlm_judge")

    def test_continuity_preserves_explicit_requests_and_exclusions(self):
        from agent.deep_agent.routing import select_provider

        self.assertEqual(select_provider("continuity_qc", provider="kling").status, "blocked")
        self.assertEqual(select_provider("continuity_qc", provider="gemini",
                                        excluded_providers=["gemini"]).status, "blocked")

    def test_mock_benchmark_runs_420_images_without_promotable_evidence(self):
        from PIL import Image
        from providers.gemini.contracts import GeminiJudgement
        from scripts.continuity_qc_benchmark import evaluate_vlm, frame_name, vlm_inputs_hash
        from agent.deep_agent.routing import POLICY

        pairs = [{"id": row["id"], "label": row["label"], "category": row["category"],
                  "a": ["film", 1, "shot", "scene"], "b": ["film", 2, "shot", "scene"],
                  "perturbation": None} for row in self.rows]
        client = Mock()
        client.judge.side_effect = [GeminiJudgement(same_shot_continuity=row["label"] == "consistent",
                                                    confidence=.9, issues=[]) for row in self.rows]
        with tempfile.TemporaryDirectory() as tmp:
            frames = Path(tmp)
            for t in (1, 2):
                Image.new("RGB", (16, 16), "blue").save(frames / frame_name("film", t))
            with patch.dict(POLICY["continuity_qc"]["vlm_eval_gate"], {
                    "manifest_sha256": self.vlm.manifest_hash(pairs),
                    "inputs_sha256": vlm_inputs_hash(pairs, frames)}):
                result = evaluate_vlm(pairs, frames, client=client)
        self.assertEqual(client.judge.call_count, 420)
        self.assertEqual(result["accuracy"], 1)
        self.assertTrue(result["complete"])
        self.assertFalse(result["live"])
        self.assertFalse(self.vlm.eval_qualifies(result))

    def test_benchmark_missing_frames_fails_before_client(self):
        from scripts.continuity_qc_benchmark import evaluate_vlm
        from agent.deep_agent.routing import POLICY

        pairs = [{"id": row["id"], "label": row["label"], "category": row["category"],
                  "a": ["film", 1, "shot", "scene"], "b": ["film", 2, "shot", "scene"],
                  "perturbation": None} for row in self.rows]
        client = Mock()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(POLICY["continuity_qc"]["vlm_eval_gate"], {
                "manifest_sha256": self.vlm.manifest_hash(pairs)}), self.assertRaisesRegex(ValueError, "frames"):
            evaluate_vlm(pairs, Path(tmp), client=client)
        client.judge.assert_not_called()

    def test_changed_manifest_rejected_before_client(self):
        from scripts.continuity_qc_benchmark import validate_vlm_pairs

        pairs = [{"id": row["id"], "label": row["label"], "category": row["category"],
                  "a": ["film", 1, "shot", "scene"], "b": ["film", 2, "shot", "scene"],
                  "perturbation": None} for row in self.rows]
        with self.assertRaisesRegex(ValueError, "manifest"):
            validate_vlm_pairs(pairs, self.rows)
