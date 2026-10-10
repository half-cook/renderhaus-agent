import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, type Page } from "@playwright/test";
import type { Screen } from "./screens";
import { assertCapturePrivacy } from "./privacy.mjs";
import { findCopyLeaks } from "./copy-rules.mjs";

export const HERE = path.dirname(fileURLToPath(import.meta.url));
export const OUT = path.resolve(process.env.SHOT_OUT_DIR || path.join(HERE, "out"));
export const THEME = process.env.SHOT_THEME === "light" ? "light" : "dark";
const FIXED_NOW = new Date("2026-10-12T19:42:00-04:00");
const DATA: Record<string, unknown> = JSON.parse(readFileSync(path.join(HERE, "fixtures/studio.json"), "utf8"));
const ACCOUNT = readFileSync(path.join(HERE, "fixtures/account.json"), "utf8");

/** Mocked beta backends: dry-run verification only, nothing leaves the browser. */
function betaPost(pathname: string, body: Record<string, unknown>): { status: number; json: unknown } | null {
  if (pathname === "/api/beta/verify/email/start") return { status: 200, json: { challenge_id: "fx-email", dry_run: true, message: "Mock verification. No message was sent. Use beta-email-ok." } };
  if (pathname === "/api/beta/verify/email/confirm") return body.token === "beta-email-ok" ? { status: 200, json: { verified: true, message: "Email verified." } } : { status: 400, json: { detail: "Verification could not be confirmed." } };
  if (pathname === "/api/beta/hold") return { status: 200, json: { held: true, claimed: false, expires_at: Math.floor(FIXED_NOW.getTime() / 1000) + 900 - 24, hold_seconds: 900, message: "Your spot is held for 15 minutes." } };
  if (pathname === "/api/beta/verify/phone/start") return { status: 200, json: { challenge_id: "fx-phone", dry_run: true, message: "Mock verification. No message was sent. Use 424242." } };
  if (pathname === "/api/beta/verify/phone/confirm") return body.code === "424242" ? { status: 200, json: { verified: true, message: "Phone verified." } } : { status: 400, json: { detail: "Verification could not be confirmed." } };
  if (pathname === "/api/beta/claim") return { status: 200, json: { balance_cents: 1000, grant: { amount_cents: 1000, wave: 1 }, message: "Your free beta credit is ready." } };
  if (pathname === "/api/beta/waitlist") return { status: 200, json: { message: "You joined the waitlist. No email was sent." } };
  if (pathname === "/api/studio/demo-project") return { status: 200, json: { project_id: "demo-matte-mug", name: "Matte travel mug", copied: true } };
  return null;
}

export async function wire(page: Page, screen?: Screen) {
  const overrides = screen?.fixtures ?? {};
  await page.addInitScript((theme) => {
    localStorage.setItem("renderhaus.studio.theme", theme);
    localStorage.setItem("renderhaus.studio.server-migration.v2", "true");
  }, screen?.theme ?? THEME);
  await page.clock.setFixedTime(FIXED_NOW);
  await page.route("**/api/**", (route) => route.abort("blockedbyclient"));
  const har = path.join(HERE, "fixtures/studio.har");
  if (existsSync(har)) await page.routeFromHAR(har, { url: /\/api\//, notFound: "fallback" });
  await page.route("**/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (route.request().method() !== "GET") {
      const mocked = betaPost(pathname, JSON.parse(route.request().postData() || "{}"));
      if (mocked) return route.fulfill({ status: mocked.status, contentType: "application/json", body: JSON.stringify(mocked.json) });
    }
    if (route.request().method() !== "GET" && !/^\/api\/studio\/assets\/(demo-artifact-v1|fx-[a-z0-9-]+)\/playback$/.test(pathname)) return route.abort("blockedbyclient");
    if (Object.hasOwn(overrides, pathname)) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(overrides[pathname]) });
    const fx = /^\/api\/studio\/assets\/fx-([a-z0-9-]+)\/playback$/.exec(pathname);
    if (fx) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ url: `/beta/${fx[1] === "still-mug" ? "still-mug" : fx[1]}.jpg` }) });
    if (pathname === "/api/studio/account") return route.fulfill({ status: 200, contentType: "application/json", body: ACCOUNT });
    if (Object.hasOwn(DATA, pathname)) return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(DATA[pathname]) });
    if (pathname === "/api/studio/design-shot-artifact.svg") return route.fulfill({ status: 200, contentType: "image/svg+xml", body: readFileSync(path.join(HERE, "fixtures/artifact.svg"), "utf8") });
    return route.fallback();
  });
}

