import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";

const here = path.dirname(fileURLToPath(import.meta.url));
const studio = path.resolve(process.env.SHOT_STUDIO_DIR || path.join(here, ".."));
const mode = process.argv[2] || "after";
if (!["before", "after", "a11y", "verify"].includes(mode)) throw new Error(`Unknown capture mode: ${mode}`);
const port = Number(process.env.SHOT_PORT || 5191);
if (!Number.isInteger(port) || port < 1024 || port > 65535 || [5174, 8000].includes(port)) throw new Error("Choose an unreserved SHOT_PORT between 1024 and 65535");
const baseURL = `http://localhost:${port}`;
const distDir = process.env.RH_SHOT_BUILD_DIR || ".next-design-shots";
const env = {
  ...process.env,
  NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: "",
  CLERK_SECRET_KEY: "",
  NEXT_TELEMETRY_DISABLED: "1",
  STUDIO_API_ORIGIN: "http://localhost:1",
  SHOT_BASE_URL: baseURL,
  SHOT_LABEL: ["a11y", "verify"].includes(mode) ? process.env.SHOT_LABEL || "after" : mode,
  A11Y: mode === "a11y" ? "1" : "",
  RH_SHOT_BUILD_DIR: distDir,
};

async function command(script, args, cwd, owner) {
  const child = spawn(process.execPath, [script, ...args], { cwd, env, stdio: "inherit" });
  let ownerExited = false;
  const stopChild = () => { ownerExited = true; child.kill("SIGTERM"); };
  owner?.once("exit", stopChild);
  try {
    await new Promise((resolve, reject) => {
      child.once("error", reject);
      child.once("exit", (code, signal) => code === 0 && !ownerExited ? resolve() : reject(new Error(`Command failed (${signal || code}): ${path.basename(script)}`)));
    });
  } finally {
    owner?.removeListener("exit", stopChild);
  }
}

const next = path.join(studio, "node_modules/next/dist/bin/next");
if (process.env.SHOT_SKIP_BUILD !== "1" || !existsSync(path.join(studio, distDir, "BUILD_ID"))) {
  await command(next, ["build"], studio);
}
await new Promise((resolve, reject) => {
  const probe = net.createServer();
  probe.once("error", reject);
  probe.listen(port, "localhost", () => probe.close(resolve));
});
const server = spawn(process.execPath, [next, "start", "--port", String(port), "--hostname", "localhost"], { cwd: studio, env, stdio: ["ignore", "pipe", "pipe"] });
let readyTimer;
const ready = new Promise((resolve, reject) => {
  readyTimer = setTimeout(() => reject(new Error("Owned Next server did not report readiness")), 60_000);
  server.once("error", reject);
  server.once("exit", () => reject(new Error("Owned Next server exited")));
  let output = "";
  server.stdout.on("data", (chunk) => {
    process.stdout.write(chunk);
    output = (output + chunk).slice(-4096);
    if (/Ready in \d/.test(output)) resolve();
  });
  server.stderr.on("data", (chunk) => process.stderr.write(chunk));
});
const exited = new Promise((resolve) => server.once("close", resolve));
const stop = () => { server.kill("SIGTERM"); };
process.once("SIGINT", stop);
process.once("SIGTERM", stop);
try {
  await ready;
  clearTimeout(readyTimer);
  const deadline = Date.now() + 60_000;
  while (true) {
    if (server.exitCode !== null || server.signalCode !== null) throw new Error("Owned Next server exited before it was ready");
    try {
      const response = await fetch(baseURL, { signal: AbortSignal.timeout(2000) });
      if (response.ok) break;
    } catch {}
    if (Date.now() >= deadline) throw new Error(`Next did not become ready at ${baseURL}`);
    await delay(200);
  }
  const playwright = path.join(here, "../node_modules/@playwright/test/cli.js");
  await command(playwright, ["test", "--config", path.join(here, "playwright.config.ts"), mode === "a11y" ? "a11y.spec.ts" : mode === "verify" ? "interactions.spec.ts" : "shots.spec.ts", "--project=desktop-1920x1200"], here, server);
} finally {
  clearTimeout(readyTimer);
  process.removeListener("SIGINT", stop);
  process.removeListener("SIGTERM", stop);
  if (server.exitCode === null && server.signalCode === null) {
    server.kill("SIGTERM");
    await Promise.race([exited, delay(5000)]);
    if (server.exitCode === null && server.signalCode === null) server.kill("SIGKILL");
    await exited;
  }
}
