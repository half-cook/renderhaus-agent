"""Offline continuity-qc embedder benchmark on openly licensed films.

Stages (run in order; every stage is offline once footage and weights are local):

    detect  PySceneDetect shot boundaries for each film in the manifest.
    sheets  Contact sheets of mid-shot frames used to hand-label scenes.
    pairs   Build labelled frame pairs from shots plus the hand-labelled scene file.
    embed   Embed every frame with each model on CPU and time it.
    report  AUROC (overall, per category, bootstrap CI), best-threshold accuracy,
            cross-validated threshold accuracy and latency, as JSON and Markdown.
    calibrate  Fit per-model Platt scaling from docs/continuity_qc_benchmark_scores.json
            and write agent/deep_agent/continuity_qc_calibration.json.

Embeddings use agent.deep_agent.continuity_qc.LazyImageEmbedder, the production
code path, which loads weights with local_files_only=True. Weights must already be
in the Hugging Face cache; a gated model such as DINOv3 reads HF_TOKEN from the
environment only. This script never prints, stores or logs the token.

Example:
    python scripts/continuity_qc_benchmark.py detect --footage F --work W
    python scripts/continuity_qc_benchmark.py sheets --footage F --work W
    python scripts/continuity_qc_benchmark.py pairs --footage F --work W \
        --scenes docs/continuity_qc_benchmark_scenes.json
    python scripts/continuity_qc_benchmark.py embed --work W
    python scripts/continuity_qc_benchmark.py report --work W --out docs/continuity_qc_benchmark_results.json
"""

from __future__ import annotations

import argparse
import io
import json
import math
import random
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FILMS = {
    "sintel": {
        "title": "Sintel (2010)",
        "file": "Sintel.2010.720p.mkv",
        "url": "https://download.blender.org/durian/movies/Sintel.2010.720p.mkv.zip",
        "licence": "CC BY 3.0 (c) copyright Blender Foundation | durian.blender.org",
        "licence_url": "https://creativecommons.org/licenses/by/3.0/",
    },
    "bbb": {
        "title": "Big Buck Bunny (2008)",
        "file": "BigBuckBunny_640x360.m4v",
        "url": "https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_640x360.m4v.zip",
        "licence": "CC BY 3.0 (c) copyright 2008, Blender Foundation | www.bigbuckbunny.org",
        "licence_url": "https://creativecommons.org/licenses/by/3.0/",
    },
    "ed": {
        "title": "Elephants Dream (2006)",
        "file": "elephantsdream-480-h264-st-aac.mov",
        "url": "https://download.blender.org/ED/elephantsdream-480-h264-st-aac.mov",
        "licence": "CC BY 2.5 (c) copyright 2006, Blender Foundation / Netherlands Media Art Institute | www.elephantsdream.org",
        "licence_url": "https://creativecommons.org/licenses/by/2.5/",
    },
    "tos": {
        "title": "Tears of Steel (2012)",
        "file": "tears_of_steel_720p.mov",
        "url": "https://download.blender.org/demo/movies/ToS/tears_of_steel_720p.mov",
        "licence": "CC BY 3.0 (c) copyright Blender Foundation | mango.blender.org",
        "licence_url": "https://creativecommons.org/licenses/by/3.0/",
    },
}

MODELS = {
    "siglip": "google/siglip-so400m-patch14-384",
    "dinov2": "facebook/dinov2-base",
    "dinov3": "facebook/dinov3-vitb16-pretrain-lvd1689m",
}
COMBOS = {"siglip+dinov2": ("siglip", "dinov2"), "siglip+dinov3": ("siglip", "dinov3")}
POSITIVE = ("same_shot", "cross_shot_same_scene", "same_character_other_scene", "perturbed")
NEGATIVE = ("different_scene", "hard_negative")
PERTURBATIONS = ("grade", "crop", "blur", "jpeg")
FRAME_HEIGHT = 360


# ---------------------------------------------------------------- metrics (pure)

