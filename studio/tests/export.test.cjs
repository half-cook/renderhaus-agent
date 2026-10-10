const test = require('node:test');
const assert = require('node:assert/strict');
const load = require('./load-ts.cjs');
const { exportModel } = load('lib/rh/export.ts');

test('a disconnected export carries no fabricated price or video metadata', () => {
  const model = exportModel({ state: 'disconnected' });
  assert.equal(model.state, 'disconnected');
  assert.equal(model.estimate, null);
  assert.equal(model.resolution, null);
  assert.equal(model.sizeBytes, null);
});
test('export uses only server estimate and cap cents, never a line sum', () => {
  const model = exportModel({ state: 'configure', format: 'mp4', resolution: '720p', size_bytes: 1200000,
    estimate: { estimate_cents: 0, cap_cents: 0, lines: [{ kind: 'media', label: 'Studio render', price_cents: 99 }] } });
  assert.equal(model.estimate.estimateCents, 0);
  assert.equal(model.estimate.capCents, 0);
  assert.equal(model.sizeBytes, 1200000);
});
test('missing or fractional money cannot turn on a render approval', () => {
  for (const estimate of [undefined, { lines: [{ price_cents: 100 }] }, { estimate_cents: 10.5, cap_cents: 20 }, { estimate_cents: 10 }]) {
    assert.equal(exportModel({ state: 'configure', estimate }).estimate, null);
  }
});
test('done requires a safe download path and neutral format', () => {
  assert.equal(exportModel({ state: 'done', download_path: '/beta/p1-film.mp4', format: 'mp4' }).state, 'done');
  for (const download_path of ['javascript:alert(1)', '//example.com/film', 'https://example.com/private?token=secret']) {
    assert.equal(exportModel({ state: 'done', download_path }).state, 'disconnected');
  }
});
