from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from providers.ffmpeg.sandbox import (
    input_file, job_directory, output_file, output_records, validate_job_id,
)
from providers.lottie.authoring import author_document, patch_document
from providers.lottie.container import pack_lottie, unpack_lottie
from providers.lottie.contracts import owned_input_placeholders, request_for, tool_schema
from providers.lottie.svg import svg_document
from providers.lottie.validation import TARGETS, validate_document


MAX_JSON_BYTES = 8 * 1024 * 1024


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Animation JSON contains duplicate keys.')
        result[key] = value
    return result


def _read(directory: Path, value: str) -> tuple[dict, str]:
    source = input_file(directory, value, max_bytes=MAX_JSON_BYTES)
    data = source.read_bytes()
    checksum = hashlib.sha256(data).hexdigest()
    if source.suffix == '.lottie':
        return unpack_lottie(data), checksum
    if source.suffix != '.json':
        raise ValueError('Animation input must be a .json or .lottie file.')
    document = json.loads(data, object_pairs_hook=_unique_keys)
    if not isinstance(document, dict):
        raise ValueError('Animation JSON must contain an object.')
    return document, checksum


def _author_directory(job_id: str) -> Path:
    validate_job_id(job_id)
    root = Path(os.getenv('RENDERHAUS_MEDIA_DIR', '.renderhaus/media')).expanduser().resolve()
    directory = root / job_id
    if directory.is_symlink() or not directory.resolve().is_relative_to(root):
        raise ValueError('Animation job directory must stay inside the media root without symlinks.')
    directory.mkdir(parents=True, exist_ok=True)
    return job_directory(job_id)


def stage_owned_inputs(tool: str, arguments: dict, resolver: Callable[[str], str] | None) -> dict:
    """Stage owned Studio asset handles before applying the confined provider contract."""
    references = {field: arguments[field] for field in ('svg_path', 'input_path')
                  if isinstance(arguments.get(field), str)
                  and arguments[field].startswith('renderhaus-asset://')}
    if not references:
        return arguments
    if resolver is None:
        raise ValueError('Animation asset staging requires the owned Studio asset resolver.')
    prepared = owned_input_placeholders(arguments)
    request = request_for(tool, prepared)
    written: list[Path] = []
    try:
        sources = []
        for field, reference in references.items():
            version_id = reference.removeprefix('renderhaus-asset://')
            if not version_id:
                raise ValueError('Animation asset reference must include its owned version ID.')
            source = Path(resolver(version_id))
            suffix = '.svg' if field == 'svg_path' else source.suffix
            if suffix not in {'.svg', '.json', '.lottie'} or field == 'input_path' and suffix == '.svg':
                raise ValueError('Animation input assets must be JSON or dotLottie; use svg_path for SVG.')
            maximum = 1024 * 1024 if field == 'svg_path' else MAX_JSON_BYTES
            with source.open('rb') as stream:
                payload = stream.read(maximum + 1)
            if not payload or len(payload) > maximum:
                raise ValueError('Owned animation asset is empty or exceeds its input size limit.')
            sources.append((field, suffix, payload))
        directory = _author_directory(request.job_id)
        for field, suffix, payload in sources:
            destination = output_file(directory, 'owned-animation-source', suffix)
            with destination.open('xb') as stream:
                written.append(destination)
                stream.write(payload)
            prepared[field] = str(destination)
        return prepared
    except (OSError, ValueError, KeyError):
        for destination in written:
            destination.unlink(missing_ok=True)
        raise


def _downloads(records: list[dict]) -> list[dict]:
    return [{**record, 'output_path': record['path'],
             'download_url': '/api/studio/media?path=' + quote(record['path'], safe='')}
            for record in records]


def _failure(message: str, *, validation: dict | None = None) -> dict:
    return {'ok': False, 'status': 'failed', 'errors': [message], 'outputs': [],
            **({'validation': validation} if validation is not None else {})}


def _error(exc: Exception) -> str:
    return str(exc) if isinstance(exc, ValueError) else 'Animation files could not be read or written.'


