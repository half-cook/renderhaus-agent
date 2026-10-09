"""Regional DashScope configuration without reading API credentials."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit


DEFAULT_MODEL = "wan3.0-video"
REGIONAL_HOSTS = {
    "us-east-1": "dashscope-us.aliyuncs.com",
    "ap-southeast-1": "dashscope-intl.aliyuncs.com",
}
WORKSPACE_HOST = re.compile(r"[a-z0-9][a-z0-9-]{0,127}\.(us-east-1|ap-southeast-1)\.maas\.aliyuncs\.com")


@dataclass(frozen=True)
class Settings:
    base_url: str
    region: str
    model: str
    endpoint_verification: str


def dry_run() -> bool:
    return os.getenv("MODELSTUDIO_DRY_RUN", "true").lower() != "false"


def settings(*, base_url: str | None = None, region: str | None = None,
             model: str | None = None) -> Settings:
    region = region if region is not None else os.getenv("DASHSCOPE_REGION", "us-east-1")
    if region not in REGIONAL_HOSTS:
        raise ValueError("DASHSCOPE_REGION must be us-east-1 or ap-southeast-1.")
    model = model if model is not None else os.getenv("DASHSCOPE_MODEL", DEFAULT_MODEL)
    if not isinstance(model, str) or not model.strip() or model != model.strip():
        raise ValueError("DASHSCOPE_MODEL must be a non-empty model identifier.")
    if base_url is None:
        base_url = os.getenv("DASHSCOPE_BASE_URL", "").strip()
        if not base_url:
            workspace = os.getenv("DASHSCOPE_WORKSPACE_ID", "").strip()
            if workspace:
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,127}", workspace):
                    raise ValueError("DASHSCOPE_WORKSPACE_ID must be a valid workspace hostname label.")
                base_url = f"https://{workspace}.{region}.maas.aliyuncs.com"
            else:
                base_url = f"https://{REGIONAL_HOSTS[region]}"
    if not isinstance(base_url, str):
        raise ValueError("DASHSCOPE_BASE_URL must be an official HTTPS endpoint.")
    parsed = urlsplit(base_url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or parsed.netloc != parsed.hostname or parsed.path.rstrip("/") not in {"", "/api/v1"}):
        raise ValueError("DASHSCOPE_BASE_URL must be an official HTTPS endpoint without credentials or query parameters.")
    match = WORKSPACE_HOST.fullmatch(parsed.hostname)
    host_region = match.group(1) if match else next(
        (name for name, host in REGIONAL_HOSTS.items() if host == parsed.hostname), None
    )
    if host_region is None:
        raise ValueError("DASHSCOPE_BASE_URL must use a documented Alibaba Model Studio host.")
    if host_region != region:
        raise ValueError("DASHSCOPE_BASE_URL region conflicts with DASHSCOPE_REGION.")
    verification = ("UNVERIFIED: legacy US DashScope synthesis is not supported by the regions page."
                    if parsed.hostname == REGIONAL_HOSTS["us-east-1"] else "verified documented Model Studio endpoint")
    return Settings(f"https://{parsed.hostname}", region, model, verification)


def live_blocker(configuration: Settings | None = None) -> str | None:
    if dry_run():
        return None
    try:
        configuration = configuration or settings()
    except ValueError as exc:
        return str(exc)
    if configuration.endpoint_verification.startswith("UNVERIFIED"):
        return configuration.endpoint_verification
    if configuration.model != DEFAULT_MODEL:
        return f"UNVERIFIED Model Studio model {configuration.model}; live submission is disabled."
    return None
