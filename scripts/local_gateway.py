#!/usr/bin/env python3
"""Loopback MCP Gateway with progressive search over committed provider schemas."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import mcp_types as types
from mcp.server.lowlevel.server import Server
import uvicorn

from providers.catalog import PROVIDERS
from providers.registry import dispatch, load_committed_schemas
from agent.deep_agent.routing import estimate_cost

SEARCH_NAME = 'x_amz_bedrock_agentcore_search'
SEARCH_TOOL = types.Tool(name=SEARCH_NAME, description=(
    'Search provider tools by capability, provider, verb, or model. Returns matching full tool '
    'schemas for progressive discovery; use the returned Target___tool names to call them.'),
    input_schema={'type': 'object', 'properties': {
        'query': {'type': 'string', 'description': 'Capability or exact tool name to search.'},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20, 'default': 8},
    }, 'required': ['query']})
logger = logging.getLogger(__name__)


class LocalGateway:
    def __init__(self, *, max_spend_cents: int | None = None, ledger: Path | None = None) -> None:
        if max_spend_cents is not None and max_spend_cents < 0:
            raise ValueError('max_spend_cents must be nonnegative.')
        self.tools: dict[str, tuple[str, str, dict[str, Any]]] = {}
        for provider in PROVIDERS:
            for schema in load_committed_schemas(provider):
                name = f'{provider.target_name}___{schema["name"]}'
                self.tools[name] = (provider.id, schema['name'], {**schema, 'name': name})
        self.max_spend_cents = max_spend_cents
        self.ledger = ledger
        self.spent_cents = 0
        self.reserved_cents = 0
        self._spend_lock = asyncio.Lock()
        if ledger and ledger.is_file():
            self.spent_cents = sum(int(json.loads(line).get('charged_cents', 0))
                                   for line in ledger.read_text().splitlines() if line.strip())
        self.server = Server('renderhaus-local-gateway', on_list_tools=self.list_tools,
                             on_call_tool=self.call_tool)

    async def list_tools(self, context: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[SEARCH_TOOL])

    def search(self, query: str, limit: int = 8) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip() or len(query) > 2000:
            raise ValueError('query must be a nonempty string of at most 2000 characters.')
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 20:
            raise ValueError('limit must be an integer from 1 to 20.')
        stopwords = {'the', 'a', 'an', 'for', 'to', 'and', 'with', 'tool', 'tools', 'use', 'get'}
        words = set(re.findall(r'[a-z0-9]+', query.lower())) - stopwords
        ranked: list[tuple[int, str]] = []
        for name, (_, _, schema) in self.tools.items():
            named = set(re.findall(r'[a-z0-9]+', name.lower()))
            described = set(re.findall(r'[a-z0-9]+', schema.get('description', '').lower()))
            score = 4 * len(words & named) + len(words & described)
            if name.lower() in query.lower():
                score += 100
            if score:
                ranked.append((score, name))
        ranked.sort(key=lambda entry: (-entry[0], entry[1]))
        return {'tools': [self.tools[name][2] for _, name in ranked[:limit]],
                'matched_count': len(ranked)}

    async def call_tool(self, context: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        name, arguments = params.name, dict(params.arguments or {})
        started = time.monotonic()
        estimate = 0
        attempted = False
        payload: dict[str, Any]
        if name == SEARCH_NAME:
            try:
                if set(arguments) - {'query', 'limit'}:
                    raise ValueError('Search accepts query and optional limit only.')
                payload = self.search(arguments.get('query'), arguments.get('limit', 8))
            except ValueError as exc:
                payload = {'error': str(exc), 'error_type': 'ValueError'}
        elif name not in self.tools:
            payload = {'error': 'Unknown Gateway tool.', 'error_type': 'ValueError'}
        else:
            provider, verb, _ = self.tools[name]
            blocked = ''
            if self.max_spend_cents is not None:
                try:
                    quote = estimate_cost(name, arguments, list_price=True)
                    if quote.total_cents is None:
                        raise ValueError("Unknown list-price estimate.")
                    estimate = quote.total_cents
                except (ValueError, TypeError, KeyError):
                    blocked = 'Local spend guard requires a known cost estimate.'
                async with self._spend_lock:
                    if not blocked and self.spent_cents + self.reserved_cents + estimate > self.max_spend_cents:
                        blocked = 'Local spend cap would be exceeded.'
                    if not blocked:
                        self.reserved_cents += estimate
            if blocked:
                payload = {'status': 'blocked', 'error': blocked}
            else:
                attempted = True
                try:
                    result = await asyncio.to_thread(dispatch, provider, verb, arguments)
                    payload = result if isinstance(result, dict) else {'result': result}
                except Exception as exc:  # Same registry boundary as the Lambda handler.
                    payload = {'error': 'Local provider dispatch failed.', 'error_type': type(exc).__name__}
                if self.max_spend_cents is not None:
                    async with self._spend_lock:
                        self.reserved_cents -= estimate
                        # A timeout/error after dispatch may still incur provider charges.
                        if payload.get('status') != 'dry_run':
                            self.spent_cents += estimate
        record = {'event': 'local_gateway_call', 'tool': name,
                  'status': payload.get('status', 'error' if payload.get('error') else 'succeeded'),
                  'error_type': payload.get('error_type'),
                  'latency_ms': round((time.monotonic() - started) * 1000),
                  'estimate_cents': estimate if self.max_spend_cents is not None else None,
                  'charged_cents': estimate if attempted and payload.get('status') != 'dry_run' else 0}
        # Never log arguments, credentials, URLs, provider payloads, or exception text.
        logger.info(json.dumps(record, sort_keys=True))
        if self.ledger:
            self.ledger.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger.open('a') as file:
                file.write(json.dumps(record, sort_keys=True) + '\n')
        return types.CallToolResult(content=[types.TextContent(type='text', text=json.dumps(payload, default=str))],
                                    structured_content=payload, is_error=bool(payload.get('error')))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--max-spend-cents', type=int, help='Optional conservative total cap; unknown costs block.')
    parser.add_argument('--ledger', type=Path, help='Optional JSONL ledger without arguments or URLs.')
    args = parser.parse_args()
    if os.getenv('AGENTCORE_GATEWAY_ALLOW_LOOPBACK_HTTP', '').lower() != 'true':
        parser.error('Set AGENTCORE_GATEWAY_ALLOW_LOOPBACK_HTTP=true for this explicit development mode.')
    gateway = LocalGateway(max_spend_cents=args.max_spend_cents, ledger=args.ledger)
    app = gateway.server.streamable_http_app(host='127.0.0.1')
    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
