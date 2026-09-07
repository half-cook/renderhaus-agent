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


@dataclass(frozen=True)
class SubscriptionPlan:
    id: str
    label: str
    price_usd_cents: int  # monthly


# Same "no conversion" philosophy as TOP_UP_PACKS: paying $X/mo grants
# exactly $X of generation budget for the month (see cost_for in
# billing_rates.py for what that budget actually buys), spread evenly
# across 30 days as a daily allowance with no rollover. Placeholder
# amounts -- data, not logic, trivially retuned.
SUBSCRIPTION_PLANS: tuple[SubscriptionPlan, ...] = (
    SubscriptionPlan(id="basic", label="Basic", price_usd_cents=2000),
    SubscriptionPlan(id="pro", label="Pro", price_usd_cents=5000),
    SubscriptionPlan(id="studio", label="Studio", price_usd_cents=15000),
)
PLANS_BY_ID = {plan.id: plan for plan in SUBSCRIPTION_PLANS}


def _secret_key() -> str:
    return os.getenv("STRIPE_SECRET_KEY", "")


def _webhook_secret() -> str:
    return os.getenv("STRIPE_WEBHOOK_SECRET", "")


def stripe_enabled() -> bool:
    return bool(_secret_key())


class CheckoutBody(BaseModel):
    pack_id: str


class SubscribeBody(BaseModel):
    plan_id: str


def _frontend_url() -> str:
    # Not APP_URL -- that's already claimed for the backend's own public URL
    # (see server/auth.py's _authorized_parties). This is where the browser
    # gets redirected after checkout, i.e. the studio/ frontend.
    return os.getenv("STUDIO_APP_URL", "http://127.0.0.1:5174").rstrip("/")


def _existing_stripe_customer(user_id: str) -> str | None:
    return repository.get_stripe_customer(user_id)


def _monthly_budget_cents(metadata: dict[str, object], plan: SubscriptionPlan | None) -> int:
    """price_usd_cents is snapshotted onto a subscription's own metadata at
    checkout time (see create_subscription_checkout) -- read it back
    instead of re-deriving from the current SUBSCRIPTION_PLANS, so a later
    reprice or removal of a plan_id can't retroactively change what an
    existing subscriber is charged for. Falls back to the plan's current
    price if the snapshot is missing (subscriptions created before this
    field existed) or malformed (defensive -- Stripe metadata is a plain
    string map, not schema-validated) rather than letting a bad value 500
    the whole webhook delivery."""
    try:
        return int(metadata["price_usd_cents"])
    except (KeyError, TypeError, ValueError):
        return plan.price_usd_cents if plan else 0


def _serialize_price_options(options: tuple[TopUpPack, ...] | tuple[SubscriptionPlan, ...]) -> dict[str, object]:
    return {
        "items": [
            {"id": option.id, "label": option.label, "price_usd_cents": option.price_usd_cents}
            for option in options
        ]
    }


@router.get("/packs")
async def list_packs() -> dict[str, object]:
    return _serialize_price_options(TOP_UP_PACKS)


@router.get("/plans")
async def list_plans() -> dict[str, object]:
    return _serialize_price_options(SUBSCRIPTION_PLANS)


