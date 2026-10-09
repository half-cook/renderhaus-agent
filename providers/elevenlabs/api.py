"""One authenticated HTTP dispatcher for the allowed ElevenLabs media features."""
from __future__ import annotations

import base64
from email.parser import BytesParser
from email.policy import default as email_policy
from functools import lru_cache
import json
import mimetypes
import os
from pathlib import Path
import tempfile
from typing import Any
from urllib.parse import quote, urlsplit
import uuid

import boto3
import httpx
from jsonschema import Draft202012Validator, ValidationError

from providers.elevenlabs.catalog import CATALOG, SPEC
from server.billing_rates import elevenlabs_tts_model

GATEWAY_TOOLS = tuple(CATALOG)
GATEWAY_SCHEMAS = [item["tool"] for item in CATALOG.values()]
MAX_MEDIA_BYTES = 100 * 1024 * 1024


def dry_run() -> bool:
    return os.getenv("ELEVENLABS_DRY_RUN", "true").lower() == "true"


@lru_cache(maxsize=1)
def api_key() -> str:
    value = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not value and (secret := os.getenv("RENDERHAUS_SECRETS_NAME")):
        payload = boto3.client("secretsmanager").get_secret_value(SecretId=secret)
        value = str(json.loads(payload["SecretString"]).get("ELEVENLABS_API_KEY") or "").strip()
    if not value:
        raise RuntimeError("Add ELEVENLABS_API_KEY to the renderhaus/app AWS Secrets Manager JSON secret (or .env.local for local-only calls).")
    return value


def _validate(value: Any, schema: dict, field: str) -> None:
    try:
        Draft202012Validator({**schema, "components": SPEC["components"]}).validate(value)
    except ValidationError as exc:
        # Validation messages can include user input or a supplied credential; report the path/rule only.
        path = ".".join(map(str, exc.absolute_path))
        raise ValueError(f"Invalid ElevenLabs {field}{'.' + path if path else ''}: {exc.validator} constraint failed.") from None


def prepare_request(tool_name: str, arguments: dict) -> tuple[str, dict, dict, Any]:
    entry = CATALOG[tool_name]
    if tool_name.startswith("text_to_speech_"):
        arguments = {**arguments, "model_id": elevenlabs_tts_model(arguments)}
    unknown = set(arguments) - set(entry["bindings"])
    if unknown:
        raise ValueError("Unsupported ElevenLabs arguments: " + ", ".join(sorted(unknown)))
    missing = set(entry["tool"]["inputSchema"]["required"]) - set(arguments)
    if missing:
        raise ValueError("Missing ElevenLabs arguments: " + ", ".join(sorted(missing)))
    path, params, headers, body = entry["path"], {}, {}, {}
    for exposed, value in arguments.items():
        binding = entry["bindings"][exposed]
        field, location = binding["field"], binding["location"]
        if binding["json"]:
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                raise ValueError(f"{exposed} must contain valid JSON.") from None
        _validate(value, binding["schema"], exposed)
        if location == "path":
            # A single path segment cannot select a different upstream operation.
            if str(value) in {".", ".."} or not str(value):
                raise ValueError(f"Invalid path parameter {field}.")
            path = path.replace("{" + field + "}", quote(str(value), safe=""))
        elif location == "query":
            params[field] = value
        elif location == "header":
            headers[field] = str(value)
        elif location == "whole_body":
            body = value
        else:
            body[field] = value
    if entry["body_schema"]:
        _validate(body, entry["body_schema"], "body")
    if tool_name in {"music_compose", "music_stream", "music_compose_detailed", "music_compose_detailed_stream"}:
        if sum(bool(body.get(k)) for k in ("prompt", "composition_plan", "music_prompt")) != 1:
            raise ValueError("Music requires exactly one of prompt or composition_plan_json.")
        if not body.get("prompt") and any(k in body for k in ("music_length_ms", "force_instrumental", "generation_mode")):
            raise ValueError("music_length_ms and force_instrumental are only valid with prompt.")
        if body.get("prompt") and "seed" in body:
            raise ValueError("seed requires a composition plan, not prompt.")
    return path, params, headers, body


