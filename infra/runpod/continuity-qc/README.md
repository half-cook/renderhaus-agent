# Continuity QC GPU worker

This image embeds supplied still frames with SigLIP and DINOv2. It imports the
production calibration module and JSON unchanged. Optional DINOv3 replaces the
DINO slot only when requested and baked into the image. Scores use the production
mean calibrated probability and 0.2 single-model drift veto. Calibration measures
visual similarity, not face identity, and still needs Renderhaus-specific labels.

Run all commands from the repository root. Docker is unavailable on the current
implementation host, so this image has not been built or measured there.

## Build and run

```bash
docker buildx build --platform linux/amd64 --load \
  -f infra/runpod/continuity-qc/Dockerfile \
  -t YOUR_REGISTRY/continuity-qc:VERSION .
docker run --rm --gpus all YOUR_REGISTRY/continuity-qc:VERSION \
  python handler.py --test_input "$(cat infra/runpod/continuity-qc/test_input.json)"
# CPU test uses the same image without a GPU allocation.
docker run --rm YOUR_REGISTRY/continuity-qc:VERSION \
  python handler.py --test_input "$(cat infra/runpod/continuity-qc/test_input.json)"
```

The Dockerfile-specific ignore file includes only the worker and shared maths.
Model downloads happen during the build, pinned to the benchmark's Hugging Face
snapshot revisions in `download_models.py`. Runtime loads use `local_files_only`,
`token=False`, and `HF_HUB_OFFLINE=1`; they do not download models. Models load once
when `handler.py` imports. Set `CONTINUITY_QC_BATCH_SIZE=1..8`, default 4, to tune
memory. CUDA uses fp16 autocast under inference mode. CPU uses fp32.

DINOv3 requires acceptance of the Meta DINOv3 Licence and legal review before
production. Commercial use has conditions. Preserve the downloaded licence in
`/models/dinov3/LICENSE*` when redistributing this image. Provide HF_TOKEN to your
build environment securely, then use only the BuildKit secret:

```bash
docker buildx build --platform linux/amd64 --load \
  -f infra/runpod/continuity-qc/Dockerfile \
  --build-arg INCLUDE_DINOV3=1 --secret id=hf_token,env=HF_TOKEN \
  -t YOUR_REGISTRY/continuity-qc:VERSION .
```

The token is never an ARG or ENV, never saved into model files, and never printed.
The download script reads it directly from `/run/secrets/hf_token`. Public-model
builds pass `token=False` and do not read ambient Hugging Face credentials.

## Local CPU test without Docker

Keep GPU packages out of the project environment. Use a throwaway Python 3.11
venv and download public weights into `/tmp`:

```bash
python3.11 -m venv /tmp/continuity-qc-cpu
/tmp/continuity-qc-cpu/bin/pip install \
  torch==2.8.0 torchvision==0.23.0 --index-url https://download.pytorch.org/whl/cpu
/tmp/continuity-qc-cpu/bin/pip install -r infra/runpod/continuity-qc/requirements.txt
export PYTHONPATH="$PWD:$PWD/infra/runpod/continuity-qc"
/tmp/continuity-qc-cpu/bin/python infra/runpod/continuity-qc/download_models.py \
  --model-dir /tmp/continuity-qc-models
cd infra/runpod/continuity-qc
CONTINUITY_QC_MODEL_DIR=/tmp/continuity-qc-models \
  /tmp/continuity-qc-cpu/bin/python handler.py --test_input "$(cat test_input.json)"
```

The fixture contains two deterministic 2x2 PNGs, a red square and a blue square,
constructed from pixels with stdlib PNG encoding. It contains no sourced media.
A successful local SDK result has model IDs and one finite scored pair. Actual
GPU throughput and image size require a later Docker build and GPU run.

## Input and output

RunPod jobs wrap this object in `{"input": ...}`:

```json
{
  "frames": [{"id": "a", "b64": "..."}, {"id": "b", "url": "https://..."}],
  "models": ["siglip", "dinov2"],
  "pairs": [["a", "b"]],
  "return": ["embeddings", "similarities", "scores"]
}
```

`models` defaults to SigLIP and DINOv2, `pairs` to adjacent frames, and `return`
to similarities and scores. Embeddings are optional L2-normalized float lists.
Model subsets are allowed for embeddings or similarities. Scores require SigLIP
and exactly one DINO model. The worker never substitutes models.

```json
{
  "models": {"siglip": "google/siglip-so400m-patch14-384", "dinov2": "facebook/dinov2-base"},
  "pairs": [{"before": "a", "after": "b", "similarities": {"siglip": 0.9, "dinov2": 0.6},
             "probabilities": {"siglip": 0.987, "dinov2": 0.972}, "accepted": true, "score": 0.979}],
  "embeddings": {"siglip": {"a": [1.0, 0.0], "b": [0.9, 0.435889894]},
                 "dinov2": {"a": [1.0, 0.0], "b": [0.6, 0.8]}}
}
```

The example probabilities are rounded illustrations. Production computes them
from `agent/deep_agent/continuity_qc_calibration.json`. Errors return
`{"error":{"code":"invalid_input","message":"..."}}` with sanitized messages.
Errors never include frame URLs, payloads, exception text, or secrets.

Limits are 8 frames, 8 MiB per decoded frame payload, 24 MiB total payload,
20 million pixels per still image, 64 pairs, and 128 ASCII characters per unique
ID. IDs accept letters, digits, `_`, `.`, `:`, and `-`. Requests reject unknown
fields, duplicate model/output names, invalid base64, invalid pair IDs, and unknown
models. HTTPS fetches allow only port 443, validate all resolved addresses as
public, pin the approved IP for TLS, reject redirects, limit streamed bytes,
and enforce a 10-second deadline. Private DNS answers and mixed public/private
answers fail. Use short-lived presigned S3 URLs without logging them.

Run offline logic tests with the project's existing venv. They inject an embedder
and image decoder; they need no worker dependencies or network:

```bash
.venv/bin/python -m unittest discover -s tests -p test_continuity_qc_worker.py -q
```

See [the RunPod deployment guide](../../../docs/CONTINUITY_QC_RUNPOD.md) for endpoint setup and Renderhaus configuration.
