"""Exercise the actual client/worker JSON boundary with offline frame adapters."""

import base64
import io
import json
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.deep_agent.continuity_qc import (
    DINO_MODEL, DINOV3_MODEL, SIGLIP_MODEL, ContinuityConfig, ContinuityQC, Shot,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "infra/runpod/continuity-qc"))
from worker_logic import process_request  # noqa: E402


class Frame:
    def __init__(self, data):
        self.data = data

    def save(self, stream, *, format):
        if format != "PNG":
            raise AssertionError("Client must send PNGs")
        stream.write(self.data)


class Embeddings:
    available_models = {"siglip", "dinov2", "dinov3"}

    def __init__(self, siglip, dino):
        self.cosines = {"siglip": siglip, "dinov2": dino, "dinov3": dino}

    def embed_batch(self, model, frames):
        cosine = self.cosines[model]
        return [[1.0, 0.0] if frame == b"a" else [cosine, math.sqrt(1 - cosine**2)]
                for frame in frames]


class LocalEmbedding:
    def __init__(self, model_id, name, embeddings):
        self.model_id, self.name, self.embeddings = model_id, name, embeddings

    def embed(self, frame):
        return self.embeddings.embed_batch(self.name, [frame.data])[0]


class RunPodContractTests(unittest.TestCase):
    def test_client_worker_roundtrip_preserves_models_pairs_and_host_decisions(self):
        for dinov3 in (False, True):
            for siglip, dino in ((0.92, 0.74), (1.0, 0.0), (0.55, 0.11)):
                with self.subTest(dinov3=dinov3, cosines=(siglip, dino)):
                    embedder = Embeddings(siglip, dino)
                    frames = [Shot("a", Frame(b"a")), Shot("b", Frame(b"b"))]
                    dino_id = DINOV3_MODEL if dinov3 else DINO_MODEL
                    dino_name = "dinov3" if dinov3 else "dinov2"

                    def http(request, **kwargs):
                        self.assertEqual(request.get_method(), "POST")
                        self.assertEqual(request.full_url, "https://api.runpod.ai/v2/offline/runsync")
                        payload = json.loads(request.data)["input"]
                        self.assertEqual(base64.b64decode(payload["frames"][0]["b64"]), b"a")
                        output = process_request(payload, embedder,
                                                 image_decoder=lambda data, max_pixels: data)
                        self.assertNotIn("error", output)
                        return io.BytesIO(json.dumps({"status": "COMPLETED", "output": output}).encode())

                    with patch.dict("os.environ", {
                        "RUNPOD_API_KEY": "offline-test-key",
                        "CONTINUITY_QC_RUNPOD_ENDPOINT_ID": "offline",
                    }, clear=True), patch("agent.deep_agent.continuity_qc_runpod._open", http):
                        remote = ContinuityQC(config=ContinuityConfig(
                            backend="runpod", enable_dinov3=dinov3)).score(frames)
                        local = ContinuityQC(
                            siglip=LocalEmbedding(SIGLIP_MODEL, "siglip", embedder),
                            dino=LocalEmbedding(dino_id, dino_name, embedder),
                            config=ContinuityConfig(backend="local", enable_dinov3=dinov3),
                        ).score(frames)
                    self.assertEqual(remote.status, "completed")
                    self.assertEqual(remote.accepted, local.accepted)
                    self.assertEqual(remote.dino_model, dino_id)
                    self.assertAlmostEqual(remote.pairs[0].siglip_score, local.pairs[0].siglip_score)
                    self.assertAlmostEqual(remote.pairs[0].dino_score, local.pairs[0].dino_score)
                    self.assertEqual(remote.accepted, (siglip, dino) == (0.92, 0.74))
