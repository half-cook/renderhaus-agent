const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');

require.extensions['.ts'] = function (mod, filename) {
  const { outputText } = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  mod._compile(outputText, filename);
};

const { toolForAgentArtifact } = require('../lib/canvas/tool-registry.ts');
for (const [provider, name] of [
  ['remotion', 'Remotion___deliver_render'],
  ['remotion', 'Remotion___qc_deliverable'],
  ['remotion', 'Remotion___render_ad_variants'],
  ['ffmpeg', 'Ffmpeg___ffmpeg_tool'],
]) {
  for (const kind of ['video', 'image']) {
    assert.equal(toolForAgentArtifact(kind, { provider, name }), undefined,
      'Local finished media must remain an asset, without a paid generation tool');
  }
}
assert.equal(toolForAgentArtifact('video', { provider: 'fal', name: 'Fal___generate_wan3_t2v' }).id,
  'video.wan3.generate');
console.log('passed local delivery artifact provenance checks (offline, browser E2E pending)');
