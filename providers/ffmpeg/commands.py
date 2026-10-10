from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FORMATS = "mov,matroska,mp3,wav,aac,image2,png_pipe,jpeg_pipe,webp_pipe,ogg,flac"
THREADS = 2


@dataclass(frozen=True)
class Command:
    argv: list[str]
    outputs: list[Path] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    stderr_bytes: int = 8192
    sidecars: dict[Path, bytes] = field(default_factory=dict)


def _input(directory: Path, source: Path) -> str:
    return "./" + source.relative_to(directory).as_posix()


def _ffmpeg_input(directory: Path, source: Path) -> list[str]:
    return ["ffmpeg", "-nostdin", "-hide_banner", "-v", "info", "-n",
            "-filter_threads", str(THREADS), "-filter_complex_threads", str(THREADS),
            "-threads", str(THREADS), "-protocol_whitelist", "file,pipe",
            "-format_whitelist", FORMATS, "-i", _input(directory, source)]

