"use client";

import { formatCents } from "@/lib/rh/money";
import type { RunReceiptModel } from "@/lib/rh/billing";
import { Ledger, LedgerRow, LedgerTotal, lineLabel } from "./Ledger";

export type SpendRow = { label: string; amountCents: number; tone?: "awaiting" };

/** "Spend in this task": the server's own lines for the current step or run, then the server's total. The UI only lists them. */
export function SpendLedger({ rows, totalLabel, totalCents, heading = "Spend in this task" }: { rows: SpendRow[]; totalLabel: string; totalCents: number; heading?: string }) {
  return (
    <section className="rh-spend" aria-label={heading}>
      <h3 className="rh-eyebrow">{heading}</h3>
      <Ledger className="rh-spend-ledger">
        {rows.map((row) => <LedgerRow key={row.label} label={row.label} amount={formatCents(row.amountCents)} tone={row.tone === "awaiting" ? "ember" : undefined} />)}
        <LedgerTotal label={totalLabel} amountCents={totalCents} />
      </Ledger>
    </section>
  );
}

export function RunReceipt({ receipt }: {
  receipt: RunReceiptModel;
  onOpen?: () => void;
  onTimeline?: () => void;
  onExport?: () => void;
}) {
  const released = Math.max(0, receipt.estimateCents - receipt.actualCents);
  return (
    <article className="rh-appr rh-receipt rh-receipt-v4" role="group" aria-label={`Run receipt, ${receipt.title}`} data-state="done" data-shot="receipt-v4">
      {receipt.thumbStrip?.length ? (
        <div className="rh-receipt-strip" aria-hidden="true">
          {receipt.thumbStrip.map((url, i) => <i key={i} style={{ backgroundImage: `url(${url})` }} />)}
        </div>
      ) : null}
      <div className="rh-appr-bd">
        <h3 className="rh-h3">{receipt.title || "Delivered"}</h3>
        {receipt.finishedLabel ? <div className="rh-fg3 rh-appr-tier">{receipt.finishedLabel}</div> : null}
      </div>
      <Ledger>
        {receipt.lines.map((line) => <LedgerRow key={`${line.kind}:${line.label}:${line.detail ?? ""}`} label={lineLabel(line, "actual")} amount={formatCents(line.priceCents)} />)}
        <LedgerTotal label="Total charged" amountCents={receipt.actualCents} />
        <div className="rh-receipt-est">
          {released > 0 ? <span>{formatCents(released)} released back · </span> : null}
          <span>estimate {formatCents(receipt.estimateCents)} · cap {formatCents(receipt.capCents)}</span>
        </div>
      </Ledger>
      <div className="rh-footnote"><span>{receipt.status === "failed" ? "Only what was charged is listed. Nothing more will be billed for this run." : "Every charge above is the final amount. Nothing else is billed for this run."}</span></div>
    </article>
  );
}

