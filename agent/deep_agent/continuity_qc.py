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

import math
import os
from dataclasses import dataclass
from typing import Any, Callable, Protocol, Sequence, TypeVar


SIGLIP_MODEL = "google/siglip-so400m-patch14-384"
DINO_MODEL = "facebook/dinov2-base"
DINOV3_MODEL = "facebook/dinov3-vitb16-pretrain-lvd1689m"
DINOV3_MIN_TRANSFORMERS = "4.56"
APPROVED_MODELS = frozenset({SIGLIP_MODEL, DINO_MODEL})
OPT_IN_MODELS = frozenset({DINOV3_MODEL})
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
    similarity_threshold: float = 0.8
    enable_dinov3: bool = False

    def __post_init__(self):
        if not math.isfinite(self.similarity_threshold) or not -1 <= self.similarity_threshold <= 1:
            raise ValueError("similarity_threshold must be finite and between -1 and 1.")


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

    @property
    def score(self) -> float:
        return (self.siglip_similarity + self.dino_similarity) / 2


@dataclass(frozen=True)
class ContinuityReport:
    pairs: tuple[ShotPairScore, ...]
    similarity_threshold: float
    dino_model: str = DINO_MODEL

    @property
    def accepted(self) -> bool:
        return all(pair.accepted for pair in self.pairs)


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

    def score(self, shots: Sequence[Shot]) -> ContinuityReport:
        if len(shots) < 2:
            raise ValueError("Continuity QC needs at least two shots.")
        embeddings = [
            (self.siglip.embed(shot.frame), self.dino.embed(shot.frame)) for shot in shots
        ]
        pairs = []
        for index, (before, after) in enumerate(zip(shots, shots[1:])):
            siglip = cosine_similarity(embeddings[index][0], embeddings[index + 1][0])
            dino = cosine_similarity(embeddings[index][1], embeddings[index + 1][1])
            pairs.append(
                ShotPairScore(
                    before=before.shot_id,
                    after=after.shot_id,
                    siglip_similarity=siglip,
                    dino_similarity=dino,
                    face_identity=self.face_identity.compare(before.frame, after.frame),
                    accepted=min(siglip, dino) >= self.config.similarity_threshold,
                )
            )
        return ContinuityReport(tuple(pairs), self.config.similarity_threshold, self.dino_model)


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
