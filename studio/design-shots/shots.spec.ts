import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { test, expect } from "@playwright/test";
import { LABEL } from "./playwright.config";
import { SCREENS } from "./screens";
import { canvasStyles } from "./canvas-styles";
import { wire, settle, privacyGuard, OUT, THEME } from "./fixture";

for (const screen of SCREENS.filter((entry) => !process.env.SHOT_ONLY || new RegExp(process.env.SHOT_ONLY).test(entry.id))) {
  test(screen.id, async ({ page }, info) => {
    test.skip(!!screen.requiresAuth, "Clerk screens require a publishable key; this kit runs without keys");
    await wire(page, screen);
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const response = await page.goto(screen.url, { waitUntil: "domcontentloaded" });
    expect(response?.status() ?? 200, `${screen.id}: HTTP status`).toBeLessThan(400);
    await settle(page, screen);
    await privacyGuard(page);
    expect(errors.length, `${screen.id}: browser errors`).toBe(0);
    const computedStyles = screen.id === "07-canvas-demo-project" ? await canvasStyles(page, LABEL === "after") : undefined;
    const dir = path.join(OUT, LABEL, screen.theme ?? THEME, info.project.name);
    mkdirSync(dir, { recursive: true });
    await page.screenshot({
      path: path.join(dir, `${screen.id}.png`),
      fullPage: !!screen.fullPage,
      animations: "disabled",
      caret: "hide",
      mask: (screen.mask ?? []).map((selector) => page.locator(selector)),
      maskColor: "#262626",
    });
    const evidence = path.join(OUT, "observations", LABEL, screen.theme ?? THEME);
    mkdirSync(evidence, { recursive: true });
    writeFileSync(path.join(evidence, `${screen.id}.json`), JSON.stringify({ screen: screen.id, url: screen.url, theme: screen.theme ?? THEME, viewport: info.project.use.viewport, pageErrors: errors, computedStyles, evidence: "Mock design capture, not Comet E2E" }, null, 2));
  });
}
