"""Supervisor production records: brief → typed plan → approve → execute."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

from agent.config import ROOT

PRODUCTIONS_DIR = ROOT / ".renderhaus" / "productions"

PUBLIC_FIELDS = {
    "id",
    "schema_version",
    "user_id",
    "brief",
    "title",
    "status",
    "plan",
    "execution",
    "error",
    "created_at",
    "updated_at",
    "approved_at",
    "completed_at",
}


def _now() -> int:
    return int(time.time())


def public_production(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in PUBLIC_FIELDS if key in record}


class ProductionStore:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or PRODUCTIONS_DIR
        self._items: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        for path in self.directory.glob("*.json"):
            try:
                item = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                self._items[item["id"]] = item

    async def create(
        self,
        *,
        user_id: str,
        brief: str,
        title: str = "",
    ) -> dict[str, Any]:
        now = _now()
        record = {
            "id": uuid.uuid4().hex,
            "schema_version": 1,
            "user_id": user_id,
            "brief": brief.strip(),
            "title": title.strip() or "Untitled production",
            "status": "draft",
            "plan": None,
            "execution": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "approved_at": None,
            "completed_at": None,
        }
        await self.put(record)
        return record

    async def put(self, record: dict[str, Any]) -> None:
        async with self._lock:
            record["updated_at"] = _now()
            self._items[record["id"]] = record
            self.directory.mkdir(parents=True, exist_ok=True)
            target = self.directory / f"{record['id']}.json"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(record, indent=2, sort_keys=True))
            temporary.replace(target)

    async def get(self, production_id: str) -> dict[str, Any] | None:
        return self._items.get(production_id)

    async def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        items = [item for item in self._items.values() if item.get("user_id") == user_id]
        items.sort(key=lambda item: item.get("updated_at", 0), reverse=True)
        return items

    async def delete(self, production_id: str) -> None:
        async with self._lock:
            self._items.pop(production_id, None)
            path = self.directory / f"{production_id}.json"
            if path.exists():
                path.unlink()
