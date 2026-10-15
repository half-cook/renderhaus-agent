"use client";

import { useEffect, useState } from "react";
import { ApprovalCard } from "@/components/rh/ApprovalCard";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { answerAgentCap, decideAgentApproval, stopAgentRun } from "@/lib/api";
import type { ApprovalCardModel } from "@/lib/rh/billing";
import { isPaidChange } from "@/lib/rh/changes";
import type { ChangeAction, ChangeItem } from "@/lib/rh/changes";
import { useChangesStore } from "@/lib/rh/changes-store";
import { useCanvasStore } from "@/lib/canvas/store";
import type { ChangeRowProps } from "./ChangeRow";

export function useChangesReview() {
  const document = useChangesStore((state) => state.document);
  const [price, setPrice] = useState<{ model: ApprovalCardModel; change?: ChangeItem } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [stillConfirm, setStillConfirm] = useState<number | null>(null);

  function requestPrice(change: ChangeItem, fresh = false) {
    const model = fresh ? document?.newTakeApproval : change.approval;
    if (!model) { setNotice("An estimate and hard cap are needed before this step can run. Ask the agent to re-check this change."); return; }
    setPrice({ model: { ...model, status: "pending" }, change: fresh ? undefined : change });
  }
  async function runAction(change: ChangeItem, action: "approve" | "reject" | "cancel" | "raise" | "stop", capCents?: number) {
    if (!change.executionId) { setNotice("This change has no connected run yet. Nothing will run or be charged."); return; }
    try {
      if (action === "raise" || action === "stop") await answerAgentCap(change.executionId, action, capCents);
      else if (action === "cancel") await stopAgentRun(change.executionId);
      else if (change.callId) await decideAgentApproval(change.executionId, change.callId, action);
      else { setNotice("The approval is not connected yet. Ask the agent to re-check this change."); return; }
      await useChangesStore.getState().load(document?.changeset.projectId ?? "");
      setPrice(null);
    } catch { setNotice("The decision could not be saved. Nothing else has been approved. Retry after checking the connection."); }
  }
  function perform(change: ChangeItem, action: ChangeAction) {
    if (action === "accept" && isPaidChange(change) && !change.taken) { focusPrice(change.n); return; }
    if (action === "accept" && change.kind === "still") { setStillConfirm(change.n); return; }
    void useChangesStore.getState().act(change.n, action);
  }
  function rowProps(n: number): Omit<ChangeRowProps, "document" | "change" | "selected" | "compact" | "busy"> {
    const change = document?.changes.find((item) => item.n === n);
    if (!change) return {};
    return {
      onSelect: () => useChangesStore.getState().selectChange(n),
      onInsert: () => useChangesStore.getState().setComposerInsertion(`change ${n}`),
      onAction: (action) => perform(change, action),
      onCompare: () => useChangesStore.getState().openCompare(n),
      onPrice: () => requestPrice(change),
      onRecheck: () => useChangesStore.getState().setComposerInsertion(`Re-check change ${n}. The shot changed since this was proposed.`),
      approvalEnabled: Boolean(change.executionId && change.callId),
      approvalActions: {
        onApprove: () => void runAction(change, "approve"), onReject: () => void runAction(change, "reject"),
        onCancel: () => void runAction(change, "cancel"), onRaise: (cap) => void runAction(change, "raise", cap), onStop: () => void runAction(change, "stop"),
      },
    };
  }
  const dialogs = <>
    <Dialog open={price !== null} onOpenChange={(open) => { if (!open) setPrice(null); }}><DialogContent className="rh-changes-dialog" onOpenAutoFocus={(event) => { event.preventDefault(); globalThis.document.getElementById("rh-change-price-title")?.focus(); }}><DialogTitle id="rh-change-price-title" tabIndex={-1}>Review the price</DialogTitle><DialogDescription>Paid work has its own approval. Accepting or rejecting a result already taken adds no cost.</DialogDescription>{price ? <><ApprovalCard model={price.model} focusOnMount={false} approveEnabled={Boolean(price.change?.executionId && price.change?.callId)} actions={{ onApprove: () => price.change && void runAction(price.change, "approve"), onReject: () => setPrice(null), onEdit: () => { setPrice(null); useChangesStore.getState().setComposerInsertion("Adjust this step before asking for approval again."); } }} /><p className="rh-small rh-fg2">{price.change?.executionId ? "Review this step before approving." : "Take generation is not connected yet. This card cannot start a run."}</p></> : null}</DialogContent></Dialog>
    <Dialog open={stillConfirm !== null} onOpenChange={(open) => { if (!open) setStillConfirm(null); }}><DialogContent className="rh-changes-dialog"><DialogTitle>Accept the still image?</DialogTitle><DialogDescription>The dependent shots keep their current takes. Regenerating them needs a separate estimate and approval.</DialogDescription><button type="button" className="rh-btn rh-btn-solid" onClick={() => { if (stillConfirm !== null) void useChangesStore.getState().act(stillConfirm, "accept"); setStillConfirm(null); }}>Accept the still only</button></DialogContent></Dialog>
    {notice ? <div className="rh-changes-toast" role="status"><span>{notice}</span><button type="button" className="rh-btn rh-btn-sm" onClick={() => setNotice(null)}>Dismiss</button></div> : null}
  </>;
  return { rowProps, dialogs, requestPrice, perform };
}

