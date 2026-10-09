"""Bake approved weights. Public repositories never use ambient credentials."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys

from huggingface_hub import snapshot_download
from huggingface_hub.utils import disable_progress_bars

from worker_logic import MODEL_IDS

MODEL_REVISIONS = {
    "siglip": "9fdffc58afc957d1a03a25b10dba0329ab15c2a3",
    "dinov2": "f9e44c814b77203eaa57a6bdbbd535f21ede1415",
    "dinov3": "5931719e67bbdb9737e363e781fb0c67687896bc",
}


def download_models(model_dir, include_dinov3=False):
    disable_progress_bars()
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    models = ["siglip", "dinov2"] + (["dinov3"] if include_dinov3 else [])
    for name in models:
        token = False
        if name == "dinov3":
            secret = Path("/run/secrets/hf_token")
            if not secret.is_file():
                raise RuntimeError("DINOv3 build needs the hf_token BuildKit secret.")
            token = secret.read_text().strip()
            if not token:
                raise RuntimeError("DINOv3 BuildKit secret is empty.")
        destination = Path(model_dir) / name
        snapshot_download(
            MODEL_IDS[name],
            revision=MODEL_REVISIONS[name],
            local_dir=destination,
            token=token,
            allow_patterns=["*.json", "*.safetensors", "*.txt", "LICENSE*", "license*"],
            ignore_patterns=["onnx/*", "tflite/*", "tf_model*", "flax_model*"],
        )
        token = False
        shutil.rmtree(destination / ".cache", ignore_errors=True)
        if name == "dinov3" and not any(destination.glob("LICENSE*")):
            raise RuntimeError(
                "DINOv3 licence artifact is missing; do not redistribute this image."
            )
        print(f"Baked {name} weights and repository metadata.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", default="/models")
    parser.add_argument("--include-dinov3", choices=("0", "1"), default="0")
    args = parser.parse_args()
    try:
        download_models(args.model_dir, args.include_dinov3 == "1")
    except Exception:
        print(
            "Model download failed. Check build access, disk space, and gated-model licence approval.",
            file=sys.stderr,
        )
        sys.exit(1)
