const test = require('node:test');
const assert = require('node:assert/strict');
const load = require('./load-ts.cjs');

const clock = load('lib/rh/compare-clock.ts');

const clip = (id, trimIn, trimOut) => ({ id, trimIn, trimOut });
const before = [clip('shot-1', 0, 5), clip('shot-2', 0, 5)];
const after = [clip('shot-1', 0, 4.2), clip('shot-2', 0.5, 4.7)];

test('shot alignment follows the same shot after an earlier trim', () => {
  const frames = clock.compareFrames({ before, after, seconds: 7.4, alignment: 'shot', fps: 24 });
  assert.equal(frames.before.clipId, 'shot-2');
  assert.equal(frames.after.clipId, 'shot-2');
  assert.equal(frames.before.sourceSeconds, 2.4166666666666665);
  assert.equal(frames.after.sourceSeconds, 2.9166666666666665);
  assert.equal(frames.after.cutSeconds, 6.616666666666667);
});

test('time alignment samples both cuts at the same clock position', () => {
  const frames = clock.compareFrames({ before, after, seconds: 4.5, alignment: 'time', fps: 24 });
  assert.equal(frames.before.clipId, 'shot-1');
  assert.equal(frames.after.clipId, 'shot-2');
  assert.equal(frames.after.sourceSeconds, 0.7916666666666667);
});

test('a shorter take holds its last available frame without advancing to another shot', () => {
  const frames = clock.compareFrames({ before, after: [clip('shot-1', 0, 4.2), clip('shot-2', 0, 5)], seconds: 4.8, alignment: 'shot', fps: 24 });
  assert.equal(frames.after.clipId, 'shot-1');
  assert.equal(frames.after.held, true);
  assert.equal(frames.after.sourceSeconds, 4.166666666666667);
});

test('shot alignment follows a reordered slot by its id', () => {
  const frames = clock.compareFrames({ before, after: [clip('shot-2', 0, 5), clip('shot-1', 0, 5)], seconds: 2, alignment: 'shot' });
  assert.equal(frames.after.clipId, 'shot-1');
  assert.equal(frames.after.cutSeconds, 7);
});

test('missing shots and empty cuts have no invented frame', () => {
  assert.equal(clock.compareFrames({ before, after: [], seconds: 7, alignment: 'shot' }).after, null);
  assert.deepEqual(clock.compareFrames({ before: [], after: [], seconds: 0, alignment: 'time' }), { before: null, after: null });
});

test('frame stepping clamps at the first and last playable frames', () => {
  assert.equal(clock.stepCompareFrame({ seconds: 0, direction: -1, durationSeconds: 5, fps: 24 }), 0);
  assert.equal(clock.stepCompareFrame({ seconds: 1, direction: 1, durationSeconds: 5, fps: 24 }), 25 / 24);
  assert.equal(clock.stepCompareFrame({ seconds: 5, direction: 1, durationSeconds: 5, fps: 24 }), 119 / 24);
});

test('frame timecode carries into the next second and minute', () => {
  assert.equal(clock.compareTimecode(2.4, 24), '00:02:10');
  assert.equal(clock.compareTimecode(59.99, 24), '01:00:00');
  assert.equal(clock.compareTimecode(-1, 24), '00:00:00');
});
