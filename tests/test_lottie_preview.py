from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import shutil
import stat
import subprocess
import zipfile

from PIL import Image
import pytest

from providers.lottie.container import pack_lottie, unpack_lottie
from providers.lottie.preview import render_preview
from providers.lottie.raster import render_frame


def document():
    return {'v': '5.12.2', 'nm': 'Success icon', 'w': 64, 'h': 64, 'ip': 0, 'op': 10,
            'fr': 10, 'assets': [], 'layers': [
                {'ty': 4, 'ind': 1, 'nm': 'Accent square', 'ip': 0, 'op': 10, 'st': 0,
                 'ks': {'p': {'a': 0, 'k': [32, 32]}, 'a': {'a': 0, 'k': [0, 0]},
                        's': {'a': 0, 'k': [100, 100]}, 'r': {'a': 0, 'k': 0},
                        'o': {'a': 0, 'k': 100}},
                 'shapes': [{'ty': 'rc', 'p': {'a': 0, 'k': [0, 0]},
                             's': {'a': 0, 'k': [20, 20]}, 'r': {'a': 0, 'k': 0}},
                            {'ty': 'fl', 'c': {'a': 0, 'k': [1, 0, 0, 1]},
                             'o': {'a': 0, 'k': 100}, 'r': 1}]}]}


def archive(members):
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w') as output:
        for name, data in members:
            output.writestr(name, data)
    return result.getvalue()


def test_container_is_deterministic_and_round_trips():
    payload = pack_lottie(document(), 'success')
    assert payload == pack_lottie(document(), 'success')
    assert unpack_lottie(payload) == document()
    with zipfile.ZipFile(io.BytesIO(payload)) as packed:
        assert packed.namelist() == ['manifest.json', 'animations/success.json']
        manifest = json.loads(packed.read('manifest.json'))
        assert manifest['version'] == '1'
        assert manifest['animations'][0]['id'] == 'success'


@pytest.mark.parametrize('member', ['../outside.json', '/outside.json', 'a/../../b',
                                   'animations\\evil.json', 'images/unexpected.png'])
def test_container_refuses_any_unsafe_or_unknown_member(member):
    packed = pack_lottie(document())
    with zipfile.ZipFile(io.BytesIO(packed)) as source:
        members = [(name, source.read(name)) for name in source.namelist()]
    with pytest.raises(ValueError, match='member|path'):
        unpack_lottie(archive([*members, (member, b'{}')]))


def test_container_refuses_duplicate_symlink_and_unbundled_assets():
    packed = pack_lottie(document())
    with zipfile.ZipFile(io.BytesIO(packed)) as source:
        members = [(name, source.read(name)) for name in source.namelist()]
    with pytest.warns(UserWarning):
        duplicate = archive([*members, members[0]])
    with pytest.raises(ValueError, match='duplicate'):
        unpack_lottie(duplicate)
    target = io.BytesIO()
    with zipfile.ZipFile(target, 'w') as output:
        for name, data in members:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            output.writestr(info, data)
    with pytest.raises(ValueError, match='regular'):
        unpack_lottie(target.getvalue())
    value = document()
    value['assets'] = [{'id': 'asset', 'p': 'picture.png'}]
    with pytest.raises(ValueError, match='assets'):
        pack_lottie(value)


def test_container_refuses_oversized_or_malformed_payload():
    with pytest.raises(ValueError, match='size'):
        unpack_lottie(b'x' * (5 * 1024 * 1024))
    with pytest.raises(ValueError, match='container'):
        unpack_lottie(b'not a zip')
    with pytest.raises(ValueError, match='identifier'):
        pack_lottie(document(), '../evil')


def test_frame_has_transparent_background_and_stable_native_geometry():
    result = render_frame(document(), 0, max_size=64)
    assert result.mode == 'RGBA'
    assert result.size == (64, 64)
    assert result.getpixel((0, 0)) == (0, 0, 0, 0)
    assert result.getpixel((32, 32)) == (255, 0, 0, 255)
    assert result.getbbox() == (22, 22, 43, 43)
    assert hashlib.sha256(result.tobytes()).hexdigest() == 'c15f2d99452189e7cc9ad8d33491b2c7816f40aaeae27bb64b56e25457175319'


