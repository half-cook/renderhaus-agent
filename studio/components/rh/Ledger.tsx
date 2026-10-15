import type { ReactNode } from "react";
import { Lock, Wallet } from "lucide-react";
import { formatCents } from "@/lib/rh/money";
import type { BillingLine } from "@/lib/rh/billing";

export function LedgerRow({ label, amount, tone }: { label: ReactNode; amount: string; tone?: "money" | "muted" | "ember" }) {
  const free = amount === "$0.00" || amount === "$0";
  return (
    <dl className="rh-ledger-row" data-tone={free ? "muted" : tone}>
      <dt>{label}</dt>
      <dd className="rh-num">{free ? "Free" : amount}</dd>
    </dl>
  );
}

/** Line label as shown in the ledger: the work it paid for, never a fee. The total carries est./actual. */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function lineLabel(line: BillingLine, _mode: "estimate" | "actual" | "so-far"): string {
  return line.detail ? `${line.label} · ${line.detail}` : line.label;
}

export function Ledger({ heading, children, className = "" }: { heading?: string; children: ReactNode; className?: string }) {
  return (
    <div className={`rh-ledger ${className}`}>
      {heading ? <div className="rh-ledger-head"><span className="rh-eyebrow">{heading}</span></div> : null}
      <div>{children}</div>
    </div>
  );
}

export function LedgerTotal({ label, amountCents, big = true }: { label: string; amountCents: number; big?: boolean }) {
  return (
    <dl className="rh-ledger-total" data-big={big}>
      <dt>{label}</dt>
      <dd className="rh-num">{formatCents(amountCents)}</dd>
    </dl>
  );
}

export function CapRow({ capCents, tone, bar }: { capCents: number; tone?: "ember"; bar?: number }) {
  return (
    <>
      <div className="rh-cap-row" data-tone={tone}>
        <Lock size={12} aria-hidden="true" /><span>Hard cap</span><b className="rh-num rh-mono">{formatCents(capCents)}</b>
      </div>
      {bar != null ? <div className="rh-bar rh-bar-money" role="presentation" style={{ marginTop: 8 }}><b style={{ width: `${Math.min(100, Math.max(0, bar))}%` }} /></div> : null}
    </>
  );
}

export function BalanceNote({ children }: { children: ReactNode }) {
  return <div className="rh-note"><Wallet size={13} aria-hidden="true" /><span>{children}</span></div>;
}
