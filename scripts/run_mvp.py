#!/usr/bin/env python3
"""Run the authenticated Studio, local Gateway and API; providers stay dry unless --live."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.secrets import EXCLUDED_SECRET_KEYS, fetch_secret_map


def environment(secrets: dict[str, str], *, live: bool) -> dict[str, str]:
    env = {**os.environ, **{k: v for k, v in secrets.items() if k not in EXCLUDED_SECRET_KEYS}}
    # Shared cloud settings must never turn a development session into a paid run.
    for key in env:
        if key.endswith('_DRY_RUN'):
            env[key] = 'true'
    for key in ('SEEDANCE', 'FAL', 'FISH_AUDIO', 'REMOTION', 'SEEDREAM', 'ELEVENLABS',
                'OPENAI_IMAGES', 'MUREKA', 'GEMINI', 'SYNC', 'TOPAZ', 'FFMPEG'):
        env[key + '_DRY_RUN'] = 'false' if live and key in {'SEEDANCE', 'FAL', 'FISH_AUDIO', 'REMOTION'} else 'true'
    env.update(RENDERHAUS_SECRETS_NAME='', RENDERHAUS_SECRETS_ARN='',
               AGENTCORE_RUNTIME_ARN='', AGENTCORE_DEV_URL='',
               AGENTCORE_GATEWAY_URL='http://127.0.0.1:8765/mcp',
               AGENTCORE_GATEWAY_AUTH_TOKEN='', AGENTCORE_GATEWAY_ALLOW_LOOPBACK_HTTP='true',
               REMOTION_RENDER_BACKEND='lambda', SEEDANCE_TRANSPORT='fal',
               RH_SHOT_BUILD_DIR='.next-mvp-dev')
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Enable paid calls for the MVP providers; UI approvals still apply.')
    args = parser.parse_args()
    env = environment(fetch_secret_map('renderhaus/app'), live=args.live)
    children = []
    try:
        for command, cwd in [([sys.executable, 'scripts/local_gateway.py'], ROOT),
                             ([sys.executable, '-m', 'server.app'], ROOT),
                             (['npm', 'run', 'dev'], ROOT / 'studio')]:
            children.append(subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True))
        print('Studio: http://localhost:5174 | providers: ' + ('LIVE' if args.live else 'DRY RUN'), flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        import signal

        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


if __name__ == '__main__':
    raise SystemExit(main())
