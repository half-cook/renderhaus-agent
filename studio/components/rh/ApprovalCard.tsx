"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Check, CircleAlert, CircleCheck, CirclePause, ImageOff, Info, Pencil, Play, Plus, RotateCw, ShieldCheck, Lock } from "lucide-react";
import { OUT_OF_CREDIT_FULL, topupsEnabled } from "@/lib/launch";
import { formatCents } from "@/lib/rh/money";
import { a11yApproveName, creditState, type ApprovalCardModel } from "@/lib/rh/billing";
import { BalanceNote, CapRow, Ledger, LedgerRow, LedgerTotal, lineLabel } from "./Ledger";

export const UP_TO_FOOTNOTE = "We stop at this amount, you are never charged more.";
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
  onUseCheaper?: () => void;
  /** Over-credit with nothing that fits: close the card without spending. */
  onNotNow?: () => void;
  onTrim?: () => void;
  onKeep?: () => void;
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
export function ApprovalCard({ model, approveEnabled, busy = false, actions = {}, className = "", focusOnMount = true }: {
  model: ApprovalCardModel;
  approveEnabled?: boolean;
  busy?: boolean;
  actions?: ApprovalCardActions;
  className?: string;
  focusOnMount?: boolean;
}) {
  const titleId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const header = HEADER[model.status];
  const credit = model.status === "pending" && !model.pricing ? creditState(model, approveEnabled) : "ok";
  const locked = busy || approveEnabled === false || model.pricing === true || model.unpriceable === true;
  const topups = topupsEnabled();
  const approveName = a11yApproveName(model, formatCents);
  const live = model.status === "approved" ? `Approved. Up to ${formatCents(model.capCents)} reserved.`
    : model.status === "paused_cap" ? `Paused. Cap of ${formatCents(model.capCents)} reached.` : "";

  // Focus lands on the heading, never on Approve, so Enter cannot approve by accident.
  useEffect(() => {
    if (focusOnMount && model.status === "pending") headingRef.current?.focus({ preventScroll: true });
  }, [model.id, model.status, focusOnMount]);

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
          <span className="rh-appr-label">{header.label}</span>
        </span>
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
            {model.pricing ? (
              <dl className="rh-ledger-total rh-pricing" data-big="true" data-shot="approval-pricing">
                <dt>Pricing this step…</dt>
                <dd><span className="rh-shimmer" aria-hidden="true" /></dd>
              </dl>
            ) : model.upTo ? (
              <div data-shot="approval-up-to">
                <dl className="rh-ledger-total rh-upto" data-big="true">
                  <dt>Up to</dt>
                  <dd className="rh-num">{formatCents(model.capCents)}</dd>
                </dl>
                <p className="rh-upto-stop">Up to {formatCents(model.capCents)} · we’ll stop there</p>
              </div>
            ) : model.unpriceable ? (
              <dl className="rh-ledger-total" data-big="true"><dt>Can’t be priced</dt><dd className="rh-fg3">Approve is off</dd></dl>
            ) : <LedgerTotal label="Estimated total" amountCents={model.estimateCents} />}
            {model.pricing || model.unpriceable ? null : credit === "ok" && model.upTo ? null : credit === "ok" ? <CapRow capCents={model.capCents} bar={model.capCents ? (model.estimateCents / model.capCents) * 100 : 0} /> : (
              <>
                <CapRow capCents={model.capCents} tone="ember" />
                <div className="rh-cap-row"><span style={{ width: 12 }} /><span>Your credit</span><b className="rh-num rh-mono">{formatCents(model.balanceCents ?? 0)}</b></div>
              </>
            )}
          </Ledger>
          {model.unpriceable ? <div className="rh-note" role="status"><Info size={13} aria-hidden="true" /><span>This step can’t be priced, so it can’t be approved. Nothing was charged.</span></div> : null}
          {model.upTo && credit === "ok" ? <div className="rh-note" role="status"><Info size={13} aria-hidden="true" /><span>This step has no exact price. Its full amount is held from your credit, and the run stops if it reaches it.</span></div> : null}
          {credit === "ok" && !model.pricing && !model.upTo && model.balanceAfterEstimateCents != null && model.balanceAfterCapCents != null ? (
            <BalanceNote>Balance after this step · est. <b className="rh-num rh-mono">{formatCents(model.balanceAfterEstimateCents)}</b>, at the cap <b className="rh-num rh-mono">{formatCents(model.balanceAfterCapCents)}</b></BalanceNote>
          ) : null}
        </>
      ) : null}

      {credit !== "ok" && !topups ? <OverCredit model={model} credit={credit} titleId={titleId} approveName={approveName} actions={actions} /> : null}

      {credit !== "ok" && topups ? (
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
            <button type="button" className="rh-btn rh-btn-primary rh-btn-act" style={{ flex: 1 }} aria-label={model.pricing ? "Approve, locked while this step is priced" : approveName} disabled={locked} onClick={actions.onApprove}>
              Approve and run
            </button>
            <button type="button" className="rh-btn rh-btn-act" onClick={actions.onEdit}><Pencil size={14} aria-hidden="true" />Edit</button>
            {model.pricing || model.upTo || model.unpriceable ? (
              // Same server decline as the over-credit card: clears the approval, releases any hold, posts the Paused line.
              <button type="button" className="rh-btn rh-btn-quiet rh-btn-act" data-shot="not-now" disabled={busy} onClick={actions.onNotNow}>Not now</button>
            ) : null}
          </div>
          <div className="rh-footnote"><Info size={12} aria-hidden="true" /><span>{model.upTo ? UP_TO_FOOTNOTE : APPROVAL_FOOTNOTE}</span></div>
        </>
      ) : null}

      {model.status === "pending" && credit !== "ok" && topups ? (
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
            <button type="button" className="rh-btn rh-btn-act" style={{ flex: 1 }} aria-label={approveName} aria-disabled="true" aria-describedby={`${titleId}-why`} disabled><Lock size={13} aria-hidden="true" />Approve</button>
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
            {model.actualCents != null ? <LedgerTotal label="Total charged" amountCents={model.actualCents} /> : <p className="rh-fg3 rh-small">Final charge unavailable.</p>}
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

      {model.status === "paused_cap" && !topups && (model.raiseOptionsCents ?? []).length === 0 ? (
        <>
          <Notice tone="ember" title={`Stopped at your ${formatCents(model.capCents)} cap`}>{OUT_OF_CREDIT_FULL}</Notice>
          <Ledger heading="Spent so far">
            {estimateLines.map((line) => <LedgerRow key={`${line.kind}:${line.label}`} label={lineLabel(line, "so-far")} amount={formatCents(line.priceCents)} />)}
            <LedgerTotal label="Charged · at cap" amountCents={model.chargedCents ?? model.capCents} />
          </Ledger>
          {model.balanceCents != null ? <BalanceNote>Balance now <b className="rh-num rh-mono">{formatCents(model.balanceCents)}</b>{model.walletTotalCents != null ? ` of ${formatCents(model.walletTotalCents)}` : ""}</BalanceNote> : null}
          <div className="rh-appr-ft" data-shot="out-of-credit-actions">
            <button type="button" className="rh-btn rh-btn-solid rh-btn-act" style={{ flex: 1 }} onClick={actions.onTrim}>Trim</button>
            <button type="button" className="rh-btn rh-btn-act" onClick={actions.onKeep ?? actions.onStop}>Keep as is</button>
          </div>
          <div className="rh-footnote"><span>Both are free. Trim opens the timeline on the partial clip. Free edits (trim, reorder, export) still work.</span></div>
        </>
      ) : null}

      {model.status === "paused_cap" && (topups || (model.raiseOptionsCents ?? []).length > 0) ? (
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
            {(model.raiseOptionsCents ?? []).length === 0 && topups ? <button type="button" className="rh-btn rh-btn-primary rh-btn-act" style={{ flex: 1 }} onClick={actions.onAddCredit}><Plus size={14} aria-hidden="true" />Add credit</button> : null}
            <button type="button" className="rh-btn rh-btn-quiet rh-btn-act" onClick={actions.onStop}>Stop here</button>
          </div>
          <div className="rh-footnote"><span>Raising the cap lets this step continue until the new total is reached. Stopping keeps what was made and charges nothing further.</span></div>
        </>
      ) : null}

      <span className="rh-sr-only" role="status" aria-live="polite">{live}</span>
    </article>
  );
}

