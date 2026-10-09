const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const ts = require("typescript");
const { execFileSync } = require("node:child_process");
const { webcrypto } = require("node:crypto");

const root = path.resolve(__dirname, "..");
const MB = 1024 * 1024;
const limits = { max_upload_mb: 100, max_upload_mb_by_kind: { image: 15, video: 100, audio: 50 } };
const version = { asset_id: "asset", version_id: "version", kind: "video", filename: "clip.mp4", size_bytes: 13600000 };

function harness(fetch, env = {}) {
  const cache = new Map();
  function load(filename) {
    filename = path.resolve(filename);
    if (cache.has(filename)) return cache.get(filename).exports;
    if (filename.endsWith(".json")) return JSON.parse(fs.readFileSync(filename, "utf8"));
    const output = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2021, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(filename, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, fetch, Headers, FormData, Response, Error,
      crypto: webcrypto, structuredClone,
      process: { env },
      require: (name) => {
        if (name.startsWith("@/")) return load(path.join(root, name.slice(2) + ".ts"));
        if (name.startsWith(".")) return load(path.resolve(path.dirname(filename), name.endsWith(".json") ? name : name + ".ts"));
        return require(name);
      },
    }, { filename });
    return module.exports;
  }
  return { load: (relative) => load(path.join(root, relative)) };
}

function file(name, size, type = "video/mp4") {
  const result = new Blob([new Uint8Array(size)], { type });
  Object.defineProperty(result, "name", { value: name });
  return result;
}
const health = () => new Response(JSON.stringify(limits));

test("preflight rejects limit plus one without posting", async () => {
  const calls = [];
  const { uploadStudioFile } = harness(async (url, options) => {
    calls.push([url, options]);
    return health();
  }).load("lib/api.ts");
  await assert.rejects(uploadStudioFile(file("frame.png", 15 * MB + 1, "image/png"), "project"), /File is larger than 15 MB\./);
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "/api/health");
  assert.equal(calls[0][1].cache, "no-store");
});

test("preflight accepts exact limit and uses filename kind for empty MIME", async () => {
  const calls = [];
  const { uploadStudioFile } = harness(async (url, options) => {
    calls.push([url, options]);
    return url === "/api/health" ? health() : new Response(JSON.stringify({ ...version, kind: "image" }));
  }).load("lib/api.ts");
  const uploaded = await uploadStudioFile(file("frame.PNG", 15 * MB, ""), "project space");
  assert.equal(uploaded.versionId, "version");
  assert.equal(calls[1][0], "/api/studio/upload?project_id=project%20space");
  assert.equal(calls[1][1].body.get("file").size, 15 * MB);
});

test("server-configured video limit overrides the default", async () => {
  const { uploadStudioFile } = harness(async () => new Response(JSON.stringify({ max_upload_mb: 2, max_upload_mb_by_kind: { image: 1, video: 2, audio: 1 } }))).load("lib/api.ts");
  await assert.rejects(uploadStudioFile(file("clip.mov", 2 * MB + 1, ""), "project"), /File is larger than 2 MB\./);
});

test("unsupported extension has a readable preflight error", async () => {
  const { uploadStudioFile } = harness(async () => health()).load("lib/api.ts");
  await assert.rejects(uploadStudioFile(file("notes.txt", 10, "text/plain"), "project"), /Use an image, video, or audio file\./);
});

for (const [status, body, expected] of [
  [413, JSON.stringify({ detail: "File is larger than 2 MB." }), /File is larger than 2 MB\./],
  [413, "<html>Too large</html>", /File is larger than 100 MB\./],
  [413, "null", /File is larger than 100 MB\./],
  [415, "", /Use an image, video, or audio file\./],
  [500, "Internal Server Error", /Upload failed\. Please try again\./],
  [400, JSON.stringify({ detail: "There was an error parsing the body" }), /Upload was interrupted\. Please try again\./],
  [200, "{\"asset_id\":", /Upload was interrupted\. Please try again\./],
]) {
  test(`upload maps ${status} ${body.slice(0, 20)} to a readable error`, async () => {
    const { uploadStudioFile } = harness(async (url) => url === "/api/health" ? health() : new Response(body, { status })).load("lib/api.ts");
    await assert.rejects(uploadStudioFile(file("clip.mp4", 100), "project"), expected);
  });
}

