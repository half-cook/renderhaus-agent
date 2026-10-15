"use client";

import { create } from "zustand";
import { studioFetch } from "@/lib/authenticated-fetch";
import { isPaidChange, acceptFreeChanges, cutDurationMs, editChangesCut, parseChangesDocument, rejectAllChanges, restoreCheckpoint, transitionChange, trimVoiceToFit, type ChangeAction, type ChangesDocument, type Cut, type TransitionOptions } from "./changes";

export type ChangesTab = "preview" | "changes" | "timeline";
export type CompareMode = "swipe" | "side-by-side" | "flicker";
export type MonitorMode = "current" | "changes";
export type FrameMessage = { text: string; projectId: string; conversationId: string; slotId: string };
export type ChangesStore = {
  frameMessage: FrameMessage | null;
  queueFrameMessage: (text: string, projectId: string, conversationId: string, slotId: string) => void;
  consumeFrameMessage: () => FrameMessage | null;
  document: ChangesDocument | null; documents: ChangesDocument[]; mode: "api" | "fixture"; projectId: string | null;
  selectedN: number | null; tab: ChangesTab; compareN: number | null; compareMode: CompareMode; monitorMode: MonitorMode;
  composerInsertion: string | null; error: string | null; busy: boolean;
  seed: (document: ChangesDocument) => void;
  load: (projectId: string) => Promise<void>;
  selectDocument: (id: string) => void;
  act: (n: number, action: ChangeAction) => Promise<void>;
  acceptTake: (n: number, takeId: string) => Promise<void>;
  acceptFree: () => Promise<void>;
  rejectAll: () => Promise<void>;
  restore: () => Promise<void>;
  trimToFit: (cut?: Cut) => Promise<void>;
  editCut: (cut: Cut) => Promise<void>;
  selectChange: (n: number) => void;
  setTab: (tab: ChangesTab) => void;
  openCompare: (n: number) => void;
  closeCompare: () => void;
  setCompareMode: (mode: CompareMode) => void;
  setMonitorMode: (mode: MonitorMode) => void;
  setComposerInsertion: (text: string) => void;
  consumeComposerInsertion: () => string | null;
  dismissError: () => void;
};

type Mutation = ChangeAction | "acceptFree" | "rejectAll" | "restore" | "trimToFit" | "editCut";

