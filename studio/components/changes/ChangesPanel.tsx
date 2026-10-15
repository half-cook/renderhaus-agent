"use client";

import { Clock, History, Lock } from "lucide-react";
import { useState } from "react";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Ledger, LedgerRow, LedgerTotal, lineLabel } from "@/components/rh/Ledger";
import { ChangeRow, type ChangeRowProps } from "./ChangeRow";
import type { ChangesDocument } from "@/lib/rh/changes";
import { formatCents } from "@/lib/rh/money";
import { cutClips, freeChanges, needYou, withChangesCut } from "@/lib/rh/changes";
import { totalSeconds } from "@/lib/rh/timeline";

export type ChangesPanelProps = {
  document: ChangesDocument;
  selectedN: number;
  compact?: boolean;
  busy?: boolean;
  error?: string | null;
  rowProps: (n: number) => Omit<ChangeRowProps, "document" | "change" | "selected" | "compact" | "busy">;
  onAcceptFree: () => void;
  onRejectAll: () => void;
  onRestore: () => Promise<boolean>;
};

export function ChangesPanel({ document, selectedN, compact = false, busy, error, rowProps, onAcceptFree, onRejectAll, onRestore }: ChangesPanelProps) {
  const [restoreOpen, setRestoreOpen] = useState(false);
  const { changeset, changes } = document;
  const needs = needYou(document);
  const free = freeChanges(document).length;
  const before = totalSeconds(cutClips(document, document.checkpointCut));
  const after = totalSeconds(cutClips(document, withChangesCut(document)));
  const date = new Date(changeset.createdAt);
  const today = date.toLocaleDateString("en-CA", { timeZone: "America/Toronto" }) === new Date().toLocaleDateString("en-CA", { timeZone: "America/Toronto" });
  const dateLabel = Number.isNaN(date.getTime()) ? "Time unavailable" : `${today ? "Today" : date.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "America/Toronto" })} ${date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/Toronto" })}`;

  return <section className="rh-changes-panel" data-shot="agent-changes-ready" aria-label="Changeset review">
    <header className="rh-changes-heading"><p className="rh-eyebrow">Changeset {changeset.n} · {dateLabel}</p><div><h2 className="rh-serif">{changeset.title}</h2><span className="rh-chip rh-chip-accent">{needs} need you</span></div>
      <p className="rh-changes-meta"><Clock size={12} aria-hidden="true" /><span>Cut length <b className="rh-mono">{before.toFixed(1)} s → {after.toFixed(1)} s</b> · {changes.filter((change) => change.state === "accepted").length} accepted · {changes.filter((change) => change.state === "rejected").length} rejected</span></p>
      <div className="rh-changes-bulk">{free > 0 ? <button type="button" className="rh-btn rh-btn-solid" disabled={busy} onClick={onAcceptFree}>Accept free changes · {free}</button> : null}<button type="button" className="rh-btn rh-btn-quiet" disabled={busy || !changes.some((change) => ["proposed", "ready", "awaiting_approval", "out_of_date", "failed"].includes(change.state))} onClick={onRejectAll}>Reject all</button></div>
    </header>
    {error ? <p className="rh-change-notice" role="alert">{error}</p> : null}
    <div className="rh-changes-rows">{changes.map((change) => <ChangeRow key={change.id} document={document} change={change} selected={selectedN === change.n} compact={compact} busy={busy} {...rowProps(change.n)} />)}</div>
    <div className="rh-changes-spend"><Ledger heading="Charged so far">{changeset.lines.map((line) => <LedgerRow key={`${line.kind}:${line.label}`} label={lineLabel(line, "so-far")} amount={formatCents(line.priceCents)} tone={line.kind === "orchestration" ? "muted" : undefined} />)}<LedgerTotal label="Charged so far" amountCents={changeset.actualCents} /><p className="rh-changes-cap"><Lock size={12} aria-hidden="true" />Estimate was {formatCents(changeset.estimateCents)} · hard cap {formatCents(changeset.capCents)}</p></Ledger></div>
    <div className="rh-changes-checkpoint"><History size={14} aria-hidden="true" /><span>Checkpoint before this changeset</span><Dialog open={restoreOpen} onOpenChange={setRestoreOpen}><DialogTrigger asChild><button type="button" className="rh-btn rh-btn-quiet" disabled={busy}><History size={13} aria-hidden="true" />Restore</button></DialogTrigger><DialogContent className="rh-changes-dialog" onOpenAutoFocus={(event) => { event.preventDefault(); documentFocus("rh-restore-title"); }}><DialogTitle id="rh-restore-title" tabIndex={-1}>Restore the checkpoint?</DialogTitle><DialogDescription>The film returns to the cut saved before this changeset as a new version. Every take stays in Takes.</DialogDescription><DialogFooter><DialogClose asChild><button type="button" className="rh-btn">Keep this version</button></DialogClose><button type="button" className="rh-btn rh-btn-solid" disabled={busy} onClick={() => void onRestore().then((success) => { if (success) setRestoreOpen(false); })}>Restore as a new version</button></DialogFooter></DialogContent></Dialog></div>
    <span className="sr-only" aria-live="polite">{changes.find((change) => change.n === selectedN)?.title}. {needs} changes need you.</span>
  </section>;
}

function documentFocus(id: string) { globalThis.document.getElementById(id)?.focus(); }
