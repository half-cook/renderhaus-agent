# Non-fiction series planning

`series-video-planner` turns a long article, topic or course outline into a
reviewable series plan and per-episode briefs. It is separate from fictional
`short-drama-series` and from `plan-to-video`, which renders a plan review.
Single-episode production keeps its existing explainer routing.

## Planning contract

The deterministic router proposes a ready planning route with no tool, provider,
model, paid steps or execution groups. `required.planning_only` and
`required.plan_approval` describe the workflow. They do not grant spending
permission or install an approval tool. The manager reads the skill and uses
the existing Deep Agents planner and virtual project-file tools.

The plan lives at `/series/<series_id>/plan.md`. Each episode has
`/series/<series_id>/episodes/<episode_id>/brief.md`. These are conversation
files persisted by the existing checkpoint, not directories on the customer's
computer. A new conversation needs the files supplied explicitly.

The plan records source locators, evidence gaps and corrections, one takeaway
per episode, estimated durations, an episode graph, viewing order, exact shared
locks, asset needs, optional extras and progress. `requires` edges identify
prerequisites; `next` links suggest viewing order. Modular is the default link
strength. Tight serial and anthology require a stated editorial reason.
The agent checks graph IDs and cycles while planning; no deterministic graph
validator or factuality checker is introduced.

One mental model in about 150-180 seconds usually needs one explainer. That is
a planning heuristic, not an API limit or a fixed narration speed. The planner
preserves explicit episode-count preferences and flags filler or crowding.
Missing source content produces a provisional outline or a request for the
material, never an invented source read.

## Review and production

The planning turn returns a draft through `StudioAgentOutput` and asks for review
in chat. It does not submit production. This is ordinary conversational review,
not a native approval card or host-enforced outline hash. The agent records the
actual response and revision. Rejected or revised plans require another review.
The fictional drama approval/checker tools do not apply.

The shared `request_tool_blocker` removes Gateway media tools from discovery and
refuses their execution in a series-planning turn, even for an already-approved
autonomous call. Gateway schema search remains available. A later single-episode
production request uses its normal route and cost approval. Mentioning an existing
series in that request does not restart series planning.
Studio's completion checker accepts the planning route as a document result, including
requests phrased as "make a video series". Other video routes still require their media artifact.

After actual plan approval and an episode production request, the manager hands
off one brief at a time to `whiteboard-explainer`, `knowledge-explainer` or
`art-style-motion`. The brief carries source evidence, locks and explicit
production preferences. The production skills reuse existing image, audio and
render tools with their exact discovered schemas. Plan approval authorizes no
spend. Existing paid-video cost approvals apply in autonomous runs, along with
all other consent, licence, dry-run and spending-cap controls. Unknown prices
remain unknown. Project confidentiality does not select a different route.

The skill has empty `include_tools`, `routing_tools` and `gateway_tools` metadata
because planning exposes no provider calls. It links production skills rather
than advertising their tools as planning dependencies. No provider, Gateway
schema, secret, billing rate, model policy, UI model label or capability-map ID
is added or renamed. Runtime model configuration remains unchanged.

## Sources and licence

The external draft and handoff item 2 supply the task scope. Both RT-189 and
RT-190 are absent from the supplied `capability-map.routing.csv` and the starting
JSON fixture. The added prompts are authored from that scope, not transcribed
workbook rows. The fixture retains all original rows and all six dependency skips.

The method uses the learning-sequence and modular-link pattern in
[JustChenk/vibe-video-skills](https://github.com/JustChenk/vibe-video-skills/blob/f7aec769a2fbb12f1c808349608b0344b7117c06/skills/series-video-planner/SKILL.md).
Its [MIT licence](https://github.com/JustChenk/vibe-video-skills/blob/f7aec769a2fbb12f1c808349608b0344b7117c06/LICENSE)
was verified through the official GitHub repository on 2026-10-15.
Renderhaus uses original wording and templates. No upstream executable code,
media, weights, fixed output settings or renderer dependency is included.
The skill's packaged NOTICE retains the upstream licence. No AGPL or
non-commercial dependency is introduced.

[LangChain's skills documentation](https://docs.langchain.com/oss/python/deepagents/skills)
was read 2026-10-15. Installed `deepagents==0.7.23` signatures for
`create_deep_agent`, `SkillsMiddleware`, `_parse_skill_metadata` and
`HumanInTheLoopMiddleware` take precedence. The implementation reuses the
existing skill directory, planner, checkpoint and file tools.
No new model ID, endpoint, request schema or price needs verification.

## Validation

`tests/test_series_video_planner.py` exercises planning-only routing, fiction
and single-explainer boundaries, negated and quoted source requests, unchanged
stored project policy, and a scripted file-planning run through the installed
Deep Agents harness. A direct executor check confirms the planning guard blocks
an autonomous image submission before Gateway dispatch and spend accounting.
These checks do not establish live model behavior.
Independent offline skill forward-testing supplements them.

Comet browser E2E is pending. No Comet control tool is available in this session,
and the user prohibits live or paid API calls. The pending scenario is to submit
a non-fiction series request through Studio, inspect the saved draft and briefs,
request a revision, reject production, and observe that no media was submitted.
Mocks and routing assertions are supporting checks, not browser evidence.
See [decisions](series-video-planner-decisions.tsv).
