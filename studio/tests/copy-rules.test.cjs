const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const { pathToFileURL } = require('node:url');

const studio = path.resolve(__dirname, '..');
// identifiers and ids are fine; only quoted user-facing strings and JSX text count
const userStrings = (text) => [...text.matchAll(/"([^"\n]{3,})"|'([^'\n]{3,})'|>([^<>{}\n]{3,})</g)].map((m) => m[1] || m[2] || m[3]).filter((s) => /\s/.test(s));
const rules = () => import(pathToFileURL(path.join(studio, 'design-shots/copy-rules.mjs')).href);

test('copy guard catches fee wording and vendor or model names', async () => {
  const { findCopyLeaks, ALLOWED_FEE_LINE } = await rules();
  for (const text of ['Platform fee $0.30', 'includes a 30% fee', 'Powered by Runway', 'Wan 3 image to video', 'GPT Image 2.5', 'Voiced by ElevenLabs', 'Seedance video', 'Planned by Sonnet', 'Rendered with Remotion', 'via fal']) {
    assert.ok(findCopyLeaks(text).length > 0, text);
  }
  for (const text of ['Product still $0.26', '10-second clip $1.30', 'Voiceover $0.02', 'Total $1.58', 'Approve once', 'Demo Studio launch', 'Open the swan lake storyboard']) {
    assert.deepEqual(findCopyLeaks(text), [], text);
  }
  assert.deepEqual(findCopyLeaks(ALLOWED_FEE_LINE), []);
  assert.ok(findCopyLeaks(`${ALLOWED_FEE_LINE} Platform fee 30%`).length > 0);
});

test('new foundation files, kit fixtures and docs (product copy) carry no fee or vendor wording', async () => {
  const { findCopyLeaks } = await rules();
  const files = ['design-shots/fixtures/studio.json', 'design-shots/fixtures/account.json', 'design-shots/fixtures/artifact.svg', 'design-shots/screens.ts', 'design-shots/README.md', 'design-shots/fixtures/README.md'];
  for (const dir of ['components/ui', 'components/motion']) {
    for (const entry of fs.readdirSync(path.join(studio, dir))) files.push(path.join(dir, entry));
  }
  for (const file of files) {
    if (!fs.existsSync(path.join(studio, file))) continue;
    const raw = fs.readFileSync(path.join(studio, file), 'utf8');
    if (file.endsWith('studio.json')) {
      // internal id keys mirror the real payload shape and are never rendered
      const values = [];
      JSON.parse(raw, (key, value) => { if (typeof value === 'string' && !['providerId', 'toolName', 'tool_name', 'toolId'].includes(key)) values.push(value); return value; });
      assert.deepEqual(findCopyLeaks(values.join('\n')), [], file);
    } else {
      assert.deepEqual(findCopyLeaks(raw), [], file);
    }
  }
});

test('approval fixtures expose no provider or fee fields to the client', () => {
  const data = JSON.parse(fs.readFileSync(path.join(studio, 'design-shots/fixtures/studio.json'), 'utf8'));
  const text = JSON.stringify(data);
  assert.doesNotMatch(text, /"provider"\s*:|platform_fee|fee_cents|"fee"/i);
});

// Ratchet: these legacy files still contain vendor-named labels. The revamp must remove them;
// no other app source file may start leaking.
const LEGACY_VENDOR_LABELS = new Set([
  'components/canvas/NodeInspector.tsx',
  'components/canvas/StudioCanvas.tsx',
  'lib/canvas/model-labels.ts',
  'lib/canvas/tool-registry.ts',
  'lib/canvas/generate-readiness.ts',
]);

function walk(dir) {
  return fs.readdirSync(path.join(studio, dir), { withFileTypes: true }).flatMap((entry) => {
    const rel = path.join(dir, entry.name);
    if (entry.isDirectory()) return walk(rel);
    return /\.(tsx?|css)$/.test(entry.name) ? [rel] : [];
  });
}

test('no app source file outside the legacy list names a provider or shows fee wording', async () => {
  const { findCopyLeaks } = await rules();
  const offenders = [];
  for (const file of [...walk('components'), ...walk('app'), ...walk('lib')]) {
    if (LEGACY_VENDOR_LABELS.has(file)) continue;
    const text = fs.readFileSync(path.join(studio, file), 'utf8');
    if (findCopyLeaks(userStrings(text).join('\n')).length) offenders.push(file);
  }
  assert.deepEqual(offenders, []);
});

test('the legacy list only shrinks: every listed file still leaks', async () => {
  const { findCopyLeaks } = await rules();
  for (const file of LEGACY_VENDOR_LABELS) {
    assert.ok(findCopyLeaks(userStrings(fs.readFileSync(path.join(studio, file), 'utf8')).join('\n')).length > 0, `${file} is clean now: remove it from LEGACY_VENDOR_LABELS`);
  }
});
