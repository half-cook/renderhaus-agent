"""Worker contract tests deliberately need no torch, RunPod, Pillow, or network."""

import base64
import importlib.util
import math
import os
from pathlib import Path
import socket
import sys
import time
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.deep_agent.continuity_qc import (
    ContinuityConfig,
    ContinuityQC,
    DINO_MODEL,
    DINOV3_MODEL,
    SIGLIP_MODEL,
    Shot,
)

WORKER = Path(__file__).resolve().parents[1] / "infra/runpod/continuity-qc"
sys.path.insert(0, str(WORKER))
from worker_logic import Limits, MODEL_IDS, _public_addresses, process_request  # noqa: E402


class FakeEmbedder:
    available_models = {"siglip", "dinov2"}

    def __init__(self, similarities=None):
        self.similarities = similarities or {"siglip": 0.9, "dinov2": 0.6, "dinov3": 0.5}
        self.calls = []

    def embed_batch(self, model, frames):
        self.calls.append((model, list(frames)))
        cosine = self.similarities[model]
        return [
            [2.0, 0.0] if frame == b"a" else [2 * cosine, 2 * math.sqrt(1 - cosine**2)]
            for frame in frames
        ]


def payload():
    return {
        "frames": [
            {"id": frame, "b64": base64.b64encode(frame.encode()).decode()} for frame in ("a", "b")
        ]
    }


