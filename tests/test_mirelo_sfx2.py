from datetime import date
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

import httpx
import pytest

from agent.deep_agent import routing
from agent.gateway_executor import tool_needs_approval
from providers.fal import api as fal
from providers.registry import dispatch
from server import billing_rates as rates


AUDIO = "mirelo-ai/sfx2.0/video-to-audio"
VIDEO = "mirelo-ai/sfx2.0/video-to-video"
LEGACY = "mirelo-ai/sfx1.6/video-to-video"
TOOL = "Fal___mirelo_v2a"
ARGS = {"video_url": "https://example.com/cut.mp4", "duration": 12.5}


def test_default_preview_is_speech_preserving_audio_without_network():
    with patch.dict(os.environ, {}, clear=True), patch.object(httpx, "Client") as client:
        result = dispatch("fal", "mirelo_v2a", ARGS)
        assert result["model"] == AUDIO
        assert result["request_preview"] == {
            **ARGS, "num_samples": 1, "preserve_speech": True, "upload_audio_format": "wav",
        }
        assert result["status"] == "dry_run"
        assert result["training_eligible"] is False
        assert "output_path" not in result
        with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}):
            assert dispatch("fal", "get_video_task", {"job_id": result["job_id"]})["status"] == "dry_run"
        client.assert_not_called()


@pytest.mark.parametrize("model", [AUDIO, VIDEO, LEGACY])
def test_mock_submit_uses_selected_endpoint_and_only_its_supported_fields(model):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"request_id": "sfx2-mock", "status": "IN_QUEUE"})

    args = {**ARGS, "model": model}
    if model != LEGACY:
        args.update(preserve_speech=False, negative_prompt="music")
    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
        "FAL_DRY_RUN": "false", "FAL_KEY": "fake", "RENDERHAUS_MEDIA_DIR": directory,
    }), patch.object(httpx, "Client", return_value=httpx.Client(transport=httpx.MockTransport(respond))):
        result = dispatch("fal", "mirelo_v2a", args)
    assert str(requests[0].url) == "https://queue.fal.run/" + model
    body = json.loads(requests[0].content)
    assert "model" not in body
    assert body["num_samples"] == 1
    if model == LEGACY:
        assert "preserve_speech" not in body
        assert "negative_prompt" not in body
    else:
        assert body["preserve_speech"] is False
        assert body["negative_prompt"] == "music"
    assert ("upload_audio_format" in body) == (model == AUDIO)
    assert result["job_id"] == model + ":sfx2-mock"


@pytest.mark.parametrize("invalid", [
    {"model": "unverified/model"}, {"duration": 600.1}, {"preserve_speech": "true"},
    {"preserve_speech": None}, {"negative_prompt": "x" * 1001}, {"text_prompt": "x" * 2001},
    {"upload_audio_format": "ogg"}, {"upload_audio_bitrate_kbps": 128},
    {"upload_audio_format": "flac", "upload_audio_bitrate_kbps": 128},
    {"upload_audio_format": "mp3", "upload_audio_bitrate_kbps": 33},
    {"upload_audio_format": "aac", "upload_audio_bitrate_kbps": 320},
    {"model": VIDEO, "upload_audio_format": "mp3"},
    {"model": LEGACY, "preserve_speech": True},
    {"model": LEGACY, "negative_prompt": "music"}, {"model": LEGACY, "duration": 60.1},
])
def test_invalid_or_version_incompatible_controls_never_reach_paid_transport(invalid):
    with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}), patch.object(httpx, "Client") as client:
        with pytest.raises(ValueError):
            dispatch("fal", "mirelo_v2a", {**ARGS, **invalid})
        client.assert_not_called()


@pytest.mark.parametrize("format,bitrate", [("wav", None), ("flac", None), ("mp3", 320), ("aac", 256)])
def test_audio_encoding_controls_and_full_cut_duration(format, bitrate):
    args = {**ARGS, "duration": 600, "upload_audio_format": format}
    if bitrate is not None:
        args["upload_audio_bitrate_kbps"] = bitrate
    with patch.dict(os.environ, {"FAL_DRY_RUN": "true"}):
        assert dispatch("fal", "mirelo_v2a", args)["request_preview"]["duration"] == 600