@router.post("/checkout")
async def create_checkout(body: CheckoutBody, auth: AuthUser) -> dict[str, str]:
    if not stripe_enabled():
        raise HTTPException(status_code=503, detail="Billing is not configured yet.")
    pack = PACKS_BY_ID.get(body.pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Unknown top-up pack.")
    user_id = current_user_id(auth)
    frontend_url = _frontend_url()
    stripe.api_key = _secret_key()
    existing_customer = _existing_stripe_customer(user_id)
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            client_reference_id=user_id,
            customer=existing_customer,
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
            success_url=f"{frontend_url}/canvas?checkout=success",
            cancel_url=f"{frontend_url}/canvas?checkout=cancelled",
        )
    except stripe.StripeError as exc:
        logger.exception("Stripe checkout session creation failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"url": session.url or ""}


@router.post("/subscribe")
async def create_subscription_checkout(body: SubscribeBody, auth: AuthUser) -> dict[str, str]:
    if not stripe_enabled():
        raise HTTPException(status_code=503, detail="Billing is not configured yet.")
    plan = PLANS_BY_ID.get(body.plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Unknown subscription plan.")
    user_id = current_user_id(auth)
    # Two independent guards against ending up with more than one paid
    # subscription for the same user: an already-active/past_due
    # subscription blocks a new checkout outright (the billing portal is
    # the way to change plans), and claim_pending_subscription_checkout
    # closes the narrower window where two requests race each other before
    # either one's webhook has landed (double-click, two tabs).
    if repository.get_subscription_state(user_id) is not None:
        raise HTTPException(
            status_code=409,
            detail="You already have an active subscription. Manage it from the billing portal.",
        )
    if not repository.claim_pending_subscription_checkout(user_id):
        raise HTTPException(
            status_code=409,
            detail="A subscription checkout is already in progress. Finish or cancel it before starting another.",
        )
    frontend_url = _frontend_url()
    stripe.api_key = _secret_key()
    existing_customer = _existing_stripe_customer(user_id)
    try:
        # Inline price_data (no pre-created Stripe Product/Price needed),
        # same "define pricing as code" approach the top-up packs use.
        # Metadata lives on subscription_data, not just this session, so
        # the created Subscription object itself carries user_id/plan_id --
        # every later webhook event for it is then self-contained.
        # price_usd_cents is snapshotted here too, not re-derived from
        # SUBSCRIPTION_PLANS at webhook time -- if a plan is ever repriced
        # or removed, existing subscribers keep the allowance they actually
        # pay for instead of silently shifting to today's code value.
        session = stripe.checkout.Session.create(
            mode="subscription",
            client_reference_id=user_id,
            customer=existing_customer,
            line_items=[
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": plan.price_usd_cents,
                        "recurring": {"interval": "month"},
                        "product_data": {
                            "name": f"Renderhaus {plan.label} plan (${plan.price_usd_cents / 100:.2f}/mo)"
                        },
                    },
                }
            ],
            subscription_data={
                "metadata": {
                    "user_id": user_id,
                    "plan_id": plan.id,
                    "price_usd_cents": str(plan.price_usd_cents),
                }
            },
            success_url=f"{frontend_url}/canvas?checkout=success",
            cancel_url=f"{frontend_url}/canvas?checkout=cancelled",
        )
    except stripe.StripeError as exc:
        logger.exception("Stripe subscription checkout session creation failed")
        # The checkout attempt never reached Stripe successfully -- release
        # the claim rather than leaving the user locked out of retrying for
        # up to 24h over an error that left no actual pending checkout.
        repository.release_pending_subscription_checkout(user_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"url": session.url or ""}


