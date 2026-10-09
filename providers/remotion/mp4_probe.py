from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import os
from pathlib import Path
import stat
import struct
from typing import Any, BinaryIO, Iterator


_ERROR = "Local source/output is not a supported media container."
_MAX_DEPTH = 16
_MAX_BOXES = 10_000
_MAX_TRACKS = 64
_MAX_ENTRIES = 1_000_000
_CHUNK_ENTRIES = 4096
_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"udta",
               b"edts", b"dinf", b"tref", b"meta", b"ilst"}
_PARENTS = {
    b"moov": {None}, b"trak": {b"moov"}, b"mvhd": {b"moov"}, b"tkhd": {b"trak"},
    b"mdia": {b"trak"}, b"mdhd": {b"mdia"}, b"hdlr": {b"mdia", b"minf", b"meta"},
    b"minf": {b"mdia"}, b"stbl": {b"minf"}, b"edts": {b"trak"},
    b"dinf": {b"minf"}, b"tref": {b"trak"}, b"ftyp": {None},
    b"stsd": {b"stbl"}, b"stsz": {b"stbl"}, b"stts": {b"stbl"},
    b"stz2": {b"stbl"},
}
_UNIQUE = set(_PARENTS) - {b"trak"}
_TRACK_HEADERS = {b"tkhd", b"mdhd", b"hdlr", b"stsd", b"stsz", b"stts"}
_CODECS = {
    b"avc1": "h264", b"avc3": "h264", b"hvc1": "hevc", b"hev1": "hevc",
    b"mp4a": "aac", b"mp4v": "mpeg4", b"vp09": "vp9", b"vp08": "vp8",
    b"av01": "av1", b"jpeg": "mjpeg", b"mjpg": "mjpeg", b"mjpa": "mjpeg",
    b"mjpb": "mjpeg", b"apco": "prores", b"apcs": "prores", b"apcn": "prores",
    b"apch": "prores", b"ap4h": "prores", b"ap4x": "prores", b"Opus": "opus",
    b"fLaC": "flac", b"alac": "alac", b"ac-3": "ac3", b"ec-3": "eac3",
}


class UnsupportedContainer(ValueError):
    pass


@dataclass(frozen=True)
class _Box:
    kind: bytes
    start: int
    end: int
    depth: int


