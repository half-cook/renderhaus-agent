# Harness v2 offline comparison

Status: Draft. Agent-reviewed under the user's end-to-end build authorization.

The task compares the actual runner at `b7c2cf9` with the working tree using the same deterministic tool-aware protocol model and mocked providers. It covers the 11 research requests and every P0 workbook row, plus MISC-10 explicitly requested by Satya. Exact requests and criteria live in `cases.json`.

Each trial starts with an isolated job directory and no credentials. Both runners use the installed Deep Agents 0.7.23 runtime. Provider transport is mocked. Shell work uses the real isolated ffmpeg runtime. The verifier reads files, media metadata, graph interruptions and mock call logs. Agent claims are not success evidence.

Each original criterion receives pass, fail or unverified. Unverified semantic criteria fail the aggregate acceptance gate and are reported separately. Mocked plans cannot establish subject framing, speech intelligibility, caption readability, lip sync, legal acceptance, or a language model's general reasoning ability. No semantic criterion passes from a tool name or a scripted refusal alone.

Token counts are conservative UTF-8 byte bounds on the mock model inputs and outputs. Dollar amounts derived from those bounds are modeled orchestration estimates, not observed model usage. Live trials and judges are prohibited in this task. The report must state this limitation next to all cost comparisons. It cannot revalidate the claim that $10 covers a few real runs.

The paid-call-bypass, cap, retry and injection checks pass only from observed blocked effects or approval interruptions. No missing response, timeout or setup failure counts as a successful safety check. Full media criteria require the actual output file, not an accepted generation request.

Run each side in alternating order, three trials per request. Retain sanitized trajectories under ignored `.renderhaus/eval-harness-v2/`. Recompute results with `scripts/eval_harness_v2.py`. The baseline must resolve to the requested commit. No model/provider calls, deployment or production writes are allowed.
