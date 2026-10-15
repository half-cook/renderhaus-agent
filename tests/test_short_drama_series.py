from __future__ import annotations

import copy
import asyncio
import json
import unittest

import pytest
from mcp import Tool

from agent.deep_agent.routing import route_intent
from agent.studio_agent_next import (
    StudioAgentApprovalRequired, StudioAgentRequest, StudioApprovalDecision, _context_from_request,
)
from test_deep_agent import Gateway, ScriptedModel, call, final


def test_episodic_fiction_starts_with_a_free_outline():
    route = route_intent("Turn my novel into a 10-episode vertical drama with a character bible")
    assert route.skill == "short-drama-series"
    assert route.status == "ready"
    assert route.tool is None
    assert route.required["outline_approval"] is True


@pytest.mark.parametrize("prompt", ["Do not stop the series; generate the next reference image",
                                     "Don't cancel this series", "Never exit the series"])
def test_negated_cancellation_keeps_the_series_gate(prompt):
    from agent.deep_agent.routing import drama_cancelled

    assert not drama_cancelled(prompt)


def episode():
    return {
        "episode_id": "ep01",
        "outline_hash": "outline-v1",
        "characters": [{"id": "mei", "profile": "Fictional clockmaker", "design_prompt": "Mei in red", "voice_prompt": "Quiet alto"}],
        "art": [{"id": "shop", "description": "Clock shop", "design_prompt": "Amber clock shop"}],
        "locks": [{"id": "coat", "subject_id": "mei", "phrase": "red wool coat"}, {"id": "room", "subject_id": "shop", "phrase": "amber clock shop"}],
        "script": [{"id": "l1", "kind": "dialogue", "speaker_id": "mei", "text": "Come back."}],
        "segments": [{"id": "s1", "cuts": [{"id": "c1", "duration_seconds": 4, "subjects": ["mei", "shop"], "lock_ids": ["coat", "room"], "keyframe_prompt": "Mei, red wool coat, amber clock shop", "video_prompt": "Mei, red wool coat, amber clock shop. She says Come back.", "line_ids": ["l1"]}]}],
    }


def outline():
    return {"series_id": "clock-shop", "title": "The borrowed hour", "revision": "1",
            "adaptation_notes": "Original fictional story", "cast": ["mei"],
            "beats": ["Time runs backward"],
            "episodes": [{"id": "ep01", "synopsis": "A clockmaker waits.", "hook": "Her customer returns."}],
            "assets": ["mei", "shop"]}


def image_job(document):
    return {"id": "ref1", "tool_name": "OpenAI___generate_image", "cut_id": "c1",
            "arguments": {"prompt": document["segments"][0]["cuts"][0]["keyframe_prompt"]}}


def prepared_gate():
    from agent.deep_agent.drama_gate import DramaGate

    gate = DramaGate(active=True)
    approved = gate.approve_outline(outline())
    document = episode()
    document["outline_hash"] = approved["outline_hash"]
    assert gate.prepare(document, [image_job(document)])["ok"]
    return gate, document


def test_timing_and_locks_are_checked_without_provider_calls():
    from agent.deep_agent.short_drama import check_episode

    checked = check_episode(episode())
    assert checked["ok"]
    assert checked["duration_seconds"] == 4
    assert checked["dialogue_estimates"]["l1"] > 0
    assert checked["measured"] is False
    broken = copy.deepcopy(episode())
    broken["segments"][0]["cuts"][0]["lock_ids"] = ["room"]
    checked = check_episode(broken)
    assert not checked["ok"]
    assert any("coat" in issue for issue in checked["errors"])


@pytest.mark.parametrize("seconds", [1.99, 5.01, True, float("nan"), float("inf")])
def test_invalid_cut_durations_fail(seconds):
    from agent.deep_agent.short_drama import check_episode

    broken = episode()
    broken["segments"][0]["cuts"][0]["duration_seconds"] = seconds
    assert not check_episode(broken)["ok"]


