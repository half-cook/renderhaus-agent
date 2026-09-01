"use client";

import { useEffect, useRef, useState } from "react";
import { createCheckoutSession, fetchAccount, fetchTopUpPacks } from "@/lib/api";
import type { TopUpPack } from "@/lib/types";
import styles from "./AccountBalance.module.css";

function formatUsd(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

export function AccountBalance({ refreshKey }: { refreshKey?: number | string }) {
  const [balanceCents, setBalanceCents] = useState<number | null>(null);
  const [open, setOpen] = useState(false);
  const [packs, setPacks] = useState<TopUpPack[] | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    void fetchAccount()
      .then((account) => {
        if (!cancelled) setBalanceCents(account.balance_cents);
      })
      .catch(() => {
        // Clerk off, or the request failed -- no balance to show rather
        // than a broken chip.
        if (!cancelled) setBalanceCents(null);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  useEffect(() => {
    if (!open || packs) {
      return;
    }
    void fetchTopUpPacks()
      .then(setPacks)
      .catch(() => setPacks([]));
  }, [open, packs]);

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

  if (balanceCents === null) {
    return null;
  }

  const buy = async (packId: string) => {
    setPending(packId);
    setError(null);
    try {
      const url = await createCheckoutSession(packId);
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

  return (
    <div className="header-menu-wrap" ref={wrapRef}>
      <button
        type="button"
        className={styles["account-balance"]}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {formatUsd(balanceCents)}
      </button>
      {open ? (
        <div className={`popover ${styles["balance-popover"]}`} role="menu" aria-label="Add funds">
          {packs === null ? (
            <p className="inspector-note">Loading top-ups…</p>
          ) : packs.length === 0 ? (
            <p className="inspector-note">Billing isn&apos;t set up yet.</p>
          ) : (
            packs.map((pack) => (
              <button
                key={pack.id}
                type="button"
                className={styles["top-up-row"]}
                disabled={pending !== null}
                onClick={() => void buy(pack.id)}
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
