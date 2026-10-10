from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.deep_agent import routing
from agent.deep_agent.runner import run_with_servers
from agent.gateway_executor import APPROVAL_EXEMPT_TOOLS, GatewayExecutor, tool_needs_approval
from agent.studio_agent_next import (
    StudioAgentOutput, StudioAgentRequest, StudioToolEvent, _context_from_request,
    _validate_video_delivery,
)
from providers.registry import generate_schemas
from server.billing_rates import cost_for
from test_deep_agent import ScriptedModel, call, final


DELIVERY = "Remotion___deliver_render"
QC = "Remotion___qc_deliverable"
ARGS = {"job_id": "owned-job", "input_path": "source.mp4", "preset": "social-feed"}


def schemas(spec):
    existing = generate_schemas(spec)
    if spec.id != "remotion":
        return existing
    return existing + [{
        "name": name, "description": "Finish or inspect existing local media.",
        "inputSchema": {"type": "object", "properties": {
            "job_id": {"type": "string"}, "input_path": {"type": "string"},
            "manifest_path": {"type": "string"}, "preset": {"type": "string"},
            "spec": {"type": "object"},
        }, "required": ["job_id"], "additionalProperties": False},
    } for name in ("deliver_render", "qc_deliverable")]


def provider_double():
    module = ModuleType("providers.remotion.delivery")

    def validate_report(result):
        if result.get("status") != "succeeded" or result.get("passed") is not True:
            return False
        try:
            report = json.loads(Path(result["report_path"]).read_text())
            if report != result or not report["files"]:
                return False
            for row in report["files"]:
                path = Path(row["output_path"])
                if (row["file"] != str(path) or row["passed"] is not True
                        or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]):
                    return False
            return True
        except (OSError, ValueError, KeyError, TypeError):
            return False

    module.validate_delivery_report = validate_report
    return module


def tool_event(name, result, event_id="current", arguments=None):
    return StudioToolEvent(id=event_id, name=name, label="Delivery QC", summary="Worker report",
                          status=result.get("status", "failed"), result=result,
                          arguments=arguments or ARGS)


def bound_report(root, name="report"):
    artifact = root / f"{name}.mp4"
    artifact.write_bytes(b"fixture bytes for the worker's report binding")
    result = {"status": "succeeded", "passed": True, "files": [{
        "file": str(artifact), "output_path": str(artifact),
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(), "passed": True,
        "checks": [{"name": "duration", "pass": True, "severity": "error", "detail": "Within one frame."}],
        "failures": [], "width": 1280, "height": 720,
    }], "report_path": str(root / f"{name}.json")}
    Path(result["report_path"]).write_text(json.dumps(result))
    return result


class DeliveryHostTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.patches = [
            patch("providers.registry.generate_schemas", side_effect=schemas),
            patch.dict(routing.POLICY, {"free_tools": [*routing.POLICY["free_tools"],
                                                      "deliver_render", "qc_deliverable"]}),
            patch.dict(sys.modules, {"providers.remotion.delivery": provider_double()}),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    @staticmethod
    def request(autonomous=False):
        return StudioAgentRequest(prompt="Inspect the local media", job_id="owned-job",
                                  autonomous=autonomous)

    def test_finishing_and_qc_never_request_approval_or_change_exemptions(self):
        for name in (DELIVERY, QC, "delivery_render", "deliverable_qc"):
            for autonomous in (False, True):
                with self.subTest(name=name, autonomous=autonomous):
                    self.assertFalse(tool_needs_approval(name, autonomous, ARGS))
        self.assertEqual(APPROVAL_EXEMPT_TOOLS, {"Remotion___export_nle_timeline"})

    def test_local_finishing_quotes_zero_even_when_backend_is_lambda(self):
        for backend in ("local", "lambda"):
            for name in ("deliver_render", "qc_deliverable"):
                with self.subTest(backend=backend, name=name), patch.dict(
                    os.environ, {"REMOTION_RENDER_BACKEND": backend},
                ):
                    self.assertEqual(cost_for("remotion", name, ARGS).total_cents, 0)

    async def test_worker_tools_are_discovered_without_a_remote_gateway(self):
        available = await GatewayExecutor(_context_from_request(self.request()), []).available()
        for name in (DELIVERY, QC):
            with self.subTest(name=name):
                self.assertIn(name, available)
                self.assertIsNone(available[name][0])

    async def test_owned_worker_dispatch_persists_dry_run_result_without_approval(self):
        for name in (DELIVERY, QC):
            with self.subTest(name=name):
                context = _context_from_request(self.request())
                executor = GatewayExecutor(context, [])

                def dispatch(provider, verb, arguments):
                    self.assertEqual((provider, verb), ("remotion", name.split("___")[1]))
                    self.assertEqual(arguments, ARGS)
                    return {"status": "dry_run", "passed": False, "files": [],
                            "reason": "No file was inspected."}

                with patch("providers.registry.dispatch", side_effect=dispatch):
                    result = await executor.execute({"tool_name": name, "arguments": ARGS,
                                                     "call_id": "dry-run"})
                self.assertEqual(result["status"], "dry_run")
                self.assertEqual(context.tool_events[-1].result["reason"], "No file was inspected.")
                self.assertEqual(executor.cost_ledger, {})

    async def test_worker_scope_refuses_another_job_before_dispatch(self):
        for name in (DELIVERY, QC):
            with self.subTest(name=name):
                executor = GatewayExecutor(_context_from_request(self.request()), [])
                result = await executor.execute({"tool_name": name,
                    "arguments": {**ARGS, "job_id": "another-job"}, "call_id": "foreign"})
                self.assertEqual(result["status"], "not_run")
                self.assertIn("trusted current Studio job_id", result["reason"])

    async def test_invalid_worker_contract_is_refused_before_dispatch(self):
        executor = GatewayExecutor(_context_from_request(self.request()), [])
        with patch("providers.contracts.validate_tool_arguments", side_effect=ValueError(
            "Choose exactly one input_path or manifest_path.",
        )):
            result = await executor.execute({"tool_name": DELIVERY,
                "arguments": {**ARGS, "manifest_path": "matrix.json"}, "call_id": "invalid"})
        self.assertEqual(result["status"], "not_run")
        self.assertEqual(result["reason"], "Choose exactly one input_path or manifest_path.")

    async def test_stopped_spending_cap_still_allows_free_worker_inspection(self):
        with patch.dict(os.environ, {"RENDERHAUS_AUTONOMOUS_RUN_CAP_CENTS": "0"}):
            executor = GatewayExecutor(_context_from_request(self.request(True)), [])
        executor.cap_stopped = True
        with patch("providers.registry.dispatch", return_value={"status": "dry_run", "passed": False}):
            result = await executor.execute({"tool_name": QC, "arguments": ARGS, "call_id": "inspect"})
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(executor.reservations, {})
        self.assertTrue(executor.cap_stopped)

    async def test_deep_agents_dispatch_finishing_without_a_human_interrupt(self):
        request = self.request().model_copy(update={"conversation_id": "delivery-host"})
        context = _context_from_request(request)
        with patch("providers.registry.dispatch", return_value={"status": "dry_run", "passed": False}):
            await run_with_servers(request, context, [], model=ScriptedModel([
                call("call_editor_tool", {"tool_name": QC, "arguments": ARGS}, "inspect"), final(),
            ]))
        self.assertTrue(any(event.name == QC and event.status == "dry_run" for event in context.tool_events))
        self.assertFalse(any(event.status == "awaiting_approval" for event in context.tool_events))

    async def test_direct_studio_invoke_refuses_worker_tools(self):
        from fastapi import HTTPException
        from server.studio import InvokeBody, invoke_tool

        for tool in ("deliver_render", "qc_deliverable"):
            with self.subTest(tool=tool), patch("server.studio.repository.require_project"):
                with self.assertRaises(HTTPException) as caught:
                    await invoke_tool(InvokeBody(project_id="project", provider="remotion", tool=tool,
                                                arguments=ARGS), None)
            self.assertEqual(caught.exception.status_code, 409)

    async def test_failed_qc_is_persisted_as_an_incomplete_execution(self):
        from server.studio import _run_studio_agent_job

        request = self.request()
        context = _context_from_request(request)
        context.record_event(tool_event(QC, {"status": "failed", "passed": False,
                                            "reason": "Audio is missing."}))
        output = StudioAgentOutput(title="Finished export", summary="The export is delivered.",
                                   markdown="# Finished export", filename="export.md")
        self.assertFalse(_validate_video_delivery(request, context, output))
        outcome = SimpleNamespace(final=output, tool_events=context.tool_events,
                                  progress_events=context.progress_events, session_items=[])
        repository = MagicMock()
        repository.get_conversation_recovery_items.return_value = []
        repository.list_executions.return_value = []
        with patch("server.studio.repository", repository), patch(
            "server.studio.run_studio_agent", new=AsyncMock(return_value=outcome),
        ), patch("server.studio._hydrate_tool_event_assets"):
            await _run_studio_agent_job("owned-job", request.prompt, [], "conversation",
                                       workspace_id="workspace", project_id="project", user_id="user")
        stored = repository.update_execution.call_args.kwargs
        self.assertEqual(stored["status"], "error")
        self.assertEqual(stored["error_type"], "VideoExportIncomplete")
        self.assertTrue(stored["result"]["partial"])
        self.assertFalse(any(item.kwargs["event"]["type"] == "RUN_FINISHED"
                             for item in repository.append_agent_event.call_args_list))

    async def test_run_limit_cannot_recover_an_old_render_over_current_qc_failure(self):
        from agent.errors import AgentRunLimitExceeded
        from server.studio import _run_studio_agent_job

        failed = tool_event(QC, {"status": "failed", "passed": False,
                                "reason": "Audio is missing."})
        old_render = tool_event("Remotion___get_render_progress", {"status": "succeeded"},
                                event_id="old-render")
        old_render.assets = [{"kind": "video", "version_id": "old-video", "filename": "old.mp4"}]
        repository = MagicMock()
        repository.get_conversation_recovery_items.return_value = []
        repository.list_executions.return_value = []
        repository.get_execution.return_value = {"tool_calls": [old_render.public(), failed.public()]}
        with patch("server.studio.repository", repository), patch(
            "server.studio.run_studio_agent", new=AsyncMock(side_effect=AgentRunLimitExceeded()),
        ), self.assertLogs("server.studio", level="ERROR"):
            await _run_studio_agent_job("owned-job", self.request().prompt, [], "conversation",
                                       workspace_id="workspace", project_id="project", user_id="user")
        self.assertEqual(repository.update_execution.call_args.kwargs["status"], "error")
        self.assertIn("Audio is missing.", repository.update_execution.call_args.kwargs["result"]["markdown"])

    async def test_run_limit_recovery_verifies_current_worker_reports(self):
        from agent.errors import AgentRunLimitExceeded
        from server.studio import _run_studio_agent_job

        for defect in (None, "changed-file", "missing-report"):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as directory:
                result = bound_report(Path(directory))
                if defect == "changed-file":
                    Path(result["files"][0]["output_path"]).write_bytes(b"changed")
                elif defect == "missing-report":
                    Path(result["report_path"]).unlink()
                repository = MagicMock()
                repository.get_conversation_recovery_items.return_value = []
                repository.list_executions.return_value = []
                repository.get_execution.return_value = {"tool_calls": [tool_event(DELIVERY, result).public()]}
                with patch("server.studio.repository", repository), patch(
                    "server.studio.run_studio_agent", new=AsyncMock(side_effect=AgentRunLimitExceeded()),
                ), self.assertLogs("server.studio", level="ERROR"):
                    await _run_studio_agent_job("owned-job", self.request().prompt, [], "conversation",
                                               workspace_id="workspace", project_id="project", user_id="user")
                self.assertEqual(repository.update_execution.call_args.kwargs["status"],
                                 "completed" if defect is None else "error")

    async def test_run_limit_selected_delivery_cannot_recover_a_legacy_render(self):
        from agent.errors import AgentRunLimitExceeded
        from server.studio import _run_studio_agent_job

        old_render = tool_event("Remotion___get_render_progress", {"status": "succeeded"})
        old_render.assets = [{"kind": "video", "version_id": "old-video", "filename": "old.mp4"}]
        repository = MagicMock()
        repository.get_conversation_recovery_items.return_value = []
        repository.list_executions.return_value = []
        repository.get_execution.return_value = {"tool_calls": [old_render.public()]}
        with patch("server.studio.repository", repository), patch(
            "server.studio.run_studio_agent", new=AsyncMock(side_effect=AgentRunLimitExceeded()),
        ), patch("agent.deep_agent.routing.route_intent", return_value=routing.Route(alias="delivery_render")), \
                self.assertLogs("server.studio", level="ERROR"):
            await _run_studio_agent_job("owned-job", self.request().prompt, [], "conversation",
                                       workspace_id="workspace", project_id="project", user_id="user")
        self.assertEqual(repository.update_execution.call_args.kwargs["status"], "error")


class DeliveryCompletionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        module_patch = patch.dict(sys.modules, {"providers.remotion.delivery": provider_double()})
        module_patch.start()
        self.addCleanup(module_patch.stop)
        self.request = StudioAgentRequest(prompt="Inspect the local media", job_id="owned-job")

    def report(self, name="report"):
        return bound_report(self.root, name)

    def context(self, *events):
        context = _context_from_request(self.request)
        for event in events:
            context.record_event(event)
        return context

    def test_current_bound_worker_report_certifies_delivery_or_qc(self):
        for name in (DELIVERY, QC):
            with self.subTest(name=name):
                result = self.report()
                self.assertTrue(_validate_video_delivery(self.request, self.context(tool_event(name, result))))

    def test_missing_changed_or_mismatched_reports_cannot_certify_completion(self):
        for defect in ("missing", "changed-file", "changed-report", "mismatched-path"):
            with self.subTest(defect=defect):
                result = self.report()
                if defect == "missing":
                    Path(result["report_path"]).unlink()
                elif defect == "changed-file":
                    Path(result["files"][0]["output_path"]).write_bytes(b"changed")
                elif defect == "changed-report":
                    Path(result["report_path"]).write_text("{}")
                else:
                    result["files"][0]["file"] = str(self.root / "another.mp4")
                self.assertFalse(_validate_video_delivery(self.request, self.context(tool_event(DELIVERY, result))))

    def test_prior_worker_report_does_not_certify_a_selected_new_delivery(self):
        old = tool_event(DELIVERY, self.report(), event_id="old")
        self.request.prior_tool_events = [old.public()]
        context = self.context(old, tool_event("Remotion___get_render_progress",
            {"status": "succeeded", "url": "https://example.com/old-render.mp4"}, event_id="poll"))
        with patch("agent.deep_agent.routing.route_intent", return_value=routing.Route(alias="delivery_render")):
            self.assertFalse(_validate_video_delivery(self.request, context))

    def test_failed_delivery_takes_precedence_over_a_complete_matrix(self):
        matrix = tool_event("Remotion___render_ad_variants", {"status": "succeeded", "planned": 1,
            "rendered": [{"file": "matrix.mp4"}], "failed": [], "blocked": []},
            event_id="matrix", arguments={"stage": "render_batch"})
        failed = tool_event(DELIVERY, {"status": "failed", "passed": False, "files": [],
                                      "reason": "Audio is missing."})
        with patch("agent.studio_agent_next._completed_video_artifact", return_value=True):
            self.assertFalse(_validate_video_delivery(self.request, self.context(matrix, failed)))

    def test_latest_worker_failure_invalidates_an_earlier_pass(self):
        passed = tool_event(DELIVERY, self.report(), event_id="passed")
        failed = tool_event(QC, {"status": "failed", "passed": False, "files": [],
                                "reason": "Unexpected frozen frames."}, event_id="failed")
        self.assertFalse(_validate_video_delivery(self.request, self.context(passed, failed)))

    def test_later_qc_must_bind_to_the_current_delivered_files(self):
        delivered = tool_event(DELIVERY, self.report("delivery"), event_id="delivered")
        inspected = tool_event(QC, self.report("other"), event_id="inspected")
        self.assertFalse(_validate_video_delivery(self.request, self.context(delivered, inspected)))

    def test_malformed_failed_report_still_discloses_the_worker_reason(self):
        failed = tool_event(DELIVERY, {"status": "failed", "passed": False, "files": None,
            "rendered": None, "checks": None, "failures": None, "reason": "Invalid source media."})
        output = StudioAgentOutput(title="Finished export", summary="The export is delivered.",
                                   markdown="# Finished export", filename="export.md")
        self.assertFalse(_validate_video_delivery(self.request, self.context(failed), output))
        self.assertIn("Invalid source media.", output.markdown)

    def test_failed_checks_replace_finished_claims_with_verbatim_reasons(self):
        failures = ["Integrated loudness -18.1 LUFS differs from target -14 LUFS.",
                    "Unexpected black interval 2.0-3.0 seconds."]
        failed = tool_event(DELIVERY, {"status": "failed", "passed": False, "files": [{
            "file": "final.mp4", "passed": False, "checks": [], "failures": failures,
        }]})
        final_output = StudioAgentOutput(title="Finished export", summary="The video is delivered.",
                                         markdown="# Finished export\n\nThe video is delivered.", filename="export.md")
        self.assertFalse(_validate_video_delivery(self.request, self.context(failed), final_output))
        for reason in failures:
            self.assertIn(reason, final_output.markdown)
        self.assertNotIn("finished", final_output.title.lower())
        self.assertNotIn("delivered", final_output.summary.lower())
        self.assertNotIn("delivered", final_output.markdown.lower())

    def test_delivery_route_cannot_finish_from_a_standalone_qc_report(self):
        with patch("agent.deep_agent.routing.route_intent", return_value=routing.Route(alias="delivery_render")):
            self.assertFalse(_validate_video_delivery(self.request, self.context(tool_event(QC, self.report()))))

    def test_ordinary_assembly_preserves_legacy_successful_poll(self):
        self.request.prompt = "Assemble and export the final MP4"
        context = self.context(tool_event("Remotion___get_render_progress",
            {"status": "succeeded", "url": "https://example.com/render.mp4"}))
        self.assertTrue(_validate_video_delivery(self.request, context))


if __name__ == "__main__":
    unittest.main()
