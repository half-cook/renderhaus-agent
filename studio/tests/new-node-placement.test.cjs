const test = require('node:test');
const assert = require('node:assert/strict');
const { newNodePosition } = require('./load-ts.cjs')('lib/canvas/new-node-placement.ts');
const { nodeFrameSize } = require('./load-ts.cjs')('lib/canvas/story.ts');

function node(id, x, y, extra = {}) {
  return { id, position: { x, y }, data: { kind: 'image', title: 'Scene', status: 'idle',
    config: { aspect_ratio: '16:9', size: '2K' }, ...extra } };
}

test('an empty or already clear canvas preserves the requested insertion point', () => {
  const incoming = node('new', 150, 200);
  assert.deepEqual(newNodePosition(incoming, []), incoming.position);
  assert.deepEqual(newNodePosition(incoming, [node('far-away', 150, 1500)]), incoming.position);
});

test('the Add scene then portrait upload reproduction only moves the new card', () => {
  const old = { ...node('old', 910.75, 335.49), measured: { width: 420, height: 282 } };
  const incoming = node('portrait', 1054, 502, { output: { versionId: 'upload', kind: 'image' }, config: {} });
  const before = structuredClone([old, incoming]);
  const placed = newNodePosition(incoming, [old]);
  assert.ok(placed.x >= old.position.x + old.measured.width + 40);
  assert.equal(placed.y, 502);
  assert.deepEqual([old, incoming], before);
});

test('unknown media reserves room for both future portrait and landscape dimensions', () => {
  const loading = node('loading', 0, 0, { output: { versionId: 'loading', kind: 'image' }, config: {} });
  const placed = newNodePosition(node('next', 180, 380), [loading]);
  assert.ok(placed.x >= 460, 'unknown portrait height must not leave a collision below its placeholder');
});

test('empty generation scenes reserve room before their actual media enlarges', () => {
  for (const [kind, width, height] of [['video', 1280, 720], ['image', 720, 1280]]) {
    for (const status of ['idle', 'running']) {
      const data = { kind, status, config: { resolution: '720p', aspect_ratio: `${width}:${height}` } };
      const frame = nodeFrameSize(data);
      const existing = { ...node('generation', 0, 0, data), measured: { width: Math.max(200, frame.width), height: frame.height + 46 } };
      const incoming = node('new', kind === 'video' ? existing.measured.width + 40 : 0,
        kind === 'image' ? existing.measured.height + 140 : 0, { kind: 'text', config: {} });
      const before = structuredClone([existing, incoming]);
      const placed = newNodePosition(incoming, [existing]);
      const completedFrame = nodeFrameSize({ ...existing.data, output: { versionId: 'generated', kind },
        outputMetadata: { versionId: 'generated', width, height } });
      assert.ok(placed.x >= Math.max(200, completedFrame.width) + 40
        || placed.y - 90 >= completedFrame.height + 46 + 40, `${kind} ${status} leaves room for its final frame`);
      assert.deepEqual([existing, incoming], before);
    }
  }
});

test('known output dimensions keep the existing precise spacing', () => {
  const existing = node('portrait', 0, 0, { output: { versionId: 'known', kind: 'image' },
    outputMetadata: { versionId: 'known', width: 720, height: 1280 }, config: {} });
  const incoming = node('text', 240, 0, { kind: 'text', config: {} });
  assert.deepEqual(newNodePosition(incoming, [existing]), incoming.position);
});

test('measured larger cards and zoom-independent toolbar overhang remain clear', () => {
  const existing = { ...node('large', 0, 0), measured: { width: 700, height: 600 } };
  const incoming = node('new', 100, 500);
  const placed = newNodePosition(incoming, [existing], .5);
  // Existing unscaled title can extend to 1400; the new toolbar extends 108 left.
  assert.ok(placed.x - 108 >= 1400 + 40);
});

test('a vertical gap in card bodies still reserves room for the title and toolbar', () => {
  const old = { ...node('old', 0, 0), measured: { width: 420, height: 282 } };
  const placed = newNodePosition(node('new', 0, 320), [old]);
  assert.ok(placed.x >= 460);
});

test('repeated insertions clear an unsorted crowded row without changing old positions', () => {
  const nodes = [node('right', 1000, 0), node('left', 0, 0), node('middle', 500, 0)];
  const before = structuredClone(nodes);
  const placed = newNodePosition(node('new', 100, 0), nodes);
  assert.ok(placed.x >= 1460);
  assert.deepEqual(nodes, before);
  const next = newNodePosition(node('another', 100, 0), [...nodes, node('new', placed.x, placed.y)]);
  assert.ok(next.x >= placed.x + 460);
});

test('hidden nodes do not block placement and invalid zoom uses the normal canvas scale', () => {
  const incoming = node('new', 0, 0);
  assert.deepEqual(newNodePosition(incoming, [{ ...node('hidden', 0, 0), hidden: true }]), incoming.position);
  assert.deepEqual(newNodePosition(incoming, [node('old', 0, 0)], NaN),
    newNodePosition(incoming, [node('old', 0, 0)], 1));
});

test('manual and agent insertions keep history reversible and preserve existing coordinates', () => {
  const { useCanvasStore } = require('./load-ts.cjs')('lib/canvas/store.ts');
  const previous = useCanvasStore.getState();
  const old = node('existing', 0, 0);
  useCanvasStore.setState({ nodes: [old], edges: [], past: [], future: [], viewport: { x: 0, y: 0, zoom: 1 },
    persist: async () => {} });
  try {
    const manualId = useCanvasStore.getState().addCreativeNode({ kind: 'image', position: { x: 0, y: 0 } });
    const manual = useCanvasStore.getState().nodes.find((item) => item.id === manualId);
    assert.ok(manual.position.x > old.position.x);
    assert.deepEqual(useCanvasStore.getState().nodes[0].position, old.position);
    useCanvasStore.getState().undo();
    assert.deepEqual(useCanvasStore.getState().nodes, [old]);
    useCanvasStore.getState().redo();
    assert.deepEqual(useCanvasStore.getState().nodes.find((item) => item.id === manualId).position, manual.position);
    const agentId = useCanvasStore.getState().placeAgentAsset({ asset: { versionId: 'asset', kind: 'image' },
      position: { x: 0, y: 0 }, executionId: 'run' });
    const agent = useCanvasStore.getState().nodes.find((item) => item.id === agentId);
    assert.ok(agent.position.x > manual.position.x);
    assert.deepEqual(useCanvasStore.getState().nodes[0].position, old.position);
    assert.equal(agent.data.agentRunId, 'run');
  } finally {
    useCanvasStore.setState(previous);
  }
});
