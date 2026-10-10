import { readFile } from "node:fs/promises";
import { test, expect } from "@playwright/test";
import { SCREENS, reachPhoneStep } from "./screens";
import { wire, privacyGuard } from "./fixture";
import { changesDocument } from "./rh-fixtures";

function screen(id: string) {
  const fixture = SCREENS.find((entry) => entry.id === id);
  if (!fixture) throw new Error(`Missing fixture: ${id}`);
  return fixture;
}

test("a trimmed video loads its first cut frame from an extensionless media URL and plays", async ({ page }) => {
  const fixture = screen("m27-timeline-changes");
  const document = changesDocument();
  for (const cut of [document.currentCut, document.checkpointCut]) cut.slots.find((slot) => slot.slotId === "n-shot2")!.inMs = 1000;
  for (const take of document.takes.filter((take) => take.slotId === "n-shot2")) { take.mediaKind = "video"; take.mediaRef = "/api/studio/assets/design-take/content"; }
  await wire(page, { ...fixture, fixtures: { ...fixture.fixtures, "/api/studio/projects/demo-matte-mug/changesets": { items: [document] } } });
  const media = await readFile(new URL("../public/beta/p1-film.mp4", import.meta.url));
  await page.route("**/api/studio/assets/design-take/content", async (route) => {
    const range = /^bytes=(\d+)-(\d*)$/.exec(route.request().headers().range ?? "");
    const start = range ? Number(range[1]) : 0;
    const end = range?.[2] ? Math.min(Number(range[2]), media.length - 1) : media.length - 1;
    return route.fulfill({ status: range ? 206 : 200, contentType: "video/mp4", headers: { "Accept-Ranges": "bytes", ...(range ? { "Content-Range": `bytes ${start}-${end}/${media.length}` } : {}) }, body: media.subarray(start, end + 1) });
  });
  await page.goto(fixture.url);
  const video = page.locator(".rh-ch-timeline-monitor video");
  await expect(video).toBeVisible();
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => ({
    clock: Math.round(element.currentTime * 10) / 10,
    paused: element.paused,
    error: element.error?.message ?? null,
    frameReady: element.readyState >= 2,
  }))).toEqual({ clock: 1, paused: true, error: null, frameReady: true });
  await expect(page.getByText("Still preview. Playback is not available for this take.")).toHaveCount(0);
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => !element.paused && element.currentTime > 1)).toBe(true);
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await privacyGuard(page);
});

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

