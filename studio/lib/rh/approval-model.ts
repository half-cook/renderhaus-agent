import type { AgentApprovalRequest } from "@/lib/api";
import { isCents } from "./money";
import { parseLines, safeCopy, toApprovalCardModel, type ApprovalCardModel, type ApprovalStatus, type RunPayload } from "./billing";

const STATUSES: ApprovalStatus[] = ["pending", "approved", "running", "done", "failed", "paused_cap"];

function str(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

/** Spec tags come from the step's own arguments (duration, resolution, aspect, count). Never a model or provider. */
export function specsFrom(args: Record<string, unknown>): string[] {
  const specs: string[] = [];
  const duration = args.duration_seconds ?? args.duration;
  if (typeof duration === "number" && Number.isFinite(duration)) specs.push(`${duration} s`);
  for (const key of ["resolution", "aspect_ratio"] as const) {
    const value = str(args[key]);
    if (value && safeCopy(value, "") && /^[0-9a-z:.\-x ]{1,12}$/i.test(value)) specs.push(value);
  }
  return specs;
}

/**
 * The approval item from `execution.approvals[]` as the card renders it. The server sends one flat item:
 * call_id, label, detail, status, estimate_cents, cap_cents, lines[], balance_*, approve_enabled,
 * insufficient_credit, raise_options_cents, estimate_incomplete. Null when no price was sent (no card to show).
 */
export function approvalCardModel(approval: AgentApprovalRequest): ApprovalCardModel | null {
  const item = approval.billing;
  if (!item || !isCents(item.estimate_cents) || !isCents(item.cap_cents)) return null;
  const status = str(item.status);
  if (status === "rejected") return null;
  const card: ApprovalStatus = STATUSES.includes(status as ApprovalStatus) ? (status as ApprovalStatus) : approval.decision === "approve" ? "approved" : "pending";
  const insufficient = record(item.insufficient_credit);
  const args = approval.arguments;
  const payload: RunPayload = {
    ...item,
    // The nested insufficient_credit block is authoritative for the credit state.
    balance_cents: isCents(insufficient?.balance_cents) ? insufficient!.balance_cents : item.balance_cents,
    lower_cap_option_cents: insufficient ? insufficient.lower_cap_option_cents ?? null : null,
    lines: parseLines(item.lines).map((line) => ({ kind: line.kind, label: line.label, detail: line.detail, price_cents: line.priceCents, basis: line.basis })),
  };
  const model = toApprovalCardModel({
    id: approval.callId,
    status: card,
    title: safeCopy(approval.label, "Paid step"),
    tier: safeCopy(item.detail, "") || undefined,
    prompt: typeof args.prompt === "string" ? safeCopy(args.prompt, "") || undefined : undefined,
    specs: specsFrom(args),
    stepIndex: typeof item.step_index === "number" ? item.step_index : undefined,
    stepCount: typeof item.step_count === "number" ? item.step_count : undefined,
    balanceAfterEstimateCents: isCents(item.balance_after_estimate_cents) ? item.balance_after_estimate_cents : undefined,
    balanceAfterCapCents: isCents(item.balance_after_cap_cents) ? item.balance_after_cap_cents : undefined,
    heldCents: isCents(item.held_cents) ? item.held_cents : undefined,
    spentSoFarCents: isCents(item.spent_so_far_cents) ? item.spent_so_far_cents : undefined,
  }, payload);
  model.estimateIncomplete = item.estimate_incomplete === true;
  model.approveEnabled = item.approve_enabled !== false && !insufficient;
  return model;
}

/** Parameters worth showing for "Edit": the step's own arguments minus anything that names a model, provider or machine id. */
export function visibleParameters(args: Record<string, unknown>): Array<[string, string]> {
  const hidden = /^(model|provider|endpoint|tool|tool_name|name|.*_id|.*_url|.*_b64)$/i;
  return Object.entries(args).flatMap(([key, value]): Array<[string, string]> => {
    if (hidden.test(key) || value == null || typeof value === "object") return [];
    if (!safeCopy(key, "")) return [];
    const label = safeCopy(key.replaceAll("_", " "), "");
    if (!label) return [];
    const text = String(value);
    const clean = safeCopy(text, "");
    return clean ? [[label, clean.length > 400 ? `${clean.slice(0, 400)}…` : clean]] : [];
  });
}

export type SpendSummary = { rows: Array<{ label: string; amountCents: number; tone?: "awaiting" }>; totalLabel: string; totalCents: number };

/**
 * "Spend in this task" for the right panel, from the server's own numbers for the newest run that has any:
 * the receipt (actual), the paused-at-cap payload (charged so far) or the waiting approval card (estimate).
 * Rows are the server's lines in order; the total is the server's total. Nothing is added up here.
 */
export function spendSummary(executions: Array<{ createdAt?: number; approvals: AgentApprovalRequest[]; pausedCap?: Record<string, unknown>; receipt?: Record<string, unknown> }>): SpendSummary | null {
  const newest = [...executions].sort((a, b) => (b.createdAt ?? 0) - (a.createdAt ?? 0));
  for (const execution of newest) {
    const receipt = execution.receipt;
    if (receipt && isCents(receipt.actual_cents)) {
      return { rows: parseLines(receipt.lines).map((line) => ({ label: line.detail ? `${line.label} · ${line.detail}` : line.label, amountCents: line.priceCents })), totalLabel: "Total charged", totalCents: receipt.actual_cents };
    }
    const paused = execution.pausedCap;
    if (paused && isCents(paused.charged_cents)) {
      return { rows: parseLines(paused.lines).map((line) => ({ label: line.label, amountCents: line.priceCents })), totalLabel: "Charged · at cap", totalCents: paused.charged_cents };
    }
    const waiting = execution.approvals.map(approvalCardModel).find((model) => model && model.status === "pending");
    if (waiting) {
      return { rows: waiting.lines.map((line) => ({ label: lineText(line), amountCents: line.priceCents })), totalLabel: "Estimated total", totalCents: waiting.estimateCents };
    }
  }
  return null;
}

function lineText(line: { label: string; detail?: string; kind: string; basis: string }): string {
  const base = line.detail ? `${line.label} · ${line.detail}` : line.label;
  return line.kind === "orchestration" && line.basis === "estimate" ? `${base} · est.` : base;
}