function focusPrice(n: number) {
  useChangesStore.getState().setTab("changes");
  requestAnimationFrame(() => {
    const root = globalThis.document.querySelector<HTMLElement>(`[data-price-change="${n}"]`);
    (root?.querySelector<HTMLElement>("h3") ?? root)?.focus();
  });
}

export function ChangesKeyboard() {
  const document = useChangesStore((state) => state.document);
  const agentOpen = useCanvasStore((state) => state.agentOpen);
  const timelineOpen = useCanvasStore((state) => state.timelineOpen);
  useEffect(() => {
    if (!document || (!agentOpen && !timelineOpen)) return;
    function onKey(event: KeyboardEvent) {
      if (event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
      const target = event.target;
      if (target instanceof Element && target.closest("input,textarea,select,[contenteditable='true'],[role='dialog']")) return;
      const store = useChangesStore.getState();
      const doc = store.document;
      if (!doc || store.busy) return;
      const key = event.key.toLowerCase();
      if (store.compareN !== null && ["a", "r", "c"].includes(key)) return;
      const selected = doc.changes.find((change) => change.n === store.selectedN);
      if (key === "j" || key === "k") {
        event.preventDefault();
        const current = doc.changes.findIndex((change) => change.n === store.selectedN);
        const next = doc.changes[Math.max(0, Math.min(doc.changes.length - 1, current + (key === "j" ? -1 : 1)))];
        if (next) { store.closeCompare(); store.selectChange(next.n); store.setTab("changes"); requestAnimationFrame(() => globalThis.document.querySelector<HTMLElement>(`.rh-review-panel [data-change="${next.n}"] .rh-change-number`)?.focus()); }
      } else if (key === "g") { event.preventDefault(); store.setMonitorMode(store.monitorMode === "current" ? "changes" : "current"); }
      else if (selected && key === "c" && selected.kind === "take") { event.preventDefault(); if (isPaidChange(selected) && !selected.taken) focusPrice(selected.n); else store.openCompare(selected.n); }
      else if (selected && key === "a") {
        event.preventDefault();
        if (isPaidChange(selected) && !selected.taken) focusPrice(selected.n);
        else if (["proposed", "ready"].includes(selected.state)) {
          if (selected.kind === "still") globalThis.document.querySelector<HTMLButtonElement>(`.rh-review-panel [data-change="${selected.n}"] .rh-change-actions button:last-child`)?.click();
          else void store.act(selected.n, "accept");
        }
      } else if (selected && key === "r" && ["proposed", "ready", "awaiting_approval"].includes(selected.state)) { event.preventDefault(); void store.act(selected.n, "reject"); }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [document, agentOpen, timelineOpen]);
  return null;
}
