"""Seedream (BytePlus image) provider API."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
import uuid
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel
from pydantic.fields import FieldInfo


class SeedreamResult(BaseModel):
    job_id: str
    status: str
    provider: str = "byteplus-seedream"
    mode: str
    prompt: str
    aspect_ratio: str
    size: str
    model: str | None = None
    output_path: str | None = None
    image_url: str | None = None
    note: str


def _field_value(value: Any, default: Any) -> Any:
    if isinstance(value, FieldInfo):
        return getattr(value, "default", default)
    return value


def _media_dir() -> Path:
    path = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _dry_run() -> bool:
    dry = os.getenv("SEEDREAM_DRY_RUN")
    if dry is None:
        dry = os.getenv("SEEDANCE_DRY_RUN", "true")
    return dry.lower() != "false"


def _base_url() -> str:
    base_url = os.getenv(
        "BYTEPLUS_BASE_URL",
        "https://ark.ap-southeast.bytepluses.com/api/v3",
    ).rstrip("/")
    if not base_url.endswith("/api/v3"):
        base_url = f"{base_url}/api/v3"
    return base_url


def _model(model: str | None = None) -> str:
    return model or os.getenv("SEEDREAM_MODEL") or "seedream-5-0-lite-260128"


def _api_key() -> str:
    key = os.getenv("BYTEPLUS_API_KEY") or os.getenv("ARK_API_KEY")
    if not key:
        raise RuntimeError("BYTEPLUS_API_KEY or ARK_API_KEY is required for live Seedream calls.")
    return key


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }


def _image_dir() -> Path:
    path = _media_dir() / "images"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _output_path(job_id: str, suffix: str = ".png") -> Path:
    return _image_dir() / f"{job_id}{suffix}"


def _as_modelark_image_url(path_or_url: str) -> str:
    if path_or_url.startswith(("http://", "https://", "data:")):
        return path_or_url

    path = Path(path_or_url).expanduser()
    if not path.exists():
        return path_or_url

    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _provider_error(response: httpx.Response) -> RuntimeError:
    try:
        payload = response.json()
    except ValueError:
        message = response.text[:1000]
        return RuntimeError(f"BytePlus API error {response.status_code}: {message}")

    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        code = error.get("code") or "UnknownCode"
        message = error.get("message") or payload
        return RuntimeError(f"BytePlus API error {response.status_code} ({code}): {message}")
    return RuntimeError(f"BytePlus API error {response.status_code}: {payload}")


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_error:
        raise _provider_error(response)


def _size_for_ratio(aspect_ratio: str, size: str) -> str:
    if "x" in size.lower():
        return size
    presets = {
        "1:1": {"1K": "1024x1024", "2K": "2048x2048", "3K": "3072x3072"},
        "16:9": {"1K": "1280x720", "2K": "2560x1440", "3K": "3072x1728"},
        "9:16": {"1K": "720x1280", "2K": "1440x2560", "3K": "1728x3072"},
    }
    return presets.get(aspect_ratio, presets["1:1"]).get(size.upper(), size)


def _suffix_from_url(url: str) -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".png"


def _download_image(image_url: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", image_url, follow_redirects=True, timeout=120) as response:
        response.raise_for_status()
        with output_path.open("wb") as file:
            for chunk in response.iter_bytes():
                if chunk:
                    file.write(chunk)


def _write_b64_image(b64_data: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(base64.b64decode(b64_data))


def _extract_image_payload(response: dict[str, Any]) -> tuple[str | None, str | None]:
    data = response.get("data")
    if not isinstance(data, list) or not data:
        return None, None
    first = data[0]
    if not isinstance(first, dict):
        return None, None
    url = first.get("url")
    b64 = first.get("b64_json")
    return (url if isinstance(url, str) else None, b64 if isinstance(b64, str) else None)


def text_to_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    size: str = "2K",
    model: str | None = None,
    watermark: bool = False,
    response_format: Literal["url", "b64_json"] = "url",
) -> dict:
    """Generate an image with Seedream and save it locally when live."""
    aspect_ratio = str(_field_value(aspect_ratio, "1:1"))
    size = str(_field_value(size, "2K"))
    model = _field_value(model, None)
    watermark = bool(_field_value(watermark, False))
    response_format = _field_value(response_format, "url")
    selected_model = _model(model)
    job_id = f"seedream_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    resolved_size = _size_for_ratio(aspect_ratio, size)

    if _dry_run():
        return SeedreamResult(
            job_id=job_id,
            status="dry_run",
            mode="text_to_image",
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            size=resolved_size,
            model=selected_model,
            output_path=str(_output_path(job_id)),
            note="Dry run only. Set SEEDREAM_DRY_RUN=false to create a live BytePlus image.",
        ).model_dump()

    body: dict[str, Any] = {
        "model": selected_model,
        "prompt": prompt,
        "size": resolved_size,
        "watermark": watermark,
        "response_format": response_format,
    }
    url = f"{_base_url()}/images/generations"
    with httpx.Client(timeout=180) as client:
        response = client.post(url, headers=_headers(), json=body)
        _raise_for_status(response)
        payload = response.json()

    image_url, b64_data = _extract_image_payload(payload)
    if not image_url and not b64_data:
        raise RuntimeError(f"BytePlus image generation returned no image data: {payload}")

    suffix = _suffix_from_url(image_url) if image_url else ".png"
    output_path = _output_path(job_id, suffix)
    if b64_data:
        _write_b64_image(b64_data, output_path)
    elif image_url:
        _download_image(image_url, output_path)

    return SeedreamResult(
        job_id=job_id,
        status="succeeded",
        mode="text_to_image",
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        size=resolved_size,
        model=selected_model,
        output_path=str(output_path),
        image_url=image_url,
        note="Seedream image generated and downloaded.",
    ).model_dump()


def image_to_image(
    image_path_or_url: str,
    prompt: str,
    aspect_ratio: str = "1:1",
    size: str = "2K",
    model: str | None = None,
    watermark: bool = False,
    response_format: Literal["url", "b64_json"] = "url",
) -> dict:
    """Edit or restyle an image with Seedream and save it locally when live."""
    aspect_ratio = str(_field_value(aspect_ratio, "1:1"))
    size = str(_field_value(size, "2K"))
    model = _field_value(model, None)
    watermark = bool(_field_value(watermark, False))
    response_format = _field_value(response_format, "url")
    selected_model = _model(model)
    job_id = f"seedream_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    resolved_size = _size_for_ratio(aspect_ratio, size)
    reference = _as_modelark_image_url(image_path_or_url)

    if _dry_run():
        return SeedreamResult(
            job_id=job_id,
            status="dry_run",
            mode="image_to_image",
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            size=resolved_size,
            model=selected_model,
            output_path=str(_output_path(job_id)),
            note="Dry run only. Set SEEDREAM_DRY_RUN=false to create a live BytePlus image.",
        ).model_dump()

    body: dict[str, Any] = {
        "model": selected_model,
        "prompt": prompt,
        "image": reference,
        "size": resolved_size,
        "watermark": watermark,
        "response_format": response_format,
    }
    url = f"{_base_url()}/images/generations"
    with httpx.Client(timeout=180) as client:
        response = client.post(url, headers=_headers(), json=body)
        _raise_for_status(response)
        payload = response.json()

    image_url, b64_data = _extract_image_payload(payload)
    if not image_url and not b64_data:
        raise RuntimeError(f"BytePlus image generation returned no image data: {payload}")

    suffix = _suffix_from_url(image_url) if image_url else ".png"
    output_path = _output_path(job_id, suffix)
    if b64_data:
        _write_b64_image(b64_data, output_path)
    elif image_url:
        _download_image(image_url, output_path)

    return SeedreamResult(
        job_id=job_id,
        status="succeeded",
        mode="image_to_image",
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        size=resolved_size,
        model=selected_model,
        output_path=str(output_path),
        image_url=image_url,
        note="Seedream image edit generated and downloaded.",
    ).model_dump()


def list_seedream_models() -> dict:
    """List image generation models visible from this BytePlus API key."""
    if _dry_run():
        return {
            "status": "dry_run",
            "models": [],
            "note": "Dry run is enabled; set SEEDREAM_DRY_RUN=false to query BytePlus /models.",
        }
    with httpx.Client(timeout=60) as client:
        response = client.get(f"{_base_url()}/models", headers=_headers())
        _raise_for_status(response)
        payload = response.json()
    models = payload.get("data") if isinstance(payload, dict) else payload
    image_models = []
    if isinstance(models, list):
        for item in models:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "")
            if "seedream" in model_id.lower() or "image" in model_id.lower():
                image_models.append(item)
    return {"status": "ok", "models": image_models or models}


TOOL_HANDLERS = {
    "text_to_image": text_to_image,
    "image_to_image": image_to_image,
    "list_seedream_models": list_seedream_models,
}

GATEWAY_TOOLS = (
    "text_to_image",
    "image_to_image",
    "list_seedream_models",
)
