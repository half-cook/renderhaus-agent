"use client";

import { CircleCheck, Download, Film, Lock, Play } from "lucide-react";
import { formatCents } from "@/lib/rh/money";
import type { PlanModel, RunReceiptModel, SpendModel } from "@/lib/rh/billing";
import { Ledger, LedgerRow, LedgerTotal, lineLabel } from "./Ledger";

/** Collapsed-by-default plan: each step with its price, the orchestration estimate and the whole-plan total. */
export function PlanCard({ plan }: { plan: PlanModel }) {
  return (
    <section className="rh-plan" aria-label="Plan and estimated cost">
      <ol className="rh-plan-steps">
        {plan.steps.map((step) => (
          <li key={step.label} data-state={step.state}>
            <span className="rh-plan-mark" aria-hidden="true">{step.state === "done" ? <CircleCheck size={14} /> : <span />}</span>
            <span className="rh-plan-label">{step.label}</span>
            <span className="rh-plan-price rh-mono rh-num">
              {step.free ? "free" : step.priceCents == null ? "" : `${step.estimate ? "est. " : ""}${formatCents(step.priceCents)}`}
            </span>
          </li>
        ))}
      </ol>
      <div className="rh-plan-total">
        <span>Estimated total <span className="rh-fg3">· cap {formatCents(plan.capCents)}</span></span>
        <b className="rh-mono rh-num rh-money">{formatCents(plan.estimateCents)}</b>
      </div>
    </section>
  );
}

/** "Spend in this task": every figure comes from the server's spend payload, the UI only lists it. */
export function SpendLedger({ spend, heading = "Spend in this task" }: { spend: SpendModel; heading?: string }) {
  return (
    <section className="rh-spend" aria-label={heading}>
      <h3 className="rh-eyebrow">{heading}</h3>
      <Ledger className="rh-spend-ledger">
        {spend.lines.map((line) => (
          <LedgerRow key={line.label} label={line.label} amount={`${line.tone === "charged" ? "" : "est. "}${formatCents(line.amountCents)}`} tone={line.tone === "awaiting" ? "ember" : undefined} />
        ))}
        <LedgerTotal label={spend.totalLabel} amountCents={spend.totalCents} />
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
        <span className="rh-appr-state"><CircleCheck size={15} aria-hidden="true" /><span className="rh-eyebrow">Done · run receipt</span></span>
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
          {receipt.underEstimate ? <span className="rh-chip rh-chip-ok">Under estimate</span> : null}
        </div>
      </Ledger>
      <Ledger>
        <LedgerRow label="Balance before" amount={formatCents(receipt.balanceBeforeCents)} />
        <LedgerRow label="Balance after" amount={formatCents(receipt.balanceAfterCents)} tone="money" />
      </Ledger>
      <div className="rh-appr-ft">
        <button type="button" className="rh-btn rh-btn-solid" style={{ flex: 1 }} onClick={onOpen}><Play size={13} aria-hidden="true" />Open the film</button>
        <button type="button" className="rh-btn" onClick={onTimeline}><Film size={14} aria-hidden="true" />Timeline</button>
        <button type="button" className="rh-btn" onClick={onExport}><Download size={14} aria-hidden="true" />Export</button>
      </div>
      <div className="rh-footnote"><span>Every charge above is the final amount. Nothing else is billed for this run.</span></div>
    </article>
  );
}

