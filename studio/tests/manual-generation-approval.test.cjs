const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const load = require('./load-ts.cjs');

function harness() {
  const calls = [];
  let quote = { estimate_cents: 40, cap_cents: 40, approval_token: 'signed-price', expires_at: 9999999999, balance_cents: 1000 };
  let quoteWait;
  let result = { result: { status: 'succeeded' }, assets: [{ assetId: 'asset', versionId: 'version', kind: 'video' }] };
  const api = {
    quoteTool: async (...args) => { calls.push(['quote', ...args]); if (quoteWait) await quoteWait; return quote; },
    invokeTool: async (...args) => { calls.push(['invoke', ...args]); return result; },
  };
  const cache = new Map();
  const compile = (file) => {
    const full = path.resolve(__dirname, '..', file);
    if (cache.has(full)) return cache.get(full);
    const exported = {};
    cache.set(full, exported);
    const js = ts.transpileModule(fs.readFileSync(full, 'utf8'), { compilerOptions: {
      module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
    } }).outputText;
    new Function('require', 'exports', js)((name) => {
      if (name === 'react') return { ...require('react'), useRef: (current) => ({ current }) };
      if (name === '@/lib/api') return api;
      if (name === '@/lib/canvas/store') return { useCanvasStore: (selector) => selector(store.getState()) };
      if (name.startsWith('@/') || name.startsWith('.')) {
        const local = name.startsWith('@/') ? path.resolve(__dirname, '..', name.slice(2)) : path.resolve(path.dirname(full), name);
        const target = fs.existsSync(local) ? local : fs.existsSync(`${local}.ts`) ? `${local}.ts` : `${local}.tsx`;
        return compile(path.relative(path.resolve(__dirname, '..'), target));
      }
      return require(name);
    }, exported);
    return exported;
  };
  const store = compile('lib/canvas/store.ts').useCanvasStore;
  const graph = compile('lib/canvas/graph-execution.ts');
  const node = { id: 'shot', position: { x: 0, y: 0 }, data: { kind: 'video', title: 'Shot', toolId: 'video.wan3.generate', providerId: 'fal',
    status: 'idle', config: { prompt: 'Original prompt', resolution: '720p', settings: { n: 1 } } } };
  store.setState({ projectId: 'project', nodes: [node], edges: [], persist: async () => {} });
  return { store, graph, node, calls,
    renderApproval: () => compile('components/canvas/ManualRunApproval.tsx').ManualRunApproval(),
    setQuote: (value) => { quote = value; }, waitQuote: (value) => { quoteWait = value; },
    setResult: (value) => { result = value; } };
}

function find(element, predicate) {
  if (!element || typeof element !== 'object') return;
  if (predicate(element)) return element;
  for (const child of [element.props?.children].flat(Infinity)) {
    const result = find(child, predicate);
    if (result) return result;
  }
}

test('manual review shows numeric Wan duration and retains duration_seconds precedence', async () => {
  const { store, node, renderApproval } = harness();
  node.data.config.duration = 4;
  await store.getState().runNode('shot');
  let card = find(renderApproval(), (element) => element.type?.name === 'ApprovalCard');
  assert.ok(card.props.model.specs.includes('4 s'), 'review matches Wan duration submitted to the provider');
  store.getState().cancelManualRun();
  node.data.config.duration_seconds = 6;
  await store.getState().runNode('shot');
  card = find(renderApproval(), (element) => element.type?.name === 'ApprovalCard');
  assert.ok(card.props.model.specs.includes('6 s'));
  assert.ok(!card.props.model.specs.includes('4 s'));
});

test('manual review restores keyboard focus on close and ignores a removed trigger', async () => {
  const { store, renderApproval } = harness();
  await store.getState().runNode('shot');
  const previousDocument = global.document;
  const previousHTMLElement = global.HTMLElement;
  class Element {
    isConnected = true;
    focus() { global.document.activeElement = this; }
  }
  const trigger = new Element();
  const heading = new Element();
  global.HTMLElement = Element;
  global.document = { activeElement: trigger, getElementById: () => heading };
  try {
    const dialog = find(renderApproval(), (element) => typeof element.props?.onOpenAutoFocus === 'function');
    let prevented = 0;
    const event = { preventDefault: () => prevented++ };
    dialog.props.onOpenAutoFocus(event);
    assert.equal(global.document.activeElement, heading);
    dialog.props.onCloseAutoFocus(event);
    assert.equal(global.document.activeElement, trigger);
    assert.equal(prevented, 2);
    dialog.props.onOpenAutoFocus(event);
    trigger.isConnected = false;
    dialog.props.onCloseAutoFocus(event);
    assert.equal(global.document.activeElement, heading);
  } finally {
    global.document = previousDocument;
    global.HTMLElement = previousHTMLElement;
  }
});