test("Changes free bulk excludes paid; badges insert text; decisions reverse; restore confirms", async ({ page }) => {
  const fixture = screen("m24-agent-changes");
  await wire(page, fixture); await page.goto(fixture.url);
  const panel = page.getByRole("region", { name: "Changeset review" });
  const free = panel.locator('[data-change="2"]'); const paid = panel.locator('[data-change="1"]');
  await expect(free.locator('.rh-appr')).toHaveCount(0);
  await free.locator('.rh-change-number').click();
  await expect(page.getByRole("textbox", { name: "Ask the project agent" })).toHaveValue(/change 2/);
  await panel.getByRole("button", { name: "Accept free changes · 1" }).click();
  await expect(free).toHaveAttribute("data-state", "accepted"); await expect(paid).toHaveAttribute("data-state", "ready");
  await expect(panel.getByRole("button", { name: /Accept free changes/ })).toHaveCount(0);
  await free.getByRole("button", { name: "Revert" }).click(); await expect(free).toHaveAttribute("data-state", "reverted");
  await free.getByRole("button", { name: "Re-apply" }).click(); await expect(free).toHaveAttribute("data-state", "accepted");
  await paid.getByRole("button", { name: "Reject", exact: true }).click(); await expect(paid).toContainText("$0.65 kept in Takes");
  await paid.getByRole("button", { name: "Undo" }).click(); await expect(paid).toHaveAttribute("data-state", "ready");
  await panel.getByRole("button", { name: "Restore", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Restore the checkpoint?" })).toBeFocused();
  await page.getByRole("button", { name: "Restore as a new version" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0); await expect(free).toHaveAttribute("data-state", "reverted");
  await privacyGuard(page);
});

test("Compare selects retained takes, switches views, holds before and opens separate price approval", async ({ page }) => {
  const fixture = screen("m25-compare-swipe"); await wire(page, fixture); await page.goto(fixture.url);
  const compare = page.locator('.rh-compare');
  await expect(compare.getByRole("heading").first()).toBeFocused();
  await page.keyboard.press("3"); await expect(compare.getByRole("button", { name: "Accept take 3" })).toBeEnabled();
  await page.keyboard.press("2");
  await compare.getByRole("button", { name: "Side by side", exact: true }).click(); await expect(compare).toHaveAttribute("data-shot", "compare-side-by-side");
  await compare.getByRole("button", { name: "Flicker", exact: true }).click();
  const before = compare.locator('.rh-compare-frame[data-side="before"]');
  const hidden = await before.evaluate((element) => getComputedStyle(element).clipPath);
  await page.keyboard.down("b"); await expect(compare.getByRole("button", { name: "Hold to see before" })).toHaveAttribute("aria-pressed", "true");
  await expect.poll(() => before.evaluate((element) => getComputedStyle(element).clipPath)).not.toBe(hidden);
  await page.keyboard.up("b"); await expect.poll(() => before.evaluate((element) => getComputedStyle(element).clipPath)).toBe(hidden);
  await compare.getByRole("button", { name: /New take/ }).click();
  const dialog = page.getByRole("dialog"); await expect(dialog.getByRole("heading", { name: "Review the price" })).toBeFocused();
  await expect(dialog).toContainText("$1.05"); await expect(dialog).toContainText("$1.50");
  await expect(dialog.getByRole("button", { name: /Approve, estimated/ })).toBeDisabled();
  await page.keyboard.press("Escape");
  await compare.getByRole("button", { name: "Accept take 2" }).click(); await expect(compare.getByRole("button", { name: "Take 2 is in your cut" })).toBeDisabled();
  await privacyGuard(page);
});

test("Timeline flags clear the trim hatch; monitor switches; rejected takes retain price", async ({ page }) => {
  const fixture = screen("m27-timeline-changes"); await wire(page, fixture); await page.goto(fixture.url);
  const timeline = page.locator('.rh-ch-timeline');
  await expect(timeline.getByRole("button", { name: "Change 1, Shot 2, new take, needs you", exact: true })).toBeVisible();
  const l = (await timeline.locator('.rh-ch-timeline-take-label').first().boundingBox())!;
  const h = (await timeline.locator('.rh-ch-timeline-trim').first().boundingBox())!;
  expect(l.y + l.height).toBeLessThanOrEqual(h.y);
  await expect(timeline.getByRole("button", { name: "Take 3, rejected, $0.65 charged" })).toBeVisible();
  await timeline.getByRole("button", { name: "Current cut", exact: true }).click(); await expect(timeline.locator('.rh-ch-timeline-monitor')).toHaveAttribute("data-mode", "current");
  await page.keyboard.press("g"); await expect(timeline.locator('.rh-ch-timeline-monitor')).toHaveAttribute("data-mode", "changes");
  await privacyGuard(page);
});

test("One heavily trimmed shot keeps its take label separate and warns about long voiceover", async ({ page }) => {
  const fixture = screen("m27-one-shot-heavy-trim"); await wire(page, fixture); await page.goto(fixture.url);
  const timeline = page.locator('.rh-ch-timeline');
  const l = (await timeline.locator('.rh-ch-timeline-take-label').boundingBox())!;
  const h = (await timeline.locator('.rh-ch-timeline-trim').boundingBox())!;
  expect(l.y + l.height).toBeLessThanOrEqual(h.y);
  await expect(timeline.getByText("Voiceover is longer than this cut.")).toBeVisible();
  await timeline.getByRole("button", { name: "Keep", exact: true }).click();
  await expect(timeline.getByText(/Kept at its full length/)).toBeVisible();
  await timeline.getByRole("button", { name: "Trim to fit", exact: true }).click();
  await expect(timeline.locator('.rh-ch-timeline-audio-warning')).toHaveCount(0);
  const geometry = await timeline.locator('.rh-tl-strip-cover img').first().evaluate((img) => { const rect = img.getBoundingClientRect(); return { ratio: rect.width / rect.height, fit: getComputedStyle(img).objectFit }; });
  expect(geometry.fit).toBe("cover"); expect(geometry.ratio).toBeCloseTo(16 / 9, 1);
  await privacyGuard(page);
});

test("Twelve changes and zero-free changes retain keyboard navigation and no bulk-paid action", async ({ page }) => {
  let fixture = screen("m24-twelve-changes"); await wire(page, fixture); await page.goto(fixture.url);
  const panel = page.getByRole("region", { name: "Changeset review" });
  await expect(panel.locator('.rh-change-row')).toHaveCount(12);
  await panel.locator('[data-change="1"] .rh-change-number').focus();
  await page.keyboard.press("k"); await expect(panel.locator('[data-change="2"]')).toHaveClass(/rh-change-selected/);
  await page.keyboard.press("a"); await expect(panel.locator('[data-change="2"]')).toHaveAttribute("data-state", "accepted");
  await privacyGuard(page);
  fixture = screen("m24-zero-free-changes"); await wire(page, fixture); await page.goto(fixture.url);
  await expect(panel.getByRole("button", { name: /Accept free changes/ })).toHaveCount(0);
  await privacyGuard(page);
});

test("Failed persistence rolls the optimistic decision back and keeps an explicit error", async ({ page }) => {
  const fixture = screen("m24-agent-changes"); await wire(page, fixture);
  await page.route("**/api/studio/changesets/**/changes/**", (route) => route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: "The cut changed." }) }));
  await page.goto(fixture.url);
  const row = page.getByRole("region", { name: "Changeset review" }).locator('[data-change="2"]');
  await row.getByRole("button", { name: "Accept", exact: true }).click();
  await expect(row).toHaveAttribute("data-state", "proposed"); await expect(page.getByRole("alert").filter({ hasText: "Changes could not be saved" })).toBeVisible();
});

