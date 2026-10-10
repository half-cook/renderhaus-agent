const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function loadTypeScript(filename, dependencies = {}) {
  const source = fs.readFileSync(path.join(__dirname, '../src', filename), 'utf8');
  const compiled = ts.transpileModule(source, {compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
  }}).outputText;
  const output = {exports: {}};
  vm.runInNewContext(compiled, {exports: output.exports, module: output,
    require: (name) => Object.hasOwn(dependencies, name) ? dependencies[name] : require(name),
    Intl, console}, {filename});
  return output.exports;
}

const {ChatStorySchema} = loadTypeScript('ChatStorySchema.ts');
const {assertChatStory} = loadTypeScript('ChatStory.tsx', {
  './ChatStorySchema': {ChatStorySchema}, remotion: {}, react: {}, 'react/jsx-runtime': {},
});
const story = JSON.parse(fs.readFileSync(0, 'utf8'));
assert.deepEqual(JSON.parse(JSON.stringify(ChatStorySchema.parse(story))), story);
assertChatStory(story);

function rejects(change) {
  const invalid = structuredClone(story);
  change(invalid);
  assert.throws(() => ChatStorySchema.parse(invalid));
  assert.throws(() => assertChatStory(invalid));
}

rejects((value) => { value.payload.messages[0].typingMs = '700'; });
rejects((value) => { value.payload.messages[0].text = '   '; });
rejects((value) => { value.payload.messages[0].text = 'x'.repeat(501); });
rejects((value) => { value.payload.messages[0].reaction = '🚀'; });
rejects((value) => { value.payload.messages[0].status = 'official'; });
rejects((value) => { value.payload.messages[0].from = 'someone'; });
rejects((value) => { value.payload.messages = Array(41).fill(value.payload.messages[0]); });
rejects((value) => { value.payload.contact.avatar = 'https://example.org/private-face.jpg'; });
rejects((value) => { value.payload.theme = 'WhatsApp-style'; });
rejects((value) => { value.payload.aspect = '16:9'; });
rejects((value) => { value.payload.music_ref = '../secret.wav'; });
rejects((value) => { value.payload.confidential = true; });
rejects((value) => { value.payload.sfx = 1; });
rejects((value) => { value.plan.bubbles[0].x = Infinity; });
rejects((value) => { value.plan.bubbles[0].startFrame = 0.5; });
rejects((value) => { value.plan.scrollEvents = [{frame: 0, endFrame: 1, offset: NaN}]; });
rejects((value) => { value.plan.sfxCues[0].kind = 'voice'; });
rejects((value) => { value.plan.reviewFrames[0] = -1; });
const reordered = structuredClone(story);
reordered.plan.bubbles[0].index = 1;
assert.doesNotThrow(() => ChatStorySchema.parse(reordered));
assert.throws(() => assertChatStory(reordered));
const noViewport = structuredClone(story);
noViewport.plan.safeTop = noViewport.plan.height;
assert.doesNotThrow(() => ChatStorySchema.parse(noViewport));
assert.throws(() => assertChatStory(noViewport));
console.log('21 native schema cases passed');
