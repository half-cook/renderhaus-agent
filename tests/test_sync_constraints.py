from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.deep_agent import routing
from test_sync_wiring import ARGS


class SyncIntentConstraintsTests(unittest.TestCase):
    def test_new_generated_talking_shots_never_select_existing_footage_tool(self):
        with patch.object(routing, "policy_blocker", return_value=None), \
                patch.object(routing, "estimate_cost", return_value=routing.CostEstimate(0)):
            for prompt, alias in (
                ("create a talking avatar video using a cartoon image", "seedance25_i2v"),
                ("generate a talking head video", "seedance25_t2v"),
                ("generate a cartoon talking head video", "seedance25_t2v"),
                ("talking head from a cartoon photo with narration", "seedance25_i2v"),
            ):
                with self.subTest(prompt=prompt):
                    self.assertEqual(routing.route_intent(prompt).alias, alias)

    def test_sync_quote_keeps_measured_inputs_when_output_length_is_requested(self):
        with patch.object(routing, "policy_blocker", return_value=None), \
                patch.object(routing, "estimate_cost", return_value=routing.CostEstimate(0)) as quote:
            route = routing.route_intent("lipsync this 8 second interview clip", arguments=ARGS)
        self.assertEqual(route.alias, "sync3_lipsync")
        measured = quote.call_args.args[1]
        self.assertEqual(measured["source_duration_seconds"], 10.0)
        self.assertEqual(measured["audio_duration_seconds"], 8.0)
        self.assertNotIn("duration_seconds", measured)


if __name__ == "__main__":
    unittest.main()
