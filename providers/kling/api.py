"""Kling official direct API, documented shapes verified on 2026-10-08.

Current API uses a bearer API key. Legacy endpoints use AK/SK signed JWTs.
Official documentation:
https://kling.ai/document-api/api/get-started/authentication
https://kling.ai/document-api/api/video/3-0-omni/text-to-video
https://kling.ai/document-api/api/video/3-0-omni/image-to-video
https://kling.ai/document-api/api/video/3-0-omni/video-omni
https://kling.ai/document-api/api/video/3-0-turbo/text-to-video
https://kling.ai/document-api/api/video/3-0-turbo/image-to-video
https://kling.ai/document-api/api/video/3-0-omni/text-to-video/legacy
https://kling.ai/document-api/api/video/3-0-omni/image-to-video/legacy
https://kling.ai/document-api/api/video/3-0-omni/video-omni/legacy

The documented model catalog is static. Account activation and live API behavior
have not been verified. No official model-discovery endpoint was confirmed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import inspect
import json
import os
import re
import struct
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import boto3
import httpx

from providers.contracts import validate_tool_arguments


MODELS = {
    "kling-3.0": {
        "tools": ("text_to_video", "image_to_video"),
        "resolutions": ("720p", "1080p", "4k"),
        "native_audio": True,
        "last_frame": True,
        "elements": True,
        "legacy_model": "kling-v3",
    },
    "kling-3.0-turbo": {
        "tools": ("text_to_video", "image_to_video"),
        "resolutions": ("720p", "1080p"),
        "native_audio": False,
        "last_frame": False,
        "elements": False,
        "legacy_model": None,
    },
    "kling-3.0-omni": {
        "tools": ("omni_video",),
        "resolutions": ("720p", "1080p", "4k"),
        "native_audio": True,
        "last_frame": True,
        "elements": True,
        "legacy_model": "kling-v3-omni",
    },
}
LEGACY_ENDPOINTS = {
    "text_to_video": "/v1/videos/text2video",
    "image_to_video": "/v1/videos/image2video",
    "omni_video": "/v1/videos/omni-video",
}
STATES = {
    "submitted": "queued",
    "processing": "running",
    "succeeded": "succeeded",
    "succeed": "succeeded",
    "failed": "failed",
}
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")


def _dry_run() -> bool:
    return os.getenv("KLING_DRY_RUN", "true").lower() != "false"


def _api_style() -> str:
    style = os.getenv("KLING_API_STYLE", "current")
    if style not in {"current", "legacy"}:
        raise ValueError("KLING_API_STYLE must be current or legacy.")
    return style


def _https_url(value: str, field: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"{field} must be an HTTPS URL without embedded credentials.")
    return value


def _base_url() -> str:
    value = os.getenv("KLING_BASE_URL", "https://api-singapore.klingai.com").rstrip("/")
    _https_url(value, "KLING_BASE_URL")
    if urlsplit(value).query or urlsplit(value).fragment:
        raise ValueError("KLING_BASE_URL must not contain a query or fragment.")
    return value


def _secrets(keys: tuple[str, ...]) -> dict[str, str]:
    values = {key: os.getenv(key, "") for key in keys}
    secret_name = os.getenv("RENDERHAUS_SECRETS_ARN") or os.getenv("RENDERHAUS_SECRETS_NAME")
    if all(values.values()) or not secret_name:
        return values
    try:
        response = boto3.client("secretsmanager").get_secret_value(SecretId=secret_name)
        payload = json.loads(response.get("SecretString") or "{}")
        if not isinstance(payload, dict):
            raise ValueError("Invalid secret shape")
    except Exception:
        raise RuntimeError("Could not load Kling credentials from Secrets Manager.") from None
    for key in keys:
        if not values[key] and isinstance(payload.get(key), str):
            values[key] = payload[key]
    return values


def _signed_jwt(access_key: str, secret_key: str, now: int | None = None) -> str:
    timestamp = int(time.time()) if now is None else now

    def encoded(value: dict[str, Any]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    header = encoded({"alg": "HS256", "typ": "JWT"})
    payload = encoded({"iss": access_key, "exp": timestamp + 1800, "nbf": timestamp - 5})
    message = f"{header}.{payload}"
    signature = hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).digest()
    return f"{message}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def _headers(style: str) -> dict[str, str]:
    if style == "current":
        credentials = _secrets(("KLING_API_KEY",))
        token = credentials["KLING_API_KEY"]
        if not token:
            raise RuntimeError("KLING_API_KEY is required for current Kling API calls.")
    else:
        credentials = _secrets(("KLING_ACCESS_KEY", "KLING_SECRET_KEY"))
        if not all(credentials.values()):
            raise RuntimeError(
                "KLING_ACCESS_KEY and KLING_SECRET_KEY are required for legacy Kling."
            )
        token = _signed_jwt(credentials["KLING_ACCESS_KEY"], credentials["KLING_SECRET_KEY"])
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _image_dimensions(data: bytes) -> tuple[int, int]:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("Local reference image must be a JPEG or PNG.")
    position = 2
    while position + 4 <= len(data):
        if data[position] != 255:
            break
        while position < len(data) and data[position] == 255:
            position += 1
        if position >= len(data):
            break
        marker = data[position]
        position += 1
        if marker in {0x01, 0xD8} or 0xD0 <= marker <= 0xD7:
            continue
        if marker in {0xD9, 0xDA} or position + 2 > len(data):
            break
        length = int.from_bytes(data[position : position + 2], "big")
        if length < 2 or position + length > len(data):
            break
        if (
            marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
            and length >= 7
        ):
            height, width = struct.unpack(">HH", data[position + 3 : position + 7])
            return width, height
        position += length
    raise ValueError("Could not read local JPEG dimensions.")


def _image_input(value: str, style: str) -> str:
    if value.startswith("https://"):
        # Remote format, size and dimensions require provider-side validation.
        return _https_url(value, "Reference image")
    if value.startswith(("http:", "data:")) or "://" in value:
        raise ValueError("Reference images must be HTTPS URLs or local JPEG/PNG paths.")
    path = Path(value).expanduser()
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png"} or not path.is_file():
        raise ValueError("Reference image must be an existing local JPEG/PNG or an HTTPS URL.")
    maximum = (10 if style == "legacy" else 50) * 1024 * 1024
    if path.stat().st_size > maximum:
        raise ValueError(f"Reference image exceeds the {maximum // (1024 * 1024)}MB limit.")
    data = path.read_bytes()
    width, height = _image_dimensions(data)
    if min(width, height) < 300 or not 0.4 <= width / height <= 2.5:
        raise ValueError("Reference image needs dimensions >=300px and aspect ratio 0.4 to 2.5.")
    return base64.b64encode(data).decode("ascii")


def _shots(args: dict[str, Any], maximum_prompt: int) -> tuple[str, list[dict[str, Any]]]:
    prompt = args["prompt"]
    if not prompt.strip() or len(prompt) > maximum_prompt:
        raise ValueError(f"prompt must be nonempty and at most {maximum_prompt} characters.")
    shots = args.get("shots")
    if shots is None:
        return prompt, []
    if not args["multi_shot"]:
        raise ValueError("shots requires multi_shot=true.")
    if not 1 <= len(shots) <= 6:
        raise ValueError("shots must contain 1 to 6 shots.")
    for shot in shots:
        if not shot["prompt"].strip() or len(shot["prompt"]) > 512:
            raise ValueError("Each shot prompt must be nonempty and at most 512 characters.")
        if shot["duration_seconds"] < 1:
            raise ValueError("Each shot duration_seconds must be at least 1.")
        if ";" in shot["prompt"]:
            raise ValueError("Shot prompts cannot contain the semicolon shot separator.")
    if sum(shot["duration_seconds"] for shot in shots) != args["duration_seconds"]:
        raise ValueError("Shot durations must sum to duration_seconds.")
    formatted = " ".join(
        f"shot {index}, {shot['duration_seconds']}, {shot['prompt']};"
        for index, shot in enumerate(shots, 1)
    )
    if len(formatted) > maximum_prompt:
        raise ValueError(f"Combined shot prompt exceeds {maximum_prompt} characters.")
    return formatted, shots


def _references(args: dict[str, Any]) -> None:
    elements = args.get("elements") or []
    refs = args.get("reference_images") or []
    first = args.get("image_path_or_url")
    last = args.get("end_image_path_or_url")
    if last and not first:
        raise ValueError("end_image_path_or_url requires image_path_or_url.")
    ids = [element["id"] for element in elements]
    generated_ids = [f"image_{i}" for i in range(1, len(refs) + 1)]
    if first:
        generated_ids.append("first_frame")
    if last:
        generated_ids.append("last_frame")
    if len(set(ids + generated_ids)) != len(ids + generated_ids):
        raise ValueError("Element ids must be unique and must not conflict with image ids.")
    for element in elements:
        if not SAFE_ID.fullmatch(element["element_id"]) or not SAFE_ID.fullmatch(element["id"]):
            raise ValueError("Element element_id and id must use letters, digits, '_' or '-'.")
        if element["element_type"] not in {"multi_image_elements", "video_character_elements"}:
            raise ValueError(
                "element_type must be multi_image_elements or video_character_elements."
            )
    video_count = sum(e["element_type"] == "video_character_elements" for e in elements)
    image_count = len(elements) - video_count
    if video_count > 3:
        raise ValueError("At most 3 video character elements are supported.")
    if first and len(elements) > 3:
        raise ValueError("First-frame generation supports at most 3 elements.")
    maximum = 4 if video_count else 7
    if len(refs) + bool(first) + bool(last) + image_count > maximum:
        raise ValueError(f"Combined images and multi-image elements must not exceed {maximum}.")


def prepare_request(tool_name: str, arguments: dict[str, Any]) -> tuple[str, str, str, dict]:
    """Validate arguments and build a documented request before authentication or I/O."""
    schema = next(tool for tool in GATEWAY_SCHEMAS if tool["name"] == tool_name)
    cleaned = validate_tool_arguments("kling", tool_name, arguments, schema["inputSchema"])
    bound = inspect.signature(TOOL_HANDLERS[tool_name]).bind(**cleaned)
    bound.apply_defaults()
    args = dict(bound.arguments)
    style = _api_style()
    selected_model = (
        "kling-3.0-omni"
        if tool_name == "omni_video"
        else args.get("model") or os.getenv("KLING_MODEL") or "kling-3.0"
    )
    capability = MODELS.get(selected_model)
    if not capability or tool_name not in capability["tools"]:
        raise ValueError("model is not a documented Kling model for this tool.")
    if style == "legacy" and not capability["legacy_model"]:
        raise ValueError("Kling 3.0 Turbo has no confirmed legacy endpoint.")
    if not 3 <= args["duration_seconds"] <= 15:
        raise ValueError("duration_seconds must be between 3 and 15.")
    if args["resolution"] not in capability["resolutions"]:
        raise ValueError("resolution is unsupported by this model.")
    if args.get("aspect_ratio", "16:9") not in {"16:9", "9:16", "1:1"}:
        raise ValueError("aspect_ratio must be 16:9, 9:16, or 1:1.")
    if args["generate_audio"] and not capability["native_audio"]:
        raise ValueError("Native audio is not documented for Kling 3.0 Turbo.")
    if args.get("end_image_path_or_url") and not capability["last_frame"]:
        raise ValueError("Last-frame input is not supported by this model.")
    if args.get("elements") and not capability["elements"]:
        raise ValueError("Elements are not supported by this model.")
    maximum = (
        2500
        if style == "legacy"
        or (selected_model == "kling-3.0-turbo" and tool_name == "image_to_video")
        else 3072
    )
    prompt, shots = _shots(args, maximum)
    _references(args)
    if style == "legacy":
        return (
            style,
            selected_model,
            LEGACY_ENDPOINTS[tool_name],
            _legacy_request(tool_name, args, capability["legacy_model"], shots),
        )
    settings: dict[str, Any] = {
        "duration": args["duration_seconds"],
        "resolution": args["resolution"],
    }
    if "aspect_ratio" in args and not args.get("image_path_or_url"):
        settings["aspect_ratio"] = args["aspect_ratio"]
    if selected_model != "kling-3.0-turbo":
        settings.update(
            audio="native" if args["generate_audio"] else "off", multi_shot=args["multi_shot"]
        )
    # Turbo documents multi-shot prompt syntax but no settings.multi_shot or audio field.
    if tool_name == "text_to_video":
        body = {"prompt": prompt, "settings": settings}
    else:
        contents: list[dict[str, Any]] = [{"type": "prompt", "text": prompt}]
        for field, kind in (
            ("image_path_or_url", "first_frame"),
            ("end_image_path_or_url", "last_frame"),
        ):
            if args.get(field):
                item = {"type": kind, "url": _image_input(args[field], style)}
                if tool_name == "omni_video":
                    item["id"] = kind
                contents.append(item)
        contents.extend(
            {"type": "refer_image", "url": _image_input(value, style), "id": f"image_{i}"}
            for i, value in enumerate(args.get("reference_images") or [], 1)
        )
        contents.extend(
            {"type": "element", "element_id": e["element_id"], "id": e["id"]}
            for e in args.get("elements") or []
        )
        body = {"contents": contents, "settings": settings}
    return style, selected_model, f"/{tool_name.replace('_', '-')}/{selected_model}", body


def _legacy_request(tool_name: str, args: dict, model: str, shots: list[dict]) -> dict:
    body: dict[str, Any] = {
        "model_name": model,
        "duration": str(args["duration_seconds"]),
        "mode": {"720p": "std", "1080p": "pro", "4k": "4k"}[args["resolution"]],
        "sound": "on" if args["generate_audio"] else "off",
        "multi_shot": args["multi_shot"],
    }
    if args["multi_shot"]:
        body["shot_type"] = "customize" if shots else "intelligence"
    if shots:
        body["multi_prompt"] = [
            {"index": i, "prompt": shot["prompt"], "duration": str(shot["duration_seconds"])}
            for i, shot in enumerate(shots, 1)
        ]
    else:
        body["prompt"] = args["prompt"]
    if "aspect_ratio" in args and not args.get("image_path_or_url"):
        body["aspect_ratio"] = args["aspect_ratio"]
    if tool_name == "image_to_video":
        body["image"] = _image_input(args["image_path_or_url"], "legacy")
        if args.get("end_image_path_or_url"):
            body["image_tail"] = _image_input(args["end_image_path_or_url"], "legacy")
    elif tool_name == "omni_video":
        image_list = [
            {"image_url": _image_input(value, "legacy")}
            for value in args.get("reference_images") or []
        ]
        for field, kind in (
            ("image_path_or_url", "first_frame"),
            ("end_image_path_or_url", "end_frame"),
        ):
            if args.get(field):
                image_list.append({"image_url": _image_input(args[field], "legacy"), "type": kind})
        if image_list:
            body["image_list"] = image_list
    elements = args.get("elements") or []
    if elements:
        if any(not e["element_id"].isdigit() for e in elements):
            raise ValueError("Legacy element_id must be a decimal integer string.")
        body["element_list"] = [{"element_id": int(e["element_id"])} for e in elements]
    return body


def _response(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError(f"Kling returned invalid JSON (HTTP {response.status_code}).") from None
    if not isinstance(payload, dict):
        raise RuntimeError("Kling returned an invalid response object.")
    code = payload.get("code")
    if response.is_error or type(code) is not int or code != 0:
        safe_code = str(code) if type(code) is int else "invalid"
        request_id = payload.get("request_id")
        suffix = (
            f", request_id={request_id}"
            if isinstance(request_id, str) and SAFE_ID.fullmatch(request_id)
            else ""
        )
        raise RuntimeError(
            f"Kling API error (HTTP {response.status_code}, code={safe_code}{suffix})."
        )
    return payload


def _submit(tool_name: str, arguments: dict) -> dict:
    style, model, path, body = prepare_request(tool_name, arguments)
    if _dry_run():
        return {
            "job_id": f"{style}:{tool_name}:dry_{uuid.uuid4().hex}",
            "status": "dry_run",
            "provider": "kling",
            "model": model,
            "mode": tool_name,
            "duration_seconds": arguments["duration_seconds"],
            "resolution": arguments["resolution"],
            "note": "Dry run only. Set KLING_DRY_RUN=false to submit a paid Kling request.",
        }
    try:
        with httpx.Client(timeout=60) as client:
            payload = _response(
                client.post(f"{_base_url()}{path}", headers=_headers(style), json=body)
            )
    except httpx.HTTPError:
        raise RuntimeError("Kling submission failed at the HTTP boundary.") from None
    data = payload.get("data")
    task_id = (
        data.get("id" if style == "current" else "task_id") if isinstance(data, dict) else None
    )
    if not isinstance(task_id, str) or not SAFE_ID.fullmatch(task_id):
        raise RuntimeError("Kling submission did not return a valid task id.")
    raw_state = data.get("status" if style == "current" else "task_status")
    if not isinstance(raw_state, str) or raw_state not in STATES:
        raise RuntimeError("Kling submission returned an unknown task state.")
    # Submission responses have no artifacts. Completion requires polling their outputs.
    status = "queued" if STATES[raw_state] == "succeeded" else STATES[raw_state]
    return {
        "job_id": f"{style}:{tool_name}:{task_id}",
        "task_id": task_id,
        "status": status,
        "provider": "kling",
        "model": model,
        "mode": tool_name,
        "duration_seconds": arguments["duration_seconds"],
        "resolution": arguments["resolution"],
        "note": "Poll get_video_task with this job_id to retrieve completed media.",
    }


def text_to_video(
    prompt: str,
    duration_seconds: int = 5,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    model: str | None = None,
    generate_audio: bool = False,
    multi_shot: bool = False,
    shots: list[dict] | None = None,
) -> dict:
    """Submit a Kling text-to-video job, optionally with native audio and structured shots."""
    return _submit("text_to_video", locals())


def image_to_video(
    image_path_or_url: str,
    prompt: str,
    duration_seconds: int = 5,
    resolution: str = "720p",
    model: str | None = None,
    end_image_path_or_url: str | None = None,
    generate_audio: bool = False,
    multi_shot: bool = False,
    shots: list[dict] | None = None,
    elements: list[dict] | None = None,
) -> dict:
    """Submit first-frame video generation, optionally with a last frame or existing elements."""
    return _submit("image_to_video", locals())


def omni_video(
    prompt: str,
    reference_images: list[str] | None = None,
    elements: list[dict] | None = None,
    image_path_or_url: str | None = None,
    end_image_path_or_url: str | None = None,
    duration_seconds: int = 5,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    generate_audio: bool = False,
    multi_shot: bool = False,
    shots: list[dict] | None = None,
) -> dict:
    """Submit Kling 3.0 Omni video using reference images, frames or existing library elements."""
    return _submit("omni_video", locals())


def _parse_job_id(job_id: str) -> tuple[str, str, str]:
    parts = job_id.split(":")
    if (
        len(parts) != 3
        or parts[0] not in {"current", "legacy"}
        or parts[1] not in LEGACY_ENDPOINTS
        or not SAFE_ID.fullmatch(parts[2])
    ):
        raise ValueError("job_id must be the exact id returned by a Kling generation tool.")
    return parts[0], parts[1], parts[2]


def _download_video(video_url: str, output_path: Path) -> None:
    _https_url(video_url, "Generated video")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output_path.parent, suffix=".part", delete=False
        ) as file:
            temporary = Path(file.name)
            with httpx.stream("GET", video_url, follow_redirects=True, timeout=120) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    file.write(chunk)
        if temporary.stat().st_size == 0:
            raise RuntimeError("Kling video download returned an empty artifact.")
        temporary.replace(output_path)
    except httpx.HTTPError:
        raise RuntimeError("Kling video download failed at the HTTP boundary.") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def get_video_task(job_id: str, download: bool = False) -> dict:
    """Poll one Kling job and optionally persist every completed MP4."""
    schema = next(tool for tool in GATEWAY_SCHEMAS if tool["name"] == "get_video_task")
    validate_tool_arguments(
        "kling", "get_video_task", {"job_id": job_id, "download": download}, schema["inputSchema"]
    )
    style, tool_name, task_id = _parse_job_id(job_id)
    if _dry_run() or task_id.startswith("dry_"):
        return {
            "job_id": job_id,
            "status": "dry_run",
            "provider": "kling",
            "note": "Dry run only. No live task was queried.",
        }
    path = "/tasks" if style == "current" else f"{LEGACY_ENDPOINTS[tool_name]}/{task_id}"
    try:
        with httpx.Client(timeout=60) as client:
            payload = _response(
                client.get(
                    f"{_base_url()}{path}",
                    headers=_headers(style),
                    params={"task_ids": task_id} if style == "current" else None,
                )
            )
    except httpx.HTTPError:
        raise RuntimeError("Kling polling failed at the HTTP boundary.") from None
    data = payload.get("data")
    if style == "current":
        matches = (
            [item for item in data if isinstance(item, dict) and item.get("id") == task_id]
            if isinstance(data, list)
            else []
        )
        if len(matches) != 1:
            raise RuntimeError("Kling polling returned no unique matching task.")
        data = matches[0]
    if not isinstance(data, dict) or data.get("id" if style == "current" else "task_id") != task_id:
        raise RuntimeError("Kling polling returned a mismatched task.")
    raw_state = data.get("status" if style == "current" else "task_status")
    if not isinstance(raw_state, str) or raw_state not in STATES:
        raise RuntimeError("Kling polling returned an unknown task state.")
    status = STATES[raw_state]
    videos: list[dict] = []
    if status == "succeeded":
        result = data.get("task_result")
        outputs = (
            data.get("outputs")
            if style == "current"
            else result.get("videos")
            if isinstance(result, dict)
            else None
        )
        if not isinstance(outputs, list):
            raise RuntimeError("Kling succeeded without a video output list.")
        for i, item in enumerate(outputs):
            if not isinstance(item, dict):
                raise RuntimeError("Kling returned a malformed video output.")
            if style == "current" and item.get("type") != "video":
                continue
            url = item.get("url")
            if not isinstance(url, str) or not url:
                raise RuntimeError("Kling returned a video without a URL.")
            _https_url(url, "Generated video")
            output_path = (
                Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")).expanduser()
                / "video"
                / f"kling_{style}_{tool_name}_{task_id}_{i}.mp4"
            )
            exists = output_path.is_file() and output_path.stat().st_size > 0
            if download and not exists:
                _download_video(url, output_path)
                exists = True
            videos.append(
                {
                    "video_url": url,
                    "output_path": str(output_path) if exists else None,
                    "downloaded": bool(download and exists),
                }
            )
        if not videos:
            raise RuntimeError("Kling succeeded without any video artifacts.")
    return {
        "job_id": job_id,
        "task_id": task_id,
        "status": status,
        "provider": "kling",
        "videos": videos,
        "video_url": videos[0]["video_url"] if videos else None,
        "output_path": videos[0]["output_path"] if videos else None,
        "downloaded": bool(videos and download),
        "note": "Kling task failed. Inspect the provider console for the failure reason."
        if status == "failed"
        else "Kling task queried.",
    }


def list_kling_models() -> dict:
    """List the documented model catalog without network calls or activation claims."""
    style = _api_style()
    return {
        "status": "ok",
        "provider": "kling",
        "source": "documented_catalog",
        "selected_model": os.getenv("KLING_MODEL") or "kling-3.0",
        "api_style": style,
        "models": [
            {
                "id": model,
                **capability,
                "native_audio": capability["native_audio"] if model != "kling-3.0-turbo" else None,
                "multi_shot": True,
                "duration_seconds": [3, 15],
                "available_in_api_style": style == "current" or bool(capability["legacy_model"]),
            }
            for model, capability in MODELS.items()
        ],
        "note": "Static official documentation catalog. Account activation is unverified. No model-discovery endpoint was confirmed. Turbo has no documented audio-control field; its output audio semantics are unconfirmed.",
    }


TOOL_HANDLERS = {
    "text_to_video": text_to_video,
    "image_to_video": image_to_video,
    "omni_video": omni_video,
    "get_video_task": get_video_task,
    "list_kling_models": list_kling_models,
}
GATEWAY_TOOLS = tuple(TOOL_HANDLERS)


def _schemas() -> list[dict]:
    fields = {
        "prompt": {
            "type": "string",
            "description": "Nonempty prompt. Maximum 3072 characters on current API, 2500 on legacy API or Turbo image-to-video. Current Omni uses @image_1 and @<id> element aliases; legacy uses ordinal <<<image_1>>> and <<<element_1>>> references.",
        },
        "duration_seconds": {"type": "integer"},
        "aspect_ratio": {"type": "string"},
        "resolution": {"type": "string"},
        "model": {"type": "string"},
        "generate_audio": {"type": "boolean"},
        "multi_shot": {"type": "boolean"},
        "image_path_or_url": {
            "type": "string",
            "description": "HTTPS URL or existing local JPEG/PNG first-frame image. At least 300px per side and aspect ratio 0.4 to 2.5. Limit 50MB current, 10MB legacy. Remote image properties are checked by Kling.",
        },
        "end_image_path_or_url": {
            "type": "string",
            "description": "Optional last-frame image with the same requirements as the first frame. Requires a first frame and is unavailable for Turbo.",
        },
        "reference_images": {
            "type": "array",
            "items": {"type": "string"},
            "description": "HTTPS URLs or local JPEG/PNG images. Current prompt aliases are @image_1, @image_2, etc. Images and multi-image elements share a total limit of 7, or 4 when video-character elements are present.",
        },
        "shots": {
            "type": "array",
            "description": "1 to 6 shots. Requires multi_shot=true. Each prompt has at most 512 characters; each duration is at least 1 second, and durations sum to duration_seconds. Converted to the official prompt syntax or legacy multi_prompt.",
            "items": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "duration_seconds": {"type": "integer"},
                },
                "required": ["prompt", "duration_seconds"],
            },
        },
        "elements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "element_id": {
                        "type": "string",
                        "description": "Existing provider element library ID. Legacy requires a decimal integer string.",
                    },
                    "id": {
                        "type": "string",
                        "description": "Unique current-API prompt alias without @. This tool references an existing element and does not create one.",
                    },
                    "element_type": {
                        "type": "string",
                        "description": "multi_image_elements or video_character_elements. Required for enforcing reference limits; not sent to Kling.",
                    },
                },
                "required": ["element_id", "id", "element_type"],
            },
        },
        "job_id": {"type": "string"},
        "download": {"type": "boolean"},
    }
    tools = []
    for name, fn in TOOL_HANDLERS.items():
        parameters = inspect.signature(fn).parameters
        tools.append(
            {
                "name": name,
                "description": inspect.getdoc(fn),
                "inputSchema": {
                    "type": "object",
                    "properties": {key: fields[key] for key in parameters},
                    "required": [
                        key
                        for key, param in parameters.items()
                        if param.default is inspect.Parameter.empty
                    ],
                },
            }
        )
    return tools


GATEWAY_SCHEMAS = _schemas()
