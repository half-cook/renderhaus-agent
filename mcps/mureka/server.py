from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from fastmcp import FastMCP
from pydantic import BaseModel, Field
from pydantic.fields import FieldInfo


mcp = FastMCP("renderhaus-mureka")


class MurekaTask(BaseModel):
    job_id: str
    status: str
    provider: str = "mureka"
    mode: str
    prompt: str
    model: str | None = None
    output_path: str | None = None
    audio_url: str | None = None
    note: str


TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "canceled", "timeouted", "timeout"}
QUERY_KIND = Literal["instrumental", "song"]


def _field_value(value: Any, default: Any) -> Any:
    if isinstance(value, FieldInfo):
        return getattr(value, "default", default)
    return value


def _media_dir() -> Path:
    path = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _dry_run() -> bool:
    return os.getenv("MUREKA_DRY_RUN", "true").lower() != "false"


def _base_url() -> str:
    return os.getenv("MUREKA_API_URL", "https://api.mureka.ai").rstrip("/")


def _model(model: str | None = None) -> str:
    return model or os.getenv("MUREKA_MODEL") or "auto"


def _api_key() -> str:
    key = os.getenv("MUREKA_API_KEY")
    if not key:
        raise RuntimeError("MUREKA_API_KEY is required for live Mureka calls.")
    return key


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }


def _music_dir() -> Path:
    path = _media_dir() / "music"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _task_meta_dir() -> Path:
    path = _music_dir() / ".tasks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _task_meta_path(job_id: str) -> Path:
    return _task_meta_dir() / f"{job_id}.json"


def _write_task_meta(job_id: str, metadata: dict[str, Any]) -> None:
    _task_meta_path(job_id).write_text(json.dumps(metadata, indent=2, sort_keys=True))


def _read_task_meta(job_id: str) -> dict[str, Any]:
    path = _task_meta_path(job_id)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _output_path(job_id: str, suffix: str = ".mp3") -> Path:
    return _music_dir() / f"{job_id}{suffix}"


def _provider_error(response: httpx.Response) -> RuntimeError:
    try:
        payload = response.json()
    except ValueError:
        message = response.text[:1000]
        return RuntimeError(f"Mureka API error {response.status_code}: {message}")
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("error") or payload
        return RuntimeError(f"Mureka API error {response.status_code}: {message}")
    return RuntimeError(f"Mureka API error {response.status_code}: {payload}")


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_error:
        raise _provider_error(response)


def _suffix_from_url(url: str) -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if suffix in {".mp3", ".wav", ".m4a", ".flac", ".ogg"}:
        return suffix
    return ".mp3"


