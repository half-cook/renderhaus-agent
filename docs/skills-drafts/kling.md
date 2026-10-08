# Kling generation guidance draft

Status: provider built. Guidance is incorporated in the live t2v and i2v skills.
The live skills and `agent/deep_agent/routing_policy.json` define current routing.

This provider reference informs the installed intent skills. Those skills own live routing.

Route to Kling when the user asks for Kling, synchronized native audio, controlled
start/end frames, multi-shot video, or multiple image and element references.
Use Wan for an ordinary video request unless the brief requires Kling capabilities. Do not treat Kling as a replacement for still-image
editing or video assembly. Use existing assembly tools after source media exists.

Discover the actual Gateway tools and schemas. Use `Kling___list_kling_models`
when capabilities or model selection matter. Its catalog reflects published
documentation, not account activation. Never invent a model or endpoint.

Choose one submission tool.

- Use `Kling___text_to_video` for a clip described by text.
- Use `Kling___image_to_video` to animate a start frame. Supply an end frame only
  when the selected model and API style support it.
- Use `Kling___omni_video` for multiple reference images or existing elements.
  Supply the element's actual ID, prompt identifier, and element type. Do not
  fabricate an element or assume an image URL is an element ID.

Prefer short 720p requests. Set `generate_audio=true` only when native audio is
wanted and documented for the model. Explicit shots use `prompt` and
`duration_seconds`, one through six shots, with a duration sum equal to the total.
Preserve supplied reference handles so the backend can resolve media access.
Consult [the provider reference](../KLING.md) for the precise limits.

Respect the user's approval and spending scope. Quote generation using
`server/billing_rates.py` before a paid request. Explain the provider cost and
platform fee. Polling and model discovery are free. Never silently repeat a
submission after a timeout or uncertain response; it could create a second paid
job. Turbo billing is blocked until its audio semantics are confirmed. Do not
estimate a silent Turbo rate from consumer credits or another provider.

After submission, pass the exact returned `job_id` to `Kling___get_video_task`.
Poll once per tool call. On success, use `download=true` and verify that the
actual persisted artifact opens and plays. A task ID or `queued` result does not
mean the video exists. Report a provider failure and its safe error message.
A `dry_run` result is terminal and has no generated media.

Kling credentials belong in environment configuration or AWS Secrets Manager.
The current API requires `KLING_API_KEY`; legacy requests use `KLING_ACCESS_KEY`
and `KLING_SECRET_KEY`. Never ask users to paste credentials, JWTs, or signed
media URLs into chat. Never change the dry-run flag to spend money without
existing authorization.

Commercial output use is permitted by the official API terms, subject to lawful
input rights and applicable law. Users retain infringement responsibility.
Credential sharing and reselling API access have separate restrictions. Do not
promise blanket rights or a licence to redistribute the API. Consult
[the official terms](https://kling.ai/document-api/guides/protocols/paid-service).

When live API access or Comet is unavailable, report validation as blocked.
Offline tests establish request and state handling; they do not establish live
model activation, output quality, playback, or browser behavior.