def _file_input(client: httpx.Client, source: str) -> tuple[str, bytes, str]:
    """Accept only Renderhaus storage URLs; never fetch arbitrary URLs with Lambda authority."""
    parsed = urlsplit(source)
    region = os.getenv("AWS_REGION") or os.getenv("AWS_REGION_NAME") or "us-east-1"
    buckets = {os.getenv(k, "") for k in ("PROVIDER_INPUT_BUCKET", "AWS_S3_BUCKET", "REMOTION_APP_BUCKET_NAME")}
    allowed = {host for b in buckets if b for host in (f"{b}.s3.amazonaws.com", f"{b}.s3.{region}.amazonaws.com", f"{b}.s3-{region}.amazonaws.com")}
    if (parsed.scheme != "https" or parsed.hostname not in allowed or parsed.username or
            parsed.password or parsed.fragment or parsed.port not in (None, 443)):
        raise ValueError("Upload inputs must be Renderhaus source_ref assets resolved to signed storage URLs.")
    data = bytearray()
    with client.stream("GET", source) as response:
        if response.status_code != 200:
            raise RuntimeError(f"Source media download failed (HTTP {response.status_code}); refresh the asset reference.")
        for chunk in response.iter_bytes():
            data.extend(chunk)
            if len(data) > MAX_MEDIA_BYTES:
                raise ValueError("File input exceeds the 100 MiB Gateway adapter limit.")
        mime = response.headers.get("content-type", "application/octet-stream")
    if not data:
        raise ValueError("Source media is empty.")
    return Path(parsed.path).name or "input", bytes(data), mime


def _save_media(data: bytes, mime: str, *, output_format: str = "") -> dict:
    if not data:
        raise RuntimeError("ElevenLabs returned empty media.")
    mime = mime.split(";", 1)[0].strip()
    suffix = {"audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/pcm": ".pcm", "application/x-zip": ".zip"}.get(mime) or mimetypes.guess_extension(mime) or ".bin"
    if mime.startswith("audio/") and output_format.startswith(("pcm_", "ulaw_", "alaw_")):
        suffix = "." + output_format.split("_", 1)[0]
    filename = uuid.uuid4().hex + suffix
    bucket = os.getenv("AWS_S3_BUCKET") or os.getenv("REMOTION_APP_BUCKET_NAME")
    kind = "audio" if mime.startswith("audio/") else "video" if mime.startswith("video/") else "image" if mime.startswith("image/") else "file"
    if bucket:
        s3 = boto3.client("s3")
        key = "renderhaus-elevenlabs/" + filename
        s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=mime)
        url = s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=21600)
        return {"url": url, **({f"{kind}_url": url} if kind != "file" else {}), "filename": filename, "mime_type": mime, "size_bytes": len(data)}
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        raise RuntimeError("Configure AWS_S3_BUCKET or REMOTION_APP_BUCKET_NAME for ElevenLabs media output.")
    root = Path(os.getenv("RENDERHAUS_MEDIA_DIR", ".renderhaus/media")) / "elevenlabs"
    root.mkdir(parents=True, exist_ok=True)
    destination = root / filename
    destination.write_bytes(data)
    return {"output_path": str(destination.resolve()), "filename": filename, "mime_type": mime, "size_bytes": len(data)}


def _json_result(payload: Any, output_format: str = "") -> Any:
    if isinstance(payload, list):
        return [_json_result(item, output_format) for item in payload]
    if not isinstance(payload, dict):
        return payload
    result = {}
    for key, value in payload.items():
        if key in {"audio_base64", "audio"} and isinstance(value, str) and not value.startswith("http"):
            try:
                data = base64.b64decode(value, validate=True)
            except ValueError:
                result[key] = value
            else:
                result["audio_asset"] = _save_media(data, "audio/mpeg", output_format=output_format)
        elif key.lower() in {"api_key", "xi-api-key", "secret", "token", "access_token", "refresh_token", "client_secret"}:
            result[key] = "[credential redacted; manage in ElevenLabs dashboard]"
        else:
            result[key] = _json_result(value, output_format)
    return result


