"""Prompt hypotheses adapted from MMMProd's MIT guide, not verified API behavior.

See skills/t2v/references/NOTICE for source, revision and licence. Results are
fixed advice only; caller feedback is never copied into an executable action.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


RETRY_NOTICE = (
    'Diagnosis only proposes prompt changes. A paid retry needs fresh approval '
    'and a new cost estimate through the approval card, including in autonomous runs.'
)


@dataclass(frozen=True)
class Diagnosis:
    key: str
    suggestion: str
    rewrite_guidance: str


_RULES = (
    (r'identity.{0,20}drift|face.{0,30}(?:chang|drift)|(?:chang|swap).{0,30}face|character.{0,20}drift', Diagnosis(
        'identity_drift',
        'Identity descriptions may conflict or omit continuity at a cut. Check the tested prompt before assigning a cause.',
        'Keep one stable character description across shots. Restate visible face, hair and costume anchors after cuts or occlusion; preserve the original scene and cast.',
    )),
    (r'ignor.{0,40}(?:camera|dolly|push|pan|orbit|truck)|camera.{0,30}(?:ignor|static|did not move|didn.t move)', Diagnosis(
        'ignored_camera',
        'The camera path may lack an endpoint or conflict with subject motion. A clear instruction can also go unfollowed.',
        'Separate subject motion from camera motion. State starting framing, camera height, one move, its pace and final framing; translate the move into the visible change.',
    )),
    (r'wrong language|(?:language|accent).{0,25}(?:wrong|incorrect)|spoke.{0,30}instead of', Diagnosis(
        'wrong_language',
        'The spoken language or speaker may be unspecified. Check the actual line and audio before proposing a rewrite.',
        'Name the spoken language and requested regional variety before the exact quoted line. Attribute it to one character and a time window; leave the requested words untranslated.',
    )),
    (r'voice.{0,35}(?:chang|drift|different)|timbre.{0,25}(?:chang|different)|(?:chang|different).{0,25}voice', Diagnosis(
        'voice_change',
        'Voice descriptions may have changed between clips. The cause remains uncertain if the same description was already used.',
        'Reuse the same voice description verbatim for that character: range, texture, pace, delivery and language. Keep each line attached to its speaker; consistent wording cannot guarantee identical sound.',
    )),
    (r'duplicat|(?:two|multiple|extra).{0,25}(?:objects?|mugs?|cups?|props?)', Diagnosis(
        'duplicated_objects',
        'Object count or ownership may be ambiguous across beats. Verify the original description rather than assuming an omission.',
        'Name exactly one instance of the object, its holder and its location. Carry that count through each beat and the final state; describe a transfer only when the scene requires it.',
    )),
    (r'lip.{0,25}(?:sync|align|late)|mouth.{0,25}(?:speech|audio|dialogue)', Diagnosis(
        'lip_sync',
        'A long line or competing speakers may overload the shot. Compare the line timing with the observed mouth movement.',
        'Give one speaker a short line within a clear time window, with a pause before and after it. Describe listeners as silent during that line and preserve the approved wording.',
    )),
    (r'action.{0,25}(?:missing|absent|ignor)|(?:missing|absent|ignor).{0,25}action', Diagnosis(
        'missing_action',
        'Several simultaneous actions may compete, or a requested action may be absent from the text. Check the tested clause.',
        'Give the missing action its own beat with a visible start, contact or trigger, and end state. Keep secondary activity simple without deleting requested story events.',
    )),
    (r'teleport|chang.{0,15}hands?|float.{0,20}(?:object|cup)|(?:physics|motion).{0,20}(?:wrong|impossible)', Diagnosis(
        'physics_discontinuity',
        'The force, contact or carried object state may be unclear. A visible discontinuity alone does not establish its cause.',
        'State which hand holds the object, the contact that causes movement, its direction and where it settles. Carry its state through occlusion and distinguish body motion from camera motion.',
    )),
    (r'wide.{0,35}(?:tight|close|cropp)|fram.{0,20}(?:drift|wrong)|full.body.{0,20}cropp', Diagnosis(
        'framing_drift',
        'Fine facial detail may conflict with a wide composition. Check the requested aspect and the first visible frame as well.',
        'Describe the visible body extent, its share of the frame and surrounding space. Match acting detail to that scale and state the framing to hold at the end.',
    )),
    (r'unwanted.{0,20}(?:text|subtitles?|captions?)|subtitles?.{0,25}(?:appear|unwanted)|dialogue.{0,25}on.screen', Diagnosis(
        'unwanted_text',
        'Dialogue may be confused with screen lettering. Check whether on-screen text was requested before changing it.',
        'Label the quoted line as spoken dialogue by the named character. If captions were not requested, add a brief no-subtitles instruction; keep required titles for later composition.',
    )),
)
_UNKNOWN = Diagnosis(
    'unknown',
    'The cause is unknown. Compare the tested prompt and accepted settings with the reported result before changing anything.',
    'Identify the expected result, reported symptom and relevant original clause. If the clause is clear and compatible, preserve it and propose a targeted check instead of adding synonyms.',
)


def diagnose_failure(description: str) -> Diagnosis:
    """Return a fixed prompt hypothesis, never a tool call or authorization."""
    return next((diagnosis for pattern, diagnosis in _RULES
                 if re.search(pattern, description, re.I)), _UNKNOWN)


def diagnosis_request(prompt: str) -> bool:
    """Recognize explicit feedback or prompt repair, excluding new media work."""
    if not re.search(r'\bseedance\b(?!\s+1\.5)', prompt, re.I):
        return False
    instructions = re.sub(
        r"\b(?:do not|don't|never)\s+(?:generate|create|make|animate|render|produce|edit|extend|restyle|relight|trim|continue|regenerate|rerender)\b[^.;!?\n]*",
        '', prompt, flags=re.I,
    )
    media_action = r'(?:generate|create|make|animate|produce|regenerate|rerender|edit|extend|restyle|relight|trim|continue)'
    media_noun = r'(?:videos?|shots?|clips?|footage|films?|animations?|logos?)'
    if re.search(
        rf'\b{media_action}\b[^.;!?\n]{{0,80}}\b{media_noun}\b|'
        rf'\b{media_action}\s+(?:it|them|this|that|again)\b|'
        r'\brender\s+(?:it|them|a|an|the|this|that|new|another|again|my|our|your|supplied|attached|uploaded|existing)\b|'
        rf'\buse\s+seedance(?:\s+2\.5)?\s+for\b(?:(?!\b(?:prompt|wording|diagnosis|advice)\b)[^.;!?\n]){{0,80}}\b{media_noun}\b',
        instructions, re.I,
    ):
        return False
    prompt_repair = re.search(
        r'\b(?:fix|rewrite|revise|improve|repair|diagnose)\b[^.;!?]*\b(?:prompt|wording)\b|'
        r'\b(?:prompt|wording)\b[^.;!?]*\b(?:fix|rewrite|revise|improve|repair)\b', prompt, re.I,
    )
    if prompt_repair:
        return True
    feedback = re.search(
        r'(?:^|[.;!?\n])\s*(?:my|our|the|this|that|last|previous)\s+'
        r'(?:seedance(?:\s+2\.5)?\s+)?(?:render|clip|shot|video|result|voice)\b', prompt, re.I,
    )
    named_media = re.search(r'\bseedance(?:\s+2\.5)?\s+(?:render|clip|shot|video|result|voice)\b', prompt, re.I)
    failure = re.search(r'\b(?:drift(?:ed|s)?|ignor(?:ed|es)|chang(?:ed|es)|duplicat(?:ed|es|ion)|failed|wrong|missing|unwanted|teleported)\b', prompt, re.I)
    return bool(feedback and diagnose_failure(prompt).key != 'unknown'
                or (feedback or named_media) and (failure or re.search(r'\bdiagnos(?:e|is)\b', prompt, re.I)))