def _download_audio(audio_url: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", audio_url, follow_redirects=True, timeout=120) as response:
        response.raise_for_status()
        with output_path.open("wb") as file:
            for chunk in response.iter_bytes():
                if chunk:
                    file.write(chunk)


def _extract_audio_url(payload: dict[str, Any]) -> str | None:
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return None
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        url = choice.get("url")
        if isinstance(url, str) and url:
            return url
    return None


def _dry_task(*, mode: str, prompt: str, model: str | None) -> dict:
    job_id = f"mureka_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    selected_model = _model(model)
    output_path = _output_path(job_id)
    return MurekaTask(
        job_id=job_id,
        status="dry_run",
        mode=mode,
        prompt=prompt,
        model=selected_model,
        output_path=str(output_path),
        note="Dry run only. Set MUREKA_DRY_RUN=false to create a live Mureka track.",
    ).model_dump()


def _create_task(
    *,
    mode: str,
    kind: QUERY_KIND,
    prompt: str,
    body: dict[str, Any],
    model: str | None,
) -> dict:
    selected_model = _model(model)
    endpoint = (
        f"{_base_url()}/v1/instrumental/generate"
        if kind == "instrumental"
        else f"{_base_url()}/v1/song/generate"
    )
    with httpx.Client(timeout=60) as client:
        response = client.post(endpoint, headers=_headers(), json=body)
        _raise_for_status(response)
        payload = response.json()

    job_id = str(payload.get("id") or "")
    if not job_id:
        raise RuntimeError(f"Mureka did not return a task id: {payload}")

    output_path = _output_path(job_id)
    metadata = {
        "job_id": job_id,
        "mode": mode,
        "kind": kind,
        "prompt": prompt,
        "model": selected_model,
        "output_path": str(output_path),
        "created_at": int(time.time()),
        "create_response": payload,
    }
    _write_task_meta(job_id, metadata)

    return MurekaTask(
        job_id=job_id,
        status=str(payload.get("status") or "queued"),
        mode=mode,
        prompt=prompt,
        model=selected_model,
        output_path=str(output_path),
        note="Live Mureka task created. Call get_music_task to poll it.",
    ).model_dump()


def _retrieve_task(job_id: str, download: bool) -> dict:
    if _dry_run():
        return {
            "job_id": job_id,
            "status": "dry_run",
            "provider": "mureka",
            "note": "Dry run is enabled; no live Mureka task exists.",
        }

    metadata = _read_task_meta(job_id)
    kind = metadata.get("kind") or "instrumental"
    if kind not in {"instrumental", "song"}:
        kind = "instrumental"
    query_url = f"{_base_url()}/v1/{kind}/query/{job_id}"

    with httpx.Client(timeout=60) as client:
        response = client.get(query_url, headers=_headers())
        _raise_for_status(response)
        payload = response.json()

    status = str(payload.get("status") or "unknown").lower()
    audio_url = _extract_audio_url(payload)
    output_path = Path(metadata.get("output_path") or _output_path(job_id))
    downloaded = False

    if download and status == "succeeded" and audio_url:
        if output_path.suffix.lower() not in {".mp3", ".wav", ".m4a", ".flac", ".ogg"}:
            output_path = _output_path(job_id, _suffix_from_url(audio_url))
        elif audio_url:
            preferred = _suffix_from_url(audio_url)
            if preferred != output_path.suffix.lower():
                output_path = output_path.with_suffix(preferred)
        if not output_path.exists() or output_path.stat().st_size == 0:
            _download_audio(audio_url, output_path)
        downloaded = True

    metadata.update(
        {
            "job_id": job_id,
            "status": status,
            "audio_url": audio_url,
            "output_path": str(output_path),
            "last_response": payload,
            "updated_at": int(time.time()),
        }
    )
    _write_task_meta(job_id, metadata)

    return {
        "job_id": job_id,
        "status": status,
        "provider": "mureka",
        "mode": metadata.get("mode"),
        "model": payload.get("model") or metadata.get("model"),
        "audio_url": audio_url,
        "output_path": str(output_path) if downloaded or output_path.exists() else None,
        "downloaded": downloaded,
        "failed_reason": payload.get("failed_reason"),
        "raw": payload,
    }


@mcp.tool()
def text_to_music(
    prompt: str = Field(
        description="Music direction: genre, mood, tempo, instruments, and use case."
    ),
    lyrics: str | None = Field(
        default=None,
        description="Optional lyrics. When omitted, generates an instrumental score.",
    ),
    model: str | None = Field(
        default=None,
        description="Mureka model id. Defaults to MUREKA_MODEL or auto.",
    ),
) -> dict:
    """Create a Mureka music task and return the task id immediately."""
    lyrics_value = _field_value(lyrics, None)
    lyrics_text = str(lyrics_value).strip() if isinstance(lyrics_value, str) else ""
    model = _field_value(model, None)
    selected_model = _model(model)

    if lyrics_text:
        mode = "lyrics_to_song"
        if _dry_run():
            return _dry_task(mode=mode, prompt=prompt, model=selected_model)
        return _create_task(
            mode=mode,
            kind="song",
            prompt=prompt,
            body={"lyrics": lyrics_text, "model": selected_model, "prompt": prompt},
            model=selected_model,
        )

    mode = "text_to_instrumental"
    if _dry_run():
        return _dry_task(mode=mode, prompt=prompt, model=selected_model)
    return _create_task(
        mode=mode,
        kind="instrumental",
        prompt=prompt,
        body={"model": selected_model, "prompt": prompt},
        model=selected_model,
    )


@mcp.tool()
def get_music_task(
    job_id: str = Field(description="Mureka task id returned by text_to_music."),
    download: bool = Field(default=True, description="Download the audio when succeeded."),
) -> dict:
    """Poll a Mureka music task and optionally download the finished audio."""
    download = bool(_field_value(download, True))
    return _retrieve_task(job_id, download=download)


@mcp.tool()
def list_mureka_models() -> dict:
    """Describe the default Mureka model selection for this workspace."""
    return {
        "provider": "mureka",
        "default_model": _model(),
        "supported": ["auto", "mureka-6", "mureka-5.5", "mureka-7.6", "mureka-o2"],
        "note": "Use auto unless a specific Mureka model id is required.",
    }


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
