from __future__ import annotations

import base64
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

from PIL import Image
import pytest


def core():
    assert importlib.util.find_spec("providers.reference_shots"), (
        "The measured reference-shot provider must exist."
    )
    return importlib.import_module("providers.reference_shots.api")


def labels(camera_move="static", shot_ids=(1, 2, 3)):
    return [dict(shot_id=i, shot_size="wide", category="scene", camera_move=camera_move,
                 frame_description="A solid colour field.", rhythm_role="build") for i in shot_ids]


@pytest.fixture(scope="module")
def films(tmp_path_factory):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Real local ffmpeg and ffprobe are required.")
    directory = tmp_path_factory.mktemp("reference-fixtures")
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error"]
    for colour, duration in (("red", 1), ("blue", 2), ("red", 1)):
        command += ["-f", "lavfi", "-i", f"color=c={colour}:s=160x90:r=12:d={duration}"]
    subprocess.run([*command, "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
                    "-map", "[v]", "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(directory / "cuts.mp4")],
                   check=True, capture_output=True, timeout=30)
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-f", "lavfi",
                    "-i", "testsrc2=s=160x90:r=12:d=2", "-c:v", "libx264", "-threads", "1",
                    "-pix_fmt", "yuv420p", str(directory / "moving.mp4")],
                   check=True, capture_output=True, timeout=30)
    return directory


@pytest.fixture
def job(tmp_path, monkeypatch, films):
    directory = tmp_path / "media" / "job"
    directory.mkdir(parents=True)
    shutil.copyfile(films / "cuts.mp4", directory / "cuts.mp4")
    shutil.copyfile(films / "moving.mp4", directory / "moving.mp4")
    monkeypatch.setenv("RENDERHAUS_MEDIA_DIR", str(directory.parent))
    monkeypatch.setenv("REFERENCE_SHOTS_DRY_RUN", "false")
    monkeypatch.setenv("GEMINI_DRY_RUN", "true")
    return directory


def measure(job, source="cuts.mp4"):
    result = core().shot_breakdown("measure", "job", source)
    assert result["ok"], result
    return result


def report(measured, values=None, **params):
    return core().shot_breakdown("report", "job", measured["analysis_path"],
                                 {"labels": labels() if values is None else values,
                                  "measurements_sha256": measured["measurements_sha256"], **params})


def test_dry_run_validates_without_reading_or_inventing_measurements(tmp_path, monkeypatch):
    monkeypatch.setenv("RENDERHAUS_MEDIA_DIR", str(tmp_path))
    monkeypatch.delenv("REFERENCE_SHOTS_DRY_RUN", raising=False)
    result = core().shot_breakdown("measure", "missing-job", "absent.mp4")
    assert result["ok"] and result["status"] == "dry_run"
    assert result["outputs"] == []
    assert "shots" not in result and "analysis_path" not in result
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("change", [
    {"op": "shell"}, {"job_id": "../job"}, {"input_path": "../source.mp4"},
    {"input_path": "https://example.org/video.mp4"}, {"input_path": "-i"},
    {"params": {"duration": 4}}, {"params": {"threshold": .1}}, {"unknown": True},
    {"job_id": 3}, {"input_path": "source.mp4\n"},
])
def test_invalid_contract_is_rejected_before_media_access(change):
    arguments = {"op": "measure", "job_id": "job", "input_path": "source.mp4", **change}
    with pytest.raises(ValueError):
        core().validate_arguments(arguments)


def test_owned_asset_handle_is_lexically_valid_but_requires_host_staging(job):
    arguments = {"op": "measure", "job_id": "job", "input_path": "renderhaus-asset://asset_123"}
    core().validate_arguments(arguments)
    result = core().shot_breakdown(**arguments)
    assert not result["ok"] and "stag" in result["error"].lower()


def test_known_cuts_are_measured_and_cut_jumps_do_not_become_motion(job):
    result = measure(job)
    assert result["status"] == "measured"
    manifest = json.loads(Path(result["analysis_path"]).read_text())
    assert manifest["source"]["duration_s"] == pytest.approx(4)
    assert [(shot["start_s"], shot["end_s"], shot["duration_s"]) for shot in manifest["shots"]] == [
        (0, 1, 1), (1, 3, 2), (3, 4, 1)]
    assert all(shot["median_frame_difference"] < .001 for shot in manifest["shots"])
    assert [shot["frame_times_s"] for shot in manifest["shots"]] == [[.15, .85], [1.3, 2.7], [3.15, 3.85]]
    assert len(manifest["threshold_sweep"]) >= 3
    assert all(sweep["scene_times_s"] == [1, 3] for sweep in manifest["threshold_sweep"])
    assert manifest["selected_threshold"] != manifest["threshold_sweep"][0]["threshold"]
    assert result["contact_sheets"][0]["shot_ids"] == [1, 2, 3]
    for sheet in result["contact_sheets"]:
        path = Path(sheet["path"])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sheet["sha256"]
        with Image.open(path) as image:
            assert image.width <= 1400 and image.height <= 3000
    assert hashlib.sha256(Path(result["analysis_path"]).read_bytes()).hexdigest() == result["measurements_sha256"]
    initial = json.loads(next(Path(item["path"]) for item in result["outputs"] if item["path"].endswith("shots.json")).read_text())
    assert initial["semantic_review"] == "pending_visual_review"
    assert all(shot["camera_move"] == "unknown" for shot in initial["shots"])