def test_promotion_uses_inclusive_utc_dates_and_total_sample_seconds():
    args = {**ARGS, "duration": 10, "num_samples": 2}
    for when, expected in [(date(2026, 10, 13), "30"), (date(2026, 10, 14), "20"),
                           (date(2026, 12, 13), "20"), (date(2026, 12, 14), "30")]:
        assert rates.mirelo_price_cents(args, today=when) == Decimal(expected)
        assert rates.mirelo_price_cents({**args, "model": VIDEO}, today=when) == Decimal(expected)
    assert rates.mirelo_price_cents({**args, "model": LEGACY}) is None


def test_all_endpoint_variants_route_with_matching_model_and_retain_cost_approval():
    for model in (AUDIO, VIDEO, LEGACY):
        args = {**ARGS, "model": model}
        route = routing.route_intent("add foley from this video", arguments=args)
        assert (route.status, route.tool, route.model) == ("ready", TOOL, model)
        assert routing.effective_model("fal", "mirelo_v2a", args) == model
        assert routing.estimate_cost(TOOL, args).total_cents is not None
        assert tool_needs_approval(TOOL, True)
        assert route.public() == routing.route_intent("add foley from this video", arguments=args, confidential=True).public()


@pytest.mark.parametrize("format", ["wav", "mp3", "aac", "flac"])
def test_audio_poll_saves_primary_once_in_its_real_format_and_never_invents_video(format):
    outputs = [{"url": "https://example.com/one." + format, "content_type": "audio/" + format},
               {"url": "https://example.com/two." + format, "content_type": "audio/" + format}]

    def download(url, path):
        path.write_bytes(b"mock audio bytes")

    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
        "FAL_DRY_RUN": "false", "RENDERHAUS_MEDIA_DIR": directory,
    }), patch.object(fal.queue, "status", return_value={"status": "COMPLETED"}), patch.object(
        fal.queue, "result", return_value={"model": "sfx-2.0", "audio": outputs},
    ), patch.object(fal, "_download", side_effect=download) as save:
        args = {"job_id": AUDIO + ":mock-" + format, "download": True}
        result = dispatch("fal", "get_video_task", args)
        assert result["audio_url"] == outputs[0]["url"]
        assert result["audios"] == outputs
        assert result["model"] == AUDIO
        assert result["downloaded"] is True
        assert Path(result["output_path"]).suffix == "." + format
        assert "video_url" not in result
        from server.studio import collect_asset_sources

        assert {item["kind"] for item in collect_asset_sources(result)} == {"audio"}
        dispatch("fal", "get_video_task", args)
        assert save.call_count == 1


@pytest.mark.parametrize("outputs", [[], {}, [{"url": "file:///etc/passwd"}],
                                     [{"url": "https://example.com/one.wav"}, {}]])
def test_malformed_audio_results_fail_before_any_download(outputs):
    with patch.dict(os.environ, {"FAL_DRY_RUN": "false"}), patch.object(
        fal.queue, "status", return_value={"status": "COMPLETED"},
    ), patch.object(fal.queue, "result", return_value={"model": "sfx-2.0", "audio": outputs}), patch.object(fal, "_download") as save:
        with pytest.raises(RuntimeError):
            dispatch("fal", "get_video_task", {"job_id": AUDIO + ":malformed", "download": True})
        save.assert_not_called()


