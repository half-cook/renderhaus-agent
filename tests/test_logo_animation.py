"""Synthetic marks only. These tests catch geometry drift, unsafe inputs and approval bypasses."""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import shutil
import socket
import subprocess
import time
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw
import pytest

CASES = json.loads((Path(__file__).parent / 'fixtures/logo_animation/cases.json').read_text())


def logo_api():
    assert importlib.util.find_spec('providers.logo_animation') is not None, 'local logo provider is missing'
    return importlib.import_module('providers.logo_animation.api')


@pytest.fixture
def job(tmp_path, monkeypatch):
    monkeypatch.setenv('RENDERHAUS_MEDIA_DIR', str(tmp_path))
    directory = tmp_path / 'logos'
    directory.mkdir()
    return directory


def source(job, case=CASES[0]):
    bg = (0, 0, 0, 0) if case['background'] == 'transparent' else 'white'
    image = Image.new('RGBA', tuple(case['size']), bg)
    draw = ImageDraw.Draw(image)
    shape, box = case['shape'], case['box']
    if shape == 'triangle':
        draw.polygon([(48, 16), (80, 80), (16, 80)], fill=case['foreground'])
    else:
        getattr(draw, 'ellipse' if shape == 'ring' else shape)(box, fill=case['foreground'])
        if shape == 'ring':
            draw.ellipse((30, 30, 66, 66), fill=(0, 0, 0, 0))
    path = job / (case['name'] + '.png')
    image.save(path)
    return path


def vectorize(job, case=CASES[0]):
    path = source(job, case)
    return logo_api().logo_vectorize('vectorize', 'logos', path.name)


def approved(job, case=CASES[0]):
    result = vectorize(job, case)
    api = logo_api()
    with api.authorize(result['svg_sha256'], 'human:test'):
        receipt = api.logo_vectorize('approve', 'logos', result['svg_path'],
                                    {'sha256': result['svg_sha256'], 'rights_confirmed': True})
    assert receipt['status'] == 'approved'
    return result


@pytest.mark.parametrize('case', CASES, ids=lambda c: c['name'])
def test_local_vectorizer_preserves_synthetic_silhouette_and_has_safe_editable_geometry(job, case):
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
        result = vectorize(job, case)
        audit = result['geometry_qa']
        assert audit['passed'], audit
        assert audit['iou'] >= case['minimum_iou']
        svg = (job / result['svg_path']).read_text()
        root = ET.fromstring(svg)
        assert root.attrib['viewBox'] == f"0 0 {case['size'][0]} {case['size'][1]}"
        assert {node.tag.split('}')[-1] for node in root.iter()} <= {'svg', 'g', 'path', 'rect', 'ellipse'}
        assert all(not attr.startswith('on') for node in root.iter() for attr in node.attrib)
        assert len(svg) < 50_000
        assert (job / result['overlay_path']).is_file()
        assert result['phase'] == 'needs_vector_approval'
        assert result['training_eligible'] is False


def test_render_handoff_requires_real_approval_of_current_vector_and_rights(job):
    api = logo_api()
    result = vectorize(job)
    with pytest.raises(ValueError, match='approval'):
        api.logo_vectorize('choreograph', 'logos', result['svg_path'])
    with pytest.raises(ValueError, match='approval'):
        api.logo_vectorize('approve', 'logos', result['svg_path'],
                           {'sha256': result['svg_sha256'], 'rights_confirmed': True})
    with api.authorize(result['svg_sha256'], 'human:test'):
        with pytest.raises(ValueError, match='rights'):
            api.logo_vectorize('approve', 'logos', result['svg_path'],
                               {'sha256': result['svg_sha256'], 'rights_confirmed': False})
        api.logo_vectorize('approve', 'logos', result['svg_path'],
                           {'sha256': result['svg_sha256'], 'rights_confirmed': True})
    motion = api.logo_vectorize('choreograph', 'logos', result['svg_path'])
    assert motion['template']['name'] == 'logo-animation'
    assert (job / motion['html_path']).is_file()
    assert (job / motion['motion_spec_path']).is_file()
    html = (job / motion['html_path']).read_text()
    assert 'prefers-reduced-motion' in html and 'requestAnimationFrame' in html
    assert not any(word in html.lower().replace('http://www.w3.org/2000/svg', '') for word in ('http:', 'https:', 'fetch(', 'remotion', 'pixel2motion', 'fee', 'fal.ai'))
    path = job / result['svg_path']
    path.write_text(path.read_text().replace('#163f72', '#ff0000'))
    with pytest.raises(ValueError, match='checksum|approval'):
        api.logo_vectorize('choreograph', 'logos', result['svg_path'])


