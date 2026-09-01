"""Stripe billing: pay-as-you-go top-ups + webhook.

No subscriptions, no credit-to-dollar conversion -- a $10 pack grants
exactly $10.00 (1000 cents) of balance. Balance is granted exclusively
from the webhook (checkout.session.completed) -- never from the
client-side redirect back from Stripe -- so a user can't fake a
successful payment by just hitting the success URL.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import stripe
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from server.auth import AuthUser, current_user_id
from server.studio_state import repository

router = APIRouter(prefix="/api/studio/billing", tags=["billing"])
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TopUpPack:
    id: str
    label: str
    price_usd_cents: int


# Placeholder amounts -- data, not logic, trivially retuned. Each pack
# grants exactly its price in balance (1000 cents in -> 1000 cents of
# balance) -- no credit-unit conversion to keep transparent.
TOP_UP_PACKS: tuple[TopUpPack, ...] = (
    TopUpPack(id="starter", label="Starter", price_usd_cents=1000),
    TopUpPack(id="plus", label="Plus", price_usd_cents=4000),
    TopUpPack(id="pro", label="Pro", price_usd_cents=10000),
)
PACKS_BY_ID = {pack.id: pack for pack in TOP_UP_PACKS}


def _secret_key() -> str:
    return os.getenv("STRIPE_SECRET_KEY", "")


def _webhook_secret() -> str:
    return os.getenv("STRIPE_WEBHOOK_SECRET", "")


def stripe_enabled() -> bool:
    return bool(_secret_key())


class CheckoutBody(BaseModel):
    pack_id: str


@router.get("/packs")
async def list_packs() -> dict[str, object]:
    return {
        "items": [
            {
                "id": pack.id,
                "label": pack.label,
                "price_usd_cents": pack.price_usd_cents,
            }
            for pack in TOP_UP_PACKS
        ]
    }


@router.post("/checkout")
async def create_checkout(body: CheckoutBody, auth: AuthUser) -> dict[str, str]:
    if not stripe_enabled():
        raise HTTPException(status_code=503, detail="Billing is not configured yet.")
    pack = PACKS_BY_ID.get(body.pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Unknown top-up pack.")
    user_id = current_user_id(auth)
    # Not APP_URL -- that's already claimed for the backend's own public URL
    # (see server/auth.py's _authorized_parties). This is where the
    # browser gets redirected after checkout, i.e. the studio/ frontend.
    frontend_url = os.getenv("STUDIO_APP_URL", "http://127.0.0.1:5174").rstrip("/")
    stripe.api_key = _secret_key()
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            client_reference_id=user_id,
            line_items=[
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": pack.price_usd_cents,
                        "product_data": {
                            "name": f"Renderhaus balance — {pack.label} (${pack.price_usd_cents / 100:.2f})"
                        },
                    },
                }
            ],
            metadata={"pack_id": pack.id, "user_id": user_id, "amount_cents": str(pack.price_usd_cents)},
            success_url=f"{frontend_url}/app?checkout=success",
            cancel_url=f"{frontend_url}/app?checkout=cancelled",
        )
    except stripe.StripeError as exc:
        logger.exception("Stripe checkout session creation failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"url": session.url or ""}


@router.post("/webhook")
async def stripe_webhook(request: Request) -> dict[str, bool]:
    if not stripe_enabled():
        raise HTTPException(status_code=503, detail="Billing is not configured yet.")
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, _webhook_secret())
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook signature.") from exc

    if event["type"] == "checkout.session.completed":
        # StripeObject isn't a plain dict (no .get()) -- convert once so the
        # rest of this reads like ordinary JSON.
        session = event["data"]["object"].to_dict()
        metadata = session.get("metadata") or {}
        user_id = metadata.get("user_id") or session.get("client_reference_id")
        amount_cents = metadata.get("amount_cents")
        if user_id and amount_cents:
            try:
                repository.adjust_balance(
                    str(user_id),
                    int(amount_cents),
                    "purchase",
                    reference_id=str(event["id"]),
                )
            except Exception:
                logger.exception(
                    "Could not credit %s after checkout.session.completed", user_id
                )
        else:
            logger.warning(
                "checkout.session.completed missing user_id/amount_cents metadata: %s",
                session.get("id"),
            )
    return {"received": True}
