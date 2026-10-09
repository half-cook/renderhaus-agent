#!/usr/bin/env python3
"""Run the lighthouse brief through Deep Agents and a guarded loopback MCP Gateway.

The default writes a dry-run plan without contacting models or providers. Operators
must pass --live and configure provider dry-run flags themselves to authorize calls.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langchain_core.callbacks import BaseCallbackHandler
from langsmith import tracing_context
import uvicorn

from agent.backend_config import configured_deep_agent_model, deep_agent_model
from agent.deep_agent.routing import POLICY, estimate_cost, is_free_tool
from agent.deep_agent.usage import MODEL_RATES, ModelUsage
from agent.gateway_client import GatewayClient
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, run_studio_agent,
)
from scripts.local_gateway import LocalGateway, SEARCH_NAME

BRIEF = (
    "Make a 5-second cinematic shot: a lighthouse keeper climbing a spiral staircase at dusk, "
    "warm lamp light, slow push-in, with a one-line voiceover: "
    "'Every night, someone has to keep the light.' "
    "Generate the voiceover concurrently with the video. Keep the source video frame rate and "
    "quality in the final export. Use local Remotion assembly. Never retry any paid generation."
)


def paid_step_key(tool_name):
    if 'text_to_speech' in tool_name or tool_name.endswith('___generate_speech'):
        return 'voiceover'
    for row in POLICY['capabilities']:
        for capability, name in row.get('tools', {}).items():
            if name == tool_name:
                return ('video-generation' if capability in {
                    't2v', 'i2v', 'reference', 'ref', 'reference_video', 'start_end_frame',
                } else capability)
    return tool_name


@dataclass(frozen=True)
class LighthouseOptions:
    out: Path
    live: bool = False
    spend_cap_usd: Decimal = Decimal('5')
    max_output_tokens: int = 4096
    max_turns: int = 40
    timeout_seconds: int = 1800
    prompt: str = BRIEF

    def __post_init__(self):
        cap = Decimal(str(self.spend_cap_usd))
        if not cap.is_finite() or cap <= 0 or cap * 100 != (cap * 100).to_integral_value():
            raise ValueError('Spend cap must be a positive whole number of cents.')
        if self.max_output_tokens <= 0 or self.max_turns <= 0 or self.timeout_seconds <= 0:
            raise ValueError('Token, turn and timeout limits must be positive.')


class SpendBudget:
    def __init__(self, cap_cents: int):
        self.cap_cents = Decimal(cap_cents)
        self.model_cents = Decimal(0)
        self.media_cents = Decimal(0)
        self._reservations: dict[str, Decimal] = {}
        self._paid_attempts: set[str] = set()
        self.unknown_cost = False
        self._lock = threading.RLock()

    @property
    def reserved_cents(self):
        with self._lock:
            return sum(self._reservations.values(), Decimal(0))

    def approval_blocker(self, tool_name, cents, pending_cents=0):
        with self._lock:
            if cents == 0:
                return None
            if self.unknown_cost or cents is None:
                return 'Cost unknown; refusing further paid work.'
            if cents > 0 and paid_step_key(tool_name) in self._paid_attempts:
                return 'Paid retries are disabled; reconcile the original job.'
            if self.model_cents + self.media_cents + self.reserved_cents + cents + pending_cents > self.cap_cents:
                return 'Hard spend cap would be exceeded.'
            return None

    def reserve_media(self, tool_name, estimate_cents):
        with self._lock:
            if blocker := self.approval_blocker(tool_name, estimate_cents):
                return blocker
            if estimate_cents > 0:
                self._paid_attempts.add(paid_step_key(tool_name))
            self._reservations['media:' + tool_name] = Decimal(estimate_cents)
            return None

    def settle_media(self, tool_name, estimate_cents, *, charged):
        with self._lock:
            self._reservations.pop('media:' + tool_name, None)
            if charged:
                self.media_cents += Decimal(estimate_cents)

    def reserve_model(self, call_id, estimate_cents):
        with self._lock:
            if blocker := self.approval_blocker('', estimate_cents):
                raise RuntimeError(blocker)
            self._reservations['model:' + str(call_id)] = Decimal(str(estimate_cents))

    def complete_model(self, call_id, actual_cents):
        with self._lock:
            if actual_cents is None:
                self.unknown_cost = True
                return
            reserved = self._reservations.pop('model:' + str(call_id), Decimal(0))
            self.model_cents += Decimal(str(actual_cents))
            if Decimal(str(actual_cents)) > reserved:
                self.unknown_cost = True
                raise RuntimeError('Model usage exceeded its conservative reservation; run stopped.')


class ModelMeter(BaseCallbackHandler):
    raise_error = True
    run_inline = True

    def __init__(self, budget, *, model, journal=None):
        if model not in MODEL_RATES:
            raise ValueError('Official token price is unknown for selected model.')
        self.budget, self.model, self.journal = budget, model, journal
        self.usage = ModelUsage('e2e-lighthouse')
        self._lock = threading.RLock()

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        for batch in messages:
            for message in batch:
                if not text_content(message.content):
                    raise RuntimeError('This text-only driver rejects unpriced multimodal inputs.')
        params = kwargs.get('invocation_params') or {}
        max_output = params.get('max_tokens') or params.get('max_tokens_to_sample')
        if not isinstance(max_output, int) or max_output <= 0:
            raise RuntimeError('Model output token limit unknown; refusing model call.')
        # One token per UTF-8 byte plus framing covers arbitrary user/tool text.
        raw = json.dumps([[message.model_dump() for message in batch] for batch in messages],
                         ensure_ascii=False, default=str) + json.dumps(params, ensure_ascii=False, default=str)
        input_bound = len(raw.encode('utf-8')) + 10_000 + 64 * sum(map(len, messages))
        rates = MODEL_RATES[self.model]
        input_rate = max(rates.input, rates.cache_write_5m, rates.cache_write_1h)
        output_rate = rates.output
        if self.model == 'claude-haiku-5-5':
            input_rate, output_rate = max(input_rate, 1.0), max(output_rate, 2.5)
        reserved = (Decimal(input_bound) * Decimal(str(input_rate))
                    + Decimal(max_output) * Decimal(str(output_rate))) / Decimal(10_000)
        self.budget.reserve_model(run_id, reserved)
        if self.journal:
            self.journal.record('model_call_start', model=self.model, reserved_cents=float(reserved),
                                max_output_tokens=max_output)

    def on_llm_end(self, response, *, run_id, **kwargs):
        with self._lock:
            before = self.summary()['estimated_cost_usd']
            found = False
            for generations in response.generations:
                for generation in generations:
                    message = getattr(generation, 'message', None)
                    if message is not None and message.usage_metadata:
                        found = True
                        if not (message.response_metadata.get('model_name') or message.response_metadata.get('model')):
                            message.response_metadata['model'] = self.model
                        self.usage.record(message)
            after = self.summary()['estimated_cost_usd']
            self.budget.complete_model(run_id, None if not found or after is None or before is None
                                       else (after - before) * 100)
            if self.journal:
                self.journal.record('model_usage', model=self.model, **self.summary())

    def on_llm_error(self, error, *, run_id, **kwargs):
        # A transport timeout may have consumed tokens. Keep the reservation.
        self.budget.unknown_cost = True
        if self.journal:
            self.journal.record('model_error', error_type=type(error).__name__)

    def summary(self):
        return aggregate_usage(self.usage.records())


def aggregate_usage(rows):
    counters = ('calls', 'input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens',
                'cache_write_5m_tokens', 'cache_write_1h_tokens', 'unknown_cost_calls')
    total = {key: sum(row.get(key, 0) for row in rows) for key in counters}
    total['estimated_cost_usd'] = (None if total['unknown_cost_calls'] else
                                 sum(row['estimated_cost_usd'] for row in rows))
    total['per_model'] = rows
    return total


def text_content(content):
    if isinstance(content, str):
        return True
    if not isinstance(content, list):
        return False
    for block in content:
        if isinstance(block, str):
            continue
        if not isinstance(block, dict) or block.get('type') not in {
            'text', 'thinking', 'redacted_thinking', 'tool_use', 'tool_result',
        }:
            return False
        if block['type'] == 'tool_result' and not text_content(block.get('content', '')):
            return False
    return True


def sanitize(value):
    if isinstance(value, dict):
        return {key: ('[redacted]' if re.search(r'token|secret|password|authorization|api.?key|cookie', key, re.I)
                      and key not in {'tokens', 'input_tokens', 'output_tokens', 'total_tokens', 'cache_read_tokens',
                                      'cache_write_tokens', 'cache_write_5m_tokens', 'cache_write_1h_tokens',
                                      'max_output_tokens'} else sanitize(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        def clean_url(match):
            parsed = urlsplit(match.group())
            return urlunsplit((parsed.scheme, parsed.hostname or '', parsed.path, '', ''))
        value = re.sub(r'https?://[^\s<>"\']+', clean_url, value)
        return re.sub(r'(?i)(?:Bearer\s+|(?:HF_TOKEN|[A-Z_]*(?:API_KEY|SECRET|TOKEN))\s*[=:]\s*)[^\s,;]+',
                      '[redacted]', value)
    return value


class EventJournal:
    def __init__(self, path, run_id):
        self.path, self.run_id = path, run_id
        self.path.touch()
        self._lock = threading.Lock()

    def record(self, kind, **values):
        row = sanitize({'time': time.time(), 'kind': kind, 'entry_point': 'e2e_lighthouse',
                        'run_id': self.run_id, **values})
        with self._lock, self.path.open('a') as file:
            file.write(json.dumps(row, default=str, sort_keys=True) + '\n')


@contextmanager
def driver_runtime(environment, model_factory):
    from agent.deep_agent import runner

    previous = {key: os.environ.get(key) for key in environment}
    factory = runner.configured_deep_agent_model
    os.environ.update(environment)
    runner.configured_deep_agent_model = model_factory
    try:
        yield
    finally:
        runner.configured_deep_agent_model = factory
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@asynccontextmanager
async def loopback_gateway(gateway):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        app = gateway.server.streamable_http_app(host='127.0.0.1')
        server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False, lifespan='on'))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError('Loopback Gateway failed to start.')
                    await asyncio.sleep(0.01)
            async with GatewayClient({'url': f'http://127.0.0.1:{port}/mcp', 'allow_loopback_http': True},
                                     name='lighthouse-local-gateway') as client:
                yield client
        finally:
            server.should_exit = True
            await task


def _write_json(path, data):
    path.write_text(json.dumps(sanitize(data), indent=2, default=str, sort_keys=True) + '\n')


def probe_artifact(events, out):
    artifacts = [event['result'].get('output_path') for event in events.values()
                 if event.get('name') in {'Remotion___get_render_progress', 'Remotion___render_timeline'}
                 and event.get('status') == 'succeeded' and event.get('result', {}).get('status') == 'succeeded']
    if not artifacts or not artifacts[-1] or not Path(artifacts[-1]).is_file():
        raise ValueError('Final local video artifact is missing; run incomplete.')
    destination = out / 'final.mp4'
    shutil.copyfile(artifacts[-1], destination)
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json',
                             str(destination)], check=True, capture_output=True, text=True, timeout=30)
    probe = json.loads(result.stdout)
    video = next((stream for stream in probe.get('streams', []) if stream.get('codec_type') == 'video'), None)
    if not video or float(probe.get('format', {}).get('duration', 0)) <= 0:
        raise ValueError('Final artifact has no playable video stream.')
    if not any(stream.get('codec_type') == 'audio' for stream in probe.get('streams', [])):
        raise ValueError('Lighthouse artifact has no voiceover audio stream; run incomplete.')
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(destination), '-f', 'null', '-'],
                   check=True, capture_output=True, timeout=60)
    _write_json(out / 'final.ffprobe.json', probe)
    _write_json(out / 'final.ffprobe.txt', probe)
    return {'fps': video.get('r_frame_rate'),
            'bitrate_bps': int(video.get('bit_rate') or probe.get('format', {}).get('bit_rate') or 0),
            'duration_seconds': float(probe['format']['duration']), 'artifact': 'final.mp4'}


async def run_lighthouse(options, *, agent_run=None):
    out = options.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError('Output directory must be empty; use a new directory for each run.')
    cap_cents = int(Decimal(str(options.spend_cap_usd)) * 100)
    run_id = 'lighthouse-' + uuid4().hex
    journal = EventJournal(out / 'agent_events.jsonl', run_id)
    ledger = out / 'gateway_ledger.jsonl'
    ledger.touch()
    budget = SpendBudget(cap_cents)
    model_id = deep_agent_model().split(':', 1)[1]
    summary = {'status': 'dry_run', 'run_id': run_id, 'model': deep_agent_model(),
               'spend_cap_usd': cap_cents / 100, 'model_cost_usd': 0, 'media_cost_usd': 0,
               'total_cost_usd': 0, 'tokens': {}, 'media_steps': [], 'wall_time_seconds': 0,
               'fps': None, 'bitrate_bps': None, 'browser_e2e': 'blocked: Comet unavailable'}
    journal.record('request', prompt=options.prompt, model=summary['model'], live=options.live,
                   spend_cap_usd=summary['spend_cap_usd'])
    if not options.live:
        summary['reason'] = 'Plan only. Pass --live to authorize the real agent and configured providers.'
        _write_json(out / 'summary.json', summary)
        return summary
    meters = {}
    events = {}
    approved = set()
    configured = configured_deep_agent_model
    def make_model(role=None):
        selected = deep_agent_model(role)
        if not selected.startswith('anthropic:') or selected.split(':', 1)[1] not in MODEL_RATES:
            raise ValueError('Operator driver requires a model with verified Anthropic token prices.')
        model = configured(role)
        model.max_tokens = options.max_output_tokens
        model.max_retries = 0
        selected_id = selected.split(':', 1)[1]
        if selected_id not in meters:
            meters[selected_id] = ModelMeter(budget, model=selected_id, journal=journal)
        callback = meters[selected_id]
        model.callbacks = [*(model.callbacks or []), callback]
        journal.record('model', role=role, model=selected, max_output_tokens=options.max_output_tokens)
        return model
    def tool_event(event):
        row = event.public()
        events[row['id']] = row
        journal.record('tool_event', **row)
    def progress(event):
        journal.record('progress', **event.public())
    base = {'prompt': options.prompt, 'job_id': run_id, 'conversation_id': run_id,
            'workspace_id': 'e2e-lighthouse', 'project_id': 'e2e-lighthouse', 'autonomous': False}
    request = StudioAgentRequest(**base)
    started = time.monotonic()
    env = {'RENDERHAUS_AGENT_BACKEND': 'deepagents', 'RENDERHAUS_SECRETS_NAME': '',
           'REMOTION_RENDER_BACKEND': 'local', 'RENDERHAUS_MEDIA_DIR': str(out / 'media'),
           'LANGSMITH_TRACING': 'false', 'LANGSMITH_TRACING_V2': 'false',
           'LANGCHAIN_TRACING': 'false', 'LANGCHAIN_TRACING_V2': 'false'}
    try:
        meters[model_id] = ModelMeter(budget, model=model_id, journal=journal)
        gateway = LocalGateway(max_spend_cents=cap_cents, ledger=ledger, spend_guard=budget)
        with driver_runtime(env, make_model), tracing_context(enabled=False):
            async with asyncio.timeout(options.timeout_seconds), loopback_gateway(gateway) as client:
                for turn in range(options.max_turns):
                    journal.record('turn', turn=turn)
                    try:
                        final = await (agent_run or run_studio_agent)(request, mcp_servers=[client],
                                                                     event_sink=tool_event, progress_sink=progress)
                        _write_json(out / 'final.json', final.model_dump())
                        summary.update(probe_artifact(events, out), status='completed')
                        break
                    except StudioAgentApprovalRequired as exc:
                        decisions = []
                        pending = 0
                        for approval in exc.approvals:
                            cost = estimate_cost(approval.tool_name, approval.arguments, list_price=True)
                            blocker = budget.approval_blocker(approval.tool_name, cost.total_cents, pending)
                            step = paid_step_key(approval.tool_name)
                            if cost.total_cents and step in approved:
                                blocker = 'Paid retries are disabled; reconcile the original job.'
                            if not blocker:
                                pending += cost.total_cents
                                if cost.total_cents:
                                    approved.add(step)
                            decisions.append(StudioApprovalDecision(
                                call_id=approval.call_id, decision='reject' if blocker else 'approve', message=blocker))
                            journal.record('approval', call_id=approval.call_id, tool=approval.tool_name,
                                           estimated_cost_cents=cost.total_cents, decision=decisions[-1].decision,
                                           reason=blocker or 'Within hard spend cap.')
                        request = StudioAgentRequest(**base, resume_state=exc.state, approval_decisions=decisions,
                                                     session_items=exc.session_items,
                                                     prior_tool_events=[event.public() for event in exc.tool_events])
                else:
                    raise RuntimeError('Approval turn limit reached; run incomplete.')
    except Exception as exc:
        summary.update(status='failed', error_type=type(exc).__name__,
                       error=str(exc) if isinstance(exc, ValueError) else 'Run stopped; inspect safe event records.')
        journal.record('error', error_type=type(exc).__name__)
    finally:
        rows = [json.loads(line) for line in ledger.read_text().splitlines() if line]
        steps = [{**row, 'stage': paid_step_key(row['tool'])} for row in rows if row.get('attempted')
                 and row['tool'] != SEARCH_NAME and not is_free_tool(row['tool'])]
        usage = aggregate_usage([row for meter in meters.values() for row in meter.usage.records()])
        summary.update(tokens=usage, model_cost_usd=float(budget.model_cents / 100),
                       media_cost_usd=sum(row['charged_cents'] for row in rows) / 100,
                       media_steps=steps, wall_time_seconds=round(time.monotonic() - started, 3),
                       unpriced_model_usage=budget.unknown_cost,
                       media_cost_basis='Conservative list-price quotes for attempted calls, including uncertain failures.',
                       conservative_reserved_usd=float(budget.reserved_cents / 100))
        summary['total_cost_usd'] = summary['model_cost_usd'] + summary['media_cost_usd']
        if budget.unknown_cost:
            summary.update(status='failed', model_cost_usd=None, total_cost_usd=None)
        journal.record('summary', **summary)
        _write_json(out / 'summary.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--live', action='store_true', help='Authorize model and configured provider calls.')
    parser.add_argument('--spend-cap-usd', type=Decimal, default=Decimal('5'))
    parser.add_argument('--max-output-tokens', type=int, default=4096)
    parser.add_argument('--max-turns', type=int, default=40)
    parser.add_argument('--timeout-seconds', type=int, default=1800)
    parser.add_argument('--prompt', default=BRIEF)
    args = parser.parse_args(argv)
    try:
        options = LighthouseOptions(**vars(args))
        result = asyncio.run(run_lighthouse(options))
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(sanitize(result), sort_keys=True, default=str))
    return 0 if result['status'] in {'completed', 'dry_run'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
