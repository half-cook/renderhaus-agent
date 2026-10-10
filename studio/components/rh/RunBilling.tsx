"use client";

import { CircleCheck, Download, Film, Lock, Play } from "lucide-react";
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

export function RunReceipt({ receipt, onOpen, onTimeline, onExport }: {
  receipt: RunReceiptModel;
  onOpen?: () => void;
  onTimeline?: () => void;
  onExport?: () => void;
}) {
  return (
    <article className="rh-appr rh-receipt" role="group" aria-label={`Run receipt, ${receipt.title}`} data-state="done">
      <div className="rh-appr-hd" data-tone="ok">
        <span className="rh-appr-state"><CircleCheck size={15} aria-hidden="true" /><span className="rh-eyebrow">{receipt.status === "failed" ? "Stopped · run receipt" : "Done · run receipt"}</span></span>
        <span className="rh-mono rh-fg3 rh-appr-step">{receipt.paidSteps} paid steps</span>
      </div>
      <div className="rh-appr-bd">
        <h3 className="rh-h3">{receipt.title}</h3>
        {receipt.finishedLabel ? <div className="rh-fg3 rh-appr-tier">{receipt.finishedLabel}</div> : null}
      </div>
      <Ledger heading="Charged">
        {receipt.lines.map((line) => <LedgerRow key={`${line.kind}:${line.label}:${line.detail ?? ""}`} label={lineLabel(line, "actual")} amount={formatCents(line.priceCents)} />)}
        <LedgerTotal label="Total charged" amountCents={receipt.actualCents} />
        <div className="rh-receipt-est">
          <span>Estimate was {formatCents(receipt.estimateCents)} · <Lock size={11} aria-hidden="true" /> cap {formatCents(receipt.capCents)}</span>
          {receipt.underEstimate && receipt.status === "done" ? <span className="rh-chip rh-chip-ok">Under estimate</span> : null}
        </div>
      </Ledger>
      <Ledger>
        <LedgerRow label="Balance before" amount={formatCents(receipt.balanceBeforeCents)} />
        <LedgerRow label="Balance after" amount={formatCents(receipt.balanceAfterCents)} tone="money" />
      </Ledger>
      <div className="rh-appr-ft">
        {receipt.status === "done" ? <button type="button" className="rh-btn rh-btn-solid" style={{ flex: 1 }} onClick={onOpen}><Play size={13} aria-hidden="true" />Open the film</button> : null}
        <button type="button" className="rh-btn" onClick={onTimeline}><Film size={14} aria-hidden="true" />Timeline</button>
        <button type="button" className="rh-btn" onClick={onExport}><Download size={14} aria-hidden="true" />Export</button>
      </div>
      <div className="rh-footnote"><span>{receipt.status === "failed" ? "Only what was charged is listed. Nothing more will be billed for this run." : "Every charge above is the final amount. Nothing else is billed for this run."}</span></div>
    </article>
  );
}

