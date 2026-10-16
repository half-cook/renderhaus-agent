const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function harness() {
  let state = { projectId: 'project', projectName: 'Project', projects: [], nodes: [], executions: [],
    selectedNodeIds: [], past: [], future: [] };
  const AccountBalance = () => null;
  const exported = {};
  const source = fs.readFileSync(path.join(__dirname, '../components/canvas/CanvasHeader.tsx'), 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  new Function('require', 'exports', js)((name) => {
    if (name === 'react') return { useState: (initial) => [initial, () => {}], useRef: () => ({ current: null }), useEffect() {} };
    if (name === '@/lib/canvas/store') return { useCanvasStore: (selector) => selector(state),
      queueSize: (nodes) => nodes.filter((node) => ['running', 'queued'].includes(node.data.status)).length };
    if (name === '@/lib/canvas/story') return { approvedSequence: () => [] };
    if (name === '@/components/StudioAuth') return { useClerkConfigured: () => false };
    if (name === './AccountBalance') return { AccountBalance };
    if (name === 'react/jsx-runtime') return require(name);
    return new Proxy({}, { get: () => () => null });
  }, exported);
  const find = (element) => {
    if (!element || typeof element !== 'object') return;
    if (element.type === AccountBalance) return element;
    for (const child of [element.props?.children].flat(Infinity)) {
      const found = find(child);
      if (found) return found;
    }
  };
  return { set: (next) => { state = { ...state, ...next }; },
    key: () => find(exported.CanvasHeader({ navigationBusy: false, onBusyChange() {} })).props.refreshKey };
}

const node = (status, jobId) => ({ id: 'scene', data: { status, jobId } });
const execution = (status) => ({ jobId: 'voice-run', projectId: 'project', status, toolEvents: [] });

test('wallet refresh follows individual jobs even when the running count stays one', () => {
  const ui = harness();
  ui.set({ nodes: [node('idle')], executions: [execution('running')] });
  const voiceRunning = ui.key();
  ui.set({ nodes: [node('running')], executions: [execution('completed')] });
  const manualStarting = ui.key();
  assert.notEqual(manualStarting, voiceRunning, 'completed voice plus started manual job is not the same account state');
  ui.set({ nodes: [node('queued', 'wan-job')], executions: [execution('completed')] });
  const providerCharged = ui.key();
  assert.notEqual(providerCharged, manualStarting, 'accepted provider request refreshes after its debit');
  ui.set({ nodes: [node('failed', 'wan-job')] });
  assert.notEqual(ui.key(), providerCharged, 'failure/refund is another balance transition');
});

test('job identity, tool completion and final receipt changes refresh without reacting to frames or pan', () => {
  const ui = harness();
  const run = execution('running');
  run.toolEvents = [{ id: 'paid-tool', status: 'running' }];
  ui.set({ nodes: [node('queued', 'job-one')], executions: [run] });
  const before = ui.key();
  ui.set({ nodes: [{ ...node('queued', 'job-one'), position: { x: 300, y: 400 }, data: {
    ...node('queued', 'job-one').data, title: 'Renamed', result: { frames: 90 }, config: { prompt: 'Edited' },
  } }], executions: [{ ...run, message: 'Frame 90', updatedAt: 123, progressEvents: [{ id: 'frame-90' }] }] });
  assert.equal(ui.key(), before, 'progress, message, positions and config do not add account requests');
  ui.set({ nodes: [node('queued', 'job-two')] });
  assert.notEqual(ui.key(), before, 'a new provider job must refresh even if its status is unchanged');
  const queued = ui.key();
  ui.set({ executions: [{ ...run, toolEvents: [{ id: 'paid-tool', status: 'completed' }] }] });
  assert.notEqual(ui.key(), queued);
  const completedTool = ui.key();
  ui.set({ executions: [{ ...run, toolEvents: [{ id: 'paid-tool', status: 'completed' }],
    receipt: { actual_cents: 52, balance_after_cents: 850 } }] });
  assert.notEqual(ui.key(), completedTool);
  const receipt = ui.key();
  ui.set({ projectId: 'other-project' });
  assert.notEqual(ui.key(), receipt);
});
