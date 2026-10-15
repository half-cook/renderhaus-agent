"use client";

import { ArrowRight, CircleAlert, ScanLine } from "lucide-react";
import { ApprovalCard } from "@/components/rh/ApprovalCard";
import type { ApprovalCardModel } from "@/lib/rh/billing";
import { cn } from "@/lib/cn";
import type { ApprovalCardActions } from "@/components/rh/ApprovalCard";
import { isPaidChange, type ChangeAction, type ChangeItem, type ChangesDocument } from "@/lib/rh/changes";
import { formatCents } from "@/lib/rh/money";

export const CHANGE_STATE_LABELS: Record<ChangeItem["state"], string> = {
  proposed: "Needs you", awaiting_approval: "Waiting for approval", running: "Running",
  ready: "Needs you", accepted: "Accepted", rejected: "Rejected", reverted: "Reverted",
  out_of_date: "Out of date", failed: "Failed", paused_at_cap: "Paused at the cap",
};
const KINDS = { take: "New take", trim: "Trim", reorder: "Reorder", voice: "Voiceover", still: "Image" };
const stamp = (ms: number) => `0:${(ms / 1000).toFixed(1).padStart(4, "0")}`;

export function changeAccessibleName(change: ChangeItem): string {
  const shot = change.title.match(/Shot \d+/i)?.[0];
  return [`Change ${change.n}`, shot, KINDS[change.kind].toLowerCase(), CHANGE_STATE_LABELS[change.state].toLowerCase()].filter(Boolean).join(", ");
}

export function ChangeBadge({ change, selected = false, onClick }: { change: ChangeItem; selected?: boolean; onClick?: () => void }) {
  return <button type="button" className="rh-change-number rh-mono" data-state={change.state} data-selected={selected}
    aria-label={changeAccessibleName(change)} title={`Insert change ${change.n} into the message`} onClick={onClick}>{change.n}</button>;
}

function ThumbPair({ document, change }: { document: ChangesDocument; change: ChangeItem }) {
  if (change.kind !== "take" && change.kind !== "still") return null;
  const beforeTake = change.kind === "take" ? document.takes.find((take) => take.id === change.beforeRef.takeId) : undefined;
  const afterTake = change.kind === "take" ? document.takes.find((take) => take.id === change.afterRef.takeId) : undefined;
  const before = beforeTake?.posterUrl ?? (change.kind === "still" ? change.beforeRef.mediaRef : undefined);
  const after = afterTake?.posterUrl ?? (change.kind === "still" ? change.afterRef.mediaRef : undefined);
  return <div className="rh-change-thumbs">
    <figure>{before ? <img src={before} alt="Before this change" width={76} height={43} /> : <span className="rh-change-missing">No preview</span>}<figcaption>{change.kind === "take" ? `Take ${beforeTake?.n ?? "?"} · in your cut` : "Before"}</figcaption></figure>
    <ArrowRight size={14} aria-hidden="true" />
    <figure className="rh-change-after">{after ? <img src={after} alt="With this change" width={76} height={43} /> : <span className="rh-change-missing">No preview</span>}<figcaption>{change.kind === "take" ? `Take ${afterTake?.n ?? "?"} · new` : "After"}</figcaption></figure>
  </div>;
}

function Waveform({ label, after }: { label: string; after?: boolean }) {
  return <div className="rh-change-wave" data-after={after}><span>{label}</span><svg viewBox="0 0 200 24" role="img" aria-label={`${label} audio waveform illustration`}>
    {Array.from({ length: 66 }, (_, n) => { const height = 4 + ((n * 17 + (after ? 7 : 0)) % 19); return <path key={n} d={`M${n * 3 + 1} ${12 - height / 2}v${height}`} />; })}
  </svg></div>;
}

function ChangeBody({ document, change }: { document: ChangesDocument; change: ChangeItem }) {
  switch (change.kind) {
    case "take": return <><ThumbPair document={document} change={change} /><p>{change.description}</p></>;
    case "trim": return <><div className="rh-change-trim rh-mono"><del>− {change.title.replace(/^Trim /, "")} · out {stamp(change.beforeRef.outMs)}</del><ins>+ {change.title.replace(/^Trim /, "")} · out {stamp(change.afterRef.outMs)}</ins></div><p>{change.description}</p></>;
    case "reorder": return <><p className="rh-mono">{change.beforeRef.order.map((id) => document.currentCut.slots.find((slot) => slot.slotId === id)?.title ?? "Shot").join(" → ")}<br />{change.afterRef.order.map((id) => document.currentCut.slots.find((slot) => slot.slotId === id)?.title ?? "Shot").join(" → ")}</p><p>{change.description}</p></>;
    case "voice": return <><Waveform label="Before" /><Waveform label="After" after /><p>Length {stamp(change.beforeRef.durationMs)} → {stamp(change.afterRef.durationMs)}. Voiceover is attached to the cut.</p><p>{change.description}</p><small>Waveform illustration. Audio playback is unavailable.</small></>;
    case "still": return <><ThumbPair document={document} change={change} /><p>{change.description}</p><p>{change.afterRef.dependentSlotIds.map((id) => document.currentCut.slots.find((slot) => slot.slotId === id)?.title ?? "Dependent shot").join(" and ")} start from this still. You will be asked before regenerating them.</p></>;
    default: { const exhaustive: never = change; return exhaustive; }
  }
}

export type ChangeRowProps = {
  document: ChangesDocument;
  change: ChangeItem;
  selected?: boolean;
  compact?: boolean;
  busy?: boolean;
  onSelect?: () => void;
  onInsert?: () => void;
  onAction?: (action: ChangeAction) => void;
  onCompare?: () => void;
  onPrice?: () => void;
  onRecheck?: () => void;
  approvalActions?: ApprovalCardActions;
  approvalEnabled?: boolean;
};

