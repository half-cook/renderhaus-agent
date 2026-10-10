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
);
