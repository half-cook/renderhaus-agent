const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');

require.extensions['.ts'] = function (mod, filename) {
  const source = fs.readFileSync(filename, 'utf8');
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  mod._compile(outputText, filename);
};

const { toolById, toolForAgentArtifact } = require('../lib/canvas/tool-registry.ts');
const { choiceLabel } = require('../lib/canvas/model-labels.ts');

for (const [endpoint, toolId, toolName] of [
  ['ideogram/v4.5/edit', 'image.ideogram.edit', 'ideogram_edit'],
  ['fal-ai/recraft/v4.1/pro/text-to-vector', 'image.recraft.vector', 'recraft_text_to_vector'],
]) {
  const tool = toolById(toolId);
  assert.equal(tool.providerId, 'fal');
  assert.equal(tool.toolName, toolName);
  assert.equal(tool.pollTool, 'get_video_task');
  assert.equal(tool.outputPorts[0].dataType, 'image');
  assert.equal(toolForAgentArtifact('image', { name: 'Fal___' + toolName, provider: 'fal' }).id, toolId);
  assert.equal(toolForAgentArtifact('image', {
    name: 'Fal___get_video_task', provider: 'fal', providerJobId: endpoint + ':completed-image',
  }).id, toolId);
  assert.notEqual(choiceLabel('model', endpoint), endpoint);
}
assert.equal(toolById('image.ideogram.edit').defaults.edit_precision, 'high');
assert.equal(toolById('image.recraft.vector').defaults.enable_safety_checker, true);
console.log('passed image specialist Studio tool and async artifact routing checks (offline, not browser E2E)');