def test_smoothness_and_overlap_reject_bad_geometry_independently(job):
    from providers.logo_animation.geometry import audit_svg, vectorize_image
    original = source(job, CASES[1])
    svg, _ = vectorize_image(original)
    bad = svg.replace('cx="64.5"', 'cx="20"') if 'cx="64.5"' in svg else svg.replace('fill="#dc542a"', 'fill="#000000"')
    bad = '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="96" viewBox="0 0 128 96"><g id="mark"><rect x="1" y="1" width="10" height="10" fill="#dc542a"/></g></svg>'
    assert not audit_svg(bad, original)['passed']
    zig = 'M 10 10 ' + ' '.join(f'L {11+i} {10+i%2}' for i in range(90)) + ' L 10 30 Z'
    jagged = f'<svg xmlns="http://www.w3.org/2000/svg" width="128" height="96" viewBox="0 0 128 96"><g id="mark"><path d="{zig}" fill="#dc542a"/></g></svg>'
    assert not audit_svg(jagged, original)['smoothness']['passed']
    kinked = '<svg xmlns="http://www.w3.org/2000/svg" width="128" height="96" viewBox="0 0 128 96"><g id="mark"><path d="M 10 10 Q 20 10 30 10 Q 30 30 40 30 L 10 30 L 10 10 Z" fill="#dc542a"/></g></svg>'
    assert not audit_svg(kinked, original)['smoothness']['passed']


def test_edited_safe_vector_needs_fresh_overlay_audit_and_new_approval(job):
    result = approved(job)
    path = job/result['svg_path']
    path.write_text(path.read_text().replace('id="mark"', 'id="wordmark"'))
    with pytest.raises(ValueError, match='checksum|approval'):
        logo_api().logo_vectorize('choreograph', 'logos', result['svg_path'])
    audit = logo_api().logo_vectorize('audit', 'logos', result['svg_path'])
    assert audit['geometry_qa']['passed']
    assert audit['svg_sha256'] != result['svg_sha256']
    with pytest.raises(ValueError, match='approval'):
        logo_api().logo_vectorize('choreograph', 'logos', result['svg_path'])


def test_forged_disk_receipt_cannot_authorize_a_vector(job):
    result = vectorize(job)
    path = job/result['svg_path']
    (path.parent/'approval.json').write_text(json.dumps({'svg_sha256':result['svg_sha256'],
        'manifest_sha256':hashlib.sha256((path.parent/'vector.json').read_bytes()).hexdigest(),
        'approved_by':'human:forged', 'rights_confirmed':True, 'signature':'0'*64}))
    with pytest.raises(ValueError, match='trusted receipt'):
        logo_api().logo_vectorize('choreograph', 'logos', result['svg_path'])


def test_approval_checks_the_exact_svg_read_snapshot(job):
    result = approved(job)
    path = job/result['svg_path']
    read = Path.read_bytes
    def swapped_read(target):
        data = read(target)
        return data.replace(b'#163f72', b'#ff0000') if target == path else data
    with patch.object(Path, 'read_bytes', swapped_read), pytest.raises(ValueError, match='checksum'):
        logo_api().logo_vectorize('choreograph', 'logos', result['svg_path'])


@pytest.mark.parametrize('payload', [
    '<svg><script>alert(1)</script></svg>',
    '<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg>&x;</svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" onload="x()"/>',
    '<svg><image href="https://example.com/x.png"/></svg>',
])
def test_svg_parser_rejects_active_or_external_content(payload):
    from providers.logo_animation.geometry import parse_svg
    with pytest.raises(ValueError):
        parse_svg(payload)


@pytest.mark.parametrize('name', ['../private.png', '/etc/passwd', 'https://example.com/logo.png'])
def test_tool_refuses_traversal_urls_and_cross_job_files(job, name):
    with pytest.raises(ValueError):
        logo_api().logo_vectorize('vectorize', 'logos', name)