def auroc(positives: Sequence[float], negatives: Sequence[float]) -> float:
    """Mann-Whitney AUROC with average ranks for ties."""
    if not positives or not negatives:
        raise ValueError("AUROC needs at least one positive and one negative score.")
    scored = sorted([(s, 1) for s in positives] + [(s, 0) for s in negatives])
    rank_sum, index = 0.0, 0
    while index < len(scored):
        end = index
        while end + 1 < len(scored) and scored[end + 1][0] == scored[index][0]:
            end += 1
        average = (index + end) / 2 + 1
        rank_sum += average * sum(label for _, label in scored[index:end + 1])
        index = end + 1
    n_pos, n_neg = len(positives), len(negatives)
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def best_threshold(scores: Sequence[float], labels: Sequence[int]) -> tuple[float, float]:
    """Threshold (accept if score >= t) maximising accuracy, and that accuracy."""
    if not scores or len(scores) != len(labels):
        raise ValueError("Scores and labels must be nonempty and aligned.")
    candidates = sorted(set(scores))
    cuts = [candidates[0] - 1e-9] + [
        (a + b) / 2 for a, b in zip(candidates, candidates[1:])
    ] + [candidates[-1] + 1e-9]
    best = (cuts[0], -1.0)
    for cut in cuts:
        accuracy = accuracy_at(scores, labels, cut)
        if accuracy > best[1]:
            best = (cut, accuracy)
    return best


def accuracy_at(scores: Sequence[float], labels: Sequence[int], threshold: float) -> float:
    return sum((s >= threshold) == bool(y) for s, y in zip(scores, labels)) / len(scores)


def cross_validated_accuracy(scores: Sequence[float], labels: Sequence[int], *, folds: int = 5,
                             seed: int = 0) -> float:
    """Pick the threshold on k-1 folds, score the held-out fold; less optimistic."""
    order = list(range(len(scores)))
    random.Random(seed).shuffle(order)
    correct = 0
    for fold in range(folds):
        held = set(order[fold::folds])
        train = [i for i in order if i not in held]
        threshold, _ = best_threshold([scores[i] for i in train], [labels[i] for i in train])
        correct += sum((scores[i] >= threshold) == bool(labels[i]) for i in held)
    return correct / len(scores)


