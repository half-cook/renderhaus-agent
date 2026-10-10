const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function load(file, mocks = {}) {
  const source = fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const exported = {};
  new Function('require', 'exports', js)((name) => mocks[name] ?? require(name), exported);
  return exported;
}
const timeline = load('lib/rh/timeline.ts', {
  '@/lib/canvas/story': { approvedSequence: (nodes) => nodes.filter((n) => n.data.approved).sort((a, b) => (a.data.storyOrder ?? 0) - (b.data.storyOrder ?? 0)) },
});

const clip = (patch = {}) => ({ id: 'a', order: 1, title: 'Shot 1', sourceSeconds: 5, trimIn: 0, trimOut: 5, ...patch });

test('trimming snaps to a quarter second and stays inside the source', () => {
  assert.deepEqual({ ...timeline.trimEdge(clip(), 'out', -0.8) }, { trimIn: 0, trimOut: 4.25 });
  assert.equal(timeline.trimEdge(clip(), 'out', 3).trimOut, 5);
  assert.equal(timeline.trimEdge(clip(), 'in', -2).trimIn, 0);
  assert.equal(timeline.trimEdge(clip({ trimIn: 1 }), 'in', 0.3).trimIn, 1.25);
});

test('a clip can never be trimmed below the minimum length', () => {
  assert.equal(timeline.trimEdge(clip(), 'out', -10).trimOut, timeline.MIN_CLIP_SECONDS);
  assert.equal(timeline.trimEdge(clip(), 'in', 10).trimIn, 5 - timeline.MIN_CLIP_SECONDS);
});

test('exact fields: In, Out and Length write through the same limits', () => {
  assert.deepEqual({ ...timeline.setTrimField(clip(), 'length', 3.2) }, { trimIn: 0, trimOut: 3.2 });
  assert.deepEqual({ ...timeline.setTrimField(clip(), 'in', 1) }, { trimIn: 1, trimOut: 5 });
  assert.deepEqual({ ...timeline.setTrimField(clip(), 'out', 99) }, { trimIn: 0, trimOut: 5 });
  assert.deepEqual({ ...timeline.setTrimField(clip(), 'in', Number.NaN) }, { trimIn: 0, trimOut: 5 });
});

test('reorder moves one clip and clamps at both ends', () => {
  assert.deepEqual(timeline.moveClip(['a', 'b', 'c'], 'c', -1), ['a', 'c', 'b']);
  assert.deepEqual(timeline.moveClip(['a', 'b', 'c'], 'a', -5), ['a', 'b', 'c']);
  assert.deepEqual(timeline.moveClip(['a', 'b', 'c'], 'a', 9), ['b', 'c', 'a']);
  assert.deepEqual(timeline.moveClip(['a', 'b'], 'zzz', 1), ['a', 'b']);
});

test('dropping a clip picks the slot by the midpoint of the clips it passes', () => {
  const clips = [clip({ id: 'a', trimOut: 3 }), clip({ id: 'b', trimOut: 2 }), clip({ id: 'c', trimOut: 2 })];
  assert.equal(timeline.dropIndex(clips, 'c', 10), 0);
  assert.equal(timeline.dropIndex(clips, 'c', 3 * 124 + 20), 1);
  assert.equal(timeline.dropIndex(clips, 'a', 9999), 2);
});

test('clips come from the approved sequence in story order, with trims read from node config', () => {
  const node = (id, order, config, extra = {}) => ({ id, position: { x: order * 10, y: 0 }, data: { kind: 'video', title: id, approved: true, storyOrder: order, config, ...extra } });
  const clips = timeline.clipsFromNodes([
    node('two', 1, { duration_seconds: 5, trim_out_seconds: 4.2, thumbnail_url: '/beta/shot-lift.jpg' }),
    node('one', 0, { duration_seconds: 5, trim_in_seconds: 0.5 }),
    node('stillnodur', 2, {}),
  ]);
  assert.deepEqual(clips.map((c) => [c.id, c.order, c.trimIn, c.trimOut]), [['one', 1, 0.5, 5], ['two', 2, 0, 4.2]]);
  assert.equal(clips[1].thumbUrl, '/beta/shot-lift.jpg');
  assert.equal(timeline.totalSeconds(clips), 8.7);
});

test('timecode renders minutes, seconds and frames', () => {
  assert.equal(timeline.timecode(3.25), '00:03:06');
  assert.equal(timeline.timecode(0), '00:00:00');
});


test('seconds parser accepts decimal, comma and timecode, rejects invalid and overflowing input', () => {
  for (const [input, expected] of [['4.2', 4.2], ['0:04.2', 4.2], ['4,2', 4.2], [' 1:30 ', 90], ['0', 0]]) assert.equal(timeline.parseSeconds(input), expected);
  for (const input of ['', '-1', '4 seconds', '1:2:3', 'Infinity', '9'.repeat(400)]) assert.equal(timeline.parseSeconds(input), null);
});
