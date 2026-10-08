"""Build a portable archive and verify every pinned source while copying it."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZIP_STORED, ZipFile

import httpx

from providers.nle.formats import edl_texts, fcpxml_text, media_paths, otio_text, reel_aliases, track_entries
from providers.nle.model import Asset, parse_snapshot


MAX_MEDIA_BYTES = 128 * 1024 * 1024
MAX_TOTAL_BYTES = 384 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


@contextmanager
def _source_chunks(asset: Asset, roots: tuple[Path, ...], source_root: Path,
                   allowed_hosts: tuple[str, ...]) -> Iterator[Iterator[bytes]]:
    parsed = urlsplit(asset.source)
    if parsed.scheme:
        if (parsed.scheme != "https" or parsed.hostname not in allowed_hosts
                or parsed.username or parsed.password or parsed.port not in {None, 443}
                or parsed.fragment):
            raise ValueError("Remote media must use HTTPS on a configured Renderhaus bucket host.")
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError("Remote media hosts must resolve to public addresses.")
        try:
            with httpx.Client(follow_redirects=False, timeout=30, trust_env=False) as client:
                with client.stream("GET", asset.source) as response:
                    if response.status_code != 200:
                        raise ValueError("Pinned source media was unavailable; redirects are not followed.")
                    length = response.headers.get("content-length")
                    if length and int(length) > MAX_MEDIA_BYTES:
                        raise ValueError("Pinned source media exceeds the per-file export limit.")
                    yield response.iter_bytes(CHUNK_SIZE)
        except httpx.HTTPError:
            raise ValueError("Pinned source media could not be downloaded.") from None
        return
    source = Path(asset.source).expanduser()
    if not source.is_absolute():
        source = source_root / source
    source = source.resolve()
    if not any(source == root or root in source.parents for root in roots):
        raise ValueError("Local source media must stay inside the configured Renderhaus media roots.")
    if not source.is_file() or source.stat().st_size <= 0:
        raise ValueError("Pinned local source media does not exist or is empty.")
    if source.stat().st_size > MAX_MEDIA_BYTES:
        raise ValueError("Pinned source media exceeds the per-file export limit.")
    with source.open("rb") as media:
        yield iter(lambda: media.read(CHUNK_SIZE), b"")


def build_handoff(snapshot: dict, output_path: Path, *, media_roots: tuple[Path, ...],
                  source_root: Path | None = None,
                  allowed_media_hosts: tuple[str, ...] = ()) -> dict:
    """Write a real ZIP containing all formats and checksum-verified, relative media references."""
    timeline = parse_snapshot(snapshot)
    output_path = Path(output_path)
    roots = tuple(Path(root).resolve() for root in media_roots)
    base = Path(source_root).resolve() if source_root else Path.cwd().resolve()
    if not roots:
        raise ValueError("At least one allowed local media root is required.")
    if output_path.suffix.lower() != ".zip":
        raise ValueError("The handoff destination must have a .zip extension.")
    paths = media_paths(timeline)
    if len(set(paths.values())) != len(paths):
        raise ValueError("Pinned assets produce conflicting archive media paths.")
    aliases = reel_aliases(timeline)
    tracks = track_entries(timeline)
    warnings = list(timeline.warnings)
    for reel, alias in aliases.items():
        if reel != alias:
            warnings.append(f"CMX3600 reel {reel} uses alias {alias}; original identity remains in metadata.")
    files = {"otio": "timeline.otio", "fcpxml": "timeline.fcpxml",
             "edl": [entry["edl"] for entry in tracks]}
    formats = {"timeline.otio": otio_text(timeline, paths),
               "timeline.fcpxml": fcpxml_text(timeline, paths),
               **edl_texts(timeline, paths, aliases)}
    manifest = {
        "schemaVersion": 1, "projectId": timeline.id, "name": timeline.name,
        "frameRate": {"numerator": timeline.rate.value.numerator,
                      "denominator": timeline.rate.value.denominator,
                      "dropFrame": timeline.rate.drop_frame},
        "timecode": timeline.start_timecode, "width": timeline.width, "height": timeline.height,
        "durationInFrames": timeline.duration, "files": files, "tracks": tracks,
        "assets": [], "warnings": warnings,
        "clips": [{"id": clip.id, "assetId": clip.asset_id, "trackId": track.id,
                   "originalTrackId": clip.original_track_id, "recordStartFrame": clip.start,
                   "durationFrames": clip.duration, "sourceInFrames": clip.source_in}
                  for track in timeline.tracks for clip in track.clips],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".nle-", suffix=".zip", dir=output_path.parent)
    os.close(descriptor)
    temporary_path = Path(temporary)
    total_bytes = 0
    try:
        with ZipFile(temporary_path, "w", compression=ZIP_STORED, allowZip64=True) as archive:
            for filename, content in formats.items():
                archive.writestr(filename, content.encode("utf-8"))
            for asset in timeline.assets:
                digest = hashlib.sha256()
                size = 0
                with _source_chunks(asset, roots, base, allowed_media_hosts) as chunks:
                    with archive.open(paths[asset.id], "w", force_zip64=True) as destination:
                        for chunk in chunks:
                            size += len(chunk)
                            total_bytes += len(chunk)
                            if size > MAX_MEDIA_BYTES or total_bytes > MAX_TOTAL_BYTES:
                                raise ValueError("Pinned source media exceeds the handoff export size limit.")
                            digest.update(chunk)
                            destination.write(chunk)
                if size == 0 or digest.hexdigest() != asset.checksum:
                    raise ValueError(f"Pinned source media checksum mismatch for asset {asset.id}.")
                manifest["assets"].append({
                    **asset.metadata(), "kind": asset.kind, "mediaPath": paths[asset.id],
                    "sizeBytes": size, "reelAlias": aliases[asset.reel_name],
                })
            archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return {
        "status": "succeeded", "filename": output_path.name, "output_path": str(output_path),
        "formats": ["otio", "fcpxml", "edl"], "files": files,
        "tracks": tracks, "warnings": warnings, "media_count": len(timeline.assets),
        "media_bytes": total_bytes, "size_bytes": output_path.stat().st_size,
    }
