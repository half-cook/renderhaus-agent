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
  { id: "10-beta-signup", url: "/beta", ready: "[data-shot='beta-ready']", isNew: true },
  { id: "11-beta-wave-spots-left", url: "/beta", ready: "[data-shot='wave-spots-left']", isNew: true },
  { id: "12-export-download", url: `/canvas?project=${DEMO_PROJECT}&workspace=agent&task=${DEMO_TASK}`, ready: "[data-shot='export-ready'], .agent-artifacts", isNew: false },
];

SCREENS.push({ id: "13-sign-up", url: "/sign-up", ready: ".cl-card", requiresAuth: true });
