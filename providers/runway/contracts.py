"""Runway request rules shared by direct tools and Gateway dispatch.

Sources checked 2026-10-08:
https://docs.dev.runwayml.com/api/
https://docs.dev.runwayml.com/assets/inputs/
https://docs.dev.runwayml.com/assets/uploads/
https://docs.dev.runwayml.com/guides/pricing/

The endpoint OpenAPI schemas define the supported payloads. They limit Aleph video
data URIs to 5 MiB, although the general inputs guide says 16 MiB. Use the smaller
endpoint limit, measured over the entire encoded URI. URI validation cannot verify
a remote video's codec, frame rate, resolution, or actual duration.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit


CATALOG_SOURCE = "https://docs.dev.runwayml.com/api/"
CATALOG_VERIFIED_ON = "2026-10-08"
MAX_DATA_URI_BYTES = 5 * 1024 * 1024
T2V_RATIOS = ("1280:720", "720:1280")
I2V_RATIOS = ("1280:720", "720:1280", "1104:832", "960:960", "832:1104", "1584:672")
IMAGE_720_RATIOS = ("1280:720", "720:1280", "720:720", "960:720", "720:960", "1680:720")
IMAGE_1080_RATIOS = ("1920:1080", "1080:1920", "1080:1080", "1440:1080", "1080:1440")
# Deliberately omit legacy OpenAPI dimensions whose pricing tier is not documented.
IMAGE_RATIOS = IMAGE_720_RATIOS + IMAGE_1080_RATIOS

MODEL_CONSTRAINTS: dict[str, dict[str, Any]] = {
    "gen4.5": {
        "media_kind": "video",
        "tools": ("text_to_video", "image_to_video"),
        "duration_seconds": {"minimum": 2, "maximum": 10, "integer": True},
        "ratios_by_tool": {"text_to_video": T2V_RATIOS, "image_to_video": I2V_RATIOS},
    },
    "aleph2": {
        "media_kind": "video",
        "tools": ("video_to_video",),
        "video_duration_seconds": {"minimum": 2, "maximum": 30},
        "input_fps": 30,
        "max_input_resolution": "1080p",
        "max_reference_images": 1,
    },
    "gen4_image": {
        "media_kind": "image",
        "tools": ("text_to_image", "image_to_image"),
        "ratios": IMAGE_RATIOS,
        "min_reference_images": 0,
        "max_reference_images": 3,
    },
    "gen4_image_turbo": {
        "media_kind": "image",
        "tools": ("image_to_image",),
        "ratios": IMAGE_RATIOS,
        "min_reference_images": 1,
        "max_reference_images": 3,
    },
}

_DEFAULT_MODELS = {
    "text_to_video": "gen4.5",
    "image_to_video": "gen4.5",
    "video_to_video": "aleph2",
    "text_to_image": "gen4_image",
    "image_to_image": "gen4_image",
}
_COMMON_FIELDS = {"prompt", "model", "seed"}
_TOOL_FIELDS = {
    "text_to_video": _COMMON_FIELDS | {"duration_seconds", "ratio"},
    "image_to_video": _COMMON_FIELDS | {"image_path_or_url", "duration_seconds", "ratio"},
    "video_to_video": _COMMON_FIELDS
    | {
        "video_path_or_url",
        "video_duration_seconds",
        "reference_image_path_or_url",
        "reference_seconds",
    },
    "text_to_image": _COMMON_FIELDS | {"ratio"},
    "image_to_image": _COMMON_FIELDS | {"image_path_or_url", "ratio", "reference_images"},
    "get_runway_task": {"job_id", "download"},
    "list_runway_models": set(),
}
_REQUIRED_FIELDS = {
    "text_to_video": {"prompt"},
    "image_to_video": {"prompt", "image_path_or_url"},
    "video_to_video": {"prompt", "video_path_or_url", "video_duration_seconds"},
    "text_to_image": {"prompt"},
    "image_to_image": {"prompt", "image_path_or_url"},
    "get_runway_task": {"job_id"},
    "list_runway_models": set(),
}
_DOMAIN_RE = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)
_LIVE_JOB_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-4[0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\Z"
)
_DRY_JOB_RE = re.compile(r"runway_dry_[0-9a-f]{32}\Z")
_TAG_RE = re.compile(r"[a-z][a-z0-9_]{2,15}\Z")
_IMAGE_MIMES = {"image/jpg", "image/jpeg", "image/png", "image/webp"}
_VIDEO_MIMES = {
    "video/mp4",
    "video/quicktime",
    "video/x-matroska",
    "video/webm",
    "video/3gpp",
    "video/ogg",
    "video/x-msvideo",
    "video/x-flv",
    "video/mpeg",
}


def validate_job_id(job_id: Any) -> str:
    """Require a Runway UUID or one of this provider's dry task IDs."""
    if not isinstance(job_id, str) or not (
        _LIVE_JOB_RE.fullmatch(job_id) or _DRY_JOB_RE.fullmatch(job_id)
    ):
        raise ValueError("job_id must be a Runway task UUID or a Runway dry-run task ID.")
    return job_id


