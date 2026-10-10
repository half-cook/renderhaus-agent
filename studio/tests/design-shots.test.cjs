const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const studio = path.resolve(__dirname, '..');
const read = (file) => fs.readFileSync(path.join(studio, file), 'utf8');

test('manual screenshot commands use one install and stay outside the app typecheck and CI', () => {
  const pkg = JSON.parse(read('package.json'));
  for (const command of ['shots', 'shots:install', 'shots:before', 'shots:after', 'shots:compare', 'shots:a11y']) assert.ok(pkg.scripts[command], command);
  assert.deepEqual(JSON.parse(read('design-shots/package.json')), { private: true, type: 'module' });
  assert.ok(JSON.parse(read('tsconfig.json')).exclude.includes('design-shots'));
  const ci = fs.readFileSync(path.join(studio, '../.github/workflows/ci.yml'), 'utf8');
  assert.doesNotMatch(ci, /playwright|shots:/i);
});

test('the screenshot runner owns its server and forces a secret-free production environment', () => {
  const runner = read('design-shots/run.mjs');
  assert.match(runner, /5191/);
  assert.doesNotMatch(runner, /--port[ =]5174|shell:\s*true|pkill|killall/);
  assert.match(runner, /NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY/);
  assert.match(runner, /CLERK_SECRET_KEY/);
  assert.match(runner, /server\.kill/);
  assert.match(runner, /finally/);
});

test('screenshots and axe share fail-closed mock routing and the privacy guard', () => {
  const fixture = read('design-shots/fixture.ts');
  assert.match(fixture, /abort\("blockedbyclient"\)/);
  assert.match(fixture, /request\(\)\.method\(\) !== "GET"/);
  assert.match(fixture, /privacyGuard/);
  const privacy = read("design-shots/privacy.mjs");
  assert.match(privacy, /X-Amz-Signature/);
  assert.match(privacy, /Private-looking email/);
  assert.match(read('design-shots/shots.spec.ts'), /privacyGuard/);
  assert.match(read('design-shots/a11y.spec.ts'), /privacyGuard/);
  const data = JSON.parse(read('design-shots/fixtures/studio.json'));
  assert.equal(data['/api/studio/projects'].items[0].name, 'Demo Studio');
  assert.doesNotMatch(JSON.stringify(data), /X-Amz-Signature|sk_live_|@(?!example\.com)/);
});

test('privacy rejection never includes the private value in its diagnostic', async () => {
  const { assertCapturePrivacy } = await import('../design-shots/privacy.mjs');
  for (const [body, urls, secret] of [
    ['Person private@personal.invalid', [], 'private@personal.invalid'],
    ['Demo Creator', ['https://example.com/file?X-Amz-Signature=private-signature'], 'private-signature'],
  ]) {
    assert.throws(() => assertCapturePrivacy(body, urls), (error) => !error.message.includes(secret) && /private/i.test(error.message));
  }
  assert.doesNotThrow(() => assertCapturePrivacy('Demo Creator demo@example.com', ['/api/studio/design-shot-artifact.svg']));
});
