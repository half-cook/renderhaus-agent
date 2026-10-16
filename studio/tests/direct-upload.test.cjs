const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const ts = require("typescript");

const root = path.resolve(__dirname, "..");
const MB = 1024 * 1024;

function load(relative, globals = {}) {
  const cache = new Map();
  function inner(filename) {
    filename = path.resolve(filename);
    if (cache.has(filename)) return cache.get(filename).exports;
    if (filename.endsWith(".json")) return JSON.parse(fs.readFileSync(filename, "utf8"));
    const output = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2021, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(filename, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, Headers, Response, Blob, Error, Promise, setTimeout, JSON, Number, Math, Map, Array, Object, String,
      process: { env: {} }, ...globals,
      require: (name) => {
        if (name.startsWith("@/")) return inner(path.join(root, name.slice(2) + ".ts"));
        if (name.startsWith(".")) return inner(path.resolve(path.dirname(filename), name.endsWith(".json") ? name : name + ".ts"));
        return require(name);
      },
    }, { filename });
    return module.exports;
  }
  return inner(path.join(root, relative));
}

function file(name, size) {
  const blob = new Blob([new Uint8Array(size)], { type: "video/mp4" });
  Object.defineProperty(blob, "name", { value: name });
  Object.defineProperty(blob, "lastModified", { value: 1 });
  return blob;
}

/** In-memory fake of the backend + storage. */
function fakeServer({ partSize = 8 * MB, failPutsFor = new Set(), stored = new Map() } = {}) {
  const calls = [];
  const state = { size: 0, stored, failPutsFor, completed: null };
  const api = async (url, body) => {
    calls.push([url, body]);
    const op = url.split("/").pop();
    if (op === "create") {
      state.size = body.size_bytes;
      return new Response(JSON.stringify({ token: "tok", part_size: partSize, part_count: Math.ceil(body.size_bytes / partSize) }), { status: 201 });
    }
    if (op === "status") {
      if (body.token !== "tok") return new Response(JSON.stringify({ detail: "expired" }), { status: 410 });
      return new Response(JSON.stringify({ part_size: partSize, part_count: Math.ceil(state.size / partSize), completed_parts: [...state.stored].map(([part_number, etag]) => ({ part_number, etag })) }));
    }
    if (op === "sign-parts") {
      return new Response(JSON.stringify({ urls: Object.fromEntries(body.part_numbers.map((n) => [String(n), `https://storage.test/part/${n}`])) }));
    }
    if (op === "complete") {
      state.completed = body.parts;
      return new Response(JSON.stringify({ asset_id: "a", version_id: "v", kind: "video", filename: "take.mp4", size_bytes: state.size }));
    }
    return new Response("{}", { status: 404 });
  };
  const puts = [];
  const put = async (url, blob) => {
    const n = Number(url.split("/").pop());
    puts.push([n, blob.size]);
    if (state.failPutsFor.has(n)) throw new TypeError("network down");
    state.stored.set(n, `"etag-${n}"`);
    return new Response("", { status: 200, headers: { ETag: `"etag-${n}"` } });
  };
  return { api, put, calls, puts, state };
}

function memoryStorage() {
  const map = new Map();
  return { map, getItem: (k) => (map.has(k) ? map.get(k) : null), setItem: (k, v) => map.set(k, v), removeItem: (k) => map.delete(k) };
}

const { directUpload, parseDirectUploadConfig, resumeKey } = load("lib/direct-upload.ts");

test("uploads every part directly and completes in order", async () => {
  const server = fakeServer();
  const storage = memoryStorage();
  const progress = [];
  const result = await directUpload(file("take.mp4", 20 * MB + 5), "p", {
    api: server.api, put: server.put, storage, onProgress: (u) => progress.push(u), wait: async () => {},
  });
  assert.equal(result.version_id, "v");
  assert.deepEqual(server.puts.map(([n]) => n).sort(), [1, 2, 3]);
  assert.deepEqual(server.puts.find(([n]) => n === 3)[1], 4 * MB + 5);
  assert.equal(JSON.stringify(server.state.completed.map((p) => p.part_number)), JSON.stringify([1, 2, 3]));
  assert.equal(progress.at(-1), 20 * MB + 5);
  assert.equal(storage.map.size, 0, "resume state cleared after completion");
});

