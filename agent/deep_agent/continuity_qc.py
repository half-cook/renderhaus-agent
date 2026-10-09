"""Adjacent-shot visual consistency without required ML dependencies.

Frames are caller-supplied decoded images. Optional transformers and torch load
only on the first embedding request, using already cached weights. This module
never downloads weights. Scores measure visual similarity, not face identity.

DINOv3 (facebook/dinov3-vitb16-pretrain-lvd1689m) is an opt-in replacement for the
DINOv2 slot behind routing_policy.json ``continuity_qc.dinov3_enabled`` (default
false). It is gated on Hugging Face and ships under the DINOv3 Licence, not
Apache-2.0: commercial use is allowed with conditions (pass the licence on when
redistributing, cite it in publications, trade controls and no military use, the
licence ends if you sue Meta over IP, and Meta may change the terms). Get legal
review before enabling it in production. Weights must already be in the local
Hugging Face cache; HF_TOKEN is read from the environment only and never logged.
Benchmark: docs/CONTINUITY_QC_BENCHMARK.md.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence, TypeVar


SIGLIP_MODEL = "google/siglip-so400m-patch14-384"
DINO_MODEL = "facebook/dinov2-base"
DINOV3_MODEL = "facebook/dinov3-vitb16-pretrain-lvd1689m"
DINOV3_MIN_TRANSFORMERS = "4.56"
APPROVED_MODELS = frozenset({SIGLIP_MODEL, DINO_MODEL})
OPT_IN_MODELS = frozenset({DINOV3_MODEL})
CALIBRATION_PATH = Path(__file__).with_name("continuity_qc_calibration.json")
RULES = ("calibrated_mean", "legacy_min")
TrainingResult = TypeVar("TrainingResult")


class ImageEmbedder(Protocol):
    model_id: str

    def embed(self, frame: Any) -> Sequence[float]: ...


@dataclass(frozen=True)
class FaceIdentityResult:
    status: str
    similarity: float | None = None


class FaceIdentity(Protocol):
    def compare(self, before: Any, after: Any) -> FaceIdentityResult: ...


class UnconfiguredFaceIdentity:
    def compare(self, before: Any, after: Any) -> FaceIdentityResult:
        return FaceIdentityResult(status="not configured")


@dataclass(frozen=True)
class ContinuityConfig:
    """Acceptance rule for adjacent shots.

    ``calibrated_mean`` (default): map each model's cosine to a probability with its own
    calibration, accept when the mean probability >= ``acceptance_threshold`` and no single
    model falls below ``veto_threshold``. ``legacy_min`` keeps the old
    ``min(siglip, dino) >= similarity_threshold`` rule for comparison only; DINO cosines run
    far lower than SigLIP's, so it rejects most true continuity pairs.
    """

    similarity_threshold: float = 0.8
    enable_dinov3: bool = False
    rule: str = "calibrated_mean"
    acceptance_threshold: float | None = None
    veto_threshold: float | None = None
    backend: str = field(default_factory=lambda: os.environ.get("CONTINUITY_QC_BACKEND", "local"))

    def __post_init__(self):
        if not math.isfinite(self.similarity_threshold) or not -1 <= self.similarity_threshold <= 1:
            raise ValueError("similarity_threshold must be finite and between -1 and 1.")
        if self.rule not in RULES:
            raise ValueError(f"rule must be one of {RULES}.")
        for name in ("acceptance_threshold", "veto_threshold"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError(f"{name} must be a probability between 0 and 1.")


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


@dataclass(frozen=True)
class Calibration:
    """Per-model Platt scaling: probability = sigmoid(slope * cosine + intercept)."""

    models: dict[str, tuple[float, float]]
    acceptance_threshold: float = 0.5
    veto_threshold: float = 0.2
    method: str = "platt-logistic-class-balanced"
    warning: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    def probability(self, model_id: str, cosine: float) -> float:
        if model_id not in self.models:
            raise ValueError(f"No continuity calibration for {model_id}.")
        slope, intercept = self.models[model_id]
        return _sigmoid(slope * cosine + intercept)

    def decide(self, siglip: float, dino: float, dino_model: str,
               config: ContinuityConfig) -> tuple[bool, float, float]:
        """Return (accepted, siglip_probability, dino_probability)."""
        p_siglip = self.probability(SIGLIP_MODEL, siglip)
        p_dino = self.probability(dino_model, dino)
        if config.rule == "legacy_min":
            return min(siglip, dino) >= config.similarity_threshold, p_siglip, p_dino
        acceptance = config.acceptance_threshold if config.acceptance_threshold is not None else self.acceptance_threshold
        veto = config.veto_threshold if config.veto_threshold is not None else self.veto_threshold
        accepted = (p_siglip + p_dino) / 2 >= acceptance and min(p_siglip, p_dino) >= veto
        return accepted, p_siglip, p_dino


def load_calibration(path: Path | str | None = None) -> Calibration:
    """Load the committed calibration (see docs/CONTINUITY_QC_BENCHMARK.md)."""
    data = json.loads(Path(path or CALIBRATION_PATH).read_text())
    models = {}
    for model_id, fit in data["models"].items():
        slope, intercept = float(fit["slope"]), float(fit["intercept"])
        if not (math.isfinite(slope) and math.isfinite(intercept)) or slope <= 0:
            raise ValueError(f"Invalid continuity calibration for {model_id}.")
        models[model_id] = (slope, intercept)
    return Calibration(
        models=models,
        acceptance_threshold=float(data["acceptance_threshold"]),
        veto_threshold=float(data["veto_threshold"]),
        method=data["method"],
        warning=data.get("warning", ""),
        metrics=data.get("metrics", {}),
    )


@dataclass(frozen=True)
class Shot:
    shot_id: str
    frame: Any


@dataclass(frozen=True)
class ShotPairScore:
    before: str
    after: str
    siglip_similarity: float
    dino_similarity: float
    face_identity: FaceIdentityResult
    accepted: bool
    siglip_score: float | None = None
    dino_score: float | None = None

    @property
    def score(self) -> float:
        """Mean calibrated probability (raw cosine mean only if uncalibrated)."""
        if self.siglip_score is None or self.dino_score is None:
            return (self.siglip_similarity + self.dino_similarity) / 2
        return (self.siglip_score + self.dino_score) / 2


@dataclass(frozen=True)
class ContinuityReport:
    pairs: tuple[ShotPairScore, ...]
    similarity_threshold: float
    dino_model: str = DINO_MODEL
    rule: str = "calibrated_mean"
    acceptance_threshold: float | None = None
    status: str = "completed"
    reason: str = ""

    @property
    def accepted(self) -> bool:
        return self.status == "completed" and all(pair.accepted for pair in self.pairs)


class LazyImageEmbedder:
    def __init__(self, model_id: str, *, allow_dinov3: bool = False):
        if model_id in OPT_IN_MODELS and not allow_dinov3:
            raise ValueError(
                "DINOv3 is opt-in: enable continuity_qc.dinov3_enabled after licence review."
            )
        if model_id not in APPROVED_MODELS | OPT_IN_MODELS:
            raise ValueError("Use an approved continuity model, SigLIP or DINOv2.")
        self.model_id = model_id
        self._model = None
        self._processor = None
        self._torch = None

    def _load_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"local_files_only": True}
        if self.model_id == DINOV3_MODEL and os.environ.get("HF_TOKEN"):
            # Gated repo: the token only ever comes from the environment.
            kwargs["token"] = os.environ["HF_TOKEN"]
        return kwargs

    def embed(self, frame: Any) -> Sequence[float]:
        if self._model is None:
            try:
                import torch
                from transformers import AutoImageProcessor, AutoModel
            except ImportError as exc:
                raise RuntimeError(
                    "Continuity embeddings need optional torch and transformers packages."
                ) from exc
            kwargs = self._load_kwargs()
            try:
                processor = AutoImageProcessor.from_pretrained(self.model_id, **kwargs)
                model = AutoModel.from_pretrained(self.model_id, **kwargs)
            except OSError as exc:
                raise RuntimeError(
                    f"Continuity weights for {self.model_id} are not cached locally. "
                    "Provision approved weights separately; QC does not download them."
                ) from exc
            except (KeyError, ValueError):
                if self.model_id != DINOV3_MODEL:
                    raise
                raise RuntimeError(
                    f"DINOv3 needs transformers>={DINOV3_MIN_TRANSFORMERS} with DINOv3ViTModel support."
                ) from None
            model.eval()
            self._processor, self._model, self._torch = processor, model, torch
        inputs = self._processor(images=frame, return_tensors="pt")
        # DINOv2 and DINOv3 both expose the normalised CLS token at position 0
        # (DINOv3 register tokens follow it), so one pooling path serves both.
        with self._torch.inference_mode():
            if self.model_id == SIGLIP_MODEL:
                embedding = self._model.get_image_features(**inputs)
                # transformers 5 returns BaseModelOutputWithPooling; 4.x returns the tensor.
                if not hasattr(embedding, "squeeze") and hasattr(embedding, "pooler_output"):
                    embedding = embedding.pooler_output
            else:
                embedding = self._model(**inputs).last_hidden_state[:, 0]
        return embedding.squeeze(0).tolist()


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) == 0 or len(left) != len(right):
        raise ValueError("Embeddings must be nonempty and have matching dimensions.")
    if not all(math.isfinite(value) for value in (*left, *right)):
        raise ValueError("Embedding values must be finite.")
    left_norm, right_norm = math.hypot(*left), math.hypot(*right)
    if not left_norm or not right_norm:
        raise ValueError("Embeddings must have nonzero magnitude.")
    if not math.isfinite(left_norm) or not math.isfinite(right_norm):
        raise ValueError("Embedding magnitudes must be finite.")
    similarity = math.fsum(
        (a / left_norm) * (b / right_norm) for a, b in zip(left, right, strict=True)
    )
    return max(-1.0, min(1.0, similarity))


class ContinuityQC:
    def __init__(
        self,
        *,
        siglip: ImageEmbedder | None = None,
        dino: ImageEmbedder | None = None,
        face_identity: FaceIdentity | None = None,
        config: ContinuityConfig | None = None,
        calibration: Calibration | None = None,
    ):
        from agent.deep_agent.routing import POLICY

        self.config = config or ContinuityConfig(
            enable_dinov3=POLICY["continuity_qc"]["dinov3_enabled"]
        )
        self.dino_model = DINOV3_MODEL if self.config.enable_dinov3 else DINO_MODEL
        self.siglip = siglip or LazyImageEmbedder(SIGLIP_MODEL)
        self.dino = dino or LazyImageEmbedder(self.dino_model, allow_dinov3=self.config.enable_dinov3)
        if self.siglip.model_id != SIGLIP_MODEL or self.dino.model_id != self.dino_model:
            raise ValueError(
                "Use an approved continuity model in its matching SigLIP/DINO slot "
                "(DINOv3 only when continuity_qc.dinov3_enabled is on)."
            )
        self.face_identity = face_identity or UnconfiguredFaceIdentity()
        self.calibration = calibration or load_calibration()
        missing = {SIGLIP_MODEL, self.dino_model} - set(self.calibration.models)
        if missing:
            raise ValueError(f"Continuity calibration is missing {sorted(missing)}.")

    def score(self, shots: Sequence[Shot]) -> ContinuityReport:
        if self.config.backend != "local":
            from agent.deep_agent.continuity_qc_runpod import RunPodBackendError, runpod_similarities

            try:
                if self.config.backend != "runpod":
                    raise RunPodBackendError("Continuity backend must be local or runpod.")
                similarities = runpod_similarities(shots, self.dino_model)
                return self._report(shots, similarities)
            except RunPodBackendError as exc:
                reason = str(exc)
            except Exception as exc:
                reason = f"RunPod continuity QC failed ({type(exc).__name__})."
            acceptance = (self.config.acceptance_threshold if self.config.acceptance_threshold is not None
                          else self.calibration.acceptance_threshold)
            return ContinuityReport((), self.config.similarity_threshold, self.dino_model,
                                    self.config.rule, acceptance if self.config.rule == "calibrated_mean" else None,
                                    status="skipped", reason=reason)
        if len(shots) < 2:
            raise ValueError("Continuity QC needs at least two shots.")
        embeddings = [
            (self.siglip.embed(shot.frame), self.dino.embed(shot.frame)) for shot in shots
        ]
        similarities = [
            (cosine_similarity(embeddings[index][0], embeddings[index + 1][0]),
             cosine_similarity(embeddings[index][1], embeddings[index + 1][1]))
            for index in range(len(shots) - 1)
        ]
        return self._report(shots, similarities)

    def _report(self, shots: Sequence[Shot], similarities: Sequence[tuple[float, float]]) -> ContinuityReport:
        pairs = []
        for index, (before, after) in enumerate(zip(shots, shots[1:])):
            siglip, dino = similarities[index]
            accepted, p_siglip, p_dino = self.calibration.decide(siglip, dino, self.dino_model, self.config)
            pairs.append(
                ShotPairScore(
                    before=before.shot_id,
                    after=after.shot_id,
                    siglip_similarity=siglip,
                    dino_similarity=dino,
                    face_identity=self.face_identity.compare(before.frame, after.frame),
                    accepted=accepted,
                    siglip_score=p_siglip,
                    dino_score=p_dino,
                )
            )
        acceptance = (self.config.acceptance_threshold if self.config.acceptance_threshold is not None
                      else self.calibration.acceptance_threshold)
        return ContinuityReport(tuple(pairs), self.config.similarity_threshold, self.dino_model,
                                self.config.rule, acceptance if self.config.rule == "calibrated_mean" else None)


def training_loop_hook(
    assets: Sequence[dict[str, Any]],
    consume: Callable[[list[dict[str, Any]]], TrainingResult],
) -> TrainingResult:
    """Validate every asset before a training consumer has any side effects."""
    from agent.deep_agent.routing import training_eligible

    batch = list(assets)
    for index, asset in enumerate(batch):
        if not training_eligible(asset):
            raise ValueError(
                f"Asset {index} is not training-eligible. Only verified Apache-2.0 Wan assets qualify."
            )
    return consume(batch)
