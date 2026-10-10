"""Offline routing checks for retrieval of existing footage."""
from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from agent.deep_agent.routing import estimate_cost, route_intent, tool_parts


class FootageRoutingTests(unittest.TestCase):
    def aliases(self, prompt, **arguments):
        route = route_intent(prompt, arguments=arguments or None)
        self.assertEqual(route.skill, "footage-memory")
        self.assertEqual(route.status, "ready")
        steps = route.steps or (route,)
        self.assertTrue(all(step.dispatch_tool == "call_editor_tool" for step in steps))
        return route, [step.alias for step in steps]

    def test_long_rushes_verify_between_retrieval_and_cutting(self):
        route, aliases = self.aliases(
            "Here are 3 hours of interview rushes. Find every moment where the guest talks about her childhood and give me the clips"
        )
        self.assertEqual(aliases, ["footage_memory_status", "footage_memory_build", "footage_memory_query",
                                   "footage_watch_answer", "footage_clip_extract"])
        self.assertEqual(route.required["recommendation"], "build")
        self.assertTrue(route.required["verify_before_extract"])
        self.assertEqual(route.execution_groups, tuple((alias,) for alias in aliases))

    def test_short_clip_one_question_watches_once(self):
        _, aliases = self.aliases("In this 4-minute clip, what's written on the whiteboard behind the speaker?")
        self.assertEqual(aliases, ["footage_watch_answer"])

    def test_folders_and_several_questions_build(self):
        for prompt in ["Find every moment with a red car in this folder of clips",
                       "Index this folder of clips",
                       "The same footage, several questions: who laughs and when?",
                       "I have several questions about the same footage: what is written, who speaks, and when does she laugh?"]:
            with self.subTest(prompt=prompt):
                route, aliases = self.aliases(prompt)
                self.assertEqual(route.required["recommendation"], "build")
                self.assertIn("footage_memory_build", aliases)

    def test_existing_memory_wins_even_for_short_single_question(self):
        route, aliases = self.aliases("Find the moment where she laughs in this 4-minute clip", memory_exists=True)
        self.assertEqual(route.required["recommendation"], "query")
        self.assertEqual(aliases, ["footage_memory_query"])

    def test_unknown_duration_checks_status_before_choosing(self):
        route, aliases = self.aliases("Find the moment where she laughs in this footage")
        self.assertEqual(aliases, ["footage_memory_status"])
        self.assertTrue(route.required["choose_after_status"])

    def test_explicit_duration_and_question_count_use_shared_rule(self):
        route, aliases = self.aliases("Find the moment where she laughs in this footage",
                                      duration_s=599, question_count=2)
        self.assertEqual(route.required["recommendation"], "build")
        self.assertIn("footage_memory_build", aliases)

    def test_dialogue_cleanup_and_continuity_keep_their_existing_routes(self):
        for prompt, skill in [
            ("Cut the ums and long pauses out of this talking-head take", "conversational-edit"),
            ("Remove filler words from this transcript", "conversational-edit"),
            ("Check continuity across these clips", "continuity-qc"),
            ("Find the moment where continuity breaks across these shots", "continuity-qc"),
        ]:
            with self.subTest(prompt=prompt):
                route = route_intent(prompt)
                self.assertEqual(route.skill, skill)
                self.assertFalse(any((step.alias or "").startswith("footage_") for step in (route.steps or (route,))))

    def test_generation_request_does_not_build_memory(self):
        route = route_intent("Generate a clip of a guest talking about her childhood")
        self.assertNotEqual(route.skill, "footage-memory")

    def test_unavailable_verification_blocks_a_clip_plan(self):
        tools = {"FootageMemory___" + name for name in ["footage_memory_status", "footage_memory_build",
                                                       "footage_memory_query", "footage_clip_extract"]}
        route = route_intent("Find every moment where she laughs in this 3-hour footage and give me the clips",
                             available_tools=tools)
        self.assertEqual(route.status, "blocked")
        self.assertIsNone(route.tool)

    def test_target_and_gate_are_explicit_without_promoting_a_backend(self):
        self.assertEqual(tool_parts("FootageMemory___footage_memory_query"), ("footage_memory", "footage_memory_query"))
        policy = json.loads((Path(__file__).parents[1] / "agent/deep_agent/routing_policy.json").read_text())
        gate = policy["footage_memory_ab"]
        self.assertIsNone(gate["promoted_default"])
        self.assertEqual(gate["status"], "candidate-with-gate")
        self.assertIn("precision", gate["gate"])
        for alias in ["footage_memory_status", "footage_memory_build", "footage_memory_query",
                      "footage_watch_answer", "footage_clip_extract"]:
            self.assertFalse(policy["tools"][alias]["training_eligible"])

    def test_estimate_disclosure_keeps_backend_and_fee_out_of_customer_text(self):
        quote = {"backend_calls": 20, "estimate_cents": 40,
                 "estimate_description": "Estimated 20 analysis calls, $0.40 USD; configured estimate, UNVERIFIED."}
        with patch("server.billing_rates.footage_memory_estimate", return_value=quote, create=True):
            for alias in ["footage_memory_build", "footage_watch_answer", "footage_memory_status",
                          "footage_memory_query", "footage_clip_extract"]:
                result = estimate_cost("FootageMemory___" + alias, {})
                self.assertNotRegex(result.description.lower(), r"gemini|qwen|google|alibaba|fee")
            self.assertEqual(estimate_cost("FootageMemory___footage_memory_build", {}).total_cents, 40)


if __name__ == "__main__":
    unittest.main()
