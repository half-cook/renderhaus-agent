"""RunPod adapter. Baked models load once at module initialization."""

from __future__ import annotations

from contextlib import nullcontext
import os
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"

import runpod  # noqa: E402
import torch  # noqa: E402
from transformers import AutoImageProcessor, AutoModel  # noqa: E402

from worker_logic import MODEL_IDS, process_request  # noqa: E402


class TorchEmbedder:
    def __init__(self, model_dir, batch_size=4):
        if not 1 <= batch_size <= 8:
            raise ValueError("CONTINUITY_QC_BATCH_SIZE must be between 1 and 8.")
        self.batch_size = batch_size
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.models, self.processors = {}, {}
        for name in MODEL_IDS:
            path = Path(model_dir) / name
            if name == "dinov3" and not path.is_dir():
                continue
            try:
                self.processors[name] = AutoImageProcessor.from_pretrained(
                    str(path), local_files_only=True, token=False
                )
                self.models[name] = (
                    AutoModel.from_pretrained(str(path), local_files_only=True, token=False)
                    .eval()
                    .to(self.device)
                )
            except Exception:
                raise RuntimeError(
                    f"Baked {name} model could not load; check image provisioning."
                ) from None
        self.available_models = frozenset(self.models)

    def embed_batch(self, model, frames):
        vectors = []
        for start in range(0, len(frames), self.batch_size):
            inputs = self.processors[model](
                images=frames[start : start + self.batch_size], return_tensors="pt"
            )
            inputs = {key: value.to(self.device) for key, value in inputs.items()}
            precision = (
                torch.autocast(device_type="cuda", dtype=torch.float16)
                if self.device == "cuda"
                else nullcontext()
            )
            with torch.inference_mode(), precision:
                if model == "siglip":
                    embedding = self.models[model].get_image_features(**inputs)
                    if not hasattr(embedding, "squeeze") and hasattr(embedding, "pooler_output"):
                        embedding = embedding.pooler_output
                else:
                    embedding = self.models[model](**inputs).last_hidden_state[:, 0]
                vectors.extend(embedding.float().cpu().tolist())
        return vectors


EMBEDDER = TorchEmbedder(
    os.environ.get("CONTINUITY_QC_MODEL_DIR", "/models"),
    int(os.environ.get("CONTINUITY_QC_BATCH_SIZE", "4")),
)


def handler(job):
    return process_request(job.get("input") if isinstance(job, dict) else None, EMBEDDER)


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
