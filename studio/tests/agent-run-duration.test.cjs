const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

let now = 1120;
const source = fs.readFileSync(path.join(__dirname, '../components/canvas/AgentDock.tsx'), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;
const exported = {};
new Function('require', 'exports', 'Date', `${js}\nexports.duration = runDuration;`)(
  (name) => name === 'react/jsx-runtime' ? require(name) : new Proxy({}, { get: () => () => null }),
  exported, { now: () => now * 1000 },
);

test('active elapsed time advances between existing execution refreshes even without new saved events', () => {
  for (const status of ['running', 'queued', 'pending']) {
    const execution = { status, createdAt: 1000, updatedAt: 1001 };
    now = 1120;
    assert.equal(exported.duration(execution), '2m 0s');
    now = 1121.9;
    assert.equal(exported.duration(execution), '2m 1s');
  }
  assert.equal(exported.duration({ status: 'running', createdAt: 1100 }), '21s');
});

test('finished, failed and approval-paused durations stay at the saved timestamp', () => {
  for (const status of ['completed', 'failed', 'incomplete', 'awaiting_approval']) {
    const execution = { status, createdAt: 1000, updatedAt: 1025 };
    now = 1120;
    assert.equal(exported.duration(execution), '25s');
    now = 2200;
    assert.equal(exported.duration(execution), '25s');
  }
  assert.equal(exported.duration({ status: 'completed', createdAt: 1000 }), null);
  assert.equal(exported.duration({ status: 'running' }), null);
});
