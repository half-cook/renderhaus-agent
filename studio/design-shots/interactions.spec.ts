import { readFile } from "node:fs/promises";
import { test, expect } from "@playwright/test";
import { SCREENS, reachPhoneStep } from "./screens";
import { wire, privacyGuard } from "./fixture";

function screen(id: string) {
  const fixture = SCREENS.find((entry) => entry.id === id);
  if (!fixture) throw new Error(`Missing fixture: ${id}`);
  return fixture;
}

test("approval arrives on its heading and announces estimate and cap", async ({ page }) => {
  const fixture = screen("m04-agent-run");
  await wire(page, fixture); await page.goto(fixture.url);
  const heading = page.locator(".rh-appr h3");
  await expect(heading).toBeFocused();
  await expect(page.getByRole("button", { name: "Approve, estimated $1.31, hard cap $2.00" })).toBeVisible();
  await privacyGuard(page);
});

test("timeline keyboard trims, reorders and removes", async ({ page }) => {
  const fixture = screen("m07-timeline");
  await wire(page, fixture); await page.goto(fixture.url);
  await page.getByRole("option", { name: /Shot 1/ }).click();
  const lane = page.getByRole("listbox");
  await lane.focus(); await page.keyboard.press("ArrowLeft");
  await expect(page.getByLabel("Out", { exact: true })).toHaveValue("0:05.0");
  await expect(page.getByRole("option", { name: /Shot 1/ })).toHaveAttribute("aria-label", /4\.96s/);
  await page.keyboard.press("]");
  await expect(page.getByRole("option").first()).toHaveAttribute("aria-label", /Shot 2/);
  await page.keyboard.press("[");
  await expect(page.getByRole("option").first()).toHaveAttribute("aria-label", /Shot 1/);
  await page.keyboard.press("Backspace");
  await expect(page.getByRole("option")).toHaveCount(1);
  await expect(page.getByRole("option")).toHaveAttribute("aria-label", /Shot 2/);
  await privacyGuard(page);
});

test("the timeline dock keeps canvas controls and panels above its boundary", async ({ page }) => {
  const fixture = screen("m06-canvas-timeline");
  await wire(page, fixture); await page.goto(fixture.url);
  await expect(page.locator(".rh-tl-dock")).toBeVisible();
  await fixture.prepare?.(page);
  const boundary = (await page.locator(".rh-tl-dock").boundingBox())!.y;
  for (const selector of [".tool-rail", ".scene-rail", ".inspector", ".rh-minimap", ".rh-canvas-controls"]) {
    const bounds = await page.locator(selector).boundingBox();
    expect(bounds, selector).not.toBeNull();
    expect(bounds!.y + bounds!.height, selector).toBeLessThanOrEqual(boundary);
  }
  await privacyGuard(page);
});

test("export traps focus, escapes and downloads the actual editable JSON", async ({ page }) => {
  const fixture = screen("m18-export");
  await wire(page, fixture); await page.goto(fixture.url);
  const trigger = page.getByRole("button", { name: "Export", exact: true });
  await trigger.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("heading", { name: "Export your project." })).toBeFocused();
  await expect(dialog.getByText("Rendering isn’t connected yet.")).toBeVisible();
  await page.keyboard.press("Shift+Tab");
  await expect.poll(() => page.evaluate(() => document.activeElement?.closest('[role="dialog"]') != null)).toBe(true);
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused(); await trigger.click();
  await dialog.getByRole("button", { name: "Prepare project JSON" }).click();
  const waiting = page.waitForEvent("download");
  await dialog.getByRole("link", { name: "Download project JSON" }).click();
  const download = await waiting;
  const file = await download.path();
  expect(file).not.toBeNull();
  const project = JSON.parse(await readFile(file!, "utf8"));
  expect(project.projectName).toBe("Matte travel mug");
  expect(project.nodes.filter((node: { data: { kind: string } }) => node.data.kind === "video")).toHaveLength(2);
  expect(project.schemaVersion).toBe(2);
  await privacyGuard(page);
});

test("welcome amount comes from account and dismiss clears the banner", async ({ page }) => {
  const fixture = screen("m12-signup-success");
  await wire(page, { ...fixture, fixtures: { ...fixture.fixtures, "/api/studio/account": { balance_cents: 1234, beta_credit: { granted_cents: 1234, remaining_cents: 1234, spent_cents: 0 }, recent_ledger: [] } } });
  await page.goto(fixture.url);
  await expect(page.getByText("You’re in. $12.34 beta credit added.")).toBeVisible();
  await page.getByRole("button", { name: "Dismiss welcome" }).click();
  await expect(page.locator(".rh-welcome")).toHaveCount(0);
  expect(new URL(page.url()).searchParams.has("welcome")).toBe(false);
  await privacyGuard(page);
});

test("verified signup opens the server-created demo project", async ({ page }) => {
  const fixture = screen("m08-demo-project");
  await wire(page, fixture); await page.goto("/beta");
  await reachPhoneStep(page);
  for (const [index, digit] of [..."424242"].entries()) await page.getByLabel(`Phone code, digit ${index + 1}`).fill(digit);
  await page.getByRole("button", { name: "Verify and open the demo project" }).click();
  await expect(page).toHaveURL(/\/project\/demo-matte-mug\?welcome=1/);
  await expect(page.locator(".rh-welcome")).toBeVisible();
  await expect(page.locator(".rh-shot-card")).toHaveCount(3);
  await privacyGuard(page);
});


test("the existing example film opens and plays its actual local media", async ({ page }) => {
  const fixture = screen("m01-landing");
  await wire(page, fixture); await page.goto(fixture.url);
  await page.getByRole("button", { name: "Play the example film" }).click();
  const film = page.locator(".rh-hero-video");
  await expect.poll(() => film.evaluate((video: HTMLVideoElement) => !video.paused && video.currentTime > 0)).toBe(true);
  const dimensions = await film.evaluate((video: HTMLVideoElement) => ({ width: video.videoWidth, height: video.videoHeight, error: video.error?.message ?? null }));
  expect(dimensions).toEqual({ width: 1706, height: 960, error: null });
  await film.evaluate((video: HTMLVideoElement) => video.pause());
  await privacyGuard(page);
});