const OVER_CREDIT_FOOTNOTE = "Approve is off because this step’s hard cap is more than your credit. Top-ups are coming soon.";

/** Quiet beta, top-ups off (spec 4.12.4, mockups 49 / 49b): Approve disabled, one option that fits the credit. */
function OverCredit({ model, credit: reported, titleId, actions }: {
  model: ApprovalCardModel; credit: "lower_cap" | "add_credit"; titleId: string; approveName?: string; actions: ApprovalCardActions;
}) {
  const balance = model.balanceCents ?? 0;
  // The estimate fitting the credit is what decides 49 vs 49b, even if the server sent no lower-cap option.
  const credit = model.estimateCents <= balance ? "lower_cap" : reported === "lower_cap" ? "lower_cap" : "add_credit";
  const lowered = model.lowerCapOptionCents ?? balance;
  const cheaper = credit === "add_credit" && model.cheaperOption && model.cheaperOption.capCents <= balance ? model.cheaperOption : null;
  const fits = credit === "lower_cap" || Boolean(cheaper);
  const [closed, setClosed] = useState(false);
  if (closed) return <p className="rh-footnote" role="status" data-shot="not-now-closed">Closed. Nothing was spent.</p>;
  return (
    <div data-shot={credit === "lower_cap" ? "approval-over-cap" : "approval-over-estimate"}>
      {credit === "lower_cap" ? (
        <Notice tone="ember" title={`Not enough credit for the ${formatCents(model.capCents)} cap`}>
          The cap is held from your credit while the step runs, so it can’t be more than the {formatCents(balance)} you have.
        </Notice>
      ) : (
        <Notice tone="ember" title="This step costs more than your credit">
          The {formatCents(model.estimateCents)} estimate is more than the {formatCents(balance)} you have.
        </Notice>
      )}
      {model.status === "pending" && (credit === "lower_cap" || cheaper) ? (
        <div className="rh-appr-bd rh-fits" style={{ paddingTop: 12 }}>
          <div className="rh-eyebrow">Fits your credit</div>
          <div className="rh-fg2" style={{ fontSize: 12.5, marginTop: 6 }}>
            {credit === "lower_cap"
              ? <>Same step, cap lowered to <b className="rh-mono rh-num">{formatCents(lowered)}</b>.</>
              : <>{cheaper!.label} · cap <b className="rh-mono rh-num">{formatCents(cheaper!.capCents)}</b></>}
          </div>
        </div>
      ) : null}
      {model.status === "pending" ? (
        <>
          <div className="rh-appr-ft">
            {credit === "lower_cap" ? (
              <button type="button" className="rh-btn rh-btn-primary rh-btn-act" style={{ flex: 1 }} onClick={() => actions.onLowerCap?.(lowered)}>Use this · lower the cap to {formatCents(lowered)}</button>
            ) : cheaper ? (
              <button type="button" className="rh-btn rh-btn-primary rh-btn-act" style={{ flex: 1 }} onClick={actions.onUseCheaper}>Use this · est. {formatCents(cheaper.estimateCents)}</button>
            ) : null}
            <button type="button" className="rh-btn rh-btn-act" onClick={actions.onEdit}><Pencil size={14} aria-hidden="true" />Edit</button>
            {!fits ? <button type="button" className="rh-btn rh-btn-quiet rh-btn-act" data-shot="not-now" onClick={() => { if (actions.onNotNow) actions.onNotNow(); else setClosed(true); }}>Not now</button> : null}
          </div>
          <div className="rh-appr-ft rh-appr-locked-row" style={{ paddingTop: 0 }}>
            <button type="button" className="rh-btn rh-btn-act rh-appr-locked" aria-label="Approve, unavailable: the hard cap is more than your credit" aria-disabled="true" aria-describedby={`${titleId}-why`} disabled>
              <Lock size={13} aria-hidden="true" />Approve
            </button>
          </div>
          <div className="rh-footnote" id={`${titleId}-why`}><span>{OVER_CREDIT_FOOTNOTE}</span></div>
        </>
      ) : null}
    </div>
  );
}
