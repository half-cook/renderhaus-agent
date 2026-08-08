"""Shared Mureka HTTP client used by the local MCP server and the AgentCore Gateway Lambda."""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx


TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "canceled", "timeouted", "timeout"}


def dry_run() -> bool:
    return os.getenv("MUREKA_DRY_RUN", "true").lower() != "false"


def base_url() -> str:
    return os.getenv("MUREKA_API_URL", "https://api.mureka.ai").rstrip("/")


def default_model(model: str | None = None) -> str:
    return (model or os.getenv("MUREKA_MODEL") or "auto").strip() or "auto"


def api_key() -> str:
    key = (os.getenv("MUREKA_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("MUREKA_API_KEY is required for live Mureka calls.")
    return key


def headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
    }


def media_dir() -> Path:
    path = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def music_dir() -> Path:
    path = media_dir() / "music"
    path.mkdir(parents=True, exist_ok=True)
    return path


def task_meta_dir() -> Path:
    path = music_dir() / ".tasks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def task_meta_path(job_id: str) -> Path:
    return task_meta_dir() / f"{job_id}.json"


def write_task_meta(job_id: str, metadata: dict[str, Any]) -> None:
    task_meta_path(job_id).write_text(json.dumps(metadata, indent=2, sort_keys=True))


def read_task_meta(job_id: str) -> dict[str, Any]:
    path = task_meta_path(job_id)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def output_path(job_id: str, suffix: str = ".mp3") -> Path:
    return music_dir() / f"{job_id}{suffix}"


def provider_error(response: httpx.Response) -> RuntimeError:
    try:
        payload = response.json()
    except ValueError:
        return RuntimeError(f"Mureka API error {response.status_code}: {response.text[:1000]}")
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("error") or payload
        return RuntimeError(f"Mureka API error {response.status_code}: {message}")
    return RuntimeError(f"Mureka API error {response.status_code}: {payload}")


def raise_for_status(response: httpx.Response) -> None:
    if response.is_error:
        raise provider_error(response)


def suffix_from_url(url: str) -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if suffix in {".mp3", ".wav", ".m4a", ".flac", ".ogg"}:
        return suffix
    return ".mp3"


def extract_audio_url(payload: dict[str, Any]) -> str | None:
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return None
    for choice in choices:
        if isinstance(choice, dict):
            url = choice.get("url") or choice.get("mp3_url") or choice.get("wav_url")
            if isinstance(url, str) and url:
                return url
    return None


def _request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    timeout: float = 120,
) -> dict[str, Any]:
    url = f"{base_url()}{path}"
    with httpx.Client(timeout=timeout) as client:
        if files is not None:
            response = client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {api_key()}"},
                files=files,
                data=json_body or {},
            )
        else:
            response = client.request(method, url, headers=headers(), json=json_body)
        raise_for_status(response)
        payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected Mureka response type: {type(payload)}")
    return payload


def _dry_async(mode: str, **extra: Any) -> dict[str, Any]:
    job_id = f"mureka_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    return {
        "job_id": job_id,
        "id": job_id,
        "status": "dry_run",
        "provider": "mureka",
        "mode": mode,
        "note": "Dry run only. Set MUREKA_DRY_RUN=false for live Mureka calls.",
        **extra,
    }


def _remember_task(job_id: str, *, kind: str, mode: str, prompt: str | None, model: str | None) -> None:
    write_task_meta(
        job_id,
        {
            "job_id": job_id,
            "kind": kind,
            "mode": mode,
            "prompt": prompt,
            "model": model,
            "output_path": str(output_path(job_id)),
            "created_at": int(time.time()),
        },
    )


