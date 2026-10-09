"""Bounded MP4 container checks before a Sync output becomes an artifact."""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path
from typing import BinaryIO, Iterator

from providers.remotion import local


MAX_BOXES = 10000
MAX_TRACKS = 32
MP4_BRANDS = {b"isom", b"mp41", b"mp42", b"avc1", b"M4V ", b"MSNV", b"dash"}


def _invalid() -> RuntimeError:
    return RuntimeError("Sync returned an invalid or truncated MP4 video container.")


def _boxes(source: BinaryIO, start: int, end: int) -> Iterator[tuple[bytes, int, int]]:
    position = start
    count = 0
    while position < end:
        count += 1
        source.seek(position)
        header = source.read(8)
        if len(header) != 8 or count > MAX_BOXES:
            raise _invalid()
        size, kind = int.from_bytes(header[:4], "big"), header[4:]
        header_size = 8
        if size == 1:
            extended = source.read(8)
            if len(extended) != 8:
                raise _invalid()
            size, header_size = int.from_bytes(extended, "big"), 16
        elif size == 0:
            size = end - position
        if size < header_size or position + size > end:
            raise _invalid()
        yield kind, position + header_size, position + size
        position += size


def _handlers(source: BinaryIO, start: int, end: int) -> set[bytes]:
    handlers = set()
    tracks = 0
    for kind, body, finish in _boxes(source, start, end):
        if kind != b"trak":
            continue
        tracks += 1
        if tracks > MAX_TRACKS:
            raise _invalid()
        for child, media_start, media_end in _boxes(source, body, finish):
            if child != b"mdia":
                continue
            for field, handler_start, handler_end in _boxes(source, media_start, media_end):
                if field == b"hdlr":
                    if handler_end - handler_start < 12:
                        raise _invalid()
                    source.seek(handler_start + 8)
                    handlers.add(source.read(4))
    return handlers


def validate_mp4(path: Path) -> None:
    """Require bounded ISO-BMFF boxes with video/audio tracks and nonempty media data."""
    size = path.stat().st_size
    if not size:
        raise _invalid()
    with path.open("rb") as source:
        boxes = list(_boxes(source, 0, size))
        headers = [(start, end) for kind, start, end in boxes if kind == b"ftyp"]
        movies = [(start, end) for kind, start, end in boxes if kind == b"moov"]
        if len(headers) != 1 or len(movies) != 1 or not any(kind == b"mdat" and end > start for kind, start, end in boxes):
            raise _invalid()
        start, end = headers[0]
        if not 8 <= end - start <= 256 or (end - start) % 4:
            raise _invalid()
        source.seek(start)
        brands = source.read(end - start)
        candidates = [brands[:4], *(brands[index:index + 4] for index in range(8, len(brands), 4))]
        if not any(brand in MP4_BRANDS or (brand[:3] == b"iso" and brand[3:].isdigit()) for brand in candidates):
            raise _invalid()
        if not {b"vide", b"soun"} <= _handlers(source, *movies[0]):
            raise _invalid()
    if shutil.which("ffprobe"):
        try:
            probe = local._probe(path)
            kinds = {stream.get("codec_type") for stream in probe["streams"]}
            duration = float(probe["format"]["duration"])
            if not {"video", "audio"} <= kinds or not math.isfinite(duration) or duration <= 0:
                raise _invalid()
        except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
            raise _invalid() from None
