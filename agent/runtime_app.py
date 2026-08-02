"""Bedrock AgentCore Runtime HTTP entrypoint for the Renderhaus LangChain agent + MCPs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from agent.config import load_local_env, mcp_config_path
from agent.media_store import download_storage_key, upload_local_media
from agent.service import (
    invoke_agent,
    poll_music_generation,
    poll_video_generation,
    start_image_generation,
    start_music_generation,
    start_video_generation,
)


load_local_env()
os.environ.setdefault("AGENTCORE_RUNTIME", "1")

app = FastAPI(title="Renderhaus AgentCore Runtime", version="0.1.0")

REF_DIR = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser() / ".refs"
REF_DIR.mkdir(parents=True, exist_ok=True)


async def _payload(request: Request) -> dict[str, Any]:
    """Normalize AgentCore / local payloads into a flat action dict."""
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {exc}") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object body required.")
    if isinstance(body.get("input"), dict):
        data = dict(body["input"])
    else:
        data = dict(body)
    if isinstance(body.get("prompt"), str) and "prompt" not in data:
        data["prompt"] = body["prompt"]
    if isinstance(body.get("action"), str) and "action" not in data:
        data["action"] = body["action"]
    return data


def _materialize_reference(storage_key: str | None) -> str | None:
    if not storage_key:
        return None
    filename = Path(storage_key).name or "reference.bin"
    destination = REF_DIR / filename
    download_storage_key(storage_key, destination)
    return str(destination.resolve())


def _with_reference_prompt(prompt: str, reference_path: str | None) -> str:
    if not reference_path:
        return prompt
    if reference_path in prompt:
        return prompt
    return f"{prompt}\nUse this local reference image: {reference_path}."


def _publish_path(
    path: str | None,
    *,
    user_id: str,
    kind: str,
) -> dict[str, Any] | None:
    if not path:
        return None
    candidate = Path(path).expanduser()
    if not candidate.is_file() or candidate.stat().st_size <= 0:
        return None
    return upload_local_media(user_id=user_id, source_path=candidate, kind=kind)  # type: ignore[arg-type]


def _enrich_artifacts(result: dict[str, Any], *, user_id: str, kind: str) -> dict[str, Any]:
    artifacts = []
    for artifact in result.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        item = dict(artifact)
        status = str(item.get("status") or "").lower()
        if status in {"succeeded", "complete", ""} and item.get("output_path"):
            published = _publish_path(str(item["output_path"]), user_id=user_id, kind=kind)
            if published:
                item.update(published)
                item.pop("output_path", None)
        artifacts.append(item)
    enriched = dict(result)
    enriched["artifacts"] = artifacts
    return enriched


def _enrich_poll(result: dict[str, Any], *, user_id: str, kind: str) -> dict[str, Any]:
    item = dict(result)
    status = str(item.get("status") or "").lower()
    if status == "succeeded":
        published = _publish_path(
            item.get("output_path") if isinstance(item.get("output_path"), str) else None,
            user_id=user_id,
            kind=kind,
        )
        if published:
            item.update(published)
            item.pop("output_path", None)
    return item


@app.get("/ping")
async def ping() -> dict[str, str]:
    return {"status": "Healthy"}


@app.post("/invocations")
async def invocations(request: Request) -> dict[str, Any]:
    data = await _payload(request)
    action = str(data.get("action") or "invoke_agent").strip()
    prompt = data.get("prompt")
    user_id = str(data.get("user_id") or "agentcore")
    reference_storage_key = data.get("reference_storage_key")
    if reference_storage_key is not None and not isinstance(reference_storage_key, str):
        raise HTTPException(status_code=400, detail="reference_storage_key must be a string.")

    try:
        reference_path = _materialize_reference(reference_storage_key)
        config_path = mcp_config_path()

        if action == "invoke_agent":
            if not isinstance(prompt, str) or not prompt.strip():
                raise HTTPException(status_code=400, detail="prompt is required.")
            result = await invoke_agent(
                _with_reference_prompt(prompt, reference_path),
                config_path=config_path,
                local_only=True,
            )
            return {"output": result}

        if action == "start_video_generation":
            if not isinstance(prompt, str) or not prompt.strip():
                raise HTTPException(status_code=400, detail="prompt is required.")
            result = await start_video_generation(
                _with_reference_prompt(prompt, reference_path),
                local_only=True,
            )
            return {"output": _enrich_artifacts(result, user_id=user_id, kind="video")}

        if action == "start_image_generation":
            if not isinstance(prompt, str) or not prompt.strip():
                raise HTTPException(status_code=400, detail="prompt is required.")
            result = await start_image_generation(
                _with_reference_prompt(prompt, reference_path),
                local_only=True,
            )
            return {"output": _enrich_artifacts(result, user_id=user_id, kind="image")}

        if action == "start_music_generation":
            if not isinstance(prompt, str) or not prompt.strip():
                raise HTTPException(status_code=400, detail="prompt is required.")
            result = await start_music_generation(prompt, local_only=True)
            return {"output": _enrich_artifacts(result, user_id=user_id, kind="music")}

        if action == "poll_video_generation":
            job_id = data.get("job_id")
            if not isinstance(job_id, str) or not job_id.strip():
                raise HTTPException(status_code=400, detail="job_id is required.")
            result = await poll_video_generation(job_id, local_only=True)
            return {"output": _enrich_poll(result, user_id=user_id, kind="video")}

        if action == "poll_music_generation":
            job_id = data.get("job_id")
            if not isinstance(job_id, str) or not job_id.strip():
                raise HTTPException(status_code=400, detail="job_id is required.")
            result = await poll_music_generation(job_id, local_only=True)
            return {"output": _enrich_poll(result, user_id=user_id, kind="music")}

        raise HTTPException(status_code=400, detail=f"Unsupported action: {action}")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - surface agent failures to AgentCore client
        return {"output": {"error": str(exc), "status": "failed"}}
