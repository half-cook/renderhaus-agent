# Product requirements: Renderhaus Long Video

**Status:** Draft for implementation  
**Date:** 2026-07-12  
**Target release:** 2026-10-02  
**Owner:** Renderhaus team

## 1. Product thesis

Renderhaus will turn a creative brief into a coherent, editable, narrated 60–180 second video by
planning a production, generating short shots with explicit continuity memory, evaluating and
repairing weak shots, and assembling approved assets on a deterministic timeline.

This is deliberately not “ask one model for a three-minute clip.” The 2025 ICCV survey of 32
long-video methods reports that contemporary generators largely produce 5–16 second clips and that
longer output commonly loses character appearance, scene layout, motion coherence, or temporal
diversity. It identifies multi-stage planning and consistency mechanisms as the practical route to
long-form storytelling ([Elmoghany et al., 2025](https://openaccess.thecvf.com/content/ICCV2025W/LongVid-Foundation/html/Elmoghany_A_Survey_on_Long-Video_Storytelling_Generation_Architectures_Consistency_and_Cinematic_ICCVW_2025_paper.html)).
The official Seedance 2.0 API similarly exposes 4–15 second generation with text, image, audio,
video, and prior-task references, confirming that Renderhaus must orchestrate shots rather than
inflate one provider call ([BytePlus Seedance 2.0](https://ai.byteplus.com/en/product/seedance),
[BytePlus task API](https://docs.byteplus.com/en/docs/ModelArk/1520757)).

## 2. Target customer and initial jobs

The initial customer is a creator, small studio, marketer, or product team that wants a polished
short film without manually coordinating a script editor, storyboard tool, several generation
providers, an audio pipeline, and a non-linear editor.

Launch formats are intentionally bounded:

1. Narrated product and brand films.
2. Documentary-style explainers composed from narration and generated B-roll.
3. Travel, architectural, fashion, and mood films.
4. Social mini-stories with one recurring hero, no more than two locations, and a small prop set.

The constraint is evidence-driven. EntityBench shows that entity consistency degrades sharply as
recurrence distance grows and that explicit per-entity memory materially improves fidelity
([He et al., 2026](https://arxiv.org/abs/2605.15199)). A limited initial cast and location count
therefore reduces both technical risk and the number of identity constraints the system must
satisfy.

## 3. User promise

> Give Renderhaus a brief. Review an editable script and storyboard. Render a coherent 60–180
> second video that survives interruptions, reports cost and provenance, and lets you replace one
> weak shot without regenerating the whole film.

### Required user journey

1. The user submits a brief, target duration, format, audience, style, references, and budget mode.
2. Renderhaus returns a timed treatment, continuity bible, and shot plan before spending on video.
3. The user approves or edits the plan and keyframes.
4. Renderhaus renders independent shots with bounded concurrency and visible progress.
5. Automated critics identify technical, prompt-alignment, continuity, and transition defects.
6. Renderhaus repairs only the affected shots within an approved retry budget.
7. The editor creates a preview with narration, music, SFX, and captions.
8. The user can replace, lock, or revise a shot; only downstream dependencies are invalidated.
9. Renderhaus produces an MP4, captions, thumbnails, and a machine-readable production manifest.

Hierarchical scene and shot planning is supported by MovieAgent, which reports improved script
faithfulness, character consistency, and narrative coherence from director/scene/shot planning
compared with less structured approaches ([Wu et al., 2025](https://arxiv.org/abs/2503.07314)).
FilmAgent also reports that iterative collaboration over idea, script, and cinematography stages
outperformed its tested baselines in human evaluation, including a stronger single-agent model
([Xu et al., 2025](https://arxiv.org/abs/2501.12909)). These results motivate staged artifacts and
review gates, not an unconstrained chat loop.

## 4. Scope

### P0 — launch requirements

- 60–180 second target duration; exact exported duration within ±250 ms.
- 16:9 and 9:16 delivery at 1080p, with 720p draft proxies.
- Timed treatment, scene plan, shot plan, continuity bible, and storyboard.
- One recurring character, two locations, five persistent props, and up to 24 shots.
- Provider-independent shot routing with Seedance as the first production video provider.
- Image-conditioned generation and previous/end-frame references.
- Durable pause, resume, cancel, restart recovery, and idempotent paid generation.
- Shot-level candidates, selection, critique, bounded regeneration, and fallback treatment.
- Live narration, music/SFX tracks, caption generation, ducking, loudness normalization, and final
  FFmpeg assembly.
- User approval before paid video generation and when projected spend exceeds the approved budget.
- Per-shot progress, provider attempt history, cost ledger, provenance, and safe public errors.
- Manifest export and versioned project history.

### P1 — immediately after launch

- Multi-character dialogue and lip-sync routing.
- Reusable character, location, voice, and style libraries.
- Multiple video providers with empirical router policies.
- Timeline trimming, reordering, transition choice, and audio gain controls.
- Collaborative comments and shareable approval links.
- Four-to-ten-minute documentary/explainer projects.

### Explicit non-goals for launch

- A single end-to-end neural model that directly emits a complete film.
- Feature-length or hour-long narrative generation.
- Training a proprietary video foundation model.
- Unbounded autonomous spending or unbounded critic/regeneration loops.
- Pixel-perfect identity for arbitrary real people; provider policy and consent constraints apply.
- Frame-level manual NLE parity with Premiere, Resolve, or Final Cut.

## 5. Functional requirements

### FR-1: brief normalization

The Director must convert prose into a typed `CreativeBrief` containing audience, objective,
runtime, delivery format, narrative mode, visual rules, audio rules, references, forbidden content,
budget ceiling, approval policy, and acceptance criteria. Missing non-critical fields receive
visible defaults; ambiguous safety, rights, or budget constraints require clarification.

### FR-2: timed hierarchical plan

The Writer must produce beats, scenes, and shots whose durations sum exactly to the requested
runtime after transition handles. MovieBench organizes long-form video hierarchically and is built
around movie-, scene-, and shot-level structure, supporting a matching data model
([Wu et al., 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Wu_MovieBench_A_Hierarchical_Movie_Level_Dataset_for_Long_Video_Generation_CVPR_2025_paper.html)).
VideoAuteur further reports improvements from a Long Narrative Video Director that aligns semantic
and visual structure ([Xiao et al., 2025](https://openaccess.thecvf.com/content/ICCV2025/html/Xiao_VideoAuteur_Towards_Long_Narrative_Video_Generation_ICCV_2025_paper.html)).

### FR-3: continuity bible and memory packs

The Continuity Supervisor must create canonical entities and state transitions for characters,
locations, props, costumes, time, weather, lighting, screen direction, and story facts. Each shot
receives only relevant verified references plus adjacent transition frames.

VideoMemory uses an entity-centric dynamic memory bank for characters, props, and backgrounds,
retrieving states per shot and updating them after story-driven changes
([Zhou et al., 2026](https://arxiv.org/abs/2601.03655)). StoryMem reports stronger cross-shot
consistency using a compact, dynamically updated bank of selected keyframes rather than an
unbounded history ([Zhang et al., 2025](https://arxiv.org/abs/2512.19539)). CANVAS separately
reports gains from character continuity, persistent background anchors, and location-aware scene
planning ([Comanici et al., 2026](https://arxiv.org/abs/2604.13452)). These findings directly
support explicit, entity-indexed, bounded memory packs.

### FR-4: storyboard-first generation

Every expensive shot must have an approved shot spec and start keyframe; hero and transition shots
should also have an end keyframe. NVIDIA’s Video Storyboarding demonstrates that storyboards can
preserve recurring subject identity across shots without fine-tuning the underlying video model
([NVIDIA, 2025](https://research.nvidia.com/labs/par/video_storyboarding/)). DreamFactory similarly
uses iterative keyframes to maintain style and cross-scene consistency
([Xie et al., 2024](https://arxiv.org/abs/2408.11788)).

### FR-5: durable execution

Every LLM call, provider submission, provider poll, asset download, evaluator, and FFmpeg render
must be an idempotent workflow activity with persisted input, output, attempt, and cost metadata.
Temporal guarantees workflow resumption after failures and provides durable timers, retries, and
signals ([Temporal documentation](https://docs.temporal.io/)). Google’s durable-agent reference
maps LLM and tool calls to Temporal activities so completed operations are not repeated after a
crash ([Google durable-agent example](https://ai.google.dev/gemini-api/docs/temporal-example)).

### FR-6: evaluation and targeted repair

Renderhaus must evaluate technical validity, intra-shot quality, prompt adherence, entity
continuity, transition compatibility, narrative coverage, audio quality, and cross-modal timing.
VBench decomposes video quality into 16 dimensions rather than one aggregate score
([Huang et al., 2024](https://openaccess.thecvf.com/content/CVPR2024/html/Huang_VBench_Comprehensive_Benchmark_Suite_for_Video_Generative_Models_CVPR_2024_paper.html)).
DirectorBench finds between-unit transition quality to be a major bottleneck in long-form workflows
and evaluates script, visual, audio, cross-modal, and stability dimensions
([Chen et al., 2026](https://arxiv.org/abs/2605.30090)). Therefore a shot may pass locally yet fail
at the sequence level; both gates are required.

### FR-7: deterministic editorial assembly

LLMs may propose trims and transitions, but deterministic media code must execute them. FFmpeg’s
official concat filter/demuxer support provides a reproducible basis for normalized clip assembly
([FFmpeg FAQ](https://ffmpeg.org/faq.html)). The final render must use pinned command templates,
record exact inputs and checksums, and be reproducible from the manifest.

## 6. Success metrics

### Product metrics

- At least 70% of approved projects reach an export without manual engineering intervention.
- Median time from approved storyboard to 90-second draft under 45 minutes, provider latency
  permitting.
- At least 60% of first-time users approve or make only localized edits to the generated plan.
- At least 80% of revisions invalidate no more than one scene.

### Quality metrics

- 95% of exported shots pass file, codec, duration, frozen-frame, and black-frame checks.
- 85% of selected shots pass prompt-adherence and local visual thresholds without manual override.
- At least 80% entity-presence and identity pass rate across recurrence gaps in the internal
  EntityBench-inspired suite.
- No unresolved P0 continuity defect in a released project.
- Narration intelligibility MOS target ≥4/5 in internal review; no clipping; output loudness within
  the configured delivery target.
- Human review median ≥4/5 for story clarity and ≥3.5/5 for transitions.

Metrics are deliberately multidimensional. VBench shows that subject identity, motion smoothness,
flicker, spatial relations, and prompt alignment are separable qualities, while VBench 2.0 adds
human fidelity, controllability, physics, and commonsense checks
([Zheng et al., 2025](https://arxiv.org/abs/2503.21755)).

### Reliability and cost metrics

- Zero duplicate paid provider submissions across worker restarts in chaos tests.
- 99% of workflow state transitions persist before the next paid side effect.
- 100% of projects have an estimate before approval and an exact cost ledger after completion.
- Default retry spend ≤30% of first-pass generation spend.
- A failed shot can be repaired and reassembled without rerendering unaffected video shots.

## 7. Risks and mitigations

| Risk | Evidence | Mitigation |
|---|---|---|
| Identity drifts after long gaps | EntityBench observes consistency degradation with recurrence distance. | Persistent verified entity memory; keyframes; recurrence-specific evaluation. |
| Autoregressive errors accumulate | ShotStream identifies error accumulation as a core multi-shot problem. | Do not condition blindly on every prior generated frame; retrieve verified canonical references and quarantine rejected takes ([Luo et al., 2026](https://arxiv.org/abs/2603.25746)). |
| Local quality hides bad transitions | DirectorBench reports a between-unit bottleneck. | Pairwise transition gate plus whole-film QC. |
| Agent loops become expensive or nondeterministic | Agent papers demonstrate planning value, not production safety. | Typed artifacts, bounded turns, schema validation, deterministic workflow and media execution. |
| Provider limits or policy reject references | Official APIs impose model- and content-specific constraints. | Capability registry, preflight validation, provider fallback, user-visible policy errors. |
| Audio feels pasted on | ReelWave treats on-screen synchronization and off-screen sound as distinct planning problems. | Separate dialogue, on-screen SFX, ambience, and music plans; timeline-aware mix ([Wang et al., 2025](https://arxiv.org/abs/2503.07217)). |

## 8. Launch acceptance film

Renderhaus passes launch when it can autonomously produce and then locally revise a 90-second film
with 12–18 shots, one recurring character, two locations, one tracked prop, narration, music,
captions, and at least one deliberate continuity challenge. During the run, the worker is killed
after paid tasks have started; recovery must not duplicate them. A reviewer then replaces one shot;
only dependent evaluation and editorial activities may rerun.

This acceptance scenario tests the specific failure modes exposed by the literature: long-range
entity recurrence ([EntityBench](https://arxiv.org/abs/2605.15199)), memory updates
([VideoMemory](https://arxiv.org/abs/2601.03655)), transition quality
([DirectorBench](https://arxiv.org/abs/2605.30090)), and durable external calls
([Temporal](https://docs.temporal.io/)).
