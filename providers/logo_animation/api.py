"""Free worker-local logo tools. No network, model, keys, or source uploads."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Literal
import uuid
from fractions import Fraction

import numpy as np
from PIL import Image

from providers.ffmpeg.sandbox import input_file, job_directory, output_records, sha256_file
from providers.logo_animation.contracts import MODELS, request_for
from providers.logo_animation.geometry import audit_svg, overlay_strip, vectorize_image, parse_svg
from providers.logo_animation.motion import (compare_final, continuity_sweep, easing_probe,
    motion_spec, preview_html, render_frame, spec_markdown, state_at)

_AUTHORIZATION: ContextVar[tuple[str, str] | None] = ContextVar('logo_vector_approval', default=None)
# Receipts cannot be authored by an agent. A worker restart deliberately requires fresh review.
_RECEIPT_KEY = os.urandom(32)


@contextmanager
def authorize(sha256: str, approved_by: str):
    token = _AUTHORIZATION.set((sha256, approved_by))
    try:
        yield
    finally:
        _AUTHORIZATION.reset(token)


def _json(path: Path, value: dict) -> None:
    _write_text(path, json.dumps(value, indent=2, allow_nan=False) + '\n')


def _write_text(path: Path, text: str) -> None:
    root = Path(os.getenv('RENDERHAUS_MEDIA_DIR', '.renderhaus/media')).expanduser().resolve()
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError('Logo outputs must stay inside local job storage without symlinks.')
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as writer:
        writer.write(text)


def _signature(payload: dict) -> str:
    return hmac.new(_RECEIPT_KEY, json.dumps(payload, sort_keys=True, allow_nan=False).encode(), hashlib.sha256).hexdigest()


def _outputs(paths: list[Path]) -> list[dict]:
    return [{**record, 'filename': Path(record['path']).name,
             **({'output_path': record['path']} if Path(record['path']).suffix.lower() in {'.svg', '.png'} else {})}
            for record in output_records(paths)]


def vector_bundle(directory: Path, svg_path: str, *, approved=False, refresh=False) -> tuple[str, dict]:
    svg_file = input_file(directory, svg_path, max_bytes=128000)
    manifest_path = svg_file.parent / 'vector.json'
    if manifest_path.is_symlink():
        raise ValueError('Vector review files cannot be symlinks.')
    manifest_file = input_file(directory, str(manifest_path), max_bytes=128000)
    try:
        manifest_bytes = manifest_file.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (ValueError, OSError) as exc:
        raise ValueError('Vector manifest is invalid; repeat vectorization and approval.') from exc
    source = input_file(directory, manifest['source_path'], max_bytes=8*1024*1024)
    source_bytes = source.read_bytes()
    if manifest['source_sha256'] != hashlib.sha256(source_bytes).hexdigest():
        raise ValueError('Vector/source checksum changed; vector approval is invalid.')
    svg_bytes = svg_file.read_bytes()
    if len(svg_bytes) > 128000 or len(manifest_bytes) > 128000:
        raise ValueError('Vector review files exceed their byte bounds.')
    svg_hash = hashlib.sha256(svg_bytes).hexdigest()
    svg = svg_bytes.decode('utf-8')
    geometry = parse_svg(svg)
    audit = audit_svg(svg, source)
    if manifest['svg_sha256'] != svg_hash:
        if not refresh:
            raise ValueError('Vector checksum changed; vector approval is invalid. Run audit before fresh approval.')
        overlay = svg_file.parent / 'overlay-strip.png'
        if overlay.is_symlink() or manifest_file.is_symlink():
            raise ValueError('Vector review files cannot be symlinks.')
        overlay_strip(svg, source).save(overlay)
        manifest.update(svg_sha256=svg_hash, geometry_qa=audit,
                        overlay_sha256=sha256_file(overlay),
                        parts=[{'id': part['id'], 'role': 'wordmark' if part['id'].startswith('wordmark') else 'mark' if index == 0 else 'accent',
                                'paint': 'fill', 'draw_order': index} for index, part in enumerate(geometry['parts'])])
        _json(manifest_file, manifest)
        manifest_bytes = manifest_file.read_bytes()
        (svg_file.parent / 'approval.json').unlink(missing_ok=True)
    if approved:
        receipt_file = input_file(directory, str(svg_file.parent / 'approval.json'), max_bytes=4096) if (svg_file.parent / 'approval.json').exists() else None
        if receipt_file is None:
            raise ValueError('Static vector approval is required before choreography or rendering.')
        receipt = json.loads(receipt_file.read_text())
        signature = receipt.pop('signature', '')
        if not hmac.compare_digest(signature, _signature(receipt)) or receipt.get('svg_sha256') != svg_hash or receipt.get('manifest_sha256') != hashlib.sha256(manifest_bytes).hexdigest():
            raise ValueError('Static vector approval checksum or trusted receipt is invalid. Review again after a worker restart.')
        if not audit['passed']:
            raise ValueError('Approved vector no longer passes geometry QA.')
    return svg, {**manifest, '_manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest()}


def _final_frame(directory: Path, source: Path, params: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix='logo-qa-', dir=directory) as temporary:
        snapshot = Path(temporary)/source.name
        with source.open('rb') as reader, snapshot.open('xb') as writer:
            total = 0
            while chunk := reader.read(1024*1024):
                total += len(chunk)
                if total > 128*1024*1024:
                    raise ValueError('Logo QA input exceeds 128 MiB.')
                writer.write(chunk)
        return _inspect_final_frame(directory, snapshot, params, original=source)


def _inspect_final_frame(directory: Path, source: Path, params: dict, *, original: Path) -> dict:
    from providers.logo_animation.delivery import logo_template_plan
    from providers.ffmpeg.api import _bounded_run

    template = params['template']
    if template.get('logo_job_id') != directory.name or template.get('logo_path') != params['svg_path']:
        raise ValueError('Final-frame template must reference the same owned approved vector.')
    svg, manifest = vector_bundle(directory, params['svg_path'], approved=True)
    compressed = source.suffix.lower() == '.mp4'
    actual_motion = {'passed': False, 'failures': ['Observed motion requires the rendered MP4.']}
    if compressed:
        encoder, prober = shutil.which('ffmpeg'), shutil.which('ffprobe')
        if not encoder or not prober:
            raise ValueError('Final-frame MP4 verification requires the local encoder and probe.')
        probe = _bounded_run([prober, '-v', 'error', '-protocol_whitelist', 'file,pipe',
            '-f', 'mov', '-show_streams', '-of', 'json', str(source)], directory, 15)
        if probe.returncode or probe.stdout_truncated:
            raise ValueError('Final-frame media probe failed.')
        streams = json.loads(probe.stdout)['streams']
        video = next((s for s in streams if s.get('codec_type') == 'video'), None)
        if not video:
            raise ValueError('Final-frame source has no video.')
        width, height = int(video['width']), int(video['height'])
        if max(width, height) > 2048 or width*height > 4_194_304:
            raise ValueError('Final-frame canvas exceeds local bounds.')
        duration = float(video.get('duration', 0))
        if abs(duration-template['duration_seconds']) > .1:
            raise ValueError('Final-frame output duration differs from the approved motion specification.')
        target = source.parent / ('logo-final-' + uuid.uuid4().hex + '.png')
        decoded = _bounded_run([encoder, '-v', 'error', '-nostdin', '-y', '-protocol_whitelist', 'file,pipe',
            '-f', 'mov', '-i', str(source), '-an', '-update', '1', str(target)], directory, 30)
        if decoded.returncode or not target.is_file():
            raise ValueError('Final-frame decode failed.')
        with Image.open(target) as image:
            observed = image.convert('RGB')
        target.unlink()
    else:
        from providers.logo_animation.geometry import decode
        observed = decode(source).convert('RGB')
        width, height = observed.size
    plan = logo_template_plan(template, aspect_ratio='1:1', fps=30, width=width, height=height)
    spec = plan['motion_spec']
    if compressed:
        fps = float(Fraction(video['r_frame_rate']))
        frames = round(duration*fps)
        if not 12 <= fps <= 60 or not 1 <= frames <= 180:
            raise ValueError('Observed motion requires 12..60 fps and at most 180 frames.')
        thumb_size = 40
        decoded = _bounded_run([encoder, '-v', 'error', '-nostdin', '-protocol_whitelist', 'file,pipe',
            '-f', 'mov', '-i', str(source), '-vf', f'scale={thumb_size}:{thumb_size}', '-an', '-f', 'rawvideo',
            '-pix_fmt', 'rgb24', 'pipe:1'], directory, 30)
        frame_bytes = thumb_size*thumb_size*3
        if decoded.returncode or decoded.stdout_truncated or len(decoded.stdout) != frames*frame_bytes:
            raise ValueError('Observed motion decode was incomplete or exceeded its bounds.')
        errors, jumps, expected_jumps = [], [], []
        observed_frames, expected_frames, linear_frames = [], [], []
        linear_spec = copy.deepcopy(spec)
        for row in linear_spec['timeline']:
            row['easing'] = 'linear'
        previous_observed = previous_expected = None
        for index in range(frames):
            observed_frame = np.frombuffer(decoded.stdout[index*frame_bytes:(index+1)*frame_bytes], dtype=np.uint8).astype(float)
            expected_image = render_frame(svg, spec, index, fps, width, height, plan['background_color'])
            expected_frame = np.asarray(expected_image.resize((thumb_size, thumb_size), Image.Resampling.BICUBIC)).reshape(-1).astype(float)
            linear_image = render_frame(svg, linear_spec, index, fps, width, height, plan['background_color'])
            linear_frame = np.asarray(linear_image.resize((thumb_size, thumb_size), Image.Resampling.BICUBIC)).reshape(-1).astype(float)
            observed_frames.append(observed_frame)
            expected_frames.append(expected_frame)
            linear_frames.append(linear_frame)
            errors.append(float(np.abs(observed_frame-expected_frame).mean()))
            if previous_observed is not None:
                jumps.append(float(np.abs(observed_frame-previous_observed).mean()))
                expected_jumps.append(float(np.abs(expected_frame-previous_expected).mean()))
            previous_observed, previous_expected = observed_frame, expected_frame
        jump_error = max((abs(a-b) for a, b in zip(jumps, expected_jumps)), default=0)
        observed_array, expected_array, linear_array = map(np.asarray, (observed_frames, expected_frames, linear_frames))
        expected_energy = float(np.ptp(expected_array, axis=0).mean())
        observed_energy = float(np.ptp(observed_array, axis=0).mean())
        energy_ratio = observed_energy/max(.001, expected_energy)
        observed_delta = observed_array-observed_array[-1]
        correct_loss = float(np.abs(observed_delta-(expected_array-expected_array[-1])).mean())
        linear_loss = float(np.abs(observed_delta-(linear_array-linear_array[-1])).mean())
        motion_passed = (max(errors) <= 3.5 and jump_error <= 2.5 and expected_energy >= .05
                         and .4 <= energy_ratio <= 2.2 and correct_loss <= linear_loss*.85)
        actual_motion = {'passed': motion_passed, 'frames_checked': frames,
            'maximum_frame_error': round(max(errors), 6), 'maximum_jump_error': round(jump_error, 6),
            'expected_motion_energy': round(expected_energy, 6), 'observed_motion_energy': round(observed_energy, 6),
            'energy_ratio': round(energy_ratio, 6), 'declared_easing_loss': round(correct_loss, 6),
            'linear_fallback_loss': round(linear_loss, 6),
            'failures': [] if motion_passed else ['Decoded motion differs from the declared easing or contains a continuity pop.']}
    reference = render_frame(svg, spec, 0, 30, width, height, plan['background_color'], static=True)
    final = compare_final(reference, observed, compressed=compressed)
    authored = compare_final(reference, render_frame(svg, spec, 89, 30, width, height, plan['background_color']))
    samples = []
    for t in range(0, round(spec['duration_seconds']*1000)+1, 10):
        samples.extend({**state, 'time_ms': t} for state in state_at(spec, t))
    continuity = continuity_sweep(samples)
    easing = easing_probe('settle', 1000, [{'time_ms': t, 'value': t*t*(3-2*t/1000)/1_000_000} for t in (0, 250, 500, 750, 1000)])
    report = {'passed': final['passed'] and authored['passed'] and continuity['passed'] and easing['passed'] and actual_motion['passed'],
              'final_frame': final, 'authored_final_frame': authored, 'continuity': continuity,
              'actual_motion': actual_motion,
              'declared_easing': easing, 'output_sha256': sha256_file(source),
              'svg_sha256': manifest['svg_sha256'],
              'motion_spec_sha256': hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest(),
              'failures': final.get('failures', []) + authored.get('failures', []) + continuity['failures'] + easing['failures'] + actual_motion['failures'],
              'visual_review': 'pending; inspect complete playback and final frame'}
    if sha256_file(original) != report['output_sha256']:
        raise ValueError('Output checksum changed during logo QA. Check the current artifact again.')
    report_path = original.parent / ('logo-qc-' + uuid.uuid4().hex + '.json')
    _json(report_path, report)
    return {**report, 'report_path': str(report_path.relative_to(directory)), 'outputs': output_records([report_path])}


def logo_vectorize(op: Literal['vectorize', 'audit', 'approve', 'choreograph', 'final_frame', 'easing', 'continuity'],
                   job_id: str, input_path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Prepare and verify owned logo geometry and motion locally; approve pauses for static-vector review."""
    op, options = request_for({'op': op, 'job_id': job_id, 'input_path': input_path, 'params': params})
    directory = job_directory(job_id)
    source = input_file(directory, input_path, max_bytes=128*1024*1024 if op == 'final_frame' else 8*1024*1024)
    base = {'op': op, 'estimated_cost_usd': 0, 'training_eligible': False, 'label': 'Logo motion'}
    if op == 'easing':
        return {**base, **easing_probe(options['token'], options['duration_ms'], options['samples'])}
    if op == 'continuity':
        return {**base, **continuity_sweep(options['samples'])}
    if op == 'vectorize':
        svg, structure = vectorize_image(source, options['palette_size'])
        audit = audit_svg(svg, source)
        bundle = directory / ('logo-' + uuid.uuid4().hex)
        bundle.mkdir(mode=0o700)
        svg_file, overlay = bundle / 'logo.svg', bundle / 'overlay-strip.png'
        _write_text(svg_file, svg)
        overlay_strip(svg, source).save(overlay)
        manifest = {**structure, 'source_path': str(source.relative_to(directory)), 'source_sha256': sha256_file(source),
                    'svg_sha256': sha256_file(svg_file), 'geometry_qa': audit,
                    'overlay_sha256': sha256_file(overlay)}
        _json(bundle / 'vector.json', manifest)
        return {**base, **manifest, 'status': 'succeeded',
                'phase': 'needs_vector_approval' if audit['passed'] else 'geometry_failed',
                'svg_path': str(svg_file.relative_to(directory)), 'overlay_path': str(overlay.relative_to(directory)),
                'outputs': _outputs([svg_file, overlay, bundle / 'vector.json'])}
    if op == 'final_frame':
        return {**base, **_final_frame(directory, source, options)}
    svg, manifest = vector_bundle(directory, input_path, approved=op == 'choreograph', refresh=op == 'audit')
    audit = audit_svg(svg, input_file(directory, manifest['source_path']))
    if op == 'audit':
        return {**base, 'status': 'succeeded', 'geometry_qa': audit, 'svg_sha256': manifest['svg_sha256'],
                'parts': manifest['parts'], 'overlay_path': str((source.parent/'overlay-strip.png').relative_to(directory)),
                'outputs': _outputs([source, source.parent/'overlay-strip.png', source.parent/'vector.json'])}
    if op == 'approve':
        authorization = _AUTHORIZATION.get()
        if authorization is None or authorization[0] != options['sha256'] or not authorization[1]:
            raise ValueError('Native human approval of this exact vector is required, including autonomous runs.')
        if options['rights_confirmed'] is not True:
            raise ValueError('Confirm rights to animate this mark before vector approval.')
        if options['sha256'] != manifest['svg_sha256'] or not audit['passed']:
            raise ValueError('Vector checksum or geometry QA failed; approval was not saved.')
        overlay = input_file(directory, str(source.parent / 'overlay-strip.png'))
        if sha256_file(overlay) != manifest['overlay_sha256']:
            raise ValueError('Review overlay checksum changed; approval was not saved.')
        receipt = {'svg_sha256': manifest['svg_sha256'], 'manifest_sha256': manifest['_manifest_sha256'],
                   'approved_by': authorization[1], 'rights_confirmed': True}
        _json(source.parent / 'approval.json', {**receipt, 'signature': _signature(receipt)})
        return {**base, 'status': 'approved', 'svg_sha256': manifest['svg_sha256']}
    spec = motion_spec(svg, **{k: options[k] for k in ('duration_seconds', 'style', 'personality', 'idle_loop')})
    spec_hash = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    motion_dir = source.parent / ('motion-' + spec_hash[:16])
    if motion_dir.is_symlink():
        raise ValueError('Logo motion outputs cannot use a symlink directory.')
    motion_dir.mkdir(exist_ok=True)
    html_file, markdown = motion_dir / 'preview.html', motion_dir / 'motion_spec.md'
    _write_text(html_file, preview_html(svg, spec, options['background_color']))
    _write_text(markdown, spec_markdown(spec))
    _json(motion_dir / 'motion_spec.json', spec)
    template = {'name': 'logo-animation', 'logo_job_id': job_id, 'logo_path': input_path,
                'svg_sha256': manifest['svg_sha256'], **options}
    return {**base, 'status': 'succeeded', 'phase': 'ready_for_local_render', 'template': template,
            'html_path': str(html_file.relative_to(directory)), 'motion_spec_path': str(markdown.relative_to(directory)),
            'motion_spec': spec, 'outputs': _outputs([html_file, markdown, motion_dir / 'motion_spec.json'])}


