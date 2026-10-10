/**
 * Fixture payloads in the exact backend shape (feat/orchestration-billing: lines[], estimate_cents,
 * cap_cents, raise_options_cents, balance_*_cents). All figures are example data used by the
 * landing page's example card, the design-shot kit and tests. Real runs never read this file.
 */
import { toApprovalCardModel, type ApprovalCardModel, type RunPayload } from "./billing";

const base = {
  id: "fixture-shot-1",
  title: "Shot 1 · push-in on the handle",
  tier: "Studio Video · Standard quality",
  prompt: "Slow push-in on the handle and the matte texture. Soft morning window light, shallow depth of field. No text.",
  specs: ["5 s", "720p", "16:9", "1 clip"],
  thumbUrl: "/beta/still-mug-wide.jpg",
  resultThumbUrl: "/beta/shot-macro.jpg",
  stepIndex: 2,
  stepCount: 4,
} satisfies Partial<ApprovalCardModel> & { id: string };

export const FIXTURE_APPROVAL_PAYLOAD: RunPayload = {
  estimate_cents: 105,
  cap_cents: 150,
  balance_cents: 974,
  lines: [
    { kind: "media", label: "Video clip", detail: "5 s · 720p", price_cents: 65, basis: "fixed" },
    { kind: "orchestration", label: "Agent orchestration", price_cents: 40, basis: "estimate" },
  ],
};

export const pendingCard = (): ApprovalCardModel => ({
  ...toApprovalCardModel({ ...base, status: "pending" }, FIXTURE_APPROVAL_PAYLOAD),
  balanceAfterEstimateCents: 869,
  balanceAfterCapCents: 824,
});

export const approvedCard = (): ApprovalCardModel => ({ ...pendingCard(), status: "approved", approvedAtLabel: "7:41 PM" });

export const runningCard = (): ApprovalCardModel => ({
  ...pendingCard(), status: "running", heldCents: 150, spentSoFarCents: 65, elapsedLabel: "00:42 / ~01:30",
});

export const doneCard = (): ApprovalCardModel => ({
  ...toApprovalCardModel({ ...base, status: "done" }, {
    type: "receipt", status: "done", estimate_cents: 105, cap_cents: 150, actual_cents: 99, under_estimate: true,
    balance_before_cents: 974, balance_after_cents: 875,
    lines: [
      { kind: "media", label: "Video clip", detail: "5 s · 720p", price_cents: 65, basis: "fixed" },
      { kind: "orchestration", label: "Agent orchestration", price_cents: 34, basis: "fixed" },
    ],
  }),
  walletTotalCents: 1000,
});

export const failedCard = (): ApprovalCardModel => ({
  ...pendingCard(), status: "failed", chargedCents: 0,
  failureTitle: "This step timed out after 120 s", failureMessage: "No output was produced. Retrying shows a fresh estimate first.",
});

export const pausedCard = (): ApprovalCardModel => ({
  ...toApprovalCardModel({ ...base, status: "paused_cap" }, {
    type: "paused_cap", status: "paused_cap", charged_cents: 150, cap_cents: 150, held_cents: 150, balance_cents: 824,
    message: "The agent needed more attempts than estimated. Nothing more has been charged, and the step is paused so you decide.",
    raise_options_cents: [200, 250],
    lines: [
      { kind: "media", label: "Video clip", detail: "5 s · 720p", price_cents: 65, basis: "fixed" },
      { kind: "orchestration", label: "Agent orchestration", price_cents: 85, basis: "fixed" },
    ],
  }),
  walletTotalCents: 1000,
});

export const lowCreditCard = (): ApprovalCardModel => ({
  ...toApprovalCardModel({ ...base, status: "pending" }, {
    ...FIXTURE_APPROVAL_PAYLOAD, balance_cents: 120, lower_cap_option_cents: 120,
  }),
});

export type RunReceiptModel = {
  title: string;
  finishedLabel: string;
  lines: ApprovalCardModel["lines"];
  actualCents: number;
  estimateCents: number;
  capCents: number;
  underEstimate: boolean;
  balanceBeforeCents: number;
  balanceAfterCents: number;
  paidSteps: number;
};

export const FIXTURE_RECEIPT: RunReceiptModel = {
  title: "10s product film",
  finishedLabel: "Finished 7:52 PM · 10 s · 16:9 · voiceover",
  lines: [
    { kind: "media", label: "Product still", detail: "image", priceCents: 26, basis: "fixed" },
    { kind: "media", label: "Shot 1", detail: "video clip · 5 s · 720p", priceCents: 65, basis: "fixed" },
    { kind: "media", label: "Shot 2", detail: "video clip · 5 s · 720p", priceCents: 65, basis: "fixed" },
    { kind: "media", label: "Voiceover", detail: "library voice · 24 words", priceCents: 2, basis: "fixed" },
    { kind: "orchestration", label: "Agent orchestration", priceCents: 71, basis: "fixed" },
  ],
  actualCents: 229, estimateCents: 258, capCents: 350, underEstimate: true,
  balanceBeforeCents: 1000, balanceAfterCents: 771, paidSteps: 4,
};
