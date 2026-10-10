import type { Page } from "@playwright/test";

/**
 * One entry per screen worth showing. `ready` must be a locator string that is only
 * visible when the screen has finished rendering (never rely on networkidle: the agent
 * dock polls /api/studio/agent/<job> every 1 s).
 *
 * URLs use the real deep links from studio/components/canvas/CanvasShell.tsx:
 *   /canvas?project=<id>&workspace=agent|canvas&task=<conversationId>
 * DEMO_PROJECT / DEMO_TASK come from the fixture set (see fixtures/README.md).
 *
 * Entries marked NEW do not exist on staging yet; their selectors are placeholders that
 * the revamp should satisfy by adding `data-shot="<id>-ready"` to the screen root.
 */
export const DEMO_PROJECT = process.env.SHOT_PROJECT ?? "demo-project";
export const DEMO_TASK = process.env.SHOT_TASK ?? "demo-task";

export type Screen = {
  id: string;
  url: string;
  ready: string;
  prepare?: (page: Page) => Promise<void>;
  /** CSS selectors to blank out (avatars, anything time-varying). */
  mask?: string[];
  fullPage?: boolean;
  /** true = screen does not exist on staging; "before" capture is skipped automatically. */
  isNew?: boolean;
  requiresAuth?: boolean;
  /** Per-screen API fixture overrides, keyed by pathname (GET only). */
  fixtures?: Record<string, unknown>;
};

export const SCREENS: Screen[] = [
  { id: "01-landing", url: "/", ready: "main", fullPage: true },
  { id: "02-sign-in", url: "/sign-in", ready: ".cl-card, [data-shot='sign-in-ready']", requiresAuth: true },
  { id: "03-home-projects-balance", url: "/home", ready: "main, [data-shot='home-ready']" },
  {
    id: "04-balance-popover",
    url: `/canvas?project=${DEMO_PROJECT}&workspace=canvas`,
    ready: ".react-flow__node",
    prepare: async (p) => {
      await p.getByRole("button", { name: /\$\d|balance|credit/i }).first().click();
      await p.getByRole("menu", { name: "Billing" }).waitFor();
      await p.getByRole("button", { name: /Demo credits/ }).waitFor();
    },
  },
  { id: "05-chat-first", url: `/canvas?project=${DEMO_PROJECT}&workspace=agent&task=${DEMO_TASK}`, ready: ".agent-dock" },
  {
    id: "06-approval-card",
    url: `/canvas?project=${DEMO_PROJECT}&workspace=agent&task=${DEMO_TASK}`,
    ready: ".agent-approval, [data-shot='approval-ready']",
  },
  { id: "07-canvas-demo-project", url: `/canvas?project=${DEMO_PROJECT}&workspace=canvas`, ready: ".react-flow__node" },
  {
    id: "08-canvas-node-selected",
    url: `/canvas?project=${DEMO_PROJECT}&workspace=canvas`,
    ready: ".react-flow__node",
    prepare: async (p) => {
      await p.locator(".react-flow__node").first().click();
    },
  },
  { id: "09-agent-review-timeline-diff", url: `/canvas?project=${DEMO_PROJECT}&workspace=agent&task=${DEMO_TASK}`, ready: "[aria-label='Agent review']" },
  { id: "12-export-download", url: `/canvas?project=${DEMO_PROJECT}&workspace=agent&task=${DEMO_TASK}`, ready: "[data-shot='export-ready'], .agent-artifacts", isNew: false },
];

SCREENS.push({ id: "13-sign-up", url: "/sign-up", ready: ".cl-card", requiresAuth: true });

// ---- Revamp screens, numbered after the designer's mockups (m01 .. m17) -------------------------------------
const wave = (remaining: number, status: "open" | "full" = "open") => ({
  "/api/beta/wave": { capacity: 50, claimed: 50 - remaining, remaining, held: 0, status, wave: 1, hold_seconds: 900, updated_at: 1791848520 },
});

import { MUG, MUG_TASK, lowAccount, lowRun, midRun, mugCanvas, mugProjects, mugTasks, mugTools, pausedRun, receiptRun } from "./rh-fixtures";

const mug = (extra: Record<string, unknown> = {}) => ({
  "/api/studio/projects": mugProjects,
  [`/api/studio/projects/${MUG}/canvas`]: mugCanvas,
  [`/api/studio/projects/${MUG}/agent-conversations`]: mugTasks,
  "/api/studio/projects/spring-launch/agent-conversations": { items: [] },
  "/api/studio/projects/untitled-1/agent-conversations": { items: [] },
  "/api/studio/tools": mugTools,
  ...extra,
});
const agentUrl = `/canvas?project=${MUG}&workspace=agent&task=${MUG_TASK}`;
const account = (balance: number, spent: number) => ({
  "/api/studio/account": { balance_cents: balance, display_name: "Satya", beta_credit: { granted_cents: 1000, remaining_cents: balance, spent_cents: spent }, recent_ledger: [], subscription: null },
});

