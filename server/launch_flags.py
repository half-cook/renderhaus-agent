"""Launch switches read from the environment (no imports beyond stdlib)."""

from __future__ import annotations

import os

TOPUPS_COMING_SOON = "Top-ups are coming soon."


def topups_enabled() -> bool:
    """Purchases (top-ups, subscriptions, portal, webhook crediting) are off unless
    TOPUPS_ENABLED=true. The invite-only beta ships with them off: the one-time
    beta grant is the only way balance is added."""
    return os.getenv("TOPUPS_ENABLED", "false").strip().lower() in {"true", "1"}
