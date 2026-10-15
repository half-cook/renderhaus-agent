from __future__ import annotations

import hmac
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from server.auth import AuthUser
from server.beta_credits import BetaCredits, BetaError, BetaSettings
from server.beta_invites import INVITE_ONLY, BetaInvites, invite_only_enabled
from server.studio_state import repository

router = APIRouter(tags=["beta credits"])


def get_beta_credits() -> BetaCredits:
    return BetaCredits(repository, BetaSettings.from_env())


BetaService = Annotated[BetaCredits, Depends(get_beta_credits)]


def get_beta_invites() -> BetaInvites:
    return BetaInvites(repository, BetaSettings.from_env())


InviteService = Annotated[BetaInvites, Depends(get_beta_invites)]


def open_signup_only() -> None:
    """Phone/email verification, holds and the waitlist belong to the open-wave flow.
    With BETA_INVITE_ONLY=true they are switched off server-side; invite codes are the gate."""
    if invite_only_enabled():
        raise HTTPException(status_code=403, detail=INVITE_ONLY)


OpenSignup = Depends(open_signup_only)


def beta_account(auth: AuthUser) -> str:
    subject = auth.payload.get("sub") if auth is not None and auth.payload else None
    if not isinstance(subject, str) or not subject:
        raise HTTPException(status_code=401, detail="Sign in to claim beta credit.")
    return subject


BetaAccount = Annotated[str, Depends(beta_account)]


class EmailBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class PhoneBody(BaseModel):
    phone: str = Field(min_length=7, max_length=40)


class EmailConfirmBody(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=128)
    token: str = Field(min_length=1, max_length=256)


class PhoneConfirmBody(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=1, max_length=256)


class InviteBody(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    reservation: str = Field(default="", max_length=128)


def client_ip(request: Request) -> str:
    # nginx on the app host sets X-Real-IP; fall back to the socket peer.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


@router.get("/api/beta/status")
def beta_status(beta: BetaService) -> dict:
    status = beta.get_beta_status()
    status["invite_only"] = invite_only_enabled()
    if status["invite_only"]:
        status["message"] = "Invite only · $10 credit to start"
    return status


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


@router.get("/api/beta/wave")
def beta_wave(beta: BetaService) -> dict:
    return beta.get_wave()


@router.post("/api/beta/hold", dependencies=[OpenSignup])
def hold_spot(account: BetaAccount, beta: BetaService) -> dict:
    try:
        return beta.hold(account)
    except BetaError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


@router.post("/api/beta/verify/email/start", dependencies=[OpenSignup])
def start_email(body: EmailBody, account: BetaAccount, beta: BetaService) -> dict:
    try:
        return beta.start_email(account, body.email)
    except BetaError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/api/beta/verify/email/confirm", dependencies=[OpenSignup])
def confirm_email(body: EmailConfirmBody, account: BetaAccount, beta: BetaService) -> dict:
    try:
        return beta.confirm_email(account, body.challenge_id, body.token)
    except BetaError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


@router.post("/api/beta/verify/phone/start", dependencies=[OpenSignup])
def start_phone(body: PhoneBody, account: BetaAccount, beta: BetaService) -> dict:
    try:
        return beta.start_phone(account, body.phone)
    except BetaError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/api/beta/verify/phone/confirm", dependencies=[OpenSignup])
def confirm_phone(body: PhoneConfirmBody, account: BetaAccount, beta: BetaService) -> dict:
    try:
        return beta.confirm_phone(account, body.challenge_id, body.code)
    except BetaError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


@router.post("/api/beta/claim", dependencies=[OpenSignup])
def claim(account: BetaAccount, beta: BetaService) -> dict:
    try:
        return beta.claim(account)
    except BetaError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


@router.post("/api/beta/waitlist", dependencies=[OpenSignup])
def waitlist(body: EmailBody, account: BetaAccount, beta: BetaService) -> dict:
    try:
        return beta.waitlist(account, body.email)
    except BetaError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/api/admin/beta/next-wave")
def next_wave(beta: BetaService, token: Annotated[str | None, Header(alias="X-Beta-Admin-Token")] = None) -> dict:
    expected = os.environ.get("BETA_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(503, "Beta administration is disabled.")
    if not token or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(403, "Invalid beta admin credential.")
    try:
        return beta.next_wave()
    except BetaError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
