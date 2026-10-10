"""Gateway entry point and real internal execution for the local ffmpeg worker."""
from __future__ import annotations

from dataclasses import dataclass
from contextvars import ContextVar
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any

from providers.ffmpeg.ops import tool_schema, validate_params
from providers.ffmpeg.sandbox import (input_file, job_directory, output_records,
                                      validate_input_path, validate_job_id)


_PROCESS_LIMIT = threading.BoundedSemaphore(2)
_STDOUT_BYTES = 1024 * 1024
_STDERR_BYTES = 8192
_EXECUTION_DEADLINE: ContextVar[float | None] = ContextVar("ffmpeg_execution_deadline", default=None)


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    stdout_truncated: bool = False
    stderr_truncated: bool = False


def _bounded_run(argv: list[str], directory: Path, timeout: float, *, stderr_bytes: int = _STDERR_BYTES) -> ProcessResult:
    deadline = time.monotonic() + timeout
    if not _PROCESS_LIMIT.acquire(timeout=max(0, timeout)):
        raise subprocess.TimeoutExpired(argv[0], timeout)
    streams = []
    for limit, keep_tail in ((_STDOUT_BYTES, False), (stderr_bytes, True)):
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
                         streams[0][2]["truncated"], streams[1][2]["truncated"])


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
    spec, params = validate_params(arguments.get("op"), arguments.get("params"))
    job_id = validate_job_id(arguments.get("job_id"))
    root = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser().resolve()
    directory = (root / job_id).resolve()
    if directory == root or not directory.is_relative_to(root):
        raise ValueError("The job directory must stay inside the local media root.")
    validate_input_path(directory, arguments.get("input_path"), must_exist=False)
    for name, schema in spec.params.items():
        _validate_param_paths(directory, params[name], schema)


def _validate_param_paths(directory: Path, value: Any, schema: dict) -> None:
    if value is None:
        return
    if schema.get("format") == "job-path":
        validate_input_path(directory, value, must_exist=False)
    elif schema["type"] == "object":
        for name, item in value.items():
            _validate_param_paths(directory, item, schema["properties"][name])
    elif schema["type"] == "array":
        for item in value:
            _validate_param_paths(directory, item, schema["items"])


def _version(directory: Path) -> str | None:
    binary = shutil.which("ffmpeg")
    if not binary:
        return None
    try:
        deadline = _EXECUTION_DEADLINE.get()
        remaining = min(5, deadline - time.monotonic()) if deadline is not None else 5
        if remaining <= 0:
            return None
        result = _bounded_run([binary, "-hide_banner", "-version"], directory, remaining)
        return result.stdout.decode("utf-8", errors="replace").splitlines()[0][:200]
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


def _verify_reframe(directory: Path, output: Path, expected: dict) -> None:
    from fractions import Fraction

    probe = execute("probe", directory, output.name)
    if not probe["ok"]:
        raise ValueError("Reframed output is unreadable.")
    streams = probe["metrics"]["streams"]
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    duration = float(probe["metrics"].get("format", {}).get("duration", 0))
    fps = float(Fraction(expected["source_fps"]))
    if ((video.get("width"), video.get("height")) != (expected["width"], expected["height"])
            or video.get("sample_aspect_ratio") != "1:1"
            or abs(duration - expected["source_duration"]) > max(.1, 2 / fps)
            or (expected["source_audio"] and not any(s.get("codec_type") == "audio" for s in streams))):
        raise ValueError("Reframed output is incomplete or violates dimensions, SAR, duration or audio preservation.")


