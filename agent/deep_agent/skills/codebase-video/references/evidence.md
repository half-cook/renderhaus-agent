# Evidence files

Keep these small records in `/codebase-video/<video_id>/` using Deep Agents file
tools. They are editorial evidence, never arguments to a media tool.

`brief.json` records `kind` as `teach` or `progress`, the authorized repository path,
audience, subject, target duration, full `head_commit`, snapshot origin and dirty-tree
policy. For progress, also record the original boundary request, timezone, resolved
`base_commit`, `end_commit`, comparison convention and git commands. Never substitute
another range when the requested one is unavailable.

`claims.json` records a `revision` and a `claims` list. Each claim has a stable `id`,
`text`, `status`, `citations` and optional literal `excerpt` or measured `value`.
Each citation has a repository-relative `path`, inclusive `line_start` and `line_end`,
the full `commit` or working-snapshot ID, and `file_sha256`. Diff claims also identify
both endpoint revisions and the old or new side. Numbers identify the evidence file,
command, units and counting convention. Preserve supporting evidence locally.

`audit.json` records the reviewed ledger revision, source snapshot IDs, reviewer task
reference and one result per claim ID. Results use `verified`, `rejected` or `pending`,
with independent source observations and required corrections. Missing claims or
unreadable sources fail closed. An author-assigned status or copied citation is not
independent verification. A changed ledger or source invalidates the affected results.

`script.json` records ordered chapters with `id`, narration text, `claim_ids`, exact
card text, cited excerpt ranges, diagram labels and edges, visual asset paths and
caption text. After audio exists, add measured duration and output start/end times.
Every factual visual and spoken clause must map to verified claim IDs. A hypothetical
example must be visibly labelled and cannot masquerade as source code.

`citations.md` maps final timestamps to chapter and claim IDs, repository revision,
file-line citations, progress range and audit outcome. `review.md` records actual
playback observations, issues, saved QC report paths and output checksums. Keep
unknown measurements and unresolved checks explicit. Do not store credentials,
private browser state or signed URL query strings in any evidence file.
