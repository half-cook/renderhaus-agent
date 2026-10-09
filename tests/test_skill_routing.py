from __future__ import annotations

import json
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/skill_routing.json").read_text())


def gateway_names():
    from agent.hyperframes import HYPERFRAMES_TOOL
    from providers.catalog import PROVIDERS

    targets = {p.id: p.target_name for p in PROVIDERS} | {"fish_audio": "FishAudio"}
    return {HYPERFRAMES_TOOL.name} | {
        f"{targets[p.name.removesuffix('.tools.json')]}___{t['name']}"
        for p in (ROOT / "configs/gateway").glob("*.tools.json")
        for t in json.loads(p.read_text())
    }


class RoutingCases(unittest.TestCase):
    pass


def routing_case(case):
    def check(self):
        from agent.deep_agent.routing import resolve_alias, route_intent

        with patch.dict(os.environ, case.get("env", {})):
            route = route_intent(case["prompt"])
        skills = case.get("expected_routed_skill", case["expected_skill"]).split(" + ")
        aliases = case.get("expected_routed_alias", case["expected_tool"]).split(" then ")
        steps = list(route.steps) or [route]
        self.assertEqual([step.skill for step in steps[:len(skills)]], skills)
        self.assertEqual([step.alias for step in steps[:len(aliases)]], aliases)
        forbidden = {alias.strip() for alias in case.get("forbidden_tools", "").split(",") if alias.strip()}
        self.assertFalse(forbidden & {step.alias for step in steps})
        self.assertFalse({resolve_alias(alias) for alias in forbidden} - {None} & {step.tool for step in steps})
        if case.get("expected_output", "").startswith("assembled MP4"):
            self.assertEqual(route.expected_output, "assembled MP4")
            self.assertEqual(steps[-1].tool, "Remotion___render_timeline")
        status = case.get("expected_status", "ready")
        self.assertEqual(route.status, status, case.get("expected_failure"))
        if status == "ready":
            self.assertEqual(route.tool, case.get("expected_gateway_tool", resolve_alias(aliases[0])))
        else:
            self.assertIsNone(route.tool)
            self.assertIn(case["expected_reason"], route.reason)

    if case["skip_reason"]:
        return unittest.skip(case["skip_reason"])(check)
    if case.get("expected_failure"):
        return unittest.expectedFailure(check)
    return check


for index, case in enumerate(CASES):
    setattr(RoutingCases, f"test_{index:03d}_{case.get('test_id', case['suite']).replace('-', '_')}", routing_case(case))


