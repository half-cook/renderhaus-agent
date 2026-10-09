# Continuity-QC embedder benchmark: DINOv3 vs DINOv2 (and SigLIP)

Run 2026-10-08 on the Renderhaus box (CPU only). Script: `scripts/continuity_qc_benchmark.py`.
Raw numbers: `docs/continuity_qc_benchmark_results.json`. Scene labels:
`docs/continuity_qc_benchmark_scenes.json`.

## Recommendation

**Do not flip the default to DINOv3 now.** Keep `continuity_qc.dinov3_enabled=false`.

- DINOv3 ViT-B/16 is not measurably better than DINOv2-base on this set. Its AUROC is
  0.898 vs 0.890, and the paired bootstrap delta is +0.009 (95% CI -0.014 to +0.032).
  Inside the production SigLIP+DINO rule the gain is the same +0.009 (CI crosses zero).
  It is slightly faster on CPU (0.087 vs 0.104 s/frame).
- A small gain inside the noise doesn't justify taking on the DINOv3 Licence, its conditions
  and a legal review.
- **The bigger finding is the combination rule and threshold, not the DINO model.**
  - `ContinuityQC` accepts when `min(siglip, dino) >= 0.8`. DINO cosines run far lower
    than SigLIP's, so `min` is in practice always the DINO score: "SigLIP+DINOv2 (min)" has
    exactly DINOv2's AUROC, and SigLIP's signal is thrown away.
  - SigLIP alone scores AUROC 0.932, +0.042 over the production rule (CI +0.021 to +0.064).
  - The raw cosine mean (the old `ShotPairScore.score`) scores 0.922, +0.032 (CI +0.022 to +0.044).
  - At the shared 0.8 threshold the production rule accepts only 43% of same-shot pairs and
    3% of same-scene cross-shot pairs. It never false-accepts here, but it rejects almost
    every real continuity match.
