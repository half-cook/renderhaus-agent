from __future__ import annotations

import json
import asyncio
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import mcp_types as types
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult


class LighthouseSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_scripted_lighthouse_corrects_unpriced_tts_without_unknown_cost_approval(self):
        from agent.studio_agent_next import run_studio_agent
        from scripts.e2e_lighthouse import LighthouseOptions, run_lighthouse
        from test_deep_agent import ScriptedModel, call
        from test_deep_agent_execution import FINAL, TTS, TTS_ARGS, VIDEO, VIDEO_ARGS, dispatch

        corrected = {key: value for key, value in TTS_ARGS.items() if key != "model_id"}

        def correct_model(messages, tools):
            self.assertIn("Allowed model_ids:", messages[-1].text)
            result = json.loads(messages[-1].text)
            self.assertEqual(result["status"], "failed")
            self.assertIn("Allowed model_ids:", result["error"])
            self.assertIn("eleven_v4_turbo", result["error"])
            return dispatch(TTS, corrected, "good-tts")

        model = ScriptedModel([
            call("x_amz_bedrock_agentcore_search", {"query": f"{VIDEO.name} {TTS.name}", "limit": 2}, "search"),
            dispatch(VIDEO, VIDEO_ARGS, "video"),
            dispatch(TTS, {**TTS_ARGS, "model_id": "eleven_multilingual_v2"}, "bad-tts"),
            correct_model, call("StudioAgentOutput", FINAL, "finish"),
        ])

        async def agent(request, **kwargs):
            with patch("agent.deep_agent.runner.configured_deep_agent_model", return_value=model):
                return await run_studio_agent(request, **kwargs)

        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {
            "RENDERHAUS_OUTCOME_DIR": directory, "STRIPE_SECRET_KEY": "",
            "ELEVENLABS_TTS_MODEL": "eleven_v4_turbo", "ELEVENLABS_TOOL_COST_CENTS_JSON": "{}",
        }), patch("scripts.local_gateway.dispatch", return_value={"status": "succeeded"}) as provider, \
                patch("scripts.e2e_lighthouse.probe_artifact", return_value={}):
            out = Path(directory) / "out"
            summary = await run_lighthouse(LighthouseOptions(out=out, live=True), agent_run=agent)
            rows = [json.loads(line) for line in (out / "agent_events.jsonl").read_text().splitlines()]
        self.assertEqual(summary["status"], "completed", summary)
        approvals = [row for row in rows if row["kind"] == "approval"]
        self.assertCountEqual([row["tool"] for row in approvals], [VIDEO.name, TTS.name])
        self.assertTrue(all(row["decision"] == "approve" for row in approvals))
        self.assertFalse(any("unknown" in row.get("reason", "").lower() for row in approvals))
        self.assertCountEqual([item.args for item in provider.call_args_list], [
            ("fal", "generate_wan3_t2v", VIDEO_ARGS), ("elevenlabs", "text_to_speech_convert", corrected),
        ])
        self.assertFalse(model._steps)

    async def test_parallel_subagent_approvals_use_discovered_schemas_and_never_retry(self):
        from agent.studio_agent_next import run_studio_agent
        from scripts.e2e_lighthouse import LighthouseOptions, run_lighthouse
        from test_deep_agent import ScriptedModel, call
        from test_deep_agent_execution import FINAL, VIDEO, VIDEO_ARGS, VOICES, dispatch

        voice_args = {"search": "narrator"}
        tasks = AIMessage(content="", tool_calls=[
            call("task", {"subagent_type": "media", "description": "Generate the lighthouse"}, "media-task").tool_calls[0],
            call("task", {"subagent_type": "audio", "description": "Find a narrator"}, "audio-task").tool_calls[0],
        ])

        def propose(messages, tools):
            if "call_media_tool" in tools:
                return dispatch(VIDEO, VIDEO_ARGS, "wan-call")
            return dispatch(VOICES, voice_args, "voices-call")

        def completed(messages, tools):
            from langchain_core.messages import ToolMessage

            self.assertIsInstance(messages[-1], ToolMessage, "Approval resume replayed the proposed call")
            self.assertEqual(messages[-1].tool_call_id,
                             "wan-call" if "call_media_tool" in tools else "voices-call")
            result = json.loads(messages[-1].text)
            self.assertNotEqual(result.get("status"), "failed", result)
            return AIMessage(content="Task completed.")

        model = ScriptedModel([
            call("x_amz_bedrock_agentcore_search", {
                "query": f"{VIDEO.name} {VOICES.name}", "limit": 2,
            }, "search"), tasks, propose, propose, completed, completed,
            call("StudioAgentOutput", FINAL, "finish"),
        ])
        batches = []
        failures = []

        async def agent(request, **kwargs):
            if request.approval_decisions:
                batches.append(request.approval_decisions)
            with patch("agent.deep_agent.runner.configured_deep_agent_model", return_value=model):
                try:
                    return await run_studio_agent(request, **kwargs)
                except AssertionError as exc:
                    failures.append(str(exc))
                    raise

        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {
            "RENDERHAUS_OUTCOME_DIR": directory, "STRIPE_SECRET_KEY": "",
        }), patch("scripts.local_gateway.dispatch", return_value={"status": "queued", "job_id": "offline-job"}) as provider, \
                patch("scripts.e2e_lighthouse.probe_artifact", return_value={}):
            out = Path(directory) / "out"
            summary = await run_lighthouse(LighthouseOptions(out=out, live=True), agent_run=agent)
            rows = [json.loads(line) for line in (out / "agent_events.jsonl").read_text().splitlines()]
            ledger = [json.loads(line) for line in (out / "gateway_ledger.jsonl").read_text().splitlines()]
        self.assertEqual(summary["status"], "completed", {"native_failures": failures, "summary": summary})
        self.assertEqual(len(batches), 1)
        self.assertEqual([item.decision for item in batches[0]], ["approve", "approve"])
        self.assertCountEqual([row["tool"] for row in rows if row["kind"] == "approval"],
                              [VIDEO.name, VOICES.name])
        self.assertFalse(any("retries" in row.get("reason", "").lower() for row in rows))
        self.assertCountEqual([row["tool"] for row in ledger if row["attempted"]], [VIDEO.name, VOICES.name])
        self.assertCountEqual([item.args for item in provider.call_args_list],
                              [("fal", "generate_wan3_t2v", VIDEO_ARGS), ("elevenlabs", "voices_search", voice_args)])
        self.assertFalse(model._steps)

    async def test_operator_run_disables_inherited_external_tracing(self):
        from langsmith import tracing_context
        from langsmith.utils import tracing_is_enabled
        from scripts.e2e_lighthouse import LighthouseOptions, run_lighthouse
        from agent.studio_agent_next import StudioAgentOutput

        observed = []
        async def agent(request, **kwargs):
            observed.append(tracing_is_enabled())
            return StudioAgentOutput(title='Tracing check', summary='No media',
                                     markdown='No media', filename='check.md')
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {
            'LANGSMITH_TRACING_V2': 'true', 'LANGCHAIN_TRACING_V2': 'true',
            'LANGCHAIN_TRACING': 'true',
        }), tracing_context(enabled=True):
            await run_lighthouse(LighthouseOptions(out=Path(directory), live=True), agent_run=agent)
            self.assertTrue(tracing_is_enabled())
        self.assertEqual(observed, [False])

    async def test_default_cli_writes_dry_run_plan_without_calling_agent(self):
        from scripts.e2e_lighthouse import main

        with tempfile.TemporaryDirectory() as directory, \
                patch('scripts.e2e_lighthouse.run_studio_agent', new_callable=AsyncMock) as run:
            self.assertEqual(await asyncio.to_thread(main, ['--out', directory]), 0)
            summary = json.loads((Path(directory) / 'summary.json').read_text())
        self.assertEqual(summary['status'], 'dry_run')
        self.assertEqual(summary['spend_cap_usd'], 5)
        self.assertEqual(summary['model_cost_usd'], 0)
        run.assert_not_awaited()

    async def test_approvals_count_model_and_pending_media_reservations(self):
        from scripts.e2e_lighthouse import SpendBudget

        budget = SpendBudget(500)
        budget.reserve_model('model-1', 50)
        self.assertIsNone(budget.reserve_media('Fal___generate_wan3_t2v', 400))
        self.assertIn('cap', budget.approval_blocker('ElevenLabs___text_to_speech_convert', 51))
        self.assertIn('unknown', budget.approval_blocker('Unknown___paid', None))
        budget.complete_model('model-1', 10)
        budget.settle_media('Fal___generate_wan3_t2v', 400, charged=True)
        self.assertIsNone(budget.approval_blocker('ElevenLabs___text_to_speech_convert', 90))

    async def test_paid_dispatch_failure_is_charged_and_changed_argument_retry_is_blocked(self):
        from scripts.e2e_lighthouse import SpendBudget
        from scripts.local_gateway import LocalGateway
        from agent.deep_agent.routing import CostEstimate

        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / 'ledger.jsonl'
            gateway = LocalGateway(max_spend_cents=500, ledger=ledger, spend_guard=SpendBudget(500))
            with patch('scripts.local_gateway.estimate_cost', return_value=CostEstimate(60)), \
                    patch('scripts.local_gateway.dispatch', side_effect=TimeoutError) as dispatch:
                first = await gateway.call_tool(None, types.CallToolRequestParams(
                    name='Fal___generate_wan3_t2v', arguments={'prompt': 'lighthouse'}))
                retry = await gateway.call_tool(None, types.CallToolRequestParams(
                    name='Fal___generate_wan3_t2v', arguments={'prompt': 'lighthouse retry'}))
            rows = [json.loads(line) for line in ledger.read_text().splitlines()]
        self.assertTrue(first.is_error)
        self.assertIn('retries', retry.structured_content['error'].lower())
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual([row['charged_cents'] for row in rows], [60, 0])

    async def test_cancelled_paid_dispatch_keeps_conservative_charge_and_safe_ledger(self):
        from scripts.e2e_lighthouse import SpendBudget
        from scripts.local_gateway import LocalGateway
        from agent.deep_agent.routing import CostEstimate

        started, release = threading.Event(), threading.Event()
        def dispatch(*args):
            started.set()
            release.wait(2)
            return {'status': 'queued'}
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / 'ledger.jsonl'
            budget = SpendBudget(500)
            gateway = LocalGateway(max_spend_cents=500, ledger=ledger, spend_guard=budget)
            with patch('scripts.local_gateway.estimate_cost', return_value=CostEstimate(20)), \
                    patch('scripts.local_gateway.dispatch', side_effect=dispatch):
                task = asyncio.create_task(gateway.call_tool(None, types.CallToolRequestParams(
                    name='Fal___generate_wan3_t2v', arguments={'prompt': 'lighthouse'})))
                try:
                    self.assertTrue(await asyncio.to_thread(started.wait, 1))
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    self.assertEqual(budget.media_cents, 20)
                    self.assertEqual(json.loads(ledger.read_text())['charged_cents'], 20)
                finally:
                    release.set()

    async def test_cache_meter_prices_each_token_once_and_reserves_before_model_call(self):
        from scripts.e2e_lighthouse import ModelMeter, SpendBudget

        budget = SpendBudget(500)
        meter = ModelMeter(budget, model='claude-sonnet-5-5')
        call = uuid4()
        meter.on_chat_model_start({}, [[HumanMessage('hello')]], run_id=call,
                                  invocation_params={'model': 'claude-sonnet-5-5', 'max_tokens': 4096})
        response = LLMResult(generations=[[ChatGeneration(message=AIMessage(
            content='done', response_metadata={'model': 'claude-sonnet-5-5'},
            usage_metadata={'input_tokens': 1000, 'output_tokens': 100, 'total_tokens': 1100,
                            'input_token_details': {'cache_read': 400, 'cache_creation': 300}}))]])
        meter.on_llm_end(response, run_id=call)
        self.assertAlmostEqual(meter.summary()['estimated_cost_usd'], 0.00239)
        self.assertEqual(meter.summary()['input_tokens'], 1000)
        self.assertEqual(meter.summary()['cache_read_tokens'], 400)
        self.assertEqual(budget.reserved_cents, 0)
        tiny = ModelMeter(SpendBudget(1), model='claude-sonnet-5-5')
        with self.assertRaisesRegex(RuntimeError, 'cap'):
            tiny.on_chat_model_start({}, [[HumanMessage('hello')]], run_id=uuid4(),
                                     invocation_params={'max_tokens': 4096})

    async def test_unknown_model_or_unmetered_result_blocks_future_paid_work(self):
        from scripts.e2e_lighthouse import ModelMeter, SpendBudget

        with self.assertRaisesRegex(ValueError, 'price'):
            ModelMeter(SpendBudget(500), model='unknown-model')
        budget = SpendBudget(500)
        meter = ModelMeter(budget, model='claude-sonnet-5-5')
        call = uuid4()
        meter.on_chat_model_start({}, [[HumanMessage('hello')]], run_id=call,
                                  invocation_params={'max_tokens': 4096})
        meter.on_llm_end(LLMResult(generations=[[ChatGeneration(message=AIMessage('unmetered'))]]),
                         run_id=call)
        self.assertIn('unknown', budget.approval_blocker('ElevenLabs___text_to_speech_convert', 2))

    async def test_gateway_blocks_paid_submit_when_model_reservation_uses_remaining_cap(self):
        from scripts.e2e_lighthouse import SpendBudget
        from scripts.local_gateway import LocalGateway
        from agent.deep_agent.routing import CostEstimate

        budget = SpendBudget(500)
        budget.reserve_model('active-model', 499)
        gateway = LocalGateway(max_spend_cents=500, spend_guard=budget)
        with patch('scripts.local_gateway.estimate_cost', return_value=CostEstimate(2)), \
                patch('scripts.local_gateway.dispatch') as dispatch:
            result = await gateway.call_tool(None, types.CallToolRequestParams(
                name='ElevenLabs___text_to_speech_convert', arguments={'text': 'lighthouse'}))
        self.assertTrue(result.is_error)
        self.assertIn('cap', result.structured_content['error'])
        dispatch.assert_not_called()

    async def test_paid_video_provider_fallback_is_rejected_as_an_automatic_retry(self):
        from scripts.e2e_lighthouse import SpendBudget

        budget = SpendBudget(500)
        self.assertIsNone(budget.reserve_media('Fal___generate_wan3_t2v', 50))
        budget.settle_media('Fal___generate_wan3_t2v', 50, charged=True)
        self.assertIn('retries', budget.approval_blocker('Seedance___text_to_video', 50))

    async def test_hidden_vision_token_inputs_are_rejected_before_model_dispatch(self):
        from scripts.e2e_lighthouse import ModelMeter, SpendBudget

        meter = ModelMeter(SpendBudget(500), model='claude-sonnet-5-5')
        with self.assertRaisesRegex(RuntimeError, 'text-only'):
            meter.on_chat_model_start({}, [[HumanMessage(content=[
                {'type': 'image_url', 'image_url': {'url': 'https://media.example/reference.png'}},
            ])]], run_id=uuid4(), invocation_params={'max_tokens': 4096})

    async def test_one_hour_cache_writes_use_distinct_official_rate(self):
        from scripts.e2e_lighthouse import ModelMeter, SpendBudget

        meter = ModelMeter(SpendBudget(500), model='claude-sonnet-5-5')
        call = uuid4()
        meter.on_chat_model_start({}, [[HumanMessage('hello')]], run_id=call,
                                  invocation_params={'max_tokens': 4096})
        response = LLMResult(generations=[[ChatGeneration(message=AIMessage(
            content='done', response_metadata={'model': 'claude-sonnet-5-5'},
            usage_metadata={'input_tokens': 1000, 'output_tokens': 100, 'total_tokens': 1100,
                            'input_token_details': {'cache_read': 400, 'cache_creation': 300,
                                                    'ephemeral_5m_input_tokens': 100,
                                                    'ephemeral_1h_input_tokens': 200}}))]])
        meter.on_llm_end(response, run_id=call)
        self.assertAlmostEqual(meter.summary()['estimated_cost_usd'], 0.00269)

    async def test_corrupt_final_artifact_cannot_report_completed(self):
        from scripts.e2e_lighthouse import probe_artifact

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            corrupt = out / 'corrupt.mp4'
            corrupt.write_bytes(b'not a video')
            with self.assertRaises((ValueError, subprocess.SubprocessError)):
                probe_artifact({'export': {'name': 'Remotion___get_render_progress', 'status': 'succeeded',
                                          'result': {'status': 'succeeded', 'output_path': str(corrupt)}}}, out)

    async def test_final_video_without_voiceover_audio_is_incomplete(self):
        from scripts.e2e_lighthouse import probe_artifact

        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
            self.skipTest('ffmpeg and ffprobe are required for artifact validation')
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            silent = out / 'silent.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=160x90:rate=30:duration=0.2', '-c:v', 'libx264',
                            '-y', str(silent)], check=True, capture_output=True)
            with self.assertRaisesRegex(ValueError, 'audio'):
                probe_artifact({'export': {'name': 'Remotion___get_render_progress', 'status': 'succeeded',
                                          'result': {'status': 'succeeded', 'output_path': str(silent)}}}, out)

    async def test_operator_driver_rejects_approval_over_cap_without_paid_request(self):
        from scripts.e2e_lighthouse import LighthouseOptions, run_lighthouse
        from agent.studio_agent_next import StudioAgentApprovalRequired, StudioAgentOutput, StudioApprovalRequest

        async def agent(request, **kwargs):
            if not request.approval_decisions:
                raise StudioAgentApprovalRequired('cap-checkpoint', [StudioApprovalRequest(
                    call_id='video', tool_name='Fal___generate_wan3_t2v', label='Video',
                    arguments={'prompt': 'lighthouse', 'duration': 5, 'resolution': '720p'})])
            self.assertEqual(request.approval_decisions[0].decision, 'reject')
            self.assertIn('cap', request.approval_decisions[0].message)
            return StudioAgentOutput(title='Blocked', summary='Spend cap', markdown='Blocked', filename='out.md')
        with tempfile.TemporaryDirectory() as directory, \
                patch('scripts.local_gateway.dispatch') as dispatch:
            summary = await run_lighthouse(LighthouseOptions(out=Path(directory), live=True, spend_cap_usd='0.01'),
                                           agent_run=agent)
            records = (Path(directory) / 'agent_events.jsonl').read_text()
        dispatch.assert_not_called()
        self.assertEqual(summary['media_cost_usd'], 0)
        self.assertIn('"decision": "reject"', records)

    async def test_live_startup_unknown_model_records_failed_summary(self):
        from scripts.e2e_lighthouse import LighthouseOptions, run_lighthouse

        with tempfile.TemporaryDirectory() as directory, \
                patch('scripts.e2e_lighthouse.deep_agent_model', return_value='anthropic:unknown'):
            result = await run_lighthouse(LighthouseOptions(out=Path(directory), live=True))
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['error_type'], 'ValueError')
            self.assertTrue((Path(directory) / 'summary.json').is_file())

    async def test_event_journal_removes_secrets_and_signed_url_queries(self):
        from scripts.e2e_lighthouse import EventJournal

        with tempfile.TemporaryDirectory() as directory:
            journal = EventJournal(Path(directory) / 'events.jsonl', 'test-run')
            journal.record('progress', message='https://media.example/final.mp4?X-Amz-Signature=PRIVATE#x',
                           HF_TOKEN='PRIVATE', authorization='Bearer PRIVATE')
            text = journal.path.read_text()
            row = json.loads(text)
        self.assertNotIn('PRIVATE', text)
        self.assertNotIn('X-Amz-Signature', text)
        self.assertIn('https://media.example/final.mp4', row['message'])
        self.assertEqual(row['entry_point'], 'e2e_lighthouse')

    async def test_driver_resumes_true_gateway_path_and_validates_final_artifact(self):
        from scripts.e2e_lighthouse import LighthouseOptions, run_lighthouse
        from agent.studio_agent_next import (
            StudioAgentApprovalRequired, StudioAgentOutput, StudioApprovalRequest, StudioToolEvent,
        )
        if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
            self.skipTest('ffmpeg and ffprobe are required for artifact validation')
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / 'source.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=160x90:rate=30:duration=0.2', '-f', 'lavfi', '-i',
                            'sine=frequency=440:duration=0.2', '-c:v', 'libx264', '-c:a', 'aac',
                            '-metadata', 'comment=https://media.example/final.mp4?X-Amz-Signature=PRIVATE',
                            '-y', str(fixture)], check=True, capture_output=True)
            calls = []
            async def fake_agent(request, **kwargs):
                client = kwargs['mcp_servers'][0]
                search = await client.call_tool('x_amz_bedrock_agentcore_search', {'query': 'wan3'})
                self.assertTrue(search.structured_content['tools'])
                calls.append(request)
                if not request.approval_decisions:
                    raise StudioAgentApprovalRequired('checkpoint', [StudioApprovalRequest(
                        call_id='video', tool_name='Fal___generate_wan3_t2v', label='Video',
                        arguments={'prompt': 'lighthouse', 'duration': 5, 'resolution': '720p'})])
                self.assertEqual(request.approval_decisions[0].decision, 'approve')
                await client.call_tool('Fal___generate_wan3_t2v', request.approval_decisions and
                                       {'prompt': 'lighthouse', 'duration': 5, 'resolution': '720p'})
                kwargs['event_sink'](StudioToolEvent(
                    id='render', name='Remotion___get_render_progress', label='Export', status='succeeded',
                    summary='Complete', result={'status': 'succeeded', 'output_path': str(fixture)}))
                return StudioAgentOutput(title='Lighthouse', summary='Finished', markdown='Export', filename='out.md')
            out = Path(directory) / 'out'
            with patch('scripts.local_gateway.dispatch', return_value={'status': 'queued'}):
                summary = await run_lighthouse(LighthouseOptions(out=out, live=True), agent_run=fake_agent)
            self.assertTrue((out / 'final.mp4').is_file())
            self.assertTrue((out / 'final.ffprobe.json').is_file())
            self.assertTrue((out / 'agent_events.jsonl').is_file())
            self.assertTrue((out / 'gateway_ledger.jsonl').is_file())
            self.assertNotIn('X-Amz-Signature', (out / 'final.ffprobe.txt').read_text())
            self.assertNotIn('PRIVATE', (out / 'final.ffprobe.txt').read_text())
        self.assertEqual(summary['status'], 'completed')
        self.assertEqual(summary['fps'], '30/1')
        self.assertGreater(summary['bitrate_bps'], 0)
        self.assertEqual(summary['media_cost_usd'], 0.65)
        self.assertEqual(calls[1].resume_state, 'checkpoint')

    async def test_missing_final_artifact_is_failed_and_agent_exception_is_not_retried(self):
        from scripts.e2e_lighthouse import LighthouseOptions, run_lighthouse
        from agent.studio_agent_next import StudioAgentOutput

        with tempfile.TemporaryDirectory() as directory:
            async def no_artifact(request, **kwargs):
                return StudioAgentOutput(title='Incomplete', summary='No video', markdown='No video', filename='out.md')
            result = await run_lighthouse(LighthouseOptions(out=Path(directory) / 'missing', live=True),
                                          agent_run=no_artifact)
            self.assertEqual(result['status'], 'failed')
            self.assertIn('artifact', result['error'])
            failed = AsyncMock(side_effect=TimeoutError('private https://example.com/?token=PRIVATE'))
            result = await run_lighthouse(LighthouseOptions(out=Path(directory) / 'error', live=True),
                                          agent_run=failed)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['error_type'], 'TimeoutError')
            failed.assert_awaited_once()
            self.assertNotIn('PRIVATE', (Path(directory) / 'error' / 'summary.json').read_text())
