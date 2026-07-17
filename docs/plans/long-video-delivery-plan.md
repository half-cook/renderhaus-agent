# The simple Renderhaus plan

**Goal:** Make a reliable 1–3 minute video from one idea.

**Timeline:** July 13–October 2, 2026.

**Work board:** [Renderhaus in Linear](https://linear.app/fuck-tcf/project/renderhaus-a39791d4c15a)

## The product in one line

```text
idea → script → storyboard → short clips → finished video
```

Renderhaus generates short clips because current video models are still much more reliable at that
length. It keeps characters and locations consistent by reusing approved reference images. It
builds the final video with ordinary editing tools instead of asking one model to generate the
whole film. The detailed research is in the
[evidence document](../research/long-video-evidence-base.md).

## The only six milestones

### 1. Make the plan

**Dates:** July 13–24

**Goal:** Turn an idea into saved, timed scenes and shots.

Build:

- A simple project record.
- A script, scenes, and shots.
- Shot lengths that add up to the requested video length.
- A cost estimate and approval button.

Done when:

> Three test ideas each produce a saved shot list with the correct total length. No video is
> generated yet.

Linear work: VID-1 through VID-6.

### 2. Make the storyboard

**Dates:** July 27–August 7

**Goal:** Show what every character, location, and shot should look like before generating video.

Build:

- Reference sheets for people, places, props, and style.
- A start image for every shot.
- A storyboard page where the user can edit and approve the plan.
- Seedance support for the approved references.

Done when:

> A 12-shot storyboard keeps one character recognizable in two locations.

Linear work: VID-7 through VID-11.

### 3. Generate safely

**Dates:** August 10–21

**Goal:** Generate many shots without losing work or paying twice.

Build:

- A durable background workflow.
- Parallel shot generation with a small limit.
- Pause, resume, cancel, and progress updates.
- Protection against duplicate provider jobs.

Done when:

> We stop the worker in the middle of a test, restart it, and finish without generating or paying
> for the same shot twice.

Linear work: VID-12 through VID-16.

### 4. Finish the video

**Dates:** August 24–September 4

**Goal:** Turn approved clips into a watchable video.

Build:

- Voice-over.
- Music, sound effects, and captions.
- A simple timeline.
- Preview and final MP4 exports.
- Replace-one-shot behavior.

Done when:

> Renderhaus exports a 90-second video, then replaces one shot without regenerating the others.

Linear work: VID-17 through VID-21.

### 5. Find and fix bad shots

**Dates:** September 7–18

**Goal:** Catch obvious problems and fix only the broken part.

Check:

- Does the file play correctly?
- Does the shot match the storyboard?
- Do the same people, locations, and props stay consistent?
- Do cuts between shots look sensible?
- Does the complete video tell the planned story?

Done when:

> We insert a known continuity mistake, Renderhaus finds it, replaces that shot, and rebuilds the
> final video.

Linear work: VID-22 through VID-27.

### 6. Make it ready for the team

**Dates:** September 21–October 2

**Goal:** Make the complete workflow safe, understandable, and repeatable.

Finish:

- One clean production screen.
- Upload and media security.
- Cost tracking and useful error messages.
- Logs and simple operator instructions.
- 30-second, 90-second, and 180-second test videos.

Done when:

> The final 90-second acceptance video works twice from a clean start, including one forced restart
> and one replaced shot.

Linear work: VID-28 through VID-32.

## What to do right now

The first milestone is the only work that matters right now.

1. **VID-1:** Define the smallest saved project/scene/shot format.
2. **VID-4:** Make one model call produce that format.
3. **VID-2:** Save and load it.
4. **VID-5:** Make the shot lengths add up exactly.
5. **VID-3:** Expose create/get/update endpoints.
6. **VID-6:** Show cost and require approval.

Do not start storyboards, Temporal, evaluation, or FFmpeg work until this demo passes.

## Two people, two lanes

### Satya: platform lane

Own the saved data, APIs, provider calls, workflow safety, media pipeline, and reliability.

### Baohan: creative lane

Own the script/storyboard flow, approval experience, voice/audio experience, quality prompts, and
production UI.

Both people review the milestone demo. Ownership can move when one lane blocks the other.

## Five rules that prevent over-engineering

1. Build only what the current milestone demo needs.
2. Use one director/planner flow; do not build an agent swarm.
3. Start with Seedance for video and one provider for each other media type.
4. Use SQLite locally; move to Postgres only when multi-user deployment requires it.
5. A quality checker may recommend a retry, but code—not an agent—controls cost and retry limits.

## Why this shape works

- Hierarchical planning into scenes and shots is supported by
  [MovieAgent](https://arxiv.org/abs/2503.07314).
- Approved storyboards help recurring subjects stay consistent in
  [NVIDIA Video Storyboarding](https://research.nvidia.com/labs/par/video_storyboarding/).
- Explicit visual memory improves cross-shot continuity in
  [StoryMem](https://arxiv.org/abs/2512.19539) and
  [VideoMemory](https://arxiv.org/abs/2601.03655).
- Separate shot and transition checks are justified by the failure analysis in
  [DirectorBench](https://arxiv.org/abs/2605.30090).
- Durable workflows prevent long-running work from disappearing or repeating after failure, as
  described in the [Temporal documentation](https://docs.temporal.io/).

These papers support the shape of the plan. They do not guarantee Renderhaus quality. Every
milestone therefore ends with a concrete demo instead of a theoretical architecture review.
