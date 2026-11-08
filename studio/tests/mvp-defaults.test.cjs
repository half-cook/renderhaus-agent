const assert = require('node:assert/strict');
const test = require('node:test');
const load = require('./load-ts.cjs');
const { defaultToolForRail, toolById, toolForAgentArtifact } = load('lib/canvas/tool-registry.ts');

test('new video and voice nodes use Seedance and Fish without changing saved provider identities', () => {
  assert.equal(defaultToolForRail('video').providerId, 'seedance');
  assert.equal(defaultToolForRail('voice').providerId, 'fish_audio');
  assert.equal(defaultToolForRail('voice').toolName, 'generate_speech');
  assert.equal(toolById('voice.generate').providerId, 'elevenlabs');
  assert.equal(toolById('video.wan3.generate').toolName, 'generate_wan3_t2v');
});

test('completed media retains its originating provider when added to the canvas', () => {
  for (const provider of ['fish_audio', 'fish-audio', 'FishAudio']) {
    assert.equal(toolForAgentArtifact('audio', { provider, name: 'generate_speech' }).providerId, 'fish_audio');
  }
  assert.equal(toolForAgentArtifact('audio', { provider: 'elevenlabs', name: 'text_to_speech_convert' }).providerId, 'elevenlabs');
  assert.equal(toolForAgentArtifact('video', { provider: 'fal', providerJobId: 'bytedance/seedance-2.5/us/text-to-video:request' }).providerId, 'seedance');
});
