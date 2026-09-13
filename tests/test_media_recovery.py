import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from providers.mureka import api as mureka
from providers.remotion.api import build_timeline_props
from providers.registry import dispatch
from server.studio_state import StudioRepository


class MusicTimingTests(unittest.TestCase):
    def test_short_video_trims_long_score_and_preserves_in_point(self):
        props = build_timeline_props('30 second edit',
            [{'kind': 'image', 'url': 'https://example.test/image.png', 'duration_seconds': 30}],
            [{'url': 'https://example.test/music.mp3', 'duration_seconds': 180,
              'start_seconds': 2, 'source_in_seconds': 15}], fps=24, aspect_ratio='2.39:1')
        audio = props['document']['tracks'][1]['items'][0]
        self.assertEqual((audio['start'], audio['duration'], audio['sourceIn'], audio['sourceOut']), (2, 28, 15, 43))
        self.assertEqual(props['renderConfig']['durationInFrames'], 720)
        self.assertEqual(props['renderConfig']['height'], 804)
        self.assertEqual(audio['fadeOut'], .75)

    def test_audio_cannot_start_after_visuals(self):
        with self.assertRaisesRegex(ValueError, 'before the end'):
            build_timeline_props('edit', [{'kind': 'image', 'url': 'https://example.test/a.png', 'duration_seconds': 3}],
                                 [{'url': 'https://example.test/a.mp3', 'duration_seconds': 3, 'start_seconds': 4}])

    def test_replaced_soundtrack_can_mute_source_video(self):
        props = build_timeline_props('replace score', [{'kind': 'video', 'url': 'https://example.test/a.mp4',
                                                       'duration_seconds': 30, 'source_in_seconds': 5, 'volume': 0}])
        clip = props['document']['tracks'][0]['items'][0]
        self.assertEqual((clip['volume'], clip['sourceIn'], clip['sourceOut']), (0, 5, 35))

    def test_soundtrack_uses_documented_ids_milliseconds_and_single_variant(self):
        with patch.dict(os.environ, {'MUREKA_DRY_RUN': 'false'}), patch.object(mureka, '_remember_task'), patch.object(mureka, '_request', return_value={'id': 'job', 'status': 'queued'}) as request:
            result = mureka.generate_soundtrack(image_id='uploaded-image', audio_start=0, audio_end=30000)
        self.assertEqual(request.call_args.kwargs['json_body'], {'model': 'auto', 'n': 1, 'image_id': 'uploaded-image', 'audio_start': 0, 'audio_end': 30000})
        self.assertEqual(result['kind'], 'song')

    def test_seconds_are_not_silently_accepted_as_milliseconds(self):
        with self.assertRaisesRegex(ValueError, '3000'):
            dispatch('mureka', 'generate_soundtrack', {'image_id': 'uploaded', 'audio_start': 0, 'audio_end': 30})
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            dispatch('mureka', 'generate_soundtrack', {'image_id': 'one', 'video_id': 'two'})

    def test_instrumental_does_not_invent_duration_and_requests_one_track(self):
        with patch.dict(os.environ, {'MUREKA_DRY_RUN': 'false'}), patch.object(mureka, '_remember_task'), patch.object(mureka, '_request', return_value={'id': 'job'}) as request:
            mureka.create_instrumental(prompt='30 second warm piano')
        self.assertEqual(request.call_args.kwargs['json_body']['n'], 1)
        self.assertNotIn('duration', request.call_args.kwargs['json_body'])

    def test_song_poll_survives_missing_lambda_local_metadata(self):
        with patch.dict(os.environ, {'MUREKA_DRY_RUN': 'false'}), patch.object(mureka, 'read_task_meta', return_value={}), patch.object(mureka, 'write_task_meta'), patch.object(mureka, '_request', return_value={'status': 'running'}) as request:
            mureka.query_task(job_id='song-job', kind='song')
        self.assertEqual(request.call_args.args, ('GET', '/v1/song/query/song-job'))


class CheckpointTests(unittest.TestCase):
    def test_checkpoint_is_durable_scoped_and_not_exposed_in_public_job(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = StudioRepository(Path(directory) / 'studio.sqlite3', Path(directory) / 'assets')
            repo.init()
            repo.ensure_workspace('user:local', 'local')
            repo.create_project(workspace_id='user:local', user_id='local', name='Recovery', project_id='project')
            convo = repo.create_conversation('user:local', 'project', 'local')
            job = repo.create_execution(workspace_id='user:local', project_id='project', user_id='local', prompt='Make an edit', conversation_id=convo['id'])
            items = [{'type': 'renderhaus_codex_session', 'rollout': 'native history'}]
            repo.save_agent_checkpoint('user:local', convo['id'], job['job_id'], items)
            self.assertEqual(repo.get_agent_checkpoint('user:local', job['job_id']), items)
            self.assertEqual(repo.get_conversation_items('user:local', convo['id']), items)
            self.assertEqual(repo.get_agent_checkpoint('user:other', job['job_id']), [])
            self.assertIsNotNone(repo.get_execution('user:local', job['job_id'])['checkpoint_at'])
            self.assertNotIn('native history', json.dumps(repo.get_execution('user:local', job['job_id'])))

if __name__ == '__main__':
    unittest.main()