test("Frame notes hand off from Timeline to the normal agent message with a timecode", async ({ page }) => {
  const fixture = screen("m27-timeline-changes"); await wire(page, fixture);
  const sent: Array<Record<string, unknown>> = [];
  await page.route("**/api/studio/agent", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    sent.push(JSON.parse(route.request().postData() || "{}"));
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "completed", message: "Note received", result: { title: "Frame note", summary: "Note received", markdown: "I’ll review the framing before proposing any work.", assets: [], tool_events: [] } }) });
  });
  await page.goto(fixture.url);
  await page.getByRole("button", { name: "Agent", exact: true }).click();
  await page.getByRole("textbox", { name: "Ask the project agent" }).fill("Unsent idea @Shot1");
  await page.getByRole("button", { name: "Timeline", exact: true }).click();
  await page.locator('.rh-ch-timeline-caption').getByRole("button", { name: "Compare", exact: true }).click();
  const compare = page.locator('.rh-compare');
  await compare.getByLabel("Ask about this frame", { exact: true }).fill("Keep the window less blown out");
  await compare.getByRole("button", { name: /Send note about frame/ }).click();
  await expect(page.locator('.rh-agent-workspace')).toBeVisible(); await expect(page.locator('.rh-ch-timeline')).toHaveCount(0);
  await expect.poll(() => sent.length).toBe(1);
  await expect(page.getByRole("textbox", { name: "Ask the project agent" })).toHaveValue("Unsent idea @Shot1");
  expect(sent[0]?.prompt).toMatch(/frame 00:02:10: Keep the window less blown out/); expect(sent[0]?.autonomous).toBe(false); expect(sent[0]?.node_ids).toEqual(["n-shot2"]);
  await privacyGuard(page);
});

test("Changes load failure stays visible and can be retried", async ({ page }) => {
  const fixture = screen("m24-agent-changes"); await wire(page, fixture);
  await page.route("**/projects/**/changesets", (route) => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "Unavailable" }) }));
  await page.goto(fixture.url); await expect(page.getByRole("alert").filter({ hasText: "Changes could not be loaded" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Reload changes" })).toBeVisible();
});

test("A on an untaken paid change only focuses its price heading and cannot approve", async ({ page }) => {
  const fixture = screen("m24-waiting-paid-change"); await wire(page, fixture);
  const mutations: string[] = []; page.on("request", (request) => { if (request.method() === "POST" && !new URL(request.url()).pathname.endsWith("/playback")) mutations.push(new URL(request.url()).pathname); });
  await page.goto(fixture.url);
  const panel = page.getByRole("region", { name: "Changeset review" }); await panel.locator('.rh-change-number').focus(); await page.keyboard.press("a");
  await expect(panel.locator('.rh-appr h3')).toBeFocused();
  await expect(panel).not.toContainText("Not enough credit");
  await expect(panel.getByRole("button", { name: /Approve, estimated/ })).toBeDisabled();
  expect(mutations).toEqual([]); await privacyGuard(page);
});
