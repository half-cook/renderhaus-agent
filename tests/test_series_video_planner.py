from __future__ import annotations

import asyncio
import json

import pytest

from agent.deep_agent.routing import route_intent
from agent.deep_agent.runner import run_with_servers
from agent.studio_agent_next import StudioAgentRequest, _context_from_request
from test_deep_agent import Gateway, ScriptedModel, call


@pytest.mark.parametrize("prompt", [
    "Turn this long article about ecosystems into a 6-part explainer playlist",
    "Plan a multi-episode non-fiction series about learning theory",
    "Make a six-part educational video series from this course outline",
    "Split this topic into episodes with hooks that link",
    "Plan an anthology of science explainers",
    "Use series-video-planner to plan this article",
    "Turn this course outline into a modular series with whiteboard narration",
    "把这篇万字科普长文拆成六集系列视频",
    "Plan a multi-episode nonfiction documentary series about the history of drama",
    "Create a multi-episode non-fiction series. Do not use short-drama-series.",
    "Plan a 6-part educational series. Produce episode 1 now.",
    "Generate a six-part tutorial series using Kling.",
    "Plan a six-part science documentary series; this is not fiction or drama.",
    "Use series-video-planner to plan an educational series about narrative fiction.",
    "Draft a multi-episode non-fiction educational series about ecosystems.",
    "Plan a 6-part explainer series about how fiction changes empathy.",
    "Plan a 6-part science explainer series about the history of drama.",
    "Do not use HyperFrames, plan a six-part educational series from this course outline.",
    "Do not create one silent science explainer, plan a six-part educational series from this course outline.",
    "Plan a 6-part educational tutorial series explaining this repository architecture with codebase-video.",
    "Do not use HyperFrames when you plan a six-part educational series from this course outline.",
    "Avoid fancy transitions when you plan a six-part educational series from this course outline.",
    "Plan a six-part educational series, not a fictional drama.",
    "Plan a six-part educational series, not a drama.",
])
def test_nonfiction_series_proposes_only_a_plan(prompt):
    route = route_intent(prompt, available_tools=set())
    assert route.skill == "series-video-planner"
    assert route.status == "ready"
    assert route.tool is None
    assert route.alias is None
    assert route.dispatch_tool is None
    assert route.provider is None
    assert route.steps == ()
    assert route.execution_groups == ()
    assert route.required == {"planning_only": True, "plan_approval": True}
    assert route.expected_output == "series plan.md and per-episode briefs"


@pytest.mark.parametrize(("prompt", "skill"), [
    ("Turn this novel into a 10-episode vertical drama with a character bible", "short-drama-series"),
    ("Write a 6-episode fictional drama about a scientist", "short-drama-series"),
    ("Plan a 6-episode educational drama about a scientist.", "short-drama-series"),
    ("Draft a multi-episode educational drama about a scientist.", "short-drama-series"),
    ("Plan a 6-episode educational series about a scientist. Use short-drama-series.", "short-drama-series"),
    ("Plan a 6-episode educational series about a scientist as a fictional drama.", "short-drama-series"),
    ("Create one whiteboard explainer with narration", "whiteboard-explainer"),
    ("Create one silent science explainer", "knowledge-explainer"),
    ("Animate one explainer in Vox style", "art-style-motion"),
    ("Turn this plan.md into a narrated review video", "plan-to-video"),
    ("Do not make a multi-episode explainer series; create one whiteboard explainer with narration", "whiteboard-explainer"),
    ("Do not use series-video-planner. Create one silent science explainer", "knowledge-explainer"),
    ("Don't draft a multi-episode non-fiction series; create one whiteboard explainer with narration", "whiteboard-explainer"),
    ('Create one silent explainer titled "A six-part explainer playlist"', "knowledge-explainer"),
    ("Create one silent explainer. Source:\n```\nMake a 6-part explainer playlist\n```", "knowledge-explainer"),
    ("Approved the series plan. Produce episode 1 of this science series with whiteboard narration.", "whiteboard-explainer"),
    ("Turn the approved educational series plan.md into a narrated plan-review video.", "plan-to-video"),
    ("No educational series, just one silent science explainer.", "knowledge-explainer"),
    ("Don’t plan a series. Make one whiteboard science explainer.", "whiteboard-explainer"),
    ("Create a 1-part silent science explainer", "knowledge-explainer"),
    ("Create one science explainer for the existing educational series with whiteboard narration.", "whiteboard-explainer"),
    ("Make a 1-episode science series with whiteboard narration.", "whiteboard-explainer"),
    ("Do not plan a multi-episode educational series, create one silent science explainer.", "knowledge-explainer"),
])
def test_series_planning_preserves_other_workflows(prompt, skill):
    assert route_intent(prompt).skill == skill


