from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def run(directory: Path) -> None:
    job = json.loads((directory / 'worker.json').read_text())
    terminal = {'exit_code': None}
    try:
        with (directory / 'stderr.txt').open('wb') as stderr:
            completed = subprocess.run(job['command'], stdout=subprocess.DEVNULL, stderr=stderr,
                                       timeout=job['timeout'], check=False)
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