- **Follow-up:** calibrated scoring has since replaced the old rule; see
  [Calibrated scoring](#calibrated-scoring) below. Original suggestion:
  - per-model calibrated thresholds, or a mean of per-model z-scored similarities, fit on
    Renderhaus Wan outputs;
  - reassess DINOv3 once that is in place, with legal sign-off.

## Results

All AUROCs score consistent pairs as positives. For a positive category, the per-category
AUROC is that category vs all negatives. For a negative category, it is all positives vs
that category. "Best-thr acc" picks the threshold on the same data, so it is optimistic.
"5-fold CV acc" picks the threshold on held-out folds. "Acc @0.8" is the repo's default
threshold. The CI is a 1000-round stratified bootstrap.

| Scorer | AUROC (95% CI) | same_shot | cross_shot_same_scene | same_character_other_scene | perturbed | different_scene | hard_negative | Best-thr acc (thr) | 5-fold CV acc | Acc @0.8 |
|---|---|---|---|---|---|---|---|---|---|---|
| siglip | 0.932 (0.909-0.952) | 0.999 | 0.899 | 0.833 | 0.995 | 0.938 | 0.925 | 0.869 (0.646) | 0.864 | 0.707 |
| dinov2 | 0.890 (0.856-0.918) | 1.000 | 0.821 | 0.739 | 0.998 | 0.916 | 0.863 | 0.814 (0.181) | 0.800 | 0.524 |
| dinov3 | 0.898 (0.868-0.925) | 1.000 | 0.846 | 0.747 | 1.000 | 0.921 | 0.875 | 0.824 (0.310) | 0.817 | 0.593 |
| siglip+dinov2 (min) | 0.890 (0.856-0.918) | 1.000 | 0.821 | 0.739 | 0.998 | 0.916 | 0.863 | 0.814 (0.181) | 0.800 | 0.519 |
| siglip+dinov2 (mean) | 0.922 (0.894-0.944) | 1.000 | 0.878 | 0.810 | 1.000 | 0.940 | 0.904 | 0.852 (0.395) | 0.845 | 0.581 |
| siglip+dinov3 (min) | 0.898 (0.868-0.925) | 1.000 | 0.846 | 0.747 | 1.000 | 0.921 | 0.875 | 0.824 (0.310) | 0.817 | 0.583 |
| siglip+dinov3 (mean) | 0.924 (0.899-0.946) | 1.000 | 0.884 | 0.810 | 1.000 | 0.942 | 0.905 | 0.857 (0.472) | 0.852 | 0.629 |

| Paired comparison | AUROC delta | 95% CI | P(left better) |
|---|---|---|---|
| dinov3 vs dinov2 | +0.009 | -0.014 to +0.032 | 0.78 |
| siglip+dinov3 (min) vs siglip+dinov2 (min) | +0.009 | -0.014 to +0.032 | 0.78 |
| siglip+dinov3 (mean) vs siglip+dinov2 (mean) | +0.002 | -0.011 to +0.015 | 0.60 |
| siglip+dinov2 (mean) vs siglip+dinov2 (min) | +0.032 | +0.022 to +0.044 | 1.00 |
| siglip vs siglip+dinov2 (min) | +0.042 | +0.021 to +0.064 | 1.00 |

| Model | Median s/frame | Mean | p90 | Threads | Frames |
|---|---|---|---|---|---|
| siglip | 1.540 | 1.555 | 1.622 | 4 | 506 |
| dinov2 | 0.104 | 0.105 | 0.116 | 4 | 506 |
| dinov3 | 0.087 | 0.089 | 0.097 | 4 | 506 |

The paired comparisons resample the same pairs for both scorers. P(left better) is the share
of resamples where the left scorer has the higher AUROC.

### Acceptance rate at the production threshold 0.8

| Scorer | same_shot | cross_shot_same_scene | same_character_other_scene | perturbed | different_scene | hard_negative |
|---|---|---|---|---|---|---|
| siglip | 0.90 | 0.30 | 0.11 | 0.93 | 0.00 | 0.00 |
| dinov2 | 0.43 | 0.03 | 0.00 | 0.69 | 0.00 | 0.00 |
| dinov3 | 0.59 | 0.04 | 0.00 | 0.93 | 0.00 | 0.00 |
| siglip+dinov2 (min) | 0.43 | 0.03 | 0.00 | 0.66 | 0.00 | 0.00 |
| siglip+dinov3 (min) | 0.57 | 0.04 | 0.00 | 0.89 | 0.00 | 0.00 |

### Mean cosine similarity per category

| Scorer | same_shot | cross_shot_same_scene | same_character_other_scene | perturbed | different_scene | hard_negative |
|---|---|---|---|---|---|---|
| siglip | 0.914 | 0.737 | 0.694 | 0.910 | 0.552 | 0.575 |
| dinov2 | 0.738 | 0.326 | 0.244 | 0.832 | 0.108 | 0.159 |
| dinov3 | 0.816 | 0.420 | 0.307 | 0.905 | 0.153 | 0.212 |

DINOv3's cosines sit higher than DINOv2's, but both are far below SigLIP's. A single shared
threshold cannot suit both slots.

### Latency

- Hardware: 8-vCPU Intel Xeon box, no GPU, `torch.set_num_threads(4)`.
- Each figure is one frame per call, warm-up excluded, and includes preprocessing.
- Three unrelated Codex runs were using the CPU at the same time (load average around 4),
  so treat absolute numbers as indicative. The relative ordering is reliable:
  - SigLIP so400m/384 is about 15-18x slower than either DINO ViT-B.
  - DINOv3 ViT-B/16 is about 15% faster than DINOv2-base, which processes more tokens at
    its default crop.

## Calibrated scoring

`ContinuityQC` now uses the `calibrated_mean` rule by default, still with SigLIP+DINOv2
(DINOv3 stays off).

- **Method:** per-model Platt scaling with class balancing: `p = sigmoid(slope * cosine + intercept)`.
  It is fitted by Newton's method, with each class carrying half the weight, so p = 0.5 is the
  equal-error boundary.
- **Accept rule:** mean(p_siglip, p_dino) >= 0.5, and neither p falls below 0.2. The veto keeps
  gross drift in one model from being averaged away.
- **Files:**
  - Calibration: `agent/deep_agent/continuity_qc_calibration.json`.
  - Input: the per-pair cosines in `docs/continuity_qc_benchmark_scores.json`.
  - Refit: `python scripts/continuity_qc_benchmark.py calibrate`.
  - Tests: `tests/test_continuity_qc_calibration.py` checks that the committed fit reproduces
    from the committed scores.
- **Fitted parameters (2026-10-08):**
  - SigLIP: slope 19.566, intercept -13.205. p = 0.5 at cosine 0.675.
  - DINOv2: slope 10.443, intercept -2.706. p = 0.5 at cosine 0.259.
  - DINOv3: slope 9.757, intercept -3.215. p = 0.5 at cosine 0.330.

| Rule on the 420 benchmark pairs | Accuracy | 5-fold CV | same shot | perturbed | same scene, other shot | same character, other scene | different scene (false accept) | hard negative (false accept) |
|---|---|---|---|---|---|---|---|---|
| Old: min(SigLIP, DINOv2) >= 0.8 | 0.519 | n/a | 0.43 | 0.66 | 0.03 | 0.00 | 0.00 | 0.00 |
| New: calibrated mean, SigLIP+DINOv2 | **0.845** | **0.845** | 1.00 | 1.00 | 0.67 | 0.53 | 0.06 | 0.07 |
| Old rule with DINOv3 | 0.583 | n/a | 0.57 | 0.89 | 0.04 | 0.00 | 0.00 | 0.00 |
| New: calibrated mean, SigLIP+DINOv3 | 0.843 | 0.845 | 1.00 | 1.00 | 0.69 | 0.54 | 0.07 | 0.10 |

Category columns are acceptance rates. The calibrated rule trades a 6-7% false-accept rate on
clear negatives for accepting every same-shot and perturbed pair, against the old rule's 43%
and 66%. DINOv3 still gives no measurable gain once calibrated, so keeping it off remains the
recommendation.

**The thresholds must be recalibrated on real Renderhaus generations before they are relied
on.** This calibration comes from Blender open-movie frames, not Wan, Kling or Seedance outputs.
Generated footage has different noise, motion and identity drift, so both the cosine
distributions and the right boundary will shift.

To recalibrate:
1. Label a few hundred adjacent-shot pairs from real projects as consistent or inconsistent.
2. Embed them with the production models.
3. Write the cosines in the same format as `docs/continuity_qc_benchmark_scores.json`.
4. Run `calibrate --scores <file>`.
5. Review the per-category acceptance rates before committing.

`rule="legacy_min"` stays available for comparison only.

## Dataset

Four Blender Foundation open movies, all Creative Commons Attribution:

| Film | File | Source URL | Licence |
|---|---|---|---|
| Sintel (2010) | `Sintel.2010.720p.mkv` | https://download.blender.org/durian/movies/Sintel.2010.720p.mkv.zip | CC BY 3.0 (c) copyright Blender Foundation | durian.blender.org ([licence](https://creativecommons.org/licenses/by/3.0/)) |
| Big Buck Bunny (2008) | `BigBuckBunny_640x360.m4v` | https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_640x360.m4v.zip | CC BY 3.0 (c) copyright 2008, Blender Foundation | www.bigbuckbunny.org ([licence](https://creativecommons.org/licenses/by/3.0/)) |
| Elephants Dream (2006) | `elephantsdream-480-h264-st-aac.mov` | https://download.blender.org/ED/elephantsdream-480-h264-st-aac.mov | CC BY 2.5 (c) copyright 2006, Blender Foundation / Netherlands Media Art Institute | www.elephantsdream.org ([licence](https://creativecommons.org/licenses/by/2.5/)) |
| Tears of Steel (2012) | `tears_of_steel_720p.mov` | https://download.blender.org/demo/movies/ToS/tears_of_steel_720p.mov | CC BY 3.0 (c) copyright Blender Foundation | mango.blender.org ([licence](https://creativecommons.org/licenses/by/3.0/)) |

Attribution: frames © Blender Foundation (and the Netherlands Media Art Institute for
Elephants Dream), used under the licences above. Frames and footage are **not** committed.
The script re-downloads nothing; fetch the files from the URLs above.

### Building the pairs

1. **Shot boundaries:**
   - Settings: PySceneDetect 0.7.1, `ContentDetector(threshold=27, min_scene_len=12)`,
     auto-downscale.
   - Shots detected: Sintel 228, Big Buck Bunny 138, Elephants Dream 135, Tears of Steel 159.
2. **Scenes and characters:**
   - One annotator (the agent) hand-labelled them from contact sheets of mid-shot frames.
   - A scene is a continuous location and lighting set-up, and may recur (Sintel's snow
     opening and the shaman's hut both come back later).
   - Titles, credits, montages and mixed hologram or VR shots are excluded.
3. **Pairs:** 420 pairs, 70 per category, deterministic with seed 7.
   - `same_shot` (positive): two frames 2.5 s apart inside one detected shot of at least 3.5 s.
   - `cross_shot_same_scene` (positive): mid-frames of two different shots in the same
     labelled scene.
   - `same_character_other_scene` (positive): two different scenes that share a principal
     character, e.g. Sintel in the snow vs Sintel in the town. Whole-frame embedders are
     not identity models, so this is the hardest positive.
   - `perturbed` (positive): a frame vs the same frame after one of these, rotating:
     - warm grade with contrast and brightness shift;
     - 80% random crop, resized back;
     - Gaussian blur, radius 2.5;
     - JPEG at quality 12.
   - `different_scene` (negative): different scenes with no shared character, balanced
     across film pairs (17 of 70 within one film).
   - `hard_negative` (negative): different scene, no shared character, chosen by highest
     HSV colour-histogram intersection (palette match), with each shot used at most twice.

### Limitations

- These are frames from animated and live-action films, not Renderhaus generations. Wan,
  Kling and Seedance outputs may behave differently, so recalibrate on real project data.
- Most hard negatives (62 of 70) pair different films. Palettes match, but art styles differ,
  so this set is easier than same-style character confusion within one film. No film
  offered many within-film scenes with a disjoint cast.
- Labels come from one annotator viewing thumbnails. Scene boundaries inside Big Buck Bunny's
  single meadow world are judgement calls.
- 420 pairs give bootstrap CIs of roughly ±0.03 AUROC per model. Differences smaller than
  that are not resolved.

## Reproduce

Software: transformers 5.19.0, torch 2.14.1 (run on CPU), Pillow; metrics are implemented in the script (no scikit-learn).
DINOv3 needs transformers 4.56 or newer.

Weights are pinned to these Hugging Face cache snapshots:
- DINOv3: `facebook/dinov3-vitb16-pretrain-lvd1689m` @ 5931719e67bb
- DINOv2: `facebook/dinov2-base` @ f9e44c814b77
- SigLIP: `google/siglip-so400m-patch14-384` @ 9fdffc58afc9

```
# separate venv: torch (CPU), transformers>=4.56, pillow, scenedetect, opencv-python-headless
python scripts/continuity_qc_benchmark.py detect --footage FOOTAGE --work WORK
python scripts/continuity_qc_benchmark.py sheets --footage FOOTAGE --work WORK   # for labelling
python scripts/continuity_qc_benchmark.py pairs  --footage FOOTAGE --work WORK
python scripts/continuity_qc_benchmark.py embed  --work WORK --threads 4
python scripts/continuity_qc_benchmark.py report --work WORK
```

`embed` uses the production `LazyImageEmbedder` with `local_files_only=True`. The gated
DINOv3 repo needs a one-time cache download with an approved account. After that, `HF_TOKEN`
is read from the environment only; it is never printed, stored or committed.

Unit tests (`tests/test_continuity_qc_benchmark.py`, `tests/test_continuity_qc.py`) use fakes
and synthetic shots only, with no downloads.

The benchmark exposed a production bug, fixed on this branch: on transformers 5,
`SiglipModel.get_image_features` returns a `BaseModelOutputWithPooling` instead of a tensor,
which crashed `LazyImageEmbedder` for SigLIP. It now uses `pooler_output`.

## DINOv3 licence note (legal review required before shipping)

DINOv3 weights ship under the **DINOv3 Licence** (last updated Aug 19, 2025), not Apache-2.0.
It allows commercial use, with conditions:

- If you redistribute the weights or derivatives, you must do so under the same licence and
  include a copy of it.
- Publications that use DINOv3 must acknowledge it.
- You must comply with trade controls: you may not be a sanctioned party, and no ITAR,
  military, warfare, nuclear, espionage or weapons uses are allowed.
- No reverse engineering.
- The licence terminates if you sue Meta claiming DINOv3 infringes your IP. You must also
  indemnify Meta against third-party claims.
- Meta can terminate the licence on breach.
- Meta can change the terms at any time, effective immediately on continued use.
- California law governs.

The weights are also gated on Hugging Face. **Get a legal review before enabling DINOv3 in
production or redistributing it.** This branch only adds an opt-in code path that is OFF by
default.
