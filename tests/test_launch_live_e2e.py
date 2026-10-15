"""Regressions from the first recorded live e2e run on staging 0ea7f38 (no live calls)."""
from __future__ import annotations

import json

import pytest

from agent.gateway_executor import GatewayExecutor, stage_outputs_in_job
from agent.studio_agent_next import StudioAgentRequest, _context_from_request

LIVE_PROMPT = (
    'Make a 10-second product film for "Ember", a matte-black insulated travel mug. 3 shots, 16:9:\n'
    "1) Slow push-in hero shot of the mug on a wooden café counter at golden hour, steam rising.\n"
    "2) Close-up of a hand flipping the lid open, warm backlight.\n"
    '3) The mug in a backpack side pocket on a misty mountain trail at sunrise, logo text "Ember — keeps it hot for 12 hours".\n'
    'Short warm voiceover: "Ember. Your coffee, still hot at the summit."\n'
    "Keep it within budget: one generation per shot, no retries."
)
HERO = ("Cinematic product hero shot: a matte-black insulated travel mug with a closed lid stands on a worn wooden "
        "café counter at golden hour. Slow, smooth push-in camera move toward the mug.")
# Exact argument shapes the agent sent in the live run; every one came back not_run.
LIVE_CALLS = [
    {"prompt": HERO, "resolution": "720p", "aspect_ratio": "16:9", "duration": 4, "audio": False},
    {"prompt": "Close-up of a hand flipping open the lid.", "resolution": "720p", "aspect_ratio": "16:9", "duration": 3, "audio": False},
    {"prompt": "Mug in a backpack pocket on a misty trail.", "resolution": "720p", "aspect_ratio": "16:9", "duration": 3, "audio": False},
    {"prompt": HERO, "duration": 4, "resolution": "720p", "aspect_ratio": "16:9", "audio": False},
    {"prompt": HERO, "duration": 5},
]


def _executor(prompt=LIVE_PROMPT):
    return GatewayExecutor(_context_from_request(StudioAgentRequest(prompt=prompt, job_id="live-e2e")), [])


@pytest.mark.parametrize("arguments", LIVE_CALLS)
def test_live_wan_shot_calls_pass_selection(arguments):
    executor = _executor()
    route = executor.media_selection("Fal___generate_wan3_t2v", arguments)
    assert route.tool == "Fal___generate_wan3_t2v"  # quoted product name is not dialogue
    assert "duration_seconds" not in route.required  # 10 s is the film, not each shot
    assert executor.selection_blocker("Fal___generate_wan3_t2v", arguments, route) is None


def test_shot_longer_than_whole_film_is_still_refused():
    executor = _executor()
    arguments = {"prompt": HERO, "duration": 12}
    route = executor.media_selection("Fal___generate_wan3_t2v", arguments)
    assert "fit inside the 10-second film" in executor.selection_blocker("Fal___generate_wan3_t2v", arguments, route)


def test_single_clip_duration_is_still_enforced():
    executor = _executor("Make a 6-second video of a mug on a counter, 16:9.")
    arguments = {"prompt": HERO, "duration": 4}
    route = executor.media_selection("Fal___generate_wan3_t2v", arguments)
    assert route.required.get("duration_seconds") == 6
    assert executor.selection_blocker("Fal___generate_wan3_t2v", arguments, route)
    ok = {"prompt": HERO, "duration": 6}
    assert executor.selection_blocker("Fal___generate_wan3_t2v", ok, executor.media_selection("Fal___generate_wan3_t2v", ok)) is None


LIVE_FINAL = """# Ember: 10-second product film (16:9)

**Status: incomplete.** The voiceover was generated.

| Item | Result |
|---|---|
| Voiceover | Generated with ElevenLabs `eleven_v4_turbo` (default route), voice "George". Saved at `/workspace/rh-runs/e2e-live/media/elevenlabs/9a42.mp3`. |
| Video shots 1–3 | **Not generated.** |
| Remotion assembly | **Not run.** |

I dispatched each shot to `Fal___generate_wan3_t2v` (Wan 3 text-to-video). Seedance is reserved for dialogue.
The shots are planned at 4 s, 3 s and 3 s.

## Estimated media costs

- ElevenLabs___text_to_speech_convert (eleven_v4_turbo): $0.02 USD.

Estimated media cost $0.02 USD.
Recorded estimates include platform fees. Model token costs are separate."""

FORBIDDEN = ["elevenlabs", "eleven_v4", "wan", "seedance", "remotion", "fal", "___", "/workspace", "rh-runs",
             "platform fee", "token cost", "model token"]