test('all manual generation waits for a server quote and explicit approval; double clicks run once', async () => {
  const { store, calls } = harness();
  await store.getState().runNode('shot');
  assert.deepEqual(calls.map(([type]) => type), ['quote']);
  assert.equal(store.getState().nodes[0].data.status, 'idle');
  assert.equal(store.getState().pendingManualRun.quote.cap_cents, 40);
  await Promise.all([store.getState().approveManualRun(), store.getState().approveManualRun()]);
  assert.deepEqual(calls.map(([type]) => type), ['quote', 'invoke']);
  assert.equal(calls[1][4].approvalToken, 'signed-price');
  assert.equal(store.getState().nodes[0].data.status, 'completed');
});

test('cancel preserves settings and dispatches nothing', async () => {
  const { store, calls } = harness();
  await store.getState().runNode('shot');
  store.getState().cancelManualRun();
  await store.getState().approveManualRun();
  assert.deepEqual(calls.map(([type]) => type), ['quote']);
  assert.equal(store.getState().nodes[0].data.config.prompt, 'Original prompt');
  assert.equal(store.getState().nodes[0].data.status, 'idle');
});

test('quotes snapshot nested settings and invalidate after edits without losing work', async () => {
  const { store, calls, node } = harness();
  await store.getState().runNode('shot');
  node.data.config.settings.n = 2;
  assert.equal(store.getState().pendingManualRun.request.arguments.settings.n, 1);
  await store.getState().approveManualRun();
  assert.deepEqual(calls.map(([type]) => type), ['quote']);
  assert.equal(store.getState().nodes[0].data.config.settings.n, 2);
  assert.match(store.getState().nodes[0].data.error, /Settings changed/);
});

test('repeated Generate while pricing requests only one quote', async () => {
  const { store, calls, waitQuote } = harness();
  let release;
  waitQuote(new Promise((resolve) => { release = resolve; }));
  const first = store.getState().runNode('shot');
  await store.getState().runNode('shot');
  assert.equal(calls.length, 1);
  release();
  await first;
  assert.ok(store.getState().pendingManualRun);
});

test('free work skips paid approval and invokes only after its zero quote', async () => {
  const { store, calls, setQuote } = harness();
  setQuote({ estimate_cents: 0, cap_cents: 0, approval_token: 'free' });
  await store.getState().runNode('shot');
  assert.deepEqual(calls.map(([type]) => type), ['quote', 'invoke']);
  assert.equal(store.getState().pendingManualRun, null);
});

test('dry run, blocked work and terminal jobs without assets fail visibly and preserve older takes', async () => {
  const { graph, node } = harness();
  node.data.output = { assetId: 'old', versionId: 'old', kind: 'video' };
  node.data.variants = [node.data.output];
  const request = graph.creativeNodeRequest(node, [node], [], 'project');
  for (const status of ['dry_run', 'blocked', 'not_run', 'succeeded', 'completed', 'success']) {
    const patch = await graph.runCreativeNode(node, request, async () => ({ result: { status, job_id: 'job', reason: 'No work https://provider.test/file?secret=token' }, assets: [] }));
    assert.equal(patch.status, 'failed', status);
    assert.ok(patch.error);
    assert.doesNotMatch(patch.error, /secret=token/);
    assert.equal('output' in patch, false, 'a failed retry does not erase the prior take');
    assert.equal('variants' in patch, false);
  }
  const queued = await graph.runCreativeNode(node, request, async () => ({ result: { status: 'queued', job_id: 'job' }, assets: [] }));
  assert.equal(queued.status, 'queued');
});

test('polling cannot call an empty terminal result completed, and running errors stop polling', async () => {
  const { graph, node, setResult } = harness();
  node.data.jobId = 'job';
  for (const status of ['succeeded', 'completed', 'dry_run', 'blocked', 'not_run']) {
    setResult({ result: { status }, assets: [] });
    const patch = await graph.pollCreativeNode(node, 'project');
    assert.equal(patch.status, 'failed', status);
    assert.ok(patch.error);
  }
  setResult({ result: { status: 'running', error: 'Provider rejected this job' }, assets: [] });
  const patch = await graph.pollCreativeNode(node, 'project');
  assert.equal(patch.status, 'failed');
  assert.match(patch.error, /Provider rejected/);
});