def _response_payload(data: bytes, content_type: str, output_format: str) -> Any:
    if "json" in content_type:
        try:
            return _json_result(json.loads(data), output_format)
        except json.JSONDecodeError:
            # Timestamp streaming endpoints return newline-delimited JSON audio chunks.
            chunks = [json.loads(line) for line in data.splitlines() if line.strip()]
            audio = b"".join(base64.b64decode(c.pop("audio_base64", ""), validate=True) for c in chunks)
            return {"audio_asset": _save_media(audio, "audio/mpeg", output_format=output_format), "chunks": _json_result(chunks)}
    if content_type.startswith("multipart/"):
        message = BytesParser(policy=email_policy).parsebytes(f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + data)
        if not message.is_multipart():
            raise RuntimeError("ElevenLabs returned an invalid multipart response.")
        return {"parts": [_response_payload(part.get_payload(decode=True), part.get_content_type(), output_format) for part in message.iter_parts()]}
    if content_type.startswith("text/event-stream"):
        events = [json.loads(line[5:].strip()) for line in data.splitlines() if line.startswith(b"data:") and line[5:].strip() not in {b"", b"[DONE]"}]
        return {"events": _json_result(events, output_format)}
    if content_type.startswith("text/"):
        return {"text": data.decode("utf-8", errors="replace")}
    return _save_media(data, content_type or "application/octet-stream", output_format=output_format)


def dispatch_tool(tool_name: str, arguments: dict) -> dict:
    entry = CATALOG[tool_name]
    arguments = dict(arguments)
    if tool_name.startswith("text_to_dialogue_"):
        arguments.setdefault("model_id", os.getenv("ELEVENLABS_TTS_MODEL", "eleven_v4_turbo"))
    path, params, headers, body = prepare_request(tool_name, arguments)
    if dry_run():
        return {"status": "dry_run", "provider": "elevenlabs", "tool": tool_name,
                "note": "No ElevenLabs request was made and no media was generated."}
    headers["xi-api-key"] = api_key()
    output_format = str(params.get("output_format") or "")
    with httpx.Client(timeout=httpx.Timeout(180, connect=15), follow_redirects=False, trust_env=False) as client:
        kwargs: dict[str, Any] = {}
        if entry["content_type"] == "multipart/form-data":
            parts = []
            binary_fields = {v["field"] for v in entry["bindings"].values() if v["binary"]}
            for field, value in body.items():
                for item in value if isinstance(value, list) else [value]:
                    if field in binary_fields:
                        parts.append((field, _file_input(client, item)))
                    else:
                        encoded = json.dumps(item) if isinstance(item, (dict, list, bool)) else str(item)
                        parts.append((field, (None, encoded)))
            kwargs["files"] = parts
        elif entry["content_type"]:
            kwargs["json"] = body
        try:
            with client.stream(entry["method"], "https://api.elevenlabs.io" + path,
                               params=params, headers=headers, **kwargs) as response:
                if response.status_code >= 300:
                    # Never surface the request URL, API key, signed inputs or arbitrary provider echoes.
                    raise RuntimeError(f"ElevenLabs {tool_name} failed (HTTP {response.status_code}); check key permissions, quota and input constraints. Request ID: {response.headers.get('request-id', 'unavailable')}")
                with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as output:
                    for chunk in response.iter_bytes():
                        output.write(chunk)
                        if output.tell() > MAX_MEDIA_BYTES:
                            raise RuntimeError("Output exceeds the 100 MiB Gateway adapter limit; retrieve it directly from ElevenLabs.")
                    output.seek(0)
                    data = output.read()
                result = _response_payload(data, response.headers.get("content-type", ""), output_format) if data else {}
                metadata = {key.replace("-", "_"): response.headers[key] for key in ("request-id", "history-item-id", "song-id", "character-cost") if key in response.headers}
        except httpx.HTTPError as exc:
            raise RuntimeError(f"ElevenLabs transport failed ({type(exc).__name__}); check history/status before retrying paid work.") from None
    raw_status = result.get("status") if isinstance(result, dict) else None
    status = {"dubbed": "succeeded", "completed": "succeeded", "done": "succeeded",
              "dubbing": "running", "in_progress": "running"}.get(raw_status, raw_status)
    if status not in {"queued", "pending", "processing", "running", "failed", "error", "cancelled"}:
        status = "succeeded"
    return {"status": status, "provider": "elevenlabs", "tool": tool_name,
            "result": result, **metadata}
