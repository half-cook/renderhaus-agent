const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const cache = new Map();
function load(file) {
  const absolute = path.resolve(__dirname, '..', file);
  if (cache.has(absolute)) return cache.get(absolute);
  const js = ts.transpileModule(fs.readFileSync(absolute, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const exported = {};
  cache.set(absolute, exported);
  new Function('require', 'exports', js)((name) => {
    if (name.startsWith('@/')) return load(`${name.slice(2)}.ts`);
    if (name.startsWith('.')) return load(path.relative(path.resolve(__dirname, '..'), path.resolve(path.dirname(absolute), `${name}.ts`)));
    return require(name);
  }, exported);
  return exported;
}
const changes = load('lib/rh/changes.ts');
const fixtures = load('lib/rh/changes-fixtures.ts');
const doc = () => fixtures.changesDocument();

test('preview is separate from the cut until each change is accepted', () => {
  const value = doc();
  assert.equal(changes.withChangesCut(value).slots[1].outMs, 4200);
  assert.equal(value.currentCut.slots[1].outMs, 5000);
  assert.equal(changes.needYou(value), 2);
  assert.deepEqual(changes.freeChanges(value).map((item) => item.n), [2]);
});

test('free bulk acceptance cannot apply the already charged paid take', () => {
  const next = changes.acceptFreeChanges(doc());
  assert.equal(next.changes[0].state, 'ready');
  assert.equal(next.changes[1].state, 'accepted');
  assert.equal(next.currentCut.slots[1].takeId, 'shot-2-take-1');
  assert.equal(next.currentCut.slots[1].outMs, 4200);
  assert.equal(next.changeset.actualCents, 95);
});

test('zero charged on an incomplete paid quote is never treated as a free change', () => {
  const value = doc();
  value.changes[0].costCents = 0;
  value.changes[0].taken = false;
  value.changes[0].approval = { ...value.newTakeApproval, estimateCents: 0, capCents: 0, estimateIncomplete: true };
  assert.deepEqual(changes.freeChanges(value).map((item) => item.n), [2]);
  const next = changes.transitionChange(value, 1, 'accept');
  assert.equal(next.changes[0].state, 'ready');
  assert.equal(next.currentCut.slots[1].takeId, 'shot-2-take-1');
});

test('take and trim on one slot can be accepted in either order', () => {
  for (const order of [[1, 2], [2, 1]]) {
    let next = doc();
    for (const n of order) next = changes.transitionChange(next, n, 'accept');
    assert.equal(next.currentCut.slots[1].takeId, 'shot-2-take-2');
    assert.equal(next.currentCut.slots[1].outMs, 4200);
    assert.deepEqual(next.changes.slice(0, 2).map((item) => item.state), ['accepted', 'accepted']);
    assert.equal(next.changeset.actualCents, 95);
  }
});

test('paid output cannot be accepted before it has been taken', () => {
  const value = doc();
  value.changes[0].state = 'awaiting_approval';
  value.changes[0].taken = false;
  const next = changes.transitionChange(value, 1, 'accept');
  assert.equal(next.changes[0].state, 'awaiting_approval');
  assert.equal(next.currentCut.slots[1].takeId, 'shot-2-take-1');
});

test('reject undo accept and revert keep every paid take and price', () => {
  let next = changes.transitionChange(doc(), 1, 'reject');
  assert.equal(next.changes[0].state, 'rejected');
  assert.equal(next.takes.length, 4);
  next = changes.transitionChange(next, 1, 'undo');
  assert.equal(next.changes[0].state, 'ready');
  next = changes.transitionChange(next, 1, 'accept');
  next = changes.transitionChange(next, 1, 'revert');
  assert.equal(next.changes[0].state, 'reverted');
  assert.equal(next.currentCut.slots[1].takeId, 'shot-2-take-1');
  next = changes.transitionChange(next, 1, 'reapply');
  assert.equal(next.currentCut.slots[1].takeId, 'shot-2-take-2');
  assert.equal(next.changeset.actualCents, 95);
});

test('an existing rejected take can be chosen without additional charges', () => {
  const next = changes.transitionChange(doc(), 1, 'accept', { takeId: 'shot-2-take-3' });
  assert.equal(next.currentCut.slots[1].takeId, 'shot-2-take-3');
  assert.equal(next.changes[0].afterRef.takeId, 'shot-2-take-3');
  assert.equal(next.changeset.actualCents, 95);
});

test('choosing an incompatible shorter take preserves the original proposal and cut', () => {
  const value = doc();
  value.takes.find((take) => take.id === 'shot-2-take-3').durationMs = 4000;
  const next = changes.transitionChange(value, 1, 'accept', { takeId: 'shot-2-take-3' });
  assert.deepEqual(next, value);
  assert.equal(next.changes[0].afterRef.takeId, 'shot-2-take-2');
  assert.equal(next.currentCut.slots[1].takeId, 'shot-2-take-1');
});

test('a different ready change cannot select an untaken paid result', () => {
  const value = doc();
  value.changes[0].state = 'awaiting_approval';
  value.changes[0].taken = false;
  value.changes.push({ ...value.changes[0], id: 'other-take-change', n: 5, state: 'ready', costCents: 0, taken: true, afterRef: { kind: 'take', takeId: 'shot-2-take-3' } });
  const next = changes.transitionChange(value, 5, 'accept', { takeId: 'shot-2-take-2' });
  assert.deepEqual(next, value);
  assert.equal(next.currentCut.slots[1].takeId, 'shot-2-take-1');
  value.changes.at(-1).afterRef.takeId = 'shot-2-take-2';
  assert.deepEqual(changes.transitionChange(value, 5, 'accept'), value);
  assert.equal(changes.withChangesCut(value).slots[1].takeId, 'shot-2-take-1');
});

test('stale references and expected revisions become out of date without touching the cut', () => {
  const stale = doc();
  stale.currentCut.slots[1].takeId = 'shot-2-take-3';
  const next = changes.transitionChange(stale, 1, 'accept');
  assert.equal(next.changes[0].state, 'out_of_date');
  assert.equal(next.currentCut.slots[1].takeId, 'shot-2-take-3');
  const revision = changes.transitionChange(doc(), 2, 'accept', { expectedRevision: 99 });
  assert.equal(revision.changes[1].state, 'out_of_date');
  assert.equal(revision.currentCut.slots[1].outMs, 5000);
});

test('trim equal to the source length is valid but zero length is out of date', () => {
  const equal = doc();
  equal.changes[1].afterRef.outMs = 5000;
  assert.equal(changes.transitionChange(equal, 2, 'accept').changes[1].state, 'accepted');
  const empty = doc();
  empty.changes[1].afterRef.inMs = 4200;
  const next = changes.transitionChange(empty, 2, 'accept');
  assert.equal(next.changes[1].state, 'out_of_date');
  assert.equal(next.currentCut.slots[1].outMs, 5000);
});

test('restoring a checkpoint creates a new version and preserves the checkpoint', () => {
  const value = changes.acceptFreeChanges(doc());
  const next = changes.restoreCheckpoint(value, { id: 'restored-cut', createdAt: 123 });
  assert.equal(next.currentCut.id, 'restored-cut');
  assert.equal(next.currentCut.slots[1].outMs, 5000);
  assert.equal(next.checkpointCut.id, 'cut-before-7');
  assert.equal(next.versions.at(-1).id, 'restored-cut');
  assert.equal(next.versions.at(-2).id, value.currentCut.id);
  assert.equal(next.versions.at(-2).slots[1].outMs, 4200);
  assert.equal(next.changes[1].state, 'reverted');
});

test('restore preserves a changed current snapshot when its ID already names an older version', () => {
  const value = changes.transitionChange(doc(), 1, 'accept');
  const older = structuredClone(value.currentCut);
  older.slots[1].takeId = 'shot-2-take-1';
  value.versions.push(older);
  const next = changes.restoreCheckpoint(value);
  const saved = next.versions.find((cut) => cut.slots[1].takeId === 'shot-2-take-2');
  assert.ok(saved);
  assert.notEqual(saved.id, older.id);
  assert.equal(next.versions.find((cut) => cut.id === older.id).slots[1].takeId, 'shot-2-take-1');
});

test('long voiceover can be trimmed to the accepted cut without creating a lane', () => {
  const value = changes.acceptFreeChanges(doc());
  value.currentCut.voiceDurationMs = 11000;
  const next = changes.trimVoiceToFit(value);
  assert.equal(next.currentCut.voiceDurationMs, 9200);
  assert.equal(changes.cutClips(next, next.currentCut).length, 2);
});

test('unknown payload parsing sanitizes copy and rejects invalid cents instead of inventing free changes', () => {
  const value = doc();
  value.changes[0].title = 'OpenAI branch fee 12%';
  const parsed = changes.parseChangesDocument(value);
  assert.equal(parsed.changes[0].title, 'Change 1');
  for (const invalid of [null, -1, 0.65, '65', Number.NaN]) {
    const bad = doc();
    bad.changes[1].costCents = invalid;
    assert.equal(changes.parseChangesDocument(bad), null);
  }
  assert.equal(changes.parseChangesDocument({}), null);
});

test('state fixtures contain twelve valid documents including audio and still image changes', () => {
  const variants = fixtures.changesStateVariants();
  assert.equal(variants.length, 12);
  assert.equal(variants.at(-2).document.changes[0].kind, 'voice');
  assert.equal(variants.at(-1).document.changes[0].kind, 'still');
  for (const item of variants) assert.ok(changes.parseChangesDocument(item.document), item.title);
});

test('manual cut edits make affected pending proposals out of date while preserving unrelated proposals', () => {
  const value = doc();
  const cut = structuredClone(value.currentCut);
  cut.slots[1].outMs = 4800;
  const next = changes.editChangesCut(value, cut);
  assert.equal(next.changes[0].state, 'ready');
  assert.equal(next.changes[1].state, 'out_of_date');
  assert.equal(next.currentCut.slots[1].outMs, 4800);
  assert.notEqual(next.currentCut.id, value.currentCut.id);
});

test('manual cut edits cannot bypass approval or replace voice and still media', () => {
  const value = doc();
  value.changes[0].state = 'awaiting_approval';
  value.changes[0].taken = false;
  const edits = [
    (cut) => { cut.slots[1].takeId = 'shot-2-take-2'; },
    (cut) => { cut.voiceRef = '/unapproved-voice.wav'; },
    (cut) => { cut.voiceDurationMs = 1000; },
    (cut) => { cut.stillRefs['n-shot1'] = '/unapproved-still.jpg'; },
  ];
  for (const edit of edits) {
    const cut = structuredClone(value.currentCut);
    edit(cut);
    const next = changes.editChangesCut(value, cut);
    assert.deepEqual(next, value);
  }
});

test('manual cut edits permit reordering and removing existing slots', () => {
  const value = doc();
  const reordered = changes.editChangesCut(value, { ...value.currentCut, order: ['n-shot2', 'n-shot1'] });
  assert.deepEqual(reordered.currentCut.order, ['n-shot2', 'n-shot1']);
  const removed = changes.editChangesCut(value, { ...value.currentCut, slots: [value.currentCut.slots[0]], order: ['n-shot1'] });
  assert.equal(removed.currentCut.slots.length, 1);
  assert.equal(removed.currentCut.slots[0].takeId, 'shot-1-take-1');
});

test('deleting a still target marks the proposal stale and prevents an orphan image swap', () => {
  const value = fixtures.changesStateVariants().find((item) => item.id === 'still').document;
  const cut = { ...value.currentCut, slots: [value.currentCut.slots[1]], order: ['n-shot2'] };
  const edited = changes.editChangesCut(value, cut);
  assert.equal(edited.changes[0].state, 'out_of_date');
  const deleted = { ...value, currentCut: cut };
  const next = changes.transitionChange(deleted, 1, 'accept');
  assert.equal(next.changes[0].state, 'out_of_date');
  assert.equal(next.currentCut.stillRefs['n-shot1'], '/beta/still-mug.jpg');
});

test('cut parsing rejects malformed media metadata instead of dropping it', () => {
  for (const patch of [{ voiceRef: { url: '/voice.wav' } }, { stillRefs: [] }, { stillRefs: { 'n-shot1': 45 } }]) {
    assert.equal(changes.parseCut({ ...doc().currentCut, ...patch }), null);
  }
});

test('fixture store actions update the authoritative cut and stay in fixture mode', async () => {
  const { useChangesStore } = load('lib/rh/changes-store.ts');
  useChangesStore.getState().seed(doc());
  useChangesStore.getState().openCompare(1);
  await useChangesStore.getState().acceptFree();
  await useChangesStore.getState().acceptTake(1, 'shot-2-take-3');
  const state = useChangesStore.getState();
  assert.equal(state.mode, 'fixture');
  assert.equal(state.document.currentCut.slots[1].outMs, 4200);
  assert.equal(state.document.currentCut.slots[1].takeId, 'shot-2-take-3');
  assert.equal(state.compareN, 1);
  assert.equal(state.error, null);
});

test('API load failure clears fixture state and reports an error instead of falling back', async (t) => {
  const http = require('node:http');
  const server = http.createServer((_, response) => { response.writeHead(503); response.end('unavailable'); });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const originalFetch = global.fetch;
  const origin = `http://127.0.0.1:${server.address().port}`;
  global.fetch = (url, options) => originalFetch(new URL(url, origin), options);
  t.after(() => { global.fetch = originalFetch; });
  const { useChangesStore } = load('lib/rh/changes-store.ts');
  useChangesStore.getState().seed(doc());
  await useChangesStore.getState().load('real-project');
  assert.equal(useChangesStore.getState().mode, 'api');
  assert.equal(useChangesStore.getState().document, null);
  assert.equal(useChangesStore.getState().error, 'Changes could not be loaded. Try again.');
});

test('choosing another taken result is atomic from accepted rejected and reverted rows', () => {
  for (const state of ['accepted', 'rejected', 'reverted']) {
    let value = doc();
    if (state === 'rejected') value = changes.transitionChange(value, 1, 'reject');
    else value = changes.transitionChange(value, 1, 'accept');
    if (state === 'reverted') value = changes.transitionChange(value, 1, 'revert');
    const next = changes.transitionChange(value, 1, 'accept', { takeId: 'shot-2-take-3' });
    assert.equal(next.currentCut.slots[1].takeId, 'shot-2-take-3', state);
    assert.equal(next.changes[0].state, 'accepted');
    assert.equal(next.revision, value.revision + 1);
    assert.equal(next.changeset.actualCents, 95);
  }
});

test('voice trim can fit the displayed proposed cut without accepting its pending changes', () => {
  const value = doc();
  value.currentCut.voiceDurationMs = 11000;
  const next = changes.trimVoiceToFit(value, changes.withChangesCut(value));
  assert.equal(next.currentCut.voiceDurationMs, 9200);
  assert.equal(next.currentCut.slots[1].outMs, 5000);
  assert.equal(next.changes[1].state, 'proposed');
});

test('API mutation applies optimistically and rolls back if persistence fails', async (t) => {
  const http = require('node:http');
  let release;
  const waiting = new Promise((resolve) => { release = resolve; });
  const server = http.createServer(async (request, response) => {
    if (request.method === 'GET') { response.setHeader('content-type', 'application/json'); response.end(JSON.stringify({ items: [doc()] })); }
    else { await waiting; response.writeHead(503); response.end('unavailable'); }
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const originalFetch = global.fetch;
  const origin = `http://127.0.0.1:${server.address().port}`;
  global.fetch = (url, options) => originalFetch(new URL(url, origin), options);
  t.after(() => { global.fetch = originalFetch; });
  const { useChangesStore } = load('lib/rh/changes-store.ts');
  await useChangesStore.getState().load('demo-matte-mug');
  const pending = useChangesStore.getState().acceptFree();
  assert.equal(useChangesStore.getState().document.currentCut.slots[1].outMs, 4200);
  release();
  await pending;
  assert.equal(useChangesStore.getState().document.currentCut.slots[1].outMs, 5000);
  assert.equal(useChangesStore.getState().document.changes[1].state, 'proposed');
  assert.ok(useChangesStore.getState().error);
});

test('Changes price cards use real approval paused-cap and receipt payloads without recomputing cents', () => {
  const docs = fs.readFileSync(path.join(__dirname, '../../docs/BILLING.md'), 'utf8').split('## Orchestration billing, run holds and caps')[1];
  const examples = [...docs.matchAll(/```json\s*([\s\S]*?)```/g)].map((match) => JSON.parse(match[1]));
  for (const payload of [examples.find((item) => item.call_id), examples.find((item) => item.type === 'paused_cap'), examples.find((item) => item.type === 'receipt')]) {
    const value = doc();
    value.changes[0].approval = { id: 'real-price', title: 'New take', estimateCents: 97, [payload.type === 'paused_cap' ? 'paused_cap' : payload.type === 'receipt' ? 'receipt' : 'billing']: payload };
    const parsed = changes.parseChangesDocument(value);
    assert.ok(parsed?.changes[0].approval);
    const model = parsed.changes[0].approval;
    assert.equal(model.estimateCents, payload.estimate_cents ?? 97); assert.equal(model.capCents, payload.cap_cents);
    if (payload.type === 'receipt') assert.equal(model.actualCents, payload.actual_cents);
    if (payload.type === 'paused_cap') assert.deepEqual(model.raiseOptionsCents, payload.raise_options_cents);
  }
});

test('malformed approval pricing cannot turn an untaken zero-cost change into free work', () => {
  const value = doc(); value.changes[0].costCents = 0; value.changes[0].taken = false;
  value.changes[0].approval = { id: 'bad-price', estimateCents: '65', capCents: 150, lines: [], specs: [], status: 'pending' };
  assert.equal(changes.parseChangesDocument(value), null);
});
