"""Resolve saved logo artifacts within their owning execution's job directory."""
from __future__ import annotations

import re
import hashlib
from pathlib import Path
from typing import Any

from providers.ffmpeg.sandbox import NAME_PATTERN, input_file, job_directory


def logo_artifact_content(
    execution: dict[str, Any] | None, execution_id: str, tool_call_id: str, filename: str,
) -> bytes:
    if (execution is None or not re.fullmatch(NAME_PATTERN, filename)
            or Path(filename).suffix.lower() not in {".svg", ".png", ".html", ".md", ".json"}):
        raise ValueError("Logo artifact not found.")
    call = next((call for call in execution["tool_calls"]
                 if call["id"] == tool_call_id and call["name"] == "Logo___logo_vectorize"), None)
    outputs = call["result"].get("outputs") if call else None
    if not isinstance(outputs, list):
        raise ValueError("Logo artifact not found.")
    for record in outputs:
        if not isinstance(record, dict):
            continue
        recorded_path = record.get("path") or record.get("output_path")
        if not isinstance(recorded_path, str) or Path(recorded_path).name != filename:
            continue
        path = input_file(job_directory(execution_id), recorded_path, max_bytes=16*1024*1024)
        with path.open('rb') as source:
            content = source.read(16*1024*1024+1)
        if path.name != filename or len(content) > 16*1024*1024 or record.get("sha256") != hashlib.sha256(content).hexdigest():
            raise ValueError("Logo artifact not found.")
        return content
    raise ValueError("Logo artifact not found.")
