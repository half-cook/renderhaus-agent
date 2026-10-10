from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

from providers.ffmpeg.api import _bounded_run, _redact


def run(directory: Path) -> None:
    job = json.loads((directory / 'worker.json').read_text())
    terminal = {'exit_code': None}
    try:
        deadline = time.monotonic() + job['timeout']
        if 'props' in job:
            from providers.remotion.local import _command

            command, _ = _command(job['props'], directory,
                                  media_roots=tuple(Path(root) for root in job['media_roots']),
                                  source_root=Path(job['source_root']), filename=job['filename'])
        else:
            command = job['command']
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired('ffmpeg', job['timeout'])
        completed = _bounded_run(command, directory, remaining)
        (directory / 'stderr.txt').write_bytes(completed.stderr)
        terminal = {'exit_code': completed.returncode}
    except subprocess.TimeoutExpired:
        terminal['error'] = 'Local ffmpeg assembly timed out.'
    except OSError:
        terminal['error'] = 'Local ffmpeg assembly could not start.'
    except (ValueError, RuntimeError) as exc:
        terminal['error'] = _redact(str(exc), directory)
    temporary = directory / 'terminal.tmp'
    temporary.write_text(json.dumps(terminal))
    temporary.replace(directory / 'terminal.json')


if __name__ == '__main__':
    run(Path(sys.argv[1]))