def test_public_execution_scrubs_provider_model_path_and_fee_text():
    from server.run_billing import public_execution

    execution = {
        "message": "Completed Ember Film.",
        "result": {"title": "Ember Film", "summary": "Incomplete. Wan 3 refused every shot. The voiceover is saved.",
                   "markdown": LIVE_FINAL, "assets": [{"output_path": "/workspace/rh-runs/e2e-live/media/x.mp3"}]},
        "events": [
            {"id": "a", "title": "ElevenLabs text to speech convert · Estimated cost $0.02 USD",
             "message": "Review the arguments before ElevenLabs text to speech convert runs.",
             "tool_call_name": "ElevenLabs___text_to_speech_convert"},
            {"id": "b", "title": "Provider choice", "message": "Selected eleven_v4_turbo. Provider elevenlabs."},
        ],
        "tool_calls": [],
    }
    view = public_execution(execution)
    # Displayed text only; machine ids in tool_call_name/name stay for canvas logic and are never rendered.
    shown = json.dumps([view["message"], view["result"], [(e["title"], e["message"]) for e in view["events"]]]).lower()
    for word in FORBIDDEN:
        assert word not in shown, word
    markdown = public_execution(execution)["result"]["markdown"]
    assert "Video shots 1–3" in markdown and "4 s, 3 s and 3 s" in markdown and "$0.02" in markdown


def test_cost_section_names_work_not_tools():
    from agent.deep_agent.costs import append_media_costs
    from agent.studio_agent_next import StudioAgentOutput

    out = StudioAgentOutput(title="Ember", summary="Done.", markdown="# Ember", filename="ember.md")
    append_media_costs(out, {"c": {"request_id": "s", "tool": "ElevenLabs___text_to_speech_convert", "provider": "elevenlabs",
                                   "model": "eleven_v4_turbo", "status": "succeeded", "provider_cost_estimate_cents": 1,
                                   "fee_estimate_cents": 1, "total_estimate_cents": 2, "currency": "USD"}}, "s")
    text = (out.markdown + out.summary).lower()
    assert "voiceover" in text
    for word in ["elevenlabs", "eleven_v4", "___", "fee", "token"]:
        assert word not in text


def test_orchestration_line_is_work_not_fee():
    from server import run_budget as rb

    lines = rb.lines_from_rows([{"kind": "orchestration", "cents": 75, "label": "", "detail": None, "refunded_at": None}])
    assert lines[0]["label"] == "Planning and checks"
    assert not rb._DENY_RE.search(lines[0]["label"])


def test_incomplete_film_is_not_delivered():
    from server.studio import _deliverable_missing

    assert _deliverable_missing(LIVE_PROMPT, {"title": "Ember Film: Blocked at Video Generation",
                                              "summary": "Incomplete.", "assets": [{"kind": "audio"}]})
    assert _deliverable_missing(LIVE_PROMPT, {"title": "Ember", "summary": "Here it is.", "assets": [{"kind": "audio"}]})
    assert not _deliverable_missing(LIVE_PROMPT, {"title": "Ember", "summary": "Here it is.", "assets": [{"kind": "video"}]})


def test_prepaid_credit_is_metered_without_beta_or_stripe(monkeypatch, tmp_path):
    """Live run: $5 granted directly, Stripe off, no beta grant row -> paid steps ran free."""
    from server import beta_credits

    class Repo:
        def get_beta_credit(self, user_id):
            return None

        def get_balance(self, user_id):
            return 500

    monkeypatch.delenv("BETA_INVITE_ONLY", raising=False)
    monkeypatch.setattr(beta_credits.BetaSettings, "from_env", classmethod(lambda cls: type("S", (), {"enabled": False})()))
    assert beta_credits.beta_billing_enabled(Repo(), "local")
    Repo.get_balance = lambda self, user_id: 0
    assert not beta_credits.beta_billing_enabled(Repo(), "local")
    monkeypatch.setenv("BETA_INVITE_ONLY", "true")
    assert beta_credits.beta_billing_enabled(Repo(), "local")


def test_provider_media_is_staged_inside_the_job(monkeypatch, tmp_path):
    from providers.ffmpeg.sandbox import job_directory, validate_input_path

    monkeypatch.setenv("RENDERHAUS_MEDIA_DIR", str(tmp_path))
    (tmp_path / "elevenlabs").mkdir()
    voice = tmp_path / "elevenlabs" / "9a42.mp3"
    voice.write_bytes(b"ID3" + b"\0" * 64)
    payload = {"status": "succeeded", "result": {"output_path": str(voice), "filename": "9a42.mp3"}}
    staged = stage_outputs_in_job("live-e2e", payload)
    path = staged["result"]["output_path"]
    assert path != str(voice)
    assert validate_input_path(job_directory("live-e2e"), path).read_bytes() == voice.read_bytes()
    outside = {"status": "succeeded", "output_path": "/etc/hosts"}
    assert stage_outputs_in_job("live-e2e", outside) == outside
