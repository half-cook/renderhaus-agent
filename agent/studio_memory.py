"""Portable OpenAI Agents SDK session storage for Studio conversations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class StudioMemorySession:
    """An SDK-compatible session whose snapshot can cross runtime boundaries."""

    session_settings = None

    def __init__(self, session_id: str, items: list[dict[str, Any]] | None = None) -> None:
        self.session_id = session_id
        self._items: list[Any] = deepcopy(items or [])

    async def get_items(self, limit: int | None = None) -> list[Any]:
        items = self._items if limit is None else self._items[-max(0, limit) :]
        return deepcopy(items)

    async def add_items(self, items: list[Any]) -> None:
        self._items.extend(deepcopy(items))

    async def pop_item(self) -> Any | None:
        return deepcopy(self._items.pop()) if self._items else None

    async def clear_session(self) -> None:
        self._items.clear()