def lottie_author(job_id: str, scene: dict | None = None, lottie: dict | None = None,
                  input_path: str | None = None, svg_path: str | None = None,
                  patch: dict | None = None, name: str = 'animation') -> dict:
    """Create or revise a UI vector animation and save validated JSON and dotLottie files."""
    written: list[Path] = []
    try:
        request = request_for('lottie_author', dict(job_id=job_id, scene=scene, lottie=lottie,
                              input_path=input_path, svg_path=svg_path, patch=patch, name=name))
        if request.scene is not None:
            document = author_document(request.scene)
        elif request.lottie is not None:
            document = request.lottie
        else:
            directory = job_directory(request.job_id)
            if request.svg_path is not None:
                source = input_file(directory, request.svg_path, max_bytes=1024 * 1024)
                document = svg_document(source.read_bytes(), name=request.name)
            else:
                document, _ = _read(directory, request.input_path)
        if request.patch is not None:
            document = patch_document(document, request.patch)
        validation = validate_document(document)
        if not validation['ok']:
            return _failure('; '.join(validation['errors']), validation=validation)
        data = json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        if len(data) > MAX_JSON_BYTES:
            raise ValueError('Animation JSON exceeds 8 MiB.')
        packed = pack_lottie(document, animation_id=request.name)
        directory = _author_directory(request.job_id)
        for suffix, payload in (('.json', data), ('.lottie', packed)):
            destination = output_file(directory, request.name, suffix)
            with destination.open('xb') as stream:
                written.append(destination)
                stream.write(payload)
        records = _downloads(output_records(written))
        json_name = written[0].name
        usage = {
            'web': "import lottie from 'lottie-web'; lottie.loadAnimation({container: document.getElementById('animation'), renderer: 'svg', loop: true, autoplay: true, path: '" + json_name + "'});",
            'ios': 'Bundle ' + json_name + '; use LottieAnimationView(name: "' + written[0].stem + '").play() after adding Lottie for iOS.',
            'android': 'Place ' + json_name + ' in assets; use animationView.setAnimation("' + json_name + '"); animationView.playAnimation() after adding Lottie for Android.',
        }
        return {'ok': True, 'status': 'succeeded', 'outputs': records,
                'metadata': validation['metadata'], 'validation': validation, 'usage': usage,
                'summary': 'Saved animation JSON and dotLottie. Review compatibility and preview before use.'}
    except (ValueError, OSError, TypeError, KeyError, RecursionError) as exc:
        for destination in written:
            destination.unlink(missing_ok=True)
        return _failure(_error(exc))


def lottie_validate(job_id: str, input_path: str, targets: list[str] | None = None) -> dict:
    """Check animation structure and target player compatibility without model calls."""
    try:
        request = request_for('lottie_validate', locals())
        directory = job_directory(request.job_id)
        document, checksum = _read(directory, request.input_path)
        checked = validate_document(document, tuple(request.targets or TARGETS))
        return {**checked, 'status': 'succeeded' if checked['ok'] else 'failed', 'outputs': [],
                'source_sha256': checksum}
    except (ValueError, OSError, TypeError, KeyError, RecursionError) as exc:
        return _failure(_error(exc))


def lottie_preview_render(job_id: str, input_path: str, max_size: int = 256,
                          formats: list[str] | None = None) -> dict:
    """Render bounded PNG, scrubbable HTML and MP4/GIF animation previews locally."""
    try:
        request = request_for('lottie_preview_render', locals())
        directory = job_directory(request.job_id)
        document, checksum = _read(directory, request.input_path)
        checked = validate_document(document)
        if not checked['ok']:
            return _failure('; '.join(checked['errors']), validation=checked)
        if checked['not_previewed']:
            return {'ok': False, 'status': 'not_previewed', 'complete': False, 'outputs': [],
                    'errors': ['This animation uses features outside the local preview subset.'],
                    'not_previewed': checked['not_previewed'], 'validation': checked}
        from providers.lottie.preview import render_preview

        result = render_preview(document, directory, max_size=request.max_size,
                                formats=tuple(request.formats) if request.formats is not None else ('mp4', 'gif'))
        frames = [row for row in result.get('outputs', []) if Path(row['path']).name.startswith('frame-')]
        result['frame_files'] = len(frames)
        result['outputs'] = _downloads([row for row in result.get('outputs', []) if row not in frames])
        result['source_sha256'] = checksum
        result['validation'] = checked
        result['preview_metadata'] = result.get('metadata', {})
        result['metadata'] = checked['metadata']
        return result
    except (ValueError, OSError, TypeError, KeyError, RecursionError) as exc:
        return _failure(_error(exc))


TOOL_HANDLERS = {fn.__name__: fn for fn in (lottie_author, lottie_validate, lottie_preview_render)}
GATEWAY_TOOLS = tuple(TOOL_HANDLERS)
GATEWAY_SCHEMAS = [tool_schema(name) for name in GATEWAY_TOOLS]
