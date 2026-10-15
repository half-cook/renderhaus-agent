const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function playbackHook(fetch) {
  const state = [];
  const effects = [];
  let slot = 0;
  const exports = {};
  const source = fs.readFileSync(path.join(__dirname, '../lib/assets.ts'), 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  new Function('require', 'exports', js)((name) => {
    if (name === './authenticated-fetch') return { studioFetch: fetch };
    if (name === 'react') return {
      useState(initial) {
        const index = slot++;
        if (!(index in state)) state[index] = typeof initial === 'function' ? initial() : initial;
        return [state[index], (value) => { state[index] = typeof value === 'function' ? value(state[index]) : value; }];
      },
      useEffect(effect, dependencies) {
        const index = slot++;
        const previous = state[index];
        if (!previous || dependencies.some((value, n) => value !== previous.dependencies[n])) {
          previous?.cleanup?.();
          effects.push(() => { state[index] = { dependencies, cleanup: effect() }; });
        }
      },
    };
    return require(name);
  }, exports);
  return (asset, attempt = 0) => {
    slot = 0;
    const result = exports.useStudioAssetPlayback(asset, attempt);
    while (effects.length) effects.shift()();
    return result;
  };
}

const asset = (versionId) => ({ assetId: versionId, versionId, kind: 'video', filename: 'preview.mp4', mimeType: 'video/mp4' });
const settled = () => new Promise((resolve) => setImmediate(resolve));

test('a failed playback ticket becomes a visible error and an explicit retry can recover', async () => {
  let requests = 0;
  const render = playbackHook(async () => {
    requests++;
    return requests === 1 ? new Response('', { status: 404 }) : new Response(JSON.stringify({ url: '/saved-preview.mp4' }));
  });
  assert.equal(render(asset('a')).status, 'loading');
  await settled();
  assert.equal(render(asset('a')).status, 'error');
  assert.equal(requests, 1);
  render(asset('a'), 1);
  await settled();
  assert.equal(render(asset('a'), 1).url, '/saved-preview.mp4');
  assert.equal(requests, 2);
});

test('a stale playback response cannot replace a different current asset', async () => {
  let resolveFirst;
  const render = playbackHook(async (url) => url.includes('/a/')
    ? new Promise((resolve) => { resolveFirst = resolve; }) : new Response(JSON.stringify({ url: '/b.mp4' })));
  render(asset('a'));
  render(asset('b'));
  await settled();
  assert.equal(render(asset('b')).url, '/b.mp4');
  resolveFirst(new Response(JSON.stringify({ url: '/a.mp4' })));
  await settled();
  assert.equal(render(asset('b')).url, '/b.mp4');
});
