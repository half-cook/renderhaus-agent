"""Deterministic, bounded dotLottie v1 containers without filesystem extraction."""
from __future__ import annotations

import io
import json
import math
import re
import stat
import zipfile
import zlib

MAX_BYTES = 4 * 1024 * 1024
_ID = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_-]{0,79}')


def _json(payload: bytes):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate JSON object keys are refused.')
            value[key] = item
        return value

    try:
        return json.loads(payload, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Non-finite JSON is refused.')))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('The container contains invalid or excessively nested JSON.') from exc


def _document(document: dict) -> bytes:
    if not isinstance(document, dict):
        raise ValueError('Animation must be a JSON object.')
    if document.get('assets') or document.get('fonts') or document.get('chars'):
        raise ValueError('Container assets and fonts are not bundled by this local packer.')
    for key in ('w', 'h', 'fr', 'ip', 'op'):
        value = document.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'Animation {key} must be a finite number.')
    if (not isinstance(document.get('v'), str) or not isinstance(document.get('layers'), list)
            or not 1 <= document['w'] <= 4096 or not 1 <= document['h'] <= 4096
            or not 1 <= document['fr'] <= 120 or not 0 <= document['ip'] < document['op'] <= 18000):
        raise ValueError('Animation requires bounded Lottie dimensions, frames, fps, version and layers.')
    try:
        payload = json.dumps(document, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError('Animation must be finite bounded JSON.') from exc
    if len(payload) > MAX_BYTES:
        raise ValueError('Animation exceeds the 4 MiB size limit.')
    return payload


def pack_lottie(document: dict, animation_id: str = 'animation') -> bytes:
    """Package one self-contained native animation using reproducible ZIP metadata."""
    if not isinstance(animation_id, str) or not _ID.fullmatch(animation_id):
        raise ValueError('Animation identifier must be 1 to 80 ASCII letters, digits, underscores or hyphens.')
    animation = _document(document)
    manifest = json.dumps({'version': '1.0', 'animations': [{'id': animation_id}]},
                          sort_keys=True, separators=(',', ':')).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, payload in [('manifest.json', manifest), (f'animations/{animation_id}.json', animation)]:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
            if len(payload) > max(1, archive.getinfo(name).compress_size) * 200:
                raise ValueError('Container member compression ratio exceeds limits.')
    if len(output.getvalue()) > MAX_BYTES:
        raise ValueError('Container exceeds the 4 MiB size limit.')
    return output.getvalue()


def unpack_lottie(payload: bytes) -> dict:
    """Read one bounded container in memory, refusing every unrecognized member."""
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_BYTES:
        raise ValueError('Container size must be between 1 byte and 4 MiB.')
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = archive.infolist()
            if len(members) != 2:
                names = [member.filename for member in members]
                if len(set(names)) != len(names):
                    raise ValueError('Container has duplicate members.')
                raise ValueError('Container must contain only the manifest and one animation member.')
            names = [member.filename for member in members]
            if len(set(names)) != len(names):
                raise ValueError('Container has duplicate members.')
            total = 0
            for member in members:
                if (member.filename.startswith('/') or '\\' in member.filename
                        or any(part in {'', '.', '..'} for part in member.filename.split('/'))):
                    raise ValueError('Container member path is unsafe.')
                mode = member.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG) or member.is_dir():
                    raise ValueError('Container members must be regular files.')
                if member.flag_bits & 1 or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise ValueError('Container member encryption or compression is unsupported.')
                total += member.file_size
                if (member.file_size <= 0 or total > MAX_BYTES
                        or member.file_size > max(1, member.compress_size) * 200):
                    raise ValueError('Container member size or compression ratio exceeds limits.')
            if 'manifest.json' not in names:
                raise ValueError('Container manifest member is missing.')
            manifest = _json(archive.read('manifest.json'))
            if (not isinstance(manifest, dict) or set(manifest) != {'version', 'animations'}
                    or manifest.get('version') != '1.0' or not isinstance(manifest.get('animations'), list)
                    or len(manifest['animations']) != 1):
                raise ValueError('Container requires the supported v1 single-animation manifest.')
            animation = manifest['animations'][0]
            if (not isinstance(animation, dict) or set(animation) != {'id'}
                    or not isinstance(animation['id'], str) or not _ID.fullmatch(animation['id'])):
                raise ValueError('Container manifest animation identifier is invalid.')
            name = f"animations/{animation['id']}.json"
            if set(names) != {'manifest.json', name}:
                raise ValueError('Container has an unknown or missing animation member.')
            document = _json(archive.read(name))
            _document(document)
            return document
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, RuntimeError, EOFError, zlib.error) as exc:
        raise ValueError('Invalid dotLottie container.') from exc
