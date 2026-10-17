"""Shared public HTTPS input validation for fal adapters."""

import ipaddress
import re
from typing import Any
from urllib.parse import urlsplit

_DOMAIN_RE = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)


def validate_https_url(value: Any, field: str, *, max_length: int = 2048) -> str:
    """Check URL syntax without fetching a caller-supplied asset."""
    if not isinstance(value, str) or not 13 <= len(value) <= max_length:
        raise ValueError(f"{field} must be an HTTPS domain URL of at most {max_length} characters.")
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
