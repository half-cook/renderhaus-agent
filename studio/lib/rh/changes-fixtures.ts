import type { ApprovalCardModel } from "./billing";
import { transitionChange, type ChangesDocument, type ChangeItem, type ChangeState, type Cut } from "./changes";

const createdAt = 1791677520000;
const quote = (): ApprovalCardModel => ({
  id: "changes-new-take-quote", status: "pending", title: "New take", specs: ["5 s", "16:9"],
  estimateCents: 105, capCents: 150, balanceCents: 1000,
  lines: [{ kind: "media", label: "Video clip", priceCents: 65, basis: "fixed" }, { kind: "orchestration", label: "Agent orchestration", priceCents: 40, basis: "estimate" }],
});

export function changesDocument(): ChangesDocument {
  const checkpointCut: Cut = {
    id: "cut-before-7", label: "Checkpoint before this changeset", createdAt,
    slots: [{ slotId: "n-shot1", takeId: "shot-1-take-1", inMs: 0, outMs: 5000, title: "Shot 1" }, { slotId: "n-shot2", takeId: "shot-2-take-1", inMs: 0, outMs: 5000, title: "Shot 2" }],
    order: ["n-shot1", "n-shot2"], voiceRef: "/beta/voice-before.wav", voiceDurationMs: 9000, stillRefs: { "n-shot1": "/beta/still-mug.jpg" },
  };
  return {
    revision: 1,
    changeset: { id: "changeset-7", projectId: "demo-matte-mug", n: 7, title: "Warmer finish", createdAt, checkpointCutId: checkpointCut.id, estimateCents: 97, capCents: 150, actualCents: 95, status: "open", lines: [{ kind: "media", label: "Media", priceCents: 67, basis: "fixed" }, { kind: "orchestration", label: "Agent orchestration", priceCents: 28, basis: "fixed" }] },
    changes: [
      { id: "change-7-1", changesetId: "changeset-7", n: 1, kind: "take", slotId: "n-shot2", title: "Warmer light on the handle", description: "A softer finish for Shot 2, with the same framing.", beforeRef: { kind: "take", takeId: "shot-2-take-1" }, afterRef: { kind: "take", takeId: "shot-2-take-2" }, costCents: 65, taken: true, state: "ready" },
      { id: "change-7-2", changesetId: "changeset-7", n: 2, kind: "trim", slotId: "n-shot2", title: "Shorter ending", description: "Lose the final pause and finish on the lift.", beforeRef: { kind: "trim", inMs: 0, outMs: 5000 }, afterRef: { kind: "trim", inMs: 0, outMs: 4200 }, costCents: 0, taken: false, state: "proposed" },
      { id: "change-7-3", changesetId: "changeset-7", n: 3, kind: "voice", title: "A quieter sign-off", description: "Made for wherever the morning takes you.", beforeRef: { kind: "voice", mediaRef: "/beta/voice-before.wav", durationMs: 9000 }, afterRef: { kind: "voice", mediaRef: "/beta/voice-after.wav", durationMs: 8600 }, costCents: 2, taken: true, state: "accepted" },
      { id: "change-7-4", changesetId: "changeset-7", n: 4, kind: "reorder", title: "Lead with the lift", description: "You passed on that, so the order stays as it is.", beforeRef: { kind: "reorder", order: ["n-shot1", "n-shot2"] }, afterRef: { kind: "reorder", order: ["n-shot2", "n-shot1"] }, costCents: 0, taken: false, state: "rejected" },
    ],
    takes: [
      { id: "shot-1-take-1", slotId: "n-shot1", n: 1, mediaKind: "still", mediaRef: "/beta/shot-macro.jpg", posterUrl: "/beta/shot-macro.jpg", durationMs: 5000, costCents: 65, createdAt },
      { id: "shot-2-take-1", slotId: "n-shot2", n: 1, mediaKind: "still", mediaRef: "/beta/shot-lift-cool.jpg", posterUrl: "/beta/shot-lift-cool.jpg", durationMs: 5000, costCents: 65, createdAt },
      { id: "shot-2-take-2", slotId: "n-shot2", n: 2, mediaKind: "still", mediaRef: "/beta/shot-lift-warm.jpg", posterUrl: "/beta/shot-lift-warm.jpg", durationMs: 5000, costCents: 65, parentTakeId: "shot-2-take-1", createdAt: createdAt + 1000 },
      { id: "shot-2-take-3", slotId: "n-shot2", n: 3, mediaKind: "still", mediaRef: "/beta/still-mug-wide.jpg", posterUrl: "/beta/still-mug-wide.jpg", durationMs: 5000, costCents: 65, parentTakeId: "shot-2-take-2", createdAt: createdAt + 2000, reviewState: "rejected" },
    ],
    currentCut: { ...structuredClone(checkpointCut), id: "cut-current-7", label: "Current cut", voiceRef: "/beta/voice-after.wav", voiceDurationMs: 8600 },
    checkpointCut, versions: [structuredClone(checkpointCut)], newTakeApproval: quote(),
  };
}