export const useChangesStore = create<ChangesStore>((set, get) => {
  let loadSerial = 0;
  const receive = (document: ChangesDocument) => {
    set((state) => ({ document, documents: state.documents.map((item) => item.changeset.id === document.changeset.id ? document : item) }));
  };
  const mutate = async (n: number, action: Mutation, options: TransitionOptions = {}, cut?: Cut) => {
    const state = get();
    const document = state.document;
    if (!document || state.busy) return;
    const serial = loadSerial;
    set({ busy: true, error: null });
    try {
      const next = action === "acceptFree" ? acceptFreeChanges(document) : action === "rejectAll" ? rejectAllChanges(document) : action === "restore" ? restoreCheckpoint(document) : action === "trimToFit" ? trimVoiceToFit(document, cut) : action === "editCut" ? cut ? editChangesCut(document, cut) : document : transitionChange(document, n, action, options);
      receive(next);
      if (state.mode === "fixture") {
        return;
      } else {
        const base = `/api/studio/changesets/${encodeURIComponent(document.changeset.id)}`;
        const response = await studioFetch(action === "restore" ? `${base}/restore` : `${base}/changes/${n}/${action}`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ expected_revision: document.revision, ...(options.takeId ? { take_id: options.takeId } : {}), ...(action === "editCut" && cut ? { cut } : {}), ...(action === "trimToFit" && cut ? { max_duration_ms: cutDurationMs(cut) } : {}) }),
        });
        const payload: unknown = await response.json().catch(() => null);
        const saved = parseChangesDocument(payload);
        if (!response.ok || !saved) throw new Error("Could not save changes");
        if (get().projectId === state.projectId && get().mode === "api" && loadSerial === serial) receive(saved);
      }
    } catch {
      if (get().projectId === state.projectId && get().mode === state.mode && loadSerial === serial) {
        receive(document);
        set({ error: "Changes could not be saved. Reload and try again." });
      }
    } finally {
      if (get().projectId === state.projectId && loadSerial === serial) set({ busy: false });
    }
  };
  return {
    frameMessage: null,
    queueFrameMessage: (text, projectId, conversationId, slotId) => set({ frameMessage: { text, projectId, conversationId, slotId } }),
    consumeFrameMessage: () => { const message = get().frameMessage; set({ frameMessage: null }); return message; },
    document: null, documents: [], mode: "api", projectId: null, selectedN: null, tab: "preview", compareN: null,
    compareMode: "swipe", monitorMode: "current", composerInsertion: null, error: null, busy: false,
    seed: (value) => {
      loadSerial += 1;
      const document = parseChangesDocument(value);
      set({ mode: "fixture", document, documents: document ? [document] : [], projectId: document?.changeset.projectId ?? null, selectedN: document?.changes[0]?.n ?? null, compareN: null, error: document ? null : "This changeset is unavailable.", busy: false });
    },
    load: async (projectId) => {
      const serial = ++loadSerial;
      set({ mode: "api", projectId, document: null, documents: [], selectedN: null, compareN: null, busy: true, error: null });
      try {
        const response = await studioFetch(`/api/studio/projects/${encodeURIComponent(projectId)}/changesets`);
        const payload: unknown = await response.json().catch(() => null);
        if (!response.ok || !payload || typeof payload !== "object" || !("items" in payload) || !Array.isArray(payload.items)) throw new Error("Changes unavailable");
        const parsed = payload.items.map((item: unknown) => parseChangesDocument(item));
        if (parsed.some((item) => !item) || parsed.some((item) => item?.changeset.projectId !== projectId)) throw new Error("Invalid changes");
        const documents = parsed.filter((item): item is ChangesDocument => item !== null);
        if (serial === loadSerial) set({ documents, document: documents[0] ?? null, selectedN: documents[0]?.changes[0]?.n ?? null });
      } catch {
        if (serial === loadSerial) set({ error: "Changes could not be loaded. Try again." });
      } finally {
        if (serial === loadSerial) set({ busy: false });
      }
    },
    selectDocument: (id) => {
      const document = get().documents.find((item) => item.changeset.id === id);
      if (document) set({ document, selectedN: document.changes[0]?.n ?? null, compareN: null });
    },
    act: (n, action) => mutate(n, action),
    acceptTake: (n, takeId) => mutate(n, "accept", { takeId }),
    acceptFree: () => mutate(0, "acceptFree"),
    rejectAll: () => mutate(0, "rejectAll"),
    restore: () => mutate(0, "restore"),
    trimToFit: (cut) => mutate(0, "trimToFit", {}, cut),
    editCut: (cut) => mutate(0, "editCut", {}, cut),
    selectChange: (selectedN) => set({ selectedN }),
    setTab: (tab) => set({ tab }),
    openCompare: (n) => {
      const change = get().document?.changes.find((item) => item.n === n);
      set({ selectedN: n, tab: "changes" });
      if (change?.kind === "take" && (!isPaidChange(change) || change.taken)) set({ compareN: n });
    },
    closeCompare: () => set({ compareN: null, tab: "changes" }),
    setCompareMode: (compareMode) => set({ compareMode }),
    setMonitorMode: (monitorMode) => set({ monitorMode }),
    setComposerInsertion: (composerInsertion) => set({ composerInsertion }),
    consumeComposerInsertion: () => { const value = get().composerInsertion; set({ composerInsertion: null }); return value; },
    dismissError: () => set({ error: null }),
  };
});