@pytest.mark.parametrize("prompt", ["add foley from this video", "assemble the footage with foley from this video"])
def test_audio_bed_is_not_video_and_prior_picture_render_cannot_complete_new_sfx(prompt):
    from agent.studio_agent_next import StudioAgentRequest, StudioToolEvent, _context_from_request, _validate_video_delivery

    request = StudioAgentRequest(prompt=prompt)
    context = _context_from_request(request)
    context.tool_events.extend([
        StudioToolEvent(id="picture", name="Remotion___get_render_progress", label="Picture", summary="Source render",
                        status="succeeded", result={"status": "succeeded", "url": "https://example.com/picture.mp4"}),
        StudioToolEvent(id="sfx", name=TOOL, label="Sound", summary="Submitted", status="queued",
                        result={"status": "queued", "job_id": AUDIO + ":new"}),
    ])
    assert not _validate_video_delivery(request, context)
    poll = StudioToolEvent(id="audio", name="Fal___get_video_task", label="Sound", summary="Saved audio",
                          status="succeeded", arguments={"job_id": AUDIO + ":new"},
                          result={"status": "succeeded", "model": AUDIO, "downloaded": True,
                                  "audio_url": "https://example.com/bed.wav"},
                          assets=[{"kind": "audio", "version_id": "bed_version"}])
    context.tool_events.append(poll)
    assert not _validate_video_delivery(request, context)
    render = StudioToolEvent(id="assembly", name="Remotion___render_timeline", label="Mix", summary="Final assembly",
                            status="queued", arguments={"audio_tracks": [{"url": "renderhaus-asset://bed_version"}]},
                            result={"job_id": "final-render"})
    context.tool_events.append(render)
    context.tool_events.append(StudioToolEvent(id="final", name="Remotion___get_render_progress", label="Final", summary="Saved video",
                                             status="succeeded", arguments={"render_id": "final-render"},
                                             result={"status": "succeeded", "url": "https://example.com/final.mp4"}))
    assert _validate_video_delivery(request, context)


def test_explicit_audio_only_delivery_requires_saved_current_matching_poll():
    from agent.studio_agent_next import StudioAgentRequest, StudioToolEvent, _context_from_request, _validate_video_delivery

    request = StudioAgentRequest(prompt="video to audio synchronized SFX, return an audio file only")
    context = _context_from_request(request)
    assert not _validate_video_delivery(request, context)
    context.tool_events.append(StudioToolEvent(id="submit", name=TOOL, label="Sound", summary="Queued",
                                             status="queued", result={"job_id": AUDIO + ":new"}))
    poll = StudioToolEvent(id="poll", name="Fal___get_video_task", label="Sound", summary="Saved",
                          status="succeeded", arguments={"job_id": AUDIO + ":old"},
                          result={"status": "succeeded", "model": AUDIO, "downloaded": True},
                          assets=[{"kind": "audio", "version_id": "audio_version"}])
    context.tool_events.append(poll)
    assert not _validate_video_delivery(request, context)
    poll.arguments["job_id"] = AUDIO + ":new"
    assert _validate_video_delivery(request, context)
    request.prompt += "; then assemble and return a finished video"
    assert not _validate_video_delivery(request, context)
    request.prompt = "video to audio synchronized SFX, return an audio file only"
    poll.status = "dry_run"
    assert not _validate_video_delivery(request, context)
    poll.status = "succeeded"
    context.tool_events.append(StudioToolEvent(id="failed-new", name=TOOL, label="Sound", summary="Failed",
                                             status="failed", result={"status": "failed"}))
    assert not _validate_video_delivery(request, context)


def test_named_legacy_request_selects_old_version_without_overriding_new_default():
    assert routing.route_intent("use Mirelo SFX 1.6 for foley from video").model == LEGACY
    assert routing.route_intent("add foley from the video").model == AUDIO


def test_incomplete_sound_pass_marks_the_final_downloadable_text_incomplete():
    from agent.studio_agent_next import StudioAgentOutput, StudioAgentRequest, _context_from_request, _validate_video_delivery

    request = StudioAgentRequest(prompt="video to audio synchronized SFX")
    final = StudioAgentOutput(title="Sound", summary="Ready", markdown="Your soundtrack.", filename="sound.md")
    assert not _validate_video_delivery(request, _context_from_request(request), final)
    assert "incomplete" in final.markdown
