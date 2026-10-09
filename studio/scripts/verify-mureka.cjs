const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const Module = require('node:module');
const { createRequire } = Module;
const root = path.resolve(__dirname, '..');
const localRequire = createRequire(root + '/package.json');
const ts = localRequire('typescript');
const resolve = Module._resolveFilename;
Module._resolveFilename = function(name, parent, ...args) {
  if (name.startsWith('@/')) name = root + '/' + name.slice(2);
  return resolve.call(this, name, parent, ...args);
};
for (const ext of ['.ts', '.tsx']) {
  require.extensions[ext] = function(mod, filename) {
    const source = fs.readFileSync(filename, 'utf8');
    const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } });
    mod._compile(outputText, filename);
  };
}
const { generateBlockers } = require(root + '/lib/canvas/generate-readiness.ts');
const { toolById } = require(root + '/lib/canvas/tool-registry.ts');
const schemas = JSON.parse(fs.readFileSync(path.join(root, '../configs/gateway/mureka.tools.json'), 'utf8'));
function blockers(id, config, connections = []) {
  const tool = toolById(id);
  const schema = schemas.find(schema => schema.name === tool.toolName);
  return generateBlockers({ kind: tool.category, toolId: id, providerId: 'mureka', toolName: tool.toolName,
    config: { ...tool.defaults, ...config } }, schema, connections);
}
assert.deepEqual(blockers('music.song', { lyrics: 'Summer sun' }), []);
assert.deepEqual(blockers('music.song', { prompt: 'A summer song' }), []);
assert.deepEqual(blockers('music.song', { lyrics: 'Summer sun', prompt: 'Jazz style' }), []);
assert.equal(blockers('music.song', {}).length, 1);
assert.deepEqual(blockers('music.song', {}, ['prompt']), []);
assert.deepEqual(blockers('music.generate', { instrumental_id: 'inst_1' }), []);
assert.deepEqual(blockers('music.generate', { prompt: 'Gentle piano' }), []);
assert.equal(blockers('music.generate', { instrumental_id: 'inst_1', prompt: 'Piano' }).length, 1);
assert.equal(blockers('music.generate', {}).length, 1);
assert.deepEqual(blockers('video.mureka.lyrics', { song_id: 'song_1' }), []);
assert.deepEqual(blockers('video.mureka.lyrics', { upload_audio_id: 'upload_1' }), []);
assert.equal(blockers('video.mureka.lyrics', {}).length, 1);
assert.equal(blockers('video.mureka.lyrics', { song_id: 'song_1', upload_audio_id: 'upload_1' }).length, 1);
console.log('Mureka Studio source readiness passed (13 cases)');
