from __future__ import annotations

import asyncio
import json
import tempfile
import unittest

import httpx
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage
from pydantic import ValidationError

from agent.deep_agent.runner import run_with_servers
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, StudioQuestionAnswer,
    agent_invocation, _context_from_request,
)
from test_deep_agent import Gateway, ScriptedModel, call, final
from test_deep_agent_execution import VIDEO, VIDEO_ARGS, dispatch
import test_deep_agent_contract as contract

QUESTION = {
    "question": "Should I replace the existing cut or create a separate version?",
    "reason": "irreversible_outcome",
    "options": [
        {"id": "replace", "label": "Replace the cut", "description": "Changes the current cut."},
        {"id": "separate", "label": "Separate version", "description": "Keeps both versions."},
    ],
    "allow_free_text": True,
}


def ask():
    return call("ask_user", QUESTION, "clarify")


class DeepAgentQuestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_question_copy_cannot_expose_internal_names(self):
        from agent.deep_agent.questions import AskUserInput
        with self.assertRaises(ValidationError):
            AskUserInput.model_validate({**QUESTION, 'question': 'Use Seedance or Kling?'})
        from server.run_billing import public_approvals
        cards = public_approvals(None, run_id='job', user_id=None,
            execution_status='awaiting_approval', error_type=None,
            raw_approvals=[{**QUESTION, 'kind': 'question', 'call_id': 'q',
                            'question': 'Use Kling?'}])
        self.assertEqual(cards[0]['question'], 'Which outcome do you prefer?')

    async def test_native_question_restores_serialized_checkpoint_in_fresh_worker(self):
        request = StudioAgentRequest(prompt="Revise the cut.", workspace_id="workspace", project_id="project",
                                     conversation_id="conversation", job_id="question", autonomous=True)
        gateway = Gateway()
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"RENDERHAUS_OUTCOME_DIR": directory}):
            with self.assertRaises(StudioAgentApprovalRequired) as paused:
                await run_with_servers(request, _context_from_request(request), [gateway], model=ScriptedModel([ask()]))
            question = paused.exception.approvals[0]
            self.assertEqual(question.kind, "question")
            self.assertEqual(question.reason, "irreversible_outcome")
            self.assertEqual(question.options[1].id, "separate")
            gateway.call_tool.assert_not_awaited()
            for answer in ({"kind": "choice", "option_id": "separate"}, {"kind": "text", "text": "Keep the current cut."}):
                def completed(messages, tools):
                    self.assertIsInstance(messages[-1], ToolMessage)
                    result = json.loads(messages[-1].text)
                    self.assertEqual(result["answer"], answer)
                    self.assertEqual(result["status"], "answered")
                    return final()
                resumed = request.model_copy(update={
                    "session_items": json.loads(json.dumps(paused.exception.session_items)),
                    "resume_state": paused.exception.state,
                    "approval_decisions": [StudioQuestionAnswer(call_id=question.call_id, answer=answer)],
                })
                result = await run_with_servers(resumed, _context_from_request(resumed), [gateway],
                                                model=ScriptedModel([completed]))
                self.assertEqual(result.title, "Product still")
            gateway.call_tool.assert_not_awaited()

    async def test_parallel_question_and_paid_approval_resume_independently(self):
        request = StudioAgentRequest(prompt="Revise the cut and make a clip.", workspace_id="workspace",
                                     project_id="project", conversation_id="parallel", job_id="parallel")
        gateway = Gateway([VIDEO])
        tasks = AIMessage(content="", tool_calls=[
            call("task", {"subagent_type": "planner", "description": "Clarify which cut to replace."}, "planner").tool_calls[0],
            call("task", {"subagent_type": "media", "description": "Generate the requested clip."}, "media").tool_calls[0],
        ])

        def propose(messages, tools):
            return dispatch(VIDEO, VIDEO_ARGS, "video") if "call_media_tool" in tools else ask()

        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"RENDERHAUS_OUTCOME_DIR": directory}):
            with self.assertRaises(StudioAgentApprovalRequired) as paused:
                await run_with_servers(request, _context_from_request(request), [gateway],
                                       model=ScriptedModel([tasks, propose, propose]))
            requests = paused.exception.approvals
            self.assertCountEqual([item.kind for item in requests], ["question", "approval"])
            decisions = [StudioQuestionAnswer(call_id=item.call_id, answer={"kind": "choice", "option_id": "separate"})
                         if item.kind == "question" else StudioApprovalDecision(call_id=item.call_id, decision="reject")
                         for item in requests]
            resumed = request.model_copy(update={
                "session_items": json.loads(json.dumps(paused.exception.session_items)),
                "resume_state": paused.exception.state, "approval_decisions": decisions,
                "prior_tool_events": [event.public() for event in paused.exception.tool_events],
            })
            model = ScriptedModel([AIMessage(content="Choice recorded."), AIMessage(content="Clip skipped."), final()])
            result = await run_with_servers(resumed, _context_from_request(resumed), [gateway], model=model)
            self.assertEqual(result.title, "Product still")
            self.assertFalse(model._steps)
            gateway.call_tool.assert_not_awaited()

    async def test_answer_does_not_approve_a_subsequent_paid_call(self):
        request = StudioAgentRequest(prompt="Revise the cut.", workspace_id="workspace", project_id="project",
                                     conversation_id="then-paid", job_id="then-paid")
        gateway = Gateway([VIDEO])
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"RENDERHAUS_OUTCOME_DIR": directory}):
            with self.assertRaises(StudioAgentApprovalRequired) as paused:
                await run_with_servers(request, _context_from_request(request), [gateway], model=ScriptedModel([ask()]))
            resumed = request.model_copy(update={
                "session_items": json.loads(json.dumps(paused.exception.session_items)),
                "resume_state": paused.exception.state,
                "approval_decisions": [StudioQuestionAnswer(call_id=paused.exception.approvals[0].call_id,
                                                            answer={"kind": "choice", "option_id": "separate"})],
            })
            with self.assertRaises(StudioAgentApprovalRequired) as paid:
                await run_with_servers(resumed, _context_from_request(resumed), [gateway],
                                       model=ScriptedModel([dispatch(VIDEO, VIDEO_ARGS, "video")]))
            self.assertEqual(paid.exception.approvals[0].kind, "approval")
            self.assertEqual(paid.exception.approvals[0].tool_name, VIDEO.name)
            gateway.call_tool.assert_not_awaited()

    async def test_question_requires_cost_or_irreversible_reason(self):
        from agent.deep_agent.questions import AskUserInput
        for reason in ("preference", "missing_context", "approval"):
            with self.assertRaises(ValidationError):
                AskUserInput.model_validate({**QUESTION, "reason": reason})
        with self.assertRaises(ValidationError):
            AskUserInput.model_validate({**QUESTION, "options": [], "allow_free_text": False})
        choice_only = AskUserInput.model_validate({**QUESTION, "allow_free_text": False})
        with self.assertRaises(ValueError):
            choice_only.validate_answer({"kind": "text", "text": "Keep both."})
        with self.assertRaises(ValidationError):
            choice_only.validate_answer({"kind": "text", "text": "   "})


