/**
 * Fixture payloads in the exact backend shape (feat/orchestration-billing: lines[], estimate_cents,
 * cap_cents, raise_options_cents, balance_*_cents). All figures are example data used by the
 * landing page's example card, the design-shot kit and tests. Real runs never read this file.
 */
import { toApprovalCardModel, type ApprovalCardModel, type RunPayload, type RunReceiptModel } from "./billing";

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
  balanceBeforeCents: 1000, balanceAfterCents: 771, paidSteps: 4, status: "done",
};

/** Spec 4.5 stress cases; explicit examples, never loaded by real runs. */
export const edgeCards = (): Array<{ title: string; model: ApprovalCardModel }> => [
  { title: "Free step", model: { ...pendingCard(), title: "Included finishing pass", estimateCents: 0, capCents: 0, lines: [{ kind: "media", label: "Finishing pass", priceCents: 0, basis: "fixed" }], balanceAfterEstimateCents: 974, balanceAfterCapCents: 974 } },
  { title: "Four-digit total", model: { ...pendingCard(), estimateCents: 124050, capCents: 130000, balanceCents: 150000, balanceAfterEstimateCents: 25950, balanceAfterCapCents: 20000, lines: [{ kind: "media", label: "Production sequence", priceCents: 124000, basis: "fixed" }, { kind: "orchestration", label: "Agent orchestration", priceCents: 50, basis: "estimate" }] } },
  { title: "Long title", model: { ...pendingCard(), title: "A very long product film title with a carefully framed push-in on the handle, matte texture and pale stone counter in warm morning light" } },
  { title: "Three-line prompt", model: { ...pendingCard(), prompt: "Slow push-in on the handle.\nKeep the warm morning light and matte texture.\nNo text; finish on the pale stone counter." } },
  { title: "Balance below cap", model: { ...lowCreditCard(), approveEnabled: false } },
  { title: "Cap reached · zero left", model: { ...pausedCard(), balanceCents: 0, raiseOptionsCents: [] } },
  { title: "Actual above estimate", model: { ...doneCard(), actualCents: 125, underEstimate: false, balanceAfterCents: 849, lines: [{ kind: "media", label: "Video clip", priceCents: 65, basis: "fixed" }, { kind: "orchestration", label: "Agent orchestration", priceCents: 60, basis: "fixed" }] } },
  { title: "Twelve-step plan", model: { ...pendingCard(), stepIndex: 12, stepCount: 12 } },
];
