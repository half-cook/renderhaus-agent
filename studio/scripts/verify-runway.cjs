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
const React = localRequire('react');
const { renderToStaticMarkup } = localRequire('react-dom/server');
const { SchemaForm } = require(root + '/components/forms/SchemaForm.tsx');
const { toolById, toolForAgentArtifact } = require(root + '/lib/canvas/tool-registry.ts');
const { generateBlockers } = require(root + '/lib/canvas/generate-readiness.ts');
const mixedModels = ['gen4.5', 'aleph2', 'gen4_image', 'gen4_image_turbo'];
for (const [id, model] of [['runway.video.generate','gen4.5'],['runway.video.fromImage','gen4.5'],['runway.video.edit','aleph2'],['runway.image.generate','gen4_image'],['runway.image.edit','gen4_image']]) {
  const tool = toolById(id);
  assert.equal(tool.defaults.model, model);
  assert.equal(tool.pollTool, 'get_runway_task');
  assert.equal(tool.pollIntervalMs, 5000);
}
const schemas = JSON.parse(fs.readFileSync(path.join(root, '../configs/gateway/runway.tools.json'), 'utf8'));
const schema = schemas.find(tool => tool.name === 'text_to_video').inputSchema;
const markup = renderToStaticMarkup(React.createElement(SchemaForm,{schema,values:{model:'gen4.5'},options:{model:mixedModels},onChange(){}}));
assert(markup.includes('Studio Video · Cinematic Plus'));
assert(!markup.includes('Aleph'));
assert(!markup.includes('Gen-4 Image'));
const editSchema = { name: 'video_to_video', inputSchema: {type:'object',properties:{prompt:{type:'string'},video_path_or_url:{type:'string'},video_duration_seconds:{type:'number'}},required:['prompt','video_path_or_url','video_duration_seconds']} };
const editData = {kind:'video',title:'Edit',toolId:'runway.video.edit',providerId:'runway',config:{prompt:'Add snow',model:'aleph2'},status:'idle'};
assert.equal(generateBlockers(editData,editSchema,[]).length,2);
assert.equal(generateBlockers({...editData,config:{...editData.config,video_path_or_url:'https://example.test/a.mp4',video_duration_seconds:3}},editSchema,[]).length,0);
assert.equal(toolForAgentArtifact('image',{provider:'Runway',name:'get_runway_task'}).id,'runway.image.generate');
assert.equal(toolForAgentArtifact('video',{provider:'Runway',name:'get_runway_task'}).id,'runway.video.generate');
const { useCanvasStore } = require(root + '/lib/canvas/store.ts');
global.crypto = require('node:crypto').webcrypto;
useCanvasStore.setState({ nodes: [], persist() {}, providers: [{id:'runway', tools:schemas}] });
const asset = { assetId:'asset', versionId:'version', kind:'video', filename:'clip.mp4', mimeType:'video/mp4' };
const id = useCanvasStore.getState().placeAgentAsset({asset,position:{x:0,y:0},toolEvent:{provider:'Runway',name:'video_to_video',arguments:{prompt:'Add snow',model:'aleph2',video_duration_seconds:3}},prompt:'fallback'});
const artifact = useCanvasStore.getState().nodes.find(node => node.id === id);
assert.equal(artifact.data.config.model, 'gen4.5');
assert.equal(artifact.data.config.prompt, 'Add snow');
assert.equal(artifact.data.config.ratio, '1280:720');
console.log('passed 11 Runway Studio scenarios for tool defaults, poll settings, model choices, required edit inputs, and agent artifact routing');