def validate_https_url(value: Any, field: str) -> str:
    """Check URL syntax without fetching a caller-supplied asset."""
    if not isinstance(value, str) or not 13 <= len(value) <= 2048:
        raise ValueError(f"{field} must be an HTTPS domain URL of at most 2048 characters.")
    if any(character.isspace() or ord(character) < 32 for character in value) or "\\" in value:
        raise ValueError(f"{field} must not contain whitespace or backslashes.")
    try:
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").encode("idna").decode("ascii").lower()
        port = parsed.port
        has_credentials = parsed.username is not None or parsed.password is not None
    except (ValueError, UnicodeError):
        raise ValueError(f"{field} must be a valid HTTPS domain URL.") from None
    if parsed.scheme != "https" or has_credentials or "#" in value or port not in {None, 443}:
        raise ValueError(
            f"{field} must use HTTPS without credentials, fragments, or a custom port."
        )
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError(f"{field} must use a domain name, not an IP address.")
    if (
        len(hostname) > 253
        or not _DOMAIN_RE.fullmatch(hostname)
        or hostname.endswith((".localhost", ".local", ".internal", ".invalid", ".test"))
    ):
        raise ValueError(f"{field} must use a public domain name.")
    return value


def validate_media_uri(value: Any, field: str, kind: str) -> str:
    """Accept documented URI forms; never read arbitrary files on the host."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an HTTPS URL, Runway upload URI, or base64 data URI.")
    if value.startswith("https://"):
        return validate_https_url(value, field)
    if value.startswith("runway://"):
        if not 13 <= len(value) <= 5000 or not re.fullmatch(
            r"runway://[A-Za-z0-9._~:/+\-]+", value
        ):
            raise ValueError(
                f"{field} must be a valid Runway upload URI without credentials or fragments."
            )
        return value
    if value.startswith("data:"):
        if len(value) > MAX_DATA_URI_BYTES:
            raise ValueError(f"{field} encoded data URI must be at most 5 MiB.")
        header, separator, encoded = value.partition(",")
        allowed_mimes = _IMAGE_MIMES if kind == "image" else _VIDEO_MIMES
        if separator != "," or header not in {f"data:{mime};base64" for mime in allowed_mimes}:
            raise ValueError(f"{field} must be a base64 data URI for a supported {kind} format.")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError(f"{field} must contain valid base64 media.") from None
        if not decoded:
            raise ValueError(f"{field} must contain nonempty base64 media.")
        return value
    raise ValueError(
        f"{field} must be an HTTPS URL, Runway upload URI, or base64 data URI; local paths are not supported."
    )


def _number(value: Any, field: str, minimum: float, maximum: float, integer: bool = False) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or (integer and not isinstance(value, int))
    ):
        noun = "an integer" if integer else "a number"
        raise ValueError(f"{field} must be {noun} between {minimum:g} and {maximum:g}.")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be between {minimum:g} and {maximum:g}.")


def _reference_images(value: Any) -> None:
    if not isinstance(value, list) or len(value) > 2:
        raise ValueError(
            "reference_images must be a list of at most two additional image references."
        )
    tags: set[str] = set()
    for index, reference in enumerate(value):
        field = f"reference_images[{index}]"
        if (
            not isinstance(reference, dict)
            or set(reference) - {"uri", "tag"}
            or "uri" not in reference
        ):
            raise ValueError(f"{field} must contain uri and an optional tag only.")
        validate_media_uri(reference["uri"], f"{field}.uri", "image")
        if "tag" in reference:
            tag = reference["tag"]
            if not isinstance(tag, str) or not _TAG_RE.fullmatch(tag):
                raise ValueError(
                    f"{field}.tag must use 3-16 lowercase letters, digits, or underscores and start with a letter."
                )
            if tag in tags:
                raise ValueError("reference_images tags must be unique.")
            tags.add(tag)


def validate_runway_arguments(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate before either a direct tool or Gateway call can perform provider I/O."""
    if tool_name not in _TOOL_FIELDS:
        raise ValueError(f"Unknown Runway tool: {tool_name}")
    if not isinstance(arguments, dict):
        raise ValueError("Runway arguments must be an object.")
    unknown = set(arguments) - _TOOL_FIELDS[tool_name]
    if unknown:
        raise ValueError(
            "Runway arguments contain unsupported fields: "
            + ", ".join(sorted(str(key) for key in unknown))
            + "."
        )
    null_fields = {key for key, value in arguments.items() if value is None} - {
        "seed",
        "reference_image_path_or_url",
        "reference_images",
    }
    if null_fields:
        raise ValueError("Runway arguments cannot be null: " + ", ".join(sorted(null_fields)) + ".")
    cleaned = {key: value for key, value in arguments.items() if value is not None}
    missing = _REQUIRED_FIELDS[tool_name] - set(cleaned)
    if missing:
        raise ValueError(
            "Runway arguments are missing required fields: " + ", ".join(sorted(missing)) + "."
        )
    if tool_name == "list_runway_models":
        return cleaned
    if tool_name == "get_runway_task":
        validate_job_id(cleaned["job_id"])
        if not isinstance(cleaned.get("download", False), bool):
            raise ValueError("download must be a boolean.")
        return cleaned

    prompt = cleaned["prompt"]
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a nonempty string.")
    try:
        prompt_units = len(prompt.encode("utf-16-le")) // 2
    except UnicodeError:
        raise ValueError("prompt must contain valid Unicode text.") from None
    if prompt_units > 1000:
        raise ValueError("prompt must be at most 1000 UTF-16 code units.")
    model = cleaned.get("model", _DEFAULT_MODELS[tool_name])
    if (
        not isinstance(model, str)
        or model not in MODEL_CONSTRAINTS
        or tool_name not in MODEL_CONSTRAINTS[model]["tools"]
    ):
        allowed = [name for name, rule in MODEL_CONSTRAINTS.items() if tool_name in rule["tools"]]
        raise ValueError(f"model for {tool_name} must be one of {', '.join(allowed)}.")
    if "seed" in cleaned:
        _number(cleaned["seed"], "seed", 0, 4294967295, integer=True)
    if tool_name in {"text_to_video", "image_to_video"}:
        _number(cleaned.get("duration_seconds", 5), "duration_seconds", 2, 10, integer=True)
        ratios = MODEL_CONSTRAINTS[model]["ratios_by_tool"][tool_name]
    elif tool_name == "video_to_video":
        duration = cleaned["video_duration_seconds"]
        _number(duration, "video_duration_seconds", 2, 30)
        validate_media_uri(cleaned["video_path_or_url"], "video_path_or_url", "video")
        seconds = cleaned.get("reference_seconds", 0)
        _number(seconds, "reference_seconds", 0, duration)
        reference = cleaned.get("reference_image_path_or_url")
        if reference is not None:
            validate_media_uri(reference, "reference_image_path_or_url", "image")
        elif seconds != 0:
            raise ValueError("reference_seconds requires reference_image_path_or_url.")
        return cleaned
    else:
        ratios = MODEL_CONSTRAINTS[model]["ratios"]
    ratio = cleaned.get("ratio", "1280:720")
    if not isinstance(ratio, str) or ratio not in ratios:
        raise ValueError(f"ratio for {tool_name} must be one of {', '.join(ratios)}.")
    if tool_name in {"image_to_video", "image_to_image"}:
        validate_media_uri(cleaned["image_path_or_url"], "image_path_or_url", "image")
    if tool_name == "image_to_image":
        _reference_images(cleaned.get("reference_images", []))
    return cleaned
