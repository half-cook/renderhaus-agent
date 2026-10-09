<!--
Adapted from audrey-560/hyperframes-cinematic-caption at
6cdb01d74949cab379e048e9092709adbb3b203b, SKILL.md and references/*.md.
Copyright (c) 2026 Audrey. MIT License.
The complete copyright and permission notice is retained in
third_party/hyperframes-cinematic-caption/LICENSE.
Modified by Renderhaus on 2026-10-09 for the existing gated, dry-run skill.
-->

# Plan cinematic captions

Use this recipe only after the customer names HyperFrames or explicitly requests
an HTML template. Unnamed caption requests use the `motion-graphics` skill and
`remotion_render`. Keep the original edit, narration, approved copy, and brand.

Read supplied transcript and measured word timings before editing an actual clip.
Transcription, footage compositing, and subject matting are unavailable in the
current HyperFrames preview. Report missing timing or media instead of inventing it.

## Plan ordered cues

1. Group speech by meaning, contrast, proof, or a requested action.
2. Give each fragment a stable ID, `semanticGroupId`, and chronological `orderIndex`.
3. Choose one reading direction and anchor zone within each group.
4. Assign support, anchor, or hero emphasis. Record a `heroReason` for every hero.
5. Preserve measured word starts. Reveal fragments in spoken order and keep related
   fragments close enough to read as one phrase.
6. Change layout at a new argument or shot. Keep a parallel list at one stable anchor.

Favor a short word that carries the claim, concrete proof, or a requested action.
Use roughly two to five words per ordinary cue. Leave filler out without changing
meaning. A passage may have no hero. Most cues remain mixed-case support copy.

Keep one clean support sans and one real display weight. Use an occasional serif
action only when it helps the approved brand. Host-provided font files must contain
the declared weight. Disable synthesized weights and inspect repeated letters.
No fonts or installers are bundled with this adaptation.

## Choose placement and depth

At each cue's start, midpoint, and end, inspect the face, mouth, hair, hands,
product, source UI, and existing text. Record their combined motion envelope.
For 1080 by 1920 portrait work, begin with the critical area from x=90 to 990 and
y=240 to 1520. Apply stricter project or platform margins when supplied.

Keep foreground support at least 40 px from the face and mouth. Place a hero in
verified negative space when no clean subject layer exists. Do not claim
behind-subject type from a decorative mask or a duplicate photographic silhouette.

Behind-subject depth is a future-worker option with supplied, frame-locked source
footage and a clean matte. The base, type, subject, and support layers must share
start time, duration, frame rate, dimensions, crop, and scale. Preserve identifying
letters. Start with 10 to 22 percent outer hair or shoulder overlap, and reposition
any word that becomes ambiguous. Never cover the face or mouth. Inspect moving
edges for halos, doubled contours, shadows, and color changes. Recombine original
source RGB with the supplied alpha if separate compression creates a duplicate edge.

## Adapt the packaged sample

Read [the catalog](../templates/catalog.json) and
[the cinematic sample](../templates/cinematic-caption.html). The sample uses invented
copy on a plain full-frame ground. It contains no transcript, source footage,
matte, proof claim, audio, or simulated subject depth. Its timings illustrate a
recipe and do not represent measured speech.

The sample's two groups read from top to bottom.

| Group | Fragment | Start | End | Purpose |
| --- | --- | --- | --- | --- |
| idea | Make room for | 0.3 | 4.4 | Support establishes the phrase. |
| idea | ideas. | 1.2 | 4.4 | Hero names the sentence's central idea and stays short enough to read. |
| idea | One thought at a time. | 2.2 | 4.4 | Qualifier completes the group. |
| action | Start with a thought. | 4.8 | 7.8 | Setup establishes the action. |
| action | Give it | 5.5 | 7.8 | Action remains adjacent to its keyword. |
| action | space. | 6.1 | 7.8 | Hero keyword completes the requested action. |
| action | See where it leads. | 6.7 | 7.8 | Closing line follows the keyword. |

The outer `clip` elements own timing and layout. Each animated selector targets
an inner `cc-motion` wrapper. The sample registers one paused timeline at
`window.__timelines["cinematic-caption"]`. It requires host-provided GSAP.
No script, font, or media fetch occurs in the template.

Copy the catalog entry's `arguments` into the editor call, then add `html` with
the actual file contents. After changing the root dimensions, frame rate, or
duration, update the corresponding argument values. The catalog introduces no
new tool, loader, runtime installation, or automatic renderer selection.

Preserve approved local asset versions if a future worker adds footage. Use
clean white support by default and a restrained contrast treatment on bright
frames. The sample hero uses a neutral silver-white fill at 48 percent opacity
and a 1 px rim. The source recipe permits 32 to 55 percent fill opacity and
a 0.75 to 1.25 px rim. The sample has no footage beneath the glyphs; visible
source detail requires actual supplied footage and a future worker. Keep the
letter edges clear. Glow settles to sharp text within 0.4 seconds. Sound accents remain optional,
sparse, separately authorized, and subordinate to narration.

## Record verification limits

Save each actual cue's text, timing, source, group, order, emphasis, hero reason,
anchor zone, reading direction, motion selector, and depth strategy in the project
caption plan. Record the current checks accurately.

| Check | Current status |
| --- | --- |
| Tool argument schema and bounds | Available through the existing dry-run preview. |
| Composition structure and timeline registration | Checked offline by the packaged contract tests with a GSAP test double. |
| Real GSAP seek behavior, font metrics, layout, and contrast | PENDING. Host GSAP and the isolated renderer are not provisioned. |
| Early, midpoint, and late snapshots plus chronological contact sheet | PENDING. Preview does not execute HTML or capture frames. |
| Visible footage, matte alignment, and artifact playback | PENDING. No media artifact is created. |

A schema-valid preview is an incomplete export. After a future worker exists,
inspect cue boundaries, reading order, subject clearance, the contact sheet, and
direct seeks. Re-check after edits, then open and play the actual rendered artifact.