def create_instrumental(
    *,
    prompt: str,
    model: str | None = None,
    n: int | None = None,
    instrumental_id: str | None = None,
    stream: bool | None = None,
) -> dict[str, Any]:
    selected = default_model(model)
    if dry_run():
        return _dry_async("text_to_instrumental", prompt=prompt, model=selected)
    body: dict[str, Any] = {"model": selected, "prompt": prompt}
    if n is not None:
        body["n"] = n
    if instrumental_id:
        body["instrumental_id"] = instrumental_id
        body.pop("prompt", None)
    if stream is not None:
        body["stream"] = stream
    payload = _request("POST", "/v1/instrumental/generate", json_body=body)
    job_id = str(payload.get("id") or "")
    if not job_id:
        raise RuntimeError(f"Mureka did not return a task id: {payload}")
    _remember_task(job_id, kind="instrumental", mode="text_to_instrumental", prompt=prompt, model=selected)
    return {
        "job_id": job_id,
        "status": payload.get("status") or "queued",
        "provider": "mureka",
        "mode": "text_to_instrumental",
        "prompt": prompt,
        "model": selected,
        "note": "Live instrumental task created. Poll with query_music_task.",
        "raw": payload,
    }


def create_song(
    *,
    lyrics: str,
    prompt: str = "",
    model: str | None = None,
    n: int | None = None,
    gender: str | None = None,
    reference_id: str | None = None,
    vocal_id: str | None = None,
    melody_id: str | None = None,
    instrumental_id: str | None = None,
    stream: bool | None = None,
) -> dict[str, Any]:
    selected = default_model(model)
    if dry_run():
        return _dry_async("lyrics_to_song", prompt=prompt or lyrics[:120], model=selected)
    body: dict[str, Any] = {"lyrics": lyrics, "model": selected}
    if prompt:
        body["prompt"] = prompt
    if n is not None:
        body["n"] = n
    if gender:
        body["gender"] = gender
    if reference_id:
        body["reference_id"] = reference_id
    if vocal_id:
        body["vocal_id"] = vocal_id
    if melody_id:
        body["melody_id"] = melody_id
    if instrumental_id:
        body["instrumental_id"] = instrumental_id
    if stream is not None:
        body["stream"] = stream
    payload = _request("POST", "/v1/song/generate", json_body=body)
    job_id = str(payload.get("id") or "")
    if not job_id:
        raise RuntimeError(f"Mureka did not return a task id: {payload}")
    _remember_task(
        job_id,
        kind="song",
        mode="lyrics_to_song",
        prompt=prompt or lyrics[:120],
        model=selected,
    )
    return {
        "job_id": job_id,
        "status": payload.get("status") or "queued",
        "provider": "mureka",
        "mode": "lyrics_to_song",
        "model": selected,
        "note": "Live song task created. Poll with query_music_task.",
        "raw": payload,
    }


def create_song_from_prompt(
    *,
    prompt: str,
    model: str | None = None,
    n: int | None = None,
    gender: str | None = None,
) -> dict[str, Any]:
    selected = default_model(model)
    if dry_run():
        return _dry_async("prompt_to_song", prompt=prompt, model=selected)
    body: dict[str, Any] = {"prompt": prompt, "model": selected}
    if n is not None:
        body["n"] = n
    if gender:
        body["gender"] = gender
    # Official "Prompt to song" / easy-generate endpoint.
    payload = _request("POST", "/v1/song/easy-generate", json_body=body)
    job_id = str(payload.get("id") or "")
    if not job_id:
        raise RuntimeError(f"Mureka did not return a task id: {payload}")
    _remember_task(job_id, kind="song", mode="prompt_to_song", prompt=prompt, model=selected)
    return {
        "job_id": job_id,
        "status": payload.get("status") or "queued",
        "provider": "mureka",
        "mode": "prompt_to_song",
        "prompt": prompt,
        "model": selected,
        "note": "Live prompt-to-song task created. Poll with query_music_task.",
        "raw": payload,
    }


