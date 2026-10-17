from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from server.auth import AuthUser
from server.beta_credits import BetaError, BetaSettings
from server.beta_invites import BetaInvites, invite_only_enabled
from server.studio_state import repository

router = APIRouter(tags=["beta credits"])


def get_beta_invites() -> BetaInvites:
    return BetaInvites(repository, BetaSettings.from_env())


InviteService = Annotated[BetaInvites, Depends(get_beta_invites)]


def beta_account(auth: AuthUser) -> str:
    subject = auth.payload.get("sub") if auth is not None and auth.payload else None
    if not isinstance(subject, str) or not subject:
        raise HTTPException(status_code=401, detail="Sign in to claim beta credit.")
    return subject


BetaAccount = Annotated[str, Depends(beta_account)]


class InviteBody(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    reservation: str = Field(default="", max_length=128)


def client_ip(request: Request) -> str:
    # nginx on the app host sets X-Real-IP; fall back to the socket peer.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


@router.post("/api/beta/invite/check")
def check_invite(body: InviteBody, request: Request, invites: InviteService) -> dict:
    try:
        return invites.check(body.code, client_ip(request), body.reservation)
    except BetaError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


@router.post("/api/beta/invite/redeem")
def redeem_invite(body: InviteBody, account: BetaAccount, auth: AuthUser, invites: InviteService) -> dict:
    """Burns the code. Only reachable with a signed-in session, which Clerk issues
    after the email is confirmed (email code or link, no SMS)."""
    if not invite_only_enabled():
        raise HTTPException(404, "Invites are not enabled.")
    email = auth.payload.get("email") if auth is not None and auth.payload else None
    try:
        return invites.redeem(account, body.code, body.reservation, email if isinstance(email, str) else "")
    except BetaError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
