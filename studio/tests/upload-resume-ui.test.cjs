const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const path = require("path");
const read = (p) => fs.readFileSync(path.join(__dirname, "..", p), "utf8");

test("failed uploads offer Try again with the same file and show live progress", () => {
  const store = read("lib/canvas/store.ts");
  assert.match(store, /retryUpload: \(\) => get\(\)\.addUploadNode\(file, position\)/);
  assert.match(store, /onProgress: \(loaded: number, total: number\) => set\(\{ uploadProgress:/);
  const ui = read("components/canvas/UploadError.tsx");
  assert.match(ui, /Try again/);
  assert.match(ui, /Uploading \{progress\.filename\} · \{pct\}%/);
  assert.match(read("components/canvas/CanvasShell.tsx"), /onRetry=\{retryUpload \?/);
});

test("direct upload waits for the connection instead of burning retries offline", () => {
  const up = read("lib/direct-upload.ts");
  assert.match(up, /navigator\.onLine === false/);
  assert.match(up, /addEventListener\("online"/);
  assert.match(up, /deps\.maxAttempts \?\? 8/);
});