def generate_lyrics(*, prompt: str) -> dict[str, Any]:
    if dry_run():
        return {
            "provider": "mureka",
            "mode": "generate_lyrics",
            "status": "dry_run",
            "title": "Dry-run title",
            "lyrics": f"[Verse]\nDry-run lyrics for: {prompt[:200]}",
            "note": "Dry run only.",
        }
    payload = _request("POST", "/v1/lyrics/generate", json_body={"prompt": prompt})
    return {
        "provider": "mureka",
        "mode": "generate_lyrics",
        "status": "succeeded",
        "title": payload.get("title"),
        "lyrics": payload.get("lyrics"),
        "raw": payload,
    }


def extend_lyrics(*, lyrics: str, prompt: str = "") -> dict[str, Any]:
    if dry_run():
        return {
            "provider": "mureka",
            "mode": "extend_lyrics",
            "status": "dry_run",
            "lyrics": f"{lyrics}\n[Verse]\nDry-run extension",
            "note": "Dry run only.",
        }
    body: dict[str, Any] = {"lyrics": lyrics}
    if prompt:
        body["prompt"] = prompt
    payload = _request("POST", "/v1/lyrics/extend", json_body=body)
    return {
        "provider": "mureka",
        "mode": "extend_lyrics",
        "status": "succeeded",
        "lyrics": payload.get("lyrics") or payload.get("extended_lyrics") or payload,
        "raw": payload,
    }


def query_task(*, job_id: str, download: bool = False) -> dict[str, Any]:
    if dry_run() or job_id.startswith("mureka_"):
        meta = read_task_meta(job_id)
        if meta.get("status") == "dry_run" or dry_run():
            return {
                "job_id": job_id,
                "status": "dry_run",
                "provider": "mureka",
                "note": "Dry run is enabled; no live Mureka task exists.",
            }

    metadata = read_task_meta(job_id)
    kind = metadata.get("kind") or "instrumental"
    if kind not in {"instrumental", "song"}:
        kind = "instrumental"
    payload = _request("GET", f"/v1/{kind}/query/{job_id}")
    status = str(payload.get("status") or "unknown").lower()
    audio_url = extract_audio_url(payload)
    path = Path(metadata.get("output_path") or output_path(job_id))
    downloaded = False
    if download and status == "succeeded" and audio_url:
        preferred = suffix_from_url(audio_url)
        if path.suffix.lower() != preferred:
            path = path.with_suffix(preferred)
        if not path.exists() or path.stat().st_size == 0:
            path.parent.mkdir(parents=True, exist_ok=True)
            with httpx.stream("GET", audio_url, follow_redirects=True, timeout=120) as response:
                response.raise_for_status()
                with path.open("wb") as file:
                    for chunk in response.iter_bytes():
                        if chunk:
                            file.write(chunk)
        downloaded = True
    metadata.update(
        {
            "job_id": job_id,
            "status": status,
            "audio_url": audio_url,
            "output_path": str(path),
            "updated_at": int(time.time()),
            "last_response": payload,
        }
    )
    write_task_meta(job_id, metadata)
    return {
        "job_id": job_id,
        "status": status,
        "provider": "mureka",
        "kind": kind,
        "audio_url": audio_url,
        "output_path": str(path) if downloaded or path.exists() else None,
        "downloaded": downloaded,
        "duration_ms": _choice_duration(payload),
        "failed_reason": payload.get("failed_reason"),
        "raw": payload,
    }


def _choice_duration(payload: dict[str, Any]) -> int | None:
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return None
    for choice in choices:
        if isinstance(choice, dict) and isinstance(choice.get("duration"), int):
            return choice["duration"]
    return None


def extend_song(
    *,
    lyrics: str,
    extend_at_ms: int,
    song_id: str | None = None,
    upload_audio_id: str | None = None,
) -> dict[str, Any]:
    if dry_run():
        return _dry_async("extend_song", song_id=song_id, extend_at_ms=extend_at_ms)
    body: dict[str, Any] = {"lyrics": lyrics, "extend_at": str(extend_at_ms)}
    if song_id:
        body["song_id"] = song_id
    if upload_audio_id:
        body["upload_audio_id"] = upload_audio_id
    payload = _request("POST", "/v1/song/extend", json_body=body)
    job_id = str(payload.get("id") or "")
    if job_id:
        _remember_task(job_id, kind="song", mode="extend_song", prompt=lyrics[:120], model=default_model())
    return {"job_id": job_id or None, "status": payload.get("status") or "queued", "raw": payload}


