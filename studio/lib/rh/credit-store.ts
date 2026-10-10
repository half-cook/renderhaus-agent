import { create } from "zustand";

/** What the credit chip needs to know beyond the balance: the hard cap of the step waiting for approval,
 *  and credit currently held for a running step. Both arrive as integer cents from the approval payload. */
type CreditContext = {
  pendingCapCents: number | null;
  heldCents: number;
  setPendingCap: (cents: number | null) => void;
  setHeld: (cents: number) => void;
};

export const useCreditContext = create<CreditContext>((set) => ({
  pendingCapCents: null,
  heldCents: 0,
  setPendingCap: (pendingCapCents) => set({ pendingCapCents }),
  setHeld: (heldCents) => set({ heldCents }),
}));

export const LOW_CREDIT_FLOOR_CENTS = 200;

export type CreditState = "normal" | "low" | "held";

/** Low means: below the hard cap of the step waiting for approval, or below $2.00 when nothing is waiting. */
export function creditState(balanceCents: number, pendingCapCents: number | null, heldCents: number): CreditState {
  if (pendingCapCents != null ? balanceCents < pendingCapCents : balanceCents < LOW_CREDIT_FLOOR_CENTS) return "low";
  return heldCents > 0 ? "held" : "normal";
}
