from __future__ import annotations

import hashlib
import re
from pathlib import Path

from providers.ffmpeg.sandbox import NAME_PATTERN, input_file, job_directory


def reference_artifact_content(execution: dict | None, execution_id: str,
                               tool_call_id: str, filename: str) -> bytes:
    if (execution is None or not re.fullmatch(NAME_PATTERN, filename)
            or Path(filename).suffix.lower() not in {'.json', '.csv', '.html', '.jpg', '.png', '.mp4'}):
        raise ValueError('Reference file not found.')
    call = next((call for call in execution['tool_calls'] if call['id'] == tool_call_id
                 and call['name'] == 'Reference___shot_breakdown'), None)
    records = call['result'].get('outputs') if call else None
    if not isinstance(records, list):
        raise ValueError('Reference file not found.')
    for record in records:
        if not isinstance(record, dict):
            continue
        recorded = record.get('path')
        if not isinstance(recorded, str) or Path(recorded).name != filename:
            continue
        path = input_file(job_directory(execution_id), recorded, max_bytes=16 * 1024 * 1024)
        with path.open('rb') as source:
            content = source.read(16 * 1024 * 1024 + 1)
        if len(content) > 16 * 1024 * 1024 or hashlib.sha256(content).hexdigest() != record.get('sha256'):
            raise ValueError('Reference file not found.')
        return content
    raise ValueError('Reference file not found.')