def test_decoder_refuses_dimensions_bytes_corruption_and_animation(job):
    api = logo_api()
    for name, data in [('big.png', b'x' * (8 * 1024 * 1024 + 1)), ('broken.png', b'not an image')]:
        (job / name).write_bytes(data)
        with pytest.raises(ValueError):
            api.logo_vectorize('vectorize', 'logos', name)
    Image.new('RGB', (2049, 1)).save(job / 'wide.png')
    with pytest.raises(ValueError):
        api.logo_vectorize('vectorize', 'logos', 'wide.png')
    (job / 'link.png').symlink_to('/etc/passwd')
    with pytest.raises(ValueError):
        api.logo_vectorize('vectorize', 'logos', 'link.png')


def test_final_frame_pixel_diff_detects_wrong_color_position_and_dimensions():
    from providers.logo_animation.motion import compare_final
    reference = Image.new('RGB', (64, 64), 'white')
    ImageDraw.Draw(reference).rectangle((16, 16, 48, 48), fill='red')
    assert compare_final(reference, reference.copy())['passed']
    shifted = Image.new('RGB', (64, 64), 'white')
    ImageDraw.Draw(shifted).rectangle((20, 16, 52, 48), fill='red')
    assert not compare_final(reference, shifted)['passed']
    assert not compare_final(reference, Image.new('RGB', (64, 64), 'blue'))['passed']
    assert not compare_final(reference, Image.new('RGB', (32, 32), 'white'))['passed']


def test_declared_easing_probe_detects_linear_fallback_overshoot_and_duration():
    from providers.logo_animation.motion import easing_probe, ease
    samples = [{'time_ms': t, 'value': ease(t / 1000, 'settle')} for t in (0, 250, 500, 750, 1000)]
    assert easing_probe('settle', 1000, samples)['passed']
    assert not easing_probe('settle', 1000, [{'time_ms': t, 'value': t / 1000} for t in (0, 250, 500, 750, 1000)])['passed']
    assert not easing_probe('settle', 1000, [{'time_ms': 0, 'value': 0}, {'time_ms': 1000, 'value': 1.3}])['passed']
    with pytest.raises(ValueError):
        easing_probe('settle', 0, samples)


def test_continuity_probe_detects_transform_and_opacity_pops():
    from providers.logo_animation.motion import continuity_sweep
    samples = [{'part': 'mark', 'time_ms': t, 'x': t / 1000, 'y': 0, 'scale': 1, 'opacity': 1} for t in range(0, 1001, 10)]
    assert continuity_sweep(samples)['passed']
    for field, bad in [('x', 100), ('scale', 2), ('opacity', 0)]:
        changed = copy.deepcopy(samples)
        changed[40][field] = bad
        assert not continuity_sweep(changed)['passed']
    assert not continuity_sweep(samples + [{'part':'accent', 'time_ms':0, 'x':0, 'y':0, 'scale':1, 'opacity':1}])['passed']


@pytest.mark.parametrize('style', ['reveal', 'splash', 'loader', 'idle-hover'])
def test_choreography_plan_has_staged_parts_valid_timing_and_exact_rest_pose(job, style):
    from providers.logo_animation.motion import motion_spec, validate_motion_spec, state_at, render_frame
    from providers.logo_animation.geometry import render_svg
    result = approved(job)
    svg = (job / result['svg_path']).read_text()
    spec = motion_spec(svg, duration_seconds=2, style=style, personality=['precise', 'calm', 'confident'])
    validate_motion_spec(spec)
    assert spec['duration_seconds'] == 2
    assert state_at(spec, 2000)[0]['scale'] == 1
    assert state_at(spec, 2000)[0]['opacity'] == 1
    assert render_frame(svg, spec, 59, 30, 96, 96).size == (96, 96)
    broken = copy.deepcopy(spec)
    broken['timeline'][0]['end_ms'] = 3000
    with pytest.raises(ValueError):
        validate_motion_spec(broken)
    assert render_svg(svg).size == (96, 96)


