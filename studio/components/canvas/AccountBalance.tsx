"use client";

import { useEffect, useRef, useState } from "react";
import { BetaCredits } from "@/components/BetaCredits";
import { CreditChip } from "@/components/rh/CreditChip";
import { creditState, useCreditContext } from "@/lib/rh/credit-store";
import { RH_ADD_CREDIT_EVENT } from "@/lib/rh/events";
import { formatCents } from "@/lib/rh/money";
import { emptyWalletMessage } from "@/lib/beta-credits";
import {
  createCheckoutSession,
  createSubscriptionCheckout,
  fetchAccount,
  fetchSubscriptionPlans,
  fetchTopUpPacks,
  openBillingPortalRedirect,
} from "@/lib/api";
import type { StudioAccount, SubscriptionPlan, TopUpPack } from "@/lib/types";
import styles from "./AccountBalance.module.css";

/** Sums today's charges from the ledger rows the API sent. Display only; no price is derived. */
function spentToday(account: StudioAccount): number {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  return account.recent_ledger.filter((entry) => entry.delta < 0 && entry.created_at * 1000 >= start.getTime()).reduce((sum, entry) => sum - entry.delta, 0);
}

function formatUsd(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

export function AccountBalance({ refreshKey }: { refreshKey?: number | string }) {
  const [account, setAccount] = useState<StudioAccount | null>(null);
  const subscription = account?.subscription ?? null;
  const [open, setOpen] = useState(false);
  const [packs, setPacks] = useState<TopUpPack[] | null>(null);
  const [packsError, setPacksError] = useState(false);
  const [plans, setPlans] = useState<SubscriptionPlan[] | null>(null);
  const [plansError, setPlansError] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const pendingCap = useCreditContext((state) => state.pendingCapCents);
  const heldCents = useCreditContext((state) => state.heldCents);

  useEffect(() => {
    const openPopover = () => setOpen(true);
    window.addEventListener(RH_ADD_CREDIT_EVENT, openPopover);
    return () => window.removeEventListener(RH_ADD_CREDIT_EVENT, openPopover);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void fetchAccount()
      .then((account) => {
        if (cancelled) return;
        setAccount(account);
      })
      .catch(() => {
        // Clerk off, or the request failed -- no balance to show rather
        // than a broken chip.
        if (!cancelled) setAccount(null);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  // A fetch failure leaves packs/plans at null (not `[]`) so it stays
  // distinguishable from a genuinely empty catalog and this effect retries
  // on the next popover open -- setting `[]` on error would cache the
  // failure as "loaded, nothing here" with no way to retry short of a page
  // reload.
  useEffect(() => {
    if (!open || packs) {
      return;
    }
    setPacksError(false);
    void fetchTopUpPacks()
      .then(setPacks)
      .catch(() => setPacksError(true));
  }, [open, packs]);

  useEffect(() => {
    if (!open || plans || subscription) {
      return;
    }
    setPlansError(false);
    void fetchSubscriptionPlans()
      .then(setPlans)
      .catch(() => setPlansError(true));
  }, [open, plans, subscription]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const onPointerDown = (event: PointerEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  if (account === null) {
    return null;
  }

  const checkout = async (kind: "topup" | "subscription", id: string) => {
    setPending(id);
    setError(null);
    try {
      const url = kind === "topup" ? await createCheckoutSession(id) : await createSubscriptionCheckout(id);
      if (url) {
        window.location.href = url;
      } else {
        setError("Checkout is not available yet.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Checkout failed.");
    } finally {
      setPending(null);
    }
  };

  const manage = async () => {
    setPending("manage");
    setError(null);
    try {
      const opened = await openBillingPortalRedirect();
      if (!opened) {
        setError("Billing portal is not available yet.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open billing portal.");
    } finally {
      setPending(null);
    }
  };

  return (
    <div className="header-menu-wrap" ref={wrapRef}>
      <CreditChip
        balanceCents={account.balance_cents}
        state={creditState(account.balance_cents, pendingCap, heldCents)}
        heldCents={heldCents}
        expanded={open}
        onClick={() => setOpen((value) => !value)}
      />
      {open ? (
        <div className={`popover ${styles["balance-popover"]}`} role="dialog" aria-label="Credit">
          <dl className="rh-pop-rows">
            <div><dt>Balance</dt><dd className="rh-mono rh-num">{formatCents(account.balance_cents)}</dd></div>
            <div><dt>Held for running steps</dt><dd className="rh-mono rh-num">{formatCents(heldCents)}</dd></div>
            <div><dt>Spent today</dt><dd className="rh-mono rh-num">{formatCents(spentToday(account))}</dd></div>
          </dl>
          <p className="rh-pop-note">Media and agent orchestration come out of your credit.</p>
          {emptyWalletMessage(account) ? <p className="inspector-note">{emptyWalletMessage(account)}</p> : null}
          <BetaCredits account={account} compact />
          {subscription ? (
            <>
              <p className={styles["section-label"]}>Plan</p>
              <div className={styles["plan-status"]}>
                <span className={styles["plan-status-row"]}>
                  <span>{subscription.plan_id}</span>
                  {subscription.status === "past_due" ? <span className="generate-hint">Past due</span> : null}
                </span>
                <span className={styles["plan-status-remaining"]}>
                  {formatUsd(subscription.daily_allowance_remaining_cents)} left today of{" "}
                  {formatUsd(subscription.daily_allowance_cents)}
                </span>
                <button
                  type="button"
                  className={styles["manage-link"]}
                  disabled={pending !== null}
                  onClick={() => void manage()}
                >
                  {pending === "manage" ? "…" : "Manage subscription"}
                </button>
              </div>
              <hr className={styles.divider} />
            </>
          ) : (
            <>
              <p className={styles["section-label"]}>Subscribe</p>
              {plans === null ? (
                plansError ? (
                  <p className="inspector-note">Could not load plans. Reopen to retry.</p>
                ) : (
                  <p className="inspector-note">Loading plans…</p>
                )
              ) : plans.length === 0 ? (
                <p className="inspector-note">Subscriptions aren&apos;t set up yet.</p>
              ) : (
                plans.map((plan) => (
                  <button
                    key={plan.id}
                    type="button"
                    className={styles["top-up-row"]}
                    disabled={pending !== null}
                    onClick={() => void checkout("subscription", plan.id)}
                  >
                    <span className={styles["top-up-label"]}>{plan.label}</span>
                    <span className={styles["top-up-price"]}>
                      {pending === plan.id ? "…" : `${formatUsd(plan.price_usd_cents)}/mo`}
                    </span>
                  </button>
                ))
              )}
              <hr className={styles.divider} />
            </>
          )}
          <p className={styles["section-label"]}>Top up</p>
          {packs === null ? (
            packsError ? (
              <p className="inspector-note">Could not load top-ups. Reopen to retry.</p>
            ) : (
              <p className="inspector-note">Loading top-ups…</p>
            )
          ) : packs.length === 0 ? (
            <p className="inspector-note">Billing isn&apos;t set up yet.</p>
          ) : (
            packs.map((pack) => (
              <button
                key={pack.id}
                type="button"
                className={styles["top-up-row"]}
                disabled={pending !== null}
                onClick={() => void checkout("topup", pack.id)}
              >
                <span className={styles["top-up-label"]}>{pack.label}</span>
                <span className={styles["top-up-price"]}>
                  {pending === pack.id ? "…" : formatUsd(pack.price_usd_cents)}
                </span>
              </button>
            ))
          )}
          {error ? <p className="generate-hint">{error}</p> : null}
        </div>
      ) : null}
    </div>
  );
}
