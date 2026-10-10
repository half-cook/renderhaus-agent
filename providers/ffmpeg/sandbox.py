"""Confine media inputs and generated outputs to one local job directory."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat
import uuid


MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_TOTAL_OUTPUT_BYTES = 64 * 1024 * 1024
ID_PATTERN = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,79}"
PATH_PATTERN = r"^(?!.*(?:^|/)\.\.?(?:/|$))(?:/)?(?:[A-Za-z0-9_.][A-Za-z0-9_.-]*/)*[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}(?![\s\S])"
NAME_PATTERN = r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}"


def validate_job_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(ID_PATTERN, value):
        raise ValueError("job_id must be an ASCII identifier of 1 to 80 characters.")
    return value


def job_directory(job_id: str) -> Path:
    validate_job_id(job_id)
    root = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser().resolve()
    directory = (root / job_id).resolve()
    if directory == root or not directory.is_relative_to(root) or not directory.is_dir():
        raise ValueError("job_id must identify an existing directory inside the local media root.")
    return directory


def validate_input_path(directory: Path, value: str, *, must_exist: bool = True) -> Path:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise ValueError("input_path must name a regular file inside the job directory.")
    path = Path(value)
    directory = directory.resolve()
    if path.is_absolute():
        try:
            relative = path.relative_to(directory)
        except ValueError:
            raise ValueError("Absolute input paths must stay inside the job directory.") from None
    else:
        relative = path
    if (not relative.parts or any(part in {".", ".."} or not re.fullmatch(NAME_PATTERN, part)
                                  for part in relative.parts)):
        raise ValueError("Input names must be ASCII names without traversal, URLs, or option prefixes.")
    resolved = (directory / relative).resolve()
    if not resolved.is_relative_to(directory) or resolved == directory:
        raise ValueError("Input symlinks must stay inside the job directory.")
    if must_exist:
        try:
            info = resolved.stat()
        except OSError:
            raise ValueError("Input file is missing or unreadable inside the job directory.") from None
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_INPUT_BYTES:
            raise ValueError("Inputs must be nonempty regular files of at most 128 MiB.")
        if not os.access(resolved, os.R_OK):
            raise ValueError("Input file is not readable.")
    return resolved


def input_file(job_dir: Path, path: str) -> Path:
    return validate_input_path(job_dir, path)


def output_file(job_dir: Path, prefix: str, suffix: str) -> Path:
    name = f"{prefix}-{uuid.uuid4().hex}{suffix}"
    if not re.fullmatch(NAME_PATTERN, name):
        raise ValueError("Output template produced an unsafe filename.")
    output = job_dir / name
    if output.exists() or output.is_symlink():
        raise ValueError("Generated output already exists; overwriting is disabled.")
    return output


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def output_records(paths: list[Path]) -> list[dict]:
    records = []
    total = 0
    for path in paths:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_OUTPUT_BYTES:
            raise ValueError("Generated media is missing, empty, or exceeds the 16 MiB output cap.")
        total += info.st_size
        if total > MAX_TOTAL_OUTPUT_BYTES:
            raise ValueError("Generated outputs exceed the 64 MiB total cap.")
        records.append({"path": str(path), "sha256": sha256_file(path), "bytes": info.st_size})
    return records
