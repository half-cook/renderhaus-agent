import { mkdirSync } from "node:fs";
import path from "node:path";
import { test } from "@playwright/test";
import { SCREENS } from "./screens";
import { wire, settle } from "./fixture";

// Design pass v5 screens: credit label, pricing lock, up-to one number + lower cap, phone low credit, empty Studio.
const OUT = process.env.V5_OUT || "/workspace/share/launch-screens-v5";
const LIVE = ["m02-home", "m03-agent-empty", "m04-agent-run", "m17-low-credit"];
const REVIEW = ["v4-pricing", "v4-up-to", "v4-up-to-over", "v4-approval"];

for (const screen of SCREENS.filter((s) => LIVE.includes(s.id))) {
  test(screen.id, async ({ page }, info) => {
    await wire(page, screen);
    await page.goto(screen.url, { waitUntil: "domcontentloaded" });
    await settle(page, screen);
    await page.waitForTimeout(700); // the phone card scrolls its top into view after 350 ms
    mkdirSync(OUT, { recursive: true });
    await page.screenshot({ path: path.join(OUT, `${info.project.name}-${screen.id}.png`), animations: "disabled", caret: "hide" });
  });
}

for (const id of REVIEW) {
  test(id, async ({ page }, info) => {
    await page.goto(`/launch-review?screen=${id}`, { waitUntil: "networkidle" });
    await page.waitForSelector(".rh-appr", { timeout: 20_000 });
    // Scroll the chat to its end so the whole card, including the "Fits your credit" option, is in frame.
    await page.evaluate(() => document.querySelectorAll(".rh-v4-chat").forEach((el) => { el.scrollTop = el.scrollHeight; }));
    await page.waitForTimeout(400);
    mkdirSync(OUT, { recursive: true });
    await page.screenshot({ path: path.join(OUT, `${info.project.name}-${id}.png`), animations: "disabled", caret: "hide" });
  });
}