def bootstrap_auroc(positives: Sequence[float], negatives: Sequence[float], *,
                    rounds: int = 1000, seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    values = sorted(
        auroc([rng.choice(positives) for _ in positives], [rng.choice(negatives) for _ in negatives])
        for _ in range(rounds)
    )
    return values[int(0.025 * rounds)], values[int(0.975 * rounds) - 1]


def paired_bootstrap_delta(left: dict[str, float], right: dict[str, float], pairs: Sequence[dict], *,
                           rounds: int = 1000, seed: int = 0) -> dict[str, float]:
    """AUROC(left) - AUROC(right) on the same resampled pairs (stratified by label).

    Returns the point delta, a 95% interval and the share of resamples where left wins."""
    pos = [p["id"] for p in pairs if p["label"] == "consistent"]
    neg = [p["id"] for p in pairs if p["label"] != "consistent"]

    def delta(ps, ns):
        return (auroc([left[i] for i in ps], [left[i] for i in ns])
                - auroc([right[i] for i in ps], [right[i] for i in ns]))

    rng = random.Random(seed)
    draws = sorted(delta([rng.choice(pos) for _ in pos], [rng.choice(neg) for _ in neg]) for _ in range(rounds))
    return {"delta": delta(pos, neg), "ci95": [draws[int(0.025 * rounds)], draws[int(0.975 * rounds) - 1]],
            "p_left_better": sum(d > 0 for d in draws) / rounds}


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


def fit_platt(scores: Sequence[float], labels: Sequence[int], *, l2: float = 1e-4,
              iterations: int = 100) -> tuple[float, float]:
    """Class-balanced Platt scaling: p = sigmoid(slope * cosine + intercept).

    Newton's method on weighted logistic loss; each class carries half the total weight,
    so p = 0.5 is the equal-error boundary regardless of class imbalance."""
    positives = sum(1 for y in labels if y)
    negatives = len(labels) - positives
    if not positives or not negatives or len(scores) != len(labels):
        raise ValueError("Platt scaling needs aligned scores with both classes present.")
    weights = [len(labels) / (2 * positives) if y else len(labels) / (2 * negatives) for y in labels]
    slope, intercept = 1.0, 0.0
    for _ in range(iterations):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for x, y, w in zip(scores, labels, weights):
            p = _sigmoid(slope * x + intercept)
            r, c = w * (p - y), w * p * (1 - p)
            g0, g1 = g0 + r * x, g1 + r
            h00, h01, h11 = h00 + c * x * x, h01 + c * x, h11 + c
        g0 += l2 * slope
        h00 += l2
        h11 += 1e-12
        det = h00 * h11 - h01 * h01
        step0, step1 = (h11 * g0 - h01 * g1) / det, (h00 * g1 - h01 * g0) / det
        slope, intercept = slope - step0, intercept - step1
        if abs(step0) + abs(step1) < 1e-12:
            break
    return slope, intercept


def calibrated_accept(siglip: float, dino: float, siglip_fit: tuple[float, float],
                      dino_fit: tuple[float, float], *, acceptance: float = 0.5,
                      veto: float = 0.2) -> bool:
    """Mirror ContinuityQC's calibrated_mean rule."""
    ps = (_sigmoid(siglip_fit[0] * siglip + siglip_fit[1]), _sigmoid(dino_fit[0] * dino + dino_fit[1]))
    return sum(ps) / 2 >= acceptance and min(ps) >= veto


def cross_validated_calibrated_accuracy(siglip: Sequence[float], dino: Sequence[float],
                                        labels: Sequence[int], *, folds: int = 5, seed: int = 0,
                                        acceptance: float = 0.5, veto: float = 0.2) -> float:
    """Fit both Platt models on k-1 folds and score the held-out fold."""
    order = list(range(len(labels)))
    random.Random(seed).shuffle(order)
    correct = 0
    for fold in range(folds):
        held = set(order[fold::folds])
        train = [i for i in order if i not in held]
        sfit = fit_platt([siglip[i] for i in train], [labels[i] for i in train])
        dfit = fit_platt([dino[i] for i in train], [labels[i] for i in train])
        correct += sum(calibrated_accept(siglip[i], dino[i], sfit, dfit, acceptance=acceptance, veto=veto)
                       == bool(labels[i]) for i in held)
    return correct / len(labels)


def combine(siglip: float, dino: float, rule: str) -> float:
    """Mirror ContinuityQC: accept needs min(siglip, dino) >= threshold; score is the mean."""
    if rule == "min":
        return min(siglip, dino)
    if rule == "mean":
        return (siglip + dino) / 2
    raise ValueError(f"Unknown combination rule {rule!r}.")


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    from agent.deep_agent.continuity_qc import cosine_similarity

    return cosine_similarity(left, right)


def summarise(scores: dict[str, float], pairs: Sequence[dict]) -> dict:
    """Metrics for one scorer given pair_id -> similarity."""
    rows = [(scores[p["id"]], 1 if p["label"] == "consistent" else 0, p["category"]) for p in pairs]
    values, labels = [r[0] for r in rows], [r[1] for r in rows]
    pos = [s for s, y, _ in rows if y]
    neg = [s for s, y, _ in rows if not y]
    threshold, accuracy = best_threshold(values, labels)
    low, high = bootstrap_auroc(pos, neg)
    per_category = {}
    for category in POSITIVE:
        cat = [s for s, _, c in rows if c == category]
        if cat:
            per_category[category] = auroc(cat, neg)
    for category in NEGATIVE:
        cat = [s for s, _, c in rows if c == category]
        if cat:
            per_category[category] = auroc(pos, cat)
    return {
        "auroc": auroc(pos, neg), "auroc_ci95": [low, high],
        "best_threshold": threshold, "best_threshold_accuracy": accuracy,
        "cv5_accuracy": cross_validated_accuracy(values, labels),
        "accuracy_at_0.8": accuracy_at(values, labels, 0.8),
        "per_category_auroc": per_category,
        "accept_rate_at_0.8": {c: statistics.fmean([s >= 0.8 for s, _, k in rows if k == c])
                               for c in POSITIVE + NEGATIVE if any(k == c for *_, k in rows)},
        "mean_score": {c: statistics.fmean([s for s, _, k in rows if k == c])
                       for c in POSITIVE + NEGATIVE if any(k == c for *_, k in rows)},
    }


# ---------------------------------------------------------------- pairs (pure)

@dataclass(frozen=True)
class ShotRef:
    film: str
    index: int
    start: float
    end: float
    scene: str | None
    characters: frozenset[str] = frozenset()

    @property
    def key(self) -> str:
        return f"{self.film}-{self.index:03d}"

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def mid(self) -> float:
        return round((self.start + self.end) / 2, 3)


def label_shots(shots: dict[str, list[list[float]]], scenes: dict[str, list[dict]]) -> list[ShotRef]:
    """Attach hand-labelled scenes (inclusive shot-index ranges) and film-scoped characters."""
    refs = []
    for film, spans in shots.items():
        lookup: dict[int, tuple[str, frozenset[str]]] = {}
        for scene in scenes.get(film, []):
            characters = frozenset(f"{film}:{name}" for name in scene.get("characters", []))
            for first, last in scene["shots"]:
                if first > last:
                    raise ValueError(f"{film} scene {scene['id']} has an inverted range.")
                for index in range(first, last + 1):
                    if index in lookup:
                        raise ValueError(f"{film} shot {index} is in two scenes.")
                    lookup[index] = (f"{film}:{scene['id']}", characters)
        for index, (start, end) in enumerate(spans):
            scene, characters = lookup.get(index, (None, frozenset()))
            refs.append(ShotRef(film, index, float(start), float(end), scene, characters))
    return refs


def _round_robin(groups: dict[str, list], count: int, rng: random.Random) -> list:
    """Draw up to count items cycling across groups so no group dominates."""
    pools = {key: rng.sample(items, len(items)) for key, items in sorted(groups.items()) if items}
    picked = []
    while pools and len(picked) < count:
        for key in list(pools):
            if len(picked) == count:
                break
            picked.append(pools[key].pop())
            if not pools[key]:
                del pools[key]
    return picked


def build_pairs(refs: Sequence[ShotRef], palettes: dict[str, Sequence[float]], *,
                per_category: int = 70, gap: float = 2.5, min_shot: float = 1.0,
                seed: int = 7) -> list[dict]:
    """Deterministic labelled pairs. Labels come only from detected shot boundaries
    (same_shot), the hand-labelled scene/character file (cross-shot, same-character,
    different-scene, hard-negative) and synthetic perturbations of one frame."""
    rng = random.Random(seed)
    usable = [r for r in refs if r.duration >= min_shot and r.scene]
    pairs: list[dict] = []
    counters: dict[str, int] = {}

    def add(category, a, b, label, perturbation=None, a_time=None, b_time=None):
        counters[category] = counters.get(category, 0) + 1
        pairs.append({
            "id": f"{category}-{counters[category] - 1:03d}", "category": category, "label": label,
            "a": [a.film, a.mid if a_time is None else a_time, a.key, a.scene],
            "b": [b.film, b.mid if b_time is None else b_time, b.key, b.scene],
            "perturbation": perturbation,
        })

    by_scene: dict[str, list[ShotRef]] = {}
    for ref in usable:
        by_scene.setdefault(ref.scene, []).append(ref)

    long_by_scene = {k: [r for r in v if r.duration >= gap + 1.0] for k, v in by_scene.items()}
    for ref in _round_robin(long_by_scene, per_category, rng):
        t0 = round(ref.start + 0.5, 3)
        add("same_shot", ref, ref, "consistent", a_time=t0, b_time=round(t0 + gap, 3))

    within = {k: [(a, b) for i, a in enumerate(v) for b in v[i + 1:]] for k, v in by_scene.items()}
    for a, b in _round_robin(within, per_category, rng):
        add("cross_shot_same_scene", a, b, "consistent")

    across = [(a, b) for i, a in enumerate(usable) for b in usable[i + 1:] if a.scene != b.scene]
    shared = {}
    for a, b in across:
        if a.characters & b.characters:
            shared.setdefault(a.film, []).append((a, b))
    for a, b in _round_robin(shared, per_category, rng):
        add("same_character_other_scene", a, b, "consistent")

    disjoint = [(a, b) for a, b in across if not (a.characters & b.characters)]
    film_pairs: dict[str, list] = {}
    for a, b in disjoint:
        film_pairs.setdefault("-".join(sorted((a.film, b.film))), []).append((a, b))
    for a, b in _round_robin(film_pairs, per_category, rng):
        add("different_scene", a, b, "inconsistent")

    used = {tuple(sorted((p["a"][2], p["b"][2]))) for p in pairs}
    ranked = sorted(
        ((palette_similarity(palettes[a.key], palettes[b.key]), a.key, b.key, a, b)
         for a, b in disjoint if a.key in palettes and b.key in palettes),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    uses: dict[str, int] = {}
    for _, _, _, a, b in ranked:
        if counters.get("hard_negative", 0) == per_category:
            break
        if tuple(sorted((a.key, b.key))) in used or uses.get(a.key, 0) >= 2 or uses.get(b.key, 0) >= 2:
            continue
        uses[a.key] = uses.get(a.key, 0) + 1
        uses[b.key] = uses.get(b.key, 0) + 1
        add("hard_negative", a, b, "inconsistent")

    for i, ref in enumerate(_round_robin(by_scene, per_category, rng)):
        add("perturbed", ref, ref, "consistent", PERTURBATIONS[i % len(PERTURBATIONS)])
    return pairs


def palette_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Histogram intersection of normalised colour histograms (1 = identical palette)."""
    return sum(min(a, b) for a, b in zip(left, right, strict=True))


# ---------------------------------------------------------------- images

def palette(image) -> list[float]:
    small = image.convert("HSV").resize((64, 36))
    hist = [0.0] * (8 * 4 * 4)
    data = small.tobytes()
    for offset in range(0, len(data), 3):
        h, s, v = data[offset], data[offset + 1], data[offset + 2]
        hist[(h * 8 // 256) * 16 + (s * 4 // 256) * 4 + (v * 4 // 256)] += 1
    total = sum(hist)
    return [x / total for x in hist]


def perturb(image, kind: str, seed: int = 0):
    from PIL import Image, ImageEnhance, ImageFilter

    rng = random.Random(seed)
    if kind == "grade":
        warm = image.convert("RGB")
        r, g, b = warm.split()
        r = r.point(lambda x: min(255, int(x * 1.12 + 6)))
        b = b.point(lambda x: int(x * 0.88))
        graded = Image.merge("RGB", (r, g, b))
        graded = ImageEnhance.Contrast(graded).enhance(1.15)
        return ImageEnhance.Brightness(graded).enhance(0.92 + rng.random() * 0.04)
    if kind == "crop":
        w, h = image.size
        scale = 0.8
        cw, ch = int(w * scale), int(h * scale)
        left, top = rng.randint(0, w - cw), rng.randint(0, h - ch)
        return image.crop((left, top, left + cw, top + ch)).resize((w, h))
    if kind == "blur":
        return image.filter(ImageFilter.GaussianBlur(radius=2.5))
    if kind == "jpeg":
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=12)
        buffer.seek(0)
        return Image.open(buffer).convert("RGB")
    raise ValueError(f"Unknown perturbation {kind!r}.")


def frame_name(film: str, seconds: float) -> str:
    return f"{film}_{seconds:09.3f}.png"


def extract_frame(footage: Path, film: str, seconds: float, out: Path) -> Path:
    path = out / frame_name(film, seconds)
    if not path.exists():
        subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-ss", f"{seconds:.3f}", "-i",
             str(footage / FILMS[film]["file"]), "-frames:v", "1", "-vf",
             f"scale=-2:{FRAME_HEIGHT}", "-y", str(path)],
            check=True,
        )
    return path


def parallel(function: Callable, items: Iterable, workers: int = 6) -> list:
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(function, items))


# ---------------------------------------------------------------- stages

def stage_detect(args) -> None:
    from scenedetect import SceneManager, open_video
    from scenedetect.detectors import ContentDetector

    for film, meta in FILMS.items():
        target = args.work / f"{film}.shots.json"
        if target.exists():
            continue
        video = open_video(str(args.footage / meta["file"]))
        manager = SceneManager()
        manager.auto_downscale = True
        manager.add_detector(ContentDetector(threshold=27.0, min_scene_len=12))
        manager.detect_scenes(video, show_progress=False)
        shots = [(a.seconds, b.seconds) for a, b in manager.get_scene_list()]
        target.write_text(json.dumps({"film": film, "file": meta["file"], "shots": shots}))
        print(film, len(shots), "shots")


def load_shots(work: Path) -> dict[str, list[list[float]]]:
    return {film: json.loads((work / f"{film}.shots.json").read_text())["shots"] for film in FILMS}


def stage_sheets(args) -> None:
    from PIL import Image, ImageDraw

    frames = args.work / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    sheets = args.work / "sheets"
    sheets.mkdir(exist_ok=True)
    for film, spans in load_shots(args.work).items():
        mids = [round((a + b) / 2, 3) for a, b in spans]
        paths = parallel(lambda t: extract_frame(args.footage, film, t, frames), mids)
        cols, rows, tw, th = 8, 6, 200, 112
        for page in range(math.ceil(len(paths) / (cols * rows))):
            sheet = Image.new("RGB", (cols * tw, rows * (th + 14)), "black")
            draw = ImageDraw.Draw(sheet)
            for slot, index in enumerate(range(page * cols * rows, min(len(paths), (page + 1) * cols * rows))):
                thumb = Image.open(paths[index]).convert("RGB").resize((tw, th))
                x, y = (slot % cols) * tw, (slot // cols) * (th + 14)
                sheet.paste(thumb, (x, y + 14))
                draw.text((x + 2, y), f"{index} @{mids[index]:.0f}s", fill="yellow")
            sheet.save(sheets / f"{film}-{page}.jpg", quality=85)


def stage_pairs(args) -> None:
    from PIL import Image

    scenes = json.loads(args.scenes.read_text())["films"]
    refs = label_shots(load_shots(args.work), scenes)
    frames = args.work / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    labelled = [r for r in refs if r.scene]
    mids = parallel(lambda r: extract_frame(args.footage, r.film, r.mid, frames), labelled)
    palettes = {r.key: palette(Image.open(p).convert("RGB")) for r, p in zip(labelled, mids)}
    pairs = build_pairs(refs, palettes, per_category=args.per_category)
    needed = {(p[k][0], p[k][1]) for p in pairs for k in ("a", "b")}
    parallel(lambda ft: extract_frame(args.footage, ft[0], ft[1], frames), sorted(needed))
    (args.work / "pairs.json").write_text(json.dumps(pairs, indent=1))
    counts = {c: sum(p["category"] == c for p in pairs) for c in POSITIVE + NEGATIVE}
    print(len(pairs), "pairs", counts)


def pair_images(pair: dict, frames: Path):
    from PIL import Image

    a = Image.open(frames / frame_name(pair["a"][0], pair["a"][1])).convert("RGB")
    b = Image.open(frames / frame_name(pair["b"][0], pair["b"][1])).convert("RGB")
    if pair["perturbation"]:
        b = perturb(b, pair["perturbation"], seed=int(pair["id"].rsplit("-", 1)[1]))
    return a, b


def stage_embed(args) -> None:
    import torch

    from agent.deep_agent.continuity_qc import LazyImageEmbedder

    torch.set_num_threads(args.threads)
    pairs = json.loads((args.work / "pairs.json").read_text())
    frames = args.work / "frames"
    for name in args.models.split(","):
        target = args.work / f"scores-{name}.json"
        if target.exists():
            print("skip", name)
            continue
        embedder = LazyImageEmbedder(MODELS[name], allow_dinov3=name == "dinov3")
        cache: dict[str, list[float]] = {}
        timings: list[float] = []
        warm = pair_images(pairs[0], frames)[0]
        embedder.embed(warm)  # load + warm-up, not timed
        scores = {}
        for pair in pairs:
            images = pair_images(pair, frames)
            vectors = []
            for side, image in zip(("a", "b"), images):
                key = f"{pair[side][0]}@{pair[side][1]}" + (f"#{pair['id']}" if side == "b" and pair["perturbation"] else "")
                if key not in cache:
                    start = time.perf_counter()
                    cache[key] = list(embedder.embed(image))
                    timings.append(time.perf_counter() - start)
                vectors.append(cache[key])
            scores[pair["id"]] = cosine(*vectors)
        target.write_text(json.dumps({
            "model": MODELS[name], "scores": scores, "frames_embedded": len(timings),
            "latency_s": {"median": statistics.median(timings), "mean": statistics.fmean(timings),
                          "p90": sorted(timings)[int(0.9 * len(timings)) - 1]},
            "threads": args.threads,
        }))
        print(name, "median s/frame", round(statistics.median(timings), 3))


def stage_report(args) -> None:
    pairs = json.loads((args.work / "pairs.json").read_text())
    runs = {name: json.loads((args.work / f"scores-{name}.json").read_text()) for name in MODELS
            if (args.work / f"scores-{name}.json").exists()}
    results = {"pairs": len(pairs),
               "counts": {c: sum(p["category"] == c for p in pairs) for c in POSITIVE + NEGATIVE},
               "models": {}, "latency": {}}
    for name, run in runs.items():
        results["models"][name] = summarise(run["scores"], pairs)
        results["latency"][name] = run["latency_s"] | {"threads": run["threads"],
                                                       "frames": run["frames_embedded"]}
    for combo, (left, right) in COMBOS.items():
        if left in runs and right in runs:
            for rule in ("min", "mean"):
                scores = {pid: combine(runs[left]["scores"][pid], runs[right]["scores"][pid], rule)
                          for pid in runs[left]["scores"]}
                results["models"][f"{combo} ({rule})"] = summarise(scores, pairs)
    scorers = {name: run["scores"] for name, run in runs.items()}
    for combo, (left, right) in COMBOS.items():
        if left in runs and right in runs:
            for rule in ("min", "mean"):
                scorers[f"{combo} ({rule})"] = {
                    pid: combine(runs[left]["scores"][pid], runs[right]["scores"][pid], rule)
                    for pid in runs[left]["scores"]}
    comparisons = [("dinov3", "dinov2"), ("siglip+dinov3 (min)", "siglip+dinov2 (min)"),
                   ("siglip+dinov3 (mean)", "siglip+dinov2 (mean)"),
                   ("siglip+dinov2 (mean)", "siglip+dinov2 (min)"), ("siglip", "siglip+dinov2 (min)")]
    results["paired_deltas"] = {
        f"{a} vs {b}": paired_bootstrap_delta(scorers[a], scorers[b], pairs)
        for a, b in comparisons if a in scorers and b in scorers
    }
    args.out.write_text(json.dumps(results, indent=2))
    print(markdown(results))


def stage_calibrate(args) -> None:
    """Fit per-model Platt scaling from per-pair cosines and write the calibration file."""
    source = json.loads(args.scores.read_text())
    rows = source["pairs"]
    labels = [1 if r["label"] == "consistent" else 0 for r in rows]
    fits = {source["models"][key]: fit_platt([r[key] for r in rows], labels) for key in source["models"]}
    siglip = source["models"]["siglip"]
    metrics = {}
    for key in ("dinov2", "dinov3"):
        model = source["models"][key]
        new = [calibrated_accept(r["siglip"], r[key], fits[siglip], fits[model]) for r in rows]
        old = [min(r["siglip"], r[key]) >= 0.8 for r in rows]
        metrics[f"siglip+{key}"] = {
            "calibrated_accuracy_in_sample": sum(a == bool(y) for a, y in zip(new, labels)) / len(rows),
            "calibrated_accuracy_cv5": cross_validated_calibrated_accuracy(
                [r["siglip"] for r in rows], [r[key] for r in rows], labels),
            "legacy_min_0.8_accuracy": sum(a == bool(y) for a, y in zip(old, labels)) / len(rows),
            "calibrated_accept_rate": {c: statistics.fmean([a for a, r in zip(new, rows) if r["category"] == c])
                                       for c in POSITIVE + NEGATIVE},
            "legacy_accept_rate": {c: statistics.fmean([a for a, r in zip(old, rows) if r["category"] == c])
                                   for c in POSITIVE + NEGATIVE},
        }
    payload = {
        "method": "platt-logistic-class-balanced",
        "description": ("Per-model Platt scaling p = sigmoid(slope * cosine + intercept), class-balanced, "
                        "fitted on docs/continuity_qc_benchmark_scores.json. A pair is accepted when the mean "
                        "of the SigLIP and DINO probabilities is >= acceptance_threshold and neither "
                        "probability is below veto_threshold (single-model drift guard)."),
        "warning": ("Fitted on 420 labelled pairs of Blender open-movie frames, not Renderhaus generations. "
                    "Recalibrate on labelled Renderhaus Wan/Kling/Seedance outputs before relying on it."),
        "fitted_on": "2026-10-08",
        "source": "docs/continuity_qc_benchmark_scores.json",
        "acceptance_threshold": 0.5,
        "veto_threshold": 0.2,
        "models": {model: {"slope": round(fit[0], 6), "intercept": round(fit[1], 6)} for model, fit in fits.items()},
        "metrics": metrics,
    }
    args.calibration_out.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(metrics, indent=2))


def markdown(results: dict) -> str:
    cats = POSITIVE + NEGATIVE
    head = "| Scorer | AUROC (95% CI) | " + " | ".join(cats) + " | Best-thr acc (thr) | 5-fold CV acc | Acc @0.8 |"
    lines = [head, "|" + "---|" * (len(cats) + 5)]
    for name, m in results["models"].items():
        lo, hi = m["auroc_ci95"]
        lines.append(
            f"| {name} | {m['auroc']:.3f} ({lo:.3f}-{hi:.3f}) | "
            + " | ".join(f"{m['per_category_auroc'].get(c, float('nan')):.3f}" for c in cats)
            + f" | {m['best_threshold_accuracy']:.3f} ({m['best_threshold']:.3f}) | {m['cv5_accuracy']:.3f} | {m['accuracy_at_0.8']:.3f} |"
        )
    if results.get("paired_deltas"):
        lines += ["", "| Paired comparison | AUROC delta | 95% CI | P(left better) |", "|---|---|---|---|"]
        for name, d in results["paired_deltas"].items():
            lines.append(f"| {name} | {d['delta']:+.3f} | {d['ci95'][0]:+.3f} to {d['ci95'][1]:+.3f} | {d['p_left_better']:.2f} |")
    lines += ["", "| Model | Median s/frame | Mean | p90 | Threads | Frames |", "|---|---|---|---|---|---|"]
    for name, lat in results["latency"].items():
        lines.append(f"| {name} | {lat['median']:.3f} | {lat['mean']:.3f} | {lat['p90']:.3f} | {lat['threads']} | {lat['frames']} |")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage", choices=["detect", "sheets", "pairs", "embed", "report", "calibrate"])
    parser.add_argument("--footage", type=Path, default=Path("footage"))
    parser.add_argument("--work", type=Path, default=Path("work"))
    parser.add_argument("--scenes", type=Path, default=ROOT / "docs/continuity_qc_benchmark_scenes.json")
    parser.add_argument("--per-category", type=int, default=70)
    parser.add_argument("--models", default="siglip,dinov2,dinov3")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--out", type=Path, default=ROOT / "docs/continuity_qc_benchmark_results.json")
    parser.add_argument("--scores", type=Path, default=ROOT / "docs/continuity_qc_benchmark_scores.json")
    parser.add_argument("--calibration-out", type=Path,
                        default=ROOT / "agent/deep_agent/continuity_qc_calibration.json")
    args = parser.parse_args(argv)
    if args.stage != "calibrate":
        args.work.mkdir(parents=True, exist_ok=True)
    {"detect": stage_detect, "sheets": stage_sheets, "pairs": stage_pairs,
     "embed": stage_embed, "report": stage_report, "calibrate": stage_calibrate}[args.stage](args)


if __name__ == "__main__":
    main()
