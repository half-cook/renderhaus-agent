"use client";

import { forwardRef } from "react";
import { formatCents } from "@/lib/rh/money";
import type { CreditState } from "@/lib/rh/credit-store";

/** Header credit chip: brass coin, amount, "credit". Low turns ember with a Low tag; held shows balance minus the held cap. */
export const CreditChip = forwardRef<HTMLButtonElement, {
  balanceCents: number;
  state?: CreditState;
  heldCents?: number;
  expanded?: boolean;
  onClick?: () => void;
}>(function CreditChip({ balanceCents, state = "normal", heldCents = 0, expanded, onClick }, ref) {
  const shown = state === "held" ? Math.max(0, balanceCents - heldCents) : balanceCents;
  return (
    <button
      ref={ref}
      type="button"
      className="rh-credit-chip"
      data-state={state}
      aria-expanded={expanded}
      aria-haspopup={onClick ? "dialog" : undefined}
      aria-label={`Credit ${formatCents(shown)}${state === "low" ? ", low" : state === "held" ? ", part held for a running step" : ""}`}
      onClick={onClick}
    >
      <span className="rh-coin" aria-hidden="true" />
      <span className="rh-mono rh-num rh-credit-amt">{formatCents(shown)}</span>
      <span className="rh-credit-label">credit</span>
      {state === "low" ? <span className="rh-credit-tag">Low</span> : null}
      {state === "held" ? <span className="rh-credit-tag" data-tone="muted">Held</span> : null}
    </button>
  );
});