def test_native_frame_motion_distinguishes_a_moving_picture(job):
    result = measure(job, "moving.mp4")
    assert max(shot["median_frame_difference"] for shot in result["shots"]) > .003


@pytest.mark.parametrize("bad", [
    lambda: labels(shot_ids=(1, 2)), lambda: labels(shot_ids=(1, 1, 3)),
    lambda: [{**labels()[0], "start_s": 0}, *labels()[1:]],
    lambda: [{key: value for key, value in labels()[0].items() if key != "category"}, *labels()[1:]],
    lambda: [{**labels()[0], "shot_id": True}, *labels()[1:]],
])
def test_report_rejects_missing_duplicate_or_timing_bearing_labels(job, bad):
    measured = measure(job)
    result = report(measured, bad())
    assert not result["ok"] and result["status"] == "failed"
    assert result["outputs"] == []


@pytest.mark.parametrize("camera_move", ["push", "pull", "dolly", "pan", "truck", "track", "zoom"])
def test_near_zero_motion_blocks_moving_camera_claims(job, camera_move):
    measured = measure(job)
    result = report(measured, labels(camera_move))
    assert not result["ok"] and result["status"] == "blocked"
    assert len(result["gate_failures"]) == 3
    assert all("near-zero" in failure for failure in result["gate_failures"])
    exported = json.loads(Path(result["shots_path"]).read_text())
    assert exported["gate_failures"] == result["gate_failures"]


@pytest.mark.parametrize('description', ['pullback', 'locked off, no push-in or pull-out'])
def test_camera_descriptions_must_use_the_closed_motion_contract(description):
    from providers.reference_shots.contracts import ShotLabel

    with pytest.raises(ValueError):
        ShotLabel.model_validate(labels(description, shot_ids=(1,))[0])


def test_unknown_labels_and_simulated_labels_remain_incomplete(job):
    measured = measure(job)
    unknown = [{**item, "shot_size": "unknown"} for item in labels()]
    result = report(measured, unknown, labels_provenance="simulated")
    assert result["ok"] and result["status"] == "incomplete"
    assert result["gates_passed"] is True
    assert result["semantic_review"] == "pending_visual_review"
    assert result["labels_provenance"] == "simulated"
    assert result["incomplete_shot_ids"] == [1, 2, 3]


def test_self_contained_report_embeds_playable_video_and_escapes_label_text(job):
    measured = measure(job)
    values = labels()
    values[0]["frame_description"] = '</script><img src=x onerror="alert(1)">'
    result = report(measured, values)
    assert result["ok"] and result["status"] == "incomplete"
    assert result["semantic_review"] == "pending_visual_review"
    page = Path(result["report_path"]).read_text()
    assert "data:video/mp4;base64," in page and "data:image/jpeg;base64," in page
    assert "&lt;/script&gt;" in page and '<img src=x onerror="alert(1)">' not in page
    assert "timeupdate" in page and "currentTime" in page and 'id="pace-strip"' in page
    assert "Average shot" in page and "Cuts per minute" in page
    encoded = page.split("data:video/mp4;base64,", 1)[1].split('"', 1)[0]
    embedded = Path(result["report_path"]).parent / "verify-player.mp4"
    embedded.write_bytes(base64.b64decode(encoded))
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name",
                            "-of", "json", str(embedded)], check=True, capture_output=True, timeout=10)
    assert json.loads(probe.stdout)["streams"][0]["codec_name"] == "h264"
    assert result["stats"]["average_shot_s"] == pytest.approx(4 / 3)
    assert result["stats"]["cuts_per_minute"] == 30


@pytest.mark.parametrize("target", ["manifest", "source", "sheet"])
def test_report_rejects_modified_pinned_evidence_without_new_outputs(job, target):
    measured = measure(job)
    path = {"manifest": Path(measured["analysis_path"]), "source": job / "cuts.mp4",
            "sheet": Path(measured["contact_sheets"][0]["path"])}[target]
    path.write_bytes(path.read_bytes() + b"tampered")
    before = set(job.iterdir())
    result = report(measured)
    assert not result["ok"] and "checksum" in result["error"].lower()
    assert result["outputs"] == [] and set(job.iterdir()) == before


