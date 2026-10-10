"use client";

import { ScanLine } from "lucide-react";
import { ChangeBadge } from "./ChangeRow";
import { CutRibbon } from "./CutRibbon";
import type { ChangesDocument } from "@/lib/rh/changes";

export function ChangesetCard({ document, onOpen, onInsert }: { document: ChangesDocument; onOpen: () => void; onInsert: (n: number) => void }) {
  const needs = document.changes.filter((change) => ["ready", "proposed", "awaiting_approval", "out_of_date", "paused_at_cap"].includes(change.state)).length;
  return <article className="rh-changeset-card" aria-label={`Changeset ${document.changeset.n}`}>
    <header><span className="rh-eyebrow">Changeset {document.changeset.n}</span><strong>{document.changeset.title}</strong><span className="rh-chip rh-chip-accent">{needs} need you</span></header>
    <CutRibbon document={document} compact />
    <footer><div>{document.changes.map((change) => <ChangeBadge key={change.id} change={change} onClick={() => onInsert(change.n)} />)}</div><button type="button" className="rh-btn rh-btn-sm" onClick={onOpen}><ScanLine size={13} aria-hidden="true" />Open compare</button></footer>
  </article>;
}