def region_edit_song(
    *,
    lyrics: str,
    edit_start_ms: int,
    edit_end_ms: int,
    song_id: str | None = None,
    upload_audio_id: str | None = None,
) -> dict[str, Any]:
    if dry_run():
        return _dry_async(
            "region_edit_song",
            song_id=song_id,
            edit_start_ms=edit_start_ms,
            edit_end_ms=edit_end_ms,
        )
    body: dict[str, Any] = {
        "lyrics": lyrics,
        "edit_start": edit_start_ms,
        "edit_end": edit_end_ms,
    }
    if song_id:
        body["song_id"] = song_id
    if upload_audio_id:
        body["upload_audio_id"] = upload_audio_id
    payload = _request("POST", "/v1/song/region-edit", json_body=body)
    job_id = str(payload.get("id") or "")
    if job_id:
        _remember_task(job_id, kind="song", mode="region_edit_song", prompt=lyrics[:120], model=default_model())
    return {"job_id": job_id or None, "status": payload.get("status") or "queued", "raw": payload}


def remix_song(
    *,
    prompt: str = "",
    song_id: str | None = None,
    upload_audio_id: str | None = None,
    n: int | None = None,
) -> dict[str, Any]:
    if dry_run():
        return _dry_async("remix_song", prompt=prompt, song_id=song_id)
    body: dict[str, Any] = {}
    if prompt:
        body["prompt"] = prompt
    if song_id:
        body["song_id"] = song_id
    if upload_audio_id:
        body["upload_audio_id"] = upload_audio_id
    if n is not None:
        body["n"] = n
    payload = _request("POST", "/v1/song/remix", json_body=body)
    job_id = str(payload.get("id") or "")
    if job_id:
        _remember_task(job_id, kind="song", mode="remix_song", prompt=prompt, model=default_model())
    return {"job_id": job_id or None, "status": payload.get("status") or "queued", "raw": payload}


