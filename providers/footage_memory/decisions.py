"""Deterministic footage-memory routing, independent of backend selection."""

from __future__ import annotations

import math
from typing import Literal


def recommendation(
    duration_s: float,
    question_count: int = 1,
    is_folder: bool = False,
    memory_exists: bool = False,
) -> Literal["query", "build", "watch"]:
    if (
        isinstance(duration_s, bool)
        or not isinstance(duration_s, (int, float))
        or not math.isfinite(duration_s)
        or duration_s < 0
    ):
        raise ValueError("Footage duration must be a finite nonnegative number.")
    if type(question_count) is not int or question_count < 1:
        raise ValueError("Question count must be a positive integer.")
    if type(is_folder) is not bool or type(memory_exists) is not bool:
        raise ValueError("Folder and memory indicators must be booleans.")
    if memory_exists:
        return "query"
    if is_folder or question_count > 1 or duration_s >= 600:
        return "build"
    return "watch"


route_recommendation = recommendation
