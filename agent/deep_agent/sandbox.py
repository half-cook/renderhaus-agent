"""Secret-free, network-free job execution behind the Deep Agents sandbox protocol."""
from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path, PurePosixPath
import selectors
import shutil
import signal
import subprocess
import tarfile
import tempfile
import threading
import time

from deepagents.backends import StateBackend
from deepagents.backends.protocol import ExecuteResponse, SandboxBackendProtocol


_SUPERVISOR = r'''
import os, resource, shutil, subprocess, sys, tarfile
resource.setrlimit(resource.RLIMIT_CPU, (int(sys.argv[2]), int(sys.argv[2])))
resource.setrlimit(resource.RLIMIT_FSIZE, (int(sys.argv[3]), int(sys.argv[3])))
resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
shutil.copytree('/input', '/work', dirs_exist_ok=True, symlinks=True)
os.chdir('/work')
code = subprocess.call(['/bin/bash', '-c', sys.argv[1]], close_fds=True)
with os.fdopen(int(sys.argv[4]), 'wb') as stream:
    with tarfile.open(fileobj=stream, mode='w|') as archive:
        for name in sorted(os.listdir('/work')):
            archive.add(name, arcname=name, recursive=True)
sys.exit(code)
'''


class JobSandbox(SandboxBackendProtocol):
    """Local Linux implementation; a container can implement the same protocol."""

    def __init__(self, directory: Path, *, wall_seconds: int = 60,
                 output_bytes: int = 32_768, disk_bytes: int = 512 * 1024**2,
                 remotion_runtime: Path | None = None, meter=None):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.wall_seconds = wall_seconds
        self.output_bytes = output_bytes
        self.disk_bytes = disk_bytes
        self.remotion_runtime = remotion_runtime
        self.meter = meter
        self._lock = threading.Lock()

    @property
    def id(self) -> str:
        return str(self.directory)

    def stage_owned_file(self, source: Path, name: str) -> Path:
        from providers.ffmpeg.sandbox import NAME_PATTERN, sha256_file
        import re

        if not re.fullmatch(NAME_PATTERN, name):
            raise ValueError('Owned media needs a safe filename.')
        with self._lock:
            target = self.directory / name
            if target.is_symlink():
                raise ValueError('Staged media cannot replace a link.')
            if target.exists():
                if target.is_file() and sha256_file(target) == sha256_file(source):
                    return target
                raise ValueError('Staged media changed. Use a new asset version.')
            total = sum(path.lstat().st_size for path in self.directory.rglob('*') if path.is_file() and not path.is_symlink())
            if not source.is_file() or total + source.stat().st_size > self.disk_bytes:
                raise ValueError('Owned media exceeds the workspace disk quota.')
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                with os.fdopen(fd, 'wb') as dst, source.open('rb') as src:
                    remaining = self.disk_bytes - total
                    while chunk := src.read(min(1024**2, remaining + 1)):
                        if len(chunk) > remaining:
                            raise ValueError('Owned media exceeds the workspace disk quota.')
                        dst.write(chunk)
                        remaining -= len(chunk)
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            return target

    def _persist(self, data: bytes) -> None:
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            members = archive.getmembers()
            total = 0
            for item in members:
                path = PurePosixPath(item.name)
                if path.is_absolute() or '..' in path.parts or not path.parts:
                    raise ValueError('Unsafe sandbox output path.')
                if not (item.isfile() or item.isdir()):
                    raise ValueError('Sandbox links and special files cannot be persisted.')
                total += item.size
                if total > self.disk_bytes or len(members) > 10_000:
                    raise ValueError('Sandbox disk or file-count limit exceeded.')
            for item in members:
                target = self.directory / item.name
                if any(p.is_symlink() for p in [target, *target.parents] if p != self.directory.parent):
                    raise ValueError('Sandbox output cannot overwrite links.')
            retained = {item.name.rstrip('/') for item in members}
            for existing in sorted(self.directory.rglob('*'), key=lambda p: len(p.parts), reverse=True):
                if existing.relative_to(self.directory).as_posix() not in retained:
                    if existing.is_dir() and not existing.is_symlink():
                        existing.rmdir()
                    else:
                        existing.unlink()
            for item in members:
                target = self.directory / item.name
                if item.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(item) as src, target.open('wb') as dst:
                        shutil.copyfileobj(src, dst)

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        from agent.deep_agent.budget import record_local_work
        seconds = min(self.wall_seconds, timeout) if timeout and timeout > 0 else self.wall_seconds
        return record_local_work(self.meter, 'sandbox', lambda: self._execute(command, timeout=timeout),
                                 max_seconds=seconds + 10)

    def _execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        isolator = shutil.which('bwrap')
        if not isolator:
            return ExecuteResponse(output='Sandbox unavailable. Install bubblewrap or use an isolated container backend.', exit_code=126)
        if not isinstance(command, str) or len(command) > 65_536:
            return ExecuteResponse(output='Command must be a string of at most 65536 characters.', exit_code=2)
        seconds = min(self.wall_seconds, timeout) if timeout and timeout > 0 else self.wall_seconds
        with self._lock, tempfile.TemporaryFile() as archive:
            args = [isolator, '--unshare-all', '--die-with-parent', '--new-session',
                    '--cap-drop', 'ALL', '--clearenv', '--ro-bind', '/usr', '/usr',
                    '--symlink', 'usr/bin', '/bin', '--symlink', 'usr/lib', '/lib',
                    '--symlink', 'usr/lib64', '/lib64', '--proc', '/proc', '--dev', '/dev',
                    '--ro-bind', str(self.directory), '/input',
                    '--size', str(self.disk_bytes), '--tmpfs', '/work',
                    '--symlink', '/work', '/tmp', '--chdir', '/work',
                    '--setenv', 'PATH', '/runtime/node_modules/.bin:/usr/bin:/bin',
                    '--setenv', 'HOME', '/work', '--setenv', 'LANG', 'C.UTF-8',
                    '--setenv', 'NODE_PATH', '/runtime/node_modules',
                    '--setenv', 'OMP_NUM_THREADS', '1', '--setenv', 'OPENBLAS_NUM_THREADS', '1']
            if self.remotion_runtime and self.remotion_runtime.is_dir():
                args += ['--ro-bind', str(self.remotion_runtime.resolve()), '/runtime/node_modules']
            for runtime_path in ('/etc/alternatives', '/etc/ld.so.cache', '/etc/fonts'):
                if Path(runtime_path).exists():
                    args += ['--ro-bind', runtime_path, runtime_path]
            args += ['--remount-ro', '/dev', '--remount-ro', '/']
            args += ['/usr/bin/python3', '-I', '-c', _SUPERVISOR, command,
                     str(max(1, seconds)), str(self.disk_bytes), str(archive.fileno())]
            try:
                process = subprocess.Popen(args, env={}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           pass_fds=(archive.fileno(),), start_new_session=True)
            except OSError:
                return ExecuteResponse(output='Sandbox unavailable. Check the isolated runtime installation.', exit_code=126)
            output = bytearray()
            truncated = False
            deadline = time.monotonic() + seconds
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    if time.monotonic() >= deadline:
                        truncated = True
                        os.killpg(process.pid, signal.SIGKILL)
                        break
                    for key, _ in selector.select(0.05):
                        chunk = os.read(key.fileobj.fileno(), 8192)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            break
                        remaining = self.output_bytes - len(output)
                        output.extend(chunk[:remaining])
                        if len(chunk) > remaining:
                            truncated = True
                            os.killpg(process.pid, signal.SIGKILL)
                            selector.unregister(key.fileobj)
                            break
            code = process.wait()
            process.stdout.close()
            if truncated:
                return ExecuteResponse(output=output.decode(errors='replace') + '\nExecution stopped at its time/output limit.',
                                       exit_code=code or 124, truncated=True)
            if code == 0:
                archive.seek(0)
                try:
                    self._persist(archive.read(self.disk_bytes + 12 * 1024**2))
                except (ValueError, OSError, tarfile.TarError):
                    return ExecuteResponse(output='Sandbox output failed confinement or disk validation. Fix the paths or reduce output.', exit_code=2)
            return ExecuteResponse(output=output.decode(errors='replace'), exit_code=code, truncated=False)

    async def aexecute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        return await asyncio.to_thread(self.execute, command, timeout=timeout)


class StateExecutionBackend(StateBackend, SandboxBackendProtocol):
    def __init__(self, sandbox: JobSandbox):
        super().__init__()
        self.sandbox = sandbox

    @property
    def id(self) -> str:
        return self.sandbox.id

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        return self.sandbox.execute(command, timeout=timeout)

    async def aexecute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        return await self.sandbox.aexecute(command, timeout=timeout)


def workspace_directory(job_id: str | None, scope: str) -> Path:
    from hashlib import sha256
    from providers.ffmpeg.sandbox import validate_job_id

    key = validate_job_id(job_id) if job_id else 'agent-' + sha256(scope.encode()).hexdigest()[:32]
    root = Path(os.getenv('RENDERHAUS_MEDIA_DIR', '.renderhaus/media')).expanduser().resolve()
    target = root / key
    if target.is_symlink():
        raise ValueError('Job directory cannot be a symlink.')
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    return target
