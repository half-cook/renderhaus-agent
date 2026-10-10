"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { Check, CircleAlert, CircleCheck, CirclePause, ImageOff, Info, Pencil, Play, Plus, RotateCw, ShieldCheck, Lock } from "lucide-react";
import { formatCents } from "@/lib/rh/money";
import { a11yApproveName, creditState, type ApprovalCardModel } from "@/lib/rh/billing";
import { BalanceNote, CapRow, Ledger, LedgerRow, LedgerTotal, lineLabel } from "./Ledger";

export const APPROVAL_FOOTNOTE = "Estimate shown before anything runs. We stop at the cap, you are never charged more.";

export type ApprovalCardActions = {
  onApprove?: () => void;
  onReject?: () => void;
  onEdit?: () => void;
  onCancel?: () => void;
  onRetry?: () => void;
  onSkip?: () => void;
  onRaise?: (capCents: number) => void;
  onStop?: () => void;
  onLowerCap?: (capCents: number) => void;
  onAddCredit?: () => void;
  onPreview?: () => void;
  onRegenerate?: () => void;
};

const HEADER: Record<ApprovalCardModel["status"], { label: string; tone: "ember" | "ok" | "danger"; icon: ReactNode; dot?: boolean }> = {
  pending: { label: "Approval needed", tone: "ember", icon: <ShieldCheck size={15} aria-hidden="true" /> },
  approved: { label: "Approved · queued", tone: "ok", icon: <Check size={15} aria-hidden="true" /> },
  running: { label: "Running", tone: "ember", icon: null, dot: true },
  done: { label: "Done · receipt", tone: "ok", icon: <CircleCheck size={15} aria-hidden="true" /> },
  failed: { label: "Failed", tone: "danger", icon: <CircleAlert size={15} aria-hidden="true" /> },
  paused_cap: { label: "Paused · cap reached", tone: "ember", icon: <CirclePause size={15} aria-hidden="true" /> },
};

function Thumb({ url, failed }: { url?: string; failed?: boolean }) {
  if (failed) {
    return <div className="rh-thumb-fail" aria-hidden="true"><ImageOff size={18} /></div>;
  }
  if (!url) return null;
  return (
    <div className="rh-ticks rh-appr-thumb" aria-hidden="true">
      <div className="rh-thumb" style={{ width: "100%", height: "100%", backgroundImage: `url(${url})` }} />
      <span className="rh-tk" />
    </div>
  );
}

function Notice({ tone, title, children }: { tone: "ember" | "danger"; title: string; children: ReactNode }) {
  return (
    <div className="rh-appr-bd" style={{ paddingTop: 12 }}>
      <div className="rh-notice" data-tone={tone} role={tone === "danger" ? "alert" : undefined}>
        <div className="rh-notice-title">{title}</div>
        <div className="rh-fg2" style={{ marginTop: 4 }}>{children}</div>
      </div>
    </div>
  );
}

/**
 * One approval card, every state (pending, low credit, approved, running, done receipt, failed, paused at cap).
 * It renders integer cents it is given. It never computes, reconciles or invents a price, and it never
 * shows a fee line or a vendor name: lines are already fee-inclusive, work-described strings.
 */
