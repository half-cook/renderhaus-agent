# syntax=docker/dockerfile:1.7
FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime
WORKDIR /app
COPY infra/runpod/continuity-qc/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
RUN mkdir -p /app/agent/deep_agent && touch /app/agent/__init__.py /app/agent/deep_agent/__init__.py
COPY agent/deep_agent/continuity_qc.py agent/deep_agent/continuity_qc_calibration.json /app/agent/deep_agent/
COPY infra/runpod/continuity-qc/worker_logic.py infra/runpod/continuity-qc/download_models.py infra/runpod/continuity-qc/handler.py infra/runpod/continuity-qc/test_input.json /app/
ARG INCLUDE_DINOV3=0
RUN --mount=type=secret,id=hf_token \
    HF_HOME=/tmp/model-build-cache HF_HUB_DISABLE_IMPLICIT_TOKEN=1 \
    python /app/download_models.py --include-dinov3 "$INCLUDE_DINOV3" \
    && rm -rf /tmp/model-build-cache
ENV RUNPOD_LOG_LEVEL=INFO HF_HUB_OFFLINE=1 HF_HUB_DISABLE_IMPLICIT_TOKEN=1 CONTINUITY_QC_MODEL_DIR=/models CONTINUITY_QC_BATCH_SIZE=4
CMD ["python", "-u", "/app/handler.py"]
