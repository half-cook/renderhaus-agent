const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const load = require('./load-ts.cjs');
const story = load('lib/canvas/story.ts');
const timeline = load('lib/rh/timeline.ts');

const data = (config = {}, extra = {}) => ({ kind: 'video', title: 'Shot', status: 'completed', config, ...extra });
const output = (versionId = 'portrait') => ({ assetId: versionId, versionId, kind: 'video', filename: 'clip.mp4', mimeType: 'video/mp4' });

test('non-finite dimensions and invalid ratios never escape into canvas geometry', () => {
  for (const pair of [[NaN, 720], [Infinity, 720], [720, -Infinity], [0, 1], [-1, 1]]) {
    assert.equal(story.aspectRatioFromDimensions(...pair), undefined);
  }
  for (const ratio of ['0:9', '16:0', '0:0', 'adaptive', '16:9oops', `${'9'.repeat(400)}:1`]) {
    assert.equal(story.numericAspectRatio(ratio), undefined);
    assert.deepEqual(story.nodeFrameSize(data({ aspect_ratio: ratio })), { width: 101, height: 101 });
  }
  assert.equal(story.aspectRatioFromDimensions(1080, 1920), '9:16');
});

test('portrait, square and landscape frames retain their ratios inside the canvas ceiling', () => {
  for (const ratio of ['9:16', '1:1', '16:9', '5:1', '1:5']) {
    const frame = story.nodeFrameSize(data({ aspect_ratio: ratio, resolution: '480p' }));
    assert.ok(frame.width > 0 && frame.height > 0);
    assert.ok(frame.width <= 420 && frame.height <= 420, `${ratio} exceeds canvas bounds`);
    assert.ok(Math.abs(frame.width / frame.height - story.numericAspectRatio(ratio)) < 0.03);
  }
});

test('source ratio and fractional duration override display only for the matching output version', () => {
  const config = { aspect_ratio: '16:9', duration_seconds: 10 };
  const node = data(config, { output: output(), outputMetadata: { versionId: 'portrait', width: 1080, height: 1900, durationSeconds: 4.73 } });
  assert.equal(story.sourceAspectRatio(node), 1080 / 1900);
  assert.equal(story.sourceDuration(node), 4.73);
  assert.equal(story.durationLabel(node), '4.73s');
  assert.equal(config.aspect_ratio, '16:9');
  assert.equal(config.duration_seconds, 10);
  const otherVersion = { ...node, output: output('landscape') };
  assert.equal(story.sourceAspectRatio(otherVersion), 16 / 9);
  assert.equal(story.sourceDuration(otherVersion), 10);
});

test('completed portrait and square media fill the card minimum without changing their ratio', () => {
  assert.deepEqual(story.nodeFrameSize(data({}, { output: output() })), { width: 101, height: 101 });
  for (const [width, height] of [[360, 640], [512, 512], [1280, 720]]) {
    const frame = story.nodeFrameSize(data({}, {
      output: output(), outputMetadata: { versionId: 'portrait', width, height },
    }));
    assert.ok(frame.width >= 200, `${width}x${height} leaves an empty strip in the card`);
    assert.ok(Math.max(frame.width, frame.height) <= 420);
    assert.ok(Math.abs(frame.width / frame.height - width / height) < 0.01);
  }
});

test('uploads with empty generation config enter the timeline at their real duration', () => {
  const clips = timeline.clipsFromNodes([{ id: 'upload', position: { x: 1, y: 1 }, data: data({}, {
    output: output(), outputMetadata: { versionId: 'portrait', width: 1080, height: 1920, durationSeconds: 4.73 },
  }) }]);
  assert.equal(clips.length, 1);
  assert.equal(clips[0].sourceSeconds, 4.73);
  assert.equal(clips[0].trimOut, 4.73);
});

test('a source shorter than the usual trim minimum never acquires a negative in-point', () => {
  const [clip] = timeline.clipsFromNodes([{ id: 'short', position: { x: 1, y: 1 }, data: data({}, {
    output: output(), outputMetadata: { versionId: 'portrait', durationSeconds: 0.3 },
  }) }]);
  assert.equal(clip.trimIn, 0);
  assert.equal(clip.trimOut, 0.3);
  assert.deepEqual(timeline.trimEdge(clip, 'in', 1), { trimIn: 0, trimOut: 0.3 });
  assert.deepEqual(timeline.trimEdge(clip, 'out', -1), { trimIn: 0, trimOut: 0.3 });
});

function sceneMedia(state) {
  const source = fs.readFileSync(path.join(__dirname, '../components/canvas/nodes/SceneCard.tsx'), 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const exported = {};
  const AssetMedia = () => null;
  const store = Object.assign((selector) => selector(state), { getState: () => state });
  const mocks = {
    '@xyflow/react': { Handle: () => null, Position: { Left: 'left', Right: 'right' } },
    'lucide-react': { Loader2: () => null },
    '../NodeToolbar': { NodeToolbar: () => null },
    './NodeTag': { NodeTag: () => null },
    '@/lib/canvas/generate-readiness': { generateBlockers: () => [] },
    '@/lib/canvas/story': story,
    '@/lib/canvas/types': { schemaFor: () => undefined },
    '@/lib/canvas/store': { useCanvasStore: store },
    '@/lib/canvas/tool-registry': { portsForNode: () => ({ inputs: [], outputs: [] }) },
    '../AssetMedia': { AssetMedia },
    '@/lib/rh/money': { formatCents: () => '' },
    '@/lib/rh/billing': { toNodeEstimate: () => undefined },
  };
  new Function('require', 'exports', js)((name) => mocks[name] ?? require(name), exported);
  const find = (element) => {
    if (!element || typeof element !== 'object') return;
    if (element.type === AssetMedia) return element;
    for (const child of [element.props?.children].flat(Infinity)) {
      const match = find(child);
      if (match) return match;
    }
  };
  return find(exported.SceneCard({ id: 'shot', data: state.nodes[0].data }));
}

test('preview metadata preserves generation preferences and ignores a stale variant load', () => {
  const initial = data({ aspect_ratio: '16:9', duration_seconds: 10 }, { output: output() });
  const state = { nodes: [{ id: 'shot', data: initial }], providers: [], edges: [] };
  const patches = [];
  state.updateNodeData = (id, patch) => { patches.push(patch); state.nodes[0].data = { ...state.nodes[0].data, ...patch }; };
  const media = sceneMedia(state);
  media.props.onMetadata({ width: 1080, height: 1920, durationSeconds: 4.73 });
  assert.equal(patches.length, 1);
  assert.deepEqual(state.nodes[0].data.config, { aspect_ratio: '16:9', duration_seconds: 10 });
  assert.equal(state.nodes[0].data.outputMetadata.durationSeconds, 4.73);
  media.props.onMetadata({ width: 1080, height: 1920, durationSeconds: 4.73 });
  assert.equal(patches.length, 1, 'same metadata does not trigger another save');
  state.nodes[0].data = { ...state.nodes[0].data, output: output('landscape') };
  media.props.onMetadata({ width: 1080, height: 1920, durationSeconds: 4.73 });
  assert.equal(patches.length, 1, 'late events cannot overwrite a different current version');
});