export function ApprovalCard({ model, approveEnabled, busy = false, actions = {}, className = "" }: {
  model: ApprovalCardModel;
  approveEnabled?: boolean;
  busy?: boolean;
  actions?: ApprovalCardActions;
  className?: string;
}) {
  const titleId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const header = HEADER[model.status];
  const credit = model.status === "pending" ? creditState(model, approveEnabled) : "ok";
  const approveName = a11yApproveName(model, formatCents);
  const stepLabel = model.stepIndex && model.stepCount ? `Step ${model.stepIndex} of ${model.stepCount}` : null;
  const live = model.status === "approved" ? `Approved. Up to ${formatCents(model.capCents)} reserved.`
    : model.status === "paused_cap" ? `Paused. Cap of ${formatCents(model.capCents)} reached.` : "";

  // Focus lands on the heading, never on Approve, so Enter cannot approve by accident.
  useEffect(() => {
    if (model.status === "pending" && document.activeElement === document.body) headingRef.current?.focus({ preventScroll: true });
  }, [model.status]);

  const emphasised = model.status === "pending" || model.status === "paused_cap";
  const showPrompt = ["pending", "approved"].includes(model.status);
  const estimateLines = model.lines;
  const actualMode = model.status === "paused_cap" ? "so-far" : model.status === "done" ? "actual" : "estimate";

  return (
    <article
      className={`rh-appr ${emphasised ? "rh-appr-pending" : ""} ${className}`}
      role="group"
      aria-labelledby={titleId}
      data-state={model.status}
      data-credit={credit}
      data-shot={model.status === "pending" ? "approval-ready" : undefined}
    >
      <div className="rh-appr-hd" data-tone={header.tone}>
        <span className="rh-appr-state">
          {header.dot ? <span className="rh-dot rh-dot-run" aria-hidden="true" /> : header.icon}
          <span className="rh-eyebrow">{header.label}</span>
        </span>
        {stepLabel ? <span className="rh-mono rh-fg3 rh-appr-step">{stepLabel}</span> : null}
      </div>

      <div className="rh-appr-bd">
        <div className="rh-appr-what">
          <div style={{ flex: 1, minWidth: 0 }}>
            <h3 className="rh-h3" id={titleId} ref={headingRef} tabIndex={-1}>{model.title}</h3>
            {model.tier ? <div className="rh-fg3 rh-appr-tier">{model.tier}</div> : null}
          </div>
          <Thumb url={model.status === "done" ? model.resultThumbUrl ?? model.thumbUrl : model.thumbUrl} failed={model.status === "failed"} />
        </div>
        {showPrompt && model.prompt ? <p className="rh-appr-prompt">{model.prompt}</p> : null}
        {showPrompt && model.specs.length ? (
          <div className="rh-appr-specs">{model.specs.map((spec) => <span key={spec} className="rh-chip rh-chip-mono">{spec}</span>)}</div>
        ) : null}
      </div>

      {model.status === "pending" || model.status === "approved" ? (
        <>
          <Ledger heading="Cost">
            {estimateLines.map((line) => (
              <LedgerRow key={`${line.kind}:${line.label}`} label={lineLabel(line, "estimate")} amount={formatCents(line.priceCents)} tone={line.kind === "orchestration" ? "muted" : undefined} />
            ))}
            <LedgerTotal label="Estimated total" amountCents={model.estimateCents} />
            {credit === "ok" ? <CapRow capCents={model.capCents} bar={model.capCents ? (model.estimateCents / model.capCents) * 100 : 0} /> : (
              <>
                <CapRow capCents={model.capCents} tone="ember" />
                <div className="rh-cap-row"><span style={{ width: 12 }} /><span>Your credit</span><b className="rh-num rh-mono">{formatCents(model.balanceCents ?? 0)}</b></div>
              </>
            )}
          </Ledger>
          {model.estimateIncomplete ? <div className="rh-note" role="status"><Info size={13} aria-hidden="true" /><span>One step couldn’t be priced yet. It is shown at {formatCents(0)}, which does not mean free.</span></div> : null}
          {credit === "ok" && model.balanceAfterEstimateCents != null && model.balanceAfterCapCents != null ? (
            <BalanceNote>Balance after this step · est. <b className="rh-num rh-mono">{formatCents(model.balanceAfterEstimateCents)}</b>, at the cap <b className="rh-num rh-mono">{formatCents(model.balanceAfterCapCents)}</b></BalanceNote>
          ) : null}
        </>
      ) : null}

      {credit !== "ok" ? (
        <Notice tone="ember" title={`Not enough credit for the ${formatCents(model.capCents)} cap`}>
          The cap is held from your credit while the step runs, so it can’t be higher than what you have.{" "}
          {credit === "lower_cap"
            ? <>Add credit, or lower the cap to {formatCents(model.lowerCapOptionCents ?? model.balanceCents ?? 0)}. The {formatCents(model.estimateCents)} estimate still fits.</>
            : <>Add credit to continue. The {formatCents(model.estimateCents)} estimate is more than your credit.</>}
        </Notice>
      ) : null}

      {model.status === "pending" && credit === "ok" ? (
        <>
          <div className="rh-appr-ft">
            <button type="button" className="rh-btn rh-btn-primary rh-btn-act" style={{ flex: 1 }} aria-label={approveName} disabled={busy || approveEnabled === false} onClick={actions.onApprove}>
              Approve · est. {formatCents(model.estimateCents)}
            </button>
            <button type="button" className="rh-btn rh-btn-act" onClick={actions.onEdit}><Pencil size={14} aria-hidden="true" />Edit</button>
            <button type="button" className="rh-btn rh-btn-quiet rh-btn-act" disabled={busy} onClick={actions.onReject}>Reject</button>
          </div>
          <div className="rh-footnote"><Info size={12} aria-hidden="true" /><span>{APPROVAL_FOOTNOTE}</span></div>
        </>
      ) : null}

      {model.status === "pending" && credit !== "ok" ? (
        <>
          <div className="rh-appr-ft">
            <button type="button" className="rh-btn rh-btn-primary rh-btn-act" style={{ flex: 1 }} onClick={actions.onAddCredit}><Plus size={14} aria-hidden="true" />Add credit</button>
            {credit === "lower_cap" ? (
              <button type="button" className="rh-btn rh-btn-act" onClick={() => actions.onLowerCap?.(model.lowerCapOptionCents ?? model.balanceCents ?? 0)}>
                <Lock size={13} aria-hidden="true" />Lower the cap to {formatCents(model.lowerCapOptionCents ?? model.balanceCents ?? 0)}
              </button>
            ) : null}
          </div>
          <div className="rh-appr-ft" style={{ paddingTop: 0 }}>
            <button type="button" className="rh-btn rh-btn-act" style={{ flex: 1 }} aria-disabled="true" aria-describedby={`${titleId}-why`} disabled>Approve · est. {formatCents(model.estimateCents)}</button>
            <button type="button" className="rh-btn rh-btn-quiet rh-btn-act" onClick={actions.onReject}>Reject</button>
          </div>
          <div className="rh-footnote" id={`${titleId}-why`}><span>{credit === "lower_cap" ? "Approve turns on as soon as the cap fits your credit." : "Approve turns on once your credit covers the estimate."}</span></div>
        </>
      ) : null}

      {model.status === "approved" ? (
        <div className="rh-appr-ft">
          <span className="rh-fg2" style={{ fontSize: 12.5 }}>Approved by you{model.approvedAtLabel ? ` · ${model.approvedAtLabel}` : ""}. Waiting for a free slot…</span>
          <button type="button" className="rh-btn rh-btn-quiet rh-btn-sm" style={{ marginLeft: "auto" }} onClick={actions.onCancel}>Cancel</button>
        </div>
      ) : null}

      {model.status === "running" ? (
        <>
          <div className="rh-appr-bd" style={{ paddingTop: 14 }}>
            <div className="rh-scan" role="progressbar" aria-label="Rendering" />
            <div className="rh-run-row"><span>Rendering your clip…</span>{model.elapsedLabel ? <span className="rh-mono rh-num">{model.elapsedLabel}</span> : null}</div>
          </div>
          <Ledger>
            <LedgerRow label="Held from your credit (hard cap)" amount={formatCents(model.heldCents ?? model.capCents)} tone="money" />
            <LedgerRow label="Spent so far" amount={formatCents(model.spentSoFarCents ?? 0)} tone="muted" />
            <div className="rh-bar rh-bar-money" style={{ marginTop: 4 }}><b style={{ width: `${model.capCents ? Math.min(100, ((model.spentSoFarCents ?? 0) / model.capCents) * 100) : 0}%` }} /></div>
          </Ledger>
          <div className="rh-appr-ft">
            <span className="rh-fg3" style={{ fontSize: 11.5 }}>Cancel stops billing if the step hasn’t started. Unused hold is released.</span>
            <button type="button" className="rh-btn rh-btn-sm" style={{ marginLeft: "auto" }} onClick={actions.onCancel}>Cancel run</button>
          </div>
        </>
      ) : null}

      {model.status === "done" ? (
        <>
          <Ledger heading="Charged">
            {estimateLines.map((line) => <LedgerRow key={`${line.kind}:${line.label}`} label={lineLabel(line, actualMode)} amount={formatCents(line.priceCents)} />)}
            <LedgerTotal label="Total charged" amountCents={model.actualCents ?? model.lines.reduce((sum, line) => sum + line.priceCents, 0)} />
            <div className="rh-fg3" style={{ fontSize: 11.5, marginTop: 8 }}>Estimate was {formatCents(model.estimateCents)} · cap {formatCents(model.capCents)}</div>
          </Ledger>
          {model.balanceAfterCents != null ? (
            <BalanceNote>Balance after <b className="rh-num rh-mono">{formatCents(model.balanceAfterCents)}</b>{model.walletTotalCents != null ? ` of ${formatCents(model.walletTotalCents)}` : ""}</BalanceNote>
          ) : null}
          <div className="rh-appr-ft">
            <button type="button" className="rh-btn rh-btn-solid" style={{ flex: 1 }} onClick={actions.onPreview}><Play size={13} aria-hidden="true" />Preview clip</button>
            <button type="button" className="rh-btn" onClick={actions.onRegenerate}><RotateCw size={14} aria-hidden="true" />Regenerate · est. {formatCents(model.estimateCents)}</button>
          </div>
        </>
      ) : null}

      {model.status === "failed" ? (
        <>
          <Notice tone="danger" title={model.failureTitle ?? "This step didn’t finish"}>{model.failureMessage ?? "No output was produced. Retrying shows a fresh estimate first."}</Notice>
          <Ledger><LedgerRow label="Charged" amount={formatCents(model.chargedCents ?? 0)} /></Ledger>
          <div className="rh-appr-ft">
            <button type="button" className="rh-btn rh-btn-primary" style={{ flex: 1 }} onClick={actions.onRetry}><RotateCw size={14} aria-hidden="true" />Retry</button>
            <button type="button" className="rh-btn rh-btn-quiet" onClick={actions.onSkip}>Skip step</button>
          </div>
        </>
      ) : null}

      {model.status === "paused_cap" ? (
        <>
          <Notice tone="ember" title={`Stopped at your ${formatCents(model.capCents)} cap`}>
            {model.message ?? "The agent needed more attempts than estimated. Nothing more has been charged, and the step is paused so you decide."}
          </Notice>
          <Ledger heading="Spent so far">
            {estimateLines.map((line) => <LedgerRow key={`${line.kind}:${line.label}`} label={lineLabel(line, "so-far")} amount={formatCents(line.priceCents)} />)}
            <LedgerTotal label="Charged · at cap" amountCents={model.chargedCents ?? model.capCents} />
            <div className="rh-bar rh-bar-acc" style={{ marginTop: 8 }}><b style={{ width: "100%" }} /></div>
          </Ledger>
          {model.balanceCents != null ? <BalanceNote>Balance now <b className="rh-num rh-mono">{formatCents(model.balanceCents)}</b>{model.walletTotalCents != null ? ` of ${formatCents(model.walletTotalCents)}` : ""}</BalanceNote> : null}
          <div className="rh-appr-ft">
            {(model.raiseOptionsCents ?? []).map((option, index) => (
              <button key={option} type="button" className={`rh-btn rh-btn-act ${index === 0 ? "rh-btn-primary" : ""}`} style={index === 0 ? { flex: 1 } : undefined} onClick={() => actions.onRaise?.(option)}>
                {index === 0 ? `Raise cap to ${formatCents(option)}` : `Raise to ${formatCents(option)}`}
              </button>
            ))}
            {(model.raiseOptionsCents ?? []).length === 0 ? <button type="button" className="rh-btn rh-btn-primary rh-btn-act" style={{ flex: 1 }} onClick={actions.onAddCredit}><Plus size={14} aria-hidden="true" />Add credit</button> : null}
            <button type="button" className="rh-btn rh-btn-quiet rh-btn-act" onClick={actions.onStop}>Stop here</button>
          </div>
          <div className="rh-footnote"><span>Raising the cap lets this step continue until the new total is reached. Stopping keeps what was made and charges nothing further.</span></div>
        </>
      ) : null}

      <span className="rh-sr-only" role="status" aria-live="polite">{live}</span>
    </article>
  );
}
