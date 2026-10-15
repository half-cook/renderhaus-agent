# Repository teaching and progress videos

The [codebase-video skill](../agent/deep_agent/skills/codebase-video/SKILL.md) plans
fact-checked code walkthroughs and repository progress reports. It reuses existing
local assembly, speech, media probing and final-file QC. It adds no provider, paid
endpoint, model ID, billing rate, secret or renderer implementation.

## Supported workflow and dependencies

Teaching follows source definitions and callers. Progress reporting resolves the
requested tag, commit or date to a concrete comparison range and verifies the actual
diff. Both use a claim ledger pinned to source checksums and revisions. An independent
fresh planner reviews every claim before scripting. The script and visuals get a
second independent review. Claims about numbers, runtime behavior or deployment
require evidence specific to that assertion. Commit subjects alone are insufficient.

The [evidence reference](../agent/deep_agent/skills/codebase-video/references/evidence.md)
defines brief, claim, audit, script, citation and playback records. These are editorial
instructions, not a new schema validator or a cryptographic reviewer attestation.
The existing Deep Agents planner can perform source review only when those source
files are actually readable in its environment. No approval middleware is replaced.

Studio exposes virtual conversation files. It has no shell, git client, arbitrary
repository mount or code-card typesetting tool. A path in chat cannot grant those
capabilities. Production therefore stops unless an authorized local executor supplies
sanitized pinned source/history evidence and literal PNG cards, or the agent runs
in a local environment with actual read-only repository and drawing facilities.
An incomplete snapshot, missing base tag, unavailable fresh reviewer or missing
card asset blocks the affected step. This feature does not expose arbitrary server
file reads or execute scripts found in a customer's checkout.

Repository code cards use deterministic typesetting and existing timeline PNG
visuals. The host rejects image and video generation for this workflow. Set up the
local render backend through normal operator configuration before running it.
The skill cannot change dry-run flags or select cloud rendering. Both Gateway
discovery and dispatch refuse cloud assembly for recognized codebase-video requests.
An explicitly named HTML renderer retains its existing optional, incomplete preview.
It cannot export a finished MP4 here. UI capture remains pending under the existing
`cutaway_record` alias. Supplied genuine recordings can be used as cutaways.

User recordings work without hosted speech generation. Optional hosted narration
receives only the reviewed script, with external processing disclosed and existing
cost approval and spending limits. A requirement for entirely local processing
blocks hosted narration. Do not claim that all processing is local when a hosted
planning model or speech service receives text. Never upload a repository archive,
credentials or raw source files as speech input. The stored confidentiality field
does not select a different model or renderer.

Poll the saved render ID, open and play the actual MP4, and deliver a citation
appendix with final chapter timestamps. A finished video also needs a saved passing
deliverable QC report matching the output checksums. Technical checks cannot accept
framing, captions, legal copy or prices. Resolution reporting follows the existing
source-native policy, including every warning and any resampling disclosure.

## Routing and verification

Repository teaching or progress intent selects this skill before generic video
and narration rules. A UI launch capture and a generic science or whiteboard
explainer retain their existing routes. Explicit code-generation models refuse
rather than silently changing the user's choice. Existing audio-provider requests
apply to narration and do not choose a code-card generator.

RT-191 and RT-192 were named in the supplied radar handoff but were absent from the
original fixture and supplied capability-map CSV. The new prompts were authored
from the draft skill, with provenance recorded on each row. They are active routing
checks, not evidence that a video was generated. The six existing dependency skips
remain. Inventory is 21 providers, 140 tools, 43 skills, 344 rows and 338 active rows.

Focused offline checks run with:

```bash
.venv/bin/python -m pytest -q tests/test_codebase_video_routing.py tests/test_skill_routing.py
```

The test suite checks teach/progress selection, narration ordering, adjacent intents,
negation, generation refusal, local backend refusal and unchanged approval behavior.
No paid creative or model evaluation is authorized in this task. Comet browser E2E
and final media playback remain pending when browser access is unavailable. A mocked
or dry-run result cannot satisfy those checks.

## Source and licence

The [upstream workflow](https://github.com/OnurGumus/codebase-video/blob/70602e2700caae249b1f4a6c3eb35a008d04ae0e/skills/codebase-video/SKILL.md)
and [MIT licence](https://github.com/OnurGumus/codebase-video/blob/70602e2700caae249b1f4a6c3eb35a008d04ae0e/LICENSE)
were read on 2026-10-15. Renderhaus adapts the teaching/progress split and fresh review
pattern in original wording. It does not copy the upstream runtime, engine, prompt
templates, models or media. The skill's [NOTICE](../agent/deep_agent/skills/codebase-video/NOTICE)
retains attribution. No AGPL or non-commercial code or weights are introduced.
Existing tool licences, training eligibility and prices are unchanged.
See [decisions](codebase-video-decisions.tsv) for scope and validation limits.
