# Continuity memory, evaluation, and repair design

**Status:** Proposed  
**Goal:** Preserve story-world state across shots and reject defects before editorial assembly.

## 1. Research-grounded position

The dominant long-form failure is not merely low per-frame quality. It is loss of identity, props,
backgrounds, narrative facts, and transition logic across independently generated shots. The 2025
ICCV survey identifies character, scene-layout, and motion inconsistency as central long-video
limitations ([Elmoghany et al., 2025](https://openaccess.thecvf.com/content/ICCV2025W/LongVid-Foundation/html/Elmoghany_A_Survey_on_Long-Video_Storytelling_Generation_Architectures_Consistency_and_Cinematic_ICCVW_2025_paper.html)).
EntityBench measures steep consistency degradation as recurrence distance grows and reports its
strongest character fidelity from explicit per-entity memory
([He et al., 2026](https://arxiv.org/abs/2605.15199)). Renderhaus therefore treats continuity as
structured state plus verified visual evidence, not repeated prose in prompts.

## 2. Continuity bible

The bible has four layers:

1. **Invariant identity:** facial structure, body type, age range, signature colors, location
   geometry, prop shape and materials.
2. **Mutable story state:** costume, damage, dirt, weather, time, lighting, possession, position,
   emotional state, and relationships.
3. **Cinematic state:** screen direction, eyeline, camera side of action, palette, lens family,
   contrast, grain, movement grammar.
4. **Negative constraints:** traits or objects that must not appear, policy restrictions, and known
   model failure cues.

CANVAS plans character continuity, background anchors, and location-aware scenes, reporting higher
continuity scores on its evaluated storyboard benchmarks
([Comanici et al., 2026](https://arxiv.org/abs/2604.13452)). VideoMemory stores characters, props,
and backgrounds and updates state after story events
([Zhou et al., 2026](https://arxiv.org/abs/2601.03655)). These results support both persistent
anchors and explicit state transitions.

## 3. Canonical asset creation

Before shot generation:

- Generate or ingest a character sheet containing neutral full body, face close-up, front/profile/
  three-quarter views, costume, and palette chips.
- Generate a location master with wide geography, key landmarks, lighting references, and alternate
  reverse-angle anchors.
- Generate prop sheets with scale, material, distinctive markings, and relevant states.
- Generate a style board that captures composition, texture, lighting, color, and camera language
  without relying only on artist names.
- Human or automated review verifies that all views represent the same entity before canonical
  lock.

Video Storyboarding shows that sharing identity-relevant information across planned shots can
preserve recurring subjects without fine-tuning the underlying video generator
([NVIDIA, 2025](https://research.nvidia.com/labs/par/video_storyboarding/)). DreamFactory’s keyframe
iteration independently supports canonical visual planning before animation
([Xie et al., 2024](https://arxiv.org/abs/2408.11788)).

## 4. Per-shot memory pack

The pack is built deterministically from the shot’s entity schedule and dependencies:

```text
MemoryPack
├── shot specification and required facts
├── current entity states
├── canonical character/location/prop references
├── verified representative frames from relevant earlier shots
├── immediately previous selected end frame
├── intended next start frame when available
├── screen-direction and transition constraints
├── style rules and negative constraints
└── provenance and token/reference budget
```

Retrieval rules:

- Always include current canonical references for required entities.
- Include the most recent verified appearance of each recurring entity.
- Include one semantically similar verified appearance when angle/action differs.
- Include adjacent boundary frames for continuity, but never let them replace canonical identity.
- Prefer diverse, high-quality references; enforce provider reference-count/size limits.
- Never include frames from rejected or technically invalid takes.
- Update memory only after take selection and verification.

StoryMem uses compact dynamically updated keyframe memory and reports benefits from semantic
selection and aesthetic filtering ([Zhang et al., 2025](https://arxiv.org/abs/2512.19539)).
VideoMemory’s retrieve/update cycle and EntityMem’s prebuilt per-entity memory further support these
rules ([VideoMemory](https://arxiv.org/abs/2601.03655),
[EntityBench](https://arxiv.org/abs/2605.15199)). The “verified-only” quarantine is a Renderhaus
engineering inference designed to prevent autoregressive error amplification; ShotStream identifies
error accumulation as a central multi-shot challenge
([Luo et al., 2026](https://arxiv.org/abs/2603.25746)).

## 5. Evaluation ladder

Evaluation is ordered from cheapest and most objective to most semantic.

### Gate A — media integrity

- File exists, checksum matches, container parses.
- Expected video stream exists; codec and dimensions are allowed.
- Duration tolerance, frame-rate, and aspect ratio pass.
- No sustained black/blank/frozen intervals beyond shot intent.
- Audio stream presence agrees with the generation spec.
- No corrupt timestamps or decode errors.

Failure action: redownload when possible; otherwise classify provider attempt as invalid.

### Gate B — intra-shot quality

- Visual stability and flicker.
- Subject and background consistency within the clip.
- Motion smoothness and action completion.
- Anatomy, object integrity, physics, and commonsense.
- Composition and aesthetic quality.

VBench separates subject consistency, background consistency, motion smoothness, flicker, and
spatial relations ([Huang et al., 2024](https://openaccess.thecvf.com/content/CVPR2024/html/Huang_VBench_Comprehensive_Benchmark_Suite_for_Video_Generative_Models_CVPR_2024_paper.html)).
VBench 2.0 expands evaluation toward human fidelity, controllability, physics, and commonsense
([Zheng et al., 2025](https://arxiv.org/abs/2503.21755)). Renderhaus adopts these categories rather
than claiming benchmark-equivalent implementations.

### Gate C — shot specification adherence

- Required entities are present and forbidden entities absent.
- Action, framing, camera motion, location, time, palette, and mood match.
- Required story fact is visually or audibly communicated.
- Dialogue/native audio content matches the approved script where applicable.

Store criterion-level evidence timestamps and representative frames. A generic “looks good” score
cannot diagnose a repair.

### Gate D — entity continuity

For every scheduled entity:

- Presence gate: is the entity actually present and identifiable?
- Identity fidelity: face/body/object/location similarity to canonical references.
- State fidelity: costume, damage, possession, weather, and time match the current state.
- Relation fidelity: expected spatial or ownership relation holds.
- Recurrence check: compare with both the most recent and earlier non-adjacent appearances.

EntityBench explicitly separates intra-shot quality, prompt following, and cross-shot consistency,
and applies a fidelity gate before cross-shot scoring
([He et al., 2026](https://arxiv.org/abs/2605.15199)). Renderhaus follows that structure so a wrong
entity cannot receive a high “consistent” score merely because the wrong appearance repeats.

### Gate E — transition compatibility

Evaluate each selected pair for:

- Action direction and match-on-action.
- Eyeline and camera-axis continuity.
- Subject position, scale, pose, and motion compatibility.
- Lighting/color discontinuity not justified by story.
- Audio ambience and room-tone continuity.
- Cut motivation and transition intent.
- Duplicate or near-duplicate frames that create a stutter.

DirectorBench reports that transition quality is a major between-unit bottleneck even when prompt
fulfillment is materially higher ([Chen et al., 2026](https://arxiv.org/abs/2605.30090)). Camera
Artist also targets shot-to-shot narrative progression and cinematic language
([Camera Artist, 2026](https://arxiv.org/abs/2604.09195)). This supports a distinct pairwise gate.

### Gate F — scene and film

- All planned beats and facts appear in the correct order.
- Character and prop state transitions are causally justified.
- Pacing matches the treatment curve.
- Long-range recurrence remains consistent.
- Narration/dialogue, captions, and visuals are synchronized.
- Music and ambience have intentional continuity.
- Runtime and delivery requirements pass.
- No accumulated repetition or visual drift.

DirectorBench’s five areas—script, visual, audio, cross-modal, and stability—motivate this whole-film
rubric ([Chen et al., 2026](https://arxiv.org/abs/2605.30090)). VRBench shows why long narratives
also need temporally grounded, multi-step reasoning rather than independent frame judgments
([Yu et al., 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Yu_VRBench_A_Benchmark_for_Multi-Step_Reasoning_in_Long_Narrative_Videos_ICCV_2025_paper.html)).

## 6. Rubric and gates

Each criterion returns `{score: 0..1, confidence: 0..1, evidence, defects}`. Default launch policy:

| Dimension | Auto-pass | Human-review band | Hard fail |
|---|---:|---:|---:|
| Technical integrity | all boolean gates | none | any failed gate |
| Prompt/spec adherence | ≥0.82 | 0.68–0.82 | <0.68 |
| Required entity presence | 1.00 | none | any missing required entity |
| Entity fidelity | ≥0.82 | 0.70–0.82 | <0.70 |
| State continuity | ≥0.90 | 0.75–0.90 | critical state contradiction |
| Motion/anatomy/physics | ≥0.78 | 0.65–0.78 | severe visible defect |
| Transition | ≥0.75 | 0.60–0.75 | contradiction or unusable cut |
| Audio intelligibility | ≥0.85 | 0.72–0.85 | unintelligible/clipped |

These thresholds are hypotheses, not paper-derived constants. Calibrate them on human-labeled
Renderhaus films and publish evaluator precision/recall. Research benchmarks show useful categories
and relative effects, but model-specific scores do not transfer automatically.

## 7. Critic implementation

Use an ensemble of deterministic and model-based checks:

- FFprobe/OpenCV/PySceneDetect-style technical analyzers.
- Embedding similarity for canonical entity candidates, guarded by presence verification.
- Face/body/object/location specialists where legally and technically appropriate.
- A VLM with sampled frames plus shot spec for semantic rubrics.
- A second VLM pass only for low-confidence, high-cost, or hero-shot decisions.
- Whole-film analysis on a hierarchical sample: boundary frames, semantic keyframes, scene
  summaries, captions/transcript, and audio descriptors.

Long-video understanding has finite visual-context constraints. Work on visual context sample
scaling reports gains from diverse frame samples followed by scoring rather than one fixed sample
([Suo et al., 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Suo_From_Trial_to_Triumph_Advancing_Long_Video_Understanding_via_Visual_ICCV_2025_paper.html)).
Renderhaus therefore stores the sampling plan and may compare multiple samples for global checks.

## 8. Repair planner

A defect is normalized to:

```json
{
  "code": "CHARACTER_COSTUME_MISMATCH",
  "severity": "major",
  "shot_id": "...",
  "time_range_frames": [24, 96],
  "expected": "navy wool coat, dry",
  "observed": "brown leather jacket",
  "evidence_asset_ids": ["..."],
  "recommended_actions": ["strengthen_character_reference", "rewrite_state_constraint"]
}
```

The repair planner may choose:

1. Reselect an existing candidate.
2. Regenerate with a corrected prompt.
3. Replace/add a stronger canonical reference.
4. Use start/end-frame conditioning.
5. Shorten or split the shot.
6. Route to a provider with required control capabilities.
7. Use a still with controlled camera motion.
8. Insert B-roll or a motivated cutaway.
9. Fix only in editorial: trim, crop, color, transition, audio, or caption.
10. Escalate to human review.

Generation is not the default response to an editorial defect. Every action predicts incremental
cost, impacted dependencies, and expected criterion improvement.

## 9. Bounded policy

- Maximum three generation attempts per shot by default.
- Maximum two critic-proposed repairs.
- Maximum one provider switch without human approval.
- Stop immediately on budget exhaustion or a policy/content rejection.
- Never repeat an identical spec after a semantic failure.
- Hero shots may spend more; inserts fall back earlier.
- Low-confidence disagreement escalates instead of looping.
- A rejected take is immutable and excluded from memory.

## 10. Calibration and benchmark suite

Create an internal benchmark with at least 30 episodes and three difficulty tiers:

- 6–8 shots, one character, one location.
- 12–18 shots, one character, two locations, recurring prop.
- 20–30 shots, two characters, state changes, non-adjacent recurrence.

For every episode, define an entity schedule, state transitions, shot requirements, transition
intents, and human labels. This adapts EntityBench’s scheduled entities and recurrence gaps
([He et al., 2026](https://arxiv.org/abs/2605.15199)), VBench’s factorized quality dimensions
([Huang et al., 2024](https://openaccess.thecvf.com/content/CVPR2024/html/Huang_VBench_Comprehensive_Benchmark_Suite_for_Video_Generative_Models_CVPR_2024_paper.html)),
and DirectorBench’s checkpoint-level diagnosis
([Chen et al., 2026](https://arxiv.org/abs/2605.30090)).

Measure evaluator precision/recall by defect type, human agreement, first-pass yield, repair win
rate, cost per accepted minute, and false-accept rate. Release thresholds prioritize low false
acceptance for critical continuity and technical defects.
