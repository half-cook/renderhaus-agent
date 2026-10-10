"""Timeline capabilities and preflight shared by local workers and Gateway Lambda.

Lambda support means request/composition support, not a verified deployed render.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
import re
from typing import Any, Literal

Status = Literal['supported', 'refused-with-explicit-error', 'unsupported-but-silently-ignored']
Backend = Literal['local', 'lambda']
VERIFIED_DATE = '2026-10-10'
SUPPORTED = 'supported'
REFUSED = 'refused-with-explicit-error'


@dataclass(frozen=True)
class Capability:
    fields: tuple[str, ...]
    local: Status = SUPPORTED
    lambda_: Status = SUPPORTED
    note: str = ''
    overlay_v2: bool = False
    tools: tuple[str, ...] = ('render_timeline',)

    def status(self, backend: Backend, overlay_version: str = '1') -> Status:
        if backend == 'lambda' and self.overlay_v2 and overlay_version == '2':
            return SUPPORTED
        return self.local if backend == 'local' else self.lambda_


CAPABILITIES = {
    'identity': Capability(('title', 'output_filename', 'visuals.kind', 'visuals.url', 'visuals.output_path')),
    'clip_timing': Capability(('visuals.start_seconds', 'visuals.duration_seconds', 'visuals.source_in_seconds')),
    'speed': Capability(('visuals.playback_rate',), note='Video only; local source audio uses atempo.'),
    'source_metadata': Capability(('visuals.source_fps', 'visuals.source_bitrate'), note='Measured video metadata only.'),
    'layers': Capability(('visuals.track',), note='Ordered video/image tracks, later tracks composite above earlier ones.'),
    'transitions': Capability(('visuals.transition',), note='cut, fade and dip_to_black use item fades; no overlap cross-dissolve.'),
    'fit_position': Capability(('visuals.fit', 'visuals.position_x', 'visuals.position_y'), note='cover/contain on both; pad_blur requires local/worker.'),
    'scale': Capability(('visuals.scale',), note='Static centre scale 0.1..4; box clips at its edges.'),
    'rotation': Capability(('visuals.rotation_degrees',), note='Centre rotation -360..360 degrees, clipped at viewport.'),
    'motion': Capability(('visuals.motion',), note='none, linear zoom_in/zoom_out 8%, pan_left/pan_right +/-4% with 8% zoom. Arbitrary keyframes refused.'),
    'grade': Capability(('visuals.grade',), note='none, neutral, warm; fixed media-only filters. CSS/ffmpeg color pixel parity UNVERIFIED.'),
    'opacity_fades': Capability(('visuals.opacity', 'visuals.fade_in_seconds', 'visuals.fade_out_seconds')),
    'source_audio': Capability(('visuals.volume', 'visuals.audio_fade_in_seconds', 'visuals.audio_fade_out_seconds')),
    'audio_mix': Capability(tuple('audio_tracks.' + field for field in (
        'url', 'output_path', 'start_seconds', 'duration_seconds', 'source_in_seconds', 'volume',
        'fade_in_seconds', 'fade_out_seconds')), note='Trim, delay, volume, fades and mix; clamped to visual end.'),
    'titles': Capability(tuple('text_overlays.' + field for field in (
        'text', 'start_seconds', 'duration_seconds', 'position', 'font_size', 'font_weight', 'color',
        'background_color', 'opacity', 'fade_in_seconds', 'fade_out_seconds')),
        note='Local fonts have weights 400/700, named/hex colors and fit guards. Other CSS colors/weights require Lambda. Legacy fonts/pixels UNVERIFIED.'),
    'captions': Capability(tuple('subtitles.' + field for field in (
        'text', 'start_seconds', 'duration_seconds', 'position', 'font_size', 'font_weight', 'color',
        'background_color', 'opacity', 'fade_in_seconds', 'fade_out_seconds')),
        note='Output-timed literal burn-in text after all overlays; same local text restrictions as titles.'),
    'srt_captions': Capability(('subtitles_srt',), note='Inline numbered SRT, no file/URL, no styling or filter commands.'),
    'fitted_overlays': Capability(('visuals.box', *tuple(prefix + field for prefix in ('text_overlays.', 'subtitles.')
        for field in ('box', 'min_font_size', 'max_font_size', 'font_family'))),
        lambda_=REFUSED, overlay_v2=True,
        note='Lambda requires overlay contract version 2 with matching font assets; use local/worker until deployed.'),
    'crop_reframe': Capability(('visuals.crop_box', 'visuals.pad_box', 'visuals.reframe_size', 'visuals.allow_upscale'),
        lambda_=REFUSED, note='Lambda reframing is not deployed; use the local/worker backend for crop_box and pad_blur.'),
    'canvas': Capability(('aspect_ratio', 'output_resolution'), note='Source-native policy; explicit tiers report resampling with no added detail.'),
    'encoding': Capability(('fps', 'video_bitrate'), note='MP4/H.264, CFR, AAC when audio exists; no caller-selected codec or filtergraph.'),
    'blurred_padding': Capability((), lambda_=REFUSED,
        note='Lambda reframing is not deployed; use the local/worker backend for crop_box and pad_blur.'),
    'css_text_styles': Capability((), local=REFUSED,
        note='Local supports hex/named colors and weights 400/700; other CSS styles require Lambda.'),
    'arbitrary_keyframes': Capability((), local=REFUSED, lambda_=REFUSED,
        note='Neither backend accepts arbitrary render keyframes. Use named motion presets on local or Lambda.'),
    'nle_cuts_gaps': Capability((), tools=('export_nle_timeline', 'import_nle_timeline'),
        note='In-house OTIO/FCPXML/EDL handoff; bake effects, text, transitions and retimes first. No AAF or Resolve API.'),
    'transcript_edit': Capability((), tools=('prepare_conversational_edit',),
        note='Pure word-range edit preview, grade and captions compiled to render_timeline args; no media I/O.'),
    'ad_matrix': Capability((), lambda_=REFUSED, tools=('render_ad_variants',),
        note='Owned local/worker job, unchanged plan hash and sample/batch approval; Lambda refuses.'),
    'delivery_qc': Capability((), lambda_=REFUSED, tools=('deliver_render', 'qc_deliverable'),
        note='Owned local/worker files and binaries; Lambda refuses. No upload/publishing or arbitrary codecs.'),
    'motion_carry_qc': Capability((), lambda_=REFUSED, tools=('motion_carry_probe',),
        note='Local/worker binary QC only; keyframe boxes describe measurement, never render animation.'),
    'progress': Capability((), tools=('get_render_progress',), note='Poll saved backend-specific render ID; no replacement render.'),
}

CLIP_FIELDS = {
    'start': 'start_seconds', 'duration': 'duration_seconds', 'sourceIn': 'source_in_seconds',
    'playbackRate': 'playback_rate', 'positionX': 'position_x', 'positionY': 'position_y',
    'rotation': 'rotation_degrees', 'fadeIn': 'fade_in_seconds', 'fadeOut': 'fade_out_seconds',
    'audioFadeIn': 'audio_fade_in_seconds', 'audioFadeOut': 'audio_fade_out_seconds',
    'cropBox': 'crop_box', 'padBox': 'pad_box', 'reframeSize': 'reframe_size', 'allowUpscale': 'allow_upscale',
    **{field: field for field in ('fit', 'scale', 'opacity', 'volume', 'motion', 'grade', 'box', 'transition')},
}
TEXT_FIELDS = {
    'start': 'start_seconds', 'duration': 'duration_seconds', 'fontSize': 'font_size',
    'fontWeight': 'font_weight', 'backgroundColor': 'background_color', 'fadeIn': 'fade_in_seconds',
    'fadeOut': 'fade_out_seconds', 'fontFamily': 'font_family', 'minFontSize': 'min_font_size',
    'maxFontSize': 'max_font_size', **{field: field for field in ('text', 'position', 'color', 'opacity', 'box')},
}

PRESETS = {
    'visuals.kind': ('image', 'video'),
    'visuals.transition': ('cut', 'fade', 'dip_to_black'),
    'visuals.fit': ('cover', 'contain', 'pad_blur'),
    'visuals.motion': ('none', 'zoom_in', 'zoom_out', 'pan_left', 'pan_right'),
    'visuals.grade': ('none', 'neutral', 'warm'),
    **{prefix + field: choices for prefix in ('text_overlays.', 'subtitles.')
       for field, choices in (('position', ('top', 'center', 'bottom')),
                              ('font_family', ('dejavu-sans', 'dejavu-sans-bold')))},
    'aspect_ratio': ('16:9', '9:16', '1:1', '4:5', '2.39:1'),
}
STRUCTURES = {
    **{field: {name: 'number' for name in ('x', 'y', 'width', 'height')}
       for field in ('visuals.box', 'visuals.pad_box', 'text_overlays.box', 'subtitles.box')},
    'visuals.crop_box': {name: 'integer' for name in ('x', 'y', 'width', 'height')},
    'visuals.reframe_size': {name: 'integer' for name in ('width', 'height')},
}
FIELD_TYPES = {
    **{field: 'string' for field in (
        'title', 'output_filename', 'aspect_ratio', 'output_resolution', 'subtitles_srt',
        'visuals.kind', 'visuals.url', 'visuals.output_path', 'visuals.transition', 'visuals.fit',
        'visuals.grade', 'visuals.motion', 'audio_tracks.url', 'audio_tracks.output_path',
        *(prefix + name for prefix in ('text_overlays.', 'subtitles.')
          for name in ('text', 'position', 'color', 'background_color', 'font_family')))},
    **{field: 'integer' for field in (
        'video_bitrate', 'visuals.track', 'visuals.source_bitrate',
        *(prefix + name for prefix in ('text_overlays.', 'subtitles.')
          for name in ('font_size', 'font_weight', 'min_font_size', 'max_font_size')))},
    'visuals.allow_upscale': 'boolean',
    **{field: 'object' for field in STRUCTURES},
}
WORKFLOW_SCHEMA_SHA256 = {
    'motion_carry_probe': 'ca4a3e1a7a25949f038933d68f40909c33c3f7695d57458edc95ed477ffe46a1',
    'deliver_render': '1f13e356cb6a7b46989ffbc3d09bc8435a34709ee08a3fb184fb742a245ffe4c',
    'qc_deliverable': 'a166b684310a2a75d51ec9bc65b41e46f3696fa85cf824e78e541f6a9dd33c15',
    'render_ad_variants': 'c873a210d918c00b639bcc98e0dcacd9527730fca2d5b5e151a9c378c1120f5d',
    'import_nle_timeline': '9f5d158a4a1252f163560dcf9b8006e1be2d491fae45673b17453c80c00f8f15',
    'prepare_conversational_edit': 'af9860ec8bdcfb1fa4c76b9b4f5a71a176568c8702641a90cfd932629667bd5d',
    'get_render_progress': '66c5b76380ac064e0fd64cc4e6772ebfa5020427b4399a9011c0b48b7cab5ad5',
    'export_nle_timeline': '4f855c584be1e16e8addec3323e3c014c428e3e3009b0df09ff1d13f3e1c4f80',
}


def local_colour(value: str) -> str:
    if value in {'white', 'black', 'red', 'green', 'blue', 'yellow', 'gray', 'grey', 'transparent'}:
        return 'black@0' if value == 'transparent' else value
    if re.fullmatch(r'#[0-9a-fA-F]{3}', value):
        return '0x' + ''.join(character * 2 for character in value[1:])
    if re.fullmatch(r'#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?', value):
        return '0x' + value[1:]
    raise ValueError('Local text colors require named/hex color values; other CSS colors require Lambda.')


def _present(arguments: dict[str, Any], field: str) -> bool:
    section, _, name = field.partition('.')
    if not name:
        return section in arguments and arguments[section] is not None
    return any(name in item for item in arguments.get(section) or [])


def validate_backend(arguments: dict[str, Any], backend: Backend, *, overlay_version: str | None = None) -> None:
    from providers.contracts import validate_remotion_timeline_arguments
    from providers.remotion.text import number

    validate_remotion_timeline_arguments(arguments)
    if arguments.get('fps') is not None:
        number(arguments['fps'], 'fps', 1, 240)
    if arguments.get('video_bitrate') is not None:
        number(arguments['video_bitrate'], 'video_bitrate', 1, 200_000_000)
        if not isinstance(arguments['video_bitrate'], int):
            raise ValueError('video_bitrate must be an integer.')
    if backend not in {'local', 'lambda'}:
        raise ValueError('Remotion backend must be local or lambda.')
    version = overlay_version or os.getenv('REMOTION_OVERLAY_CONTRACT_VERSION', '1')
    for name, capability in CAPABILITIES.items():
        if any(_present(arguments, field) for field in capability.fields) and capability.status(backend, version) != SUPPORTED:
            raise ValueError(f'{backend} refuses {name}. {capability.note}')
    if backend == 'lambda' and any(item.get('fit') == 'pad_blur' for item in arguments.get('visuals') or []):
        raise ValueError(CAPABILITIES['crop_reframe'].note)
    for item in arguments.get('visuals') or []:
        if item['kind'] == 'image' and (item.get('source_in_seconds', 0) != 0 or item.get('playback_rate', 1) != 1
                                      or 'source_fps' in item or 'source_bitrate' in item):
            raise ValueError('Still images have no source trim/speed or video metadata on local or Lambda; use video media.')
        if item['kind'] == 'image' and (item.get('volume', 1) != 1 or
                item.get('audio_fade_in_seconds', 0) != 0 or item.get('audio_fade_out_seconds', 0) != 0):
            raise ValueError('Still images have no source audio on local or Lambda; use audio_tracks.')
    track_ends: dict[int, float] = {}
    for item in arguments.get('visuals') or []:
        track = item.get('track', 0)
        start = item.get('start_seconds', track_ends.get(track, 0))
        track_ends[track] = max(track_ends.get(track, 0), start + item['duration_seconds'])
    end = max(track_ends.values(), default=0)
    if end > 600:
        raise ValueError('Timeline duration must be at most 600 seconds on local or Lambda.')
    for item in [*(arguments.get('text_overlays') or []), *(arguments.get('subtitles') or [])]:
        if item['start_seconds'] >= end or item['start_seconds'] + item['duration_seconds'] > end + 1e-6:
            raise ValueError('Titles/captions must fit inside the visual timeline on local or Lambda.')
    if backend == 'local':
        for item in [*(arguments.get('text_overlays') or []), *(arguments.get('subtitles') or [])]:
            for field, default in (('color', '#ffffff'), ('background_color', 'transparent')):
                local_colour(item.get(field) or default)
            if item.get('font_weight', 700) not in {400, 700}:
                raise ValueError('Local text supports font_weight 400 or 700; other font weights require Lambda.')


def validate_document(props: dict[str, Any], backend: Backend) -> None:
    from providers.remotion.text import fit_text, number

    if backend == 'lambda':
        for track in props.get('document', {}).get('tracks', []):
            for item in track.get('items', []):
                if {'cropBox', 'padBox', 'reframeSize', 'allowUpscale'}.intersection(item) or item.get('fit') == 'pad_blur':
                    raise ValueError(CAPABILITIES['crop_reframe'].note)
                if {'box', 'fontFamily', 'minFontSize', 'maxFontSize', 'textFit'}.intersection(item) and os.getenv('REMOTION_OVERLAY_CONTRACT_VERSION', '1') != '2':
                    raise ValueError(CAPABILITIES['fitted_overlays'].note)
    config, document = props['renderConfig'], props['document']
    unknown_config = set(config) - {'width', 'height', 'fps', 'durationInFrames', 'videoBitrate', 'crf', 'resolution', 'timecode', 'dropFrame'}
    if unknown_config:
        raise ValueError(f'Unsupported renderConfig fields on local or Lambda: {sorted(unknown_config)}.')
    if config.get('videoBitrate') is not None:
        number(config['videoBitrate'], 'videoBitrate', 1, 200_000_000)
        if not isinstance(config['videoBitrate'], int):
            raise ValueError('videoBitrate must be an integer.')
    if config.get('crf') is not None:
        number(config['crf'], 'crf', 0, 51)
    for field, minimum, maximum in (('width', 2, 7680), ('height', 2, 7680), ('fps', 1, 240),
                                     ('durationInFrames', 1, 144_000)):
        value = number(config[field], field, minimum, maximum)
        if field != 'fps' and not value.is_integer():
            raise ValueError(f'{field} must be an integer.')
    if config['width'] % 2 or config['height'] % 2 or config['durationInFrames'] / config['fps'] > 600:
        raise ValueError('Remotion requires even canvas dimensions and at most 600 seconds on local or Lambda.')
    if len(document['assets']) > 60:
        raise ValueError('Remotion allows at most 60 assets on local or Lambda.')
    assets = {asset['id']: asset for asset in document['assets']}
    arguments: dict[str, Any] = {'visuals': [], 'audio_tracks': [], 'text_overlays': []}
    visual_end = 0.0
    visual_track = 0
    for track in document['tracks']:
        if track['kind'] not in {'video', 'overlay', 'caption', 'audio'}:
            raise ValueError('Unsupported track kind on local or Lambda; use video, overlay, caption or audio.')
        for item in track['items']:
            mapping = TEXT_FIELDS if item['type'] == 'text' else CLIP_FIELDS
            structural = {'id', 'type', 'textFit'} if item['type'] == 'text' else {'id', 'type', 'assetId', 'sourceOut'}
            unknown = set(item) - mapping.keys() - structural
            if unknown or item['type'] not in {'text', 'clip'}:
                raise ValueError(f'Unsupported Remotion item fields/type on local or Lambda: {sorted(unknown) or item["type"]}.')
            converted = {public: item[key] for key, public in mapping.items() if key in item}
            if item['type'] == 'text':
                if track['kind'] != 'caption':
                    raise ValueError('Text requires a caption track on local or Lambda.')
                if {'box', 'fontFamily', 'minFontSize', 'maxFontSize', 'textFit'}.intersection(item):
                    if 'textFit' not in item:
                        raise ValueError('Fitted text requires measured textFit on local or Lambda.')
                    layout = fit_text(item, config['width'], config['height'])
                    if item['textFit'] != layout['textFit'] or item.get('fontSize') != layout['fontSize']:
                        raise ValueError('textFit must match measured text on local or Lambda.')
                arguments['text_overlays'].append(converted)
            else:
                asset = assets[item['assetId']]
                converted.update(kind=asset['kind'], url=asset['url'])
                if 'sourceOut' in item and not math.isclose(item['sourceOut'], item.get('sourceIn', 0) + item['duration'] * item.get('playbackRate', 1), abs_tol=1e-6):
                    raise ValueError('sourceOut must match sourceIn + duration * playbackRate on local or Lambda.')
                if asset['kind'] == 'audio':
                    if track['kind'] != 'audio':
                        raise ValueError('Audio assets require an audio track on local or Lambda.')
                    audio_fields = {'url', 'start_seconds', 'duration_seconds', 'source_in_seconds', 'volume', 'fade_in_seconds', 'fade_out_seconds'}
                    if set(converted) - audio_fields - {'kind'}:
                        raise ValueError('Audio items accept timing, volume and fades only on local or Lambda.')
                    converted.pop('kind')
                    arguments['audio_tracks'].append(converted)
                else:
                    if track['kind'] not in {'video', 'overlay'}:
                        raise ValueError('Visual assets require a video/overlay track on local or Lambda.')
                    if 'reframeSize' in item and item['reframeSize'] != {'width': config['width'], 'height': config['height']}:
                        raise ValueError('reframeSize must match the render canvas on local or Lambda.')
                    converted['track'] = visual_track
                    visual_end = max(visual_end, item['start'] + item['duration'])
                    arguments['visuals'].append(converted)
        if track['kind'] in {'video', 'overlay'}:
            visual_track += 1
    validate_backend(arguments, backend)
    if config['durationInFrames'] != max(1, math.ceil(visual_end * config['fps'] - 1e-9)):
        raise ValueError('durationInFrames must match the visual timeline on local or Lambda.')


def field_capabilities(capabilities: dict[str, Capability] = CAPABILITIES) -> dict[str, Capability]:
    return {field: capability for capability in capabilities.values() for field in capability.fields}


def schema_note(capability: Capability) -> str:
    return f'Backend support: local {capability.local}; lambda {capability.lambda_}. {capability.note}'.strip()


def schema_fields(schema: dict[str, Any], prefix: str = '') -> dict[str, dict]:
    fields = {}
    for name, child in schema.get('properties', {}).items():
        path = prefix + name
        if 'items' in child and 'properties' in child['items']:
            fields.update(schema_fields(child['items'], path + '.'))
        else:
            fields[path] = child
    return fields


def annotate_schema(schema: dict[str, Any]) -> None:
    declared = field_capabilities()
    for field, child in schema_fields(schema).items():
        if field in declared:
            existing = child.get('description', '').split('Backend support:', 1)[0].strip()
            child['description'] = (existing + ' ' + schema_note(declared[field])).strip()


def check_contract(schemas: list[dict], skills: list[dict], *,
                   capabilities: dict[str, Capability] = CAPABILITIES) -> None:
    for name, capability in capabilities.items():
        assert 'unsupported-but-silently-ignored' not in {capability.local, capability.lambda_}, f'{name} silently ignored'
    tools = {tool for capability in capabilities.values() for tool in capability.tools}
    assert tools == {tool['name'] for tool in schemas}, f'Remotion capability/tool drift: {sorted(tools ^ {tool["name"] for tool in schemas})}'
    for tool in schemas:
        if tool['name'] in WORKFLOW_SCHEMA_SHA256:
            encoded = json.dumps(tool['inputSchema'], sort_keys=True, separators=(',', ':')).encode()
            assert hashlib.sha256(encoded).hexdigest() == WORKFLOW_SCHEMA_SHA256[tool['name']], f'{tool["name"]} schema drift requires capability review'
    declared = field_capabilities(capabilities)
    render = next(tool for tool in schemas if tool['name'] == 'render_timeline')
    fields = schema_fields(render['inputSchema'])
    assert fields.keys() == declared.keys(), f'Remotion capability/schema drift: {sorted(fields.keys() ^ declared.keys())}'
    for field, child in fields.items():
        assert child.get('type') == FIELD_TYPES.get(field, 'number'), f'{field} type/schema drift'
        assert child.get('description', '').count('Backend support:') == 1, f'{field} duplicate backend disclosure'
        assert schema_note(declared[field]) in child.get('description', ''), f'{field} backend disclosure drift'
        if field in STRUCTURES:
            expected = STRUCTURES[field]
            nested = child.get('properties', {})
            assert nested.keys() == expected.keys(), f'{field} nested schema drift: {sorted(nested.keys() ^ expected.keys())}'
            assert set(child.get('required', [])) == expected.keys(), f'{field} required fields drift'
            assert all(nested[name].get('type') == kind for name, kind in expected.items()), f'{field} nested types drift'
        if field in PRESETS:
            match = re.search(r'Allowed values: (.*?)\.(?: |$)', child.get('description', ''))
            assert match and tuple(match[1].split(', ')) == PRESETS[field], f'{field} preset/schema drift'
        if field == 'output_resolution':
            assert 'One of: source, 720p, 1080p, 1440p, 2160p.' in child.get('description', ''), 'output_resolution preset/schema drift'
    for skill in skills:
        metadata = skill['metadata']
        remotion_tools = [name.removeprefix('Remotion___') for name in metadata.get('gateway_tools', '').split()
                          if name.startswith('Remotion___')]
        for tool in remotion_tools:
            assert tool in tools, f'{skill["name"]} advertises unknown Remotion tool {tool}'
            if tool != 'render_timeline' and metadata.get('remotion_backend') in {'local', 'lambda'}:
                for feature, capability in capabilities.items():
                    if tool in capability.tools:
                        assert capability.status(metadata['remotion_backend']) == SUPPORTED, f'{skill["name"]} advertises {tool}/{feature} on {metadata["remotion_backend"]}'
        if 'Remotion___render_timeline' not in metadata.get('gateway_tools', '').split():
            continue
        backend = metadata.get('remotion_backend')
        claims = metadata.get('remotion_features', '').split()
        assert backend in {'local', 'lambda', 'configured'}, f'{skill["name"]} must declare remotion_backend'
        assert claims, f'{skill["name"]} must declare remotion_features'
        for feature in claims:
            assert feature in capabilities, f'{skill["name"]} advertises unknown {feature}'
            assert capabilities[feature].local == SUPPORTED or capabilities[feature].lambda_ == SUPPORTED, f'{skill["name"]} advertises unavailable {feature}'
            if backend != 'configured':
                assert capabilities[feature].status(backend) == SUPPORTED, f'{skill["name"]} advertises {feature} on {backend}'
        if backend == 'configured':
            assert 'Unsupported features refuse before media I/O' in skill.get('body', ''), f'{skill["name"]} lacks backend refusal contract'