export async function privacyGuard(page: Page) {
  const text = await page.locator("body").innerText();
  const urls = await page.evaluate(() => Array.from(document.querySelectorAll<HTMLImageElement | HTMLMediaElement | HTMLSourceElement | HTMLAnchorElement>("img,video,source,a,audio")).map((element) => "href" in element ? element.href : ("currentSrc" in element ? element.currentSrc : "") || element.src));
  assertCapturePrivacy(text, urls);
  const attributes = await page.evaluate(() => Array.from(document.querySelectorAll("[title],[aria-label],[alt],[placeholder]")).flatMap((element) => ["title", "aria-label", "alt", "placeholder"].map((name) => element.getAttribute(name) || "")));
  const leaks = findCopyLeaks([text, ...attributes].join("\n"));
  const label = process.env.SHOT_LABEL || "after";
  const dir = path.join(OUT, "copy-leaks", label, THEME);
  mkdirSync(dir, { recursive: true });
  const key = new URL(page.url()).pathname.replace(/\W+/g, "_") + "_" + (new URL(page.url()).searchParams.get("workspace") || "page");
  writeFileSync(path.join(dir, `${key}.json`), JSON.stringify({ url: page.url(), leaks }, null, 2));
  // Standing rule: no platform fee and no provider/model names in visible product copy.
  // Strict by default (the capture fails); SHOT_STRICT_COPY=0 downgrades it to the JSON report only.
  if (leaks.length && process.env.SHOT_STRICT_COPY !== "0") {
    throw new Error(`Visible copy leaks fee or provider wording: ${leaks.map((leak) => leak.match).join(", ")}`);
  }
  if (!process.env.SHOT_DEV) await expect(page.locator("nextjs-portal, [data-nextjs-dev-tools-button], #__next-build-watcher")).toHaveCount(0);
}

export async function settle(page: Page, screen: Screen) {
  await page.addStyleTag({ content: "*, *::before, *::after { animation: none !important; transition: none !important; scroll-behavior: auto !important; caret-color: transparent !important; }" });
  await page.locator(screen.ready).first().waitFor({ state: "visible", timeout: 30_000 });
  await page.evaluate(() => document.fonts.ready);
  if (screen.id === "03-home-projects-balance") await page.getByRole("button", { name: /Demo Studio/ }).waitFor();
  if (screen.prepare) await screen.prepare(page);
  if (screen.id === "09-agent-review-timeline-diff") await page.getByLabel("Timeline edit comparison").waitFor();
  if (screen.url.includes("workspace=agent") && !screen.id.startsWith("m")) {
    await page.locator(".agent-approval").waitFor();
    const image = page.locator(".agent-artifact img").first();
    await image.waitFor();
    await expect(image).toHaveJSProperty("complete", true);
    expect(await image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
    await page.evaluate(() => {
      const transcript = document.querySelector<HTMLElement>(".agent-transcript");
      if (transcript) transcript.scrollTop = transcript.scrollHeight;
    });
  }
  if (screen.id === "08-canvas-node-selected") {
    await page.waitForFunction(() => {
      const viewport = document.querySelector<HTMLElement>(".react-flow__viewport");
      if (!viewport) return false;
      const value = viewport.style.transform;
      const state = viewport.dataset;
      if (state.shotTransform !== value) {
        state.shotTransform = value;
        state.shotSettledAt = String(performance.now());
        return false;
      }
      return performance.now() - Number(state.shotSettledAt) >= 250;
    });
  }
  await page.waitForFunction(() => Array.from(document.images).every((image) => image.complete && image.naturalWidth > 0));
  await page.mouse.move(0, 0);
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur?.());
}
