from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import NamedTuple

from langchain_core.messages import AIMessage


class ModelRates(NamedTuple):
    input: float
    output: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float


# First-party list prices read 2026-10-09; excludes partner-host pricing.
# https://platform.claude.com/docs/en/about-claude/pricing
MODEL_RATES = {
    "claude-haiku-5-5": ModelRates(0.10, 0.50, 0.125, 0.20, 0.01),
    "claude-opus-5-5": ModelRates(4.0, 20.0, 5.0, 8.0, 0.20),
    "claude-sonnet-5-5": ModelRates(2.0, 10.0, 2.5, 4.0, 0.10),
}


class ModelUsage:

    def __init__(self, run_scope: str):
        self.run_scope = run_scope
        self._seen: set[str] = set()
        self._totals: dict[str, dict] = defaultdict(lambda: {
            "calls": 0, "input_tokens": 0, "output_tokens": 0,
            "cache_read_tokens": 0, "cache_write_tokens": 0,
            "cache_write_5m_tokens": 0, "cache_write_1h_tokens": 0,
            "estimated_cost_usd": 0.0, "unknown_cost_calls": 0,
        })

    def record(self, message: AIMessage) -> None:
        usage = message.usage_metadata
        if not usage or (message.id and message.id in self._seen):
            return
        if message.id:
            self._seen.add(message.id)
        model = message.response_metadata.get("model_name") or message.response_metadata.get("model") or "unknown"
        total = self._totals[model]
        details = usage.get("input_token_details", {})
        prompt, output = usage["input_tokens"], usage["output_tokens"]
        read, write = details.get("cache_read", 0), details.get("cache_creation", 0)
        write_1h = details.get("ephemeral_1h_input_tokens", 0)
        write_5m = details.get("ephemeral_5m_input_tokens", 0)
        write_5m += max(0, write - write_5m - write_1h)
        write = write_5m + write_1h
        total["calls"] += 1
        total["input_tokens"] += prompt
        total["output_tokens"] += output
        total["cache_read_tokens"] += read
        total["cache_write_tokens"] += write
        total["cache_write_5m_tokens"] += write_5m
        total["cache_write_1h_tokens"] += write_1h
        rates = MODEL_RATES.get(model)
        if rates is None:
            total["unknown_cost_calls"] += 1
            return
        if model == "claude-haiku-5-5" and prompt > 100_000:
            rates = ModelRates(0.50, 2.50, 0.625, 1.0, 0.05)
        ordinary = max(0, prompt - read - write)
        total["estimated_cost_usd"] += (
            ordinary * rates.input + output * rates.output + write_5m * rates.cache_write_5m
            + write_1h * rates.cache_write_1h + read * rates.cache_read
        ) / 1_000_000

    def records(self) -> list[dict]:
        return [{"event": "agent_model_usage", "entry_point": "deepagents",
                 "run_scope": self.run_scope, "model": model,
                 "price_source": "https://platform.claude.com/docs/en/about-claude/pricing",
                 "price_read_date": "2026-10-09", **total,
                 "estimated_cost_usd": None if total["unknown_cost_calls"]
                 else total["estimated_cost_usd"]}
                for model, total in sorted(self._totals.items())]

    def publish(self, logger: logging.Logger) -> None:
        for record in self.records():
            logger.info(json.dumps(record, sort_keys=True))
