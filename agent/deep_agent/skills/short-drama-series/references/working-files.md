# Working files

All files use plain UTF-8 Markdown or JSON. Preserve text exactly. The host tools accept
objects, not filesystem paths, and return validation errors without network requests.
Write the returned canonical data back to the episode file after a successful check.

`review_drama_outline` takes one `outline` object with these required fields:

```json
{
  "series_id": "clock-shop", "title": "The borrowed hour", "revision": "1",
  "adaptation_notes": "Original fictional story; six short vertical episodes.",
  "cast": ["mei"], "beats": ["A borrowed hour must be repaid."],
  "episodes": [{"id": "ep01", "synopsis": "Mei lends an hour.", "hook": "The clock starts counting backward."}],
  "assets": ["mei", "shop"]
}
```

Every field is nonempty. Episode IDs and cast IDs are unique. Approval returns an
`outline_hash`. Use that actual hash in `episode.outline_hash`; no sample hash authorizes work.
Put audience, genre, aspect and target episode length inside `adaptation_notes` or the
readable series bible. They are not additional JSON keys. Draft-only episodes may use
`outline_hash: "unapproved"`; the production gate refuses that value until outline approval.

`validate_drama_episode` accepts an `episode` object and `jobs` array. Read
[episode.json](../templates/episode.json) as a structural example. Replace its illustrative
hash with the host-approved hash and its story with the customer's approved material.
The fields are:

| Record | Required fields |
| --- | --- |
| Episode | `episode_id`, `outline_hash`, `characters`, `art`, `locks`, `script`, `segments` |
| Character | `id`, `profile`, `design_prompt`, `voice_prompt` |
| Art/location/prop | `id`, `description`, `design_prompt` |
| Lock | `id`, `subject_id`, `phrase` |
| Dialogue | `id`, `kind: "dialogue"`, `speaker_id`, `text` |
| Action | `id`, `kind: "action"`, `text`, `duration_seconds` |
| Segment | `id`, `cuts` |
| Cut | `id`, `duration_seconds`, `subjects`, `lock_ids`, `keyframe_prompt`, `video_prompt`, `line_ids` |
| Optional caption | `line_id`, `text`, in the episode's optional `captions` array |
| Production job | `id`, `tool_name`, `arguments`, and `cut_id`, `segment_id` or `line_id` when applicable |

IDs are unique in their record set; cut IDs are unique across the episode. Every script
line is assigned exactly once. Speakers must be known characters. Depicted subjects need
their locks cited and pasted into both prompts. The checker reports the missing lock ID.
Action time and estimated dialogue time must fit the assigned cut. Do not treat dialogue
timing as measured speech. The estimate counts CJK characters at four per second and other
non-whitespace characters at twelve per second, rounded up to a tenth with a 0.4-second floor.

Jobs use the exact discovered Gateway schema. Image prompt equals the referenced cut's
keyframe prompt. Video prompt equals its segment's cut video prompts joined with `\n`;
duration equals the sum of those cuts and is at most 15 seconds. Speech text equals the
referenced dialogue line. Polls, free checks and future asset placeholders are separate.
For music and assembly jobs, supply their normal exact argument objects. The host derives
prices from existing billing contracts; the batch never supplies its own estimate or approval.

A batch can produce only references, only some ready shots, or an assembly from completed
assets. It need not cover the whole episode at once. Each new batch replaces the executable
previous batch. A changed outline invalidates that batch and the previous continuity registry.
Keep completed episode files and job IDs for reuse and review.
