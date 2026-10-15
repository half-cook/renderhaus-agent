"""Owned, measured finishing previews and human review before full-video spending."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent.deep_agent.outcomes import OutcomeStore
from agent.deep_agent.routing import estimate_cost, job_type
from providers.ffmpeg.sandbox import MAX_FOOTAGE_INPUT_BYTES, output_file, sha256_file, validate_job_id
from providers.remotion.local import _probe
from providers.topaz.contracts import request_for

FINISHING_TOOLS = frozenset({'Topaz___upscale_video', 'Topaz___interpolate_video'})
HANDLE = re.compile(r'renderhaus-asset://([A-Za-z0-9_-]+)')
PREVIEW_LIMIT_SECONDS = 3.0


class VideoMeasurement(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(gt=0)
    duration_seconds: float = Field(gt=0)


def measure_video(path: Path) -> VideoMeasurement:
    if not shutil.which('ffprobe'):
        raise ValueError('Video preview requires the local media inspection tool.')
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_FOOTAGE_INPUT_BYTES:
        raise ValueError('The owned video is missing, empty or exceeds the local media limit.')
    probe = _probe(path)
    video = next((stream for stream in probe['streams'] if stream.get('codec_type') == 'video'), None)
    if video is None:
        raise ValueError('The owned asset must contain a video stream.')
    try:
        fps = float(Fraction(video.get('avg_frame_rate') or video['r_frame_rate']))
        return VideoMeasurement(width=video['width'], height=video['height'], fps=fps,
                                duration_seconds=float(video.get('duration') or probe['format']['duration']))
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError('The video dimensions, duration and frame rate must be measurable.') from exc


def _canonical(name: str, arguments: dict) -> dict:
    if name not in FINISHING_TOOLS:
        raise ValueError('Prepare a discovered finishing tool with its exact arguments.')
    request = request_for(name.split('___', 1)[1], arguments)
    result = request.model_dump(exclude_none=True)
    result.pop('fps_multiplier', None)
    return result


def _signature(name: str, arguments: dict) -> str:
    return hashlib.sha256(json.dumps([name, _canonical(name, arguments)], sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def _request_arguments(name: str, arguments: dict) -> dict:
    canonical = _canonical(name, arguments)
    supplied = {key: canonical[key] for key, value in arguments.items()
                if key in canonical and value is not None}
    if arguments.get('fps_multiplier') is not None:
        supplied['target_fps'] = canonical['target_fps']
    return supplied


class FinishingPreview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    preview_id: str
    sequence: int = 0
    tool_name: str
    full_arguments: dict
    preview_arguments: dict
    source_version_id: str
    source_sha256: str
    source_clip_version_id: str
    source_clip_sha256: str
    source: VideoMeasurement
    clip: VideoMeasurement
    source_start_seconds: float
    covers_full_source: bool
    status: Literal['prepared', 'submitting', 'submitted', 'ready', 'approved', 'rejected', 'failed'] = 'prepared'
    submit_call_id: str | None = None
    submit_result: dict | None = None
    job_id: str | None = None
    output_version_id: str | None = None
    output_sha256: str | None = None
    output: VideoMeasurement | None = None
    full_submit_call_id: str | None = None
    full_submit_result: dict | None = None
    error: str | None = None


class FinishingPreviewGate:
    def __init__(self, studio, saved: dict | None = None, *, scope: str | None = None):
        self.studio = studio
        self.scope = scope or '/'.join(str(value or '') for value in (
            studio.workspace_id, studio.project_id, studio.session_id or studio.job_id))
        self.lock = RLock()
        self.outcomes = OutcomeStore()
        self.previews: dict[str, FinishingPreview] = {}
        if saved and saved.get('scope') == self.scope:
            for value in saved.get('previews', {}).values():
                try:
                    record = FinishingPreview.model_validate(value)
                    self.previews[record.preview_id] = record
                except (ValidationError, TypeError):
                    continue

    def snapshot(self) -> dict:
        with self.lock:
            return {'scope': self.scope, 'previews': {
                key: value.model_dump(mode='json') for key, value in self.previews.items()}}

    def summaries(self) -> list[dict]:
        return [{key: value for key, value in row.model_dump().items() if key in {
            'preview_id', 'tool_name', 'status', 'job_id', 'source_version_id', 'source_clip_version_id',
            'output_version_id', 'covers_full_source', 'preview_arguments', 'full_arguments', 'error'}}
            for row in self.previews.values()]

    def _owned_path(self, version: str) -> Path:
        asset = self.studio.working_assets.get(version, {})
        if asset.get('kind') != 'video' or self.studio.source_resolver is None:
            raise ValueError('Finishing preview requires an owned video asset in this project.')
        try:
            path = Path(self.studio.source_resolver(version)).resolve(strict=True)
        except (OSError, KeyError, ValueError) as exc:
            raise ValueError('The owned preview video is unavailable.') from exc
        if not path.is_file():
            raise ValueError('The owned preview video is unavailable.')
        return path

    def _verify_sources(self, record: FinishingPreview) -> None:
        for version, checksum in ((record.source_version_id, record.source_sha256),
                                  (record.source_clip_version_id, record.source_clip_sha256)):
            if sha256_file(self._owned_path(version)) != checksum:
                raise ValueError('The source or preview clip changed. Prepare and review a new finishing preview.')

    def _result(self, record: FinishingPreview) -> dict:
        return {'ok': True, 'status': record.status, 'preview_id': record.preview_id,
                'tool_name': record.tool_name, 'preview_arguments': deepcopy(record.preview_arguments),
                'full_arguments': deepcopy(record.full_arguments),
                'source_clip_version_id': record.source_clip_version_id,
                'covers_full_source': record.covers_full_source,
                'measurements': {'source': record.source.model_dump(), 'preview': record.clip.model_dump()},
                'preview_estimated_cost': estimate_cost(record.tool_name, record.preview_arguments).public(),
                'full_estimated_cost': estimate_cost(record.tool_name, record.full_arguments).public(),
                'job_id': record.job_id,
                'message': 'The local preview clip is ready. Its finishing job still requires cost approval.'}

    def prepare(self, tool_name: str, arguments: dict, start_seconds: float = 0,
                duration_seconds: float = PREVIEW_LIMIT_SECONDS) -> dict:
        with self.lock:
            try:
                if tool_name not in FINISHING_TOOLS or not isinstance(arguments, dict):
                    raise ValueError('Prepare a discovered finishing tool with its exact arguments.')
                source = arguments.get('video_url')
                source_handle = HANDLE.fullmatch(source) if isinstance(source, str) else None
                if source_handle is None:
                    raise ValueError('Select an owned Studio video before preparing a finishing preview.')
                if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                       for value in (start_seconds, duration_seconds)) or start_seconds < 0 or duration_seconds <= 0:
                    raise ValueError('Preview start and duration must be finite, positive source times.')
                if not self.studio.job_id or self.studio.asset_registrar is None:
                    raise ValueError('Finishing preview requires the current project media store.')
                version = source_handle[1]
                path = self._owned_path(version)
                measured = measure_video(path)
                full = _request_arguments(tool_name, {
                    'source_width': measured.width, 'source_height': measured.height,
                    'source_fps': measured.fps, 'source_duration_seconds': measured.duration_seconds,
                    **arguments})
                if full.get('slowdown_factor', 1) != 1:
                    raise ValueError('Slow-motion finishing is blocked until its duration mapping and quote are verified.')
                tolerance = 1 / measured.fps + 0.001
                if (full['source_width'] != measured.width or full['source_height'] != measured.height
                        or not math.isclose(full['source_fps'], measured.fps, abs_tol=0.01)
                        or not math.isclose(full['source_duration_seconds'], measured.duration_seconds, abs_tol=tolerance)):
                    raise ValueError('Finishing source measurements differ from the owned file. Use its measured dimensions, FPS and duration.')
                full.update(source_duration_seconds=measured.duration_seconds, source_fps=measured.fps)
                full = _request_arguments(tool_name, full)
                if estimate_cost(tool_name, full).total_cents is None:
                    raise ValueError('This finishing output has an unknown quote. A paid preview is blocked.')
                duration = min(duration_seconds, PREVIEW_LIMIT_SECONDS, measured.duration_seconds - start_seconds)
                frames = math.floor(duration * measured.fps + 0.0001)
                if frames < 1:
                    raise ValueError('The preview range must contain at least one source frame.')
                source_sha = sha256_file(path)
                preview_id = hashlib.sha256(json.dumps([tool_name, _canonical(tool_name, full), source_sha, start_seconds, frames],
                                                       sort_keys=True).encode()).hexdigest()[:32]
                previous = self.previews.get(preview_id)
                if previous:
                    self._verify_sources(previous)
                    if self._full_for(tool_name, full) is not previous:
                        previous.sequence = max(row.sequence for row in self.previews.values()) + 1
                        if previous.status == 'approved':
                            previous.status = 'ready'
                    return self._result(previous)
                validate_job_id(self.studio.job_id)
                root = Path(os.getenv('RENDERHAUS_MEDIA_DIR', '.renderhaus/media')).expanduser().resolve()
                directory = root / self.studio.job_id
                if directory.is_symlink() or not directory.resolve().is_relative_to(root):
                    raise ValueError('Preview files must remain inside the current media job.')
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                target = output_file(directory, 'finishing-preview', '.mp4')
                binary = shutil.which('ffmpeg')
                if not binary:
                    raise ValueError('Video preview requires the local media trim tool.')
                result = subprocess.run([binary, '-v', 'error', '-nostdin', '-protocol_whitelist', 'file,pipe',
                    '-i', str(path), '-ss', str(start_seconds), '-t', str(duration), '-frames:v', str(frames),
                    '-map', '0:v:0', '-map', '0:a?', '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', str(target)],
                    capture_output=True, timeout=90, check=False)
                if result.returncode:
                    target.unlink(missing_ok=True)
                    raise ValueError('The owned source could not be trimmed into a playable preview.')
                clip = measure_video(target)
                if clip.duration_seconds > PREVIEW_LIMIT_SECONDS or clip.duration_seconds > duration + 0.001:
                    target.unlink(missing_ok=True)
                    raise ValueError('The actual preview exceeds its three-second source range.')
                if sha256_file(path) != source_sha:
                    target.unlink(missing_ok=True)
                    raise ValueError('The source changed while preparing the finishing preview.')
                assets = self.studio.asset_registrar(result={'status': 'succeeded', 'output_path': str(target)},
                    provider=None, label='Finishing source preview', tool_call_id=f'prepare-{preview_id}',
                    source_version_ids=[version])
                self.studio.add_assets(assets)
                saved = next((asset['version_id'] for asset in assets
                              if asset.get('kind') == 'video' and asset.get('version_id')), None)
                if not saved:
                    raise ValueError('The source preview could not be saved as an owned video.')
                saved_path = self._owned_path(saved)
                if sha256_file(saved_path) != sha256_file(target):
                    raise ValueError('The saved source preview differs from its measured trim.')
                preview = _request_arguments(tool_name, {**full, 'video_url': 'renderhaus-asset://' + saved,
                    'source_duration_seconds': clip.duration_seconds, 'source_fps': clip.fps,
                    'source_width': clip.width, 'source_height': clip.height})
                record = FinishingPreview(preview_id=preview_id,
                    sequence=max((row.sequence for row in self.previews.values()), default=0) + 1,
                    tool_name=tool_name, full_arguments=full,
                    preview_arguments=preview, source_version_id=version, source_sha256=source_sha,
                    source_clip_version_id=saved, source_clip_sha256=sha256_file(saved_path), source=measured,
                    clip=clip, source_start_seconds=start_seconds,
                    covers_full_source=(start_seconds == 0 and measured.duration_seconds <= PREVIEW_LIMIT_SECONDS
                                        and clip.duration_seconds >= measured.duration_seconds - 0.0001))
                self.previews[preview_id] = record
                return self._result(record)
            except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
                return {'ok': False, 'status': 'not_run', 'error': str(exc)}

    def preview_for(self, name: str, arguments: dict) -> FinishingPreview | None:
        if name not in FINISHING_TOOLS:
            return None
        try:
            signature = _signature(name, arguments)
            return next((record for record in self.previews.values()
                         if record.tool_name == name and _signature(name, record.preview_arguments) == signature), None)
        except (ValueError, TypeError):
            return None

    def _full_for(self, name: str, arguments: dict) -> FinishingPreview | None:
        signature = _signature(name, arguments)
        matches = [record for record in self.previews.values() if record.tool_name == name
                   and _signature(name, record.full_arguments) == signature]
        return max(matches, key=lambda record: record.sequence, default=None)

    def _submitted_full_for(self, record: FinishingPreview) -> FinishingPreview | None:
        signature = _signature(record.tool_name, record.full_arguments)
        return next((row for row in self.previews.values() if row.full_submit_call_id
                     and row.tool_name == record.tool_name and row.source_sha256 == record.source_sha256
                     and _signature(row.tool_name, row.full_arguments) == signature), None)

    def blocker(self, name: str, arguments: dict) -> str | None:
        if name not in FINISHING_TOOLS:
            return None
        with self.lock:
            try:
                _canonical(name, arguments)
                record = self.preview_for(name, arguments)
                if record:
                    self._verify_sources(record)
                    if record.status in {'prepared', 'submitting', 'submitted', 'ready', 'approved'}:
                        return None
                    raise ValueError('This finishing preview was rejected or failed. No full job is authorized.')
                record = self._full_for(name, arguments)
                if record is None or record.status != 'approved':
                    raise ValueError('Prepare a short finishing preview, run it with cost approval, and review the saved comparison before full finishing.')
                self.comparison(record.preview_id)
                return None
            except (ValueError, OSError, KeyError) as exc:
                return str(exc)

    def replay(self, name: str, arguments: dict) -> dict | None:
        if name not in FINISHING_TOOLS:
            return None
        with self.lock:
            if self.blocker(name, arguments):
                return None
            record = self.preview_for(name, arguments)
            if record and record.submit_call_id:
                return {**deepcopy(record.submit_result or {'status': 'submission_unknown'}),
                        'preview_id': record.preview_id,
                        'note': 'This preview was already submitted. Poll its saved job; no new paid job was started.'}
            record = self._full_for(name, arguments)
            if record and record.status == 'approved' and record.covers_full_source:
                return self._final_result(record)
            submitted = self._submitted_full_for(record) if record else None
            if submitted:
                return {**deepcopy(submitted.full_submit_result or {'status': 'submission_unknown'}),
                        'note': 'This finishing request was already submitted. Poll its saved job; no new paid job was started.'}
            return None

    def claim_submission(self, name: str, arguments: dict, call_id: str) -> None:
        if name not in FINISHING_TOOLS:
            return
        with self.lock:
            if blocker := self.blocker(name, arguments):
                raise ValueError(blocker)
            record = self.preview_for(name, arguments) or self._full_for(name, arguments)
            if self.preview_for(name, arguments):
                if record.submit_call_id:
                    raise ValueError('The preview already has a submission. Reconcile its saved job before retrying.')
                record.submit_call_id, record.status = call_id, 'submitting'
            else:
                if self._submitted_full_for(record):
                    raise ValueError('The full request already has a submission. Reconcile its saved job before retrying.')
                record.full_submit_call_id = call_id

    def record_submission(self, name: str, arguments: dict, call_id: str, result: dict) -> None:
        if name not in FINISHING_TOOLS:
            return
        with self.lock:
            record = self.preview_for(name, arguments) or next((row for row in self.previews.values()
                if row.full_submit_call_id == call_id and row.tool_name == name), None)
            if record is None:
                return
            if self.preview_for(name, arguments) and record.submit_call_id == call_id:
                record.submit_result = deepcopy(result)
                record.job_id = result.get('job_id')
                record.status = 'submitted' if record.job_id and result.get('status') in {'queued', 'running', 'succeeded'} else 'failed'
                if record.status == 'failed':
                    record.error = 'The preview has no successful paid submission. Dry runs and failed jobs cannot be reviewed.'
            elif record.full_submit_call_id == call_id:
                record.full_submit_result = deepcopy(result)

    def decorate_output(self, name: str, arguments: dict, output: dict) -> dict:
        if name != 'Topaz___get_video_task':
            return output
        record = next((row for row in self.previews.values() if row.job_id == arguments.get('job_id')), None)
        if record:
            return {**output, 'finishing_preview_id': record.preview_id, 'finishing_preview_only': True}
        return output

    def observe(self, event) -> None:
        with self.lock:
            if event.name != 'Topaz___get_video_task':
                return
            record = next((row for row in self.previews.values() if row.job_id and row.job_id == (
                event.provider_job_id or event.arguments.get('job_id') or event.result.get('job_id'))), None)
            if record is None:
                return
            event.result.update(finishing_preview_id=record.preview_id, finishing_preview_only=True)
            if record.status not in {'submitted', 'ready', 'approved'}:
                return
            if event.status != 'succeeded' or event.result.get('status') != 'succeeded' or event.result.get('downloaded') is not True:
                if event.status in {'failed', 'error', 'dry_run'}:
                    record.status = 'failed'
                    record.error = 'The preview did not complete successfully. No full job is authorized.'
                return
            try:
                self._verify_sources(record)
                version = next((asset['version_id'] for asset in event.assets
                                if asset.get('kind') == 'video' and asset.get('version_id')), None)
                if not version:
                    raise ValueError('Save the successful downloaded preview as an owned video before review.')
                self.studio.add_assets(event.assets)
                path = self._owned_path(version)
                output = measure_video(path)
                self._validate_output(record, output)
                binary = shutil.which('ffmpeg')
                if not binary:
                    raise ValueError('Preview playback verification requires the local media decoder.')
                decoded = subprocess.run([binary, '-v', 'error', '-xerror', '-nostdin',
                    '-protocol_whitelist', 'file,pipe', '-i', str(path), '-map', '0:v:0', '-f', 'null', '-'],
                    capture_output=True, timeout=45, check=False)
                if decoded.returncode:
                    raise ValueError('The finishing preview cannot be decoded for comparison.')
                checksum = sha256_file(path)
                if record.output_sha256 and checksum != record.output_sha256:
                    raise ValueError('The saved preview result changed after it was prepared for review. Run a new preview.')
                if not record.output_version_id:
                    record.output_version_id, record.output_sha256, record.output = version, checksum, output
                if record.status != 'approved':
                    record.status = 'ready'
                record.error = None
                if record.status == 'approved' and record.covers_full_source:
                    event.result.update(self._final_result(record))
            except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
                record.error = str(exc)

    @staticmethod
    def _validate_output(record: FinishingPreview, output: VideoMeasurement) -> None:
        request = request_for(record.tool_name.split('___', 1)[1], record.preview_arguments)
        if ((output.width, output.height) != (request.output_width, request.output_height)
                or not math.isclose(output.fps, request.output_fps, abs_tol=0.02)
                or output.duration_seconds > PREVIEW_LIMIT_SECONDS
                or not math.isclose(output.duration_seconds, request.output_duration,
                                    abs_tol=1 / request.output_fps + 0.001)):
            raise ValueError('The saved finishing preview does not match the expected dimensions, FPS or duration.')

    def comparison(self, preview_id: str) -> dict:
        with self.lock:
            record = self.previews.get(preview_id)
            if record is None or record.status not in {'ready', 'approved'} or record.error:
                raise ValueError(record.error if record and record.error else 'A successful saved finishing preview is required before review.')
            if self._full_for(record.tool_name, record.full_arguments) is not record:
                raise ValueError('A newer source sample is selected. Review the current finishing preview before full finishing.')
            self._verify_sources(record)
            if not record.output_version_id or not record.output_sha256:
                raise ValueError('The finishing result has no saved video for comparison.')
            path = self._owned_path(record.output_version_id)
            if sha256_file(path) != record.output_sha256:
                raise ValueError('The finishing result changed. Run and review a new finishing preview.')
            self._validate_output(record, measure_video(path))
            return {'before_version_id': record.source_clip_version_id,
                    'after_version_id': record.output_version_id,
                    'duration_seconds': record.clip.duration_seconds,
                    'source_start_seconds': record.source_start_seconds,
                    'full_estimated_cost_cents': estimate_cost(record.tool_name, record.full_arguments).total_cents,
                    'source_width': record.clip.width, 'source_height': record.clip.height,
                    'output_width': record.output.width, 'output_height': record.output.height,
                    'source_fps': record.clip.fps, 'output_fps': record.output.fps,
                    'covers_full_source': record.covers_full_source}

    def can_review(self, preview_id: str) -> bool:
        try:
            self.comparison(preview_id)
            return True
        except (ValueError, OSError, KeyError):
            return False

    def _final_result(self, record: FinishingPreview) -> dict:
        return {'status': 'succeeded', 'downloaded': True, 'finishing_preview_id': record.preview_id,
                'finishing_preview_only': False, 'finishing_preview_approved_final': True,
                'output_version_id': record.output_version_id, 'output_sha256': record.output_sha256,
                'source_version_id': record.source_version_id, 'source_sha256': record.source_sha256,
                'output_path': str(self._owned_path(record.output_version_id)),
                'message': 'The approved preview covers the complete source. This saved video is the finished clip.'}

    def _record_review(self, record: FinishingPreview, outcome: str) -> None:
        if not record.output_version_id:
            return
        model = request_for(record.tool_name.split('___', 1)[1], record.preview_arguments).model
        self.outcomes.record(event_id=f'finishing-preview-{self.scope}-{record.preview_id}-{outcome}',
            provider='topaz', model=model, job_type=job_type(record.tool_name), provider_job_id=record.job_id,
            outcome=outcome, stage='review', workspace_id=self.studio.workspace_id,
            project_id=self.studio.project_id, execution_id=self.studio.job_id, ab_arm='finishing_preview',
            asset={'version_id': record.output_version_id, 'provider': 'topaz', 'model': model,
                   'status': 'succeeded', 'training_eligible': False})

    def approve(self, preview_id: str, expected_comparison: dict | None = None) -> dict:
        with self.lock:
            try:
                comparison = self.comparison(preview_id)
                if expected_comparison is not None and comparison != expected_comparison:
                    raise ValueError('The comparison changed after human review. Request a fresh review.')
            except (ValueError, OSError, KeyError) as exc:
                return {'status': 'not_run', 'error': str(exc)}
            record = self.previews[preview_id]
            record.status = 'approved'
            self._record_review(record, 'accepted')
            if record.covers_full_source:
                final = self._final_result(record)
                for event in self.studio.tool_events:
                    if event.result.get('finishing_preview_id') == preview_id:
                        event.result.update(final)
                return {**final, 'preview_id': preview_id, 'covers_full_source': True}
            return {'status': 'approved', 'preview_id': preview_id, 'comparison': comparison,
                    'covers_full_source': False, 'tool_name': record.tool_name,
                    'full_arguments': deepcopy(record.full_arguments),
                    'message': 'Comparison approved. Full finishing still requires a separate cost approval.'}

    def reject(self, preview_id: str) -> dict:
        with self.lock:
            record = self.previews.get(preview_id)
            if record is None:
                return {'status': 'not_run', 'error': 'The finishing preview does not exist in this conversation.'}
            record.status = 'rejected'
            self._record_review(record, 'rejected')
            for event in self.studio.tool_events:
                if event.result.get('finishing_preview_id') == preview_id:
                    event.result['finishing_preview_only'] = True
                    event.result.pop('finishing_preview_approved_final', None)
            return {'status': 'rejected', 'preview_id': preview_id,
                    'message': 'The original is kept. No full finishing job is authorized.'}


def preview_delivery_valid(studio, result: dict) -> bool:
    if not result.get('finishing_preview_id'):
        return True
    if result.get('finishing_preview_only') or result.get('finishing_preview_approved_final') is not True:
        return False
    if studio.source_resolver is None:
        return False
    try:
        return all(sha256_file(Path(studio.source_resolver(result[key]))) == result[checksum]
                   for key, checksum in (('source_version_id', 'source_sha256'),
                                         ('output_version_id', 'output_sha256')))
    except (ValueError, OSError, KeyError):
        return False