def execute(op: str, job_dir: Path, input_path: str, params: dict | None = None) -> dict:
    """Run a validated free operation internally, including when Gateway dry-run is enabled."""
    result = _base(op)
    outputs = []
    owned_outputs = []
    owned_sidecars = []
    staging = None
    token = None
    directory = Path(job_dir).resolve()
    try:
        spec, parsed = validate_params(op, params)
        deadline = time.monotonic() + spec.timeout_s
        parent_deadline = _EXECUTION_DEADLINE.get()
        if parent_deadline is not None:
            deadline = min(deadline, parent_deadline)
        token = _EXECUTION_DEADLINE.set(deadline)
        if not directory.is_dir():
            raise ValueError("The local job directory is missing.")
        if spec.export is not None:
            validate_input_path(directory, input_path, must_exist=False)
            metrics = spec.export(directory, parsed, owned_outputs)
            outputs = owned_outputs
        elif spec.compute is not None:
            validate_input_path(directory, input_path, must_exist=False)
            metrics = spec.compute(parsed)
        elif spec.pure is not None:
            source = input_file(directory, input_path, max_bytes=spec.input_limit_bytes)
            metrics = spec.pure(source)
        else:
            source = input_file(directory, input_path, max_bytes=spec.input_limit_bytes)
            binary = shutil.which(spec.binary)
            if not binary:
                raise ValueError(f"{spec.binary} is not installed. This op requires the local/worker host "
                                 "containing the job directory; the Gateway Lambda zip has no ffmpeg.")
            commands = spec.builder(directory, source, parsed)
            outputs = [output for command in commands for output in command.outputs]
            sidecars = {path: content for command in commands for path, content in command.sidecars.items()}
            for path, content in sidecars.items():
                if not path.is_relative_to(directory) or len(content) > 2 * 1024 * 1024:
                    raise ValueError("Temporary finishing assets must stay inside the job and fit within 2 MiB.")
                with path.open("xb") as handle:
                    owned_sidecars.append(path)
                    handle.write(content)
            if outputs:
                staging = Path(tempfile.mkdtemp(prefix="ffmpeg-output-", dir=directory))
            processes = []
            metrics = {}
            for command in commands:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("Operation exceeded its hard timeout.")
                argv = [binary, *command.argv[1:]]
                targets = {"./" + output.relative_to(directory).as_posix(): "./" + (staging / output.name).relative_to(directory).as_posix()
                           for output in command.outputs}
                argv = [targets.get(argument, argument) for argument in argv]
                process = _bounded_run(argv, directory, remaining, stderr_bytes=command.stderr_bytes)
                if process.returncode:
                    result["error_tail"] = _redact(process.stderr.decode("utf-8", errors="replace"), directory)
                    raise ValueError("Media operation failed. The file may lack the required stream or be invalid.")
                if process.stdout_truncated:
                    raise ValueError("Media inspection exceeded the bounded stdout capture limit.")
                for output in command.outputs:
                    os.link(staging / output.name, output, follow_symlinks=False)
                    owned_outputs.append(output)
                processes.append(process)
                metrics.update(command.metrics)
            if spec.parse is not None:
                metrics.update(spec.parse(processes))
            if spec.finalize is not None:
                metrics.update(spec.finalize(directory, source, parsed, outputs, metrics))
            if op == "detect_scenes":
                from providers.ffmpeg.reframe import shots_from_scenes

                metrics["shots"] = shots_from_scenes(metrics["scene_times"], metrics["source_duration"])
            if op in {"reframe_crop", "reframe_pad_blur"}:
                _verify_reframe(directory, outputs[0], metrics)
        result["warnings"].extend(metrics.get("warnings", []))
        records = output_records(outputs)
        version = None if spec.pure is not None or spec.compute is not None or spec.export is not None else _version(directory)
        if time.monotonic() >= deadline:
            raise ValueError("Operation exceeded its hard timeout.")
        result.update(ok=True, status="succeeded", metrics=metrics, outputs=records, ffmpeg_version=version)
        if op == "check_faststart" and not metrics["faststart"]:
            result["warnings"].append("MP4 moov follows mdat; faststart is absent.")
        if op == "volume_stats" and metrics.get("mean_volume_db") is None:
            result["warnings"].append("Audio is silent; non-finite dB levels are reported as null.")
        return result
    except (ValueError, OSError, TypeError, subprocess.SubprocessError) as exc:
        for output in owned_outputs:
            output.unlink(missing_ok=True)
        error = "Operation exceeded its hard timeout." if isinstance(exc, subprocess.TimeoutExpired) else str(exc)
        result.update(status="failed", error=_redact(error, directory))
        return result
    finally:
        for path in owned_sidecars:
            path.unlink(missing_ok=True)
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        if token is not None:
            _EXECUTION_DEADLINE.reset(token)


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
