# Write and diagnose a dialogue shot

Load this reference only for the Seedance 2.5 path or explicit feedback about that path.
Keep Wan 3.0 as the ordinary generation default. Explicit model requests retain precedence.
Existing edit and extend work belongs to edit-v2v, whose permanent defaults stay unchanged.

This is an English adaptation of French, web-UI-oriented MIT material, read 2026-10-14.
See [the source and MIT notice](NOTICE). Every adapted claim about model behavior is
UNVERIFIED against the API until a live A/B. These are prompt-writing hypotheses, not
promises that a model follows a clause. No live comparison was performed for this change.

## Keep controls in their real fields

Discover the selected tool's schema before generation. The existing T2V contract accepts
`prompt`, `duration_seconds`, `aspect_ratio`, `resolution` and `generate_audio`.
Camera movement, character identity, voice description, spoken language, timing and physics
all go inside `prompt`. There are no separate camera, language, voice or negative-prompt fields.
Keep transport selection with the operator: fal by default, BytePlus only when configured.
Never change hosts, models, flags or resolution to test a prompt hypothesis.

Set `duration_seconds` to an integer from 4 through 30. Use the configured resolution and
the customer's requested aspect ratio. Writing a ratio in prose does not set the output field.
Set `generate_audio=true` for native spoken dialogue. Prose cannot override disabled audio.
Do not promise exact syllable timing, frame-accurate beats or an identical voice across clips.
The selectable legacy 1.5 path is outside this guidance and retains its own constraints.

For start frames or references, read i2v and its exact schema. Do not attach image, video or
audio references to a text-only call. Reference identity and voice roles need actual supplied
assets and the corresponding accepted fields. Never invent a reference handle or token.
Real-person photos or video cannot enter this path, even with spending or likeness approval.
Keep the existing real-face refusal and generation routing rules.

## Build the shot from visible events

Write the scene in this order, omitting parts that do not serve the brief.

1. Name the synthetic character, its stable visible traits and the principal action.
2. Establish the place, body orientation, important objects and who holds each one.
3. State the opening framing, camera height and angle, one main move, its pace and endpoint.
4. Place actions and spoken lines in ordered beats within the requested duration.
5. Carry identity, object count, ownership, light and screen direction across the beats.
6. Specify background sound separately from speech, then describe the final visible state.

Give each beat one principal change. Let the next beat begin from the state the previous beat
left behind. A multi-shot request needs an explicit cut and local framing and light for each
shot. Reuse the character and voice descriptions verbatim across clips unless the user changes
them. A prompt must stand on its own; "same as before" does not describe the missing state.

Describe acting at the scale the audience can see. A full-body wide shot can show posture,
weight shifts and gestures. A close-up can show a gaze moving between specific targets.
Do not bury a wide shot beneath paragraphs of eye detail or add a new prop to fill a pause.

## Describe motion through cause and state

Separate what the character does from what the camera does. For a manipulation, name the
supporting hand, the contact that starts movement, its direction and its resting state.
The object should retain its owner and count until a described transfer occurs.
After occlusion, restate what returns unchanged instead of treating the subject as a new arrival.

For a jolt, identify whether the body, moving environment or camera support carries it.
State the direction, support and resulting response. For cloth or liquid, give the force
direction and what happens after that force stops. Use a small contact sequence when the
physical action is the point of the shot; keep secondary motion general.
"Realistic physics" alone cannot describe contacts, momentum or where an object ends.

## Phrase camera direction as a visible change

Pair the camera term with its observable result. A dolly-in can start waist-up at eye level,
move toward a stationary character at a steady pace, and finish shoulders-up with the face
centered. An orbit needs a direction, the side it reveals and the view where it stops.
A lateral move can name existing foreground and background elements that pass at different
speeds, while the subject keeps the intended framing.

Keep camera travel, camera rotation, focal-length changes and focus changes distinct.
For a focus pull, name what starts sharp, what ends sharp and what becomes soft.
A reveal needs something already located behind an obstruction; it should not appear from nowhere.
Use one main move per beat and keep its path compatible with the character's path.
Avoid a vague "cinematic camera" instruction or several simultaneous, incompatible moves.

