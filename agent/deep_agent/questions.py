from __future__ import annotations

from typing import Annotated, Literal

from langchain.tools import tool
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class QuestionOption(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)
    # Customer price for choosing this option, integer cents, fee-inclusive (the same
    # units as the run budget snapshot). Shown as an estimate; it authorizes nothing.
    estimate_cents: int | None = Field(default=None, ge=0, le=1_000_000, strict=True, exclude_if=lambda value: value is None)


class ChoiceAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["choice"]
    option_id: str = Field(min_length=1, max_length=80)


class TextAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["text"]
    text: str = Field(min_length=1, max_length=2_000)


QuestionAnswer = Annotated[ChoiceAnswer | TextAnswer, Field(discriminator="kind")]


class AskUserInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=1_000)
    reason: Literal["cost_difference", "irreversible_outcome"]
    options: list[QuestionOption] = Field(default_factory=list, max_length=6)
    allow_free_text: bool = True

    @model_validator(mode="after")
    def valid_options(self):
        from server.run_budget import is_client_safe

        copy = [self.question, *(option.label for option in self.options),
                *(option.description for option in self.options)]
        if any(not is_client_safe(text) for text in copy):
            raise ValueError('Describe the outcomes without internal names or billing terms.')
        if not self.options and not self.allow_free_text:
            raise ValueError("A question needs an option or a free-text answer.")
        if len({option.id for option in self.options}) != len(self.options):
            raise ValueError("Question option IDs must be unique.")
        return self

    def validate_answer(self, value: object) -> QuestionAnswer:
        answer = TypeAdapter(QuestionAnswer).validate_python(value)
        if isinstance(answer, ChoiceAnswer) and answer.option_id not in {option.id for option in self.options}:
            raise ValueError("Choose one of this question's options.")
        if isinstance(answer, TextAnswer) and not self.allow_free_text:
            raise ValueError("This question requires one of its options.")
        return answer


class StudioQuestionRequest(AskUserInput):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    kind: Literal["question"] = "question"
    call_id: str = Field(min_length=1, max_length=200)


class StudioQuestionAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["question"] = "question"
    call_id: str = Field(min_length=1, max_length=200)
    answer: QuestionAnswer


@tool(args_schema=AskUserInput)
async def ask_user(question: str, reason: str, options: list[QuestionOption] | None = None,
                   allow_free_text: bool = True) -> dict:
    """Clarify ambiguity only when alternatives differ in cost or irreversible outcomes.

    Make routine creative and implementation choices yourself. This question does not
    authorize spending or change the run cap. Offer clear options or allow a text answer.
    Describe outcomes without naming providers, models or platform fees.
    When options differ in cost, give each option estimate_cents: the customer price in
    integer cents from your budget snapshot and step estimates, all fees included.
    """
    payload = AskUserInput(question=question, reason=reason, options=options or [], allow_free_text=allow_free_text)
    response = interrupt({"kind": "question", **payload.model_dump()})
    answer = payload.validate_answer(response)
    return {"status": "answered", "answer": answer.model_dump()}