def stem_song(
    *,
    song_id: str | None = None,
    upload_audio_id: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    if dry_run():
        return _dry_async("stem_song", song_id=song_id)
    body: dict[str, Any] = {}
    if song_id:
        body["song_id"] = song_id
    if upload_audio_id:
        body["upload_audio_id"] = upload_audio_id
    if model:
        body["model"] = model
    payload = _request("POST", "/v1/song/stem", json_body=body)
    job_id = str(payload.get("id") or payload.get("task_id") or "")
    return {"job_id": job_id or None, "status": payload.get("status") or "queued", "raw": payload}


def recognize_song(*, upload_audio_id: str | None = None, audio_url: str | None = None) -> dict[str, Any]:
    if dry_run():
        return {"provider": "mureka", "mode": "recognize_song", "status": "dry_run", "note": "Dry run only."}
    body: dict[str, Any] = {}
    if upload_audio_id:
        body["upload_audio_id"] = upload_audio_id
    if audio_url:
        body["url"] = audio_url
    payload = _request("POST", "/v1/song/recognize", json_body=body)
    return {"provider": "mureka", "mode": "recognize_song", "status": "succeeded", "raw": payload}


def describe_song(*, upload_audio_id: str | None = None, song_id: str | None = None) -> dict[str, Any]:
    if dry_run():
        return {"provider": "mureka", "mode": "describe_song", "status": "dry_run", "description": "Dry-run description"}
    body: dict[str, Any] = {}
    if upload_audio_id:
        body["upload_audio_id"] = upload_audio_id
    if song_id:
        body["song_id"] = song_id
    payload = _request("POST", "/v1/song/describe", json_body=body)
    return {"provider": "mureka", "mode": "describe_song", "status": "succeeded", "raw": payload}


def transcribe_song(*, upload_audio_id: str | None = None, song_id: str | None = None) -> dict[str, Any]:
    if dry_run():
        return {"provider": "mureka", "mode": "transcribe_song", "status": "dry_run"}
    body: dict[str, Any] = {}
    if upload_audio_id:
        body["upload_audio_id"] = upload_audio_id
    if song_id:
        body["song_id"] = song_id
    payload = _request("POST", "/v1/song/transcribe", json_body=body)
    return {"provider": "mureka", "mode": "transcribe_song", "status": "succeeded", "raw": payload}


def vocal_clone(*, upload_audio_id: str, name: str | None = None) -> dict[str, Any]:
    if dry_run():
        return {"provider": "mureka", "mode": "vocal_clone", "status": "dry_run", "vocal_id": "dry_vocal"}
    body: dict[str, Any] = {"upload_audio_id": upload_audio_id}
    if name:
        body["name"] = name
    payload = _request("POST", "/v1/song/vocal-clone", json_body=body)
    return {"provider": "mureka", "mode": "vocal_clone", "status": "succeeded", "raw": payload}


def generate_track(
    *,
    track_type: str,
    song_id: str | None = None,
    upload_audio_id: str | None = None,
    prompt: str = "",
) -> dict[str, Any]:
    if dry_run():
        return _dry_async("generate_track", track_type=track_type, prompt=prompt)
    body: dict[str, Any] = {"track_type": track_type}
    if song_id:
        body["song_id"] = song_id
    if upload_audio_id:
        body["upload_audio_id"] = upload_audio_id
    if prompt:
        body["prompt"] = prompt
    payload = _request("POST", "/v1/track/generate", json_body=body)
    job_id = str(payload.get("id") or "")
    if job_id:
        _remember_task(job_id, kind="song", mode="generate_track", prompt=prompt or track_type, model=default_model())
    return {"job_id": job_id or None, "status": payload.get("status") or "queued", "raw": payload}


def generate_soundtrack(
    *,
    prompt: str = "",
    upload_file_id: str | None = None,
    audio_start: float | None = None,
    audio_end: float | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    selected = default_model(model)
    if dry_run():
        return _dry_async("generate_soundtrack", prompt=prompt, model=selected)
    body: dict[str, Any] = {"model": selected}
    if prompt:
        body["prompt"] = prompt
    if upload_file_id:
        body["file_id"] = upload_file_id
    if audio_start is not None:
        body["audio_start"] = audio_start
    if audio_end is not None:
        body["audio_end"] = audio_end
    payload = _request("POST", "/v1/soundtrack/generate", json_body=body)
    job_id = str(payload.get("id") or "")
    if job_id:
        _remember_task(job_id, kind="song", mode="generate_soundtrack", prompt=prompt, model=selected)
    return {
        "job_id": job_id or None,
        "status": payload.get("status") or "queued",
        "provider": "mureka",
        "mode": "generate_soundtrack",
        "raw": payload,
    }


def generate_lyrics_video(
    *,
    song_id: str | None = None,
    upload_audio_id: str | None = None,
    aspect_ratio: str | None = None,
    layout: str | None = None,
) -> dict[str, Any]:
    if dry_run():
        return _dry_async("generate_lyrics_video", song_id=song_id)
    body: dict[str, Any] = {}
    if song_id:
        body["song_id"] = song_id
    if upload_audio_id:
        body["upload_audio_id"] = upload_audio_id
    if aspect_ratio:
        body["aspect_ratio"] = aspect_ratio
    if layout:
        body["layout"] = layout
    payload = _request("POST", "/v1/lyrics-video/generate", json_body=body)
    return {"job_id": payload.get("id"), "status": payload.get("status") or "queued", "raw": payload}


def upload_file(*, purpose: str, filename: str, content_b64: str) -> dict[str, Any]:
    if dry_run():
        return {
            "provider": "mureka",
            "mode": "upload_file",
            "status": "dry_run",
            "id": f"upload_{uuid.uuid4().hex[:12]}",
            "purpose": purpose,
            "filename": filename,
        }
    raw = base64.b64decode(content_b64)
    files = {"file": (filename, raw)}
    data = {"purpose": purpose}
    payload = _request("POST", "/v1/files/upload", json_body=data, files=files)
    return {"provider": "mureka", "mode": "upload_file", "status": "succeeded", "raw": payload, **payload}


def create_speech(*, text: str, voice: str | None = None) -> dict[str, Any]:
    if dry_run():
        return _dry_async("create_speech", text=text[:80], voice=voice)
    body: dict[str, Any] = {"text": text}
    if voice:
        body["voice"] = voice
    payload = _request("POST", "/v1/tts/generate", json_body=body)
    return {"provider": "mureka", "mode": "create_speech", "status": payload.get("status") or "queued", "raw": payload}


def create_podcast(*, script: str, title: str | None = None) -> dict[str, Any]:
    if dry_run():
        return _dry_async("create_podcast", title=title or "dry-run")
    body: dict[str, Any] = {"script": script}
    if title:
        body["title"] = title
    payload = _request("POST", "/v1/tts/podcast", json_body=body)
    return {"provider": "mureka", "mode": "create_podcast", "status": payload.get("status") or "queued", "raw": payload}


def query_billing() -> dict[str, Any]:
    if dry_run():
        return {"provider": "mureka", "mode": "query_billing", "status": "dry_run", "note": "Dry run only."}
    payload = _request("GET", "/v1/account/billing")
    return {"provider": "mureka", "mode": "query_billing", "status": "succeeded", "raw": payload}


def list_models() -> dict[str, Any]:
    return {
        "provider": "mureka",
        "default_model": default_model(),
        "supported": [
            "auto",
            "mureka-6",
            "mureka-5.5",
            "mureka-7.5",
            "mureka-7.6",
            "mureka-8",
            "mureka-9",
            "mureka-o1",
            "mureka-o2",
        ],
        "note": "Use auto unless a specific Mureka model id is required.",
    }


# Tool name -> callable used by Lambda and expanded MCP.
TOOL_HANDLERS: dict[str, Any] = {
    "text_to_music": None,  # compatibility shim filled below
    "create_instrumental": create_instrumental,
    "create_song": create_song,
    "create_song_from_prompt": create_song_from_prompt,
    "generate_lyrics": generate_lyrics,
    "extend_lyrics": extend_lyrics,
    "query_music_task": query_task,
    "get_music_task": query_task,  # alias
    "extend_song": extend_song,
    "region_edit_song": region_edit_song,
    "remix_song": remix_song,
    "stem_song": stem_song,
    "recognize_song": recognize_song,
    "describe_song": describe_song,
    "transcribe_song": transcribe_song,
    "vocal_clone": vocal_clone,
    "generate_track": generate_track,
    "generate_soundtrack": generate_soundtrack,
    "generate_lyrics_video": generate_lyrics_video,
    "upload_file": upload_file,
    "create_speech": create_speech,
    "create_podcast": create_podcast,
    "query_billing": query_billing,
    "list_mureka_models": list_models,
}


def text_to_music(
    *,
    prompt: str,
    lyrics: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Backward-compatible entry used by the existing music agent."""
    lyrics_text = (lyrics or "").strip()
    if lyrics_text:
        return create_song(lyrics=lyrics_text, prompt=prompt, model=model)
    return create_instrumental(prompt=prompt, model=model)


TOOL_HANDLERS["text_to_music"] = text_to_music


def dispatch_tool(tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    args = dict(arguments or {})
    # Normalize common aliases from older callers.
    if "job_id" in args and tool_name in {"query_music_task", "get_music_task"}:
        pass
    if tool_name == "get_music_task":
        tool_name = "query_music_task"
    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        raise ValueError(f"Unknown Mureka tool: {tool_name}")
    # Drop nulls so optional kwargs stay optional.
    cleaned = {key: value for key, value in args.items() if value is not None}
    return handler(**cleaned)
