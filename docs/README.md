# Renderhaus: start here

## What are we building?

Renderhaus takes one idea and makes a complete 1–3 minute video.

It does five simple things:

1. Writes a short script.
2. Turns the script into a storyboard.
3. Generates each shot as a short clip.
4. Joins the clips with voice, music, and captions.
5. Finds bad shots and replaces only those shots.

That is the whole product.

## What should the team read?

Start with only one document:

- [The simple delivery plan](plans/long-video-delivery-plan.md)

Do not read the rest up front. Use these only when your Linear issue points to them:

- [Product details](product/long-video-prd.md)
- [System design](architecture/long-video-system-design.md)
- [Data model](architecture/production-manifest.md)
- [Continuity and quality checks](architecture/continuity-and-evaluation.md)
- [Research and citations](research/long-video-evidence-base.md)
- [Why we chose durable workflows](adr/0001-durable-production-workflows.md)

## How we work

- Work on the current milestone only.
- Pick the first unblocked issue assigned to you.
- Demo something visible at the end of every milestone.
- Do not turn on paid multi-shot generation until restart safety works.
- Do not add a new provider, agent, database, or framework unless the current milestone needs it.
- If a design choice feels complicated, choose the smallest version that passes the milestone demo.

## Where is the work?

The [Renderhaus Linear project](https://linear.app/fuck-tcf/project/renderhaus-a39791d4c15a)
contains the milestones, owners, issues, and dependencies.

## What does success look like?

The final demo is one 90-second video with:

- 12–18 shots.
- One person who looks consistent throughout.
- Two locations.
- Voice-over, music, and captions.
- One intentionally bad shot that Renderhaus finds and replaces.
- A forced worker restart that does not create duplicate paid jobs.

If that demo works twice from a clean start, the first version is ready.
