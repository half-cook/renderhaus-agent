from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from providers.remotion import delivery


class ChatDeliveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.job = Path(temp.name) / 'chat'
        self.job.mkdir()
        env = patch.dict(os.environ, {'RENDERHAUS_MEDIA_DIR': temp.name,
            'REMOTION_RENDER_BACKEND': 'local', 'REMOTION_DRY_RUN': 'false'})
        env.start()
        self.addCleanup(env.stop)
        artifact = self.job / 'candidate.mp4'
        artifact.write_bytes(b'fixture: measurement is mocked in this contract test')
        self.entry = {'file': str(artifact), 'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(),
                      'template_id': 'chat-story-v1', 'row_status': 'rendered', 'variant_key': 'a',
                      'qc_spec': {'allowed_freeze': [{'start_s': 1, 'end_s': 4}], 'n': .000001}}
        self.manifest = self.job / 'manifest.json'

    def test_partial_batch_finishes_good_files_and_retains_failures_verbatim(self):
        entries = [self.entry, {'row_status': 'blocked', 'variant_key': 'b', 'reasons': ['Empty messages.']},
                   {'row_status': 'failed', 'variant_key': 'c', 'reasons': ['Encoder failed.']}]
        self.manifest.write_text(json.dumps(entries))
        inspected = {'file': self.entry['file'], 'passed': True, 'failures': [], 'sha256': self.entry['sha256']}
        with patch.object(delivery, '_finish', return_value=inspected) as finish:
            result = delivery.deliver_render('chat', manifest_path='manifest.json')
        finish.assert_called_once()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['failures'], ['Empty messages.', 'Encoder failed.'])
        saved = json.loads(self.manifest.read_text())
        self.assertEqual(saved[1:], entries[1:])

    def test_final_qc_reuses_validated_per_row_read_holds(self):
        self.manifest.write_text(json.dumps([self.entry]))
        inspected = {'file': self.entry['file'], 'passed': True, 'failures': [], 'warnings': []}
        with patch.object(delivery, 'inspect_file', return_value=inspected) as inspect:
            result = delivery.qc_deliverable('chat', manifest_path='manifest.json')
        self.assertEqual(result['status'], 'succeeded', result)
        spec = inspect.call_args.args[3]
        self.assertEqual(spec['n'], .000001)
        self.assertEqual(spec['allowed_freeze'], self.entry['qc_spec']['allowed_freeze'])

    def test_per_row_qc_cannot_inject_unlisted_fields(self):
        self.entry['qc_spec'] = {'filtergraph': 'untrusted'}
        self.manifest.write_text(json.dumps([self.entry]))
        with patch.object(delivery, 'inspect_file') as inspect:
            result = delivery.qc_deliverable('chat', manifest_path='manifest.json')
        inspect.assert_not_called()
        self.assertNotEqual(result['status'], 'succeeded')


if __name__ == '__main__':
    unittest.main()
