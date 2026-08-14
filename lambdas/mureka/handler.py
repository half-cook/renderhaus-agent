"""Compatibility wrapper. Deploy uses lambdas/handler.py with RENDERHAUS_PROVIDER=mureka."""

from __future__ import annotations

import os
import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.environ.setdefault("RENDERHAUS_PROVIDER", "mureka")

from lambdas.handler import handler, lambda_handler  # noqa: E402, F401