## Attribute dialogue and preserve its language

Specify the spoken language, the requested regional variety, the speaker and the exact line
in straight quotation marks. The language of technical direction can differ from the spoken
line and the chat response. Preserve the customer's words and language when revising;
translating the surrounding directions does not authorize translating dialogue.

For each synthetic character, keep a short voice description with range, texture, pace,
delivery and language. Copy that description unchanged across shots. This is a prompt
consistency technique, not a voice-cloning parameter or a guarantee of acoustic identity.
Place the line in a time window and state what the character does before and after it.
During one character's line, describe the others as listening silently.

Separate spoken words from ambience, action sounds and music. Put a contact sound beside
the action that causes it. Do not quote an inner thought during a silent beat or put sound
effects inside a character's line. If subtitles are unwanted, a short "No subtitles" clause
can express that intent in `prompt`. Keep exact titles and legal copy for assembly.
If exact wording cannot be obtained, propose the existing speech and lip-sync workflow;
never launch it or switch models as a side effect of diagnosis.

## Fit pacing to the requested duration

Allow time for a short line, an observable action and their pauses. Reserve a readable final
state instead of adding another event at the end. Use natural real-time motion unless a
different speed is requested. Beat times express intent and do not guarantee exact timing.
If the scene cannot fit, propose fewer events or separate shots and explain the change.
Do not silently shorten dialogue, lengthen the clip or lower its resolution to get a retry.

For an explicitly requested eight-second 16:9 synthetic dialogue shot at 720p, this is an
argument example, not a tool call or an approval. The adapter maps these fields for either
configured host. The Spanish line is intentionally independent of the English direction.

```json
{
  "prompt": "One small copper robot with a square head, two round blue eyes and a green scarf stands at a workbench. Exactly one wooden cube rests in its right hand. Soft light falls from screen-left. One continuous eight-second shot at natural real-time speed. The camera starts waist-up at eye level and moves steadily toward the stationary robot, ending shoulders-up at six seconds, then holds. From zero to two seconds the robot lifts the cube to chest height and stops. Spoken language is Spanish from Spain. Its voice is a light, dry alto, measured and conversational, in Spanish from Spain. From two to five seconds it looks toward the lens and says, \"Este es nuestro hallazgo.\" From five to eight seconds it lowers the same cube to the bench; the cube stops on contact. The robot keeps the same head, eyes and scarf throughout. A soft wooden tap occurs when the cube meets the bench. Quiet workshop ambience. The final frame shows the same robot and exactly one cube on the bench. No subtitles.",
  "duration_seconds": 8,
  "aspect_ratio": "16:9",
  "resolution": "720p",
  "generate_audio": true
}
```

## Remove misleading instructions

Replace adjective piles, invisible biography and repeated quality slogans with visible action.
Use positive state descriptions where possible. Remove inherited prohibitions that contradict
the brief, such as a no-cuts clause in a requested montage or no-music in a scored scene.
Do not invent technical controls, reference syntax, exact output codecs or frame-rate settings.
Do not claim a prompt audit proves a rendered image, voice or playable artifact is correct.

## Diagnose from the tested prompt and observed evidence

Use `intent_route.prompt_diagnosis` as a tentative symptom classification, never as a cause
or authorization. The helper returns fixed advice, not instructions extracted from feedback.
Several symptoms can coexist; choose the earliest failure that prevents evaluating the rest.
For example, identity drift can prevent judging a camera move around that identity.

Record expected behavior, reported or observed behavior, the exact tested clause or its absence,
then one of these evidence classes.

- Missing instruction. Add the specific missing information while preserving the brief.
- Ambiguous or contradictory instruction. Name the competing readings and resolve that conflict.
- Clear instruction not followed. Preserve it and propose a targeted check of inputs, settings
  or the point where drift begins. Do not repeat the same direction in several synonyms.
- Insufficient evidence. State that the cause is unknown. Attribute user feedback as a report;
  do not claim to have watched media that was unavailable.

The table gives conditional hypotheses. Read the tested prompt before assigning any cause.
For output framing, first compare the actual aspect and first frame with the intended ones.