test("a dropped connection pauses with resume state kept, then resumes from the last stored part", async () => {
  const server = fakeServer({ failPutsFor: new Set([2, 3]) });
  const storage = memoryStorage();
  const f = file("take.mp4", 20 * MB);
  await assert.rejects(
    directUpload(f, "p", { api: server.api, put: server.put, storage, concurrency: 1, maxAttempts: 2, wait: async () => {} }),
    /Upload paused\. Check your connection and try again; it will resume where it stopped\./,
  );
  assert.equal(storage.getItem(resumeKey(f, "p")), "tok");
  server.puts.length = 0;
  server.state.failPutsFor.clear();
  await directUpload(f, "p", { api: server.api, put: server.put, storage, wait: async () => {} });
  assert.deepEqual(server.puts.map(([n]) => n).sort(), [2, 3], "part 1 is not sent again");
  assert.equal(server.calls.filter(([u]) => u.endsWith("/create")).length, 1);
  assert.equal(JSON.stringify(server.state.completed.map((p) => p.part_number)), JSON.stringify([1, 2, 3]));
});

test("an expired saved session starts a fresh upload", async () => {
  const server = fakeServer();
  const storage = memoryStorage();
  const f = file("take.mp4", 9 * MB);
  storage.setItem(resumeKey(f, "p"), "stale");
  await directUpload(f, "p", { api: server.api, put: server.put, storage, wait: async () => {} });
  assert.equal(server.calls.filter(([u]) => u.endsWith("/create")).length, 1);
});

test("a lost completion response recovers the saved asset without uploading again", async () => {
  const storage = memoryStorage();
  const f = file("take.mp4", 9 * MB);
  storage.setItem(resumeKey(f, "p"), "saved-token");
  const asset = { asset_id: "saved", version_id: "saved-version", kind: "video" };
  const calls = [];
  const progress = [];
  const result = await directUpload(f, "p", {
    storage,
    api: async (url) => {
      calls.push(url);
      return new Response(JSON.stringify({ completed_asset: asset }));
    },
    put: async () => assert.fail("Completed file must not be uploaded again"),
    onProgress: (uploaded, total) => progress.push([uploaded, total]),
  });
  assert.equal(result.version_id, "saved-version");
  assert.equal(calls.length, 1);
  assert.ok(calls[0].endsWith("/status"));
  assert.deepEqual(progress, [[f.size, f.size]]);
  assert.equal(storage.map.size, 0);
});

test("transient part failure retries without failing the upload", async () => {
  const server = fakeServer();
  let first = true;
  const put = async (url, blob) => {
    if (first) { first = false; return new Response("", { status: 500 }); }
    return server.put(url, blob);
  };
  await directUpload(file("take.mp4", 9 * MB), "p", { api: server.api, put, wait: async () => {} });
  assert.equal(JSON.stringify(server.state.completed.map((p) => p.part_number)), JSON.stringify([1, 2]));
});

test("health config parsing", () => {
  assert.deepEqual({ ...parseDirectUploadConfig({}) }, { enabled: false, maxUploadMb: 0 });
  assert.deepEqual({ ...parseDirectUploadConfig({ direct_upload: { enabled: true, max_upload_mb: 20480 } }) }, { enabled: true, maxUploadMb: 20480 });
  assert.equal(parseDirectUploadConfig({ direct_upload: { enabled: true, max_upload_mb: -1 } }).enabled, false);
});

test("uploadStudioFile routes video through the direct path and never sends app credentials to storage", async () => {
  const server = fakeServer();
  const seen = [];
  const fetch = async (url, init = {}) => {
    seen.push([String(url), init]);
    if (url === "/api/health") {
      return new Response(JSON.stringify({ max_upload_mb_by_kind: { image: 15, video: 100, audio: 50 }, direct_upload: { enabled: true, max_upload_mb: 20480 } }));
    }
    if (String(url).startsWith("https://storage.test/")) return server.put(url, init.body);
    return server.api(String(url), JSON.parse(init.body));
  };
  const { uploadStudioFile } = load("lib/api.ts", { fetch, FormData, crypto: require("node:crypto").webcrypto, structuredClone });
  const asset = await uploadStudioFile(file("take.mp4", 150 * MB), "p");
  assert.equal(asset.versionId, "v");
  const storageCalls = seen.filter(([u]) => u.startsWith("https://storage.test/"));
  assert.equal(storageCalls.length, 19);
  for (const [, init] of storageCalls) assert.equal(new Headers(init.headers).get("Authorization"), null);
  assert.equal(seen.some(([u]) => u.includes("/api/studio/upload?")), false);
});

test("UI-facing strings name no storage provider and no fees", () => {
  const source = fs.readFileSync(path.join(root, "lib/direct-upload.ts"), "utf8");
  const strings = [...source.matchAll(/new UploadError\("([^"]+)"/g), ...source.matchAll(/"(Upload[^"]+)"/g)].map((m) => m[1]);
  assert.ok(strings.length > 0);
  for (const text of strings) assert.doesNotMatch(text, /\b(S3|AWS|Amazon|R2|Cloudflare|\$|fee|cost)\b/i);
});