for (const failure of [new TypeError("Failed to fetch"), new DOMException("aborted", "AbortError")]) {
  test(`upload maps ${failure.name} to an interrupted upload message`, async () => {
    const { uploadStudioFile } = harness(async (url) => {
      if (url === "/api/health") return health();
      throw failure;
    }).load("lib/api.ts");
    await assert.rejects(uploadStudioFile(file("clip.mp4", 100), "project"), /Upload was interrupted\. Check your connection and try again\./);
  });
}

test("an unavailable health response prevents upload with a readable error", async () => {
  const { uploadStudioFile } = harness(async () => new Response("offline", { status: 503 })).load("lib/api.ts");
  await assert.rejects(uploadStudioFile(file("clip.mp4", 100), "project"), /Could not check upload limits\. Please try again\./);
});

test("canvas upload failure settles and stores a visible alert without adding a node", async () => {
  const { useCanvasStore } = harness(async (url) => url === "/api/health" ? health() : new Response("", { status: 415 })).load("lib/canvas/store.ts");
  await useCanvasStore.getState().addUploadNode(file("clip.mp4", 100), { x: 0, y: 0 });
  assert.equal(useCanvasStore.getState().nodes.length, 0);
  assert.equal(useCanvasStore.getState().uploadError, "Use an image, video, or audio file.");
});

test("upload alert renders the message and can be dismissed", () => {
  const { UploadError } = harness().load("components/canvas/UploadError.tsx");
  const { renderToStaticMarkup } = require("react-dom/server");
  let dismissed = false;
  const tree = UploadError({ message: "File is larger than 15 MB.", onDismiss: () => { dismissed = true; } });
  const markup = renderToStaticMarkup(tree);
  assert.match(markup, /role="alert"/);
  assert.match(markup, /File is larger than 15 MB\./);
  const children = tree.props.children;
  children.find((child) => child.type === "button").props.onClick();
  assert.equal(dismissed, true);
  assert.equal(UploadError({ message: null, onDismiss: () => {} }), null);
});

test("a successful retry clears the upload alert and adds the asset", async () => {
  let fail = true;
  const { useCanvasStore } = harness(async (url) => {
    if (url === "/api/health") return health();
    if (String(url).includes("/upload?")) return fail ? new Response("", { status: 415 }) : new Response(JSON.stringify(version));
    return new Response(JSON.stringify({ revision: 1 }));
  }).load("lib/canvas/store.ts");
  const upload = () => useCanvasStore.getState().addUploadNode(file("clip.mp4", 100), { x: 0, y: 0 });
  assert.equal(await upload(), false);
  fail = false;
  assert.equal(await upload(), true);
  assert.equal(useCanvasStore.getState().uploadError, null);
  assert.equal(useCanvasStore.getState().nodes[0].data.output.versionId, "version");
  await useCanvasStore.getState().persist();
});

for (const env of [{}, { STUDIO_MAX_UPLOAD_MB: "8", STUDIO_MAX_VIDEO_UPLOAD_MB: "20" }, { STUDIO_MAX_AUDIO_UPLOAD_MB: "120" }]) {
  test(`Next proxy and Python limits agree for ${JSON.stringify(env)}`, async () => {
    const config = harness(undefined, env).load("next.config.ts").default;
    const venvPython = path.join(root, "../.venv/bin/python");
    const python = fs.existsSync(venvPython) ? venvPython : "python3";
    const backend = JSON.parse(execFileSync(python, ["-c", "import json; from server.uploads import upload_limits_mb; print(json.dumps(upload_limits_mb()))"], { cwd: path.join(root, ".."), env: { PATH: process.env.PATH, ...env } }).toString());
    assert.equal(config.experimental?.middlewareClientMaxBodySize, (Math.max(...Object.values(backend)) + 1) * MB);
    const rewrites = await config.rewrites();
    assert.equal(rewrites[0].source, "/api/:path*");
  });
}

test("invalid proxy limits fail configuration", () => {
  for (const value of ["0", "-1", "NaN", "1.5", "unlimited", "9007199254740992"]) {
    assert.throws(() => harness(undefined, { STUDIO_MAX_UPLOAD_MB: value }).load("next.config.ts"), /STUDIO_MAX_UPLOAD_MB/);
  }
});