export function ChangeRow({ document, change, selected = false, compact = false, busy = false, onSelect, onInsert, onAction, onCompare, onPrice, onRecheck, approvalActions, approvalEnabled = false }: ChangeRowProps) {
  const paid = isPaidChange(change);
  const collapsed = ["accepted", "rejected", "reverted"].includes(change.state);
  const waiting = change.state === "awaiting_approval" || (paid && !change.taken && change.state === "proposed");
  const cardState = waiting ? "pending" : change.state === "running" ? "running" : change.state === "paused_at_cap" ? "paused_cap" : undefined;
  const card: ApprovalCardModel | undefined = paid && change.approval && cardState ? { ...change.approval, status: cardState } : undefined;
  const canAccept = ["proposed", "ready"].includes(change.state) && (!paid || change.taken);
  const cost = !paid ? "Free" : `${formatCents(change.costCents)} ${change.state === "rejected" ? "kept in Takes" : change.state === "reverted" ? "not refunded" : change.taken ? "charged" : "estimated"}`;

  if (collapsed) {
    const action = change.state === "accepted" ? "revert" : change.state === "rejected" ? "undo" : "reapply";
    const actionLabel = change.state === "accepted" ? "Revert" : change.state === "rejected" ? "Undo" : "Re-apply";
    return <article className={cn("rh-change-row", "rh-change-one-line", selected && "rh-change-selected")} data-change={change.n} data-state={change.state} data-collapsed="true" aria-label={`Change ${change.n} · ${change.title}`} onFocus={onSelect}>
      <ChangeBadge change={change} selected={selected} onClick={onInsert} />
      <h3 title={change.title}>{change.title}</h3>
      <span className={cn("rh-chip", change.state === "accepted" && "rh-chip-ok")}>{CHANGE_STATE_LABELS[change.state]}</span>
      <span className="rh-mono rh-change-cost" title={cost}>{paid ? formatCents(change.costCents) : "Free"}</span><span className="sr-only">{cost}</span>
      <button type="button" className="rh-btn rh-btn-quiet rh-btn-sm" disabled={busy} onClick={() => onAction?.(action)}>{actionLabel}</button>
    </article>;
  }

  return <article className={cn("rh-change-row", selected && "rh-change-selected")} data-state={change.state} data-collapsed="false" data-compact={compact}
    data-change={change.n} aria-label={`Change ${change.n} · ${change.title}`} onFocus={onSelect}>
    <div className="rh-change-row-head">
      <ChangeBadge change={change} selected={selected} onClick={onInsert} />
      <div className="rh-change-name"><h3>{change.title}</h3>{!compact ? <span className="rh-eyebrow">{KINDS[change.kind]}</span> : null}</div>
      <span className={cn("rh-chip", ["failed", "out_of_date"].includes(change.state) ? "rh-chip-danger" : "rh-chip-accent")}>{waiting ? "Waiting for approval" : CHANGE_STATE_LABELS[change.state]}</span>
    </div>
    {!compact && !card && !["failed", "out_of_date"].includes(change.state) ? <div className="rh-change-body"><ChangeBody document={document} change={change} /></div> : null}
    {change.state === "out_of_date" ? <p className="rh-change-notice" role="status"><CircleAlert size={14} aria-hidden="true" />{change.title.match(/Shot \d+/i)?.[0] ?? (change.slotId ? `Shot ${document.checkpointCut.order.indexOf(change.slotId) + 1}` : "The cut")} changed since this was proposed. Re-check before accepting.</p> : null}
    {change.state === "failed" ? <p className="rh-change-notice" data-tone="danger">No output was produced. Charged {formatCents(change.approval?.chargedCents ?? 0)}.</p> : null}
    {card ? <div className="rh-change-price" tabIndex={-1} data-price-change={change.n}><ApprovalCard model={card} busy={busy} focusOnMount={false} approveEnabled={approvalEnabled} actions={approvalActions} />{!approvalEnabled && cardState === "pending" ? <p className="rh-small rh-fg2">Generation is not connected to this change yet. Nothing will run.</p> : null}</div> : null}
    {!card ? <div className="rh-change-row-foot"><span className={cn("rh-mono", paid && "rh-change-cost")}>{cost}</span><span className="rh-change-actions">
      {canAccept && change.kind === "take" ? <button type="button" className="rh-btn rh-btn-quiet rh-btn-sm" onClick={onCompare}><ScanLine size={13} aria-hidden="true" />Compare</button> : null}
      {canAccept ? <><button type="button" className="rh-btn rh-btn-sm" disabled={busy} onClick={() => onAction?.("reject")}>Reject</button><button type="button" className={cn("rh-btn rh-btn-sm", selected ? "rh-btn-primary" : "rh-btn-solid")} disabled={busy} onClick={() => onAction?.("accept")}>Accept</button></> : null}
      {waiting ? <button type="button" className="rh-btn rh-btn-sm" data-price-change={change.n} onClick={onPrice}>Review price</button> : null}
      {change.state === "out_of_date" ? <><button type="button" className="rh-btn rh-btn-sm" disabled={busy} onClick={() => onAction?.("reject")}>Dismiss</button><button type="button" className="rh-btn rh-btn-solid rh-btn-sm" onClick={onRecheck}>Re-check</button></> : null}
      {change.state === "failed" ? <><button type="button" className="rh-btn rh-btn-sm" disabled={busy} onClick={() => onAction?.("reject")}>Skip</button><button type="button" className="rh-btn rh-btn-solid rh-btn-sm" onClick={onPrice}>Retry{change.approval ? ` · est. ${formatCents(change.approval.estimateCents)}` : " · estimate first"}</button></> : null}
    </span></div> : null}
  </article>;
}