def test_logo_template_refuses_lambda_and_missing_approval_before_media_io(job, monkeypatch):
    from providers.remotion.api import render_timeline
    from providers.remotion.capabilities import validate_backend
    result = approved(job)
    args = logo_api().logo_vectorize('choreograph', 'logos', result['svg_path'])
    template = args['template']
    with pytest.raises(ValueError, match='local|Lambda|lambda'):
        validate_backend({'template': template}, 'lambda')
    monkeypatch.setenv('REMOTION_DRY_RUN', 'true')
    monkeypatch.setenv('REMOTION_RENDER_BACKEND', 'local')
    assert render_timeline('Logo', template=template, aspect_ratio='1:1')['status'] == 'dry_run'
    template['svg_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='checksum|approval'):
        render_timeline('Logo', template=template)


def test_logo_approval_always_pauses_without_changing_spending_exemptions():
    from agent.gateway_executor import tool_needs_approval, APPROVAL_EXEMPT_TOOLS
    for autonomous in (False, True):
        assert tool_needs_approval('Logo___logo_vectorize', autonomous, {'op': 'approve'})
        assert not tool_needs_approval('Logo___logo_vectorize', autonomous, {'op': 'vectorize'})
    assert APPROVAL_EXEMPT_TOOLS == frozenset({'Remotion___export_nle_timeline'})


def test_rt184_and_nearby_intents_preserve_router_ownership():
    from agent.deep_agent.routing import route_intent
    route = route_intent("Here's our logo PNG, give me a 2-second logo reveal sting for the start of our YouTube videos")
    assert route.skill == 'logo-animation'
    assert [step.alias for step in route.steps] == ['logo_vectorize', 'remotion_render']
    assert not {'wan3_t2v', 'seedance25_t2v', 'gpt_image25_edit'} & {step.alias for step in route.steps}
    assert route_intent('A channel intro sting for my YouTube videos').skill == 'motion-graphics'
    assert route_intent('Create animated lower thirds for our interview').skill == 'motion-graphics'
    assert route_intent('Design me a new logo as an editable SVG vector').skill == 'image-gen'


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='local encoder unavailable')
@pytest.mark.parametrize(('case', 'style'), list(zip(CASES, ['reveal', 'splash', 'loader', 'idle-hover'])), ids=lambda value: value['name'] if isinstance(value, dict) else value)
def test_small_real_local_render_finishes_and_final_frame_gate_reads_actual_mp4(job, monkeypatch, case, style):
    from providers.remotion.templates import build_template_props
    from providers.remotion.local import start_render, get_progress
    result = approved(job, case)
    template = logo_api().logo_vectorize('choreograph', 'logos', result['svg_path'], {'style':style})['template']
    props = build_template_props('Logo', template, audio_tracks=[], aspect_ratio='1:1', fps=24,
                                 output_resolution='source', video_bitrate=None)
    from providers.logo_animation.delivery import logo_template_plan
    props['template'] = logo_template_plan(template, aspect_ratio='1:1', fps=24, width=128, height=128)
    props['renderConfig'].update(width=128, height=128, durationInFrames=48,
        resolution={'width':128,'height':128,'source_resolution':props['template']['source_resolution'],'upscaled':False,'warnings':[]})
    monkeypatch.setenv('REMOTION_DRY_RUN', 'false')
    monkeypatch.setenv('REMOTION_RENDER_BACKEND', 'local')
    queued = start_render(props, output_filename='logo.mp4', media_roots=(job.parent,), source_root=Path(__file__).resolve().parents[1])
    for _ in range(100):
        done = get_progress(queued['render_id'], media_roots=(job.parent,))
        if done['status'] in {'succeeded', 'failed'}:
            break
        time.sleep(.1)
    assert done['status'] == 'succeeded', done
    output = Path(done['output_path'])
    probe = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(output)]))
    video = next(stream for stream in probe['streams'] if stream['codec_type'] == 'video')
    assert (video['width'], video['height']) == (128, 128)
    shutil.copyfile(output, job / 'render.mp4')
    qa = logo_api().logo_vectorize('final_frame', 'logos', 'render.mp4',
        {'svg_path': result['svg_path'], 'template': template})
    assert qa['final_frame']['passed'], qa
    assert qa['output_sha256'] == hashlib.sha256((job/'render.mp4').read_bytes()).hexdigest()
    assert qa['actual_motion']['passed'], qa
    if style == 'reveal':
        from providers.remotion.delivery import qc_deliverable, validate_delivery_report
        delivery = qc_deliverable('logos', 'render.mp4', spec={
            'expected_width':128, 'expected_height':128, 'expected_fps':24,
            'expected_duration_s':2, 'expected_sha256':qa['output_sha256'],
            'expected_filename':'render.mp4',
            'require_audio':False, 'allowed_freeze':[{'start_s':1.2, 'end_s':2}],
            'allowed_black':[{'start_s':0, 'end_s':.6}]})
        assert delivery['passed'], delivery
        assert validate_delivery_report(delivery)
    from providers.logo_animation.motion import render_frame
    render_frame(props['template']['svg'], props['template']['motion_spec'], 0, 24, 128, 128, static=True).save(job/'static.png')
    subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-loop', '1', '-i', str(job/'static.png'),
        '-t', '2', '-r', '24', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(job/'static.mp4')], check=True)
    rejected = logo_api().logo_vectorize('final_frame', 'logos', 'static.mp4',
        {'svg_path': result['svg_path'], 'template': template})
    assert rejected['final_frame']['passed'], rejected
    assert not rejected['actual_motion']['passed']
    assert not rejected['passed']
    from providers.remotion.template_frames import write_template_video
    linear = copy.deepcopy(props['template'])
    for row in linear['motion_spec']['timeline']:
        row['easing'] = 'linear'
    alternative = job/'linear'
    alternative.mkdir()
    produced = write_template_video(linear, alternative)
    shutil.copyfile(produced, job/'linear.mp4')
    rejected = logo_api().logo_vectorize('final_frame', 'logos', 'linear.mp4',
        {'svg_path':result['svg_path'], 'template':template})
    assert not rejected['actual_motion']['passed']
    if style == 'reveal':
        from providers.ffmpeg.api import _bounded_run
        def replace_output_after_probe(argv, *args, **kwargs):
            result = _bounded_run(argv, *args, **kwargs)
            if Path(argv[0]).name == 'ffprobe':
                (job/'render.mp4').write_bytes(b'changed during QA')
            return result
        with patch('providers.ffmpeg.api._bounded_run', side_effect=replace_output_after_probe), pytest.raises(ValueError, match='checksum changed'):
            logo_api().logo_vectorize('final_frame', 'logos', 'render.mp4',
                {'svg_path':result['svg_path'], 'template':template})


