import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test, expect } from "@playwright/test";
import { SCREENS } from "./screens";
import { wire, settle } from "./fixture";

const OUT = process.env.LAYOUT_OUT || "/workspace/share/launch-screens-v4";
const IDS = ["m03-agent-empty", "m04-agent-run", "m04-agent-plan-12", "m15-run-receipt", "m16-cap-reached", "m17-low-credit",
  "m07-timeline", "m02-home", "m08-demo-project", "m06-canvas-timeline", "m05-approval-states", "m13-agent-run-light"];
const metrics: Record<string, unknown>[] = [];

for (const screen of SCREENS.filter((s) => IDS.includes(s.id))) {
  test(screen.id, async ({ page }, info) => {
    await wire(page, screen);
    await page.goto(screen.url, { waitUntil: "domcontentloaded" });
    await settle(page, screen);
    const m = await page.evaluate(() => {
      const box = (sel: string) => { const el = document.querySelector(sel); if (!el) return null; const r = el.getBoundingClientRect(); return r.width ? { w: Math.round(r.width), h: Math.round(r.height) } : null; };
      const texts = Array.from(document.querySelectorAll<HTMLElement>(".rh-agent-conversation p, .rh-agent-conversation li, .agent-markdown, .rh-trace-label, .rh-appr dt, .rh-appr dd"))
        .filter((el) => el.offsetParent && !el.matches(".rh-eyebrow") && el.innerText.trim().length > 20);
      const sizes = texts.map((el) => parseFloat(getComputedStyle(el).fontSize));
      const buttons = Array.from(document.querySelectorAll<HTMLElement>(".rh-appr .rh-btn-act")).filter((b) => b.offsetParent).map((b) => Math.round(b.getBoundingClientRect().height));
      return { chat: box(".rh-agent-conversation"), stage: box(".rh-stage-frame"), strip: box(".rh-strip"), minBodyPx: sizes.length ? Math.min(...sizes) : null, buttonHeights: [...new Set(buttons)],
        hScroll: document.documentElement.scrollWidth > window.innerWidth + 1 };
    });
    metrics.push({ screen: screen.id, viewport: info.project.name, ...m });
    if (m.stage) expect(Math.abs(m.stage.w / m.stage.h - 16 / 9)).toBeLessThan(0.02);
    if (m.chat && info.project.name !== "390x844") { expect(m.chat.w).toBeGreaterThanOrEqual(359); expect(m.chat.w).toBeLessThanOrEqual(441); }
    if (m.minBodyPx) expect(m.minBodyPx).toBeGreaterThanOrEqual(12.5);
    expect(m.hScroll).toBe(false);
    mkdirSync(OUT, { recursive: true });
    await page.screenshot({ path: path.join(OUT, `layout-${info.project.name}-${screen.id}.png`), animations: "disabled", caret: "hide" });
  });
}

test.afterAll(async ({}, info) => {
  mkdirSync(OUT, { recursive: true });
  writeFileSync(path.join(OUT, `layout-metrics-${info.project.name}.json`), JSON.stringify(metrics, null, 2));
});