def test_native_keyframes_and_easing_change_actual_pixels():
    value = document()
    value['layers'][0]['ks']['p'] = {'a': 1, 'k': [
        {'t': 0, 's': [12, 32], 'o': {'x': .42, 'y': 0}, 'i': {'x': 1, 'y': 1}},
        {'t': 9, 's': [52, 32]}]}
    early = render_frame(value, 3, max_size=64)
    final = render_frame(value, 9, max_size=64)
    assert early.getbbox()[0] < 15
    assert final.getpixel((52, 32)) == (255, 0, 0, 255)
    assert final.getpixel((12, 32)) == (0, 0, 0, 0)


def test_ellipse_and_layer_opacity_composite():
    value = document()
    value['layers'][0]['shapes'][0]['ty'] = 'el'
    value['layers'][0]['shapes'][0].pop('r')
    value['layers'][0]['ks']['o']['k'] = 50
    result = render_frame(value, 5, max_size=64)
    assert result.getpixel((32, 32)) == (255, 0, 0, 128)
    assert result.getpixel((22, 22)) == (0, 0, 0, 0)


def test_native_bezier_trim_reveals_only_the_requested_stroke():
    value = document()
    value['layers'][0]['ks']['p']['k'] = [0, 0]
    value['layers'][0]['shapes'] = [
        {'ty': 'sh', 'ks': {'a': 0, 'k': {'v': [[8, 32], [56, 32]],
            'i': [[0, 0], [0, 0]], 'o': [[0, 0], [0, 0]], 'c': False}}},
        {'ty': 'st', 'c': {'a': 0, 'k': [0, 1, 0, 1]}, 'o': {'a': 0, 'k': 100},
         'w': {'a': 0, 'k': 4}, 'lc': 2, 'lj': 2},
        {'ty': 'tm', 's': {'a': 0, 'k': 0}, 'e': {'a': 0, 'k': 50},
         'o': {'a': 0, 'k': 0}, 'm': 1}]
    result = render_frame(value, 0, max_size=64)
    assert result.getpixel((16, 32)) == (0, 255, 0, 255)
    assert result.getpixel((48, 32)) == (0, 0, 0, 0)


@pytest.mark.parametrize('feature', ['ef', 'masksProperties', 'tt'])
def test_unsupported_features_refuse_the_entire_preview(tmp_path, feature):
    value = document()
    value['layers'][0][feature] = [{'unsupported': True}]
    result = render_preview(value, tmp_path, formats=())
    assert result['ok'] is False
    assert result['not_previewed']
    assert not list(tmp_path.iterdir())
    with pytest.raises(ValueError, match='not previewed'):
        render_frame(value, 0)


def test_preview_has_full_scrubbable_frames_and_contact_sheet(tmp_path):
    result = render_preview(document(), tmp_path, max_size=64, formats=())
    assert result['ok'] is True, result
    records = result['outputs']
    for record in records:
        path = Path(record['path'])
        assert path.is_relative_to(tmp_path)
        assert record['bytes'] == path.stat().st_size
        assert record['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    html = Path(result['scrubber_path']).read_text()
    assert "get('frame')" in html and 'type="range"' in html
    assert 'data:image/png;base64,' in html
    assert 'https://' not in html and 'http://' not in html
    assert len(list(tmp_path.rglob('frame-*.png'))) == 10
    for path in tmp_path.rglob('*.png'):
        with Image.open(path) as actual:
            actual.load()
    assert result['metadata']['frame_count'] == 10


def test_preview_bounds_fail_before_writing(tmp_path):
    value = document()
    value['op'] = 601
    result = render_preview(value, tmp_path, formats=())
    assert result['ok'] is False
    assert '600' in ' '.join(result['errors'])
    assert not list(tmp_path.iterdir())


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='ffmpeg/ffprobe missing')
def test_real_mp4_and_gif_are_readable_with_expected_frames_and_dimensions(tmp_path):
    result = render_preview(document(), tmp_path, max_size=64)
    assert result['ok'] is True, result
    for suffix in ('.mp4', '.gif'):
        target = next(Path(item['path']) for item in result['outputs'] if item['path'].endswith(suffix))
        payload = json.loads(subprocess.check_output([
            'ffprobe', '-v', 'error', '-count_frames', '-show_entries',
            'stream=width,height,nb_read_frames:format=duration', '-of', 'json', str(target)]))
        stream = payload['streams'][0]
        assert (stream['width'], stream['height']) == (64, 64)
        assert int(stream['nb_read_frames']) == 10
        assert abs(float(payload['format']['duration']) - 1) <= .11


