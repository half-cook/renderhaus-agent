import { defineConfig, devices } from "@playwright/test";

export const LABEL = process.env.SHOT_LABEL ?? "after";
const BASE = process.env.SHOT_BASE_URL ?? "http://localhost:5191"; // NOT 127.0.0.1: studio middleware can self-proxy (docs/BROWSER_E2E.md)

export default defineConfig({
  testDir: ".",
  testMatch: ["shots.spec.ts", "a11y.spec.ts", "interactions.spec.ts"],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  outputDir: `${process.env.SHOT_OUT_DIR || "./out"}/.pw-output/${LABEL}`,
  reporter: [["list"]],
  use: {
    baseURL: BASE,
    colorScheme: process.env.SHOT_THEME === "light" ? "light" : "dark",
    reducedMotion: "reduce",
    locale: "en-US",
    timezoneId: "America/Toronto",
    trace: "off",
    video: "off",
  },
  projects: [
    {
      name: "desktop-1920x1200",
      use: { viewport: { width: 1920, height: 1200 }, deviceScaleFactor: 1 },
    },
    {
      name: "desktop-1920x1200@2x",
      grep: process.env.SHOT_2X ? /.*/ : /^$/,
      use: { viewport: { width: 1920, height: 1200 }, deviceScaleFactor: 2 },
    },
    {
      name: "mobile-iphone15",
      // Chromium-emulated iPhone 15 (393x852 @3x): no WebKit download needed. Use real Safari/Comet for final mobile QA.
      use: { ...devices["iPhone 15"], defaultBrowserType: "chromium" },
    },
  ],
});
