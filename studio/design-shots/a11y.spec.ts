import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { LABEL } from "./playwright.config";
import { SCREENS } from "./screens";
import { wire, settle, privacyGuard, OUT, THEME } from "./fixture";

test.skip(!process.env.A11Y, "Use npm run shots:a11y");
for (const screen of SCREENS.filter((screen) => (!process.env.SHOT_ONLY || new RegExp(process.env.SHOT_ONLY).test(screen.id)) && !screen.isNew && !screen.requiresAuth)) {
  test(`a11y ${screen.id}`, async ({ page }) => {
    await wire(page, screen);
    await page.goto(screen.url, { waitUntil: "domcontentloaded" });
    await settle(page, screen);
    await privacyGuard(page);
    const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
    const dir = path.join(OUT, "a11y", LABEL, THEME);
    mkdirSync(dir, { recursive: true });
    writeFileSync(path.join(dir, `${screen.id}.json`), JSON.stringify(result.violations, null, 2));
    const bad = result.violations.filter((violation) => ["serious", "critical"].includes(violation.impact || ""));
    expect(bad.map((violation) => `${violation.id} (${violation.nodes.length})`), `${screen.id}: serious/critical a11y violations`).toEqual([]);
  });
}
