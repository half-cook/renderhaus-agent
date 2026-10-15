import { defineConfig } from "@playwright/test";

// Layout pass: 4 viewports x the live Studio screens. Mock API only (fixture.ts); nothing leaves the browser.
export default defineConfig({
  testDir: ".",
  testMatch: ["layout.spec.ts"],
  workers: 1,
  retries: 0,
  timeout: 90_000,
  outputDir: "./out/.pw-output/layout",
  reporter: [["list"]],
  use: { baseURL: process.env.SHOT_BASE_URL ?? "http://localhost:5197", colorScheme: "dark", reducedMotion: "reduce",
    locale: "en-US", timezoneId: "America/Toronto", trace: "off", video: "off" },
  projects: [
    { name: "1280x800", use: { viewport: { width: 1280, height: 800 } } },
    { name: "1440x900", use: { viewport: { width: 1440, height: 900 } } },
    { name: "1920x1080", use: { viewport: { width: 1920, height: 1080 } } },
    { name: "390x844", use: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true } },
  ],
});