class SkillContracts(unittest.TestCase):
    def test_every_gateway_reference_exists_and_dispatches_through_correct_role(self):
        from agent.deep_agent.routing import TOOL_MAP
        from agent.deep_agent.runner import DISPATCH_TARGETS
        from deepagents.middleware.skills import _parse_skill_metadata

        known = gateway_names()
        skills = list((ROOT / "agent/deep_agent/skills").glob("*/SKILL.md"))
        names = set()
        for path in skills:
            body = path.read_text()
            self.assertIsNotNone(_parse_skill_metadata(body, str(path), path.parent.name), path)
            front = yaml.safe_load(body.split("---", 2)[1])
            names.add(front["name"])
            self.assertEqual(front["name"], path.parent.name)
            self.assertIsInstance(front["description"], str)
            metadata = front["metadata"]
            dispatch = metadata["include_tools"].split()
            self.assertTrue(set(dispatch) <= DISPATCH_TARGETS.keys())
            aliases = metadata["routing_tools"].split()
            self.assertTrue(set(aliases) <= TOOL_MAP.keys(), (path, aliases))
            self.assertFalse(any(TOOL_MAP[alias]["status"] == "retired" for alias in aliases), path)
            gateway = set(metadata.get("gateway_tools", "").split())
            references = set(re.findall(r"\b[A-Za-z_]+___[a-z_]+\b", body))
            self.assertTrue(references <= gateway, (path, references - gateway))
            self.assertTrue(gateway <= known, (path, gateway - known))
            for name in gateway:
                self.assertTrue(
                    any(name.split("___")[0] in DISPATCH_TARGETS[d] for d in dispatch), name
                )
        self.assertEqual(len(names), 24)
        self.assertTrue(
            {
                "t2v", "i2v", "edit-v2v", "still-then-video", "image-gen", "named-provider",
                "audio-bed", "motion-graphics", "hyperframes", "continuity-qc", "resolve-handoff",
                "video-short", "product-images", "storyboard-shots", "audio", "final-assembly",
                "refinement", "conversational-edit", "act-two", "lipsync", "upscale",
                "lyrics-video", "product-demo-video", "whiteboard-explainer",
            } <= names
        )
        self.assertFalse(
            {"veo-t2v", "vidu-q4", "confidential-route", "fframes", "heygen-video", "kandinsky-t2v"} & names
        )

    def test_fixture_preserves_active_workbook_rows_and_explains_pending_dependencies(self):
        self.assertEqual(len(CASES), 129)
        self.assertEqual(sum(not c["skip_reason"] for c in CASES), 122)
        self.assertEqual(sum(bool(c["skip_reason"]) for c in CASES), 7)
        self.assertTrue(all(c.get("source_status") != "archived" for c in CASES))
        self.assertTrue(all("[project.confidential=true]" not in c["prompt"] for c in CASES))
        self.assertTrue(all(c["expected_skill"] != "confidential-route" for c in CASES))
        for case in CASES:
            if case["skip_reason"]:
                self.assertTrue(case["skip_reason"].startswith(("provider pending:", "licence blocked:", "semantics unverified:")))
                self.assertRegex(case["skip_reason"], r"\(feat/[a-z0-9-]+\)")
        imports = [c for c in CASES if c["prompt"] == "import editor FCPXML back"]
        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0]["skip_reason"], "provider pending: nle import (feat/nle-import-fcpxml)")

    def test_quality_default_and_unknown_requests_do_not_invent_tools(self):
        from agent.deep_agent.routing import route_intent

        video = route_intent("generate a video of a forest")
        self.assertEqual(video.alias, "wan3_t2v")
        self.assertEqual(video.tool, "Fal___generate_wan3_t2v")
        self.assertNotIn("interim default", video.disclosure)
        image = route_intent("animate an image")
        self.assertEqual(image.alias, "wan3_i2v")
        self.assertEqual(image.tool, "Fal___generate_wan3_i2v")
        self.assertEqual(route_intent("tell me a joke").status, "unrouted")

    def test_built_performance_specialists_never_dispatch_generation_tools(self):
        from agent.deep_agent.routing import route_intent

        for prompt, alias in [
            ("Act-Two performance capture onto character image", "runway_act_two"),
            ("make this character do my full-body dance", "kling_motion_control"),
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.alias, alias)
                self.assertEqual(route.status, "ready")
                self.assertEqual(route.tool, "Runway___act_two" if alias == "runway_act_two" else "Fal___kling_motion_control")
        for provider in ["MiniMax H3", "Hunyuan"]:
            route = route_intent(f"generate a video with {provider}")
            self.assertEqual(route.status, "blocked")
            self.assertIsNone(route.tool)

    def test_explicit_retired_provider_requests_do_not_dispatch_replacements(self):
        from agent.deep_agent.routing import route_intent

        for prompt in ["use Veo 3.1 for this shot", "make a HeyGen generative video clip"]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.status, "retired")
                self.assertIsNone(route.tool)
                self.assertIn("retired", route.reason)

    def test_explicit_runway_modality_is_preserved(self):
        from agent.deep_agent.routing import route_intent

        self.assertEqual(route_intent("Runway Gen-4 image of a product").tool, "Runway___text_to_image")
        self.assertEqual(route_intent("runway image to video").tool, "Runway___image_to_video")

    def test_pending_and_retired_aliases_are_not_gateway_tools(self):
        from agent.deep_agent.routing import TOOL_MAP

        known = gateway_names() | {None}
        for alias, entry in TOOL_MAP.items():
            with self.subTest(alias=alias):
                if entry["status"] in {"pending", "blocked", "retired"}:
                    self.assertIsNone(entry["gateway_tool"])
                    required = "provider pending" if entry["status"] == "pending" else entry["status"]
                    self.assertIn(required, entry["reason"])
                else:
                    self.assertIn(entry["gateway_tool"], known)
        required_aliases = {
            "wan3_t2v", "wan3_i2v", "wan3_r2v", "wan3_edit", "wan3_extend",
            "seedance25_t2v", "seedance25_i2v", "seedance25_r2v",
            "gpt_image25_t2i", "gpt_image25_edit", "recraft_v41_vector", "ideogram45_edit",
            "gemini_vlm_judge", "sync3_lipsync", "heygen_avatar_v", "runway_act_two",
            "kling_motion_control", "mureka_v95", "mureka_lyrics_video", "mirelo_v2a",
            "elevenlabs_sfx_v2", "eleven_v4_turbo", "topaz_upscale", "topaz_interpolate",
        }
        self.assertTrue(required_aliases <= TOOL_MAP.keys())
        self.assertNotIn("flux2_klein4b_t2i", TOOL_MAP)