const homeProjects = {
  "/api/studio/projects": { items: [
    { id: "demo-matte-mug", name: "Matte travel mug", created_at: 1791848000, updated_at: 1791848400 },
    { id: "spring-launch", name: "Spring launch ads", file_count: 3, thumbs: ["/beta/shot-macro.jpg", "/beta/shot-lift.jpg", "/beta/shot-window.jpg"], created_at: 1791600000, updated_at: 1791670000 },
    { id: "untitled-1", name: "Untitled", created_at: 1791848100, updated_at: 1791848100 },
  ] },
};

/** Drives the real sign-up UI against the mocked dry-run verification endpoints. */
export async function reachPhoneStep(page: Page) {
  await page.getByLabel("Email", { exact: true }).fill("you@example.com");
  await page.getByRole("button", { name: "Send code" }).click();
  await page.getByLabel("Email code").fill("beta-email-ok");
  await page.getByRole("button", { name: "Verify email" }).click();
  await page.getByLabel("Phone, with country code").fill("+14165550123");
  await page.getByRole("button", { name: "Send code" }).click();
  await page.getByLabel("Phone code, digit 1").waitFor();
}
async function typeCode(page: Page, digits: string) {
  for (const [index, digit] of [...digits].entries()) await page.getByLabel(`Phone code, digit ${index + 1}`).fill(digit);
}

SCREENS.push(
  { id: "m01-landing", url: "/", ready: "[data-shot='landing-ready']", fullPage: true },
  { id: "m01-landing-fold", url: "/", ready: "[data-shot='landing-ready']" },
  { id: "m09-signup-open", url: "/beta", ready: "[data-shot='claim-form']", prepare: async (p) => { await reachPhoneStep(p); await typeCode(p, "4829"); } },
  { id: "m10-signup-spots-left", url: "/beta", ready: "[data-shot='wave-spots-left']", fixtures: wave(6) },
  { id: "m11-signup-full", url: "/beta", ready: "[data-shot='wave-full']", fixtures: wave(0, "full") },
  { id: "m14-signup-code-error", url: "/beta", ready: "[data-shot='claim-form']", prepare: async (p) => {
    await reachPhoneStep(p); await typeCode(p, "111111");
    await p.getByRole("button", { name: "Verify and open the demo project" }).click();
    await p.getByRole("alert").filter({ hasText: "didn’t match" }).waitFor();
  } },
  { id: "m02-home", url: "/home", ready: "[data-shot='home-ready'] .rh-pgrid", fixtures: homeProjects },
  { id: "m03-agent-empty", url: agentUrl, ready: ".rh-starters", fixtures: mug({ "/api/studio/agent": { items: [] }, ...account(1000, 0) }) },
  { id: "m04-agent-run", url: agentUrl, ready: "[data-shot='approval-ready']", fixtures: mug({ "/api/studio/agent": midRun, ...account(974, 26) }) },
  { id: "m15-run-receipt", url: agentUrl, ready: ".rh-receipt", fixtures: mug({ "/api/studio/agent": receiptRun, ...account(771, 229) }) },
  { id: "m16-cap-reached", url: agentUrl, ready: ".rh-appr[data-state='paused_cap']", fixtures: mug({ "/api/studio/agent": pausedRun, ...account(824, 176) }) },
  { id: "m17-low-credit", url: agentUrl, ready: ".rh-appr[data-credit='lower_cap']", fixtures: mug({ "/api/studio/agent": lowRun, "/api/studio/account": lowAccount }) },
  { id: "m06-canvas-timeline", url: `/canvas?project=${MUG}&workspace=canvas&dock=timeline`, ready: ".rh-tl-clip", fixtures: mug({ "/api/studio/agent": { items: [] }, ...account(974, 26) }),
    prepare: async (p) => { await p.locator(".react-flow__node").filter({ hasText: "Shot 1 · push-in" }).click(); await p.getByRole("option", { name: /Shot 1/ }).click(); } },
  { id: "m07-timeline", url: `/canvas?project=${MUG}&workspace=timeline`, ready: "[data-shot='timeline-ready'] .rh-tl-clip", fixtures: mug({ "/api/studio/agent": { items: [] }, ...account(974, 26) }) },
);

SCREENS.push({ id: "m05-approval-states", url: "/design/approval-states", ready: "[data-shot='approval-states-ready']", fullPage: true });