@router.post("/portal")
async def create_billing_portal_session(auth: AuthUser) -> dict[str, str]:
    if not stripe_enabled():
        raise HTTPException(status_code=503, detail="Billing is not configured yet.")
    user_id = current_user_id(auth)
    customer_id = _existing_stripe_customer(user_id)
    if not customer_id:
        raise HTTPException(status_code=404, detail="No billing account on file yet.")
    stripe.api_key = _secret_key()
    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{_frontend_url()}/home",
        )
    except stripe.StripeError as exc:
        logger.exception("Stripe billing portal session creation failed")
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

    if event["type"] in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        # StripeObject isn't a plain dict (no .get()) -- convert once so the
        # rest of this reads like ordinary JSON.
        session = event["data"]["object"].to_dict()
        # Delayed payment methods (e.g. ACH) fire checkout.session.completed
        # with payment_status "unpaid" -- the funds aren't confirmed yet.
        # Wait for checkout.session.async_payment_succeeded (or a later
        # completed delivery once Stripe reflects "paid") instead of
        # crediting a payment that hasn't actually landed.
        if session.get("payment_status") != "paid":
            return {"received": True}
        metadata = session.get("metadata") or {}
        user_id = metadata.get("user_id") or session.get("client_reference_id")
        customer_id = session.get("customer")
        if user_id and customer_id:
            repository.set_stripe_customer(str(user_id), str(customer_id))
        # Subscription-mode checkouts carry no amount_cents metadata (their
        # user_id/plan_id live on subscription_data.metadata instead, read
        # by the customer.subscription.* branch below) -- only top-up
        # (mode="payment") sessions are handled here.
        if session.get("mode") != "payment":
            return {"received": True}
        amount_cents = metadata.get("amount_cents")
        if user_id and amount_cents:
            try:
                repository.adjust_balance(
                    str(user_id),
                    int(amount_cents),
                    "purchase",
                    # The Checkout Session id, not the event id: completed
                    # and async_payment_succeeded are two different events
                    # for the *same* payment, and both must collapse to one
                    # credit -- keying on the session ties them together
                    # instead of letting each event id count as distinct.
                    reference_id=str(session.get("id") or event["id"]),
                )
            except Exception as exc:
                logger.exception(
                    "Could not credit %s after %s", user_id, event["type"]
                )
                # Non-2xx so Stripe retries delivery -- returning 200 here
                # would mark the event delivered while the customer paid
                # without receiving the balance they bought.
                raise HTTPException(status_code=500, detail="Could not record credit.") from exc
        else:
            logger.warning(
                "%s missing user_id/amount_cents metadata: %s",
                event["type"],
                session.get("id"),
            )
    elif event["type"] in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
        event_subscription = event["data"]["object"].to_dict()
        subscription_id = str(event_subscription.get("id") or "")
        # Stripe doesn't guarantee webhook delivery order, and doesn't want
        # you inferring order from timestamps either -- re-fetching the
        # subscription live gives its true current state regardless of
        # which historical event triggered this delivery, so two events for
        # the *same* subscription arriving out of order both converge on
        # the same (correct) result. Falls back to the event's own payload
        # only if the live fetch itself fails (e.g. transient network
        # error), rather than dropping the event entirely.
        subscription = event_subscription
        if subscription_id:
            stripe.api_key = _secret_key()
            try:
                subscription = stripe.Subscription.retrieve(subscription_id).to_dict()
            except stripe.StripeError:
                logger.exception("Could not re-fetch subscription %s; using event payload", subscription_id)
        metadata = subscription.get("metadata") or {}
        user_id = metadata.get("user_id")
        plan_id = metadata.get("plan_id")
        customer_id = subscription.get("customer")
        if not user_id or not plan_id:
            logger.warning("%s missing user_id/plan_id metadata: %s", event["type"], subscription.get("id"))
            return {"received": True}
        if customer_id:
            repository.set_stripe_customer(str(user_id), str(customer_id))
        plan = PLANS_BY_ID.get(str(plan_id))
        monthly_budget_cents = _monthly_budget_cents(metadata, plan)
        # Stripe's own subscription statuses collapse onto the three this
        # app actually branches on: trialing/active both grant the daily
        # allowance, anything terminal or unpaid does not.
        stripe_status = subscription.get("status")
        if event["type"] == "customer.subscription.deleted" or stripe_status in ("canceled", "unpaid", "incomplete_expired"):
            status = "canceled"
        elif stripe_status == "past_due":
            status = "past_due"
        elif stripe_status in ("active", "trialing"):
            status = "active"
        else:
            status = "canceled"
        try:
            repository.sync_subscription(
                str(user_id),
                stripe_subscription_id=str(subscription.get("id") or ""),
                plan_id=str(plan_id),
                status=status,
                monthly_budget_cents=monthly_budget_cents,
                current_period_end=subscription.get("current_period_end"),
            )
        except Exception as exc:
            logger.exception("Could not sync subscription for %s after %s", user_id, event["type"])
            raise HTTPException(status_code=500, detail="Could not record subscription state.") from exc
    return {"received": True}