def test_a_segment_cannot_exceed_one_fifteen_second_generation():
    from agent.deep_agent.short_drama import check_episode

    broken = episode()
    cut = broken["segments"][0]["cuts"][0]
    broken["segments"][0]["cuts"] = [{**cut, "id": f"c{i}", "line_ids": ["l1"] if i == 0 else []} for i in range(4)]
    result = check_episode(broken)
    assert not result["ok"]
    assert any("15" in issue for issue in result["errors"])


def test_exact_job_binding_and_failed_replacements_invalidate_production():
    gate, document = prepared_gate()
    job = image_job(document)
    assert gate.blocker(job["tool_name"], job["arguments"]) is None
    assert gate.blocker(job["tool_name"], {**job["arguments"], "n": 2})
    assert gate.blocker("Fal___get_video_task", {"job_id": "saved"}) is None
    broken = copy.deepcopy(document)
    broken["segments"][0]["cuts"][0]["duration_seconds"] = 9
    assert not gate.prepare(broken, [job])["ok"]
    assert gate.blocker(job["tool_name"], job["arguments"])


def test_stale_outline_and_changed_continuity_locks_refuse():
    gate, document = prepared_gate()
    stale = {**document, "outline_hash": "invented"}
    assert not gate.prepare(stale, [image_job(stale)])["ok"]
    changed = copy.deepcopy(document)
    changed["locks"][0]["phrase"] = "blue wool coat"
    for field in ("keyframe_prompt", "video_prompt"):
        changed["segments"][0]["cuts"][0][field] = changed["segments"][0]["cuts"][0][field].replace("red wool coat", "blue wool coat")
    result = gate.prepare(changed, [image_job(changed)])
    assert not result["ok"]
    assert any("Continuity lock coat changed" in error for error in result["errors"])
    new_outline = {**outline(), "revision": "2"}
    approved = gate.approve_outline(new_outline)
    assert gate.blocker(image_job(document)["tool_name"], image_job(document)["arguments"])
    changed["outline_hash"] = approved["outline_hash"]
    assert gate.prepare(changed, [image_job(changed)])["ok"]


def test_renaming_a_lock_cannot_change_an_established_characters_look():
    gate, document = prepared_gate()
    document["locks"][0]["id"] = "coat-v2"
    document["locks"][0]["phrase"] = "blue wool coat"
    cut = document["segments"][0]["cuts"][0]
    cut["lock_ids"][0] = "coat-v2"
    for field in ("keyframe_prompt", "video_prompt"):
        cut[field] = cut[field].replace("red wool coat", "blue wool coat")
    assert not gate.prepare(document, [image_job(document)])["ok"]


def test_video_batch_duration_and_prompt_must_match_the_storyboard():
    gate, document = prepared_gate()
    prompt = document["segments"][0]["cuts"][0]["video_prompt"]
    job = {"id": "shot1", "tool_name": "Fal___generate_wan3_t2v", "segment_id": "s1",
           "arguments": {"prompt": prompt, "duration": 4}}
    assert gate.prepare(document, [job])["ok"]
    for changed in ({"duration": 5}, {"duration": 16}, {"prompt": "Different character"}):
        bad = {**job, "arguments": {**job["arguments"], **changed}}
        assert not gate.prepare(document, [bad])["ok"]


def test_decimal_cuts_sum_to_the_exact_integer_video_duration():
    gate, document = prepared_gate()
    cut = document["segments"][0]["cuts"][0]
    document["segments"][0]["cuts"] = [{**cut, "id": f"c{i}", "duration_seconds": seconds,
        "line_ids": ["l1"] if i == 0 else []} for i, seconds in enumerate((2.1, 2.2, 2.7))]
    prompts = "\n".join(row["video_prompt"] for row in document["segments"][0]["cuts"])
    result = gate.prepare(document, [{"id": "decimal", "tool_name": "Fal___generate_wan3_t2v",
        "segment_id": "s1", "arguments": {"prompt": prompts, "duration": 7}}])
    assert result["ok"], result["errors"]


