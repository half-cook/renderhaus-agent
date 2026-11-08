from unittest.mock import patch
import os

from scripts.run_mvp import environment


def test_cloud_live_flags_cannot_enable_development_spending():
    secret = {'SEEDANCE_DRY_RUN': 'false', 'FAL_DRY_RUN': 'false',
              'FISH_AUDIO_DRY_RUN': 'false', 'REMOTION_DRY_RUN': 'false',
              'CLERK_SECRET_KEY': 'test-only', 'NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY': 'test-only',
              'AGENTCORE_RUNTIME_ARN': 'cloud', 'AGENTCORE_GATEWAY_AUTH_TOKEN': 'cloud',
              'AWS_SECRET_ACCESS_KEY': 'must-not-replace-aws-bootstrap'}
    with patch.dict(os.environ, {}, clear=True):
        env = environment(secret, live=False)
    assert all(value == 'true' for key, value in env.items() if key.endswith('_DRY_RUN'))
    assert env['RENDERHAUS_SECRETS_NAME'] == env['AGENTCORE_RUNTIME_ARN'] == ''
    assert env['AGENTCORE_GATEWAY_AUTH_TOKEN'] == ''
    assert env['REMOTION_RENDER_BACKEND'] == 'lambda'
    assert env['CLERK_SECRET_KEY'] == secret['CLERK_SECRET_KEY']
    assert 'AWS_SECRET_ACCESS_KEY' not in env


def test_live_enables_only_the_primary_stack():
    with patch.dict(os.environ, {}, clear=True):
        env = environment({'ELEVENLABS_DRY_RUN': 'false'}, live=True)
    enabled = {key for key, value in env.items() if key.endswith('_DRY_RUN') and value == 'false'}
    assert enabled == {'SEEDANCE_DRY_RUN', 'FAL_DRY_RUN', 'FISH_AUDIO_DRY_RUN', 'REMOTION_DRY_RUN'}
