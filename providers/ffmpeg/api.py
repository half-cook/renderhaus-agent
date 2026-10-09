"""Gateway entry point and real internal execution for the local ffmpeg worker."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Any

from providers.ffmpeg.ops import tool_schema, validate_params
from providers.ffmpeg.sandbox import (input_file, job_directory, output_records,
                                      validate_input_path, validate_job_id)


_PROCESS_LIMIT = threading.BoundedSemaphore(2)
_STDOUT_BYTES = 1024 * 1024
_STDERR_BYTES = 8192


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool = False


def _bounded_run(argv: list[str], directory: Path, timeout: float) -> ProcessResult:
    deadline = time.monotonic() + timeout
    if not _PROCESS_LIMIT.acquire(timeout=max(0, timeout)):
        raise subprocess.TimeoutExpired(argv[0], timeout)
    streams = []
    for limit, keep_tail in ((_STDOUT_BYTES, False), (_STDERR_BYTES, True)):
        reader, writer = os.pipe()
        capture = bytearray()
        state = {"truncated": False}

        def drain(fd=reader, output=capture, maximum=limit, tail=keep_tail, status=state):
            with os.fdopen(fd, "rb", buffering=0) as source:
                while chunk := source.read(65536):
                    if len(output) + len(chunk) > maximum:
                        status["truncated"] = True
                    if tail:
                        output.extend(chunk)
                        if len(output) > maximum:
                            del output[:-maximum]
                    else:
                        output.extend(chunk[:max(0, maximum - len(output))])

        worker = threading.Thread(target=drain, daemon=True)
        worker.start()
        streams.append((writer, capture, state, worker))
    try:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(argv[0], timeout)
        result = subprocess.run(argv, shell=False, cwd=directory, stdin=subprocess.DEVNULL,
                                stdout=streams[0][0], stderr=streams[1][0], timeout=remaining,
                                env={"PATH": os.defpath, "LANG": "C", "LC_ALL": "C",
                                     "OMP_NUM_THREADS": "2"}, check=False)
    finally:
        for writer, _, _, _ in streams:
            os.close(writer)
        for _, _, _, worker in streams:
            worker.join(timeout=5)
        _PROCESS_LIMIT.release()
    return ProcessResult(result.returncode, bytes(streams[0][1]), bytes(streams[1][1]),
                         streams[0][2]["truncated"])


def _redact(text: str, directory: Path | None = None) -> str:
    if directory is not None:
        text = text.replace(str(directory), "[job]")
    text = re.sub(r"(?:https?|file|s3)://\S+", "[url]", text)
    text = re.sub(r"(?<![A-Za-z0-9])(?:/|\.\.?/)[^\s'\"]+", "[path]", text)
    text = re.sub(r"(?i)(token|secret|password|api[_-]?key)\s*[=:]\s*[^\s,]+", r"\1=[redacted]", text)
    return text[-2048:]


def _base(op: str) -> dict[str, Any]:
    return {"op": op, "ok": False, "outputs": [], "metrics": {}, "warnings": [],
            "ffmpeg_version": None, "provider": "ffmpeg", "estimated_cost_usd": 0,
            "training_eligible": False, "license": "installed-ffmpeg-build-license"}


def validate_arguments(arguments: dict[str, Any]) -> None:
    """Enforce op and lexical path contracts before dispatch, without reading media."""
    validate_params(arguments.get("op"), arguments.get("params"))
    job_id = validate_job_id(arguments.get("job_id"))
    root = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser().resolve()
    directory = (root / job_id).resolve()
    if directory == root or not directory.is_relative_to(root):
        raise ValueError("The job directory must stay inside the local media root.")
    validate_input_path(directory, arguments.get("input_path"), must_exist=False)


def _version(directory: Path) -> str | None:
    binary = shutil.which("ffmpeg")
    if not binary:
        return None
    try:
        result = _bounded_run([binary, "-hide_banner", "-version"], directory, 5)
        return result.stdout.decode("utf-8", errors="replace").splitlines()[0][:200]
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


def execute(op: str, job_dir: Path, input_path: str, params: dict | None = None) -> dict:
    """Run a validated free operation internally, including when Gateway dry-run is enabled."""
    result = _base(op)
    outputs = []
    directory = Path(job_dir).resolve()
    try:
        spec, parsed = validate_params(op, params)
        if not directory.is_dir():
            raise ValueError("The local job directory is missing.")
        source = input_file(directory, input_path)
        if spec.pure is not None:
            metrics = spec.pure(source)
        else:
            binary = shutil.which(spec.binary)
            if not binary:
                raise ValueError(f"{spec.binary} is not installed. This op requires the local/worker host "
                                 "containing the job directory; the Gateway Lambda zip has no ffmpeg.")
            commands = spec.builder(directory, source, parsed)
            deadline = time.monotonic() + spec.timeout_s
            processes = []
            for command in commands:
                outputs.extend(command.outputs)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("Operation exceeded its hard timeout.")
                command.argv[0] = binary
                process = _bounded_run(command.argv, directory, remaining)
                if process.returncode:
                    result["error_tail"] = _redact(process.stderr.decode("utf-8", errors="replace"), directory)
                    raise ValueError("Media operation failed. The file may lack the required stream or be invalid.")
                if process.stdout_truncated:
                    raise ValueError("Media inspection exceeded the bounded stdout capture limit.")
                processes.append(process)
            metrics = spec.parse(processes) if spec.parse is not None else {}
        result.update(ok=True, status="succeeded", metrics=metrics, outputs=output_records(outputs),
                      ffmpeg_version=None if spec.pure is not None else _version(directory))
        if op == "check_faststart" and not metrics["faststart"]:
            result["warnings"].append("MP4 moov follows mdat; faststart is absent.")
        if op == "volume_stats" and metrics.get("mean_volume_db") is None:
            result["warnings"].append("Audio is silent; non-finite dB levels are reported as null.")
        return result
    except (ValueError, OSError, TypeError, subprocess.SubprocessError) as exc:
        for output in outputs:
            output.unlink(missing_ok=True)
        error = "Operation exceeded its hard timeout." if isinstance(exc, subprocess.TimeoutExpired) else str(exc)
        result.update(status="failed", error=_redact(error, directory))
        return result


def ffmpeg_tool(op: str, job_id: str, input_path: str, params: dict | None = None) -> dict:
    """Inspect confined local media using one allow-listed op; free and never approval-gated."""
    result = _base(op)
    try:
        validate_arguments(dict(op=op, job_id=job_id, input_path=input_path, params=params))
        dry_run = os.getenv("FFMPEG_DRY_RUN", "true").lower() != "false"
        if dry_run:
            result.update(ok=True, status="dry_run", warnings=["Dry-run validates arguments only; no media was inspected."])
            return result
        directory = job_directory(job_id)
        return execute(op, directory, input_path, params)
    except (ValueError, OSError, TypeError) as exc:
        result.update(status="failed", error=_redact(str(exc)))
        return result


TOOL_HANDLERS = {"ffmpeg_tool": ffmpeg_tool}
GATEWAY_TOOLS = tuple(TOOL_HANDLERS)
GATEWAY_SCHEMAS = [tool_schema()]
