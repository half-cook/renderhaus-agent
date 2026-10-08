from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "tests/fixtures/skill_routing.json").read_text())


def gateway_names():
    from providers.catalog import PROVIDERS

    targets = {p.id: p.target_name for p in PROVIDERS} | {"fish_audio": "FishAudio"}
    return {
        f"{targets[p.name.removesuffix('.tools.json')]}___{t['name']}"
        for p in (ROOT / "configs/gateway").glob("*.tools.json")
        for t in json.loads(p.read_text())
    }


class RoutingCases(unittest.TestCase):
    pass


def routing_case(case):
    def check(self):
        from agent.deep_agent.routing import route_intent, TOOL_MAP

        route = route_intent(case["prompt"])
        self.assertEqual(route.skill, case["expected_skill"])
        self.assertEqual(route.tool, TOOL_MAP[case["expected_tool"]]["gateway_tool"])
        self.assertEqual(route.status, "ready")

    if case["skip_reason"]:
        return unittest.skip(case["skip_reason"])(check)
    return check


for index, case in enumerate(CASES):
    setattr(RoutingCases, f"test_{index:02d}_{case['suite'].replace('-', '_')}", routing_case(case))


class SkillContracts(unittest.TestCase):
    def test_every_gateway_reference_exists_and_dispatches_through_correct_role(self):
        from agent.deep_agent.runner import DISPATCH_TARGETS

        known = gateway_names()
        skills = list((ROOT / "agent/deep_agent/skills").glob("*/SKILL.md"))
        names = set()
        for path in skills:
            from deepagents.middleware.skills import _parse_skill_metadata

            body = path.read_text()
            parsed = _parse_skill_metadata(body, str(path), path.parent.name)
            self.assertIsNotNone(parsed, path)
            front = yaml.safe_load(body.split("---", 2)[1])
            names.add(front["name"])
            self.assertEqual(front["name"], path.parent.name)
            self.assertIsInstance(front["description"], str)
            dispatch = front["metadata"]["include_tools"].split()
            self.assertTrue(set(dispatch) <= DISPATCH_TARGETS.keys())
            gateway = set(front["metadata"].get("gateway_tools", "").split())
            references = set(re.findall(r"\b[A-Za-z_]+___[a-z_]+\b", body))
            self.assertTrue(references <= gateway, (path, references - gateway))
            self.assertTrue(gateway <= known, (path, gateway - known))
            for name in gateway:
                self.assertTrue(
                    any(name.split("___")[0] in DISPATCH_TARGETS[d] for d in dispatch), name
                )
        self.assertTrue(
            {
                "t2v",
                "i2v",
                "edit-v2v",
                "still-then-video",
                "audio-bed",
                "motion-graphics",
                "continuity-qc",
                "resolve-handoff",
                "video-short",
                "product-images",
                "storyboard-shots",
                "audio",
                "final-assembly",
                "refinement",
            }
            <= names
        )
        self.assertFalse({"veo-t2v", "act-two", "lipsync", "upscale"} & names)

    def test_fixture_retains_all_rows_and_explicit_skips(self):
        self.assertEqual(len(CASES), 55)
        self.assertEqual(sum(not c["skip_reason"] for c in CASES), 20)
        self.assertEqual(sum(bool(c["skip_reason"]) for c in CASES), 35)

    def test_wan_is_default_and_unknown_requests_do_not_invent_tools(self):
        from agent.deep_agent.routing import route_intent

        self.assertEqual(route_intent("generate a video of a forest").tool, "Fal___text_to_video")
        self.assertEqual(route_intent("animate an image").tool, "Fal___image_to_video")
        self.assertEqual(route_intent("tell me a joke").status, "unrouted")

    def test_pending_provider_never_falls_back_to_a_paid_alternative(self):
        from agent.deep_agent.routing import route_intent

        self.assertEqual(
            route_intent("generate with Veo 3.1 native audio dialogue").status, "pending"
        )
        self.assertIsNone(route_intent("generate with Veo 3.1 native audio dialogue").tool)

    def test_explicit_runway_modality_is_preserved(self):
        from agent.deep_agent.routing import route_intent

        self.assertEqual(
            route_intent("Runway Gen-4 image of a product").tool, "Runway___text_to_image"
        )
        self.assertEqual(route_intent("runway image to video").tool, "Runway___image_to_video")

    def test_every_seed_alias_is_mapped_or_explicitly_pending(self):
        from agent.deep_agent.routing import TOOL_MAP

        known = gateway_names() | {None}
        for entry in TOOL_MAP.values():
            if entry["status"] == "pending":
                self.assertIsNone(entry["gateway_tool"])
                self.assertIn("provider pending", entry["reason"])
            else:
                self.assertTrue(entry["gateway_tool"] in known)
        self.assertEqual(
            sum(
                k in TOOL_MAP
                for k in [
                    "kling_t2v",
                    "kling_i2v",
                    "runway_gen45_t2v",
                    "runway_aleph_edit",
                    "runway_act_two",
                    "wan_t2v",
                    "wan_i2v",
                    "wan_vace_edit",
                    "luma_ray3_t2v",
                    "luma_ray3_modify",
                    "hedra_character3",
                    "liveportrait_lipsync",
                    "infinitetalk_lipsync",
                    "seedvr2_upscale",
                    "rife_interpolate",
                    "topaz_upscale",
                    "seedance_t2v",
                    "seedance_i2v",
                    "seedream_t2i",
                    "elevenlabs_tts",
                    "fish_audio_tts",
                    "mmaudio_sfx",
                    "ace_step_music",
                    "remotion_render",
                    "veo_t2v",
                    "veo_i2v",
                    "veo_extend",
                    "ideogram_t2i",
                    "recraft_t2i",
                    "otio_export",
                    "fcpxml_export",
                    "edl_export",
                    "media_package",
                    "local_qc",
                ]
            ),
            34,
        )
