import { parseLines, safeCopy, toApprovalCardModel, type ApprovalCardModel, type BillingLine } from "./billing";
import { approvalCardModel } from "./approval-model";
import { isCents } from "./money";
import type { TimelineClip } from "./timeline";

export type ChangeState = "proposed" | "awaiting_approval" | "running" | "ready" | "accepted" | "rejected" | "reverted" | "out_of_date" | "failed" | "paused_at_cap";
export type ChangeAction = "accept" | "reject" | "revert" | "undo" | "reapply" | "dismiss" | "recheck";
export type TakeRef = { kind: "take"; takeId: string };
export type TrimRef = { kind: "trim"; inMs: number; outMs: number };
export type OrderRef = { kind: "reorder"; order: string[] };
export type VoiceRef = { kind: "voice"; mediaRef: string | null; durationMs: number };
export type StillRef = { kind: "still"; mediaRef: string | null; dependentSlotIds: string[] };
type ChangeBase = {
  id: string; changesetId: string; n: number; slotId?: string; title: string; description: string;
  state: ChangeState; costCents: number; taken: boolean; approval?: ApprovalCardModel; executionId?: string; callId?: string;
};
export type ChangeItem = ChangeBase & (
  | { kind: "take"; slotId: string; beforeRef: TakeRef; afterRef: TakeRef }
  | { kind: "trim"; slotId: string; beforeRef: TrimRef; afterRef: TrimRef }
  | { kind: "reorder"; beforeRef: OrderRef; afterRef: OrderRef }
  | { kind: "voice"; beforeRef: VoiceRef; afterRef: VoiceRef }
  | { kind: "still"; slotId: string; beforeRef: StillRef; afterRef: StillRef }
);
export type Take = {
  id: string; slotId: string; n: number; mediaRef: string; mediaKind: "video" | "still"; posterUrl?: string;
  durationMs: number; costCents: number; parentTakeId?: string; createdAt: number; width?: number; height?: number; reviewState?: "kept" | "rejected";
};
export type CutSlot = { slotId: string; takeId: string; inMs: number; outMs: number; title?: string };
export type Cut = {
  id: string; label: string; createdAt: number; slots: CutSlot[]; order: string[];
  voiceRef?: string; voiceDurationMs?: number; stillRefs?: Record<string, string | null>;
};
export type Changeset = {
  id: string; projectId: string; n: number; title: string; createdAt: number; checkpointCutId: string;
  estimateCents: number; capCents: number; actualCents: number; status: "open" | "running" | "paused_at_cap" | "done"; lines: BillingLine[];
};
export type ChangesDocument = {
  revision: number; changeset: Changeset; changes: ChangeItem[]; takes: Take[];
  currentCut: Cut; checkpointCut: Cut; versions: Cut[]; newTakeApproval?: ApprovalCardModel;
};
export type TransitionOptions = { expectedRevision?: number; takeId?: string };

const REVIEW_STATES: ChangeState[] = ["proposed", "ready"];
const UI_JARGON = /\b(diff|commit|merge|branch|provider|vendor|upstream|third.party|planner|llm|tokens|aws|amazon|clerk|stripe|cloudflare|vercel)\b/i;
export function safeChangeCopy(value: unknown, fallback: string): string {
  const clean = safeCopy(value, fallback);
  return UI_JARGON.test(clean) ? fallback : clean;
}

export function needYou(document: ChangesDocument): number {
  return document.changes.filter((change) => ["proposed", "awaiting_approval", "ready", "out_of_date", "failed", "paused_at_cap"].includes(change.state)).length;
}
export function isPaidChange(change: ChangeItem): boolean {
  return change.costCents > 0 || (change.approval?.estimateCents ?? 0) > 0 || (change.approval?.capCents ?? 0) > 0 || change.approval?.estimateIncomplete === true;
}
export function freeChanges(document: ChangesDocument): ChangeItem[] {
  return document.changes.filter((change) => !isPaidChange(change) && REVIEW_STATES.includes(change.state));
}
export function cutDurationMs(cut: Cut): number {
  return cut.slots.reduce((sum, slot) => sum + slot.outMs - slot.inMs, 0);
}
export function cutClips(document: ChangesDocument, cut: Cut): TimelineClip[] {
  return cut.order.flatMap((id, index): TimelineClip[] => {
    const slot = cut.slots.find((item) => item.slotId === id);
    const take = document.takes.find((item) => item.id === slot?.takeId);
    return slot && take ? [{ id, order: index + 1, title: slot.title ?? `Shot ${index + 1}`, sourceSeconds: take.durationMs / 1000, trimIn: slot.inMs / 1000, trimOut: slot.outMs / 1000, thumbUrl: take.posterUrl ?? (take.mediaKind === "still" ? take.mediaRef : undefined) }] : [];
  });
}

