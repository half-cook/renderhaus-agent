const test = require('node:test');
const assert = require('node:assert/strict');
const load = require('./load-ts.cjs');

const { finishingComparison } = load('lib/rh/finishing-preview.ts');
const comparison = {
  before_version_id: 'source-preview', after_version_id: 'finished-preview',
  duration_seconds: 3, source_start_seconds: 2, full_estimated_cost_cents: 156,
  source_width: 960, source_height: 540, output_width: 1920, output_height: 1080,
  source_fps: 30, output_fps: 60,
};

test('comparison uses owned asset versions and preserves measured timing and the full quote', () => {
  const result = finishingComparison({ comparison });
  assert.equal(result.before.versionId, 'source-preview');
  assert.equal(result.after.versionId, 'finished-preview');
  assert.equal(result.duration, 3);
  assert.equal(result.sourceStart, 2);
  assert.equal(result.fullEstimateCents, 156);
  assert.equal(result.sourceFps, 30);
  assert.equal(result.outputFps, 60);
});

test('missing, forged URL, long, nonfinite, or same-source comparisons cannot enable review', () => {
  for (const item of [null, {}, { ...comparison, before_version_id: 'https://example.test/a' },
    { ...comparison, after_version_id: comparison.before_version_id },
    { ...comparison, duration_seconds: 0 }, { ...comparison, duration_seconds: 3.1 },
    { ...comparison, source_start_seconds: -1 }, { ...comparison, output_fps: NaN },
    { ...comparison, output_width: '1920' }, { ...comparison, full_estimated_cost_cents: 1.2 },
    { ...comparison, duration_seconds: 0.01 }, { ...comparison, source_fps: Number.MIN_VALUE }]) {
    assert.equal(finishingComparison({ comparison: item }), null);
  }
});

test('unknown full prices remain unknown rather than becoming zero', () => {
  assert.equal(finishingComparison({ comparison: { ...comparison, full_estimated_cost_cents: null } }).fullEstimateCents, null);
});

test('a measured single-frame source accepts ffprobe decimal rounding', () => {
  const result = finishingComparison({ comparison: { ...comparison, duration_seconds: 0.033333, covers_full_source: true } });
  assert.equal(result.coversFullSource, true);
  assert.equal(result.duration, 0.033333);
});