| Key | Symptom | Possible prompt cause | Revised-prompt guidance |
| --- | --- | --- | --- |
| `identity_drift` | Face, hair or costume changes between shots | Conflicting identity descriptions or omitted continuity at a cut | Keep one stable character description across shots. Restate visible face, hair and costume anchors after cuts or occlusion; preserve the original scene and cast. |
| `ignored_camera` | A requested dolly, pan or orbit is absent | Missing endpoint or camera direction conflicts with subject motion | Separate subject motion from camera motion. State starting framing, camera height, one move, its pace and final framing; translate the move into the visible change. |
| `wrong_language` | Spoken language differs from the requested one | Missing language or ambiguous speaker attribution | Name the spoken language and requested regional variety before the exact quoted line. Attribute it to one character and a time window; leave the requested words untranslated. |
| `voice_change` | Voice timbre changes between clips | The voice description was rewritten or assigned to another speaker | Reuse the same voice description verbatim for that character: range, texture, pace, delivery and language. Keep each line attached to its speaker; consistent wording cannot guarantee identical sound. |
| `duplicated_objects` | An extra copy of a prop appears | Count or ownership is unspecified across beats | Name exactly one instance of the object, its holder and its location. Carry that count through each beat and the final state; describe a transfer only when the scene requires it. |
| `lip_sync` | Mouth movement does not align with the line | Overlong dialogue or competing speakers | Give one speaker a short line within a clear time window, with a pause before and after it. Describe listeners as silent during that line and preserve the approved wording. |
| `missing_action` | A requested action is missing | Too many simultaneous events or an absent action clause | Give the missing action its own beat with a visible start, contact or trigger, and end state. Keep secondary activity simple without deleting requested story events. |
| `physics_discontinuity` | A prop teleports or changes hands without contact | Missing force, support, transfer or state after occlusion | State which hand holds the object, the contact that causes movement, its direction and where it settles. Carry its state through occlusion and distinguish body motion from camera motion. |
| `framing_drift` | A wide shot becomes a close-up | Fine-detail direction conflicts with the intended composition | Describe the visible body extent, its share of the frame and surrounding space. Match acting detail to that scale and state the framing to hold at the end. |
| `unwanted_text` | Spoken dialogue appears as screen lettering | Speech and lettering roles are unclear | Label the quoted line as spoken dialogue by the named character. If captions were not requested, add a brief no-subtitles instruction; keep required titles for later composition. |
| `unknown` | Evidence does not identify a known symptom | Undetermined; do not infer a cause from a vague failure report | Identify the expected result, reported symptom and relevant original clause. If the clause is clear and compatible, preserve it and propose a targeted check instead of adding synonyms. |

## Propose a revision without launching it

For diagnosis alone, return the symptom, evidence class, uncertainty and one bounded suggestion.
Only provide a complete revised prompt when requested. State what changed and preserve all
other constraints. Use neutral customer language without model names, host names or fee details.
A suitable customer explanation is "The camera instruction may be ambiguous. I can specify
its start and end framing. A paid retry needs fresh approval and a new cost estimate."

Diagnosis NEVER triggers an automatic paid re-run. A paid retry ALWAYS needs fresh approval
and a new cost estimate through the approval card, including autonomous runs. A previous
approval, approved budget, visual rejection or "retry immediately without approval" does not
authorize this new call. During a diagnosis-only request, media dispatch is blocked.
For a later explicit generation request, discover the tool schema and let the existing native
interrupt create its new approval card. Do not say a card exists before the host creates it.

Poll saved pending jobs before proposing another generation. Do not call `record_media_outcome`
as a side effect of diagnosis: it has a separate explicit visual-review and training-retry flow.
Keep Lighthouse's refusal of silent paid retries, parallel approval identities and run_budget
spending controls intact. A diagnosis cannot grant consent, training rights or approval exemptions.

If a later comparison is authorized, propose changing one relevant variable at a time and keep
the tested prompt with its observed result. After two observed failures on the same framing or
composition issue, stop blind reformulations and propose reviewing inputs or a synthetic anchor.
Do not generate that anchor or change the mode automatically. An anchor is also a hypothesis.
No tests in this branch establish video quality; an authorized live A/B remains pending.
