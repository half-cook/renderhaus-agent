"""Strict, bounded arguments for a network-free recipe lookup."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from providers.shot_recipes.library import CATEGORIES


class SearchRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)

    mode: Literal['search', 'validate_storyboard'] = 'search'
    query: Annotated[str, Field(max_length=512)] | None = None
    card_id: Annotated[str, Field(max_length=100, pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$')] | None = None
    category: str | None = None
    max_duration_s: Annotated[float, Field(gt=0, le=600)] | None = None
    energy: Literal['low', 'medium', 'high'] | None = None
    limit: Annotated[int, Field(ge=1, le=20)] = 8
    storyboard: dict | None = None

    @model_validator(mode='after')
    def check_mode(self) -> SearchRequest:
        if self.category is not None and self.category not in CATEGORIES:
            raise ValueError('Unknown shot category.')
        if self.mode == 'validate_storyboard':
            if self.storyboard is None:
                raise ValueError('Storyboard validation requires a storyboard object.')
            from providers.shot_recipes.storyboard import parse_storyboard

            parse_storyboard(self.storyboard)
            if any(value is not None for value in (self.query, self.card_id, self.category,
                                                   self.max_duration_s, self.energy)):
                raise ValueError('Search filters cannot be used in storyboard validation mode.')
        elif self.storyboard is not None:
            raise ValueError('Storyboard requires validate_storyboard mode.')
        return self


def request_for(arguments: dict) -> SearchRequest:
    try:
        return SearchRequest.model_validate(arguments)
    except ValidationError as exc:
        errors = ['.'.join(str(p) for p in error['loc']) + ': ' + error['msg']
                  for error in exc.errors(include_input=False, include_url=False)]
        raise ValueError('; '.join(errors)) from None


def validate_arguments(arguments: dict) -> None:
    request_for(arguments)


FIELD_DESCRIPTIONS = {
    'mode': 'search by default; validate_storyboard checks timing and returns an assembly plan without rendering.',
    'query': 'Optional lexical query, at most 512 characters. English aliases include ink press, crane reveal and odometer.',
    'card_id': 'Exact indexed lowercase slug, at most 100 characters. Wins over the query and all filters. No paths.',
    'category': 'Optional category: ' + ', '.join(CATEGORIES) + '.',
    'max_duration_s': 'Optional positive maximum recipe duration, at most 600 seconds.',
    'energy': 'Optional low, medium or high energy filter.',
    'limit': 'Integer result limit 1-20. Default 8.',
    'storyboard': 'Required only in validate_storyboard mode. Bounded beats, declared fps, supplied beat grid and separate sfx/music/vo stems. This validates a plan, never media.',
}