def test_container_uses_required_deflate_and_refuses_bombs():
    packed = pack_lottie(document())
    with zipfile.ZipFile(io.BytesIO(packed)) as source:
        assert all(member.compress_type == zipfile.ZIP_DEFLATED for member in source.infolist())
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as target:
        target.writestr('manifest.json', b'x' * (1024 * 1024))
        target.writestr('animations/animation.json', b'{}')
    with pytest.raises(ValueError, match='compression ratio'):
        unpack_lottie(output.getvalue())


def test_group_rotation_parent_and_alpha_are_applied_to_native_geometry():
    value = document()
    shape = value['layers'][0]
    shape['ks']['p']['k'] = [10, 0]
    shape['parent'] = 2
    value['layers'].append({'ty': 3, 'ind': 2, 'ks': {
        'p': {'a': 0, 'k': [32, 32]}, 'r': {'a': 0, 'k': 90}}})
    result = render_frame(value, 0, max_size=64)
    assert result.getpixel((32, 42)) == (255, 0, 0, 255)
    assert result.getpixel((42, 22)) == (0, 0, 0, 0)
    shape['shapes'] = [{'ty': 'gr', 'it': [*shape['shapes'],
        {'ty': 'tr', 'o': {'a': 0, 'k': 50}}]}]
    assert render_frame(value, 0, max_size=64).getpixel((32, 42)) == (255, 0, 0, 128)


def test_unsupported_property_and_multigeometry_are_not_silently_ignored(tmp_path):
    value = document()
    value['layers'][0]['ks']['p']['x'] = 'time * 100'
    assert render_preview(value, tmp_path, formats=())['status'] == 'not_previewed'
    value = document()
    value['layers'][0]['shapes'].insert(0, value['layers'][0]['shapes'][0])
    assert render_preview(value, tmp_path, formats=())['status'] == 'not_previewed'
    assert not list(tmp_path.iterdir())


def test_missing_encoder_leaves_explicitly_incomplete_inspectable_pngs(tmp_path, monkeypatch):
    monkeypatch.setattr('providers.ffmpeg.api.shutil.which', lambda _: None)
    result = render_preview(document(), tmp_path, max_size=64)
    assert result['ok'] is False
    assert result['status'] == 'incomplete'
    assert len(result['errors']) == 2
    assert all('not installed' in item for item in result['errors'])
    assert Path(result['scrubber_path']).is_file()
    assert all(not item['path'].endswith(('.mp4', '.gif')) for item in result['outputs'])


def test_sequence_encoder_refuses_symlinks_leaving_the_job(tmp_path):
    from providers.ffmpeg.api import execute
    outside = tmp_path.parent / (tmp_path.name + '-outside.png')
    Image.new('RGBA', (32, 32)).save(outside)
    (tmp_path / 'frame-000000.png').symlink_to(outside)
    result = execute('image_sequence_preview', tmp_path, 'frame-000000.png')
    assert not result['ok']
    assert 'inside' in result['error']


def test_hidden_layer_expressions_are_still_reported(tmp_path):
    value = document()
    value['layers'][0]['hd'] = True
    value['layers'][0]['ks']['p']['x'] = 'time * 100'
    result = render_preview(value, tmp_path, formats=())
    assert result['status'] == 'not_previewed'
    assert 'expressions' in result['not_previewed'][0]
    assert not list(tmp_path.iterdir())


def test_container_refuses_unresolved_assets_and_excessive_json_depth():
    value = document()
    value['layers'][0]['refId'] = 'missing'
    with pytest.raises(ValueError, match='asset references'):
        pack_lottie(value)
    value = document()
    nested = value
    for _ in range(26):
        nested['extra'] = {}
        nested = nested['extra']
    with pytest.raises(ValueError, match='complexity'):
        pack_lottie(value)


def test_self_contained_precomposition_round_trips_with_v1_metadata():
    value = document()
    value['assets'] = [{'id': 'badge', 'layers': value['layers']}]
    value['layers'] = [{'ty': 0, 'ind': 1, 'nm': 'Badge instance', 'ip': 0, 'op': 10,
                       'ks': {}, 'refId': 'badge'}]
    packed = pack_lottie(value)
    assert unpack_lottie(packed) == value
    with zipfile.ZipFile(io.BytesIO(packed)) as source:
        animation = source.read('animations/animation.json')
    manifest = {'version': '1', 'generator': 'Example app', 'author': 'Asset owner',
                'activeAnimationId': 'animation', 'animations': [{'id': 'animation',
                'loop': True, 'autoplay': False, 'speed': 1.0}]}
    supplied = archive([('manifest.json', json.dumps(manifest)), ('animations/animation.json', animation)])
    assert unpack_lottie(supplied) == value
