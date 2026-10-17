from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.deep_agent.routing import (
    capability_constraints, filter_request_tools, intent_constraints,
    request_tool_blocker, route_intent, select_provider,
)
from agent.gateway_executor import tool_needs_approval


TEACH = "Make an onboarding video of this repo explaining how request flow works with real code."
PROGRESS = "Make a progress video of what shipped in this repository since v1.2."
ROOT = Path(__file__).resolve().parents[1]
GENERATION = {
    "Fal___generate_wan3_t2v", "Fal___generate_wan3_i2v", "Fal___generate_wan3_r2v",
    "Seedance___text_to_video", "Seedance___image_to_video", "Seedance___reference_to_video",
    "OpenAI___generate_image", "OpenAI___edit_image",

}


@pytest.mark.parametrize("prompt,kind", [
    (TEACH, "teach"), (PROGRESS, "progress"),
    ("Use codebase-video to teach /work/project", "teach"),
    ("Use codebase-video to teach how OpenAI requests flow through this repo.", "teach"),
    ("Make a codebase video of this repo. Use ElevenLabs for narration about OpenAI requests.", "teach"),
    ("Turn this codebase into a narrated teaching video with module diagrams", "teach"),
    ("Video walkthrough of how this repository works", "teach"),
    ("Video of what changed in the repo since last Monday", "progress"),
    ("Do not upload this repository, make an onboarding video explaining the request flow.", "teach"),
    (TEACH + " Use ElevenLabs for narration.", "teach"),
    (TEACH + " Do not use HyperFrames.", "teach"),
    (TEACH + " No HyperFrames.", "teach"),
    (TEACH + ", without HyperFrames.", "teach"),
    ("Progress video of what shipped since v1.2 in this repo.", "progress"),
    ("Make an onboarding video of this repo explaining how OpenAI requests flow through the gateway.", "teach"),
    ("Make an onboarding video of this repo explaining how the Kling API works.", "teach"),
])
def test_local_repository_workflow_precedes_speech_and_generic_video(prompt, kind):
    with patch.dict("os.environ", {"REMOTION_RENDER_BACKEND": "local"}):
        route = route_intent(prompt)
    assert route.skill == "codebase-video"
    assert route.status == "ready"
    assert route.alias == "remotion_render"
    assert route.tool == "Remotion___render_timeline"
    assert route.required["codebase_kind"] == kind
    assert route.required["repository_evidence"] is True
    assert route.required["fresh_agent_audit"] is True
    assert route.required["local_render"] is True
    assert not route.steps


@pytest.mark.parametrize("backend", ["lambda", "local"])
def test_local_requirement_applies_at_discovery_and_dispatch(backend):
    with patch.dict("os.environ", {"REMOTION_RENDER_BACKEND": backend}):
        route = route_intent(TEACH)
        blocker = request_tool_blocker(TEACH, "Remotion___render_timeline")
        assert bool(blocker) == (backend != "local")
        assert route.status == ("blocked" if blocker else "ready")
        if blocker:
            assert route.tool is None
            assert "local" in route.reason


def test_code_cards_never_use_image_or_video_generation_even_when_named():
    for prompt in (TEACH, PROGRESS, "Use Wan to generate code cards for a codebase-video"):
        with patch.dict("os.environ", {"REMOTION_RENDER_BACKEND": "local"}):
            allowed = {"Remotion___render_timeline", "Remotion___get_render_progress",
                       "ElevenLabs___text_to_speech_convert", "Ffmpeg___ffmpeg_tool"}
            assert filter_request_tools(prompt, GENERATION | allowed) == allowed
            for name in GENERATION:
                assert "code" in request_tool_blocker(prompt, name).lower()
    with patch.dict("os.environ", {"REMOTION_RENDER_BACKEND": "local"}):
        route = route_intent("Use Wan to generate code cards for a codebase-video")
    assert route.skill == "codebase-video"
    assert route.status == "blocked"
    assert route.tool is None


@pytest.mark.parametrize("prompt,skill", [


    ("Make a whiteboard video explaining sorting algorithms with narration", "whiteboard-explainer"),
    ("Make a silent science explainer video", "knowledge-explainer"),
    ('Make a video of a forest; title it "codebase-video".', "t2v"),
    ("Make a video of a forest. My repo onboarding tutorial already exists.", "t2v"),
    ("Make a video of a forest. Do not make a codebase video.", "t2v"),
    ("Explain how this repository works", None),
])
def test_adjacent_intents_do_not_select_codebase_video(prompt, skill):
    route = route_intent(prompt)
    assert route.skill == skill
    assert request_tool_blocker(prompt, "Fal___generate_wan3_t2v") is None


def test_existing_render_and_voice_approval_rules_are_preserved():
    assert tool_needs_approval("Remotion___render_timeline", False)
    assert tool_needs_approval("Remotion___render_timeline", True)
    assert tool_needs_approval("ElevenLabs___text_to_speech_convert", False)
    assert not tool_needs_approval("ElevenLabs___text_to_speech_convert", True)


@pytest.mark.parametrize("subject", ["OpenAI requests", "Kling Turbo API calls"])
def test_repository_subject_does_not_select_the_narration_provider(subject):
    prompt = f"Make an onboarding video of this repo explaining how {subject} flow through the gateway."
    route = select_provider("tts", **capability_constraints(intent_constraints(prompt), "tts"))
    assert route.status == "ready"
    assert route.alias == "eleven_v4_turbo"
    assert route.tool == "ElevenLabs___text_to_speech_convert"


def test_explicit_skill_invocation_is_not_a_narration_provider_selection():
    prompt = "Use codebase-video to teach how OpenAI requests flow through this repo."
    route = select_provider("tts", **capability_constraints(intent_constraints(prompt), "tts"))
    assert route.status == "ready"
    assert route.alias == "eleven_v4_turbo"


def test_radar_rows_are_present_and_active():
    rows = json.loads((ROOT / "tests/fixtures/skill_routing.json").read_text())
    for row_id, prompt in (("RT-191", TEACH), ("RT-192", PROGRESS)):
        matches = [row for row in rows if row.get("test_id") == row_id]
        assert len(matches) == 1
        row = matches[0]
        assert row["prompt"] == prompt
        assert not row["skip_reason"]
        assert row["expected_skill"] == "codebase-video"
        assert row["expected_tool"] == "remotion_render"
        assert "wan3_t2v" in row["forbidden_tools"]
