from pathlib import Path

import pytest

from agent.deep_agent.sandbox import JobSandbox


@pytest.fixture
def clip(tmp_path):
    result = JobSandbox(tmp_path).execute(
        'ffmpeg -v error -f lavfi -i color=c=black:s=64x64:d=1 '
        '-f lavfi -i anullsrc=r=48000:cl=mono -t 1 -c:v libx264 -c:a aac black.mp4')
    assert result.exit_code == 0, result.output
    return tmp_path / 'black.mp4'


def test_inspection_measures_black_and_silence_and_binds_hash(clip):
    from agent.deep_agent.inspection import MediaInspection
    inspector = MediaInspection(JobSandbox(clip.parent))
    report = inspector.inspect('black.mp4')
    assert report['status'] == 'inspected'
    assert report['width'] == 64 and report['height'] == 64
    assert report['duration_seconds'] == pytest.approx(1, abs=.1)
    assert report['black_intervals'] and report['silence_intervals']
    assert 'loudness_lufs' in report
    assert report['speech_sample']['status'] == 'skipped'
    assert 'read_file' in report['visual_check']
    assert inspector.blocker(['black.mp4'])
    inspector.saw_frames('black.mp4')
    assert inspector.blocker(['black.mp4']) is None
    clip.write_bytes(clip.read_bytes() + b'changed')
    assert inspector.blocker(['black.mp4'])


def test_inspection_cannot_read_other_jobs_or_accept_nonmedia(tmp_path):
    from agent.deep_agent.inspection import MediaInspection
    inspector = MediaInspection(JobSandbox(tmp_path))
    with pytest.raises(ValueError):
        inspector.inspect('../private.mp4')
    (tmp_path / 'empty.txt').write_text('text')
    with pytest.raises(ValueError):
        inspector.inspect('empty.txt')


def test_inspection_does_not_accept_prior_turn_receipts(clip):
    from agent.deep_agent.inspection import MediaInspection
    first = MediaInspection(JobSandbox(clip.parent))
    first.inspect(clip.name)
    first.saw_frames(clip.name)
    assert first.blocker([clip.name]) is None
    assert MediaInspection(JobSandbox(clip.parent)).blocker([clip.name])


def test_inspection_measures_loudness(tmp_path):
    from agent.deep_agent.inspection import MediaInspection
    sandbox = JobSandbox(tmp_path)
    assert sandbox.execute('ffmpeg -v error -f lavfi -i sine=frequency=440:duration=3 -af loudnorm=I=-14:TP=-1:LRA=11 tone.wav').exit_code == 0
    report = MediaInspection(sandbox).inspect('tone.wav')
    assert report['loudness_lufs'] == pytest.approx(-14, abs=1)


def test_minute_of_audio_keeps_measurement_logs_within_output_limit(tmp_path):
    from agent.deep_agent.inspection import MediaInspection
    sandbox = JobSandbox(tmp_path)
    assert sandbox.execute('ffmpeg -v error -f lavfi -i sine=frequency=440:duration=60 tone.wav').exit_code == 0
    report = MediaInspection(sandbox).inspect('tone.wav')
    assert report['duration_seconds'] == pytest.approx(60, abs=.1)
    assert report['loudness_lufs'] is not None
    assert report['true_peak_dbfs'] is not None


def test_sdk_video_read_returns_actual_frames(clip):
    from deepagents.middleware._video import extract_video_frames
    frames = extract_video_frames(clip.read_bytes(), offset_seconds=0,
                                  duration_seconds=1, sampling_rate=.5)
    assert any(block['type'] == 'image' for block in frames)
