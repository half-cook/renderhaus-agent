/**
 * Typed adapter for run-level billing payloads (approval card, paused at cap, insufficient credit,
 * receipt). The shapes mirror the backend branch `feat/orchestration-billing` (server/run_budget.py)
 * so it wires to the real payload when that branch merges. The client only ever receives one
 * fee-inclusive price per line: there is no fee, provider or model field anywhere in these types.
 * Nothing here computes a price; it validates, normalises and maps work labels.
 */
import { isCents } from "./money";

export type BillingLineKind = "media" | "orchestration";
export type BillingLine = {
  kind: BillingLineKind;
  label: string;
  detail?: string;
  priceCents: number;
  basis: "fixed" | "estimate";
};

export type ApprovalStatus = "pending" | "approved" | "running" | "done" | "failed" | "paused_cap";

export type ApprovalCardModel = {
  id: string;
  status: ApprovalStatus;
  title: string;
  tier?: string;
  prompt?: string;
  specs: string[];
  thumbUrl?: string;
  resultThumbUrl?: string;
  stepIndex?: number;
  stepCount?: number;
  lines: BillingLine[];
  estimateCents: number;
  capCents: number;
  /** Credit available now. Drives the low-credit state (cap must be <= balance). */
  balanceCents?: number;
  balanceAfterEstimateCents?: number;
  balanceAfterCapCents?: number;
  /** Running / paused */
  heldCents?: number;
  spentSoFarCents?: number;
  chargedCents?: number;
  raiseOptionsCents?: number[];
  lowerCapOptionCents?: number | null;
  /** Done */
  actualCents?: number;
  balanceBeforeCents?: number;
  balanceAfterCents?: number;
  walletTotalCents?: number;
  underEstimate?: boolean;
  approvedAtLabel?: string;
  elapsedLabel?: string;
  failureTitle?: string;
  failureMessage?: string;
  message?: string;
  /** The server could not price a step: shown at $0.00 and flagged, never treated as free. */
  estimateIncomplete?: boolean;
  approveEnabled?: boolean;
};

const VENDOR_OR_FEE = /\b(wan|gpt|openai|eleven\s?labs|seedance|seedream|sonnet|opus|haiku|claude|anthropic|remotion|fal|kling|runway|luma|vidu|heygen|topaz|mureka|mirelo|ideogram|recraft|gemini|byteplus|dashscope|hyperframes|fee|markup|margin)\b|\d\s?%/i;

/** Work labels for tool ids; the generic fallback never exposes an id. */
const WORK_LABELS: Array<[RegExp, string]> = [
  [/(image|still|t2i|edit_image)/i, "Product image"],
  [/(voice|tts|speech|narrat)/i, "Voiceover"],
  [/(music|song|audio_gen)/i, "Music"],
  [/(lipsync|avatar)/i, "Talking shot"],
  [/(upscale|interpolate|finish)/i, "Finishing pass"],
  [/(render|assemble|export|remotion)/i, "Assemble film"],
  [/(video|i2v|t2v|r2v|clip|extend)/i, "Video clip"],
];
export function workLabel(toolName: string | undefined): string {
  const id = toolName || "";
  return WORK_LABELS.find(([pattern]) => pattern.test(id))?.[1] ?? "Media step";
}

