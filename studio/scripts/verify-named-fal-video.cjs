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
const { choiceLabel } = require('../lib/canvas/model-labels.ts');

for (const [endpoint, verb] of [
  ['pixelcut/looping-video', 'pixelcut_looping_video'],
  ['pixverse/music-video/vibemv', 'pixverse_vibemv'],
]) {
  assert.equal(toolForAgentArtifact('video', { name: 'Fal___' + verb, provider: 'fal' }), undefined,
    'named-only output must remain an asset instead of a rerunnable Wan VACE node');
  assert.equal(toolForAgentArtifact('video', {
    name: 'Fal___get_video_task', provider: 'fal', providerJobId: endpoint + ':completed-video',
  }), undefined);
  assert.match(choiceLabel('model', endpoint), /named only/);
}
assert.equal(toolForAgentArtifact('video', { name: 'Fal___generate_wan3_t2v', provider: 'fal' }).id,
  'video.wan3.generate');
console.log('passed named fal video artifact and label checks (offline, not browser E2E)');
