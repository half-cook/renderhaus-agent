const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function overlay(execution) {
  const state = { nodes: [{ id: 'scene', data: { title: 'Scene', output: { versionId: 'still', kind: 'image' } } }],
    selectedNodeIds: ['scene'], executions: [execution], conversationId: 'conversation' };
  const source = fs.readFileSync(path.join(__dirname, '../components/canvas/StudioStage.tsx'), 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const exported = {};
  const mocks = {
    'react': { useMemo: (fn) => fn(), useState: (initial) => [initial, () => {}] },
    'lucide-react': { Film: () => null },
    './AssetMedia': { AssetMedia: () => null },
    '@/lib/canvas/store': { useCanvasStore: (select) => select(state) },
  };
  new Function('require', 'exports', js)((name) => mocks[name] ?? require(name), exported);
  const find = (element) => {
    if (!element || typeof element !== 'object') return;
    if (element.props?.className === 'rh-shooting') return element;
    return [].concat(element.props?.children || []).map(find).find(Boolean);
  };
  const text = (element) => typeof element === 'string' ? element
    : !element || typeof element !== 'object' ? '' : [].concat(element.props?.children || []).map(text).join(' ');
  const found = find(exported.StudioStage({}));
  return found ? text(found) : null;
}

const run = (message, extra = {}) => ({ conversationId: 'conversation', status: 'running', toolEvents: [],
  progressEvents: [{ type: 'MODEL_UPDATE', status: 'running', message }], ...extra });

test('voice planning prices, dates and duration numbers never become frame progress', () => {
  for (const message of ['Estimated cost $0.02', 'October 15, 2026', 'Checking a 1920x1080 image', 'A 5-second voiceover']) {
    const result = overlay(run(message));
    assert.match(result, /Working…/);
    assert.doesNotMatch(result, /frames|Shot|Shooting/);
  }
});

test('only explicit valid active render frame counts produce visual progress', () => {
  for (const message of ['Rendering 12 of 150 frames', 'Rendering 0/150 frames']) {
    assert.match(overlay(run('', { toolEvents: [{ status: 'running', summary: message }] })), /Rendering….*(?:12|0) of 150 frames/);
  }
  assert.match(overlay(run('', { progressEvents: [{ type: 'MEDIA_WAIT', status: 'running', message: '24/48 frames' }] })), /24 of 48 frames/);
  for (const message of ['99 of 10 frames', '0/0 frames', '100 200', '9007199254740992/9007199254740993 frames']) {
    assert.doesNotMatch(overlay(run('', { toolEvents: [{ status: 'running', summary: message }] })), /frames|Rendering/);
  }
});

test('completed tools, model narrative and other conversations cannot invent active frame counts', () => {
  assert.doesNotMatch(overlay(run('12 of 150 frames')), /frames|Rendering/);
  assert.doesNotMatch(overlay(run('', { toolEvents: [{ status: 'completed', summary: '12 of 150 frames' }] })), /frames|Rendering/);
  assert.equal(overlay(run('12/150 frames', { conversationId: 'other' })), null);
  for (const status of ['completed', 'failed', 'error', 'awaiting_approval']) {
    assert.equal(overlay(run('12/150 frames', { status })), null);
  }
});