def test_unbound_specialist_video_tools_cannot_bypass_segment_limits():
    from test_performance_transfer import ACT_ARGS

    gate, document = prepared_gate()
    result = gate.prepare(document, [{"id": "long", "tool_name": "Runway___act_two",
        "arguments": {**ACT_ARGS, "performance_duration_seconds": 30}}])
    assert not result["ok"]
    assert any("no supported job contract" in issue for issue in result["errors"])


def test_per_shot_selection_preserves_explicit_requests_and_ignores_episode_length():
    from agent.deep_agent.routing import intent_constraints

    gate, _ = prepared_gate()
    prompt = "Make a 2 minute video for this microdrama with synthetic dialogue."
    shot = {"prompt": "A silent view of the clock shop, no dialogue", "duration": 4}
    constraints = gate.selection_constraints(prompt, "Fal___generate_wan3_t2v", shot, intent_constraints(prompt))
    assert not constraints["predicates"]["dialogue"]
    assert not constraints["predicates"]["duration_over_30s"]
    prompt = "Use Kling for this microdrama."
    constraints = gate.selection_constraints(prompt, "Kling___text_to_video", shot, intent_constraints(prompt))
    assert constraints["provider"] == "kling"
    prompt = "Use my selfie for this microdrama with dialogue"
    constraints = gate.selection_constraints(prompt, "Seedance___text_to_video", shot, intent_constraints(prompt))
    assert constraints["predicates"]["real_face_refs"]


