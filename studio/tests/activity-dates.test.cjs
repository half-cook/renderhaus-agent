const test = require('node:test');
const assert = require('node:assert/strict');
const load = require('./load-ts.cjs');
const { formatActivityTime } = load('lib/rh/dates.ts');

process.env.TZ = 'America/Toronto';

test('only the same local calendar day is labeled Today', () => {
  const now = new Date('2026-10-16T04:15:00Z');
  assert.equal(formatActivityTime(Date.parse('2026-10-16T04:05:00Z'), now), 'Today 12:05 AM');
  assert.equal(formatActivityTime(Date.parse('2026-10-16T03:30:00Z'), now), 'Oct 15, 2026 11:30 PM');
});

test('older activity includes the year rather than implying today', () => {
  assert.equal(formatActivityTime(Date.parse('2025-10-16T16:00:00Z'), new Date('2026-10-16T16:00:00Z')), 'Oct 16, 2025 12:00 PM');
});

test('invalid activity time is explicit', () => {
  assert.equal(formatActivityTime(NaN), 'Time unavailable');
});
