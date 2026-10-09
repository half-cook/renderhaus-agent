from __future__ import annotations

import importlib
import math
import sys
import unittest
from unittest.mock import MagicMock, Mock, patch

from agent.deep_agent.continuity_qc import (
    DINO_MODEL,
    DINOV3_MODEL,
    SIGLIP_MODEL,
    ContinuityConfig,
    ContinuityQC,
    FaceIdentityResult,
    LazyImageEmbedder,
    Shot,
    cosine_similarity,
    training_loop_hook,
)


class FakeEmbedder:
    def __init__(self, model_id, vectors):
        self.model_id = model_id
        self.vectors = vectors
        self.frames = []

    def embed(self, frame):
        self.frames.append(frame)
        return self.vectors[frame]


class ContinuityQCTests(unittest.TestCase):
    def checker(self, siglip=None, dino=None, **kwargs):
        vectors = {"a": [1, 0], "b": [1, 0], "c": [0, 1]}
        return ContinuityQC(
            siglip=FakeEmbedder(SIGLIP_MODEL, siglip or vectors),
            dino=FakeEmbedder(DINO_MODEL, dino or vectors),
            **kwargs,
        )

    def test_adjacent_shots_score_both_models_and_report_drift(self):
        checker = self.checker()
        report = checker.score([Shot("one", "a"), Shot("two", "b"), Shot("three", "c")])
        self.assertEqual(
            [(pair.before, pair.after) for pair in report.pairs], [("one", "two"), ("two", "three")]
        )
        self.assertEqual(report.pairs[0].siglip_similarity, 1.0)
        self.assertEqual(report.pairs[0].dino_similarity, 1.0)
        self.assertTrue(report.pairs[0].accepted)
        self.assertLess(report.pairs[1].score, 0.5)  # mean calibrated probability
        self.assertFalse(report.pairs[1].accepted)
        self.assertFalse(report.accepted)
        self.assertEqual(checker.siglip.frames, ["a", "b", "c"])
        self.assertEqual(checker.dino.frames, ["a", "b", "c"])

    def test_each_model_must_pass_instead_of_hiding_drift_in_average(self):
        report = self.checker(dino={"a": [1, 0], "b": [0, 1]}).score(
            [Shot("one", "a"), Shot("two", "b")]
        )
        pair = report.pairs[0]
        self.assertGreater(pair.siglip_score, 0.9)
        self.assertLess(pair.dino_score, 0.2)  # below the per-model veto
        self.assertFalse(report.accepted)

    def test_face_identity_defaults_to_not_configured(self):
        pair = self.checker().score([Shot("one", "a"), Shot("two", "b")]).pairs[0]
        self.assertEqual(pair.face_identity.status, "not configured")
        self.assertIsNone(pair.face_identity.similarity)

    def test_licensed_face_identity_adapter_is_pluggable(self):
        face = Mock()
        face.compare.return_value = FaceIdentityResult("configured", 0.9)
        pair = self.checker(face_identity=face).score([Shot("one", "a"), Shot("two", "b")]).pairs[0]
        face.compare.assert_called_once_with("a", "b")
        self.assertEqual(pair.face_identity.similarity, 0.9)

    def test_requires_at_least_two_shots(self):
        for shots in ([], [Shot("one", "a")]):
            with self.subTest(shots=shots), self.assertRaisesRegex(ValueError, "two shots"):
                self.checker().score(shots)

    def test_cosine_is_scale_invariant_and_preserves_negative_similarity(self):
        self.assertAlmostEqual(cosine_similarity([2, 0], [5, 0]), 1.0)
        self.assertAlmostEqual(cosine_similarity([1, 0], [-1, 0]), -1.0)
        self.assertAlmostEqual(cosine_similarity([1, 1], [1, 0]), 1 / math.sqrt(2))

    def test_invalid_embeddings_fail_instead_of_scoring_as_consistent(self):
        for left, right in (
            ([], []),
            ([1, 2], [1]),
            ([0, 0], [1, 0]),
            ([float("nan")], [1]),
            ([float("inf")], [1]),
            ([1e308] * 4, [1] * 4),
        ):
            with self.subTest(left=left, right=right), self.assertRaises(ValueError):
                cosine_similarity(left, right)

    def test_config_rejects_invalid_threshold(self):
        for threshold in (-1.1, 1.1, float("nan")):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                ContinuityConfig(similarity_threshold=threshold)

    def test_only_approved_visual_models_can_score(self):
        with self.assertRaisesRegex(ValueError, "approved continuity model"):
            ContinuityQC(siglip=FakeEmbedder("other-model", {}), dino=FakeEmbedder(DINO_MODEL, {}))
        with self.assertRaisesRegex(ValueError, "approved continuity model"):
            LazyImageEmbedder("other-model")

    def test_dinov3_is_off_by_default_in_config_and_policy(self):
        from agent.deep_agent.routing import POLICY

        self.assertFalse(ContinuityConfig().enable_dinov3)
        self.assertFalse(POLICY["continuity_qc"]["dinov3_enabled"])
        checker = self.checker()
        self.assertEqual(checker.dino_model, DINO_MODEL)
        self.assertEqual(checker.score([Shot("one", "a"), Shot("two", "b")]).dino_model, DINO_MODEL)

    def test_dinov3_opt_in_replaces_the_dino_slot(self):
        vectors = {"a": [1, 0], "b": [1, 0], "c": [0, 1]}
        checker = ContinuityQC(
            siglip=FakeEmbedder(SIGLIP_MODEL, vectors),
            dino=FakeEmbedder(DINOV3_MODEL, vectors),
            config=ContinuityConfig(enable_dinov3=True),
        )
        report = checker.score([Shot("one", "a"), Shot("two", "b"), Shot("three", "c")])
        self.assertEqual(report.dino_model, DINOV3_MODEL)
        self.assertEqual([pair.accepted for pair in report.pairs], [True, False])
        self.assertEqual(checker.dino.frames, ["a", "b", "c"])

    def test_dino_slot_must_match_the_switch(self):
        with self.assertRaisesRegex(ValueError, "matching SigLIP/DINO slot"):
            self.checker(dino={"a": [1, 0]}, config=ContinuityConfig(enable_dinov3=True))
        with self.assertRaisesRegex(ValueError, "matching SigLIP/DINO slot"):
            ContinuityQC(
                siglip=FakeEmbedder(SIGLIP_MODEL, {}), dino=FakeEmbedder(DINOV3_MODEL, {}),
            )

    def test_dinov3_embedder_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(ValueError, "opt-in"):
            LazyImageEmbedder(DINOV3_MODEL)
        self.assertEqual(LazyImageEmbedder(DINOV3_MODEL, allow_dinov3=True).model_id, DINOV3_MODEL)

    def test_dinov3_default_construction_is_lazy(self):
        with patch.dict(sys.modules, {"torch": None, "transformers": None}):
            checker = ContinuityQC(config=ContinuityConfig(enable_dinov3=True))
            self.assertEqual(checker.dino.model_id, DINOV3_MODEL)
            with self.assertRaisesRegex(RuntimeError, "optional"):
                checker.dino.embed("frame")

    def dinov3_loader(self):
        transformers, torch = MagicMock(), MagicMock()
        model = transformers.AutoModel.from_pretrained.return_value
        model.return_value.last_hidden_state.__getitem__.return_value.squeeze.return_value.tolist.return_value = [0, 1]
        return transformers, torch

    def test_dinov3_loads_from_cache_with_token_only_from_environment(self):
        fake_token = "hf_fake_test_value"
        transformers, torch = self.dinov3_loader()
        with patch.dict(sys.modules, {"transformers": transformers, "torch": torch}), patch.dict(
            "os.environ", {"HF_TOKEN": fake_token}
        ):
            embedder = LazyImageEmbedder(DINOV3_MODEL, allow_dinov3=True)
            self.assertEqual(embedder.embed("frame"), [0, 1])
        for loader in (transformers.AutoModel, transformers.AutoImageProcessor):
            loader.from_pretrained.assert_called_once_with(
                DINOV3_MODEL, local_files_only=True, token=fake_token,
            )
        self.assertNotIn(fake_token, repr(vars(embedder)))
        model = transformers.AutoModel.from_pretrained.return_value
        model.return_value.last_hidden_state.__getitem__.assert_called_with((slice(None), 0))

    def test_dinov3_without_token_still_uses_local_cache_only(self):
        transformers, torch = self.dinov3_loader()
        with patch.dict(sys.modules, {"transformers": transformers, "torch": torch}), patch.dict(
            "os.environ", {}, clear=True
        ):
            LazyImageEmbedder(DINOV3_MODEL, allow_dinov3=True).embed("frame")
        transformers.AutoModel.from_pretrained.assert_called_once_with(DINOV3_MODEL, local_files_only=True)

    def test_dinov3_on_old_transformers_explains_version_without_leaking_token(self):
        transformers = Mock()
        transformers.AutoImageProcessor.from_pretrained.side_effect = ValueError(
            "Unrecognized model type dinov3_vit"
        )
        with patch.dict(sys.modules, {"transformers": transformers, "torch": MagicMock()}), patch.dict(
            "os.environ", {"HF_TOKEN": "hf_fake_test_value"}
        ):
            with self.assertRaisesRegex(RuntimeError, "transformers>=4.56") as caught:
                LazyImageEmbedder(DINOV3_MODEL, allow_dinov3=True).embed("frame")
        self.assertNotIn("hf_fake_test_value", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_dinov3_missing_from_cache_fails_with_provisioning_message(self):
        transformers = Mock()
        transformers.AutoImageProcessor.from_pretrained.side_effect = OSError("not cached")
        with patch.dict(sys.modules, {"transformers": transformers, "torch": MagicMock()}):
            with self.assertRaisesRegex(RuntimeError, "QC does not download"):
                LazyImageEmbedder(DINOV3_MODEL, allow_dinov3=True).embed("frame")

    def test_import_and_construction_do_not_load_optional_dependencies(self):
        with patch.dict(sys.modules, {"torch": None, "transformers": None}):
            module = importlib.reload(sys.modules["agent.deep_agent.continuity_qc"])
            checker = module.ContinuityQC()
            self.assertEqual(checker.siglip.model_id, SIGLIP_MODEL)
            with self.assertRaisesRegex(RuntimeError, "optional"):
                checker.siglip.embed("frame")

    def test_model_loader_uses_local_cache_without_weight_downloads(self):
        for model_id in (SIGLIP_MODEL, DINO_MODEL):
            with self.subTest(model=model_id):
                transformers = MagicMock()
                torch = MagicMock()
                model = transformers.AutoModel.from_pretrained.return_value
                model.get_image_features.return_value.squeeze.return_value.tolist.return_value = [
                    1,
                    0,
                ]
                model.return_value.last_hidden_state.__getitem__.return_value.squeeze.return_value.tolist.return_value = [
                    1,
                    0,
                ]
                with patch.dict(sys.modules, {"transformers": transformers, "torch": torch}), patch.dict(
                    "os.environ", {"HF_TOKEN": "hf_fake_test_value"}
                ):
                    embedder = LazyImageEmbedder(model_id)
                    self.assertEqual(embedder.embed("frame"), [1, 0])
                    self.assertEqual(embedder.embed("frame"), [1, 0])
                transformers.AutoModel.from_pretrained.assert_called_once_with(
                    model_id,
                    local_files_only=True,
                )
                transformers.AutoImageProcessor.from_pretrained.assert_called_once_with(
                    model_id,
                    local_files_only=True,
                )

    def test_siglip_handles_transformers_5_pooled_output(self):
        from types import SimpleNamespace

        transformers, torch = MagicMock(), MagicMock()
        pooled = MagicMock()
        pooled.squeeze.return_value.tolist.return_value = [0.6, 0.8]
        model = transformers.AutoModel.from_pretrained.return_value
        model.get_image_features.return_value = SimpleNamespace(pooler_output=pooled)
        with patch.dict(sys.modules, {"transformers": transformers, "torch": torch}):
            self.assertEqual(LazyImageEmbedder(SIGLIP_MODEL).embed("frame"), [0.6, 0.8])
        pooled.squeeze.assert_called_once_with(0)

    def test_missing_cached_weights_fail_with_provisioning_message(self):
        transformers = Mock()
        transformers.AutoImageProcessor.from_pretrained.side_effect = OSError("not cached")
        with patch.dict(sys.modules, {"transformers": transformers, "torch": MagicMock()}):
            with self.assertRaisesRegex(RuntimeError, "QC does not download"):
                LazyImageEmbedder(SIGLIP_MODEL).embed("frame")
        transformers.AutoModel.from_pretrained.assert_not_called()

    def test_training_hook_accepts_only_verified_apache_wan_assets(self):
        eligible = {
            "provider": "fal",
            "model": "fal-ai/wan-vace-14b",
            "status": "succeeded",
            "training_eligible": True,
            "weights_license": "Apache-2.0",
        }
        sink = Mock(return_value="recorded")
        self.assertEqual(training_loop_hook([eligible], sink), "recorded")
        sink.assert_called_once_with([eligible])

    def test_training_hook_rejects_every_noneligible_asset_before_side_effect(self):
        eligible = {
            "provider": "fal",
            "model": "fal-ai/wan-vace-14b",
            "status": "succeeded",
            "training_eligible": True,
            "weights_license": "Apache-2.0",
        }
        invalid = [
            {**eligible, "provider": name}
            for name in (
                "kling",
                "runway",
                "seedance",
                "seedream",
                "veo",
                "luma",
                "minimax",
                "hunyuan",
            )
        ] + [
            {**eligible, "weights_license": "unknown"},
            {**eligible, "training_eligible": False},
            {**eligible, "model": "unrecognised-wan"},
            {**eligible, "status": "dry_run"},
            {},
        ]
        for asset in invalid:
            with self.subTest(asset=asset):
                sink = Mock()
                with self.assertRaisesRegex(ValueError, "training-eligible"):
                    training_loop_hook([eligible, asset], sink)
                sink.assert_not_called()


if __name__ == "__main__":
    unittest.main()