export type ChangesStateFixture = { id: string; title: string; document: ChangesDocument; changeN: number };
export function changesStateVariants(): ChangesStateFixture[] {
  const row = (state: ChangeState, title: string): ChangesStateFixture => {
    let document = changesDocument();
    const original = document.changes[0];
    if (!original) throw new Error("Changes fixture needs a take");
    let change: ChangeItem = { ...original, state };
    if (state === "accepted") document = transitionChange(document, 1, "accept");
    else if (state === "reverted") document = transitionChange(transitionChange(document, 1, "accept"), 1, "revert");
    else if (["awaiting_approval", "running", "paused_at_cap", "failed"].includes(state)) {
      const approval = quote();
      approval.id = `changes-${state}`;
      approval.status = state === "awaiting_approval" ? "pending" : state === "paused_at_cap" ? "paused_cap" : state === "failed" ? "failed" : "running";
      if (state === "running") { approval.heldCents = 150; approval.spentSoFarCents = 28; }
      if (state === "failed") { approval.chargedCents = 0; approval.failureMessage = "No output was produced."; }
      if (state === "paused_at_cap") { approval.heldCents = 150; approval.chargedCents = 150; approval.raiseOptionsCents = [200]; }
      change = { ...change, taken: false, approval };
    }
    if (state === "out_of_date") document.currentCut.slots = document.currentCut.slots.map((slot) => slot.slotId === "n-shot2" ? { ...slot, takeId: "shot-2-take-2" } : slot);
    document.changes = [state === "accepted" || state === "reverted" ? document.changes[0] ?? change : change];
    return { id: state, title, document, changeN: 1 };
  };
  const proposed = row("proposed", "Proposed · free");
  const trim = changesDocument().changes[1];
  if (!trim) throw new Error("Changes fixture needs a trim");
  proposed.document.changes = [{ ...trim, n: 1 }];
  const audio = row("ready", "Audio change");
  audio.id = "audio";
  audio.document.changes = [{ id: "change-audio", changesetId: "changeset-7", n: 1, kind: "voice", title: "A shorter sign-off", description: "The voiceover ends with the cut.", beforeRef: { kind: "voice", mediaRef: "/beta/voice-after.wav", durationMs: 8600 }, afterRef: { kind: "voice", mediaRef: "/beta/voice-new.wav", durationMs: 8200 }, costCents: 2, taken: true, state: "ready" }];
  const still = row("proposed", "Still image swap");
  still.id = "still";
  still.document.changes = [{ id: "change-still", changesetId: "changeset-7", n: 1, kind: "still", slotId: "n-shot1", title: "A warmer product still", description: "Shot 1 and Shot 2 use this image. A new estimate comes before regenerating either shot.", beforeRef: { kind: "still", mediaRef: "/beta/still-mug.jpg", dependentSlotIds: ["n-shot1", "n-shot2"] }, afterRef: { kind: "still", mediaRef: "/beta/still-mug-wide.jpg", dependentSlotIds: ["n-shot1", "n-shot2"] }, costCents: 0, taken: false, state: "proposed" }];
  return [proposed, row("awaiting_approval", "Waiting for approval"), row("running", "Running"), row("ready", "Ready to review"), row("accepted", "Accepted"), row("rejected", "Rejected"), row("reverted", "Reverted"), row("out_of_date", "Out of date"), row("failed", "Failed"), row("paused_at_cap", "Paused at the cap"), audio, still];
}

export const stateVariants = changesStateVariants();