def test_corrupt_and_truncated_media_fail_without_partial_bundles(job):
    (job / "corrupt.mp4").write_bytes(b"not a video")
    source = (job / "cuts.mp4").read_bytes()
    (job / "truncated.mp4").write_bytes(source[:len(source) * 3 // 4])
    for name in ("corrupt.mp4", "truncated.mp4"):
        before = set(job.iterdir())
        result = core().shot_breakdown("measure", "job", name)
        assert not result["ok"], result
        assert result["outputs"] == [] and set(job.iterdir()) == before


def test_symlink_to_media_outside_the_job_is_rejected(job, tmp_path):
    outside = tmp_path / "outside.mp4"
    shutil.copyfile(job / "cuts.mp4", outside)
    (job / "escape.mp4").symlink_to(outside)
    result = core().shot_breakdown("measure", "job", "escape.mp4")
    assert not result["ok"] and result["outputs"] == []


def test_repeated_calls_create_distinct_bundles_and_keep_prior_outputs(job):
    first = measure(job)
    first_bytes = Path(first["analysis_path"]).read_bytes()
    second = measure(job)
    assert first["analysis_path"] != second["analysis_path"]
    assert Path(first["analysis_path"]).read_bytes() == first_bytes


def test_one_frame_shots_do_not_sample_pixels_from_the_next_shot(job):
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-f", "lavfi",
                    "-i", "color=c=red:s=160x90:r=12:d=0.0833333", "-f", "lavfi", "-i",
                    "color=c=blue:s=160x90:r=12:d=1", "-f", "lavfi", "-i",
                    "color=c=red:s=160x90:r=12:d=0.0833333", "-filter_complex",
                    "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]", "-c:v", "libx264",
                    "-threads", "1", "-pix_fmt", "yuv420p", str(job / "one-frame.mp4")],
                   check=True, capture_output=True, timeout=30)
    measured = measure(job, "one-frame.mp4")
    assert len(measured["shots"]) == 3
    assert measured["shots"][0]["median_frame_difference"] is None
    for shot in measured["shots"]:
        assert all(shot["start_s"] <= pts < shot["end_s"] for pts in shot["sampled_frame_times_s"])
    with Image.open(measured["contact_sheets"][0]["path"]) as sheet:
        for x in (100, 420):
            first, middle, last = [sheet.getpixel((x, y)) for y in (120, 344, 568)]
            assert first[0] > 180 and first[2] < 40
            assert middle[2] > 180 and middle[0] < 40
            assert last[0] > 180 and last[2] < 40


def test_non_mp4_source_gets_a_complete_bounded_player_without_upscaling(job):
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-i",
                    str(job / "cuts.mp4"), "-c", "copy", str(job / "cuts.mkv")],
                   check=True, capture_output=True, timeout=20)
    measured = measure(job, "cuts.mkv")
    manifest = json.loads(Path(measured["analysis_path"]).read_text())
    assert manifest["player"]["kind"] == "proxy"
    assert manifest["player"]["duration_s"] == pytest.approx(4, abs=.1)
    assert (manifest["player"]["width"], manifest["player"]["height"]) == (160, 90)
    assert manifest["player"]["bytes"] < 8 * 1024 * 1024


def test_truncated_process_capture_is_never_treated_as_a_complete_measurement(job, monkeypatch):
    from providers.ffmpeg import api as media_api

    original = media_api._bounded_run

    def run(argv, directory, timeout, **kwargs):
        if "-progress" in argv:
            return media_api.ProcessResult(0, b"frame=48\nout_time_us=4000000\nprogress=end\n", b"",
                                           stderr_truncated=True)
        return original(argv, directory, timeout, **kwargs)

    monkeypatch.setattr(media_api, "_bounded_run", run)
    before = set(job.iterdir())
    result = core().shot_breakdown("measure", "job", "cuts.mp4")
    assert not result["ok"] and "incomplete" in result["error"]
    assert set(job.iterdir()) == before


def test_threshold_disagreement_is_visible_without_choosing_the_most_cuts(job, monkeypatch):
    from providers.ffmpeg import api as media_api

    original = media_api.execute

    def execute(op, directory, source, params=None):
        if op == "detect_scenes" and params["T"] == .2:
            return {"ok": True, "metrics": {"scene_times": [.5, 1., 2., 3.]}}
        return original(op, directory, source, params)

    monkeypatch.setattr(media_api, "execute", execute)
    measured = measure(job)
    assert len(measured["shots"]) == 3
    assert any("sensitive" in warning.lower() for warning in measured["warnings"])


def test_high_motion_static_label_warns_without_blocking(job, monkeypatch):
    moving = job / "high-motion.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
                    "nullsrc=s=160x90:r=12:d=2,geq=lum='80+30*sin(N)':cb=128:cr=128", "-c:v", "libx264",
                    "-threads", "1", "-pix_fmt", "yuv420p", str(moving)],
                   check=True, capture_output=True, timeout=30)
    measured = measure(job, moving.name)
    result = report(measured, labels(shot_ids=(1,)))
    assert result["ok"] and result["gates_passed"]
    assert any("static camera" in warning for warning in result["warnings"])
