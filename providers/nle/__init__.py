"""Offline-first NLE handoff for pinned Remotion timeline snapshots."""

from providers.nle.bundle import build_handoff
from providers.nle.model import parse_snapshot


__all__ = ["build_handoff", "parse_snapshot"]
