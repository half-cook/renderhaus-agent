from __future__ import annotations

import unittest

from pydantic import ValidationError

from agent.deep_agent.questions import AskUserInput, StudioQuestionRequest


def _q(**option):
    return {"question": "Crop or make a new shot?", "reason": "cost_difference",
            "options": [{"id": "a", "label": "Crop", **option}, {"id": "b", "label": "New shot"}]}


class QuestionOptionPriceTests(unittest.TestCase):
    def test_estimate_cents_round_trips_to_the_studio_payload(self) -> None:
        request = StudioQuestionRequest.model_validate({**_q(estimate_cents=173), "kind": "question", "call_id": "c1"})
        dumped = request.model_dump()
        self.assertEqual(dumped["options"][0]["estimate_cents"], 173)
        self.assertNotIn("estimate_cents", dumped["options"][1])

    def test_estimate_must_be_non_negative_integer_cents(self) -> None:
        for bad in (-1, 1.5, "173", 10_000_001):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                AskUserInput.model_validate(_q(estimate_cents=bad))

    def test_estimate_does_not_change_answer_validation(self) -> None:
        q = AskUserInput.model_validate(_q(estimate_cents=0))
        self.assertEqual(q.validate_answer({"kind": "choice", "option_id": "a"}).option_id, "a")


if __name__ == "__main__":
    unittest.main()