class WorkerLogicTests(unittest.TestCase):
    def run_request(self, request=None, embedder=None, **kwargs):
        return process_request(
            request if request is not None else payload(),
            embedder or FakeEmbedder(),
            image_decoder=lambda data, limit: data,
            **kwargs,
        )

    def assert_invalid(self, request, **kwargs):
        result = self.run_request(request, **kwargs)
        self.assertEqual(result["error"]["code"], "invalid_input")

    def test_defaults_adjacent_models_and_scores(self):
        result = self.run_request()
        self.assertEqual(result["models"], {"siglip": SIGLIP_MODEL, "dinov2": DINO_MODEL})
        self.assertEqual([(row["before"], row["after"]) for row in result["pairs"]], [("a", "b")])
        self.assertTrue(result["pairs"][0]["accepted"])
        self.assertAlmostEqual(result["pairs"][0]["similarities"]["siglip"], 0.9)
        self.assertNotIn("embeddings", result)

    def test_embeddings_normalized_and_explicit_pair_order(self):
        request = payload() | {"pairs": [["b", "a"]], "return": ["embeddings"]}
        result = self.run_request(request)
        self.assertEqual(result["pairs"], [{"before": "b", "after": "a"}])
        for rows in result["embeddings"].values():
            for vector in rows.values():
                self.assertAlmostEqual(math.hypot(*vector), 1.0)

    def test_subset_allowed_for_similarity(self):
        result = self.run_request(payload() | {"models": ["siglip"], "return": ["similarities"]})
        self.assertEqual(set(result["pairs"][0]["similarities"]), {"siglip"})
        self.assertNotIn("accepted", result["pairs"][0])

    def test_score_requires_siglip_and_exactly_one_dino(self):
        for models in (["siglip"], ["dinov2"], ["siglip", "dinov2", "dinov3"]):
            self.assert_invalid(payload() | {"models": models, "return": ["scores"]})

    def test_dinov3_never_substituted_when_not_baked(self):
        result = self.run_request(payload() | {"models": ["siglip", "dinov3"]})
        self.assertEqual(result["error"]["code"], "model_unavailable")

    def test_decisions_match_local_including_drift_veto(self):
        class LocalEmbedder:
            def __init__(self, model_id, model, fake):
                self.model_id, self.model, self.fake = model_id, model, fake

            def embed(self, frame):
                return self.fake.embed_batch(self.model, [frame])[0]

        for dino_name, dino_id in (("dinov2", DINO_MODEL), ("dinov3", DINOV3_MODEL)):
            for siglip_cos, dino_cos in ((0.9, 0.6), (1.0, 0.0), (0.7, 0.4), (-0.5, -0.5)):
                with self.subTest(dino=dino_name, cosines=(siglip_cos, dino_cos)):
                    fake = FakeEmbedder({"siglip": siglip_cos, dino_name: dino_cos})
                    fake.available_models = {"siglip", dino_name}
                    result = self.run_request(payload() | {"models": ["siglip", dino_name]}, fake)
                    local = (
                        ContinuityQC(
                            siglip=LocalEmbedder(SIGLIP_MODEL, "siglip", fake),
                            dino=LocalEmbedder(dino_id, dino_name, fake),
                            config=ContinuityConfig(enable_dinov3=dino_name == "dinov3"),
                        )
                        .score([Shot("a", b"a"), Shot("b", b"b")])
                        .pairs[0]
                    )
                    row = result["pairs"][0]
                    self.assertEqual(row["accepted"], local.accepted)
                    self.assertAlmostEqual(row["score"], local.score)
                    self.assertAlmostEqual(row["probabilities"]["siglip"], local.siglip_score)
                    self.assertAlmostEqual(row["probabilities"][dino_name], local.dino_score)
                    if (siglip_cos, dino_cos) == (1.0, 0.0):
                        self.assertGreater(row["score"], 0.5)
                        self.assertFalse(row["accepted"])

    def test_strict_top_level(self):
        for request in (None, [], {}, payload() | {"unknown": 1}):
            result = process_request(request, FakeEmbedder(), image_decoder=lambda b, limit: b)
            self.assertEqual(result["error"]["code"], "invalid_input")

    def test_strict_frames(self):
        for frames in (
            [],
            "ab",
            [1],
            [{"id": "a"}],
            [{"id": "a", "b64": "YQ==", "url": "https://example.com/a"}],
            [{"id": "a", "b64": "YQ==", "extra": 1}],
            [{"id": "a", "b64": "YQ=="}] * 2,
        ):
            self.assert_invalid({"frames": frames})

    def test_bad_ids(self):
        for frame_id in ("", 1, "x" * 129, "a\n"):
            self.assert_invalid({"frames": [{"id": frame_id, "b64": "YQ=="}]})

    def test_invalid_base64(self):
        for value in ("", "%%%", "YQ==\n", 1):
            self.assert_invalid({"frames": [{"id": "a", "b64": value}]})

    def test_bounds(self):
        self.assert_invalid(payload(), limits=Limits(max_frames=1))
        self.assert_invalid(payload(), limits=Limits(max_total_bytes=1))
        self.assert_invalid(
            {"frames": [{"id": "a", "b64": "YWJjZA=="}]}, limits=Limits(max_frame_bytes=3)
        )
        self.assert_invalid(payload() | {"pairs": [["a", "b"]] * 3}, limits=Limits(max_pairs=2))

    def test_models_and_return_validation(self):
        for key, values in (
            ("models", ([], "siglip", ["bad"], ["siglip", "siglip"], [1])),
            ("return", ([], "scores", ["bad"], ["scores", "scores"], [1])),
        ):
            for value in values:
                self.assert_invalid(payload() | {key: value})

    def test_pair_validation(self):
        for pairs in ("ab", [["a"]], [["a", "c"]], [["a", "a"]], [[1, "b"]]):
            self.assert_invalid(payload() | {"pairs": pairs})

    def test_https_only_no_private_targets(self):
        for url in (
            "http://example.com/a",
            "https://localhost/a",
            "https://127.0.0.1/a",
            "https://[::1]/a",
            "https://10.0.0.1/a",
            "https://169.254.169.254/a",
            "https://user:pass@example.com/a",
            "https://example.com:444/a",
            "https://example.com/a#fragment",
            "https://example.com/a\n",
        ):
            self.assert_invalid(
                {"frames": [{"id": "a", "url": url}]}, url_fetcher=lambda url, limit, timeout: b"a"
            )

    def test_url_timeout_and_bytes_passed_to_fetcher(self):
        with patch("worker_logic.fetch_url", return_value=b"a") as fetch:
            result = self.run_request({"frames": [{"id": "a", "url": "https://example.com/a"}]})
            self.assertNotIn("error", result)
            fetch.assert_called_once_with("https://example.com/a", 8 * 1024 * 1024, 10.0)

    def test_fetch_error_sanitized(self):
        def fetch(*args):
            raise TimeoutError("https://signed-secret.example.com?token=SECRET")

        result = self.run_request(
            {"frames": [{"id": "a", "url": "https://example.com/a"}]}, url_fetcher=fetch
        )
        self.assertEqual(result["error"]["code"], "fetch_error")
        self.assertNotIn("SECRET", str(result))

    def test_injected_fetch_cannot_bypass_byte_limit(self):
        self.assert_invalid(
            {"frames": [{"id": "a", "url": "https://example.com/a"}]},
            url_fetcher=lambda *args: b"abcd",
            limits=Limits(max_frame_bytes=3),
        )

    def test_decoder_checks_pixels_and_rejects_animated_images(self):
        from worker_logic import decode_image

        for size, count in (((2, 2), 1), ((3, 2), 1), ((2, 2), 2), ((0, 2), 1)):
            image = MagicMock()
            image.size, image.n_frames, image.format = size, count, "PNG"
            image.__enter__.return_value = image
            image.convert.return_value = "decoded_rgb"
            with patch.dict(
                sys.modules,
                {"PIL": SimpleNamespace(Image=SimpleNamespace(open=lambda data: image))},
            ):
                if size == (2, 2) and count == 1:
                    self.assertEqual(decode_image(b"png", 4), "decoded_rgb")
                    image.convert.assert_called_once_with("RGB")
                else:
                    with self.assertRaises(ValueError):
                        decode_image(b"png", 4)
                    image.convert.assert_not_called()

    def test_decoder_allows_only_safe_raster_formats_before_conversion(self):
        from worker_logic import decode_image

        for image_format in ("PNG", "JPEG", "WEBP", "EPS", "TIFF", "PDF", None):
            with self.subTest(format=image_format):
                image = MagicMock()
                image.format, image.size, image.n_frames = image_format, (2, 2), 1
                image.__enter__.return_value = image
                image.convert.return_value = "decoded_rgb"
                with patch.dict(
                    sys.modules,
                    {"PIL": SimpleNamespace(Image=SimpleNamespace(open=lambda data: image))},
                ):
                    if image_format in ("PNG", "JPEG", "WEBP"):
                        self.assertEqual(decode_image(b"frame", 4), "decoded_rgb")
                        image.convert.assert_called_once_with("RGB")
                    else:
                        with self.assertRaises(ValueError):
                            decode_image(b"frame", 4)
                        image.convert.assert_not_called()
                        image.load.assert_not_called()

    def test_disallowed_image_returns_error_without_model_inference(self):
        image = MagicMock()
        image.format, image.size, image.n_frames = "EPS", (2, 2), 1
        image.__enter__.return_value = image
        fake = FakeEmbedder()
        with patch.dict(
            sys.modules, {"PIL": SimpleNamespace(Image=SimpleNamespace(open=lambda data: image))}
        ):
            result = process_request(payload(), fake)
        self.assertEqual(result["error"]["code"], "image_error")
        image.convert.assert_not_called()
        image.load.assert_not_called()
        self.assertEqual(fake.calls, [])

    def test_total_bytes_rejected_before_model_inference(self):
        fake = FakeEmbedder()
        self.assert_invalid(payload(), embedder=fake, limits=Limits(max_total_bytes=1))
        self.assertEqual(fake.calls, [])

    def test_image_decode_error_sanitized(self):
        def decode(*args):
            raise ValueError("SECRET")

        result = process_request(payload(), FakeEmbedder(), image_decoder=decode)
        self.assertEqual(result["error"]["code"], "image_error")
        self.assertNotIn("SECRET", str(result))

    def test_bad_embeddings(self):
        for rows in (
            [[0.0, 0.0]] * 2,
            [[float("nan")]] * 2,
            [[1.0]],
            [[1.0], [1.0, 2.0]],
            [[1.0, True]] * 2,
            [[float("inf")]] * 2,
        ):
            fake = FakeEmbedder()
            fake.embed_batch = lambda *args: rows
            result = self.run_request(embedder=fake)
            self.assertEqual(result["error"]["code"], "embedding_error")

    def test_embedder_failure_sanitized(self):
        fake = FakeEmbedder()

        def embed(*args):
            raise RuntimeError("SECRET")

        fake.embed_batch = embed
        result = self.run_request(embedder=fake)
        self.assertEqual(result["error"]["code"], "embedding_error")
        self.assertNotIn("SECRET", str(result))

    def test_registry_is_shared_model_ids(self):
        self.assertEqual(
            MODEL_IDS, {"siglip": SIGLIP_MODEL, "dinov2": DINO_MODEL, "dinov3": DINOV3_MODEL}
        )

    def test_dns_private_and_mixed_answers_rejected(self):
        for ips in (("127.0.0.1",), ("1.1.1.1", "10.0.0.1"), ("::1",)):
            resolver = lambda *args: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips
            ]
            with self.assertRaises(ValueError):
                _public_addresses("example.com", resolver=resolver)
        resolver = lambda *args: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443))]
        self.assertEqual(_public_addresses("example.com", resolver=resolver), ["1.1.1.1"])

    def test_url_redirect_and_declared_oversize_rejected(self):
        from worker_logic import fetch_url

        for status, length in ((302, None), (200, "999")):
            connection = MagicMock()
            connection.getresponse.return_value.status = status
            connection.getresponse.return_value.getheader.return_value = length
            with (
                patch("worker_logic._public_addresses", return_value=["1.1.1.1"]),
                patch("worker_logic._PinnedHTTPSConnection", return_value=connection) as make,
            ):
                with self.assertRaises(ValueError):
                    fetch_url("https://example.com/image?presigned=PRIVATE", 8, 10)
                make.assert_called_once()
                self.assertEqual(make.call_args.args[:2], ("example.com", "1.1.1.1"))
                connection.close.assert_called_once()
                connection.getresponse.return_value.read1.assert_not_called()

    def test_url_deadline_bounds_slow_final_read(self):
        from worker_logic import fetch_url

        connection = MagicMock()
        response = connection.getresponse.return_value
        response.status = 200
        response.getheader.return_value = None

        def slow_eof(*args):
            time.sleep(0.2)
            return b""

        response.read1.side_effect = slow_eof
        with (
            patch("worker_logic._public_addresses", return_value=["1.1.1.1"]),
            patch("worker_logic._PinnedHTTPSConnection", return_value=connection),
        ):
            start = time.monotonic()
            with self.assertRaises(TimeoutError):
                fetch_url("https://example.com/a", 8, 0.02)
            self.assertLess(time.monotonic() - start, 0.15)

    def test_url_streaming_limit_and_total_timeout(self):
        from worker_logic import fetch_url

        for clock, chunks, error in (
            ([0, 1, 2], [b"123456789"], ValueError),
            ([0, 1, 11], [], TimeoutError),
        ):
            connection = MagicMock()
            response = connection.getresponse.return_value
            response.status = 200
            response.getheader.return_value = None
            response.read1.side_effect = chunks
            with (
                patch("worker_logic._public_addresses", return_value=["1.1.1.1"]),
                patch("worker_logic._PinnedHTTPSConnection", return_value=connection),
                patch("worker_logic.time.monotonic", side_effect=clock),
            ):
                with self.assertRaises(error):
                    fetch_url("https://example.com/a", 8, 10)
                connection.close.assert_called_once()


