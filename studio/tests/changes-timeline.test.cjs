const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const load = require('./load-ts.cjs');

const timeline = load('lib/rh/timeline.ts');
function loadTimeline() {
  const file = path.join(__dirname, '../components/changes/ChangesTimeline.tsx');
  if (!fs.existsSync(file)) return {};
  const source = fs.readFileSync(file, 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const exported = {};
  new Function('require', 'exports', js)((name) => {
    if (name === '@/lib/rh/timeline') return timeline;
    if (name.startsWith('@/')) return {};
    return require(name);
  }, exported);
  return exported;
}

const clip = (id, order, length) => ({ id, order, title: `Shot ${order}`, sourceSeconds: length, trimIn: 0, trimOut: length });
const change = (n, kind, slotId) => ({ id: `change-${n}`, n, kind, slotId, state: 'ready', beforeRef: { kind, inMs: 0, outMs: 5000 }, afterRef: { kind, inMs: 0, outMs: 4200 } });

test('several changes on one shot remain separately selectable', () => {
  const { changeTimelineMarkers } = loadTimeline();
  assert.equal(typeof changeTimelineMarkers, 'function');
  const markers = changeTimelineMarkers(Array.from({ length: 12 }, (_, i) => change(i + 1, 'take', 'one')), [clip('one', 1, 5)], 124);
  assert.equal(markers.length, 12);
  assert.ok(markers.some((marker) => marker.left > 0), 'same-shot flags are horizontally offset');
  for (const marker of markers) {
    assert.ok(marker.left >= 0);
    for (const other of markers.filter((other) => other.change.n < marker.change.n && other.row === marker.row)) {
      assert.ok(marker.left >= other.left + other.width || marker.left + marker.width <= other.left, 'flag hit targets do not overlap');
    }
  }
});

test('take markers follow shot start while trim markers follow the removed region', () => {
  const { changeTimelineMarkers } = loadTimeline();
  assert.equal(typeof changeTimelineMarkers, 'function');
  const markers = changeTimelineMarkers([change(1, 'take', 'two'), change(2, 'trim', 'two')], [clip('one', 1, 5), clip('two', 2, 5)], 124);
  assert.equal(markers[0].left, 620);
  assert.equal(markers[1].left, 1140.8);
});

test('markers for a missing shot remain in the list without being attached to another shot', () => {
  const { changeTimelineMarkers } = loadTimeline();
  assert.equal(typeof changeTimelineMarkers, 'function');
  const markers = changeTimelineMarkers([change(1, 'take', 'missing')], [clip('one', 1, 5)], 124);
  assert.equal(markers[0].missingShot, true);
});
