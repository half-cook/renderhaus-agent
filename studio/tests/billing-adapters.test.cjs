const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const load = require('./load-ts.cjs');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { ApprovalCard } = load('components/rh/ApprovalCard.tsx');
const billing = load('lib/rh/billing.ts');
const approval = load('lib/rh/approval-model.ts');
const money = load('lib/rh/money.ts');
const docs = fs.readFileSync(path.join(__dirname, '../../docs/BILLING.md'), 'utf8').split('## Orchestration billing, run holds and caps')[1];
const examples = [...docs.matchAll(/```json\s*([\s\S]*?)```/g)].map((match) => JSON.parse(match[1]));
const pending = examples.find((item) => item.call_id);
const insufficient = examples.find((item) => item.type === 'insufficient_credit');
const paused = examples.find((item) => item.type === 'paused_cap');
const receipt = examples.find((item) => item.type === 'receipt');
const request = (patch = {}) => { const raw = { ...pending, ...patch }; return { callId: raw.call_id, label: raw.label, toolName: 'Studio___text_to_video', arguments: raw.arguments, billing: raw }; };

test('pending uses the documented run totals, balances and step metadata verbatim', () => {
  const card = approval.approvalCardModel(request());
  assert.equal(card.estimateCents, 233); // The documented lines intentionally differ; never recompute.
  assert.equal(card.capCents, 350);
  assert.equal(card.balanceAfterEstimateCents, 767);
  assert.equal(card.balanceAfterCapCents, 650);
  assert.equal(card.stepIndex, 2);
  assert.equal(card.stepCount, 4);
  assert.equal(card.lines.length, 4);
});
test('insufficient credit without a server lower cap offers only add credit', () => {
  const card = approval.approvalCardModel(request({ insufficient_credit: insufficient, approve_enabled: false }));
  assert.equal(card.balanceCents, 150);
  assert.equal(billing.creditState(card, card.approveEnabled), 'add_credit');
  assert.equal(card.lowerCapOptionCents, null);
});
test('a server lower cap is preserved, including an estimate of zero', () => {
  const card = approval.approvalCardModel(request({ estimate_cents: 0, insufficient_credit: { ...insufficient, balance_cents: 150, lower_cap_option_cents: 150 }, approve_enabled: false }));
  assert.equal(billing.creditState(card, card.approveEnabled), 'lower_cap');
  assert.equal(card.lowerCapOptionCents, 150);
});
test('missing lower-cap option is never invented from the balance', () => {
  const card = approval.approvalCardModel(request({ estimate_cents: 100, balance_cents: 150, insufficient_credit: null }));
  assert.equal(billing.creditState(card), 'add_credit');
});
test('documented paused cap preserves totals, affordable options and exact zero remaining', () => {
  const card = billing.toApprovalCardModel({ id: 'run' }, { ...paused, balance_cents: 0, raise_options_cents: [] });
  assert.equal(card.status, 'paused_cap');
  assert.equal(card.chargedCents, 350);
  assert.equal(card.capCents, 350);
  assert.equal(card.balanceCents, 0);
  assert.deepEqual(card.raiseOptionsCents, []);
});
test('the credit chip does not subtract a fully charged paused cap from the wallet again', () => {
  const { CreditChip } = load('components/rh/CreditChip.tsx');
  const { creditState } = load('lib/rh/credit-store.ts');
  const heldCents = approval.heldCreditCents([{ status: 'error', errorType: 'PausedAtCap', approvals: [],
    pausedCap: { held_cents: 20, charged_cents: 20 } }]);
  assert.equal(heldCents, 0);
  const html = renderToStaticMarkup(React.createElement(CreditChip, {
    balanceCents: 815, heldCents, state: creditState(815, null, heldCents),
  }));
  assert.match(html, /Credit \$8\.15/);
  assert.doesNotMatch(html, />Held</);
});
test('held credit counts each active run once and excludes stopped or historical snapshots', () => {
  const running = { status: 'running', approvals: [{ kind: 'approval', ...request({ status: 'running', held_cents: 150, spent_so_far_cents: 28 }) },
    { kind: 'approval', ...request({ status: 'running', held_cents: 150, spent_so_far_cents: 28 }) }] };
  const pausedRun = { status: 'error', errorType: 'PausedAtCap', approvals: [],
    pausedCap: { held_cents: 50, charged_cents: 39 } };
  assert.equal(approval.heldCreditCents([running, pausedRun]), 133);
  for (const status of ['completed', 'stopped', 'cancelled', 'failed', 'error']) {
    assert.equal(approval.heldCreditCents([{ ...pausedRun, status, errorType: 'UserStopped' }, running]), 122);
  }
  assert.equal(approval.heldCreditCents([{ ...pausedRun, receipt: { actual_cents: 39 } }]), 0);
  assert.equal(approval.heldCreditCents([{ ...pausedRun, pausedCap: { held_cents: 20, charged_cents: 25 } }]), 0);
  assert.equal(approval.heldCreditCents([{ ...pausedRun, pausedCap: { held_cents: 20 } }]), 0);
});
for (const raiseOptions of [[200], []]) {
  for (const charged of [26, 0, undefined]) {
    test(`paused next-step reservation shows actual ${charged ?? 'unknown'} charge with ${raiseOptions.length ? 'raise' : 'free-edit'} actions`, () => {
      const model = billing.toApprovalCardModel({ id: 'partial-pause', title: 'Voice test' }, {
        type: 'paused_cap', cap_cents: 144, charged_cents: charged, raise_options_cents: raiseOptions,
        message: 'Stopped at your cap. Nothing more has been charged, and the run is paused so you decide.',
      });
      const previous = process.env.NEXT_PUBLIC_TOPUPS_ENABLED;
      process.env.NEXT_PUBLIC_TOPUPS_ENABLED = 'false';
      let html;
      try {
        html = renderToStaticMarkup(React.createElement(ApprovalCard, { model, focusOnMount: false }));
      } finally {
        if (previous === undefined) delete process.env.NEXT_PUBLIC_TOPUPS_ENABLED;
        else process.env.NEXT_PUBLIC_TOPUPS_ENABLED = previous;
      }
      assert.match(html, /Paused · next step exceeds cap/);
      assert.match(html, /Next step exceeds your \$1\.44 cap/);
      assert.match(html, /The next step needs more than the remaining cap\. No further work has started\./);
      assert.doesNotMatch(html, /cap reached|Stopped at your|Charged · at cap/);
      const total = html.match(/<dt>Charged so far<\/dt><dd class="rh-num">(.*?)<\/dd>/)?.[1];
      assert.equal(total, charged == null ? 'Unavailable' : money.formatCents(charged));
      const bar = html.match(/class="rh-bar rh-bar-acc"[^>]*><b style="width:([^%]+)%"/);
      if (raiseOptions.length && charged != null) assert.ok(Math.abs(Number(bar?.[1]) - charged / 144 * 100) < 0.0001);
      else assert.equal(bar, null);
      if (raiseOptions.length) {
        assert.match(html, /Raise cap to \$2\.00/);
        assert.match(html, /Stop here/);
      } else {
        assert.match(html, />Trim<\/button>/);
        assert.match(html, />Keep as is<\/button>/);
      }
    });
  }
}
for (const status of ['done', 'failed']) test(`documented ${status} receipt lists exactly what was charged`, () => {
  const model = billing.toRunReceiptModel({ ...receipt, status });
  assert.equal(model.status, status);
  assert.equal(model.actualCents, 162);
  assert.equal(model.estimateCents, 233);
  assert.equal(model.capCents, 325);
  assert.equal(model.balanceBeforeCents, 1000);
  assert.equal(model.balanceAfterCents, 838);
});
test('incomplete estimate stays flagged and rejected approvals produce no paid card', () => {
  assert.equal(approval.approvalCardModel(request({ estimate_cents: 0, estimate_incomplete: true })).estimateIncomplete, true);
  assert.equal(approval.approvalCardModel(request({ status: 'rejected' })), null);
});
test('free steps, four-digit totals, long title, three-line prompt and twelve steps survive adaptation', () => {
  for (const cents of [0, 124050]) {
    const title = 'A long shot title '.repeat(20);
    const prompt = ['Morning window light.', 'A gentle push-in.', 'No text on the frame.'].join('\n');
    const model = approval.approvalCardModel(request({ label: title, arguments: { prompt }, estimate_cents: cents, cap_cents: cents, step_count: 12, step_index: 12 }));
    assert.equal(model.estimateCents, cents); assert.equal(model.capCents, cents);
    assert.equal(model.title, title.trim()); assert.equal(model.prompt, prompt); assert.equal(model.stepCount, 12);
    assert.match(billing.a11yApproveName(model, money.formatCents), /estimated .*hard cap/);
  }
});
test('actual above estimate but below cap stays the server actual', () => {
  const model = billing.toRunReceiptModel({ ...receipt, actual_cents: 250, under_estimate: false });
  assert.equal(model.actualCents, 250); assert.equal(model.underEstimate, false);
});
test('line prices cannot substitute for a missing estimate or hard cap', () => {
  assert.equal(approval.approvalCardModel(request({ estimate_cents: undefined })), null);
  assert.equal(approval.approvalCardModel(request({ cap_cents: undefined })), null);
  assert.equal(billing.toNodeEstimate({ estimate_cents: 100 }), null);
  assert.equal(billing.toApprovalCardModel({ id: 'x' }, { lines: [{ price_cents: 99 }] }).estimateCents, 0);
});
test('vendor names and machine tool calls never become copy or specification chips', () => {
  for (const value of ['Seedream___text_to_image', 'custom___a_special_tool', 'wan-3.0', 'Powered by Fish Audio', 'platform fee 30%']) assert.equal(billing.safeCopy(value, 'Studio step'), 'Studio step', value);
  assert.deepEqual(approval.specsFrom({ resolution: 'wan', aspect_ratio: '16:9', duration_seconds: 5 }), ['5 s', '16:9']);
  assert.deepEqual(approval.visibleParameters({ model: 'hidden', provider: 'hidden', tool_name: 'hidden', endpoint: 'hidden', model_id: 'hidden', prompt: 'Warm window light', steps: 12 }), [['prompt', 'Warm window light'], ['steps', '12']]);
});
test('money formatting preserves zero, a cent and four-digit totals', () => {
  for (const [cents, text] of [[0, '$0.00'], [1, '$0.01'], [105, '$1.05'], [124050, '$1,240.50']]) assert.equal(money.formatCents(cents), text);
  for (const value of [-1, 0.5, '100', NaN, Infinity]) assert.equal(money.isCents(value), false);
});

test('twelve pending approvals preserve order and the server totals for every step', () => {
  const cards = Array.from({ length: 12 }, (_, index) => approval.approvalCardModel(request({ call_id: `step-${index + 1}`, step_index: index + 1, step_count: 12 })));
  assert.deepEqual(cards.map((card) => card.stepIndex), Array.from({ length: 12 }, (_, index) => index + 1));
  assert.ok(cards.every((card) => card.stepCount === 12 && card.estimateCents === 233 && card.capCents === 350));
});
test('receipt missing account or cap data stays unavailable instead of showing zero credit', () => {
  for (const field of ['cap_cents', 'balance_before_cents', 'balance_after_cents']) assert.equal(billing.toRunReceiptModel({ ...receipt, [field]: undefined }), null);
});
test('parameter keys cannot reveal fees, vendor names or machine tool names', () => {
  assert.deepEqual(approval.visibleParameters({ platform_fee: 30, seedream_version: 2, custom___special_tool: true, negative_prompt: 'No text', steps: 12 }), [['negative prompt', 'No text'], ['steps', '12']]);
});