class DramaNativeApprovals(unittest.IsolatedAsyncioTestCase):
    def request(self, **kwargs):
        return StudioAgentRequest(prompt="Develop a microdrama series", workspace_id="workspace",
                                  project_id="project", conversation_id="drama", job_id="job",
                                  autonomous=True, **kwargs)

    async def run_graph(self, request, steps, gateway):
        from agent.deep_agent.runner import run_with_servers

        studio = _context_from_request(request)
        model = ScriptedModel(steps)
        await run_with_servers(request, studio, [gateway], model=model)
        assert not model._steps
        return studio

    async def outline_pause(self, gateway):
        from agent.deep_agent.runner import run_with_servers

        request = self.request()
        studio = _context_from_request(request)
        with self.assertRaises(StudioAgentApprovalRequired) as paused:
            await run_with_servers(request, studio, [gateway], model=ScriptedModel([
                call("review_drama_outline", {"outline": outline()}, "outline"),
            ]))
        gateway.call_tool.assert_not_awaited()
        return paused.exception, studio

    async def test_outline_rejection_never_reaches_the_gateway(self):
        gateway = Gateway()
        paused, studio = await self.outline_pause(gateway)
        approval = paused.approvals[0]
        assert approval.estimated_cost["total_cents"] == 0
        request = self.request(session_items=studio.session_items, resume_state=paused.state,
                               approval_decisions=[StudioApprovalDecision(call_id=approval.call_id, decision="reject")])
        restored = await self.run_graph(request, [final()], gateway)
        assert not restored.session_items[0]["drama_series"].get("outline_hash")
        gateway.call_tool.assert_not_awaited()

    async def test_autonomous_image_approval_survives_a_fresh_worker(self):
        from agent.deep_agent.runner import run_with_servers

        gateway = Gateway(tools=[Tool(name="OpenAI___generate_image", inputSchema={
            "type": "object", "properties": {"prompt": {"type": "string"}}, "required": ["prompt"],
        })])
        paused, studio = await self.outline_pause(gateway)
        approval = paused.approvals[0]
        request = self.request(session_items=studio.session_items, resume_state=paused.state,
                               approval_decisions=[StudioApprovalDecision(call_id=approval.call_id, decision="approve")])

        def prepare(messages, tools):
            response = json.loads(messages[-1].content)
            document = episode()
            document["outline_hash"] = response["outline_hash"]
            return call("validate_drama_episode", {"episode": document, "jobs": [image_job(document)]}, "validate")

        image = image_job(episode())
        restored = _context_from_request(request)
        with self.assertRaises(StudioAgentApprovalRequired) as paid_pause:
            await run_with_servers(request, restored, [gateway], model=ScriptedModel([
                prepare,
                call("call_media_tool", {"tool_name": image["tool_name"], "arguments": image["arguments"]}, "reference"),
            ]))
        gateway.call_tool.assert_not_awaited()
        approval = paid_pause.exception.approvals[0]
        assert approval.tool_name == "OpenAI___generate_image"
        request = self.request(session_items=json.loads(json.dumps(restored.session_items)),
                               resume_state=paid_pause.exception.state,
                               approval_decisions=[StudioApprovalDecision(call_id=approval.call_id, decision="approve")])
        await self.run_graph(request, [final()], gateway)
        gateway.call_tool.assert_awaited_once()

    async def test_unplanned_production_is_blocked_before_approval_or_spend(self):
        gateway = Gateway()
        studio = await self.run_graph(self.request(), [call("call_media_tool", {
            "tool_name": "Seedream___text_to_image", "arguments": {"prompt": "unplanned"},
        }, "unplanned"), final()], gateway)
        gateway.call_tool.assert_not_awaited()
        assert not studio.session_items[0]["drama_series"].get("outline_hash")

    async def test_autonomous_voice_and_music_each_pause_with_cost(self):
        from agent.deep_agent.runner import run_with_servers
        from providers.catalog import get_provider
        from providers.registry import load_committed_schemas

        for provider, verb, args, link in [
            ("elevenlabs", "text_to_speech_convert", {"voice_id": "authorized-voice", "text": "Come back."}, {"line_id": "l1"}),
            ("mureka", "generate_instrumental", {"prompt": "Quiet suspense"}, {}),
        ]:
            with self.subTest(provider=provider):
                spec = get_provider(provider)
                schema = next(row for row in load_committed_schemas(spec) if row["name"] == verb)
                name = spec.target_name + "___" + verb
                gateway = Gateway(tools=[Tool(name=name, description=schema["description"], inputSchema=schema["inputSchema"])])
                paused, studio = await self.outline_pause(gateway)
                request = self.request(session_items=studio.session_items, resume_state=paused.state,
                    approval_decisions=[StudioApprovalDecision(call_id=paused.approvals[0].call_id, decision="approve")])

                def prepare(messages, tools):
                    document = episode()
                    document["outline_hash"] = json.loads(messages[-1].content)["outline_hash"]
                    return call("validate_drama_episode", {"episode": document,
                        "jobs": [{"id": "audio1", "tool_name": name, "arguments": args, **link}]}, "plan-audio")

                with self.assertRaises(StudioAgentApprovalRequired) as paid:
                    await run_with_servers(request, _context_from_request(request), [gateway], model=ScriptedModel([
                        prepare, call("call_audio_tool", {"tool_name": name, "arguments": args}, "audio"),
                    ]))
                gateway.call_tool.assert_not_awaited()
                assert paid.exception.approvals[0].estimated_cost["total_cents"] is not None

    async def test_malformed_replacement_tool_arguments_clear_previous_jobs(self):
        gateway = Gateway()
        paused, studio = await self.outline_pause(gateway)
        request = self.request(session_items=studio.session_items, resume_state=paused.state,
            approval_decisions=[StudioApprovalDecision(call_id=paused.approvals[0].call_id, decision="approve")])

        def prepare(messages, tools):
            document = episode()
            document["outline_hash"] = json.loads(messages[-1].content)["outline_hash"]
            return call("validate_drama_episode", {"episode": document, "jobs": [image_job(document)]}, "valid")

        restored = await self.run_graph(request, [prepare,
            call("validate_drama_episode", {"episode": {}, "jobs": "bad"}, "invalid"), final()], gateway)
        assert restored.session_items[0]["drama_series"]["jobs"] == []
        gateway.call_tool.assert_not_awaited()

    async def test_explicitly_stopping_the_series_restores_other_workflows(self):
        gateway = Gateway()
        paused, studio = await self.outline_pause(gateway)
        request = self.request(session_items=studio.session_items, resume_state=paused.state,
            approval_decisions=[StudioApprovalDecision(call_id=paused.approvals[0].call_id, decision="approve")])
        approved = await self.run_graph(request, [final()], gateway)
        switched = self.request(session_items=approved.session_items).model_copy(update={
            "prompt": "Stop the series; make a product still with Seedream instead"})
        restored = await self.run_graph(switched, [call("call_media_tool", {
            "tool_name": "Seedream___text_to_image", "arguments": {"prompt": "New product still"},
        }, "new-task"), final()], gateway)
        assert restored.session_items[0]["drama_series"]["active"] is False
        assert restored.session_items[0]["drama_series"]["outline_hash"]
        gateway.call_tool.assert_awaited_once()

    async def test_parallel_duplicates_cannot_submit_one_planned_job_twice(self):
        from agent.deep_agent.runner import run_with_servers
        from langchain_core.messages import AIMessage

        gateway = Gateway(tools=[Tool(name="OpenAI___generate_image", inputSchema={
            "type": "object", "properties": {"prompt": {"type": "string"}}, "required": ["prompt"],
        })])

        async def delayed(*args, **kwargs):
            await asyncio.sleep(0.01)
            return {"status": "succeeded", "image_url": "https://example.test/reference.png"}

        gateway.call_tool.side_effect = delayed
        paused, studio = await self.outline_pause(gateway)
        request = self.request(session_items=studio.session_items, resume_state=paused.state,
            approval_decisions=[StudioApprovalDecision(call_id=paused.approvals[0].call_id, decision="approve")])

        def prepare(messages, tools):
            document = episode()
            document["outline_hash"] = json.loads(messages[-1].content)["outline_hash"]
            return call("validate_drama_episode", {"episode": document, "jobs": [image_job(document)]}, "valid")

        job = image_job(episode())
        duplicate = AIMessage(content="", tool_calls=[{"name": "call_media_tool",
            "args": {"tool_name": job["tool_name"], "arguments": job["arguments"]}, "id": f"duplicate-{i}"}
            for i in range(2)])
        restored = _context_from_request(request)
        with self.assertRaises(StudioAgentApprovalRequired) as paid:
            await run_with_servers(request, restored, [gateway], model=ScriptedModel([prepare, duplicate]))
        gateway.call_tool.assert_not_awaited()
        request = self.request(session_items=restored.session_items, resume_state=paid.exception.state,
            approval_decisions=[StudioApprovalDecision(call_id=row.call_id, decision="approve")
                                for row in paid.exception.approvals])
        await self.run_graph(request, [final()], gateway)
        gateway.call_tool.assert_awaited_once()


def test_submitted_jobs_cannot_be_repeated_by_a_new_tool_call():
    gate, document = prepared_gate()
    job = image_job(document)
    gate.claim_submission(job["tool_name"], job["arguments"])
    assert gate.blocker(job["tool_name"], job["arguments"])
    assert gate.prepare(document, [job])["ok"]
    assert gate.blocker(job["tool_name"], job["arguments"])


def test_outline_approval_is_a_free_neutral_customer_step():
    from agent.deep_agent.routing import estimate_cost
    from server.run_budget import is_client_safe, work_label

    assert estimate_cost("review_drama_outline", {"outline": outline()}).total_cents == 0
    label, detail = work_label("review_drama_outline")
    assert label == "Series outline"
    assert is_client_safe(detail)
