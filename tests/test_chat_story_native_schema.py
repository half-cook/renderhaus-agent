"""Exercise native props validation against an exact Python-generated frame plan."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'remotion'


class ChatStoryNativeSchemaTests(unittest.TestCase):
    def test_native_schema_preserves_the_python_contract_and_rejects_bad_props(self):
        if not shutil.which('node'):
            self.skipTest('Node is absent; native schema runtime check requires Node.')
        dependencies = subprocess.run(
            ['node', '-e', "require.resolve('typescript');require.resolve('zod');"],
            cwd=NATIVE, capture_output=True, text=True, timeout=10)
        if dependencies.returncode:
            self.skipTest('Native Zod/TypeScript dependencies are absent; install the declared renderer dependencies.')
        from providers.remotion.chat_story import build_props

        fixture = build_props('Fiction', {'messages': [
            {'from': 'me', 'text': '  Hello, 🙂\nverbatim!  ', 'status': 'read'},
            {'from': 'them', 'text': 'שלום 👩🏽\u200d💻', 'reaction': '❤️'},
        ], 'contact': {'name': 'Avery', 'avatar': 'initials'},
            'music_ref': 'music.wav', 'send_sound_ref': 'send.wav',
            'receive_sound_ref': 'receive.wav', 'dramatization': True})['document']['chatStory']
        result = subprocess.run(
            ['node', str(NATIVE / 'test/chat-story-schema.cjs')], input=json.dumps(fixture, ensure_ascii=False),
            cwd=NATIVE, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('native schema cases passed', result.stdout)
