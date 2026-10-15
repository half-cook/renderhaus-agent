from __future__ import annotations

import importlib

import pytest


def sandbox(directory, **kwargs):
    module = importlib.import_module('agent.deep_agent.sandbox')
    return module.JobSandbox(directory, **kwargs)


def test_sandbox_exists():
    from agent.deep_agent import runner
    assert 'execute' in runner.FS_TOOLS


def test_shell_persists_only_job_files_and_scrubs_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv('FAL_KEY', 'canary-not-a-real-key')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'canary-not-a-real-key')
    result = sandbox(tmp_path).execute("python3 -c 'import os; print(dict(os.environ))'; printf hello > result.txt")
    assert result.exit_code == 0, result.output
    assert 'canary-not-a-real-key' not in result.output
    assert (tmp_path / 'result.txt').read_text() == 'hello'
    assert sandbox(tmp_path).execute('cat result.txt').output.strip() == 'hello'


def test_shell_cannot_read_host_or_connect(tmp_path):
    outside = tmp_path.parent / 'private-test.txt'
    outside.write_text('outside-canary')
    result = sandbox(tmp_path).execute(f'cat {outside}; curl --max-time 2 https://fal.ai/api; curl --max-time 2 http://127.0.0.1:8000')
    assert result.exit_code != 0
    assert 'outside-canary' not in result.output
    assert not (tmp_path / 'private-test.txt').exists()


def test_symlink_and_traversal_cannot_escape(tmp_path):
    outside = tmp_path.parent / 'untouched.txt'
    outside.write_text('keep')
    (tmp_path / 'escape').symlink_to(outside)
    result = sandbox(tmp_path).execute('echo changed > escape')
    assert result.exit_code != 0
    assert outside.read_text() == 'keep'


def test_wall_and_output_are_bounded(tmp_path):
    result = sandbox(tmp_path, wall_seconds=1, output_bytes=1024).execute('yes output')
    assert len(result.output.encode()) < 1400
    assert result.truncated
    assert result.exit_code != 0


def test_disk_is_bounded(tmp_path):
    result = sandbox(tmp_path, disk_bytes=2 * 1024 * 1024).execute('dd if=/dev/zero of=huge.bin bs=1M count=8')
    assert result.exit_code != 0
    assert sum(p.stat().st_size for p in tmp_path.rglob('*') if p.is_file()) <= 2 * 1024 * 1024


def test_ffmpeg_and_ffprobe_run_without_network(tmp_path):
    result = sandbox(tmp_path).execute('ffmpeg -v error -f lavfi -i color=c=blue:s=32x32:d=0.2 -c:v libx264 tiny.mp4 && ffprobe -v error -show_entries stream=width,height -of json tiny.mp4')
    assert result.exit_code == 0, result.output
    assert '"width": 32' in result.output
    assert (tmp_path / 'tiny.mp4').stat().st_size > 0


def test_missing_isolator_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr('shutil.which', lambda _: None)
    result = sandbox(tmp_path).execute('echo unsafe')
    assert result.exit_code != 0
    assert 'unavailable' in result.output.lower()
    assert 'unsafe' not in result.output


def test_sandbox_does_not_mount_repository_secrets(tmp_path):
    result = sandbox(tmp_path).execute('test ! -e /workspace/rh-agent-harness-v2/.env && test ! -e /home/box/.aws && test ! -e /proc/1/root/workspace')
    assert result.exit_code == 0, result.output


def test_staging_enforces_total_quota_and_refuses_links(tmp_path):
    source = tmp_path.parent / 'owned-source.bin'
    source.write_bytes(b'a' * 8000)
    workspace = sandbox(tmp_path, disk_bytes=12_000)
    workspace.stage_owned_file(source, 'first.bin')
    with pytest.raises(ValueError, match='quota'):
        workspace.stage_owned_file(source, 'second.bin')
    (tmp_path / 'escape.bin').symlink_to(source)
    with pytest.raises(ValueError):
        workspace.stage_owned_file(source, 'escape.bin')
    assert source.read_bytes() == b'a' * 8000


@pytest.mark.parametrize('path', ['/escape', '/dev/escape', '/dev/shm/escape'])
def test_only_work_is_writable_and_other_mounts_cannot_bypass_quota(tmp_path, path):
    result = sandbox(tmp_path, disk_bytes=2 * 1024**2).execute(f'dd if=/dev/zero of={path} bs=1M count=1 status=none')
    assert result.exit_code != 0, result.output
