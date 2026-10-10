from __future__ import annotations

import hmac
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from server.auth import AuthUser
from server.beta_credits import BetaCredits, BetaError, BetaSettings
from server.studio_state import repository

router = APIRouter(tags=["beta credits"])


def get_beta_credits() -> BetaCredits:
    return BetaCredits(repository, BetaSettings.from_env())


BetaService = Annotated[BetaCredits, Depends(get_beta_credits)]


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


@router.get("/api/beta/status")
def beta_status(beta: BetaService) -> dict:
    return beta.get_beta_status()


@router.post("/api/beta/verify/email/start")
def start_email(body: EmailBody, account: BetaAccount, beta: BetaService) -> dict:
    try:
        return beta.start_email(account, body.email)
    except BetaError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/api/beta/verify/email/confirm")
def confirm_email(body: EmailConfirmBody, account: BetaAccount, beta: BetaService) -> dict:
    try:
        return beta.confirm_email(account, body.challenge_id, body.token)
    except BetaError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


@router.post("/api/beta/verify/phone/start")
def start_phone(body: PhoneBody, account: BetaAccount, beta: BetaService) -> dict:
    try:
        return beta.start_phone(account, body.phone)
    except BetaError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/api/beta/verify/phone/confirm")
def confirm_phone(body: PhoneConfirmBody, account: BetaAccount, beta: BetaService) -> dict:
    try:
        return beta.confirm_phone(account, body.challenge_id, body.code)
    except BetaError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


@router.post("/api/beta/claim")
def claim(account: BetaAccount, beta: BetaService) -> dict:
    try:
        return beta.claim(account)
    except BetaError as exc:
        raise HTTPException(exc.status_code, str(exc)) from None


@router.post("/api/beta/waitlist")
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