/** Strips anything that could name a vendor or the platform margin from a client-bound string. */
export function safeCopy(value: unknown, fallback: string): string {
  if (typeof value !== "string" || !value.trim()) return fallback;
  return VENDOR_OR_FEE.test(value) ? fallback : value.trim();
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

export function parseLines(value: unknown): BillingLine[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((raw): BillingLine[] => {
    const item = record(raw);
    const cents = item.price_cents ?? item.priceCents;
    if (!isCents(cents)) return [];
    const kind: BillingLineKind = item.kind === "orchestration" ? "orchestration" : "media";
    const fallback = kind === "orchestration" ? "Agent orchestration" : "Media step";
    return [{
      kind,
      label: safeCopy(item.label, fallback),
      detail: typeof item.detail === "string" && !VENDOR_OR_FEE.test(item.detail) ? item.detail : undefined,
      priceCents: cents,
      basis: item.basis === "estimate" ? "estimate" : "fixed",
    }];
  });
}

export type RunPayload = Record<string, unknown>;

function optionalCents(value: unknown): number | undefined {
  return isCents(value) ? value : undefined;
}

function centsList(value: unknown): number[] {
  return Array.isArray(value) ? value.filter(isCents) : [];
}

/** Maps the approval request (or paused / receipt / insufficient-credit payload) onto the card model. */
export function toApprovalCardModel(base: Partial<ApprovalCardModel> & { id: string }, payload: RunPayload): ApprovalCardModel {
  const type = payload.type;
  const status = payload.status;
  const lines = parseLines(payload.lines);
  const estimate = optionalCents(payload.estimate_cents) ?? optionalCents(payload.estimated_total_cents) ?? lines.reduce((sum, line) => sum + line.priceCents, 0);
  const cap = optionalCents(payload.cap_cents) ?? optionalCents(payload.hard_cap_cents) ?? estimate;
  const model: ApprovalCardModel = {
    title: "Paid step",
    specs: [],
    ...base,
    status: base.status ?? "pending",
    lines: lines.length ? lines : base.lines ?? [],
    estimateCents: estimate,
    capCents: cap,
    balanceCents: optionalCents(payload.balance_cents) ?? base.balanceCents,
    heldCents: optionalCents(payload.held_cents) ?? base.heldCents,
    chargedCents: optionalCents(payload.charged_cents) ?? base.chargedCents,
    raiseOptionsCents: centsList(payload.raise_options_cents),
    lowerCapOptionCents: isCents(payload.lower_cap_option_cents) ? payload.lower_cap_option_cents : null,
    balanceBeforeCents: optionalCents(payload.balance_before_cents) ?? base.balanceBeforeCents,
    balanceAfterCents: optionalCents(payload.balance_after_cents) ?? base.balanceAfterCents,
    actualCents: optionalCents(payload.actual_cents) ?? base.actualCents,
    underEstimate: typeof payload.under_estimate === "boolean" ? payload.under_estimate : base.underEstimate,
    message: typeof payload.message === "string" && !VENDOR_OR_FEE.test(payload.message) ? payload.message : base.message,
  };
  if (type === "paused_cap" || status === "paused_cap") model.status = "paused_cap";
  else if (type === "receipt") model.status = status === "failed" ? "failed" : "done";
  return model;
}

/** Credit check from the spec: cap must be <= balance. The server also sends approve_enabled=false. */
export function creditState(model: ApprovalCardModel, approveEnabled?: boolean): "ok" | "lower_cap" | "add_credit" {
  if (approveEnabled === false) {
    return model.lowerCapOptionCents != null ? "lower_cap" : "add_credit";
  }
  if (model.balanceCents == null || model.balanceCents >= model.capCents) return "ok";
  return model.balanceCents >= model.estimateCents ? "lower_cap" : "add_credit";
}

export function a11yApproveName(model: ApprovalCardModel, format: (cents: number) => string): string {
  return `Approve, estimated ${format(model.estimateCents)}, hard cap ${format(model.capCents)}`;
}

// ---- Run-level payloads (plan, spend ledger, receipt) ---------------------------------------------------
export type RunReceiptModel = {
  title: string;
  finishedLabel: string;
  lines: BillingLine[];
  actualCents: number;
  estimateCents: number;
  capCents: number;
  underEstimate: boolean;
  balanceBeforeCents: number;
  balanceAfterCents: number;
  paidSteps: number;
  status: "done" | "failed";
};

function text(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

/** Whole-run receipt: type "receipt", scope "run". */
export function toRunReceiptModel(value: unknown): RunReceiptModel | null {
  const receipt = record(value);
  if (receipt.type !== "receipt" || !isCents(receipt.actual_cents) || !isCents(receipt.estimate_cents)) return null;
  const lines = parseLines(receipt.lines);
  return {
    title: safeCopy(receipt.title, "Run receipt"),
    finishedLabel: safeCopy(receipt.finished_label, ""),
    lines,
    actualCents: receipt.actual_cents,
    estimateCents: receipt.estimate_cents,
    capCents: isCents(receipt.cap_cents) ? receipt.cap_cents : receipt.estimate_cents,
    underEstimate: receipt.under_estimate === true,
    balanceBeforeCents: isCents(receipt.balance_before_cents) ? receipt.balance_before_cents : 0,
    balanceAfterCents: isCents(receipt.balance_after_cents) ? receipt.balance_after_cents : 0,
    paidSteps: typeof receipt.paid_steps === "number" ? receipt.paid_steps : lines.filter((line) => line.kind === "media").length,
    status: receipt.status === "failed" ? "failed" : "done",
  };
}

export { text as optionalText };

export type NodeEstimate = { estimateCents: number; capCents: number; lines: BillingLine[] };

/** Validates a node's server-sent estimate payload. Null when the server sent no usable price. */
export function toNodeEstimate(value: unknown): NodeEstimate | null {
  const payload = record(value);
  if (!isCents(payload.estimate_cents)) return null;
  return {
    estimateCents: payload.estimate_cents,
    capCents: isCents(payload.cap_cents) ? payload.cap_cents : payload.estimate_cents,
    lines: parseLines(payload.lines),
  };
}