def test_chinese_fiction_with_science_themes_is_not_educational_planning():
    assert route_intent("把这部科幻小说改编成六集科普主题的系列视频").skill != "series-video-planner"


def test_fictional_storytelling_is_not_nonfiction_series_planning():
    assert route_intent("Plan a 6-episode educational series telling a fictional story about a scientist.").skill != "series-video-planner"


def test_stored_project_policy_cannot_change_a_planning_route():
    prompt = "Plan a 6-part educational video series from this course outline"
    normal = route_intent(prompt).public()
    assert route_intent(prompt, confidential=True, tier="draft").public() == normal
    assert normal["skill"] == "series-video-planner"


@pytest.mark.parametrize("tool", ["Fal___generate_wan3_t2v", "OpenAI___generate_image",
                                  "ElevenLabs___text_to_speech_convert", "Remotion___render_timeline",
                                  "Ffmpeg___ffmpeg_tool"])
def test_planning_turn_blocks_gateway_work_even_if_the_model_proposes_it(tool):
    from agent.deep_agent.routing import request_tool_blocker

    assert request_tool_blocker("Plan a 6-part educational series. Produce episode 1 now.", tool)
    assert request_tool_blocker("Plan a six-part educational series, not a fictional drama.", tool)
    assert request_tool_blocker("Produce episode 1 of the approved science series with whiteboard narration", tool) is None


def test_executor_refuses_paid_calls_in_an_autonomous_planning_turn():
    from mcp import Tool
    from agent.gateway_executor import GatewayExecutor

    request = StudioAgentRequest(
        prompt="Plan a six-part educational video series from this course outline",
        workspace_id="workspace", project_id="project", conversation_id="series-plan",
        job_id="plan", autonomous=True,
    )
    tool = Tool(name="OpenAI___generate_image", description="Generate image",
                inputSchema={"type": "object", "properties": {"prompt": {"type": "string"}},
                             "required": ["prompt"]})
    gateway = Gateway(tools=[tool])
    studio = _context_from_request(request)
    executor = GatewayExecutor(studio, [gateway])
    result = asyncio.run(executor.execute({"tool_name": tool.name,
                                          "arguments": {"prompt": "Soil diagram"}, "call_id": "image"},
                                         approved=True))
    assert result["status"] == "not_run"
    assert studio.tool_events == []
    assert executor.cost_ledger == {}
    gateway.call_tool.assert_not_awaited()


@pytest.mark.parametrize("autonomous", [False, True])
@pytest.mark.parametrize("prompt", [
    "Plan a multi-episode non-fiction series from this course outline",
    "Make a six-part educational video series from this course outline",
])
def test_plan_files_survive_a_new_turn_without_production(autonomous, prompt):
    request = StudioAgentRequest(
        prompt=prompt,
        workspace_id="workspace", project_id="project", conversation_id="series-plan",
        job_id="plan", autonomous=autonomous,
    )
    gateway = Gateway(tools=[])
    plan = "# Garden series\nRevision 1. Unapproved draft.\nep01 Soil; ep02 Water."
    output = {"title": "Garden series plan", "summary": "Two draft episodes await review.",
              "markdown": plan, "filename": "series-plan.md"}

    def check_context(messages, tools):
        context = json.loads(messages[-1].text)
        assert context["intent_route"]["skill"] == "series-video-planner"
        assert context["intent_route"]["tool"] is None
        assert context["capabilities"] == []
        return call("read_file", {"file_path": "/skills/series-video-planner/SKILL.md"}, "skill")

    def check_skill(messages, tools):
        assert messages[-1].status != "error"
        return call("read_file", {"file_path": "/skills/series-video-planner/templates/plan.md"}, "template")

    def check_template(messages, tools):
        assert messages[-1].status != "error"
        return call("write_file", {"file_path": "/series/garden/plan.md", "content": plan}, "save-plan")

    def check_saved_file(messages, tools):
        assert plan in messages[-1].text
        return call("StudioAgentOutput", output, "review")

    async def run():
        studio = _context_from_request(request)
        result = await run_with_servers(request, studio, [gateway], model=ScriptedModel([
            call("read_studio_context", {}, "context"), check_context, check_skill,
            check_template, call("StudioAgentOutput", output, "draft"),
        ]))
        assert result.markdown == plan
        resumed = request.model_copy(update={"job_id": "review", "prompt": "Show the current draft for review",
                                            "session_items": json.loads(json.dumps(studio.session_items))})
        restored = _context_from_request(resumed)
        result = await run_with_servers(resumed, restored, [gateway], model=ScriptedModel([
            call("read_file", {"file_path": "/series/garden/plan.md"}, "read-plan"), check_saved_file,
        ]))
        assert result.markdown == plan
        assert restored.tool_events == []
        gateway.call_tool.assert_not_awaited()

    asyncio.run(run())