function matches(cut: Cut, change: ChangeItem, side: "beforeRef" | "afterRef"): boolean {
  const slot = cut.slots.find((item) => item.slotId === change.slotId);
  switch (change.kind) {
    case "take": return slot?.takeId === change[side].takeId;
    case "trim": return slot?.inMs === change[side].inMs && slot?.outMs === change[side].outMs;
    case "reorder": return JSON.stringify(cut.order) === JSON.stringify(change[side].order);
    case "voice": return (cut.voiceRef ?? null) === change[side].mediaRef && (cut.voiceDurationMs ?? 0) === change[side].durationMs;
    case "still": return !!slot && (cut.stillRefs?.[change.slotId] ?? null) === change[side].mediaRef;
    default: { const exhaustive: never = change; return exhaustive; }
  }
}
function apply(cut: Cut, document: ChangesDocument, change: ChangeItem, side: "beforeRef" | "afterRef"): Cut | null {
  switch (change.kind) {
    case "take": {
      const take = document.takes.find((item) => item.id === change[side].takeId && item.slotId === change.slotId);
      const slot = cut.slots.find((item) => item.slotId === change.slotId);
      if (!take || !slot || slot.outMs > take.durationMs || document.changes.some((item) => item.kind === "take" && item.afterRef.takeId === take.id && isPaidChange(item) && !item.taken)) return null;
      return { ...cut, slots: cut.slots.map((item) => item.slotId === change.slotId ? { ...item, takeId: take.id } : item) };
    }
    case "trim": {
      const slot = cut.slots.find((item) => item.slotId === change.slotId);
      const take = document.takes.find((item) => item.id === slot?.takeId);
      const ref = change[side];
      if (!slot || !take || ref.inMs < 0 || ref.outMs - ref.inMs < 500 || ref.outMs > take.durationMs) return null;
      return { ...cut, slots: cut.slots.map((item) => item.slotId === change.slotId ? { ...item, inMs: ref.inMs, outMs: ref.outMs } : item) };
    }
    case "reorder": {
      const order = change[side].order;
      if (order.length !== cut.slots.length || new Set(order).size !== order.length || order.some((id) => !cut.slots.some((slot) => slot.slotId === id))) return null;
      return { ...cut, order: [...order] };
    }
    case "voice": return { ...cut, voiceRef: change[side].mediaRef ?? undefined, voiceDurationMs: change[side].durationMs };
    case "still": return cut.slots.some((slot) => slot.slotId === change.slotId) ? { ...cut, stillRefs: { ...cut.stillRefs, [change.slotId]: change[side].mediaRef } } : null;
    default: { const exhaustive: never = change; return exhaustive; }
  }
}
function updated(document: ChangesDocument, change: ChangeItem, cut = document.currentCut): ChangesDocument {
  return { ...document, revision: document.revision + 1, currentCut: cut, changes: document.changes.map((item) => item.id === change.id ? change : item) };
}
export function transitionChange(document: ChangesDocument, n: number, action: ChangeAction, options: TransitionOptions = {}): ChangesDocument {
  const selected = document.changes.find((item) => item.n === n);
  if (!selected) return document;
  let change: ChangeItem = selected;
  if (options.expectedRevision !== undefined && options.expectedRevision !== document.revision) return updated(document, { ...change, state: "out_of_date" });
  if (action === "reject" || action === "dismiss") {
    return change.state === "accepted" || change.state === "rejected" ? document : updated(document, { ...change, state: "rejected" });
  }
  if (action === "undo") return change.state === "rejected" ? updated(document, { ...change, state: isPaidChange(change) && !change.taken ? "awaiting_approval" : change.taken ? "ready" : "proposed" }) : document;
  if (action === "recheck") return change.state === "out_of_date" && matches(document.currentCut, change, "beforeRef") ? updated(document, { ...change, state: change.taken ? "ready" : isPaidChange(change) ? "awaiting_approval" : "proposed" }) : document;
  const reverting = action === "revert";
  const choosingTake = action === "accept" && change.kind === "take" && options.takeId !== undefined;
  if (choosingTake && !document.takes.some((take) => take.id === options.takeId && take.slotId === change.slotId)) return document;
  if (choosingTake && change.state === "accepted" && change.afterRef.kind === "take" && change.afterRef.takeId === options.takeId) return document;
  const allowed = choosingTake ? [...REVIEW_STATES, "accepted", "rejected", "reverted"] : REVIEW_STATES;
  if (reverting ? change.state !== "accepted" : action === "reapply" ? change.state !== "reverted" : !allowed.includes(change.state)) return document;
  if (!reverting && isPaidChange(change) && !change.taken) return document;
  const candidateId = !reverting && change.kind === "take" ? options.takeId ?? change.afterRef.takeId : undefined;
  if (candidateId && document.changes.some((item) => item.kind === "take" && item.afterRef.takeId === candidateId && isPaidChange(item) && !item.taken)) return document;
  if (!matches(document.currentCut, change, reverting || choosingTake && change.state === "accepted" ? "afterRef" : "beforeRef")) return updated(document, { ...change, state: "out_of_date" });
  if (!reverting && options.takeId !== undefined) {
    if (change.kind !== "take" || !document.takes.some((take) => take.id === options.takeId && take.slotId === change.slotId)) return document;
    change = { ...change, afterRef: { kind: "take", takeId: options.takeId } };
  }
  const cut = apply(document.currentCut, document, change, reverting ? "beforeRef" : "afterRef");
  return cut ? updated(document, { ...change, state: reverting ? "reverted" : "accepted" }, cut) : options.takeId !== undefined ? document : updated(document, { ...selected, state: "out_of_date" });
}
export function withChangesCut(document: ChangesDocument): Cut {
  return document.changes.reduce((cut, change) => REVIEW_STATES.includes(change.state) && (!isPaidChange(change) || change.taken) && matches(cut, change, "beforeRef") ? apply(cut, document, change, "afterRef") ?? cut : cut, document.currentCut);
}
export function acceptFreeChanges(document: ChangesDocument): ChangesDocument {
  return freeChanges(document).reduce((next, change) => transitionChange(next, change.n, "accept"), document);
}
export function rejectAllChanges(document: ChangesDocument): ChangesDocument {
  return document.changes.filter((change) => !["accepted", "rejected", "reverted"].includes(change.state)).reduce((next, change) => transitionChange(next, change.n, "reject"), document);
}
export function restoreCheckpoint(document: ChangesDocument, options: { id?: string; createdAt?: number } = {}): ChangesDocument {
  const versions = [...document.versions];
  const previous = structuredClone(document.currentCut);
  if (!versions.some((version) => version.id === previous.id && JSON.stringify(version) === JSON.stringify(previous))) {
    const originalId = previous.id;
    let suffix = document.revision + 1;
    while (versions.some((version) => version.id === previous.id)) previous.id = `${originalId}-saved-${suffix++}`;
    versions.push(previous);
  }
  const requestedId = options.id ?? `${document.checkpointCut.id}-restored-${document.revision + 1}`;
  let id = requestedId;
  let suffix = document.revision + 1;
  while (versions.some((version) => version.id === id)) id = `${requestedId}-${suffix++}`;
  const cut: Cut = structuredClone({ ...document.checkpointCut, id, label: "Restored checkpoint", createdAt: options.createdAt ?? Date.now() });
  return { ...document, revision: document.revision + 1, currentCut: cut, versions: [...versions, cut], changes: document.changes.map((change) => change.state === "accepted" ? { ...change, state: "reverted" } : change) };
}
export function trimVoiceToFit(document: ChangesDocument, cut: Cut = document.currentCut): ChangesDocument {
  const duration = cutDurationMs(cut);
  if (![cutDurationMs(document.currentCut), cutDurationMs(withChangesCut(document))].includes(duration)) return document;
  if (!document.currentCut.voiceRef || (document.currentCut.voiceDurationMs ?? 0) <= duration) return document;
  return { ...document, revision: document.revision + 1, currentCut: { ...document.currentCut, voiceDurationMs: duration } };
}
export function editChangesCut(document: ChangesDocument, cut: Cut): ChangesDocument {
  const parsed = parseCut(cut);
  if (!parsed || parsed.slots.some((slot) => !document.takes.some((take) => take.id === slot.takeId && take.slotId === slot.slotId && take.durationMs >= slot.outMs))) return document;
  if (parsed.slots.some((slot) => !document.currentCut.slots.some((current) => current.slotId === slot.slotId && current.takeId === slot.takeId))) return document;
  const currentStills = document.currentCut.stillRefs ?? {};
  const nextStills = parsed.stillRefs ?? {};
  if ((parsed.voiceRef ?? null) !== (document.currentCut.voiceRef ?? null) || (parsed.voiceDurationMs ?? 0) !== (document.currentCut.voiceDurationMs ?? 0) || Object.keys(nextStills).length !== Object.keys(currentStills).length || Object.entries(nextStills).some(([id, ref]) => currentStills[id] !== ref)) return document;
  const nextCut = { ...parsed, id: `${document.currentCut.id}-edit-${document.revision + 1}`, createdAt: Date.now() };
  return { ...document, revision: document.revision + 1, currentCut: nextCut, versions: [...document.versions, nextCut], changes: document.changes.map((change) => REVIEW_STATES.includes(change.state) && !matches(nextCut, change, "beforeRef") ? { ...change, state: "out_of_date" } : change) };
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? Object.fromEntries(Object.entries(value)) : null;
}
function text(value: unknown): string | undefined { return typeof value === "string" && value.trim() ? value.trim() : undefined; }
function nonnegative(value: unknown): value is number { return typeof value === "number" && Number.isSafeInteger(value) && value >= 0; }
function positive(value: unknown): value is number { return nonnegative(value) && value > 0; }
function strings(value: unknown): string[] | null { return Array.isArray(value) && value.every((item: unknown) => typeof item === "string" && item.trim()) ? value.map((item: string) => item.trim()) : null; }
function media(value: unknown): string | undefined {
  const item = text(value);
  return item && !/^(?:javascript|data|blob):/i.test(item) && !/^\/\//.test(item) ? item : undefined;
}
function billingLines(value: unknown): BillingLine[] | null {
  if (!Array.isArray(value)) return null;
  const lines = parseLines(value);
  return lines.length === value.length ? lines.map((line) => ({ ...line, label: safeChangeCopy(line.label, line.kind === "orchestration" ? "Agent orchestration" : "Media"), detail: safeChangeCopy(line.detail, "") || undefined })) : null;
}
function parseApproval(value: unknown): ApprovalCardModel | undefined {
  const item = record(value);
  if (!item) return undefined;
  const payload = record(item.paused_cap) ?? record(item.receipt) ?? record(item.billing) ?? (item.estimate_cents !== undefined ? item : null);
  if (payload) {
    const settled = payload.type === "paused_cap" || payload.type === "receipt";
    if ((!settled && !isCents(payload.estimate_cents)) || (payload.estimate_cents !== undefined && !isCents(payload.estimate_cents)) || !isCents(payload.cap_cents) || !billingLines(payload.lines)) return undefined;
    const id = text(item.id) ?? text(payload.call_id);
    if (!id) return undefined;
    if (settled) return parseApproval(toApprovalCardModel({ id, title: safeChangeCopy(item.title, "Paid step"), estimateCents: isCents(item.estimateCents) ? item.estimateCents : undefined, estimateIncomplete: payload.estimate_cents === undefined && !isCents(item.estimateCents) }, payload));
    const model = approvalCardModel({ callId: id, toolName: "", label: safeChangeCopy(item.title ?? payload.label, "Paid step"), arguments: record(payload.arguments) ?? {}, billing: payload });
    return model ? parseApproval(model) : undefined;
  }
  if (!text(item.id) || !isCents(item.estimateCents) || !isCents(item.capCents)) return undefined;
  const lines = billingLines(item.lines);
  const specs = strings(item.specs);
  const status = item.status;
  if (!lines || !specs || (status !== "pending" && status !== "approved" && status !== "running" && status !== "done" && status !== "failed" && status !== "paused_cap")) return undefined;
  const result: ApprovalCardModel = { id: String(item.id), title: safeChangeCopy(item.title, "Paid step"), status, estimateCents: item.estimateCents, capCents: item.capCents, lines, specs: specs.map((spec) => safeChangeCopy(spec, "")).filter(Boolean) };
  for (const key of ["tier", "prompt", "approvedAtLabel", "elapsedLabel", "failureTitle", "failureMessage", "message"] satisfies Array<keyof ApprovalCardModel>) {
    const clean = safeChangeCopy(item[key], "");
    if (clean) Object.assign(result, { [key]: clean });
  }
  for (const key of ["balanceCents", "balanceAfterEstimateCents", "balanceAfterCapCents", "heldCents", "spentSoFarCents", "chargedCents", "actualCents", "balanceBeforeCents", "balanceAfterCents", "walletTotalCents", "stepIndex", "stepCount"] satisfies Array<keyof ApprovalCardModel>) if (isCents(item[key])) Object.assign(result, { [key]: item[key] });
  result.raiseOptionsCents = Array.isArray(item.raiseOptionsCents) ? item.raiseOptionsCents.filter(isCents) : [];
  result.lowerCapOptionCents = isCents(item.lowerCapOptionCents) ? item.lowerCapOptionCents : null;
  result.estimateIncomplete = item.estimateIncomplete === true;
  result.approveEnabled = item.approveEnabled !== false;
  result.thumbUrl = media(item.thumbUrl);
  result.resultThumbUrl = media(item.resultThumbUrl);
  return result;
}
export function changeApprovalModel(change: ChangeItem): ApprovalCardModel | null { return change.approval ?? null; }
function parseTake(value: unknown): Take | null {
  const item = record(value);
  if (!item || !text(item.id) || !text(item.slotId) || !positive(item.n) || !media(item.mediaRef) || !positive(item.durationMs) || !isCents(item.costCents) || !nonnegative(item.createdAt) || (item.mediaKind !== "video" && item.mediaKind !== "still")) return null;
  return { id: String(item.id), slotId: String(item.slotId), n: item.n, mediaRef: String(item.mediaRef), mediaKind: item.mediaKind, durationMs: item.durationMs, costCents: item.costCents, createdAt: item.createdAt, posterUrl: media(item.posterUrl), parentTakeId: text(item.parentTakeId), width: positive(item.width) ? item.width : undefined, height: positive(item.height) ? item.height : undefined, reviewState: item.reviewState === "kept" || item.reviewState === "rejected" ? item.reviewState : undefined };
}
export function parseCut(value: unknown): Cut | null {
  const item = record(value);
  const order = strings(item?.order);
  if (!item || !text(item.id) || !nonnegative(item.createdAt) || !Array.isArray(item.slots) || !order || new Set(order).size !== order.length) return null;
  const slots: CutSlot[] = [];
  for (const raw of item.slots) {
    const slot = record(raw);
    if (!slot || !text(slot.slotId) || !text(slot.takeId) || !nonnegative(slot.inMs) || !nonnegative(slot.outMs) || slot.outMs - slot.inMs < 500) return null;
    slots.push({ slotId: String(slot.slotId), takeId: String(slot.takeId), inMs: slot.inMs, outMs: slot.outMs, title: safeChangeCopy(slot.title, "") || undefined });
  }
  if (slots.length !== order.length || new Set(slots.map((slot) => slot.slotId)).size !== slots.length || order.some((id) => !slots.some((slot) => slot.slotId === id))) return null;
  const stills = record(item.stillRefs);
  if (item.stillRefs !== undefined && (!stills || Object.values(stills).some((ref) => ref !== null && !media(ref)))) return null;
  if (item.voiceRef !== undefined && item.voiceRef !== null && !media(item.voiceRef)) return null;
  if (item.voiceDurationMs !== undefined && !nonnegative(item.voiceDurationMs)) return null;
  return { id: String(item.id), label: safeChangeCopy(item.label, "Cut"), createdAt: item.createdAt, slots, order, voiceRef: media(item.voiceRef), voiceDurationMs: nonnegative(item.voiceDurationMs) ? item.voiceDurationMs : undefined, stillRefs: stills ? Object.fromEntries(Object.entries(stills).map(([id, ref]) => [id, media(ref) ?? null])) : undefined };
}
function parseRef(value: unknown): TakeRef | TrimRef | OrderRef | VoiceRef | StillRef | null {
  const item = record(value);
  if (!item) return null;
  switch (item.kind) {
    case "take": return text(item.takeId) ? { kind: "take", takeId: String(item.takeId) } : null;
    case "trim": return nonnegative(item.inMs) && nonnegative(item.outMs) ? { kind: "trim", inMs: item.inMs, outMs: item.outMs } : null;
    case "reorder": { const order = strings(item.order); return order ? { kind: "reorder", order } : null; }
    case "voice": return (item.mediaRef === null || media(item.mediaRef)) && nonnegative(item.durationMs) ? { kind: "voice", mediaRef: media(item.mediaRef) ?? null, durationMs: item.durationMs } : null;
    case "still": { const ids = strings(item.dependentSlotIds); return (item.mediaRef === null || media(item.mediaRef)) && ids ? { kind: "still", mediaRef: media(item.mediaRef) ?? null, dependentSlotIds: ids } : null; }
    default: return null;
  }
}
function parseState(value: unknown): ChangeState | null {
  switch (value) {
    case "proposed": case "awaiting_approval": case "running": case "ready": case "accepted": case "rejected": case "reverted": case "out_of_date": case "failed": case "paused_at_cap": return value;
    default: return null;
  }
}
function parseChange(value: unknown): ChangeItem | null {
  const item = record(value);
  const beforeRef = parseRef(item?.beforeRef);
  const afterRef = parseRef(item?.afterRef);
  const state = parseState(item?.state);
  if (!item || !text(item.id) || !text(item.changesetId) || !positive(item.n) || !isCents(item.costCents) || typeof item.taken !== "boolean" || !state || !beforeRef || !afterRef) return null;
  const approval = parseApproval(item.approval);
  if (item.approval !== undefined && !approval) return null;
  const base: ChangeBase = { id: String(item.id), changesetId: String(item.changesetId), n: item.n, title: safeChangeCopy(item.title, `Change ${item.n}`), description: safeChangeCopy(item.description, ""), state, costCents: item.costCents, taken: item.taken, approval, executionId: text(item.executionId), callId: text(item.callId) };
  const slotId = text(item.slotId);
  switch (item.kind) {
    case "take": return slotId && beforeRef.kind === "take" && afterRef.kind === "take" ? { ...base, kind: "take", slotId, beforeRef, afterRef } : null;
    case "trim": return slotId && beforeRef.kind === "trim" && afterRef.kind === "trim" ? { ...base, kind: "trim", slotId, beforeRef, afterRef } : null;
    case "reorder": return beforeRef.kind === "reorder" && afterRef.kind === "reorder" ? { ...base, kind: "reorder", beforeRef, afterRef } : null;
    case "voice": return beforeRef.kind === "voice" && afterRef.kind === "voice" ? { ...base, kind: "voice", beforeRef, afterRef } : null;
    case "still": return slotId && beforeRef.kind === "still" && afterRef.kind === "still" ? { ...base, kind: "still", slotId, beforeRef, afterRef } : null;
    default: return null;
  }
}
export function parseChangesDocument(value: unknown): ChangesDocument | null {
  const item = record(value);
  const set = record(item?.changeset);
  const currentCut = parseCut(item?.currentCut);
  const checkpointCut = parseCut(item?.checkpointCut);
  const lines = billingLines(set?.lines);
  if (!item || !positive(item.revision) || !set || !text(set.id) || !text(set.projectId) || !positive(set.n) || !nonnegative(set.createdAt) || !text(set.checkpointCutId) || !isCents(set.estimateCents) || !isCents(set.capCents) || !isCents(set.actualCents) || !lines || !currentCut || !checkpointCut || !Array.isArray(item.changes) || !Array.isArray(item.takes) || !Array.isArray(item.versions)) return null;
  const status = set.status;
  if (status !== "open" && status !== "running" && status !== "paused_at_cap" && status !== "done") return null;
  const changes = item.changes.map(parseChange);
  const takes = item.takes.map(parseTake);
  const versions = item.versions.map(parseCut);
  if (changes.some((change) => !change) || takes.some((take) => !take) || versions.some((cut) => !cut)) return null;
  const validChanges = changes.filter((change): change is ChangeItem => change !== null);
  const validTakes = takes.filter((take): take is Take => take !== null);
  const validVersions = versions.filter((cut): cut is Cut => cut !== null);
  if (new Set(validChanges.map((change) => change.n)).size !== validChanges.length || new Set(validChanges.map((change) => change.id)).size !== validChanges.length || new Set(validTakes.map((take) => take.id)).size !== validTakes.length || set.checkpointCutId !== checkpointCut.id || validChanges.some((change) => change.changesetId !== set.id)) return null;
  if ([currentCut, checkpointCut, ...validVersions].some((cut) => cut.slots.some((slot) => !validTakes.some((take) => take.id === slot.takeId && take.slotId === slot.slotId && take.durationMs >= slot.outMs)))) return null;
  return { revision: item.revision, changeset: { id: String(set.id), projectId: String(set.projectId), n: set.n, title: safeChangeCopy(set.title, "Changeset"), createdAt: set.createdAt, checkpointCutId: String(set.checkpointCutId), estimateCents: set.estimateCents, capCents: set.capCents, actualCents: set.actualCents, status, lines }, changes: validChanges, takes: validTakes, currentCut, checkpointCut, versions: validVersions, newTakeApproval: parseApproval(item.newTakeApproval) };
}
