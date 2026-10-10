import type { AgentApprovalRequest } from "@/lib/api";
import { toApprovalCardModel, type ApprovalCardModel, type ApprovalStatus } from "./billing";
import { safeCopy } from "./billing";

const STATUSES: ApprovalStatus[] = ["pending", "approved", "running", "done", "failed", "paused_cap"];

function str(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function safeUrl(value: unknown): string | undefined {
  const url = str(value);
  return url && (url.startsWith("/") && !url.startsWith("//") || url.startsWith("https://")) ? url : undefined;
}

/** Spec tags come from the step's own arguments (duration, resolution, aspect, count). Never a model or provider. */
function specsFrom(args: Record<string, unknown>): string[] {
  const specs: string[] = [];
  const duration = args.duration_seconds ?? args.duration;
  if (typeof duration === "number" && Number.isFinite(duration)) specs.push(`${duration} s`);
  for (const key of ["resolution", "aspect_ratio"] as const) {
    const value = str(args[key]);
    if (value && /^[0-9a-z:.\-x ]{1,12}$/i.test(value)) specs.push(value);
  }
  const count = args.num_outputs ?? args.count;
  specs.push(typeof count === "number" && count > 0 ? `${count} ${count === 1 ? "clip" : "clips"}` : "1 clip");
  return specs;
}

/** The approval request as the card renders it, or null when the server sent no price (then there is no card to show). */
export function approvalCardModel(approval: AgentApprovalRequest): ApprovalCardModel | null {
  const billing = approval.billing;
  if (!billing || typeof billing.estimate_cents !== "number") return null;
  const requested = billing.status;
  const status: ApprovalStatus = STATUSES.includes(requested as ApprovalStatus)
    ? (requested as ApprovalStatus)
    : approval.decision === "approve" ? "approved" : "pending";
  const args = approval.arguments;
  const model = toApprovalCardModel({
    id: approval.callId,
    status,
    title: safeCopy(approval.label, "Paid step"),
    tier: safeCopy(billing.tier, "") || undefined,
    prompt: typeof args.prompt === "string" ? safeCopy(args.prompt, "") || undefined : undefined,
    specs: Array.isArray(billing.specs) ? (billing.specs as unknown[]).filter((value): value is string => typeof value === "string").slice(0, 5) : specsFrom(args),
    thumbUrl: safeUrl(billing.thumb_url),
    stepIndex: typeof billing.step_index === "number" ? billing.step_index : undefined,
    stepCount: typeof billing.step_count === "number" ? billing.step_count : undefined,
    balanceAfterEstimateCents: typeof billing.balance_after_estimate_cents === "number" ? billing.balance_after_estimate_cents : undefined,
    balanceAfterCapCents: typeof billing.balance_after_cap_cents === "number" ? billing.balance_after_cap_cents : undefined,
    approvedAtLabel: str(billing.approved_at_label),
    elapsedLabel: str(billing.elapsed_label),
    walletTotalCents: typeof billing.wallet_total_cents === "number" ? billing.wallet_total_cents : undefined,
    spentSoFarCents: typeof billing.spent_so_far_cents === "number" ? billing.spent_so_far_cents : undefined,
  }, billing);
  return model;
}
