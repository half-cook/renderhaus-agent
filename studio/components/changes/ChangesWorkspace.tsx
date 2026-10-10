"use client";

import { AgentReviewPanel } from "@/components/canvas/AgentReviewPanel";
import { useCanvasStore } from "@/lib/canvas/store";
import { useChangesStore } from "@/lib/rh/changes-store";
import { CompareView } from "./CompareView";
import { ChangesTimeline } from "./ChangesTimeline";
import { useChangesReview } from "./ChangesReview";

export function ChangesWorkspace({ timeline }: { timeline: boolean }) {
  const document = useChangesStore((state) => state.document);
  const compareN = useChangesStore((state) => state.compareN);
  const selectedN = useChangesStore((state) => state.selectedN);
  const mode = useChangesStore((state) => state.compareMode);
  const monitor = useChangesStore((state) => state.monitorMode);
  const { requestPrice, dialogs } = useChangesReview();
  const store = useChangesStore.getState();
  if (!document) return null;
  const selected = document.changes.find((change) => change.n === selectedN) ?? document.changes[0];
  const comparing = document.changes.find((change) => change.n === compareN);
  const back = () => {
    store.closeCompare();
    requestAnimationFrame(() => globalThis.document.querySelector<HTMLElement>(`.rh-review-panel [data-change="${compareN}"] button.rh-btn`)?.focus());
  };
  return <>
    {comparing ? <CompareView key={comparing.id} document={document} change={comparing} initialMode={mode} onModeChange={store.setCompareMode}
      onBack={back} onAcceptTake={(id) => void store.acceptTake(comparing.n, id)} onKeepTake={() => void store.act(comparing.n, "reject")}
      onNewTake={() => requestPrice(comparing, true)} onAskFrame={(text) => { const canvas = useCanvasStore.getState(); store.queueFrameMessage(text, canvas.projectId, canvas.conversationId ?? "", comparing.slotId ?? ""); store.closeCompare(); canvas.setWorkspaceView("agent"); }} />
      : timeline ? <ChangesTimeline document={document} selectedN={selectedN ?? 0} monitorMode={monitor} onMonitorModeChange={store.setMonitorMode}
        onSelectChange={store.selectChange} onCompare={store.openCompare} onNewTake={() => { if (selected) requestPrice(selected, true); }}
        reviewPanel={<AgentReviewPanel />} onTrimVoiceover={(cut) => void store.trimToFit(cut)}
        actions={{
          trim: (id, inSeconds, outSeconds) => void store.editCut({ ...document.currentCut, slots: document.currentCut.slots.map((slot) => slot.slotId === id ? { ...slot, inMs: Math.round(inSeconds * 1000), outMs: Math.round(outSeconds * 1000) } : slot) }),
          reorder: (order) => void store.editCut({ ...document.currentCut, order }),
          remove: (id) => void store.editCut({ ...document.currentCut, slots: document.currentCut.slots.filter((slot) => slot.slotId !== id), order: document.currentCut.order.filter((slot) => slot !== id) }),
        }} /> : null}
    {dialogs}
  </>;
}
