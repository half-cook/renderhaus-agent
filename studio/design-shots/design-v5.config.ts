import { defineConfig } from "@playwright/test";

// Design pass v5: 1280x800 + 390x844, affected launch screens. Mock API only.
export default defineConfig({
  testDir: ".",
  testMatch: ["design-v5.spec.ts"],
  workers: 1,
  retries: 0,
  timeout: 90_000,
  outputDir: "./out/.pw-output/design-v5",
  reporter: [["list"]],
  use: { baseURL: process.env.SHOT_BASE_URL ?? "http://localhost:5197", colorScheme: "dark", reducedMotion: "reduce",
    locale: "en-US", timezoneId: "America/Toronto", trace: "off", video: "off" },
  projects: [
    { name: "1280x800", use: { viewport: { width: 1280, height: 800 } } },
    { name: "390x844", use: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true } },
  ],
});
