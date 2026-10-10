"use client";

import { useEffect, useState } from "react";
import { fetchAccount } from "@/lib/api";
import { creditState, useCreditContext } from "@/lib/rh/credit-store";
import { RH_ADD_CREDIT_EVENT } from "@/lib/rh/events";
import { formatCents } from "@/lib/rh/money";
import type { StudioAccount } from "@/lib/types";

/** Sidebar credit card. Hidden when the account has no beta credit or can't be loaded. */
export function BetaCreditCard() {
  const [account, setAccount] = useState<StudioAccount | null>(null);
  const pendingCap = useCreditContext((state) => state.pendingCapCents);
  const heldCents = useCreditContext((state) => state.heldCents);
  useEffect(() => {
    let cancelled = false;
    void fetchAccount().then((value) => { if (!cancelled) setAccount(value); }).catch(() => undefined);
    return () => { cancelled = true; };
  }, []);
  const granted = account?.beta_credit?.granted_cents;
  if (!account || !granted) return null;
  const low = creditState(account.balance_cents, pendingCap, heldCents) === "low";
  return (
    <section className="rh-betacard" data-low={low} aria-label="Beta credit">
      <div className="rh-betacard-head"><span className="rh-eyebrow">Beta credit</span><span className="rh-chip rh-chip-mono">Wave 1</span></div>
      <p className="rh-betacard-amt"><b className="rh-mono rh-num">{formatCents(account.balance_cents)}</b> <span className="rh-fg3">of {formatCents(granted)}</span></p>
      <div className={`rh-bar ${low ? "rh-bar-acc" : "rh-bar-money"}`} role="img" aria-label={`${formatCents(account.balance_cents)} of ${formatCents(granted)} left`}><b style={{ width: `${Math.min(100, (account.balance_cents / granted) * 100)}%` }} /></div>
      <p className="rh-betacard-note">{low ? "Low credit. A step's hard cap can't exceed it." : "Media and agent orchestration come out of your credit."}</p>
      {low ? <button type="button" className="rh-btn rh-btn-primary rh-btn-block" onClick={() => window.dispatchEvent(new CustomEvent(RH_ADD_CREDIT_EVENT))}>Add credit</button> : null}
    </section>
  );
}
