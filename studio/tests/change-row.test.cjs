const assert = require('node:assert/strict');
const test = require('node:test');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const load = require('./load-ts.cjs');
const { ChangeRow } = load('components/changes/ChangeRow.tsx');
const base = { id: 'trim', changesetId: '7', n: 2, kind: 'trim', slotId: 'shot-2', title: 'Trim Shot 2', description: 'Ends as the hand leaves the frame.', state: 'proposed', costCents: 0, taken: false, beforeRef: { kind: 'trim', inMs: 0, outMs: 5000 }, afterRef: { kind: 'trim', inMs: 0, outMs: 4200 } };
const document = { changes: [base], takes: [], currentCut: { slots: [], order: [] }, checkpointCut: { slots: [], order: [] } };
const html = (change = base, props = {}) => renderToStaticMarkup(React.createElement(ChangeRow, { document, change, ...props }));

test('a free trim has a numbered badge, explicit before/after and Accept without a price card', () => {
  const text = html();
  assert.match(text, /Change 2/);
  assert.match(text, /0:05\.0/);
  assert.match(text, /0:04\.2/);
  assert.match(text, />Free</);
  assert.match(text, />Accept</);
  assert.doesNotMatch(text, /Estimated total|Approve/);
});
test('accepted and rejected changes keep their next reversible action in a collapsed row', () => {
  assert.match(html({ ...base, state: 'accepted' }), />Revert</);
  const rejected = html({ ...base, state: 'rejected' });
  assert.match(rejected, />Undo</);
  assert.match(rejected, /data-collapsed="true"/);
  assert.doesNotMatch(rejected, /rh-change-body/);
});
test('out of date requires re-check and never offers Accept', () => {
  const text = html({ ...base, state: 'out_of_date' });
  assert.match(text, /Shot 2 changed since this was proposed/);
  assert.match(text, />Re-check</);
  assert.doesNotMatch(text, />Accept</);
});
test('an untaken paid result offers review price without a one-key acceptance target', () => {
  const text = html({ ...base, kind: 'take', costCents: 65, state: 'awaiting_approval', beforeRef: { kind: 'take', takeId: '1' }, afterRef: { kind: 'take', takeId: '2' } });
  assert.match(text, /Waiting for approval/);
  assert.match(text, /Review price/);
  assert.doesNotMatch(text, />Accept</);
});
test('rejected paid output remains described as kept in Takes with its price', () => {
  const text = html({ ...base, kind: 'take', costCents: 65, taken: true, state: 'rejected', beforeRef: { kind: 'take', takeId: '1' }, afterRef: { kind: 'take', takeId: '2' } });
  assert.match(text, /\$0\.65/);
  assert.match(text, /kept in Takes/);
});

test('a disconnected paid approval with sufficient credit does not claim insufficient credit', () => {
  const change = { ...base, kind: 'take', state: 'awaiting_approval', costCents: 65, taken: false, beforeRef: { kind: 'take', takeId: '1' }, afterRef: { kind: 'take', takeId: '2' }, approval: { id: 'price', status: 'pending', title: 'New take', specs: [], estimateCents: 105, capCents: 150, balanceCents: 1000, lines: [] } };
  const text = html(change, { approvalEnabled: false });
  assert.doesNotMatch(text, /Not enough credit|Add credit to continue/);
  assert.match(text, /Approve · est\. \$1\.05/);
  assert.match(text, /disabled=""/);
});