class QuestionServerTests(unittest.IsolatedAsyncioTestCase):
    setUp = contract.DeepAgentContractTests.setUp
    run_job = contract.DeepAgentContractTests.run_job

    async def test_question_answer_route_is_durable_and_does_not_hold_credit(self):
        import server.studio as studio
        self.steps = [ask()]
        await self.run_job()
        execution = self.repo.get_execution("user:local", self.job)
        self.assertEqual(execution["message"], "Waiting for your answer.")
        item = execution["approvals"][0]
        self.assertEqual(item["kind"], "question")
        self.assertEqual(item["question"], QUESTION["question"])
        for field in ("provider", "tool_name", "estimate_cents", "cap_cents", "lines"):
            self.assertNotIn(field, item)
        raw = self.repo.execution_checkpoint("user:local", self.job)["approvals"]
        paid = {"call_id": "paid", "tool_name": "Seedream___text_to_image", "label": "Create image",
                "arguments": {"prompt": "Product"}, "decision": None}
        mixed = studio.run_billing.public_approvals(self.repo, run_id=self.job, user_id="local",
            execution_status="awaiting_approval", error_type=None, raw_approvals=[*raw, paid])
        self.assertEqual(next(card for card in mixed if card["call_id"] == "paid")["step_count"], 1)
        self.assertNotIn("cap_cents", next(card for card in mixed if card.get("kind") == "question"))
        with self.assertRaises(ValueError):
            self.repo.decide_execution_approval("user:local", self.job, item["call_id"], decision="approve")
        with self.assertRaises(ValueError):
            self.repo.decide_execution_approval("user:local", self.job, item["call_id"], decision="answer",
                                               answer={"kind": "choice", "option_id": "missing"})
        from fastapi import HTTPException
        with patch.object(studio.run_billing, "approval_gate") as gate:
            with self.assertRaises(HTTPException) as wrong_route:
                await studio.decide_studio_agent_tool(self.job, item["call_id"], studio.AgentApprovalBody(
                    decision="approve", cap_cents=100_000), None)
            self.assertEqual(wrong_route.exception.status_code, 409)
            gate.assert_not_called()
        with self.assertRaises(ValidationError):
            studio.AgentQuestionBody.model_validate({"answer": {"kind": "text", "text": "Yes"}, "cap_cents": 100_000})
        reloaded = type(self.repo)(self.repo.database_path, self.repo.media_root)
        self.assertEqual(reloaded.execution_checkpoint("user:local", self.job)["approvals"][0]["kind"], "question")
        self.steps = [final()]
        with patch.object(studio.run_billing, "approval_gate") as gate:
            await studio.answer_studio_agent_question(self.job, item["call_id"], studio.AgentQuestionBody(
                answer={"kind": "text", "text": "Create another version."}), None)
            gate.assert_not_called()
        await asyncio.gather(*list(studio._AGENT_TASKS))
        self.assertEqual(self.repo.get_execution("user:local", self.job)["status"], "completed")
        self.gateway.call_tool.assert_not_awaited()

    async def test_agentcore_question_payload_preserves_question_fields(self):
        self.steps = [ask()]
        chunks = [chunk async for chunk in agent_invocation({
            "prompt": "Revise the cut.", "job_id": self.job, "workspace_id": "user:local", "project_id": "project",
            "conversation_id": self.conversation,
        }, SimpleNamespace(session_id="runtime-question"))]
        payload = chunks[-1]["payload"]
        self.assertEqual(payload["status"], "awaiting_approval")
        self.assertEqual(payload["approvals"][0]["kind"], "question")
        self.assertEqual(payload["approvals"][0]["options"], QUESTION["options"])
        self.assertTrue(payload["session_items"][0]["checkpoint"])
        json.dumps(payload)
        self.gateway.call_tool.assert_not_awaited()

        class ResultStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                for chunk in chunks:
                    yield ("data: " + json.dumps(chunk) + "\n\n").encode()

        def route(request):
            if request.url.path == "/ping":
                return httpx.Response(200, json={"status": "healthy"})
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=ResultStream())

        import server.studio as studio
        client = httpx.AsyncClient
        with patch.dict("os.environ", {"AGENTCORE_DEV_URL": "http://runtime.test"}), patch(
            "server.studio.httpx.AsyncClient", side_effect=lambda **kw: client(transport=httpx.MockTransport(route), **kw),
        ):
            await self.run_job()
        remote = self.repo.get_execution("user:local", self.job)
        self.assertEqual(remote["status"], "awaiting_approval")
        self.assertEqual(remote["approvals"][0]["kind"], "question")
        self.assertEqual(remote["approvals"][0]["options"], QUESTION["options"])
