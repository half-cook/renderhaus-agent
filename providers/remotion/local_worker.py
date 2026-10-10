from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

from providers.ffmpeg.api import _bounded_run


def run(directory: Path) -> None:
    job = json.loads((directory / 'worker.json').read_text())
    terminal = {'exit_code': None}
    deadline = time.monotonic() + job['timeout']
    try:
        if 'template' in job:
            from providers.remotion.template_frames import write_template_video

            write_template_video(job['template'], directory)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired('local assembly', job['timeout'])
        completed = _bounded_run(job['command'], directory, remaining)
        (directory / 'stderr.txt').write_bytes(completed.stderr)
        terminal = {'exit_code': completed.returncode}
    except subprocess.TimeoutExpired:
        terminal['error'] = 'Local ffmpeg assembly timed out.'
    except (OSError, ValueError, RuntimeError):
        terminal['error'] = 'Local ffmpeg assembly could not start.'
    temporary = directory / 'terminal.tmp'
    temporary.write_text(json.dumps(terminal))
    temporary.replace(directory / 'terminal.json')


if __name__ == '__main__':
    run(Path(sys.argv[1]))