class _Parser:
    def __init__(self, source: BinaryIO, size: int) -> None:
        self.source = source
        self.size = size
        self.box_count = 0
        self.entry_count = 0
        self.sample_count = 0
        self.movie: _Box | None = None
        self.movie_header: _Box | None = None
        self.tracks: list[dict[bytes, _Box]] = []

    def read(self, box: _Box, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0 or box.start + offset + length > box.end:
            raise ValueError(_ERROR)
        self.source.seek(box.start + offset)
        data = self.source.read(length)
        if len(data) != length:
            raise ValueError(_ERROR)
        return data

    def boxes(self, start: int, end: int, depth: int) -> Iterator[_Box]:
        if depth > _MAX_DEPTH:
            raise ValueError(_ERROR)
        parent = _Box(b"", start, end, depth)
        position = start
        while position < end:
            size, kind = struct.unpack(">I4s", self.read(parent, position - start, 8))
            header_size = 8
            if size == 1:
                size = struct.unpack(">Q", self.read(parent, position - start + 8, 8))[0]
                header_size = 16
            elif size == 0:
                size = end - position
            if size < header_size or size > end - position:
                raise ValueError(_ERROR)
            self.box_count += 1
            if self.box_count > _MAX_BOXES:
                raise ValueError(_ERROR)
            yield _Box(kind, position + header_size, position + size, depth)
            position += size

    def full_box(self, box: _Box, versions: tuple[int, ...] = (0,)) -> int:
        header = self.read(box, 0, 4)
        if header[0] not in versions or header[1:] != b"\0\0\0":
            raise ValueError(_ERROR)
        return header[0]

    def walk(self, start: int, end: int, parent: bytes | None = None,
             depth: int = 1, track: dict[bytes, _Box] | None = None) -> None:
        seen: set[bytes] = set()
        for box in self.boxes(start, end, depth):
            kind = box.kind
            if kind in {b"moof", b"mvex", b"traf", b"stz2"}:
                raise ValueError(_ERROR)
            if kind in _PARENTS and parent not in _PARENTS[kind]:
                raise ValueError(_ERROR)
            if kind in _UNIQUE:
                if kind in seen:
                    raise ValueError(_ERROR)
                seen.add(kind)
            if kind == b"moov":
                self.movie = box
            elif kind == b"mvhd":
                self.movie_header = box
            elif kind == b"trak":
                if len(self.tracks) >= _MAX_TRACKS:
                    raise ValueError(_ERROR)
                child_track: dict[bytes, _Box] = {}
                self.tracks.append(child_track)
                self.walk(box.start, box.end, kind, depth + 1, child_track)
                continue
            elif kind == b"ftyp":
                length = box.end - box.start
                if length < 8 or (length - 8) % 4:
                    raise ValueError(_ERROR)
            elif (track is not None and kind in _TRACK_HEADERS
                  and (kind != b"hdlr" or parent == b"mdia")):
                # QuickTime's minf data handler is separate from mdia's media handler.
                track[kind] = box
            if kind in _CONTAINERS:
                offset = 4 if kind == b"meta" else 0
                if offset:
                    self.full_box(box)
                self.walk(box.start + offset, box.end, kind, depth + 1, track)

    def time(self, box: _Box) -> tuple[int, int]:
        version = self.full_box(box, (0, 1))
        offset, fmt = (20, ">IQ") if version == 1 else (12, ">II")
        minimum = (112 if version else 100) if box.kind == b"mvhd" else (36 if version else 24)
        if box.end - box.start < minimum:
            raise ValueError(_ERROR)
        timescale, ticks = struct.unpack(fmt, self.read(box, offset, struct.calcsize(fmt)))
        if not timescale:
            raise ValueError(_ERROR)
        if ticks == (1 << (64 if version else 32)) - 1:
            ticks = 0
        return timescale, ticks

    def charge_entries(self, count: int) -> None:
        self.entry_count += count
        if self.entry_count > _MAX_ENTRIES:
            raise ValueError(_ERROR)

    def entries(self, box: _Box, offset: int, count: int,
                fmt: str) -> Iterator[tuple[int, ...]]:
        width = struct.calcsize(fmt)
        if box.end - box.start != offset + count * width:
            raise ValueError(_ERROR)
        self.charge_entries(count)
        for first in range(0, count, _CHUNK_ENTRIES):
            length = min(count - first, _CHUNK_ENTRIES) * width
            yield from struct.iter_unpack(fmt, self.read(box, offset + first * width, length))

    def sample_sizes(self, box: _Box) -> tuple[int, int]:
        self.full_box(box)
        size, count = struct.unpack(">II", self.read(box, 4, 8))
        self.sample_count += count
        if not count or self.sample_count > _MAX_ENTRIES:
            raise ValueError(_ERROR)
        if size:
            if box.end - box.start != 12:
                raise ValueError(_ERROR)
            return count, size * count
        return count, sum(size for (size,) in self.entries(box, 12, count, ">I"))

    def sample_timing(self, box: _Box) -> tuple[int, int]:
        self.full_box(box)
        count = struct.unpack(">I", self.read(box, 4, 4))[0]
        samples = ticks = 0
        for run_samples, delta in self.entries(box, 8, count, ">II"):
            samples += run_samples
            if not run_samples or not delta or samples > _MAX_ENTRIES:
                raise ValueError(_ERROR)
            ticks += run_samples * delta
        if not samples:
            raise ValueError(_ERROR)
        return samples, ticks

    def sample_entry(self, box: _Box, kind: bytes) -> dict[str, Any]:
        self.full_box(box)
        count = struct.unpack(">I", self.read(box, 4, 4))[0]
        if not count or count > (box.end - box.start - 8) // 8:
            raise ValueError(_ERROR)
        self.charge_entries(count)
        first: _Box | None = None
        actual_count = 0
        for entry in self.boxes(box.start + 8, box.end, box.depth + 1):
            actual_count += 1
            minimum = 78 if kind == b"vide" else 28
            if actual_count > count or entry.end - entry.start < minimum:
                raise ValueError(_ERROR)
            if first is None:
                first = entry
        if actual_count != count or first is None:
            raise ValueError(_ERROR)
        metadata: dict[str, Any] = {"codec_name": _CODECS.get(first.kind, first.kind.decode("latin1"))}
        if kind == b"vide":
            width, height = struct.unpack(">HH", self.read(first, 24, 4))
            if width > 0 and height > 0:
                metadata.update(width=width, height=height)
        return metadata

    def display_dimensions(self, metadata: dict[str, Any], box: _Box) -> None:
        version = self.read(box, 0, 4)[0]
        if version not in (0, 1):
            raise ValueError(_ERROR)
        offset = 52 if version == 1 else 40
        if box.end - box.start < offset + 44:
            raise ValueError(_ERROR)
        a, b, u, c, d, v, _, _, w = struct.unpack(">9i", self.read(box, offset, 36))
        orientation = (a, b, c, d)
        if (u, v, w) == (0, 0, 1073741824):
            if orientation in {(65536, 0, 0, 65536), (-65536, 0, 0, -65536)}:
                return
            if orientation in {(0, 65536, -65536, 0), (0, -65536, 65536, 0)}:
                if "width" in metadata and "height" in metadata:
                    metadata["width"], metadata["height"] = metadata["height"], metadata["width"]
                return
        metadata.pop("width", None)
        metadata.pop("height", None)

    def stream(self, track: dict[bytes, _Box]) -> tuple[dict[str, Any] | None, Fraction]:
        if b"mdhd" not in track or b"hdlr" not in track:
            raise ValueError(_ERROR)
        timescale, ticks = self.time(track[b"mdhd"])
        if not ticks:
            raise ValueError(_ERROR)
        duration = Fraction(ticks, timescale)
        handler = track[b"hdlr"]
        self.full_box(handler)
        if handler.end - handler.start < 24:
            raise ValueError(_ERROR)
        kind = self.read(handler, 8, 4)
        if kind not in {b"vide", b"soun"}:
            return None, duration
        if b"stsz" not in track or b"stsd" not in track:
            raise ValueError(_ERROR)
        samples, sample_bytes = self.sample_sizes(track[b"stsz"])
        if sample_bytes > self.size:
            raise ValueError(_ERROR)
        fps = Fraction(samples * timescale, ticks)
        if b"stts" in track:
            timed_samples, sample_ticks = self.sample_timing(track[b"stts"])
            if timed_samples != samples:
                raise ValueError(_ERROR)
            fps = Fraction(timed_samples * timescale, sample_ticks)
        metadata = self.sample_entry(track[b"stsd"], kind)
        if kind == b"vide" and b"tkhd" in track:
            self.display_dimensions(metadata, track[b"tkhd"])
        return {
            "codec_type": "video" if kind == b"vide" else "audio",
            **metadata,
            "avg_frame_rate": f"{fps.numerator}/{fps.denominator}" if kind == b"vide" else "0/0",
            "bit_rate": int(sample_bytes * 8 / duration),
        }, duration

    def probe(self) -> dict[str, Any]:
        self.walk(0, self.size)
        if self.movie is None or not self.tracks:
            raise ValueError(_ERROR)
        streams: list[dict[str, Any]] = []
        duration = Fraction(0)
        for track in self.tracks:
            stream, track_duration = self.stream(track)
            duration = max(duration, track_duration)
            if stream is not None:
                streams.append(stream)
        if not streams:
            raise ValueError(_ERROR)
        if self.movie_header is not None:
            timescale, ticks = self.time(self.movie_header)
            if ticks:
                duration = Fraction(ticks, timescale)
        return {"streams": streams, "format": {
            "duration": float(duration), "bit_rate": int(self.size * 8 / duration),
        }}


def probe(path: Path, *, max_bytes: int) -> dict[str, Any]:
    try:
        with path.open("rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
                raise ValueError(_ERROR)
            if source.read(4) == b"\x1a\x45\xdf\xa3":
                raise UnsupportedContainer(_ERROR)
            if info.st_size < 8:
                raise ValueError(_ERROR)
            result = _Parser(source, info.st_size).probe()
            if os.fstat(source.fileno()).st_size != info.st_size:
                raise ValueError(_ERROR)
            return result
    except OSError:
        raise ValueError(_ERROR) from None