class WorkerAdapterTests(unittest.TestCase):
    def load_handler(self, cuda=False):
        class Tensor:
            def __init__(self, rows):
                self.rows = rows

            def to(self, device):
                return self

            def float(self):
                return self

            def cpu(self):
                return self

            def tolist(self):
                return self.rows

            def squeeze(self, *args):
                return self

            def __getitem__(self, index):
                return self

        class Model:
            def eval(self):
                return self

            def to(self, device):
                return self

            def get_image_features(self, **inputs):
                return SimpleNamespace(
                    pooler_output=Tensor([[1.0, 2.0] for _ in inputs["pixels"].rows])
                )

            def __call__(self, **inputs):
                return SimpleNamespace(
                    last_hidden_state=Tensor([[3.0, 4.0] for _ in inputs["pixels"].rows])
                )

        processor = MagicMock(side_effect=lambda images, return_tensors: {"pixels": Tensor(images)})
        auto_processor = SimpleNamespace(from_pretrained=MagicMock(return_value=processor))
        auto_model = SimpleNamespace(from_pretrained=MagicMock(side_effect=lambda *a, **k: Model()))
        torch = SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: cuda),
            float16="fp16",
            inference_mode=MagicMock(side_effect=nullcontext),
            autocast=MagicMock(side_effect=lambda **kwargs: nullcontext()),
        )
        modules = {
            "torch": torch,
            "runpod": SimpleNamespace(),
            "transformers": SimpleNamespace(
                AutoImageProcessor=auto_processor, AutoModel=auto_model
            ),
        }
        spec = importlib.util.spec_from_file_location(
            "worker_adapter_under_test", WORKER / "handler.py"
        )
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules), patch.dict(os.environ, {}, clear=False):
            spec.loader.exec_module(module)
        return module, torch, auto_model, processor

    def test_models_load_once_and_runtime_is_offline(self):
        module, _, auto_model, _ = self.load_handler()
        self.assertEqual(auto_model.from_pretrained.call_count, 2)
        module.handler({"input": {}})
        module.handler(None)
        self.assertEqual(auto_model.from_pretrained.call_count, 2)
        for call in auto_model.from_pretrained.call_args_list:
            self.assertEqual(call.kwargs, {"local_files_only": True, "token": False})

    def test_cpu_batching_siglip5_pooling_and_dino_cls(self):
        module, torch, _, processor = self.load_handler()
        module.EMBEDDER.batch_size = 2
        self.assertEqual(module.EMBEDDER.embed_batch("siglip", [1, 2, 3]), [[1.0, 2.0]] * 3)
        self.assertEqual(module.EMBEDDER.embed_batch("dinov2", [1, 2, 3]), [[3.0, 4.0]] * 3)
        self.assertEqual(
            [call.kwargs["images"] for call in processor.call_args_list], [[1, 2], [3], [1, 2], [3]]
        )
        self.assertEqual(torch.inference_mode.call_count, 4)
        torch.autocast.assert_not_called()

    def test_cuda_uses_fp16_autocast_and_bad_batch_rejected(self):
        module, torch, _, _ = self.load_handler(cuda=True)
        module.EMBEDDER.embed_batch("siglip", [1])
        torch.autocast.assert_called_once_with(device_type="cuda", dtype="fp16")
        for size in (0, 9):
            with self.assertRaises(ValueError):
                module.TorchEmbedder("/nonexistent", batch_size=size)


@unittest.skipUnless(
    importlib.util.find_spec("torch") and importlib.util.find_spec("runpod"),
    "optional GPU worker dependencies are absent; core contract tests run offline",
)
class WorkerDependencyTests(unittest.TestCase):
    def test_optional_dependencies_import(self):
        import runpod
        import torch

        self.assertTrue(callable(runpod.serverless.start))
        self.assertTrue(callable(torch.inference_mode))


if __name__ == "__main__":
    unittest.main()
