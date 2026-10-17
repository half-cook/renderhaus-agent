"use client";

import { useEffect, useRef, useState } from "react";
import { CreditChip } from "@/components/rh/CreditChip";
import { creditState, useCreditContext } from "@/lib/rh/credit-store";
import { RH_ADD_CREDIT_EVENT } from "@/lib/rh/events";
import { formatCents } from "@/lib/rh/money";
import { emptyWalletMessage } from "@/lib/beta-credits";
import { fetchAccount } from "@/lib/api";
import type { StudioAccount } from "@/lib/types";
import styles from "./AccountBalance.module.css";

/** Sums today's charges from the ledger rows the API sent. Display only; no price is derived. */
function spentToday(account: StudioAccount): number {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  return account.recent_ledger.filter((entry) => entry.delta < 0 && entry.created_at * 1000 >= start.getTime()).reduce((sum, entry) => sum - entry.delta, 0);
}

export function AccountBalance({ refreshKey }: { refreshKey?: number | string }) {
  const [account, setAccount] = useState<StudioAccount | null>(null);
  const [open, setOpen] = useState(false);
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

  return (
    <div className="header-menu-wrap" ref={wrapRef} onKeyDown={(event) => {
      if (open && event.key === "Escape") {
        event.stopPropagation();
        setOpen(false);
        wrapRef.current?.querySelector("button")?.focus();
      }
    }}>
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

        </div>
      ) : null}
    </div>
  );
}
