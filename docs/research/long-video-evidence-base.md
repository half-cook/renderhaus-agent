# Research evidence base for agentic long-video generation

**Cutoff:** 2026-07-12  
**Policy:** Prefer peer-reviewed papers, primary preprints/project pages, and official provider or
infrastructure documentation. Do not treat marketing claims or benchmark results on a different
stack as guaranteed Renderhaus outcomes.

## 1. Evidence classification

- **Demonstrated:** The cited work reports an experiment or benchmark supporting the claim.
- **Capability:** Official documentation states that an API or system exposes the feature.
- **Inference:** Renderhaus engineering conclusion derived from one or more demonstrated findings;
  it still needs internal validation.
- **Hypothesis:** A measurable proposal with insufficient external evidence; track explicitly.

## 2. Evidence matrix

| ID | Design claim | Evidence and result | Class | Renderhaus consequence |
|---|---|---|---|---|
| E01 | Long-form production should be decomposed into shots rather than one large generation. | The ICCV survey of 32 methods reports that current systems predominantly produce 5–16 second clips and that longer sequences struggle with appearance, layout, motion, redundancy, and temporal diversity ([Elmoghany et al., 2025](https://openaccess.thecvf.com/content/ICCV2025W/LongVid-Foundation/html/Elmoghany_A_Survey_on_Long-Video_Storytelling_Generation_Architectures_Consistency_and_Cinematic_ICCVW_2025_paper.html)). | Demonstrated | Model a film as scenes and short shots; assemble deterministically. |
| E02 | Commercial provider limits reinforce the shot-based architecture. | Official Seedance 2.0 materials state 4–15 second duration and multimodal references ([BytePlus Seedance](https://ai.byteplus.com/en/product/seedance)); Veo 3.1 supports repeated seven-second extension of Veo-generated clips up to its documented limit ([Google Veo](https://ai.google.dev/gemini-api/docs/veo)). | Capability | Do not encode runtime assumptions in the planner; use provider capabilities and shot routing. |
| E03 | Hierarchical planning improves automation and narrative control. | MovieAgent uses director, scene, and shot planning and reports state-of-the-art results in its tested script faithfulness, character consistency, and narrative coherence metrics ([Wu et al., 2025](https://arxiv.org/abs/2503.07314)). | Demonstrated | Use typed brief, treatment, scene, and shot artifacts. |
| E04 | Specialized roles with iterative review can outperform a single stronger planner. | FilmAgent reports higher human-evaluation scores than its tested baselines and notes that its coordinated GPT-4o agents surpassed a single-agent o1 baseline ([Xu et al., 2025](https://arxiv.org/abs/2501.12909)). | Demonstrated | Use bounded specialist nodes and explicit critique/revision, while avoiding a free-form swarm. |
| E05 | Orchestration and media utilities should be separate. | AesopAgent separates an evolutionary orchestration layer from a utility layer for images, audio, effects, and video assembly ([Wang et al., 2024](https://arxiv.org/abs/2403.07952)). | Demonstrated + inference | Keep agent proposals, workflow execution, provider adapters, and media tools as distinct layers. |
| E06 | Canonical keyframes/storyboards improve recurring-subject consistency. | NVIDIA Video Storyboarding reports a training-free method for recurring-subject identity across shots while retaining motion responsiveness ([NVIDIA, 2025](https://research.nvidia.com/labs/par/video_storyboarding/)); DreamFactory uses iterative keyframes to promote cross-scene style and consistency ([Xie et al., 2024](https://arxiv.org/abs/2408.11788)). | Demonstrated | Require canonical sheets and start frames before paid shot generation; add end frames for transitions/hero shots. |
| E07 | Continuity needs explicit character, background, and location planning. | CANVAS reports higher continuity across character, persistent-background, and location-aware storyboard criteria on its evaluated benchmarks ([Comanici et al., 2026](https://arxiv.org/abs/2604.13452)). | Demonstrated | Store persistent anchors and location-aware scene state in the continuity bible. |
| E08 | Compact, selected visual memory improves cross-shot consistency. | StoryMem reports improved cross-shot consistency using a dynamic bank of semantically selected and aesthetically filtered keyframes ([Zhang et al., 2025](https://arxiv.org/abs/2512.19539)). | Demonstrated | Retrieve a bounded per-shot memory pack; select representative frames instead of retaining all history. |
| E09 | Memory must represent mutable story state, not identity alone. | VideoMemory stores semantic and visual descriptors for characters, props, and backgrounds and updates them after story-driven changes while preserving identity ([Zhou et al., 2026](https://arxiv.org/abs/2601.03655)). | Demonstrated | Split invariant identity from versioned mutable entity state. |
| E10 | Long recurrence gaps are a specific failure mode. | EntityBench contains episodes up to 50 shots and reports sharp consistency degradation with recurrence distance; explicit per-entity memory yields its highest character fidelity and presence ([He et al., 2026](https://arxiv.org/abs/2605.15199)). | Demonstrated | Retrieve both recent and non-adjacent verified appearances; test recurrence by gap. |
| E11 | Rejected takes should not update canonical memory. | ShotStream identifies autoregressive error accumulation and uses distinct global/local context caches plus training strategies to mitigate it ([Luo et al., 2026](https://arxiv.org/abs/2603.25746)). No cited paper directly tests Renderhaus’s quarantine rule. | Inference | Only selected, verified frames may enter memory; benchmark against permissive updating. |
| E12 | Evaluation must be factorized. | VBench evaluates 16 separable dimensions including subject/background consistency, motion, flicker, and spatial relations ([Huang et al., 2024](https://openaccess.thecvf.com/content/CVPR2024/html/Huang_VBench_Comprehensive_Benchmark_Suite_for_Video_Generative_Models_CVPR_2024_paper.html)). | Demonstrated | Store dimension scores and hard gates; never use a single opaque quality score. |
| E13 | Visual plausibility is not enough. | VBench 2.0 adds human fidelity, controllability, physics, creativity, and commonsense to superficial visual metrics ([Zheng et al., 2025](https://arxiv.org/abs/2503.21755)). | Demonstrated | Add anatomy, object integrity, physics, and commonsense defects to the critic. |
| E14 | Transition quality must be evaluated separately. | DirectorBench reports a between-unit bottleneck, with transition quality substantially below prompt-level fulfillment in its evaluated workflows ([Chen et al., 2026](https://arxiv.org/abs/2605.30090)). | Demonstrated | Evaluate adjacent selected takes after local shot acceptance and again after trims. |
| E15 | Whole-film evaluation needs script, visual, audio, cross-modal, and stability checks. | DirectorBench defines checkpoint criteria across those five dimensions and argues aggregate scores hide workflow failures ([Chen et al., 2026](https://arxiv.org/abs/2605.30090)). | Demonstrated | Add scene/film gates after assembly and retain criterion-level defects. |
| E16 | Long narrative evaluation requires temporally grounded reasoning. | VRBench evaluates multi-step reasoning over long narrative videos and exposes the need for temporally localized reasoning chains ([Yu et al., 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Yu_VRBench_A_Benchmark_for_Multi-Step_Reasoning_in_Long_Narrative_Videos_ICCV_2025_paper.html)). | Demonstrated | Whole-film QC should use shot/scene summaries and temporal evidence, not independent frame votes. |
| E17 | Multiple keyframe samples can improve long-video understanding robustness. | Visual Context Sample Scaling reports improvements by generating predictions from varied frame subsets and scoring them ([Suo et al., 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Suo_From_Trial_to_Triumph_Advancing_Long_Video_Understanding_via_Visual_ICCV_2025_paper.html)). | Demonstrated | Record and diversify samples for low-confidence whole-film evaluation. |
| E18 | Audio should distinguish synchronized on-screen sound from off-screen ambience/music. | ReelWave explicitly models time-varying on-screen audio controls and agent-planned off-screen sound across multi-scene video ([Wang et al., 2025](https://arxiv.org/abs/2503.07217)). | Demonstrated | Separate dialogue/narration, on-screen SFX, ambience, and music tracks and rubrics. |
| E19 | Media assembly should be deterministic. | FFmpeg officially provides concat filters/demuxing for joining inputs ([FFmpeg FAQ](https://ffmpeg.org/faq.html)). | Capability + inference | LLMs propose editorial choices; pinned FFmpeg/FFprobe code executes and verifies them. |
| E20 | A long-running paid workflow needs durable execution. | Temporal states that workflows resume after crashes/network/infrastructure failure ([Temporal docs](https://docs.temporal.io/)); Google demonstrates a durable agent where LLM/tool steps are persisted to avoid lost state or incorrect repetition ([Google](https://ai.google.dev/gemini-api/docs/temporal-example)). | Capability | Use workflows/activities, signals, durable timers, replay tests, and idempotency. |
| E21 | The manifest should use movie/scene/shot hierarchy. | MovieBench is explicitly hierarchical at movie level and MovieAgent reasons at scene/shot levels ([MovieBench](https://openaccess.thecvf.com/content/CVPR2025/html/Wu_MovieBench_A_Hierarchical_Movie_Level_Dataset_for_Long_Video_Generation_CVPR_2025_paper.html), [MovieAgent](https://arxiv.org/abs/2503.07314)). | Demonstrated + inference | Make the hierarchy a versioned domain model and validate exact duration sums. |
| E22 | Provider-neutral reference roles are necessary. | Official BytePlus APIs accept text, image, audio, video, and sample-task references; Veo exposes image ingredients, frames, and extension controls ([BytePlus](https://docs.byteplus.com/en/docs/ModelArk/1520757), [Veo](https://ai.google.dev/gemini-api/docs/veo)). | Capability | Define neutral reference roles and translate them in adapters. |
| E23 | Shot-wise repair is more cost-effective than whole-film regeneration. | Memory-based systems synthesize iteratively per shot and long-form benchmarks evaluate shot units ([StoryMem](https://arxiv.org/abs/2512.19539), [EntityBench](https://arxiv.org/abs/2605.15199)). They do not directly measure Renderhaus cost savings. | Inference | Track dependency cones and compare cost/time of localized versus full reruns. |
| E24 | Explicit cinematic language should be planned and evaluated. | Camera Artist targets shot-level narrative progression and deliberate cinematic language across adjacent clips ([Camera Artist, 2026](https://arxiv.org/abs/2604.09195)). | Demonstrated | Store purpose, framing, camera, lens, screen direction, and transition intent per shot. |
| E25 | Visual and semantic alignment both matter for long narratives. | VideoAuteur introduces a Long Narrative Video Director and reports improved visual detail and semantic alignment from text/image embedding integration ([Xiao et al., 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Xiao_VideoAuteur_Towards_Long_Narrative_Video_Generation_ICCV_2025_paper.html)). | Demonstrated | Evaluate both required narrative facts and visual/cinematic criteria. |

## 3. What the evidence does not prove

The reviewed work does **not** prove that:

- Any current provider will produce identity-perfect three-minute films from arbitrary prompts.
- More agents always improve output. FilmAgent’s result is specific to its roles, environment,
  models, baselines, and evaluation ([Xu et al., 2025](https://arxiv.org/abs/2501.12909)).
- A paper’s critic score transfers to Seedance or Renderhaus’s genres.
- Reference memory eliminates long-range drift; EntityBench shows it improves but does not solve the
  problem ([He et al., 2026](https://arxiv.org/abs/2605.15199)).
- Automated VLM evaluation can replace human creative approval. DirectorBench is diagnostic and
  profile-aware, reinforcing rather than removing user preference
  ([Chen et al., 2026](https://arxiv.org/abs/2605.30090)).
- Provider extension is a substitute for editorial cuts. Veo’s official extension is useful for
  continuous action but has model and input restrictions
  ([Google Veo](https://ai.google.dev/gemini-api/docs/veo)).

## 4. Renderhaus hypotheses to test

| Hypothesis | Experiment | Success criterion |
|---|---|---|
| H01 Verified-only memory reduces drift versus latest-take memory. | Generate matched 12-shot episodes with rejected takes either quarantined or admitted. | ≥15% relative reduction in critical continuity defects. |
| H02 Start + end keyframes improve pairwise transitions over start-only conditioning. | A/B 50 transition pairs stratified by motion and shot size. | Higher human preference with no material local-quality loss. |
| H03 Two candidates are cost-effective only for hero shots. | Compare one vs two candidates by shot risk class. | Candidate two selection rate and quality gain justify incremental spend in hero class only. |
| H04 Hierarchical planner outperforms one-pass shot-list generation. | Blind review of matched briefs; check duration, coverage, continuity constraints, and edit count. | ≥20% fewer material plan edits. |
| H05 Pairwise transition QC catches defects local QC misses. | Human-label selected shot sequences. | Recall ≥0.80 for major transition defects with acceptable review volume. |
| H06 Targeted repair beats full rerender. | Record actual cost, time, and quality for dependency-cone repair. | ≥60% lower incremental generation cost for localized defects. |
| H07 Early narration timing improves pacing. | Compare narration-first timing with post-hoc narration. | Higher pacing and intelligibility preference in blind review. |

## 5. Source notes and limitations

### Peer review status

CVPR/ICCV open-access proceedings are peer-reviewed conference papers. Several 2026 sources—CANVAS,
VideoMemory, StoryMem, EntityBench, DirectorBench, Camera Artist, and ShotStream—are recent preprints
or review submissions at this cutoff. Their results should be treated as promising but provisional.

### Benchmark transfer

Benchmarks use different prompts, models, durations, evaluators, and human protocols. Renderhaus
borrows taxonomies and experimental patterns, not published numeric thresholds. All production
thresholds require calibration against internal human labels.

### Agent claims

Multi-agent papers show that purposeful role decomposition can help their tasks. Renderhaus infers
that the safest implementation is a deterministic graph of bounded specialist calls. This exact
workflow-agent boundary is justified primarily by durability, budget, and audit requirements, not
by a direct head-to-head video paper.

## 6. Primary bibliography

1. [Elmoghany et al., “A Survey on Long-Video Storytelling Generation,” ICCV Workshops 2025](https://openaccess.thecvf.com/content/ICCV2025W/LongVid-Foundation/html/Elmoghany_A_Survey_on_Long-Video_Storytelling_Generation_Architectures_Consistency_and_Cinematic_ICCVW_2025_paper.html)
2. [Wu et al., “Automated Movie Generation via Multi-Agent CoT Planning,” 2025](https://arxiv.org/abs/2503.07314)
3. [Xu et al., “FilmAgent,” 2025](https://arxiv.org/abs/2501.12909)
4. [Wang et al., “AesopAgent,” 2024](https://arxiv.org/abs/2403.07952)
5. [Xie et al., “DreamFactory,” 2024](https://arxiv.org/abs/2408.11788)
6. [NVIDIA, “Video Storyboarding,” 2025](https://research.nvidia.com/labs/par/video_storyboarding/)
7. [Comanici et al., “CANVAS,” 2026](https://arxiv.org/abs/2604.13452)
8. [Zhou et al., “VideoMemory,” 2026](https://arxiv.org/abs/2601.03655)
9. [Zhang et al., “StoryMem,” 2025](https://arxiv.org/abs/2512.19539)
10. [He et al., “EntityBench,” 2026](https://arxiv.org/abs/2605.15199)
11. [Luo et al., “ShotStream,” 2026](https://arxiv.org/abs/2603.25746)
12. [Huang et al., “VBench,” CVPR 2024](https://openaccess.thecvf.com/content/CVPR2024/html/Huang_VBench_Comprehensive_Benchmark_Suite_for_Video_Generative_Models_CVPR_2024_paper.html)
13. [Zheng et al., “VBench 2.0,” 2025](https://arxiv.org/abs/2503.21755)
14. [Chen et al., “DirectorBench,” 2026](https://arxiv.org/abs/2605.30090)
15. [Yu et al., “VRBench,” ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Yu_VRBench_A_Benchmark_for_Multi-Step_Reasoning_in_Long_Narrative_Videos_ICCV_2025_paper.html)
16. [Suo et al., “Visual Context Sample Scaling,” ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Suo_From_Trial_to_Triumph_Advancing_Long_Video_Understanding_via_Visual_ICCV_2025_paper.html)
17. [Wang et al., “ReelWave,” 2025](https://arxiv.org/abs/2503.07217)
18. [Wu et al., “MovieBench,” CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Wu_MovieBench_A_Hierarchical_Movie_Level_Dataset_for_Long_Video_Generation_CVPR_2025_paper.html)
19. [Xiao et al., “VideoAuteur,” ICCV 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Xiao_VideoAuteur_Towards_Long_Narrative_Video_Generation_ICCV_2025_paper.html)
20. [Camera Artist, 2026](https://arxiv.org/abs/2604.09195)
21. [BytePlus Seedance 2.0](https://ai.byteplus.com/en/product/seedance)
22. [BytePlus video task API](https://docs.byteplus.com/en/docs/ModelArk/1520757)
23. [Google Veo 3.1 API](https://ai.google.dev/gemini-api/docs/veo)
24. [Temporal documentation](https://docs.temporal.io/)
25. [Google durable agent with Temporal](https://ai.google.dev/gemini-api/docs/temporal-example)
26. [LangGraph persistence](https://langchain-ai.github.io/langgraph/cloud/concepts/threads/)
27. [FFmpeg FAQ](https://ffmpeg.org/faq.html)
