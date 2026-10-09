import json
import logging
import unittest

from langchain_core.messages import AIMessage

from agent.deep_agent.usage import ModelUsage


class ModelUsageTests(unittest.TestCase):
    def test_cache_inclusive_prompt_pricing_and_duplicate_updates(self):
        meter = ModelUsage("scope")
        for index, total in enumerate([100_000, 100_001]):
            message = AIMessage(content="", id=str(index), response_metadata={"model_name": "claude-haiku-5-5"},
                                usage_metadata={"input_tokens": total, "output_tokens": 100,
                                                "total_tokens": total + 100,
                                                "input_token_details": {"cache_read": total - 20, "cache_creation": 10}})
            meter.record(message)
            meter.record(message)
        with self.assertLogs("usage-test", level="INFO") as observed:
            meter.publish(logging.getLogger("usage-test"))
        report = json.loads(observed.records[0].message)
        self.assertEqual(report["event"], "agent_model_usage")
        self.assertEqual(report["calls"], 2)
        self.assertEqual(report["input_tokens"], 200_001)
        expected = ((10 * .10 + 10 * .125 + 99_980 * .01 + 100 * .50)
                    + (10 * .50 + 10 * .625 + 99_981 * .05 + 100 * 2.50)) / 1_000_000
        self.assertAlmostEqual(report["estimated_cost_usd"], expected, places=9)
        self.assertEqual(report["run_scope"], "scope")

    def test_unknown_model_cost_is_unknown(self):
        meter = ModelUsage("scope")
        meter.record(AIMessage(content="", id="unknown", response_metadata={"model_name": "other-model"},
                               usage_metadata={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}))
        with self.assertLogs("usage-test", level="INFO") as observed:
            meter.publish(logging.getLogger("usage-test"))
        report = json.loads(observed.records[0].message)
        self.assertEqual(report["unknown_cost_calls"], 1)
        self.assertIsNone(report["estimated_cost_usd"])