def test_preapproval_svg_and_overlay_become_private_studio_assets(job):
    from agent.studio_agent_next import _append_harvested_event, _context_from_request, StudioAgentRequest
    from server import studio
    from server.studio_state import StudioRepository
    repository = StudioRepository(job.parent/'studio.sqlite3', job.parent/'managed')
    repository.ensure_workspace('user:local', 'local')
    def register(**kwargs):
        return studio._register_payload_assets(payload=kwargs['result'], workspace_id='user:local',
            project_id=None, user_id='local', provider='logo_animation')
    context = _context_from_request(StudioAgentRequest(prompt='Animate our logo PNG', job_id='logos'))
    context.asset_registrar = register
    result = vectorize(job)
    with patch.object(studio, 'repository', repository):
        _append_harvested_event(context, call_id='vector', name='Logo___logo_vectorize',
            arguments={'op':'vectorize','job_id':'logos','input_path':'square.png'}, output=result)
    assets = context.tool_events[-1].assets
    assert {asset['filename'] for asset in assets} == {'logo.svg', 'overlay-strip.png'}
    assert all(asset['training_eligible'] is False for asset in assets)


def test_explicit_unavailable_logo_renderer_or_model_is_blocked_without_substitution():
    from agent.deep_agent.routing import route_intent
    for name in ('HyperFrames', 'Seedance 2.5', 'Wan 3', 'Kling'):
        route = route_intent(f'Animate our attached logo PNG with {name}')
        assert route.status == 'blocked', (name, route)
        assert route.tool is None
        assert route.steps == ()


def test_executor_stages_owned_attached_logo_handle_locally(job):
    from types import SimpleNamespace
    from agent.gateway_executor import _local_logo_arguments
    original = source(job)
    outside = job.parent/'owned.png'
    shutil.copyfile(original, outside)
    studio = SimpleNamespace(job_id='logos', source_versions={}, source_resolver=lambda version: str(outside))
    with patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')):
        arguments = _local_logo_arguments(studio, {'op':'vectorize', 'job_id':'logos', 'input_path':'renderhaus-asset://version-1'})
        assert arguments['input_path'] != 'renderhaus-asset://version-1'
        assert (job/arguments['input_path']).read_bytes() == outside.read_bytes()
        assert logo_api().logo_vectorize(**arguments)['geometry_qa']['passed']
