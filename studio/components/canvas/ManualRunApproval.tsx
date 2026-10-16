"use client";

import { useRef } from "react";
import { ApprovalCard } from "@/components/rh/ApprovalCard";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { useCanvasStore } from "@/lib/canvas/store";
import { RH_ADD_CREDIT_EVENT } from "@/lib/rh/events";
import { workLabel } from "@/lib/rh/billing";

export function ManualRunApproval() {
  const returnFocus = useRef<HTMLElement | null>(null);
  const pending = useCanvasStore((state) => state.pendingManualRun);
  const approve = useCanvasStore((state) => state.approveManualRun);
  const cancel = useCanvasStore((state) => state.cancelManualRun);
  if (!pending) return null;
  const label = workLabel(pending.request.tool);
  const args = pending.request.arguments;
  const prompt = args.prompt ?? args.text ?? args.script ?? args.lyrics;
  const duration = typeof args.duration_seconds === "number" ? args.duration_seconds : args.duration;
  const specs = [typeof args.aspect_ratio === "string" ? args.aspect_ratio : null,
    typeof args.resolution === "string" ? args.resolution : null,
    typeof duration === "number" ? `${duration} s` : null]
    .filter((value): value is string => Boolean(value));
  return <Dialog open onOpenChange={(open) => { if (!open) cancel(); }}>
    <DialogContent className="rh-changes-dialog max-h-[calc(100dvh-2rem)] overflow-y-auto" onOpenAutoFocus={(event) => {
      event.preventDefault();
      returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      document.getElementById("manual-generation-title")?.focus();
    }} onCloseAutoFocus={(event) => {
      event.preventDefault();
      if (returnFocus.current?.isConnected) returnFocus.current.focus();
    }}>
      <DialogTitle id="manual-generation-title" tabIndex={-1}>Review generation</DialogTitle>
      <DialogDescription>Review this step before it runs. Closing this review keeps your settings and starts no generation.</DialogDescription>
      <ApprovalCard focusOnMount={false} model={{
        id: pending.node.id, status: "pending", title: label,
        prompt: typeof prompt === "string" ? prompt : undefined,
        specs, estimateCents: pending.quote.estimate_cents, capCents: pending.quote.cap_cents,
        balanceCents: pending.quote.balance_cents,
        lines: [{ kind: "media", label, priceCents: pending.quote.estimate_cents, basis: "fixed" }],
      }} actions={{ onApprove: () => void approve(), onReject: cancel, onNotNow: cancel, onEdit: cancel,
        onAddCredit: () => window.dispatchEvent(new CustomEvent(RH_ADD_CREDIT_EVENT)) }} />
    </DialogContent>
  </Dialog>;
}