TOOL_HANDLERS = {'logo_vectorize': logo_vectorize}
GATEWAY_TOOLS = tuple(TOOL_HANDLERS)


def _schema():
    properties = {}
    for model in MODELS.values():
        for key, value in model.model_json_schema().get('properties', {}).items():
            if key == 'samples':
                properties[key] = {'type': 'array', 'items': {'type': 'object', 'properties': {
                    name: {'type': kind} for name, kind in [('part', 'string'), ('time_ms', 'number'),
                    ('value', 'number'), ('x', 'number'), ('y', 'number'), ('scale', 'number'), ('opacity', 'number')]}}}
            else:
                properties[key] = value
    return [{'name': 'logo_vectorize', 'description': 'Prepare logo geometry and motion privately on the local worker. Review the source/overlay/vector strip and smoothness audit before approve. Native review always pauses. No external requests.',
        'inputSchema': {'type': 'object', 'properties': {
            'op': {'type': 'string', 'description': 'Allowed values: vectorize, audit, approve, choreograph, final_frame, easing, continuity.'},
            'job_id': {'type': 'string', 'description': 'Trusted current job identifier.'},
            'input_path': {'type': 'string', 'description': 'Owned job-relative PNG/JPEG for vectorize, logo.svg for audit/approve/choreograph, rendered MP4/PNG for final_frame. Probes use an existing owned reference file.'},
            'params': {'type': 'object', 'properties': properties, 'description': 'Operation-specific strict contract. approve requires sha256 and rights_confirmed; choreograph accepts duration_seconds 1..3, style, personality, idle_loop, background_color; final_frame requires svg_path and exact returned template; probes require observed samples.'}},
        'required': ['op', 'job_id', 'input_path']}}]


GATEWAY_SCHEMAS = _schema()
