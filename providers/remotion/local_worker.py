from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from providers.ffmpeg.api import _bounded_run


def run(directory: Path) -> None:
    job = json.loads((directory / 'worker.json').read_text())
    terminal = {'exit_code': None}
    try:
        completed = _bounded_run(job['command'], directory, job['timeout'])
        (directory / 'stderr.txt').write_bytes(completed.stderr)
        terminal = {'exit_code': completed.returncode}
    except subprocess.TimeoutExpired:
        terminal['error'] = 'Local ffmpeg assembly timed out.'
    except OSError:
        terminal['error'] = 'Local ffmpeg assembly could not start.'
    temporary = directory / 'terminal.tmp'
    temporary.write_text(json.dumps(terminal))
    temporary.replace(directory / 'terminal.json')


if __name__ == '__main__':
    run(Path(sys.argv[1]))
