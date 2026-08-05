from __future__ import annotations

import os
from typing import Annotated

from clerk_backend_api import AuthenticateRequestOptions, authenticate_request
from clerk_backend_api.security.types import RequestState
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

http_bearer = HTTPBearer(auto_error=False)


def publishable_key() -> str:
    return (
        os.getenv("CLERK_PUBLISHABLE_KEY")
        or os.getenv("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY")
        or ""
    )


def secret_key() -> str:
    return os.getenv("CLERK_SECRET_KEY") or ""


def clerk_enabled() -> bool:
    return bool(secret_key() and publishable_key())


def _authorized_parties() -> list[str]:
    raw = os.getenv("CLERK_AUTHORIZED_PARTIES", "").strip()
    if raw:
        return [party.strip() for party in raw.split(",") if party.strip()]
    parties = [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]
    app_url = os.getenv("APP_URL", "").rstrip("/")
    if app_url and app_url not in parties:
        parties.append(app_url)
    return parties


def _jwt_key() -> str | None:
    raw = os.getenv("CLERK_JWT_KEY")
    if not raw:
        return None
    return raw.replace("\\n", "\n")


def require_auth(
    request: Request,
    _creds: Annotated[HTTPAuthorizationCredentials | None, Depends(http_bearer)] = None,
) -> RequestState | None:
    """Require a signed-in Clerk session when Clerk is configured."""
    if not clerk_enabled():
        return None

    state = authenticate_request(
        request,
        AuthenticateRequestOptions(
            secret_key=secret_key(),
            jwt_key=_jwt_key(),
            authorized_parties=_authorized_parties(),
            accepts_token=["session_token"],
        ),
    )
    if not state.is_signed_in:
        detail = state.reason.name if state.reason else "unauthorized"
        raise HTTPException(
            status_code=401,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return state


def optional_user(request: Request) -> RequestState | None:
    """Return auth state when present; never raise for missing credentials."""
    if not clerk_enabled():
        return None
    state = authenticate_request(
        request,
        AuthenticateRequestOptions(
            secret_key=secret_key(),
            jwt_key=_jwt_key(),
            authorized_parties=_authorized_parties(),
            accepts_token=["session_token"],
        ),
    )
    return state if state.is_signed_in else None


AuthUser = Annotated[RequestState | None, Depends(require_auth)]


def current_user_id(auth: RequestState | None) -> str:
    """Clerk subject when signed in; stable local owner when Clerk is off."""
    if auth is not None and auth.payload:
        subject = auth.payload.get("sub")
        if isinstance(subject, str) and subject:
            return subject
    if clerk_enabled():
        raise HTTPException(
            status_code=401,
            detail="unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return "local"
